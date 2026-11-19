#!/usr/bin/env python3
"""Search a generated KOCOTREE case index without changing it."""

import argparse
import json
import sys
from pathlib import Path


def search(index, category=None, dimension=None, query=None):
    results = []
    for case in index.get("cases", []):
        if category and category.casefold() not in case["product_category"].casefold():
            continue
        if dimension and dimension != case["dimension_id"]:
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
        if index.get("schema_version") != "1.0" or not isinstance(index.get("cases"), list):
            raise ValueError("案例索引格式无效")
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
