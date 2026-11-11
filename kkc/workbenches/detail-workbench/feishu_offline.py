"""Convert copied or exported Feishu rows into the workbench's local data format."""

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from feishu_import import (COLOR_FIELDS, INFO_FIELDS, STRUCTURED_FIELDS, TABLE_FIELDS,
                           color_values, field_key, find_field, structured_value,
                           table_value, text_value)

MAX_BYTES = 8 * 1024 * 1024


class OfflineImportError(ValueError):
    pass


@dataclass
class OfflineImport:
    data: dict
    source: str
    attachments: list[dict]
    products: dict = field(default_factory=dict)
    scenes: list = field(default_factory=list)


def _product_fields(raw_fields):
    fields = {field_key(name): value for name, value in raw_fields.items()}
    payload = structured_value(find_field(fields, STRUCTURED_FIELDS))
    payload = payload if isinstance(payload, dict) else {}
    info = payload.get("info")
    info = info if isinstance(info, dict) else {}
    warnings = [note for note in payload.get("warnings", []) if isinstance(note, str)] if isinstance(payload.get("warnings"), list) else []
    values = {name: text_value(find_field(fields, aliases)) for name, aliases in INFO_FIELDS.items()}
    code = text_value(info.get("货号"))
    if values["货号"] and code and values["货号"].casefold() != code.casefold():
        payload, info = {}, {}
        warnings = ["表格行款号与内嵌商品资料 JSON 款号不一致，本次保留行内字段，未合并该 JSON。"]
    info = {name: value or text_value(info.get(name)) for name, value in values.items()}
    colors = color_values(find_field(fields, COLOR_FIELDS)) or color_values(payload.get("colors"))
    if not any(info.values()) and not colors:
        raise OfflineImportError("没有识别到商品字段。请连同表头一起复制，至少包含商品名称、款号、尺码、材质或颜色中的一项。")
    data = {"info": info, "colors": colors}
    table_kinds = {}
    for name, aliases in TABLE_FIELDS.items():
        table_kinds.update((field_key(alias), name) for alias in aliases)
        value = find_field(fields, aliases)
        table = table_value(value, name)
        if table is None and isinstance(payload.get(name), dict):
            table = payload[name]
        if table is not None:
            data[name] = table
        elif name != "try_on":
            warnings.append(f"{aliases[0]}尚未取得结构化数据，请核对原表或图片后补入。")
    attachments = []
    for name, value in raw_fields.items():
        text = text_value(value)
        key = field_key(name)
        is_reference = bool(re.search(r"https?://|\.(?:png|jpe?g|webp|pdf|ps[bd]|json)(?:\b|$)", text, re.I))
        if text and is_reference and (key in table_kinds or any(word in key for word in ("图", "附件", "报告", "素材"))):
            if key in table_kinds and table_value(value, table_kinds[key]) is not None:
                continue
            attachments.append({"field": str(name), "name": text})
    if attachments:
        warnings.append("保留了表格中的附件名称和链接，请在图片匹配中选择本地原图；图片中的尺码和试穿数据仍需核对后录入。")
    data["warnings"] = warnings
    return data, attachments


def import_delimited(text, *, row=1, source="剪贴板表格"):
    if not isinstance(text, str) or not text.strip():
        raise OfflineImportError("请粘贴含表头和数据的表格内容。")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise OfflineImportError("本次导入的表格内容超过 8 MB，请只复制目标行和表头。")
    if not re.fullmatch(r"[0-9]{1,5}", str(row).strip()) or not 1 <= int(row) <= 20000:
        raise OfflineImportError("数据行号请填写 1–20000，第一条数据为第 1 行。")
    row = int(row)
    text = text.lstrip("\ufeff").strip("\r\n")
    first_line = text.splitlines()[0]
    delimiter = "\t" if "\t" in first_line else ";" if ";" in first_line and "," not in first_line else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        headers = next(reader)
        headers = [str(header).strip() for header in headers]
        recognized = {field_key(alias) for aliases in INFO_FIELDS.values() for alias in aliases}
        recognized.update(map(field_key, COLOR_FIELDS))
        recognized.update(map(field_key, STRUCTURED_FIELDS))
        if not any(field_key(header) in recognized for header in headers):
            raise OfflineImportError("首行未识别为商品表头。请复制表头和目标数据行，或导入飞书导出的 CSV。")
        keys = [field_key(header) for header in headers if header]
        if len(keys) != len(set(keys)):
            raise OfflineImportError("表头有重名列，请保留每个字段唯一的一列后再导入。")
        record = None
        for index, values in enumerate(reader, 1):
            if index == row:
                record = values
                break
    except (csv.Error, StopIteration):
        raise OfflineImportError("表格内容格式不完整，请重新复制含表头和数据的内容，保留单元格中的换行和引号。") from None
    if record is None:
        raise OfflineImportError(f"本次内容没有第 {row} 条数据。若只复制了目标行与表头，请选择第 1 行。")
    if len(record) != len(headers):
        raise OfflineImportError("目标数据行的列数与表头不一致。请连同完整表头一起复制，保留空单元格。")
    if any(not name and value.strip() for name, value in zip(headers, record)):
        raise OfflineImportError("目标数据中有未命名的列，请补齐该列表头后导入。")
    raw_fields = {name: value for name, value in zip(headers, record) if name}
    data, attachments = _product_fields(raw_fields)
    return OfflineImport(data, f"{source} · 数据第 {row} 行", attachments)


def load_delimited(path, *, row=1):
    path = Path(path).resolve()
    if path.suffix.lower() not in {".csv", ".tsv", ".txt"}:
        raise OfflineImportError("请选择 CSV、TSV 或含表格文本的 TXT 文件。")
    try:
        if path.stat().st_size > MAX_BYTES:
            raise OfflineImportError("表格文件超过 8 MB，请导出目标视图或只复制目标行。")
        content = path.read_bytes()
    except OSError:
        raise OfflineImportError("无法打开该表格文件，请检查路径及文件访问权限。") from None
    encodings = ("utf-16",) if content.startswith((b"\xff\xfe", b"\xfe\xff")) else ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            text = content.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise OfflineImportError("无法识别文件文字编码，请从飞书重新导出 CSV 或以 UTF-8 保存。")
    return import_delimited(text, row=row, source=str(path))
