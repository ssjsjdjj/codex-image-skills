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
            index = build_cases(root)
            self.assertEqual(index["cases"], [])
            self.assertEqual(len(index["skipped_candidates"]), 1)
            self.assertEqual(index["skipped_candidates"][0]["finding_id"], "F001")
            self.assertEqual(index["skipped_candidates"][0]["reason_code"], "supervisor_unapproved")
            self.assertIn(second["review_id"], render_reference(index))
            second["decision"]["supervisor"] = {
                "status": "recorded", "decision": "direction_approved", "reason": "确认解决",
                "calibrated_score": None,
            }
            save(root, first, second)
            index = build_cases(root)
            self.assertEqual(len(index["cases"]), 1)
            self.assertEqual(index["skipped_candidates"], [])

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

    def test_suggestions_do_not_become_cases(self):
        first, second = records()
        for record in (first, second):
            record["findings"][0].update(kind="suggestion", expected_benefit="改善主体展示")
            record["decision"]["ai_recommendation"] = "direction_ready"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root, first, second)
            index = build_cases(root)
            self.assertEqual(index["cases"], [])
            self.assertEqual(index["skipped_candidates"], [])

    def test_revoked_approval_removes_previously_generated_case(self):
        first, second = records()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root, first, second)
            self.assertEqual(len(build_cases(root)["cases"]), 1)
            second["decision"]["supervisor"].update(status="pending", decision=None, reason=None)
            save(root, first, second)
            index = build_cases(root)
            self.assertEqual(index["cases"], [])
            self.assertEqual(len(index["skipped_candidates"]), 1)

    def test_repeated_unapproved_closures_are_counted_once_and_clear_on_reopen(self):
        first, second = records()
        second["decision"]["supervisor"].update(status="pending", decision=None, reason=None)
        third = copy.deepcopy(second)
        third.update(review_id="P001-revision-3.0", version="3.0", reviewed_at="2026-10-22T10:00:00+08:00")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root, first, second, third)
            index = build_cases(root)
            self.assertEqual(len(index["skipped_candidates"]), 1)
            self.assertEqual(index["skipped_candidates"][0]["review_id"], third["review_id"])
            third["findings"][0].update(status="pending", reopen_reason="再次复核素材")
            third["decision"]["ai_recommendation"] = "insufficient_evidence"
            save(root, first, second, third)
            self.assertEqual(build_cases(root)["skipped_candidates"], [])

    def test_resolved_again_reuses_case_id_with_new_evidence_cycle(self):
        first, second = records()
        third = copy.deepcopy(second)
        third.update(review_id="P001-revision-3.0", version="3.0", reviewed_at="2026-10-22T10:00:00+08:00")
        third["findings"][0].update(status="open", reopen_reason="新排版再次遮挡")
        third["decision"]["ai_recommendation"] = "needs_revision"
        third["decision"]["supervisor"].update(status="pending", decision=None, reason=None)
        fourth = copy.deepcopy(second)
        fourth.update(review_id="P001-revision-4.0", version="4.0", reviewed_at="2026-10-23T10:00:00+08:00")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root, first, second)
            original = build_cases(root)["cases"][0]
            save(root, first, second, third, fourth)
            latest = build_cases(root)["cases"][0]
            self.assertEqual(latest["case_id"], original["case_id"])
            self.assertEqual(latest["before"]["review_id"], third["review_id"])
            self.assertEqual(latest["after"]["review_id"], fourth["review_id"])

    def test_duplicate_ids_or_instants_reject_version_sequence(self):
        for field, value in (("review_id", "P001-initial-1.0"), ("reviewed_at", "2026-10-20T02:00:00Z")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                first, second = records()
                second[field] = value
                root = Path(temporary)
                save(root, first, second)
                with self.assertRaisesRegex(ValueError, "版本衔接校验失败"):
                    build_cases(root)

    def test_continuing_closed_does_not_replace_resolution_snapshot(self):
        first, second = records()
        third = copy.deepcopy(second)
        third.update(review_id="P001-revision-3.0", version="3.0", reviewed_at="2026-10-22T10:00:00+08:00")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save(root, first, second, third)
            self.assertEqual(build_cases(root)["cases"][0]["after"]["review_id"], second["review_id"])


if __name__ == "__main__":
    unittest.main()
