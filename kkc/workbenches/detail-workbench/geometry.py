"""One source of layout and photo-crop geometry for the preview and Photoshop."""

import copy
import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

TABLE_ROLES = {"03选尺码": "size_table", "05尺码快选": "quick_size", "试穿报告": "try_on"}
MAX_COLORS = 8
MIN_ZOOM = .1
MAX_ZOOM = 8.
FONTS = Path(__file__).resolve().parent / "fonts"


def finite_number(value, fallback):
    try:
        number = float(value)
        return number if math.isfinite(number) else fallback
    except (TypeError, ValueError, OverflowError):
        return fallback


def normalize_view(state=None):
    state = state if isinstance(state, dict) else {}
    focus = state.get("focus", [.5, .5])
    if not isinstance(focus, (list, tuple)) or len(focus) != 2:
        focus = [.5, .5]
    # At 10% a source-sized image can move across a frame ten times as wide.
    # resolve_crop applies the source/frame-dependent limits on each axis.
    return {"zoom": min(MAX_ZOOM, max(MIN_ZOOM, finite_number(state.get("zoom"), 1.))),
            "focus": [min(5., max(-4., finite_number(value, .5))) for value in focus]}


def contain_zoom(width, height, frame_w, frame_h):
    """Return the closest supported zoom for showing the whole oriented source."""
    values = [finite_number(value, 0) for value in (width, height, frame_w, frame_h)]
    if min(values) <= 0:
        raise ValueError("图片和图框尺寸必须为正数。")
    width, height, frame_w, frame_h = values
    scales = (frame_w / width, frame_h / height)
    return max(MIN_ZOOM, min(scales) / max(scales))


def resolve_crop(width, height, frame_w, frame_h, state=None):
    """Return an EXIF-oriented source pixel crop. A zoom of 1 fills the frame."""
    values = [finite_number(value, 0) for value in (width, height, frame_w, frame_h)]
    if min(values) <= 0:
        raise ValueError("图片和图框尺寸必须为正数。")
    width, height, frame_w, frame_h = values
    state = normalize_view(state)
    ratio = frame_w / frame_h
    if width / height > ratio:
        crop_h = height / state["zoom"]
        crop_w = crop_h * ratio
    else:
        crop_w = width / state["zoom"]
        crop_h = crop_w / ratio
    def center(length, crop, focus):
        first, last = crop / 2, length - crop / 2
        # Filling keeps the old crop inside the source.  A smaller image stays
        # inside the frame, with its free space movable to either side.
        low, high = min(first, last), max(first, last)
        return min(high, max(low, focus * length))

    center_x = center(width, crop_w, state["focus"][0])
    center_y = center(height, crop_h, state["focus"][1])
    return [center_x - crop_w / 2, center_y - crop_h / 2,
            center_x + crop_w / 2, center_y + crop_h / 2]


def crop_state_from_box(width, height, frame_w, frame_h, box):
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return normalize_view()
    left, top, right, bottom = map(float, box)
    base = resolve_crop(width, height, frame_w, frame_h)
    return normalize_view({"zoom": (base[2] - base[0]) / max(1, right - left),
                           "focus": [(left + right) / (2 * width), (top + bottom) / (2 * height)]})


@lru_cache(maxsize=100)
def font_face(kind, px):
    names = {"cn": "cn.ttf", "latin": "latin.otf", "digit": "digit.ttf"}
    try:
        return ImageFont.truetype(str(FONTS / names[kind]), max(1, round(px)))
    except OSError:
        return ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", max(1, round(px)))


def text_width(value, px):
    total = 0.
    for char in str(value):
        kind = "digit" if char in "1%" else "latin" if char.isascii() and (char.isalnum() or char in ".+- ") else "cn"
        total += font_face(kind, px).getlength(char)
    return total


def text_descent(value, px):
    bottom = 0
    for char in str(value):
        kind = "digit" if char in "1%" else "latin" if char.isascii() and (char.isalnum() or char in ".+- ") else "cn"
        bottom = max(bottom, font_face(kind, px).getbbox(char, anchor="ls")[3])
    return bottom


def fit_text_layout(value, rect, style=None, *, avoid_orphans=True):
    """Plan complete mixed-font field text once, without clipping its last line."""
    style = style or {}
    value = str(value)
    width, height = float(rect[2]) - 10, float(rect[3])
    if min(width, height) <= 0:
        raise ValueError("文字区域尺寸无效。")
    initial = min(80., max(16., finite_number(style.get("size_px", style.get("px")), 24.)))
    candidates = [initial - index for index in range(math.ceil(initial - 16) + 1)]
    candidates = [max(16., px) for px in candidates]
    # Keep percentages, dimensions, product codes and ordinary English words
    # intact when a line wraps. Otherwise 100% can become "10" / "0%".
    tokens = re.findall(r"[A-Za-z0-9]+(?:[._/-][A-Za-z0-9]+)*%?|[\s\S]", value)
    for px in candidates:
        lines, line = [], ""
        for token in tokens:
            # A single unusually long word may still require character wraps.
            pieces = list(token) if text_width(token, px) > width else [token]
            for piece in pieces:
                if piece == "\n":
                    lines.append(line)
                    line = ""
                else:
                    if line and text_width(line + piece, px) > width:
                        lines.append(line)
                        line = ""
                    line += piece
        lines.append(line)
        leading = px * 1.15
        required = px + (len(lines) - 1) * leading + text_descent(lines[-1], px)
        orphan = avoid_orphans and len(lines) > 1 and re.fullmatch(r"[\s)\]）】〉》。，、;；:：!！?？]+", lines[-1])
        if required <= height + .5 and not orphan and all(text_width(line, px) <= width + .1 for line in lines):
            return {"value": value, "rect": list(rect), "lines": lines, "px": px, "leading": leading}
    raise ValueError("文字超过当前母版的可读范围，请缩短字段或选择更宽的母版。")


def resolve_text_layout(profile, geometry, info, colors):
    result = {}
    if geometry.get("size_note"):
        result["当前尺码备注"] = geometry["size_note"]
    product_delta = geometry["modules"].get("product", {}).get("delta_y", 0)
    for field, binding in profile.get("fields", {}).items():
        value = "/".join(colors) if field == "颜色" else info.get(field, "")
        rect = _shift(binding["rect"], product_delta)
        result["当前商品 · " + field] = fit_text_layout(value, rect, binding.get("style"))
        if binding.get("generated") and binding.get("label_rect"):
            result["字段名 · " + field] = fit_text_layout(field, _shift(binding["label_rect"], product_delta), {"size_px": 28})
    color_style = profile.get("colors", {}).get("prototype", {}).get("style", {})
    for item in geometry["colors"]["items"]:
        if item["index"] < len(colors):
            label = colors[item["index"]]
            result["当前色名 · " + label] = fit_text_layout(label, item["label_rect"], color_style)
    for module in profile.get("modules", []):
        if not geometry["modules"][module["role"]].get("visible", True):
            continue
        dy = geometry["modules"][module["role"]].get("delta_y", 0)
        for item in module.get("dynamic_texts", []):
            key = item.get("field", "")
            value = item.get("separator", "/").join(colors) if key in {"colors", "颜色"} else info.get(key, "")
            value = item.get("prefix", "") + value
            result["主视觉字段 · " + key] = fit_text_layout(value, _shift(item["rect"], dy), item.get("style"))
    return result


def plan_table(matrix, width, height, style=None):
    """Plan readable, editable cell geometry; the JSX uses this exact result."""
    if not matrix or not matrix[0] or len(matrix) < 2:
        raise ValueError("需要至少一行有效表格数据。")
    columns, row_count = len(matrix[0]), len(matrix) - 1
    if any(len(row) != columns for row in matrix):
        raise ValueError("表格各行列数不一致。")
    style = style or {}
    default_px = finite_number(style.get("px"), 24)
    header_min = finite_number(style.get("headerMin"), 32)
    header = max(header_min, finite_number(style.get("headerHeight"), 65))
    min_row = max(30, min(40, default_px + 10))
    # Grow a module when its original container cannot fit readable rows.
    height = max(float(height), header_min + row_count * min_row)
    header = min(header, height - min_row * row_count)
    row_height = min(round(finite_number(style.get("rowHeight"), 51) * 1.35),
                     math.floor((height - header) / row_count))
    px = math.floor(min(default_px, row_height - 9, header - 10))
    demands = [max(text_width(row[column], default_px) for row in matrix) for column in range(columns)]
    padding = 18 if columns <= 9 else 12
    while px >= 16:
        widths = [max(36, math.ceil(demand * px / default_px) + padding) for demand in demands]
        total = sum(widths)
        if total <= width:
            break
        px -= 1
    if px < 16:
        raise ValueError("表格列内容超出本区可读宽度，请按指标分表。")
    # Water fill the narrower columns without squeezing a long heading/feedback.
    lower, upper = 0., float(width)
    for _ in range(50):
        target = (lower + upper) / 2
        if sum(max(demand, target) for demand in widths) > width:
            upper = target
        else:
            lower = target
    widths = [max(value, lower) for value in widths]
    widths[-1] += width - sum(widths)
    return {"header": header, "row": row_height, "px": px, "widths": widths,
            "height": header + row_count * row_height}


def _rect(value, fallback=None):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return list(fallback or [0, 0, 790, 100])
    return [finite_number(number, 0) for number in value]


def _shift(rect, dy):
    result = list(rect)
    result[1] += dy
    return result


def plan_layout(profile, color_count, tables, scene_count, *, has_hero=True, has_brand=None, size_note=None):
    """Resolve original master geometry into this product's complete page layout."""
    if not isinstance(profile, dict) or not profile.get("modules"):
        raise ValueError("母版缺少版式记录，请重新校验母版。")
    if not 1 <= color_count <= MAX_COLORS:
        raise ValueError(f"商品颜色需要 1–{MAX_COLORS} 个。")
    scene_count = max(0, min(4, int(scene_count)))
    has_brand = bool(scene_count) if has_brand is None else bool(has_brand)
    raw_modules = profile["modules"]
    raw_modules = list(raw_modules.values()) if isinstance(raw_modules, dict) else raw_modules
    modules = {module["role"]: {**copy.deepcopy(module), "original_rect": _rect(module.get("rect")),
                                "rect": _rect(module.get("rect")), "visible": True}
               for module in raw_modules}
    color_spec = profile.get("colors", {})
    colors_module = modules.get("colors")
    if colors_module is None:
        raise ValueError("母版缺少选颜色区域。")
    original_color = colors_module["original_rect"]
    area = _rect(color_spec.get("content_rect", color_spec.get("rect")), original_color)
    prototype = color_spec.get("prototype", {})
    sample_image = _rect(prototype.get("image_rect"), [area[0], area[1] + 50, 210, 250])
    sample_label = _rect(prototype.get("label_rect"), [area[0], sample_image[1] + sample_image[3] + 12, 210, 30])
    rows = math.ceil(color_count / 4)
    columns = math.ceil(color_count / rows)
    gap = max(20., finite_number(color_spec.get("row_gap"), 35))
    row_step = max(sample_image[3] + sample_label[3] + 25,
                   sample_label[1] + sample_label[3] - sample_image[1]) + gap
    items = []
    for row in range(rows):
        count = min(columns, color_count - row * columns)
        span = area[2] / count
        image_width = min(sample_image[2], span - 20)
        for column in range(count):
            center = area[0] + span * (column + .5)
            items.append({"index": len(items),
                          "image_rect": [center - image_width / 2, sample_image[1] + row * row_step,
                                         image_width, sample_image[3]],
                          "label_rect": [center - (span - 12) / 2, sample_label[1] + row * row_step,
                                         span - 12, max(26, sample_label[3])]})
    color_height = original_color[3] + (rows - 1) * row_step
    target_heights = {"colors": color_height}
    table_plans = {}
    measurement = profile.get("view_slots", {}).get("measurement") or {}
    for key, role in TABLE_ROLES.items():
        module = modules.get(role)
        matrix = tables.get(key)
        if module is None:
            if matrix:
                raise ValueError(f"母版没有{key}模块。")
            continue
        if not matrix:
            module["visible"] = False
            target_heights[role] = 0
            continue
        table = module.get("table", {})
        region = _rect(table.get("rect"), [module["rect"][0] + 20, module["rect"][1] + 90,
                                          module["rect"][2] - 40, max(100, module["rect"][3] - 140)])
        if role == "size_table" and measurement.get("beside_table"):
            left, _, width, _ = _rect(measurement["rect"])
            right = region[0] + region[2]
            if left + width <= region[0] + 20:
                region[0] = max(region[0], left + width + 4)
            elif left >= right - 20:
                right = min(right, left - 4)
            region[2] = right - region[0]
        style = table.get("style", {})
        plan = plan_table(matrix, region[2], region[3], style)
        grow = max(0, plan["height"] - region[3])
        module["table_height_delta"] = grow
        target_heights[role] = module["original_rect"][3] + grow
        table_plans[key] = {"region": [*region[:3], plan["height"]], "plan": plan,
                            "spec": {"key": key, **style}, "original_region": region}
    note_layout = None
    note = profile.get("size_note")
    size_module = modules.get("size_table")
    note_paths = set()
    note_shift = 0
    if note and size_module and size_module["visible"] and note.get("after_table"):
        note_paths = {tuple(line["path"]) for line in note["lines"]}
        table_growth = size_module.get("table_height_delta", 0)
        size_region = table_plans["03选尺码"]["region"]
        clearance = max(0, size_region[1] + size_region[3] + 4 - note["rect"][1] - table_growth)
        note_shift = table_growth + clearance
        target_heights["size_table"] += clearance
    if note and size_note and size_module and size_module["visible"]:
        note_rect = _rect(note["rect"])
        picture = measurement.get("rect")
        can_grow = note.get("after_table") and (not picture or picture[1] + picture[3] <= note_rect[1])
        try:
            # Wrap at the template's type size, then keep only the height used.
            fit_rect = [*note_rect[:3], 100 * (len(size_note) + 1)] if can_grow else note_rect
            note_layout = fit_text_layout(size_note, fit_rect, note.get("style"), avoid_orphans=False)
        except ValueError as error:
            raise ValueError(f"尺码备注 · {error}") from error
        px, lines = note_layout["px"], note_layout["lines"]
        height = math.ceil(px + note_layout["leading"] * (len(lines) - 1) + text_descent(lines[-1], px) + 1)
        if can_grow:
            note_layout["rect"][3] = max(height, note_rect[3])
            target_heights["size_table"] += max(0, height - note_rect[3])
    scene_module = modules.get("scenes")
    view_slots = copy.deepcopy(profile.get("view_slots", {}))
    if scene_module:
        if scene_count == 0:
            target_heights["scenes"] = 0
            scene_module["visible"] = False
        else:
            used = [slot for name, slot in view_slots.items()
                    if name.startswith("scene_") and int(name.split("_")[-1]) <= scene_count]
            if used:
                bottom = max(_rect(slot.get("rect"))[1] + _rect(slot.get("rect"))[3] for slot in used)
                target_heights["scenes"] = max(0, bottom - scene_module["original_rect"][1] + 40)
    if "brand" in modules and not has_brand:
        modules["brand"]["visible"] = False
        target_heights["brand"] = 0
    if "hero" in modules and not has_hero:
        modules["hero"]["visible"] = False
        target_heights["hero"] = 0
    # Only leaf content modules participate in page flow. Parent groups retain
    # original coordinates; each actual move uses the role's explicit paths.
    flow_roles = {"hero", "colors", *TABLE_ROLES.values(), "measurement_method", "scenes", "brand", "footer"}
    delta = 0.
    events = []
    previous_end = None
    hidden_since_visible = False
    for module in sorted((item for role, item in modules.items() if role in flow_roles),
                         key=lambda item: item["original_rect"][1]):
        original = module["original_rect"]
        height = target_heights.get(module["role"], original[3])
        if module["visible"] and hidden_since_visible and previous_end is not None:
            adjustment = min(0, previous_end + 80 - (original[1] + delta))
            delta += adjustment
            events.append((original[1], adjustment))
        module["rect"] = [original[0], original[1] + delta, original[2], height]
        module["delta_y"] = delta
        module["height_delta"] = height - original[3]
        original_table = module.get("table", {}).get("rect")
        for title in module.get("titles", []):
            rect = _rect(title.get("rect"))
            title_shift = 0
            if module["role"] == "size_table" and tuple(title.get("path") or ()) in note_paths:
                title_shift = note_shift
            elif original_table and rect[1] >= original_table[1] + original_table[3] - 1:
                title_shift = module.get("table_height_delta", 0)
            title["rect"] = _shift(rect, delta + title_shift)
        events.append((original[1] + original[3], height - original[3]))
        delta += height - original[3]
        if module["visible"]:
            previous_end = module["rect"][1] + height
            hidden_since_visible = False
        else:
            hidden_since_visible = True
    for role, module in modules.items():
        if role not in flow_roles:
            dy = sum(change for bottom, change in events if module["original_rect"][1] >= bottom - .01)
            module["rect"] = _shift(module["original_rect"], dy)
            module["delta_y"] = dy
            module["height_delta"] = 0
            module["titles"] = [{**title, "rect": _shift(_rect(title.get("rect")), dy)}
                                for title in module.get("titles", [])]
    color_delta = modules["colors"].get("delta_y", 0)
    for item in items:
        for name in ("image_rect", "label_rect"):
            item[name] = _shift(item[name], color_delta)
    for key, table in table_plans.items():
        dy = modules[TABLE_ROLES[key]].get("delta_y", 0)
        table["region"] = _shift(table["region"], dy)
    for name, slot in view_slots.items():
        role = slot.get("role") or ("scenes" if name.startswith("scene_") else name)
        module = modules.get(role)
        delta_y = module.get("delta_y", 0) if module else 0
        if module and slot.get("after_table"):
            delta_y += module.get("table_height_delta", 0)
        slot["rect"] = _shift(_rect(slot.get("rect")), delta_y)
        slot["visible"] = bool(module is None or module["visible"])
        if name.startswith("scene_"):
            slot["visible"] = slot["visible"] and int(name.split("_")[-1]) <= scene_count
    if note_layout:
        note_layout["rect"] = _shift(note_layout["rect"], size_module["delta_y"] + note_shift)
    canvas = copy.deepcopy(profile.get("canvas", {"width": 790, "height": 13395}))
    canvas["height"] = max(1000, math.ceil(canvas["height"] + delta))
    if canvas["height"] > 300000:
        raise ValueError("当前资料超出 Photoshop 长图画布范围，请分款或分表。")
    return {"canvas": canvas, "modules": modules, "module_order": [item["role"] for item in sorted(
            modules.values(), key=lambda item: item["rect"][1])],
            "colors": {"items": items, "rows": rows, "columns": columns,
                       "rect": modules["colors"]["rect"]},
            "tables": table_plans, "view_slots": view_slots, "size_note": note_layout}
