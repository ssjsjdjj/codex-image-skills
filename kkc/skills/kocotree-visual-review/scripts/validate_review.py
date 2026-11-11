#!/usr/bin/env python3
"""Validate a KOCOTREE visual review record; never performs network writes."""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

RUBRIC = {
    "first_screen": 12,
    "product_visibility": 14,
    "scene_credibility": 10,
    "claim_clarity": 13,
    "claim_proof": 13,
    "readability": 10,
    "visual_system": 8,
    "page_flow": 10,
    "style_fit": 10,
}
CORE_GATES = {
    "product_identifiable",
    "first_three_chain",
    "design_system",
    "claim_evidence",
}
AUX_GATES = {
    "asset_materials",
    "copy_facts",
    "brand_elements",
    "ai_artifacts",
    "platform_safe_area",
}
GATES = CORE_GATES | AUX_GATES
STAGES = {"initial", "revision", "final"}
FINDING_STATUSES = {"open", "partial", "closed", "dismissed", "pending"}


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _choice(value, allowed):
    return isinstance(value, str) and value in allowed


def _objects(value, location, errors):
    if not isinstance(value, list):
        errors.append(f"{location}必须为数组")
        return []
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(f"{location}[{index}]必须为对象")
        else:
            result.append(item)
    return result


def _unique_items(items, location, errors):
    seen = set()
    for item in items:
        identifier = item.get("id")
        if not _nonempty(identifier):
            errors.append(f"{location}存在空ID")
        elif identifier in seen:
            errors.append(f"{location}存在重复ID：{identifier}")
        else:
            seen.add(identifier)
    return seen


def _refs(item, location, evidence_ids, errors, required=True, field="evidence_ids"):
    refs = item.get(field)
    if not isinstance(refs, list) or (required and not refs):
        errors.append(f"{location}.{field}须为{'非空' if required else ''}数组")
        return
    if len(refs) != len(set(ref for ref in refs if isinstance(ref, str))):
        errors.append(f"{location}.{field}存在重复或无效引用")
    for ref in refs:
        if not isinstance(ref, str) or ref not in evidence_ids:
            errors.append(f"{location}.{field}引用不存在的证据：{ref}")


def validate(record, previous=None):
    errors = []
    if not isinstance(record, dict):
        return ["记录根节点必须为对象"], None

    if record.get("template_only") is True:
        errors.append("模板标记template_only须移除后才能作为审核记录")

    if record.get("schema_version") != "1.0":
        errors.append("schema_version必须为1.0")
    for field in ("project_id", "review_id", "version"):
        if not _nonempty(record.get(field)):
            errors.append(f"{field}不能为空")
        elif record[field].strip().startswith("EXAMPLE"):
            errors.append(f"{field}仍为模板示例值")
    # Older records may omit case metadata; supplied values must be usable.
    for field in ("product_category", "product_name"):
        if field in record:
            if not _nonempty(record[field]):
                errors.append(f"{field}须为非空字符串")
            elif record[field].strip().startswith("EXAMPLE"):
                errors.append(f"{field}仍为模板示例值")
    if "reviewed_at" in record:
        try:
            value = record["reviewed_at"]
            if not _nonempty(value):
                raise ValueError
            instant = datetime.fromisoformat(value)
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            errors.append("reviewed_at须为带时区的ISO 8601日期时间")
    stage = record.get("stage")
    if not _choice(stage, STAGES):
        errors.append("stage必须为initial、revision或final")
    if record.get("rubric_version") != "kocotree-visual-1.0":
        errors.append("rubric_version必须为kocotree-visual-1.0")

    artifact = record.get("artifact")
    if not isinstance(artifact, dict):
        errors.append("artifact必须为对象")
    else:
        if not _nonempty(artifact.get("name")) or not _nonempty(artifact.get("uri")):
            errors.append("artifact.name和artifact.uri不能为空")
        elif artifact["name"].startswith("EXAMPLE") or artifact["uri"].startswith("EXAMPLE"):
            errors.append("artifact仍为模板示例值")
        sha = artifact.get("sha256")
        if sha is not None and (not isinstance(sha, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", sha)):
            errors.append("artifact.sha256须为64位十六进制或null")

    evidence = _objects(record.get("evidence"), "evidence", errors)
    evidence_ids = _unique_items(evidence, "evidence", errors)
    for item in evidence:
        label = f"evidence[{item.get('id', '?')}]"
        for field in ("locator", "observation", "source_ref"):
            if not _nonempty(item.get(field)):
                errors.append(f"{label}.{field}不能为空")
        if not _choice(item.get("source"), {"visual", "business", "platform", "supervisor"}):
            errors.append(f"{label}.source无效")

    scores = _objects(record.get("scores"), "scores", errors)
    score_ids = _unique_items(scores, "scores", errors)
    if score_ids != set(RUBRIC):
        errors.append("scores必须且只包含九项维度：" + ", ".join(RUBRIC))
    total = 0
    complete = len(scores) == len(RUBRIC) and score_ids == set(RUBRIC)
    for item in scores:
        identifier = item.get("id")
        label = f"scores[{identifier}]"
        if not _choice(identifier, RUBRIC):
            continue
        if type(item.get("max")) is not int or item["max"] != RUBRIC[identifier]:
            errors.append(f"{label}.max应为{RUBRIC[identifier]}")
        status = item.get("status")
        value = item.get("score")
        if status == "assessed":
            if type(value) is not int or not 0 <= value <= RUBRIC[identifier]:
                errors.append(f"{label}.score须为0到{RUBRIC[identifier]}的整数")
                complete = False
            else:
                total += value
            if not _nonempty(item.get("reason")):
                errors.append(f"{label}.reason不能为空")
            _refs(item, label, evidence_ids, errors)
        elif status == "insufficient":
            complete = False
            if value is not None:
                errors.append(f"{label}资料不足时score须为null")
            if not _nonempty(item.get("reason")):
                errors.append(f"{label}须说明缺少的资料")
            _refs(item, label, evidence_ids, errors, required=False)
        else:
            complete = False
            errors.append(f"{label}.status无效")

    gates = _objects(record.get("gates"), "gates", errors)
    gate_ids = _unique_items(gates, "gates", errors)
    if gate_ids != GATES:
        errors.append("gates必须且只包含四项核心门槛与五项辅助检查")
    gate_by_id = {item.get("id"): item for item in gates if _nonempty(item.get("id"))}
    for item in gates:
        identifier = item.get("id")
        label = f"gates[{identifier}]"
        if not _choice(identifier, GATES):
            continue
        status = item.get("status")
        blocking = item.get("blocking")
        if not _choice(status, {"passed", "blocked", "pending", "na"}):
            errors.append(f"{label}.status无效")
        if type(blocking) is not bool:
            errors.append(f"{label}.blocking须为布尔值")
        if identifier in CORE_GATES and blocking is not True:
            errors.append(f"{label}是核心门槛，blocking须为true")
        if identifier in CORE_GATES and status == "na":
            errors.append(f"{label}核心门槛不能标不适用")
        if stage == "final" and identifier in {"asset_materials", "copy_facts"} and blocking is not True:
            errors.append(f"{label}终稿必须作为阻断检查")
        if status == "na" and blocking is True:
            errors.append(f"{label}不适用时不能阻断")
        if not _nonempty(item.get("reason")):
            errors.append(f"{label}.reason不能为空")
        _refs(item, label, evidence_ids, errors, required=_choice(status, {"passed", "blocked"}))

    findings = _objects(record.get("findings"), "findings", errors)
    finding_ids = _unique_items(findings, "findings", errors)
    for item in findings:
        identifier = item.get("id")
        label = f"findings[{identifier}]"
        if not _choice(item.get("kind"), {"required", "suggestion"}):
            errors.append(f"{label}.kind无效")
        if not _choice(item.get("status"), FINDING_STATUSES):
            errors.append(f"{label}.status无效")
        dimension = item.get("dimension_id")
        if dimension is not None and not _choice(dimension, RUBRIC):
            errors.append(f"{label}.dimension_id无效")
        related_gates = item.get("gate_ids", [])
        if not isinstance(related_gates, list) or any(not _choice(gate, GATES) for gate in related_gates):
            errors.append(f"{label}.gate_ids无效")
            related_gates = []
        if dimension is None and not related_gates:
            errors.append(f"{label}须关联评分项或门槛")
        if not _nonempty(item.get("description")):
            errors.append(f"{label}.description不能为空")
        _refs(item, label, evidence_ids, errors)
        if item.get("kind") == "required":
            for field in ("action", "acceptance"):
                if not _nonempty(item.get(field)):
                    errors.append(f"{label}.{field}不能为空")
        if item.get("kind") == "suggestion" and not _nonempty(item.get("expected_benefit")):
            errors.append(f"{label}.expected_benefit不能为空")
        if item.get("status") == "closed":
            _refs(item, label, evidence_ids, errors, field="closure_evidence_ids")
        if item.get("status") == "dismissed" and not _nonempty(item.get("dismissal_reason")):
            errors.append(f"{label}否定问题须说明主管依据")

    for gate_id, gate in gate_by_id.items():
        if gate.get("status") != "blocked":
            continue
        linked = any(
            item.get("kind") == "required"
            and _choice(item.get("status"), {"open", "partial"})
            and gate_id in item.get("gate_ids", [])
            for item in findings
            if isinstance(item.get("gate_ids", []), list)
        )
        if not linked:
            errors.append(f"门槛{gate_id}已阻断，但没有关联未关闭的必改问题")

    unresolved = any(
        item.get("kind") == "required" and _choice(item.get("status"), {"open", "partial"})
        for item in findings
    )
    pending_finding = any(
        item.get("kind") == "required" and item.get("status") == "pending"
        for item in findings
    )
    blocked_gate = any(item.get("status") == "blocked" and item.get("blocking") is True for item in gates)
    pending_gate = any(item.get("status") == "pending" and item.get("blocking") is True for item in gates)

    if unresolved or blocked_gate:
        expected = "needs_revision"
    elif not complete or pending_finding or pending_gate:
        expected = "insufficient_evidence"
    elif total < 85:
        expected = "needs_revision"
    else:
        expected = "final_ready" if stage == "final" else "direction_ready"

    decision = record.get("decision")
    if not isinstance(decision, dict):
        errors.append("decision必须为对象")
    else:
        if decision.get("ai_recommendation") != expected:
            errors.append(f"decision.ai_recommendation应为{expected}")
        supervisor = decision.get("supervisor")
        if not isinstance(supervisor, dict):
            errors.append("decision.supervisor必须为对象")
        elif supervisor.get("status") == "pending":
            if supervisor.get("decision") is not None:
                errors.append("主管待确认时decision须为null")
        elif supervisor.get("status") == "recorded":
            choices = {"revision_requested"}
            choices.add("final_approved" if stage == "final" else "direction_approved")
            if not _choice(supervisor.get("decision"), choices):
                errors.append("主管决定与阶段不匹配")
            if not _nonempty(supervisor.get("reason")):
                errors.append("已记录主管决定时须保留依据")
            if _choice(supervisor.get("decision"), {"final_approved", "direction_approved"}) and expected not in {"final_ready", "direction_ready"}:
                if not _nonempty(supervisor.get("override_reason")):
                    errors.append("主管批准与AI建议不同时须写override_reason")
        else:
            errors.append("decision.supervisor.status无效")
        if isinstance(supervisor, dict):
            calibrated = supervisor.get("calibrated_score")
            if calibrated is not None and (type(calibrated) is not int or not 0 <= calibrated <= 100):
                errors.append("主管校准总分须为0至100的整数或null")
            if calibrated is not None and supervisor.get("status") != "recorded":
                errors.append("主管待确认时不能填写校准分")
            if calibrated is not None and not _nonempty(supervisor.get("reason")):
                errors.append("主管调整总分须写依据")

    package_status = record.get("package_status")
    if not _choice(package_status, {"not_started", "deferred", "pending", "passed", "failed"}):
        errors.append("package_status无效")
    if package_status == "passed" and not _nonempty(record.get("package_audit_ref")):
        errors.append("数据包通过须提供独立验收记录package_audit_ref")

    if previous is not None:
        if not isinstance(previous, dict):
            errors.append("上一版记录根节点必须为对象")
        else:
            if previous.get("project_id") != record.get("project_id"):
                errors.append("上一版与当前版project_id不一致")
            if previous.get("review_id") == record.get("review_id"):
                errors.append("新版本不能复用旧review_id")
            prior_findings = previous.get("findings", [])
            if not isinstance(prior_findings, list):
                errors.append("上一版findings无效")
            else:
                current = {item.get("id"): item for item in findings if _nonempty(item.get("id"))}
                for prior in prior_findings:
                    if not isinstance(prior, dict) or not _nonempty(prior.get("id")):
                        continue
                    old_status = prior.get("status")
                    new = current.get(prior["id"])
                    if _choice(old_status, {"open", "partial", "pending"}) and new is None:
                        errors.append(f"旧版未关闭问题{prior['id']}未在新版承接")
                    if old_status == "closed" and new is not None and _choice(new.get("status"), {"open", "partial", "pending"}):
                        if not _nonempty(new.get("reopen_reason")):
                            errors.append(f"问题{prior['id']}重新打开须说明reopen_reason")

    return errors, total if complete else None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path, help="本版审核JSON")
    parser.add_argument("--previous", type=Path, help="上一版审核JSON")
    args = parser.parse_args(argv)
    try:
        record = json.loads(args.record.read_text(encoding="utf-8"))
        previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"无法读取审核记录：{exc}", file=sys.stderr)
        return 1
    if args.previous is not None and not isinstance(previous, dict):
        print("错误：上一版记录根节点必须为对象", file=sys.stderr)
        return 1
    errors, total = validate(record, previous)
    if errors:
        for error in errors:
            print("错误：" + error, file=sys.stderr)
        return 1
    print("审核记录校验通过；" + (f"九项总分：{total}/100" if total is not None else "九项资料不足，暂无正式总分"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
