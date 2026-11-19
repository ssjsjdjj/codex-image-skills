"""Behavioral checks for case promotion, withdrawal, search and reproducibility."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from build_case_library import build_cases, render_reference, write_index
from search_cases import search
from test_validate_review import complete_review, issue


def records():
    first = complete_review()
    first["findings"] = [issue()]
    first["decision"]["ai_recommendation"] = "needs_revision"
    second = copy.deepcopy(first)
    second["review_id"] = "P001-revision-2.0"
    second["version"] = "2.0"
    second["stage"] = "revision"
    second["reviewed_at"] = "2026-10-21T10:00:00+08:00"
    second["artifact"]["name"] = "P001-revision-2.0.pdf"
    second["artifact"]["uri"] = "P001-revision-2.0.pdf"
    second["evidence"] = [{
        "id": "E002", "locator": "详情第1模块，主商品", "observation": "关键结构已经完整露出",
        "source": "visual", "source_ref": "P001-revision-2.0.pdf",
    }]
    for score in second["scores"]:
        score["evidence_ids"] = ["E002"]
    for gate in second["gates"]:
        gate["evidence_ids"] = ["E002"]
    second["findings"][0]["status"] = "closed"
    second["findings"][0]["evidence_ids"] = ["E002"]
    second["findings"][0]["closure_evidence_ids"] = ["E002"]
    second["decision"]["ai_recommendation"] = "direction_ready"
    second["decision"]["supervisor"] = {
        "status": "recorded", "decision": "direction_approved", "reason": "已核对返稿",
        "calibrated_score": None,
    }
    return first, second


def save(directory, *items):
    for index, record in enumerate(items, start=1):
        (directory / f"{index:02d}.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


class CaseLibraryTests(unittest.TestCase):
    def test_approved_resolution_is_traceable_and_searchable(self):
        first, second = records()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root, first, second)
            index = build_cases(root, root / "case-library")
            self.assertEqual(len(index["cases"]), 1)
            case = index["cases"][0]
            self.assertEqual(case["before"]["review_id"], first["review_id"])
            self.assertEqual(case["after"]["review_id"], second["review_id"])
            self.assertEqual(case["after"]["evidence"][0]["locator"], "详情第1模块，主商品")
            self.assertEqual(search(index, category="上衣", dimension="product_visibility", query="遮挡"), [case])
            self.assertEqual(search(index, category="鞋子"), [])
            self.assertIn(case["case_id"], render_reference(index))
            write_index(index, root / "case-library")
            self.assertEqual(build_cases(root, root / "case-library"), index)

    def test_unapproved_closure_waits_for_supervisor_and_can_be_confirmed_later(self):
        first, second = records()
        second["decision"]["supervisor"] = {
            "status": "pending", "decision": None, "reason": None, "calibrated_score": None,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root, first, second)
            self.assertEqual(build_cases(root)["cases"], [])
            second["decision"]["supervisor"] = {
                "status": "recorded", "decision": "direction_approved", "reason": "确认解决",
                "calibrated_score": None,
            }
            save(root, first, second)
            self.assertEqual(len(build_cases(root)["cases"]), 1)

    def test_reopened_issue_withdraws_case(self):
        first, second = records()
        third = copy.deepcopy(second)
        third["review_id"] = "P001-revision-3.0"
        third["version"] = "3.0"
        third["reviewed_at"] = "2026-10-22T10:00:00+08:00"
        third["findings"][0]["status"] = "open"
        third["findings"][0]["reopen_reason"] = "新排版再次遮挡"
        third["findings"][0].pop("closure_evidence_ids")
        third["decision"]["ai_recommendation"] = "needs_revision"
        third["decision"]["supervisor"] = {
            "status": "pending", "decision": None, "reason": None, "calibrated_score": None,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root, first, second, third)
            self.assertEqual(build_cases(root)["cases"], [])

    def test_missing_metadata_skips_entire_project(self):
        first, second = records()
        del second["reviewed_at"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root, first, second)
            index = build_cases(root)
            self.assertEqual(index["cases"], [])
            self.assertEqual(index["skipped_projects"][0]["project_id"], "P001")

    def test_invalid_record_does_not_overwrite_index(self):
        first, second = records()
        second["findings"][0]["closure_evidence_ids"] = ["MISSING"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root, first, second)
            out = root / "case-library"
            out.mkdir()
            (out / "case-index.json").write_text("old index", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "校验失败"):
                write_index(build_cases(root, out), out)
            self.assertEqual((out / "case-index.json").read_text(encoding="utf-8"), "old index")


if __name__ == "__main__":
    unittest.main()
