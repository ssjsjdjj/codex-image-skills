"""Validate a product's Photoshop layer bindings and build its editable long PSD."""

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = Path.home() / "Desktop" / "产品信息T.psb"
TABLE_COLUMNS = {"03选尺码": 7, "05尺码快选": 8}
ADAPTIVE_TABLES = {*TABLE_COLUMNS, "试穿报告"}


def configured_template() -> Path:
    profile = json.loads((SCRIPT_DIR / "template_profile.json").read_text(encoding="utf-8"))
    if profile["default"] == "classic":
        return DEFAULT_TEMPLATE
    candidates = [Path(value).expanduser() for value in profile[profile["default"]]]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ValueError("找不到当前默认母版，请恢复路径或在任务 JSON 显式指定 template："
                     + "、".join(map(str, candidates)))


def template_dimensions(template: Path) -> tuple[int, int]:
    with template.open("rb") as file:
        header = file.read(26)
    if len(header) != 26 or header[:6] not in {b"8BPS\0\1", b"8BPS\0\2"}:
        raise ValueError(f"母版没有有效的 PSD/PSB 文件头 {template}")
    return int.from_bytes(header[18:22], "big"), int.from_bytes(header[14:18], "big")


def resolve_path(base: Path, value: object, field: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} 必须是非空路径")
    return (base / value).resolve()


def normalize_table(matrix: object, name: str, adaptive: bool = False) -> list[list[str]]:
    if not isinstance(matrix, list) or not matrix or not isinstance(matrix[0], list) or not matrix[0]:
        raise ValueError(f"{name} 必须是包含表头的非空二维数组")
    width = len(matrix[0])
    if len(matrix) < 2 or width < 2:
        raise ValueError(f"{name} 至少需要 1 行数据和 2 列")
    if not adaptive and (len(matrix) > 8 or width > TABLE_COLUMNS[name]):
        raise ValueError(f"{name} 需有 1–7 行数据和 2–{TABLE_COLUMNS[name]} 列")
    result = []
    for row_index, row in enumerate(matrix, start=1):
        if not isinstance(row, list) or len(row) != width:
            raise ValueError(f"{name} 第 {row_index} 行列数与表头不一致")
        if any(cell is not None and type(cell) not in (str, int, float) for cell in row):
            raise ValueError(f"{name} 第 {row_index} 行有不支持的单元格类型")
        result.append(["" if cell is None else str(cell) for cell in row])
    return result


def load_job(job_path: Path) -> dict:
    job = json.loads(job_path.read_text(encoding="utf-8-sig"))
    if not isinstance(job, dict):
        raise ValueError("任务文件的顶层必须是对象")
    allowed_keys = {"template", "output", "text", "images", "tables"}
    unknown_keys = job.keys() - allowed_keys
    if unknown_keys:
        raise ValueError(f"未知任务字段 {', '.join(sorted(unknown_keys))}")
    base = job_path.resolve().parent
    template_value = job["template"] if "template" in job else str(configured_template())
    template = resolve_path(base, template_value, "template")
    output = resolve_path(base, job.get("output"), "output")
    if template.suffix.lower() not in {".psb", ".psd"} or not template.is_file():
        raise ValueError(f"母版必须是可读取的 PSD/PSB 文件 {template}")
    if output.suffix.lower() not in {".psd", ".psb"} or output == template:
        raise ValueError("output 必须是与母版不同的 .psd 或 .psb 路径")
    if output.exists():
        raise ValueError(f"输出路径已存在 {output}")
    width, height = template_dimensions(template)
    adaptive = (width, height) == (790, 40000)
    if output.suffix.lower() == ".psd" and max(width, height) > 30000:
        raise ValueError(f"母版画布 {width} × {height} px 超过 PSD 30000 px 的单边上限，"
                         "保留整页时请将 output 改为 .psb")

    job.update(template=str(template), output=str(output))
    seen_paths = set()
    for key, field in (("text", "value"), ("images", "source")):
        items = job.setdefault(key, [])
        if not isinstance(items, list):
            raise ValueError(f"{key} 必须是数组")
        for index, item in enumerate(items):
            if not isinstance(item, dict) or set(item) != {"path", field}:
                raise ValueError(f"{key}[{index}] 必须包含 path 和 {field}")
            path = item["path"]
            if not isinstance(path, list) or not path or not all(isinstance(part, str) and part for part in path):
                raise ValueError(f"{key}[{index}].path 必须是完整的图层名数组")
            if tuple(path) in seen_paths:
                raise ValueError(f"同一图层绑定了多次 {' / '.join(path)}")
            seen_paths.add(tuple(path))
            if key == "text":
                if not isinstance(item[field], str):
                    raise ValueError(f"{key}[{index}].value 必须是字符串")
            else:
                source = resolve_path(base, item[field], f"{key}[{index}].source")
                if not source.is_file():
                    raise ValueError(f"找不到图片素材 {source}")
                item[field] = str(source)

    tables = job.get("tables", {})
    supported = ADAPTIVE_TABLES if adaptive else TABLE_COLUMNS.keys()
    if not isinstance(tables, dict) or tables.keys() - supported:
        raise ValueError("当前母版的 tables 支持 " + "、".join(sorted(supported)))
    job["tables"] = {name: normalize_table(matrix, name, adaptive) for name, matrix in tables.items()}
    return job


def create_script(job: dict) -> str:
    sources = ("mixed_detail_fonts.jsx", "native_detail_template.jsx", "adaptive_detail_tables.jsx",
               "editable_long_psd.jsx")
    engine = "\n\n".join((SCRIPT_DIR / name).read_text(encoding="utf-8-sig").rstrip() for name in sources)
    arguments = json.dumps(job, ensure_ascii=True, allow_nan=False)
    return f"{engine.rstrip()}\n\nbuildEditableLongPsd({arguments});\n"


def run_script(path: Path) -> None:
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "$photoshop = New-Object -ComObject Photoshop.Application; "
        "$photoshop.DoJavaScriptFile($env:DETAIL_LONG_PSD_JSX)"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        env={**os.environ, "DETAIL_LONG_PSD_JSX": str(path)},
        check=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path, help="商品及图层绑定 JSON")
    parser.add_argument("--job-script", type=Path, help="导出可在 Photoshop 中运行的 JSX")
    parser.add_argument("--run", action="store_true", help="通过 Windows COM 在 Photoshop 中执行")
    args = parser.parse_args()
    if not args.run and args.job_script is None:
        parser.error("需要指定 --job-script 或 --run")
    try:
        job = load_job(args.job)
        script = create_script(job)
        Path(job["output"]).parent.mkdir(parents=True, exist_ok=True)
        if args.job_script is not None:
            script_path = args.job_script.resolve()
            if script_path.suffix.lower() != ".jsx":
                raise ValueError("--job-script 必须以 .jsx 结尾")
            script_path.parent.mkdir(parents=True, exist_ok=True)
            with script_path.open("x", encoding="utf-8-sig") as file:
                file.write(script)
            print(f"JSX 已生成 {script_path}", flush=True)
        if args.run:
            if args.job_script is not None:
                run_script(script_path)
            else:
                with tempfile.TemporaryDirectory(prefix="editable-long-psd-") as directory:
                    script_path = Path(directory) / "build.jsx"
                    script_path.write_text(script, encoding="utf-8-sig")
                    run_script(script_path)
            if not Path(job["output"]).is_file():
                raise ValueError("Photoshop 执行后未找到 PSD 成品")
            print(f"PSD 已生成 {job['output']}")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
