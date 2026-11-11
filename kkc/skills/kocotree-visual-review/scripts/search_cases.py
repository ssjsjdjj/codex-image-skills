#!/usr/bin/env python3
"""Search a generated KOCOTREE case index without changing it."""

import argparse
import json
import sys
from pathlib import Path


def validate_index(index):
    """Check the fields consumed by search and its CLI before using them."""
    if not isinstance(index, dict) or index.get("schema_version") != "1.0" or not isinstance(index.get("cases"), list):
        raise ValueError("案例索引格式无效：须包含schema_version=1.0和cases数组")
    for position, case in enumerate(index["cases"]):
        label = f"cases[{position}]"
        if not isinstance(case, dict):
            raise ValueError(f"{label}须为对象")
        for field in ("case_id", "product_category", "product_name", "description", "action", "acceptance"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                raise ValueError(f"{label}.{field}须为非空字符串")
        dimension = case.get("dimension_id")
        if dimension is not None and (not isinstance(dimension, str) or not dimension.strip()):
            raise ValueError(f"{label}.dimension_id须为非空字符串或null")
        for side in ("before", "after"):
            snapshot = case.get(side)
            if not isinstance(snapshot, dict) or not isinstance(snapshot.get("review_id"), str) or not snapshot["review_id"].strip():
                raise ValueError(f"{label}.{side}.review_id须为非空字符串")
            artifact = snapshot.get("artifact")
            if not isinstance(artifact, dict) or not isinstance(artifact.get("uri"), str) or not artifact["uri"].strip():
                raise ValueError(f"{label}.{side}.artifact.uri须为非空字符串")


def search(index, category=None, dimension=None, query=None):
    validate_index(index)
    results = []
    for case in index.get("cases", []):
        if category and category.casefold() not in case["product_category"].casefold():
            continue
        if dimension and dimension != case.get("dimension_id"):
            continue
        searchable = " ".join(str(case.get(field) or "") for field in (
            "product_category", "product_name", "description", "action", "acceptance", "dimension_id"
        ))
        if query and query.casefold() not in searchable.casefold():
            continue
        results.append(case)
    return results

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=Path, help="build_case_library.py生成的case-index.json")
    parser.add_argument("--category")
    parser.add_argument("--dimension")
    parser.add_argument("--query")
    args = parser.parse_args(argv)
    try:
        index = json.loads(args.index.read_text(encoding="utf-8"))
        results = search(index, args.category, args.dimension, args.query)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    for case in results:
        print(f"{case['case_id']} | {case['product_category']} | {case['description']}")
        print(f"  前：{case['before']['review_id']} {case['before']['artifact']['uri']}")
        print(f"  后：{case['after']['review_id']} {case['after']['artifact']['uri']}")
    print(f"匹配{len(results)}例")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
