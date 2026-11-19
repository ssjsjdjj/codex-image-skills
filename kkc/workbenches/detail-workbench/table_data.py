"""Lossless table parsing shared by editing, preview and export validation."""

import math
import re


TABLE_FIELDS = {"03选尺码": "size_table", "05尺码快选": "quick_size", "试穿报告": "try_on"}


def cell_text(cell, *, preserve=False):
    if cell is None:
        return ""
    if type(cell) not in (str, int, float) or isinstance(cell, float) and not math.isfinite(cell):
        raise ValueError("单元格只接受文字、有限数值和空值。")
    value = str(cell) if preserve else str(cell).strip()
    if any(ord(char) < 32 for char in value):
        raise ValueError("单元格内容请保持单行。")
    return value


def _filled(value):
    return bool(value.strip())


def align_table_columns(headers, rows):
    """Remove wholly empty trailing columns and append omitted trailing cells.

    An extra nonempty cell is never truncated. Empty cells between tabs already
    carry their position, so no middle-column inference is needed or attempted.
    """
    if not isinstance(headers, list) or not headers or not isinstance(rows, list):
        raise ValueError("需要表头及数据，表格至少保留一列。")
    head = [cell_text(cell, preserve=True) for cell in headers]
    values = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, list):
            raise ValueError(f"第 {index} 行需要按列填写。")
        values.append([cell_text(cell, preserve=True) for cell in row])
    width = max([len(head), *[len(row) for row in values]])
    while width > 1 and all(width > len(row) or not _filled(row[width - 1]) for row in [head, *values]):
        width -= 1
    if width > len(head):
        index = next(index for index, row in enumerate(values, 1)
                     if any(_filled(value) for value in row[len(head):]))
        raise ValueError(f"第 {index} 行有 {len(values[index - 1])} 列，表头只有 {len(head)} 列；"
                         "多出的非空数据未删除，请先补齐表头，再使用「删除整列」。")
    head = head[:width]
    result = []
    for row in values:
        row = row[:width]
        result.append([*row, *[""] * (width - len(row))])
    return head, result


def normalize_table(headers, rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("需要至少一列及一行有效数据。")
    head, values = align_table_columns(headers, rows)
    for index, value in enumerate(head, 1):
        if not _filled(value):
            raise ValueError(f"第 {index} 列缺少表头，请填写名称或删除整列。")
    for index, row in enumerate(values, 1):
        if not any(_filled(value) for value in row):
            raise ValueError(f"第 {index} 行没有有效数据。")
    return [head, *values]


def normalize_editor_matrix(lines, *, quick=False):
    if not lines:
        raise ValueError("需要表头及数据。")
    matrix = normalize_table(lines[0], lines[1:])
    if quick:
        if len(matrix[0]) < 2:
            raise ValueError("尺码快选需要保留行标题和至少一列推荐尺码。")
        for index, row in enumerate(matrix[1:], 1):
            if not _filled(row[0]):
                raise ValueError(f"尺码快选第 {index} 行缺少身高区间。")
    return matrix


def quick_table(quick):
    if not isinstance(quick, dict):
        raise ValueError("需要包含身高、体重区间与推荐数据的对象。")
    columns, labels, rows = (quick[key] for key in ("columns", "rows", "data"))
    if not all(isinstance(value, list) for value in (columns, labels, rows)) or len(labels) != len(rows):
        raise ValueError("身高区间与推荐行数不一致。")
    if not all(isinstance(row, list) for row in rows):
        raise ValueError("快选数据需要二维数组。")
    return normalize_editor_matrix([[quick.get("axis_label", "身高/体重"), *columns],
                                    *[[label, *row] for label, row in zip(labels, rows)]], quick=True)


def fit_table(trial):
    if not isinstance(trial, dict):
        raise ValueError("需要包含 headers 与 rows 的对象。")
    matrix = normalize_table(trial["headers"], trial["rows"])
    if matrix[0] != ["姓名", "性别", "身高", "体重", "试穿尺码", "胸围/腰围/臀围"]:
        return matrix
    rows = []
    for label, gender, height, weight, result, measurements in matrix[1:]:
        parts = measurements.split("/") if measurements.strip() else ["", "", ""]
        if len(parts) != 3:
            raise ValueError("胸围/腰围/臀围应为三个以 / 分隔的值。")
        match = re.fullmatch(r"(\d+)(?:码)?\s*(.*)", result.strip())
        size, feedback = match.groups() if match else (result, "")
        rows.append([f"{label}（{gender}）" if gender.strip() else label, height, weight, *parts, size, feedback])
    return [["用户试穿", "身高", "体重", "胸围", "腰围", "臀围", "试穿码数", "试穿反馈"], *rows]


def _has_table_content(value):
    if value is None or value == {}:
        return False
    if isinstance(value, dict):
        return any(value.get(key) for key in ("headers", "columns", "rows", "data"))
    return bool(value)


def resolve_tables(data, profile=None):
    """Return valid independent matrices and per-table issue strings, unchanged input."""
    tables, issues = {}, {}
    readers = {"03选尺码": lambda value: normalize_table(value["headers"], value["rows"]),
               "05尺码快选": quick_table, "试穿报告": fit_table}
    available = None
    if profile:
        modules = profile.get("modules", [])
        modules = modules.values() if isinstance(modules, dict) else modules
        available = {module["table"]["key"] for module in modules if module.get("table")}
    for title, field in TABLE_FIELDS.items():
        value = data.get(field)
        if title == "试穿报告" and isinstance(value, dict) and value.get("rows") == []:
            continue
        if not _has_table_content(value):
            continue
        if available is not None and title not in available:
            issues[title] = "当前母版没有该表模块，原数据保留在资料包中。"
            continue
        try:
            if not isinstance(value, dict):
                raise ValueError("表格资料需要按表头和数据行填写。")
            tables[title] = readers[title](value)
        except (KeyError, TypeError, ValueError) as error:
            issues[title] = f"缺少字段 {error.args[0]}。" if isinstance(error, KeyError) else str(error)
    return tables, issues


def parse_table_text(value):
    """Keep blank cells and spaces inside a TSV row; ignore entirely blank lines."""
    return [line.split("\t") for line in value.splitlines() if line.strip()]


def table_editor_matrix(data, title):
    """Expose an unnormalized source table for repair without losing extra cells."""
    value = data.get(TABLE_FIELDS[title]) if isinstance(data, dict) else None
    if not isinstance(value, dict):
        return None
    if title == "05尺码快选":
        columns, labels, rows = (value.get(key, []) for key in ("columns", "rows", "data"))
        if not all(isinstance(part, list) for part in (columns, labels, rows)) or not all(isinstance(row, list) for row in rows):
            return None
        matrix = [[value.get("axis_label", "身高/体重"), *columns]]
        for index in range(max(len(labels), len(rows))):
            matrix.append([labels[index] if index < len(labels) else "", *(rows[index] if index < len(rows) else [])])
    else:
        headers, rows = value.get("headers", []), value.get("rows", [])
        if not isinstance(headers, list) or not isinstance(rows, list) or not all(isinstance(row, list) for row in rows):
            return None
        matrix = [headers, *rows]
    if not any(matrix):
        return None
    return [["" if cell is None else str(cell) for cell in row] for row in matrix]


def delete_table_column(matrix, column, *, quick=False):
    if not matrix:
        raise ValueError("请先粘贴表格。")
    head, rows = align_table_columns(matrix[0], matrix[1:])
    if not isinstance(column, int) or not 0 <= column < len(head):
        raise ValueError("请选择要删除的列。")
    if quick and column == 0:
        raise ValueError("尺码快选的第一列是身高区间，请保留该列。")
    if len(head) <= (2 if quick else 1):
        raise ValueError("尺码快选需要保留行标题和至少一列推荐尺码。" if quick else "表格至少保留一列。")
    return [[*row[:column], *row[column + 1:]] for row in [head, *rows]]
