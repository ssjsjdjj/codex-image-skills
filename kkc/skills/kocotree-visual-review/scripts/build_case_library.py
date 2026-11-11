#!/usr/bin/env python3
"""Rebuild a traceable case library from per-version review JSON records."""

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from validate_review import validate


UNRESOLVED = {"open", "partial", "pending"}
APPROVED = {"direction_approved", "final_approved"}


def _evidence(record, finding, field):
    by_id = {item["id"]: item for item in record["evidence"]}
    return [by_id[identifier] for identifier in finding.get(field, [])]


def _artifact(record):
    return {
        "name": record["artifact"]["name"],
        "uri": record["artifact"]["uri"],
        "sha256": record["artifact"].get("sha256"),
    }


def _case_id(project_id, finding_id):
    digest = hashlib.sha256(f"{project_id}\0{finding_id}".encode("utf-8")).hexdigest()[:12]
    return f"CASE-{digest.upper()}"


def _approved(record):
    supervisor = record["decision"]["supervisor"]
    return supervisor["status"] == "recorded" and supervisor["decision"] in APPROVED


def _make_case(project_id, category, product_name, origin_record, origin_finding, close_record, close_finding):
    return {
        "case_id": _case_id(project_id, close_finding["id"]),
        "project_id": project_id,
        "product_category": category,
        "product_name": product_name,
        "finding_id": close_finding["id"],
        "dimension_id": close_finding.get("dimension_id"),
        "gate_ids": close_finding.get("gate_ids", []),
        "description": origin_finding["description"],
        "action": close_finding["action"],
        "acceptance": close_finding["acceptance"],
        "before": {
            "review_id": origin_record["review_id"],
            "version": origin_record["version"],
            "stage": origin_record["stage"],
            "reviewed_at": origin_record["reviewed_at"],
            "artifact": _artifact(origin_record),
            "evidence": _evidence(origin_record, origin_finding, "evidence_ids"),
        },
        "after": {
            "review_id": close_record["review_id"],
            "version": close_record["version"],
            "stage": close_record["stage"],
            "reviewed_at": close_record["reviewed_at"],
            "artifact": _artifact(close_record),
            "evidence": _evidence(close_record, close_finding, "closure_evidence_ids"),
            "supervisor_decision": close_record["decision"]["supervisor"]["decision"],
            "supervisor_reason": close_record["decision"]["supervisor"]["reason"],
        },
    }


def build_cases(source_dir, out_dir=None):
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise ValueError(f"审核记录目录不存在：{source_dir}")
    out_resolved = Path(out_dir).resolve() if out_dir is not None else None
    files = []
    for path in source_dir.rglob("*.json"):
        if out_resolved is not None and (path.resolve() == out_resolved or out_resolved in path.resolve().parents):
            continue
        files.append(path)
    files.sort()
    if not files:
        raise ValueError("审核记录目录没有JSON文件")

    projects = defaultdict(list)
    errors = []
    for path in files:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: 无法读取JSON：{exc}")
            continue
        validation_errors, _ = validate(record)
        if validation_errors:
            errors.extend(f"{path}: {message}" for message in validation_errors)
            continue
        projects[record["project_id"]].append((record, path))
    if errors:
        raise ValueError("审核记录校验失败，案例库未更新：\n" + "\n".join(errors))

    cases = []
    skipped_projects = []
    skipped_candidates = []
    for project_id, entries in sorted(projects.items()):
        missing = [
            path.name for record, path in entries
            if not all(record.get(field) for field in ("reviewed_at", "product_category", "product_name"))
        ]
        if missing:
            skipped_projects.append({"project_id": project_id, "reason": "缺少案例排序或分类元数据", "files": sorted(missing)})
            continue
        entries.sort(key=lambda pair: (datetime.fromisoformat(pair[0]["reviewed_at"]), pair[0]["review_id"]))
        seen_ids = set()
        previous = None
        timestamps = set()
        for record, path in entries:
            if record["review_id"] in seen_ids:
                errors.append(f"{project_id}: 重复review_id：{record['review_id']}")
            seen_ids.add(record["review_id"])
            instant = datetime.fromisoformat(record["reviewed_at"])
            if instant in timestamps:
                errors.append(f"{project_id}: 审核时间重复，无法确定版本顺序：{record['reviewed_at']}")
            timestamps.add(instant)
            if previous is not None:
                linkage_errors, _ = validate(record, previous)
                errors.extend(f"{path}: {message}" for message in linkage_errors)
            previous = record
        if errors:
            continue

        origins = {}
        active_cases = {}
        awaiting_approval = {}
        for record, _ in entries:
            for finding in record["findings"]:
                identifier = finding["id"]
                status = finding["status"]
                if status in UNRESOLVED:
                    origins.setdefault(identifier, (record, finding))
                    active_cases.pop(identifier, None)
                    awaiting_approval.pop(identifier, None)
                elif status == "dismissed":
                    origins.pop(identifier, None)
                    active_cases.pop(identifier, None)
                    awaiting_approval.pop(identifier, None)
                elif status == "closed":
                    origin = origins.get(identifier)
                    if origin is not None and _approved(record) and finding["kind"] == "required":
                        active_cases[identifier] = _make_case(
                            project_id, record["product_category"], record["product_name"],
                            origin[0], origin[1], record, finding,
                        )
                        origins.pop(identifier, None)
                        awaiting_approval.pop(identifier, None)
                    elif origin is not None:
                        active_cases.pop(identifier, None)
                        if finding["kind"] == "required":
                            awaiting_approval[identifier] = {
                                "project_id": project_id,
                                "finding_id": identifier,
                                "review_id": record["review_id"],
                                "reason_code": "supervisor_unapproved",
                                "reason": "问题已关闭，但该解决记录尚未获主管方向或终稿批准",
                            }
                        else:
                            awaiting_approval.pop(identifier, None)
        cases.extend(active_cases.values())
        skipped_candidates.extend(awaiting_approval[key] for key in sorted(awaiting_approval))

    if errors:
        raise ValueError("版本衔接校验失败，案例库未更新：\n" + "\n".join(errors))
    cases.sort(key=lambda case: (case["product_category"], case["dimension_id"] or "", case["case_id"]))
    return {
        "schema_version": "1.0", "cases": cases,
        "skipped_projects": skipped_projects, "skipped_candidates": skipped_candidates,
    }


def render_reference(index):
    lines = ["# KOCOTREE视觉审核案例参考", "", "由审核记录生成；引用前仍须打开原稿核对。案例ID稳定，内容随最新审核记录更新。", ""]
    if not index["cases"]:
        lines.extend(["当前没有满足入库条件的真实案例。", ""])
    for case in index["cases"]:
        before, after = case["before"], case["after"]
        lines.extend([
            f"## {case['case_id']} · {case['product_category']} · {case['description']}",
            "",
            f"- 商品：{case['product_name']}；项目：{case['project_id']}；问题ID：{case['finding_id']}；维度：{case['dimension_id'] or '门槛项'}。",
            f"- 修改动作：{case['action']}；验收条件：{case['acceptance']}。",
            f"- 修改前：{before['review_id']}，版本{before['version']}，文件`{before['artifact']['uri']}`。",
        ])
        lines.extend(f"  - 证据 {item['id']}：{item['locator']}；{item['observation']}。" for item in before["evidence"])
        lines.append(f"- 修改后：{after['review_id']}，版本{after['version']}，文件`{after['artifact']['uri']}`；主管决定：{after['supervisor_decision']}。")
        lines.extend(f"  - 关闭证据 {item['id']}：{item['locator']}；{item['observation']}。" for item in after["evidence"])
        lines.extend(["", "引用时说明本稿与此案例的可比点和差异点；本次评分仍依据本稿证据。", ""])
    if index["skipped_projects"]:
        lines.extend(["## 未入库项目", ""])
        for item in index["skipped_projects"]:
            lines.append(f"- {item['project_id']}：{item['reason']}（{', '.join(item['files'])}）。")
        lines.append("")
    if index.get("skipped_candidates"):
        lines.extend(["## 待主管批准的已关闭问题", ""])
        for item in index["skipped_candidates"]:
            lines.append(f"- {item['project_id']} / {item['finding_id']} / {item['review_id']}：{item['reason']}。")
        lines.append("")
    return "\n".join(lines)


def write_index(index, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "case-index.json": json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        "case-reference.md": render_reference(index),
    }
    for name, content in payloads.items():
        temporary = out_dir / (name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(out_dir / name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("records_dir", type=Path, help="仅存放逐版本审核JSON的目录")
    parser.add_argument("--out-dir", type=Path, required=True, help="生成案例索引的目录")
    args = parser.parse_args(argv)
    try:
        index = build_cases(args.records_dir, args.out_dir)
        write_index(index, args.out_dir)
    except (ValueError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(f"案例库已重建：{len(index['cases'])}例，跳过{len(index['skipped_projects'])}个元数据不完整的项目，"
          f"{len(index['skipped_candidates'])}个已关闭问题待主管批准；{args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
