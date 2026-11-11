"""Exercise the public commands using temporary, synthetic review records."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_case_library import records, save


SCRIPTS = Path(__file__).resolve().parent


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.reviews = self.root / "审核记录"
        self.reviews.mkdir()
        self.output = self.root / "案例输出"

    def run_script(self, name, *args, expected=0):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(SCRIPTS / name), *map(str, args)],
            capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def test_validate_build_search_and_rebuild(self):
        first, second = records()
        save(self.reviews, first, second)
        self.run_script("validate_review.py", self.reviews / "01.json")
        result = self.run_script("validate_review.py", self.reviews / "02.json", "--previous", self.reviews / "01.json")
        self.assertIn("100/100", result.stdout)
        self.run_script("build_case_library.py", self.reviews, "--out-dir", self.output)
        index_path = self.output / "case-index.json"
        content = index_path.read_bytes()
        index = json.loads(content)
        self.assertEqual(len(index["cases"]), 1)
        self.assertEqual(index["cases"][0]["after"]["evidence"][0]["id"], "E002")
        self.assertIn(index["cases"][0]["case_id"], (self.output / "case-reference.md").read_text(encoding="utf-8"))
        result = self.run_script("search_cases.py", index_path, "--category", "上衣", "--dimension", "product_visibility", "--query", "遮挡")
        self.assertIn("匹配1例", result.stdout)
        result = self.run_script("search_cases.py", index_path, "--query", "主体遮挡")
        self.assertIn("匹配0例", result.stdout)
        self.run_script("build_case_library.py", self.reviews, "--out-dir", self.output)
        self.assertEqual(index_path.read_bytes(), content)

    def test_pending_approval_is_reported_in_index_reference_and_cli(self):
        first, second = records()
        second["decision"]["supervisor"].update(status="pending", decision=None, reason=None)
        save(self.reviews, first, second)
        result = self.run_script("build_case_library.py", self.reviews, "--out-dir", self.output)
        self.assertIn("1个已关闭问题待主管批准", result.stdout)
        index = json.loads((self.output / "case-index.json").read_text(encoding="utf-8"))
        self.assertEqual(len(index["skipped_candidates"]), 1)
        self.assertIn("F001", (self.output / "case-reference.md").read_text(encoding="utf-8"))

    def test_invalid_record_does_not_replace_either_output(self):
        first, second = records()
        save(self.reviews, first, second)
        self.run_script("build_case_library.py", self.reviews, "--out-dir", self.output)
        before = {path.name: path.read_bytes() for path in self.output.iterdir()}
        second["reviewed_at"] = "2026-10-21T10:00:00"
        save(self.reviews, first, second)
        result = self.run_script("validate_review.py", self.reviews / "02.json", expected=1)
        self.assertIn("reviewed_at", result.stderr)
        self.run_script("build_case_library.py", self.reviews, "--out-dir", self.output, expected=1)
        self.assertEqual({path.name: path.read_bytes() for path in self.output.iterdir()}, before)

    def test_malformed_indexes_report_readable_errors(self):
        first, second = records()
        save(self.reviews, first, second)
        self.run_script("build_case_library.py", self.reviews, "--out-dir", self.output)
        index_path = self.output / "case-index.json"
        valid = json.loads(index_path.read_text(encoding="utf-8"))
        wrong_category = copy.deepcopy(valid)
        wrong_category["cases"][0]["product_category"] = []
        missing_artifact = copy.deepcopy(valid)
        del missing_artifact["cases"][0]["after"]["artifact"]
        for payload in ([], {"schema_version": "1.0", "cases": [None]}, wrong_category, missing_artifact):
            with self.subTest(payload=payload):
                index_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                self.run_script("search_cases.py", index_path, expected=1)

    def test_help_usage_and_missing_file_exit_codes(self):
        for name in ("validate_review.py", "build_case_library.py", "search_cases.py"):
            with self.subTest(script=name):
                self.run_script(name, "--help")
                self.run_script(name, expected=2)
        self.run_script("validate_review.py", self.root / "missing.json", expected=1)
        self.run_script("search_cases.py", self.root / "missing.json", expected=1)
        self.run_script("build_case_library.py", self.root / "missing", "--out-dir", self.output, expected=1)

    def test_null_previous_record_does_not_silently_skip_linkage(self):
        _, second = records()
        save(self.reviews, second)
        previous = self.reviews / "previous.json"
        previous.write_text("null", encoding="utf-8")
        result = self.run_script("validate_review.py", self.reviews / "01.json", "--previous", previous, expected=1)
        self.assertIn("上一版记录根节点必须为对象", result.stderr)


if __name__ == "__main__":
    unittest.main()
