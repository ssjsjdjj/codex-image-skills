from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path


TEMPLATE = {
    "info": {
        "名称": "",
        "货号": "",
        "材质": "",
        "颜色": "",
        "尺码": "",
    },
    "colors": [],
    "size_table": {
        "headers": ["尺码"],
        "rows": [[""]],
    },
    "quick_size": {
        "columns": [""],
        "rows": [""],
        "data": [[""]],
    },
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create product_data.json placeholders for product folders.")
    parser.add_argument("--input-root", required=True, help="Root folder containing product folders.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing product_data.json files.")
    args = parser.parse_args()

    root = Path(args.input_root)
    created = []
    skipped = []
    for product_dir in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.name):
        path = product_dir / "product_data.json"
        if path.exists() and not args.overwrite:
            skipped.append(str(path))
            continue
        data = deepcopy(TEMPLATE)
        data["source_product_folder"] = product_dir.name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        created.append(str(path))
    print(json.dumps({"created": created, "skipped": skipped}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
