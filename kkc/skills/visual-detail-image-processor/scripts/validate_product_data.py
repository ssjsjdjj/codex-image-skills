from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_TOP_KEYS = {"info", "size_table", "quick_size"}
INFO_KEYS = ["名称", "货号", "材质", "颜色", "尺码"]


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def as_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        fail(f"{name} must be a list")
    return value


def validate_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail(f"{path} root must be an object")

    missing = REQUIRED_TOP_KEYS - set(data)
    if missing:
        fail(f"{path} missing keys: {', '.join(sorted(missing))}")

    info = data["info"]
    if not isinstance(info, dict):
        fail(f"{path} info must be an object")
    for key in INFO_KEYS:
        info.setdefault(key, "")

    size = data["size_table"]
    if not isinstance(size, dict):
        fail(f"{path} size_table must be an object")
    headers = as_list(size.get("headers"), f"{path} size_table.headers")
    rows = as_list(size.get("rows"), f"{path} size_table.rows")
    if not headers:
        fail(f"{path} size_table.headers cannot be empty")
    for idx, row in enumerate(rows):
        if not isinstance(row, list):
            fail(f"{path} size_table.rows[{idx}] must be a list")
        if len(row) > len(headers):
            fail(f"{path} size_table.rows[{idx}] has more cells than headers")

    quick = data["quick_size"]
    if not isinstance(quick, dict):
        fail(f"{path} quick_size must be an object")
    cols = as_list(quick.get("columns"), f"{path} quick_size.columns")
    qrows = as_list(quick.get("rows"), f"{path} quick_size.rows")
    matrix = as_list(quick.get("data"), f"{path} quick_size.data")
    if not cols or not qrows:
        fail(f"{path} quick_size columns/rows cannot be empty")
    if len(matrix) != len(qrows):
        fail(f"{path} quick_size.data row count must match quick_size.rows")
    for idx, row in enumerate(matrix):
        if not isinstance(row, list):
            fail(f"{path} quick_size.data[{idx}] must be a list")
        if len(row) > len(cols):
            fail(f"{path} quick_size.data[{idx}] has more cells than columns")

    return data


def iter_json_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    seen: set[Path] = set()
    files: list[Path] = []
    for pattern in ("product_data.json", "产品数据.json", "*.json"):
        for file in sorted(path.rglob(pattern) if pattern != "*.json" else path.glob(pattern)):
            resolved = file.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(file)
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate visual detail product_data.json files.")
    parser.add_argument("path", help="A JSON file or a folder containing product data JSON files.")
    args = parser.parse_args()

    files = iter_json_files(Path(args.path))
    if not files:
        fail("no JSON files found")
    ok = []
    for file in files:
        validate_file(file)
        ok.append(str(file))
    print(json.dumps({"validated": ok, "count": len(ok)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
