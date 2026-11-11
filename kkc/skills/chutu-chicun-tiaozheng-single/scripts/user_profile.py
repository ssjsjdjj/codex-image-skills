#!/usr/bin/env python3
"""Windows 账号独立的反馈、待审草案、版本审批和手动回退。仅使用标准库。"""
import argparse
import contextlib
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from functools import wraps

MANAGED = ("settings.json", "personal_prompt.md", "renderer.py")
DEFAULT_KEYS = {"fit", "bg", "format", "on_conflict", "allow_padding", "allow_stretch", "focus",
                "position", "offset", "zoom", "subject_fill", "save_recipe", "max_bytes"}


def now():
    return datetime.now(timezone.utc).isoformat()


def identifier(prefix):
    return prefix + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:10]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _match_profile_sid(profile_path, entries):
    """Resolve the intended Windows profile, not Codex's sandbox process token."""
    if not profile_path:
        raise ValueError("缺少USERPROFILE，不能确定当前Windows账号")
    def normalized(value):
        return os.path.normcase(str(Path(os.path.expandvars(value)).resolve())).rstrip("\\/")
    wanted = normalized(profile_path)
    matches = {sid for sid, path in entries
               if re.fullmatch(r"S-1-(?:\d+-)+\d+", sid) and normalized(path) == wanted}
    if len(matches) != 1:
        raise ValueError("无法唯一确定USERPROFILE对应的Windows账号SID；请检查ProfileList，不得改写他人owner.json")
    return next(iter(matches))


def _profile_sid(profile_path):
    import winreg
    entries = []
    try:
        access = winreg.KEY_READ | winreg.KEY_WOW64_64KEY
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList", 0, access) as root:
            index = 0
            while True:
                try:
                    sid = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                if not re.fullmatch(r"S-1-(?:\d+-)+\d+", sid):
                    continue
                try:
                    with winreg.OpenKey(root, sid) as key:
                        path, _ = winreg.QueryValueEx(key, "ProfileImagePath")
                    entries.append((sid, path))
                except OSError:
                    continue
    except OSError as error:
        raise ValueError("无法读取Windows ProfileList，不能确定本账号归属") from error
    return _match_profile_sid(profile_path, entries)


def owner_id():
    if os.name == "nt":
        return _profile_sid(os.environ.get("USERPROFILE"))
    return "uid:" + str(os.getuid())


def default_root():
    if os.name == "nt":
        location = os.environ.get("LOCALAPPDATA")
        if not location:
            raise ValueError("缺少 LOCALAPPDATA，不能猜测其他用户的配置目录")
        return Path(location) / "ChutuResizeSingle"
    return Path.home() / ".local/share/chutu-resize"


def snapshot_digest(folder):
    folder = Path(folder)
    digest = hashlib.sha256()
    for name in MANAGED:
        path = folder / name
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"版本缺少普通文件：{name}")
        digest.update((name + "\0" + file_hash(path) + "\n").encode("utf-8"))
    return digest.hexdigest()


def merge(base, patch):
    result = json.loads(json.dumps(base))
    for key, value in patch.items():
        result[key] = merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def validate_settings(settings):
    required = {"schema", "defaults", "preset_defaults", "feedback", "versions", "runtime"}
    if set(settings) != required or settings["schema"] != 1:
        raise ValueError("个人配置结构或 schema 不正确")
    if set(settings["defaults"]) - DEFAULT_KEYS:
        raise ValueError("defaults 中有不支持的参数")
    if settings["defaults"].get("fit") not in ("cover", "contain", "subject", "stretch"):
        raise ValueError("个人配置需要明确默认 fit")
    for key in ("allow_padding", "allow_stretch"):
        if not isinstance(settings["defaults"].get(key), bool):
            raise ValueError(f"个人配置需要布尔参数 {key}")
    if settings["defaults"].get("fit") == "stretch" and not settings["defaults"]["allow_stretch"]:
        raise ValueError("默认拉伸与禁止拉伸的规则相冲突")
    if 'max_bytes' in settings['defaults'] and (type(settings['defaults']['max_bytes']) is not int or not 1<=settings['defaults']['max_bytes']<=500000):
        raise ValueError('默认图片字节上限必须为1至500000')
    if not isinstance(settings["preset_defaults"], dict):
        raise ValueError("preset_defaults 必须为对象")
    for name, values in settings["preset_defaults"].items():
        if name not in ("product", "full_body", "half_body", "detail") or not isinstance(values, dict) or set(values) - DEFAULT_KEYS:
            raise ValueError("不支持的个人预设参数")
    feedback = settings["feedback"]
    if feedback.get("mode") not in ("per_batch", "on_request", "manual_record"):
        raise ValueError("不支持的反馈收集方式")
    if feedback.get("storage") != "text_params_paths":
        raise ValueError("当前版本仅支持文字、参数和图片路径，不保存原图或缩略图")
    if type(feedback.get("repeat_threshold")) is not int or not 1 <= feedback["repeat_threshold"] <= 50:
        raise ValueError("反馈重复阈值必须为 1~50 的整数")
    if not feedback.get("long_term_immediate") is True:
        raise ValueError("当前流程要求明确长期偏好立即提出草案")
    if settings["runtime"].get("rollback") != "manual":
        raise ValueError("当前流程要求运行异常先报告，由用户决定回退")
    if type(settings["versions"].get("keep")) is not int or not 1 <= settings["versions"]["keep"] <= 100:
        raise ValueError("版本保留数量必须为 1~100 的整数")
    return settings


def effective_job(settings, job):
    result = dict(settings["defaults"])
    preset = job.get("preset")
    if preset:
        if "fit" not in job:
            result.pop("fit", None)
        result.update(settings["preset_defaults"].get(preset, {}))
    result.update(job)
    return result


def copy_snapshot(source, destination):
    source, destination = Path(source), Path(destination)
    snapshot_digest(source)
    destination.mkdir(parents=True, exist_ok=True)
    for name in MANAGED:
        shutil.copyfile(source / name, destination / name)


def safe_remove_version(path, parent):
    # 只删除明确版本目录内的本应用快照，拒绝链接和越界路径。
    path, parent = Path(path), Path(parent).resolve()
    if path.is_symlink() or path.resolve().parent != parent or not path.name.startswith("v-"):
        raise ValueError("拒绝清理版本目录外的路径")
    shutil.rmtree(path)


def locked(function):
    @wraps(function)
    def call(self, *args, **kwargs):
        with self.lock():
            return function(self, *args, **kwargs)
    return call


class Store:
    def __init__(self, root=None):
        self.root = Path(root if root is not None else default_root()).resolve()
        self._lock_depth = 0

    @contextlib.contextmanager
    def lock(self):
        self.owned()
        if self._lock_depth:
            self._lock_depth += 1
            try:
                yield
            finally:
                self._lock_depth -= 1
            return
        with (self.root / ".mutation.lock").open("a+b") as stream:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            deadline = time.monotonic() + 5
            acquired = False
            while not acquired:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ValueError("另一个任务正在更新本账号配置，请稍后重试") from None
                    time.sleep(.05)
            self._lock_depth = 1
            try:
                yield
            finally:
                self._lock_depth = 0
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)

    def owned(self, create=False):
        marker = self.root / "owner.json"
        if marker.exists():
            if read_json(marker).get("owner_id") != owner_id():
                raise ValueError("该配置目录属于另一账号，不能读取或修改其个人习惯")
        elif create:
            if self.root.exists() and any(self.root.iterdir()):
                raise ValueError("目标目录已有未标记内容，不能接管")
            write_json(marker, {"schema": 1, "owner_id": owner_id(), "created_at": now()})
        else:
            raise ValueError("当前账号尚未初始化，请先确认初始配置")

    def active(self):
        self.owned()
        current = read_json(self.root / "current.json")
        revision = current["revision"]
        if not re.fullmatch(r"v-[A-Za-z0-9-]+", revision):
            raise ValueError("非法版本标识")
        folder = self.root / "versions" / revision
        if snapshot_digest(folder) != current["digest"]:
            raise ValueError("正式版本文件发生未审批变更，请先处理异常")
        return revision, folder, validate_settings(read_json(folder / "settings.json"))

    def status(self):
        if not (self.root / "owner.json").exists():
            return {"initialized": False, "root": str(self.root), "owner_id": owner_id()}
        revision, folder, settings = self.active()
        return {"initialized": True, "root": str(self.root), "owner_id": owner_id(), "revision": revision,
                "digest": snapshot_digest(folder), "settings": settings, "personal_prompt": str(folder / "personal_prompt.md"),
                "renderer": str(folder / "renderer.py"), "versions": self.version_list()}

    def append(self, name, event):
        self.owned()
        with (self.root / name).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")

    def events(self, name):
        self.owned()
        path = self.root / name
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []

    def version_list(self):
        self.owned()
        parent = self.root / "versions"
        result = []
        for folder in parent.glob("v-*"):
            metadata = folder / "version.json"
            if metadata.is_file():
                result.append(read_json(metadata))
        return sorted(result, key=lambda value: value["created_at"], reverse=True)

    @locked
    def commit(self, snapshot, confirmation, proposal_id=None):
        if not confirmation or not confirmation.strip():
            raise ValueError("必须记录用户实际确认的原文，不能自动批准")
        self.owned()
        settings = validate_settings(read_json(Path(snapshot) / "settings.json"))
        revision = identifier("v-")
        target = self.root / "versions" / revision
        copy_snapshot(snapshot, target)
        digest = snapshot_digest(target)
        write_json(target / "version.json", {"revision": revision, "digest": digest, "created_at": now(),
                                             "proposal_id": proposal_id, "confirmation": confirmation})
        write_json(self.root / "current.json", {"revision": revision, "digest": digest})
        self.append("audit.jsonl", {"action": "activate", "at": now(), "revision": revision,
                                     "proposal_id": proposal_id, "confirmation": confirmation, "actor": owner_id()})
        versions = self.version_list()
        # keep 个数包括当前正式版；其余为可回退旧版。
        ordered = [revision] + [item["revision"] for item in versions if item["revision"] != revision]
        keep = set(ordered[:settings["versions"]["keep"]])
        for item in versions:
            if item["revision"] not in keep:
                safe_remove_version(self.root / "versions" / item["revision"], self.root / "versions")
        return revision

    def initialize(self, snapshot, confirmation, report):
        if (self.root / "current.json").exists():
            raise ValueError("账号已经初始化，后续变更须走提案审批")
        require_validation(snapshot, report)
        self.owned(create=True)
        return self.commit(snapshot, confirmation, "initial-install")

    @locked
    def register_batch(self, jobs, results, revision=None, feedback_mode=None):
        current_revision, _, settings = self.active()
        revision = revision or current_revision
        feedback_mode = feedback_mode or settings["feedback"]["mode"]
        batch_id = identifier("b-")
        record = {"id": batch_id, "revision": revision, "created_at": now(), "jobs": jobs,
                  "image_paths": [str(Path(job["input"]).resolve()) for job in jobs],
                  "outputs": [path for result in results for path in result.get("outputs", [])],
                  "feedback_requested": False, "feedback_due": feedback_mode == "per_batch"}
        record["status"] = "completed"
        write_json(self.root / "batches" / (batch_id + ".json"), record)
        return {"batch_id": batch_id, "feedback_due": record["feedback_due"],
                "question": "这批尺寸调整效果满意吗？可说明构图、白边、主体大小或需要保留的部位。"}

    @locked
    def begin_batch(self, jobs, revision, context=None):
        self.active()
        batch_id = identifier("b-")
        record = {"id": batch_id, "revision": revision, "created_at": now(), "status": "pending",
                  "jobs": jobs, "image_paths": [str(Path(j["input"]).resolve()) for j in jobs],
                  "items": [{"status": "pending", "outputs": []} for _ in jobs],
                  "outputs": [], "feedback_requested": False, "feedback_due": False}
        if context:
            record['context']=context
        write_json(self.root / 'batches' / (batch_id + '.json'), record)
        return batch_id

    @locked
    def update_batch(self, batch_id, index=None, result=None, error=None, complete=False, feedback_mode="per_batch"):
        record = self.batch_record(batch_id)
        if index is not None:
            item = dict(result or {})
            if error:
                item.update(status="partial" if item.get('outputs') else "failed", error=str(error))
            else:
                item["status"] = "completed"
            record['items'][index] = item
        record['outputs'] = [p for item in record['items'] for p in item.get('outputs', [])]
        record['outputs'] += [path for value in record.get('grouped_psds',{}).values()
                              if value.get('status')=='completed' for path in value.get('outputs',[])]
        if complete:
            if record.get('error'):
                record.setdefault('resolved_errors',[]).append(record.pop('error'))
            record.update(status="completed", feedback_due=feedback_mode == "per_batch")
        elif error:
            record.update(status="partial" if record['outputs'] else "failed", error=str(error), feedback_due=False)
        write_json(self.root / 'batches' / (batch_id + '.json'), record)
        return record

    def batch_record(self, batch_id):
        self.owned()
        if not re.fullmatch(r"b-[A-Za-z0-9-]+", batch_id):
            raise ValueError("非法批次标识")
        return read_json(self.root / "batches" / (batch_id + ".json"))

    @locked
    def mark_asked(self, batch_id):
        record = self.batch_record(batch_id)
        already = record["feedback_requested"]
        record.update(feedback_requested=True, feedback_due=False)
        write_json(self.root / "batches" / (batch_id + ".json"), record)
        return {"batch_id": batch_id, "ask_now": not already}

    def proposals(self):
        self.owned()
        return [read_json(path) for path in (self.root / "proposals").glob("p-*/proposal.json")]

    def write_review(self, directory, record, active):
        candidate = directory / "candidate"
        record["digest"] = snapshot_digest(candidate)
        record["script_changed"] = file_hash(active / "renderer.py") != file_hash(candidate / "renderer.py")
        diffs = []
        for name in MANAGED:
            diffs.extend(difflib.unified_diff((active / name).read_text(encoding="utf-8").splitlines(True),
                                            (candidate / name).read_text(encoding="utf-8").splitlines(True),
                                            fromfile="before/" + name, tofile="after/" + name))
        (directory / "changes.diff").write_text("".join(diffs), encoding="utf-8")
        write_json(directory / "proposal.json", record)
        (directory / "review.md").write_text(
            f"# 待审修改\n\n{record['summary']}\n\n- 草案：{record['id']}\n- 基于版本：{record['base_revision']}\n"
            f"- 校验摘要：{record['digest']}\n- 修改脚本：{'是' if record['script_changed'] else '否'}\n\n"
            "查看 changes.diff 和验证预览，用户批准后才能生效。\n", encoding="utf-8")
        return record

    def proposal(self, proposal_id):
        self.owned()
        if not re.fullmatch(r"p-[A-Za-z0-9-]+", proposal_id):
            raise ValueError("非法草案标识")
        directory = self.root / "proposals" / proposal_id
        return directory, read_json(directory / "proposal.json")

    @locked
    def propose(self, changed, summary, feedback_ids=None):
        revision, active, _ = self.active()
        if set(changed) - set(MANAGED):
            raise ValueError("自适应变更仅能修改个人配置、个人提示词和个人裁切脚本")
        proposal_id = identifier("p-")
        directory = self.root / "proposals" / proposal_id
        candidate = directory / "candidate"
        copy_snapshot(active, candidate)
        for name, value in changed.items():
            if name == "settings.json":
                validate_settings(value)
                write_json(candidate / name, value)
            else:
                if not isinstance(value, str):
                    raise ValueError("提示词和脚本草案必须为文本")
                (candidate / name).write_text(value, encoding="utf-8")
        digest = snapshot_digest(candidate)
        if digest == snapshot_digest(active):
            raise ValueError("草案没有实际变化")
        record = {"id": proposal_id, "owner_id": owner_id(), "base_revision": revision, "created_at": now(),
                  "status": "pending", "digest": digest, "summary": summary, "feedback_ids": feedback_ids or [],
                  "script_changed": file_hash(active / "renderer.py") != file_hash(candidate / "renderer.py")}
        self.write_review(directory, record, active)
        return {**record, "directory": str(directory), "review": str(directory / "review.md")}

    @locked
    def feedback(self, batch_id, text, topic, scope, desired_patch=None):
        batch = self.batch_record(batch_id)
        _, active, settings = self.active()
        if not text.strip() or not topic.strip() or scope not in ("once", "general", "long_term"):
            raise ValueError("反馈需要明确文字、主题和 once/general/long_term 范围")
        if desired_patch is not None and not isinstance(desired_patch, dict):
            raise ValueError("desired_patch 必须为对象")
        context=batch.get('context',{})
        record = {"id": identifier("f-"), "created_at": now(), "batch_id": batch_id, "source": "human_message",
                  "text": text, "topic": topic, "scope": scope, "desired_patch": desired_patch or {},
                  "params": batch["jobs"], "image_paths": batch["image_paths"], 'context':context}
        self.append("feedback.jsonl", record)
        if scope == "once":
            return {"feedback_id": record["id"], "eligible": False, "reason": "仅本次调整，不改长期习惯"}
        grouping = json.dumps(record["desired_patch"], sort_keys=True, ensure_ascii=False)
        used = {item for proposal in self.proposals() for item in proposal["feedback_ids"]}
        evidence = [item for item in self.events("feedback.jsonl") if item["scope"] != "once"
                    and item["topic"] == topic and json.dumps(item["desired_patch"], sort_keys=True, ensure_ascii=False) == grouping
                    and item.get('context',{})==context
                    and item["id"] not in used]
        count = len({item["batch_id"] for item in evidence})
        if scope != "long_term" and count < settings["feedback"]["repeat_threshold"]:
            return {"feedback_id": record["id"], "eligible": False, "distinct_batches": count,
                    "threshold": settings["feedback"]["repeat_threshold"]}
        changed_settings = merge(settings, record["desired_patch"])
        validate_settings(changed_settings)
        prompt = (active / "personal_prompt.md").read_text(encoding="utf-8").rstrip()
        line = f"- 用户偏好（主题 {topic}）：{text.strip()}"
        if context:
            line=f"- 用户偏好（用途 {context.get('image_kind','未分类')}；品类 {context.get('category','未指定')}；主题 {topic}）：{text.strip()}"
        if changed_settings == settings and line in prompt.splitlines():
            return {"feedback_id": record["id"], "eligible": True, "proposal": None,
                    "diagnostic": "相同规则已经存在，请检查执行参数或脚本，不重复添加同一条提示词"}
        prompt += f"\n\n{line}\n"
        proposal = self.propose({"settings.json": changed_settings, "personal_prompt.md": prompt},
                                f"根据用户反馈提出个人规则修改：{text.strip()}", [item["id"] for item in evidence])
        return {"feedback_id": record["id"], "eligible": True, "distinct_batches": count, "proposal": proposal}

    @locked
    def validate(self, proposal_id, jobs=None):
        directory, proposal = self.proposal(proposal_id)
        if proposal["status"] != "pending":
            raise ValueError("只能验证待审草案")
        revision, active, _ = self.active()
        if revision != proposal["base_revision"]:
            raise ValueError("正式版本已变化，请重新生成草案")
        if snapshot_digest(directory / "candidate") == snapshot_digest(active):
            raise ValueError("整理后的草案与正式版本相同，无需审批或生成新版本")
        from validate_candidate import validate_snapshot
        report = validate_snapshot(directory / "candidate", directory / "validation-artifacts", jobs or [])
        write_json(directory / "validation.json", report)
        self.write_review(directory, proposal, active)
        return report

    @locked
    def approve(self, proposal_id, expected_digest, confirmation):
        directory, proposal = self.proposal(proposal_id)
        if proposal["status"] != "pending":
            raise ValueError("草案已处理")
        if not confirmation or not confirmation.strip():
            raise ValueError("缺少用户确认原文")
        revision, _, _ = self.active()
        if revision != proposal["base_revision"]:
            raise ValueError("正式版本已变化，请重新生成和审核草案")
        candidate = directory / "candidate"
        if expected_digest != proposal["digest"] or expected_digest != snapshot_digest(candidate):
            raise ValueError("审批摘要与草案不符，必须重新审核")
        require_validation(candidate, read_json(directory / "validation.json"))
        result = self.commit(candidate, confirmation, proposal_id)
        proposal.update(status="applied", applied_at=now(), revision=result, confirmation=confirmation)
        write_json(directory / "proposal.json", proposal)
        # 已生效的完整快照只留在 versions 中，遵守3版保留策略。
        for name in MANAGED:
            (candidate / name).unlink()
        candidate.rmdir()
        return {"revision": result, "proposal_id": proposal_id}

    @locked
    def reject(self, proposal_id, reason):
        directory, proposal = self.proposal(proposal_id)
        if proposal["status"] != "pending":
            raise ValueError("草案已处理")
        proposal.update(status="rejected", reason=reason, rejected_at=now())
        write_json(directory / "proposal.json", proposal)
        return proposal

    @locked
    def incident(self, error, job=None):
        self.owned()
        current = read_json(self.root / "current.json").get("revision")
        event = {"id": identifier("e-"), "at": now(), "revision": current, "error": str(error),
                 "job": job or {}, "automatic_rollback": False,
                 "message": "已记录异常，当前正式版本保持不变；请用户决定是否回退"}
        self.append("incidents.jsonl", event)
        return event

    @locked
    def rollback(self, revision, confirmation):
        self.owned()
        if not confirmation or not confirmation.strip():
            raise ValueError("回退也需要用户明确确认")
        versions = {item["revision"]: item for item in self.version_list()}
        if revision not in versions:
            raise ValueError("版本不存在或已超出保留范围")
        candidate = self.root / "versions" / revision
        digest = snapshot_digest(candidate)
        if digest != versions[revision]["digest"]:
            raise ValueError("历史版本文件发生变化，不能回退")
        write_json(self.root / "current.json", {"revision": revision, "digest": digest})
        self.append("audit.jsonl", {"action": "rollback", "at": now(), "revision": revision,
                                     "confirmation": confirmation, "actor": owner_id()})
        return {"revision": revision, "rollback": "manual"}


def require_validation(snapshot, report):
    if not report.get("passed") or report.get("candidate_digest") != snapshot_digest(snapshot):
        raise ValueError("验证未通过或验证后文件发生变化，不能生效")
    for artifact in report.get("previews", []):
        if not Path(artifact["path"]).is_file() or file_hash(artifact["path"]) != artifact["sha256"]:
            raise ValueError("测试预览已变化或缺失，请重新验证")
    for source in report.get("sources", []):
        if not Path(source["path"]).is_file() or file_hash(source["path"]) != source["sha256"]:
            raise ValueError("测试原图已变化或缺失，请重新验证")
    if not report.get("previews"):
        raise ValueError("缺少可供用户查看的测试预览")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", help="仅用于明确指定的独立测试目录；正常使用默认账号目录")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("versions")
    init = commands.add_parser("init")
    init.add_argument("--snapshot", required=True)
    init.add_argument("--validation", required=True)
    init.add_argument("--confirmation", required=True)
    feedback = commands.add_parser("feedback")
    feedback.add_argument("--batch", required=True)
    feedback.add_argument("--text", required=True)
    feedback.add_argument("--topic", required=True)
    feedback.add_argument("--scope", choices=("once", "general", "long_term"), required=True)
    feedback.add_argument("--patch", help="已从明确反馈解析出的配置修改 JSON 文件，可省略")
    asked = commands.add_parser("mark-asked")
    asked.add_argument("--batch", required=True)
    proposal = commands.add_parser("propose")
    proposal.add_argument("--changes", required=True, help="只包含被修改的 managed 文件的目录")
    proposal.add_argument("--summary", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--proposal", required=True)
    validate.add_argument("--spec", help="用于复现反馈的候选任务单")
    approve = commands.add_parser("approve")
    approve.add_argument("--proposal", required=True)
    approve.add_argument("--digest", required=True)
    approve.add_argument("--confirmation", required=True, help="用户本次明确批准的原文；代理不得代填虚构同意")
    reject = commands.add_parser("reject")
    reject.add_argument("--proposal", required=True)
    reject.add_argument("--reason", required=True)
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--revision", required=True)
    rollback.add_argument("--confirmation", required=True)
    args = parser.parse_args()
    store = Store(args.state)
    try:
        if args.command == "status":
            result = store.status()
        elif args.command == "versions":
            result = store.version_list()
        elif args.command == "init":
            result = {"revision": store.initialize(args.snapshot, args.confirmation, read_json(args.validation))}
        elif args.command == "feedback":
            result = store.feedback(args.batch, args.text, args.topic, args.scope, read_json(args.patch) if args.patch else None)
        elif args.command == "mark-asked":
            result = store.mark_asked(args.batch)
        elif args.command == "propose":
            changes_dir = Path(args.changes)
            if any(item.name not in MANAGED or not item.is_file() for item in changes_dir.iterdir()):
                raise ValueError("草案目录只能包含 settings.json、personal_prompt.md、renderer.py")
            changes = {item.name: read_json(item) if item.name == "settings.json" else item.read_text(encoding="utf-8")
                       for item in changes_dir.iterdir()}
            result = store.propose(changes, args.summary)
        elif args.command == "validate":
            from task_spec import load_jobs
            result = store.validate(args.proposal, load_jobs(args.spec) if args.spec else [])
        elif args.command == "approve":
            result = store.approve(args.proposal, args.digest, args.confirmation)
        elif args.command == "reject":
            result = store.reject(args.proposal, args.reason)
        else:
            result = store.rollback(args.revision, args.confirmation)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "validate" and not result.get("passed"):
            raise SystemExit(2)
    except (ValueError, KeyError, OSError, TypeError) as error:
        parser.exit(2, f"[错误] {error}\n")


if __name__ == "__main__":
    main()
