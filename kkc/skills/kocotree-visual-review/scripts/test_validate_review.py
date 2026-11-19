"""Behavioral checks for record validation and cross-version continuity."""

import copy
import json
import unittest
from pathlib import Path

from validate_review import validate


TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "review-template.json"


def complete_review():
    record = copy.deepcopy(json.loads(TEMPLATE.read_text(encoding="utf-8")))
    del record["template_only"]
    record["project_id"] = "P001"
    record["review_id"] = "P001-initial-1.0"
    record["product_category"] = "上衣"
    record["product_name"] = "测试商品"
    record["artifact"]["name"] = "P001-initial-1.0.pdf"
    record["artifact"]["uri"] = "P001-initial-1.0.pdf"
    record["evidence"] = [{
        "id": "E001",
        "locator": "P001-initial-1.0.pdf，完整页面和重点局部",
        "observation": "用于测试的完整样例，全部可辨认",
        "source": "visual",
        "source_ref": "P001-initial-1.0.pdf",
    }]
    for score in record["scores"]:
        score["status"] = "assessed"
        score["score"] = score["max"]
        score["reason"] = "测试样例中的该维度无可见缺陷"
        score["evidence_ids"] = ["E001"]
    for gate in record["gates"]:
        gate["status"] = "passed"
        gate["reason"] = "测试样例通过"
        gate["evidence_ids"] = ["E001"]
    record["decision"]["ai_recommendation"] = "direction_ready"
    return record


def issue(identifier="F001", status="open", gate_ids=None):
    return {
        "id": identifier,
        "kind": "required",
        "status": status,
        "dimension_id": "product_visibility",
        "gate_ids": gate_ids or [],
        "evidence_ids": ["E001"],
        "description": "主商品被遮挡",
        "action": "调整主体露出范围",
        "acceptance": "完整露出关键结构",
    }


class ValidateReviewTests(unittest.TestCase):
    def test_complete_score_and_direction(self):
        errors, total = validate(complete_review())
        self.assertEqual(errors, [])
        self.assertEqual(total, 100)

    def test_incomplete_evidence_has_no_formal_total(self):
        record = complete_review()
        record["scores"][0].update(status="insufficient", score=None, reason="缺少可辨认的首屏", evidence_ids=[])
        record["decision"]["ai_recommendation"] = "insufficient_evidence"
        errors, total = validate(record)
        self.assertEqual(errors, [])
        self.assertIsNone(total)

    def test_blocker_preserves_raw_total(self):
        record = complete_review()
        record["scores"][0]["score"] = 4
        record["gates"][0]["status"] = "blocked"
        record["findings"] = [issue(gate_ids=["product_identifiable"])]
        record["decision"]["ai_recommendation"] = "needs_revision"
        errors, total = validate(record)
        self.assertEqual(errors, [])
        self.assertEqual(total, 92)

    def test_duplicate_issue_is_rejected(self):
        record = complete_review()
        record["findings"] = [issue(), issue()]
        record["decision"]["ai_recommendation"] = "needs_revision"
        errors, _ = validate(record)
        self.assertTrue(any("重复ID" in error for error in errors))

    def test_unclosed_issue_must_carry_to_next_version(self):
        previous = complete_review()
        previous["findings"] = [issue()]
        previous["decision"]["ai_recommendation"] = "needs_revision"
        current = complete_review()
        current["review_id"] = "P001-revision-2.0"
        current["stage"] = "revision"
        current["version"] = "2.0"
        errors, _ = validate(current, previous)
        self.assertTrue(any("未在新版承接" in error for error in errors))

    def test_reopen_requires_reason(self):
        previous = complete_review()
        old = issue(status="closed")
        old["closure_evidence_ids"] = ["E001"]
        previous["findings"] = [old]
        current = complete_review()
        current["review_id"] = "P001-revision-2.0"
        current["stage"] = "revision"
        current["version"] = "2.0"
        current["findings"] = [issue()]
        current["decision"]["ai_recommendation"] = "needs_revision"
        errors, _ = validate(current, previous)
        self.assertTrue(any("reopen_reason" in error for error in errors))
        current["findings"][0]["reopen_reason"] = "新排版再次遮挡主体"
        errors, _ = validate(current, previous)
        self.assertEqual(errors, [])

    def test_sync_requires_readback(self):
        record = complete_review()
        record["sync"]["status"] = "synced"
        errors, _ = validate(record)
        self.assertTrue(any("record_id" in error for error in errors))

    def test_template_cannot_be_used_as_real_review(self):
        record = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        errors, _ = validate(record)
        self.assertTrue(any("template_only" in error for error in errors))

    def test_final_facts_must_block_when_pending(self):
        record = complete_review()
        record["stage"] = "final"
        record["decision"]["ai_recommendation"] = "final_ready"
        for gate in record["gates"]:
            if gate["id"] in {"asset_materials", "copy_facts"}:
                gate["blocking"] = True
        errors, total = validate(record)
        self.assertEqual(errors, [])
        self.assertEqual(total, 100)
        facts = next(gate for gate in record["gates"] if gate["id"] == "copy_facts")
        facts["status"] = "pending"
        facts["evidence_ids"] = []
        facts["reason"] = "商品参数尚未确认"
        record["decision"]["ai_recommendation"] = "insufficient_evidence"
        facts["blocking"] = False
        errors, total = validate(record)
        self.assertTrue(any("终稿必须作为阻断检查" in error for error in errors))
        facts["blocking"] = True
        errors, total = validate(record)
        self.assertEqual(errors, [])
        self.assertEqual(total, 100)

    def test_bad_field_type_returns_errors_not_exception(self):
        record = complete_review()
        record["stage"] = []
        record["findings"] = [issue()]
        record["findings"][0]["gate_ids"] = [{}]
        errors, _ = validate(record)
        self.assertTrue(any("stage必须" in error for error in errors))
        self.assertTrue(any("gate_ids无效" in error for error in errors))

    def test_case_metadata_is_checked_when_present(self):
        record = complete_review()
        record["product_category"] = ""
        record["reviewed_at"] = "2026-10-20T10:00:00"
        errors, _ = validate(record)
        self.assertTrue(any("product_category" in error for error in errors))
        self.assertTrue(any("reviewed_at" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
