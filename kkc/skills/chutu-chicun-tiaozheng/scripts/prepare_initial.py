#!/usr/bin/env python3
"""创建独立初始草案和测试预览；不会安装或初始化个人正式版本。"""
import argparse
import json
import shutil
from pathlib import Path

from user_profile import read_json, snapshot_digest, write_json
from validate_candidate import validate_snapshot
from task_spec import load_jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="新的测试目录，不覆盖现有内容")
    parser.add_argument("--spec", help="实际素材的测试任务单，可含 defaults 和 jobs")
    args = parser.parse_args()
    output = Path(args.out).resolve()
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "snapshot"
    snapshot.mkdir()
    assets = Path(__file__).resolve().parents[1] / "assets"
    for original, name in (("settings.example.json", "settings.json"),
                           ("personal_prompt.example.md", "personal_prompt.md"), ("renderer.py", "renderer.py")):
        shutil.copyfile(assets / original, snapshot / name)
    jobs = []
    if args.spec:
        jobs = load_jobs(args.spec)
    report = validate_snapshot(snapshot, output / "previews", jobs)
    write_json(output / "validation.json", report)
    print(json.dumps({"draft": str(output), "digest": snapshot_digest(snapshot), "passed": report["passed"],
                      "report": str(output / "validation.json"), "activated": False}, ensure_ascii=False, indent=2))
    if not report["passed"]:
        parser.exit(2, "[错误] 初始草案验证失败，不能生效\n")


if __name__ == "__main__":
    main()
