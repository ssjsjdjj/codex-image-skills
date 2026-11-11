from __future__ import annotations

import argparse
from datetime import datetime
import json
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


OUT_W_DEFAULT = 790
SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEMPLATE_DIR = SKILL_ROOT / "template"
DEFAULT_PRODUCT_DATA_DIR = SKILL_ROOT / "scripts" / "output" / "product_data"
DEFAULT_REPORT_DIR = SKILL_ROOT / "scripts" / "output" / "report"
DEFAULT_VISUAL_MODEL_SELECTION_DIR = SKILL_ROOT / "scripts" / "output" / "visual_model_selection"
ASSETS_DIR = SKILL_ROOT / "assets"
FONT_CN = ASSETS_DIR / "方正兰亭中黑_GBK.TTF"
FONT_CN_REGULAR = ASSETS_DIR / "方正兰亭中黑_GBK-Regular.ttf"
FONT_ONE = ASSETS_DIR / "阿里妈妈方圆体-SemiBold.ttf"
FONT_LATIN = ASSETS_DIR / "G8321-MEDIUM.OTF"

TEXT = (38, 38, 38)
BG = (247, 247, 247)
GREEN = (42, 160, 76)
LINE = (226, 226, 226)
TABLE_HEAD = (232, 232, 232)
TABLE_ROW = (255, 255, 255)
TABLE_ALT = (252, 252, 252)
LEFT_HEAD = (238, 241, 243)

MISSING_VALUES = {"", "/", "--", "无", "暂无", "无数据"}


class FontManager:
    def __init__(self):
        self.paths = {
            "cn": FONT_CN_REGULAR,
            "one": FONT_ONE,
            "latin": FONT_LATIN,
        }
        missing = [str(path) for path in self.paths.values() if not path.exists()]
        if missing:
            raise FileNotFoundError(f"missing bundled font files: {missing}")
        self.cache: dict[tuple[str, int], ImageFont.ImageFont] = {}

    def _load(self, key: str, size: int) -> ImageFont.ImageFont:
        cache_key = (key, size)
        if cache_key in self.cache:
            return self.cache[cache_key]
        font = ImageFont.truetype(str(self.paths[key]), size)
        self.cache[cache_key] = font
        return font

    def for_char(self, ch: str, size: int) -> ImageFont.ImageFont:
        if ch in {"1", "%"}:
            return self._load("one", size)
        if ch == "/":
            return self._load("cn", size)
        if ch.isascii() and (ch.isalnum() or ch in "%.-+ /"):
            return self._load("latin", size)
        return self._load("cn", size)


def normalize_missing(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in MISSING_VALUES else text


def color_parts(value: Any) -> list[str]:
    if isinstance(value, list):
        parts = [normalize_missing(item) for item in value]
        return [part for part in parts if part]
    text = normalize_missing(value)
    if not text:
        return []
    parts = re.split(r"\s*[/／,，、|｜;；]\s*", text)
    return [part for part in (normalize_missing(part) for part in parts) if part]


def product_info_value(data: dict[str, Any], info: dict[str, Any], key: str) -> str:
    if key != "颜色":
        return normalize_missing(info.get(key, ""))
    colors = color_parts(data.get("colors"))
    if not colors:
        colors = color_parts(info.get("颜色", ""))
    return "/".join(colors)


def text_metrics(draw: ImageDraw.ImageDraw, fonts: FontManager, text: str, size: int) -> tuple[int, int, int]:
    width = 0
    ascent = 0
    descent = 0
    for ch in text:
        font = fonts.for_char(ch, size)
        box = draw.textbbox((0, 0), ch, font=font)
        width += box[2] - box[0]
        if hasattr(font, "getmetrics"):
            a, d = font.getmetrics()  # type: ignore[attr-defined]
        else:
            a, d = box[3] - box[1], 0
        ascent = max(ascent, a)
        descent = max(descent, d)
    return width, ascent, descent


def mixed_text(
    draw: ImageDraw.ImageDraw,
    fonts: FontManager,
    xy: tuple[float, float],
    text: Any,
    size: int,
    fill=TEXT,
    anchor: str = "la",
    max_width: int | None = None,
    min_size: int = 24,
) -> int:
    text = normalize_missing(text)
    if not text:
        return size
    actual = size
    if max_width:
        while actual > min_size and text_metrics(draw, fonts, text, actual)[0] > max_width:
            actual -= 1
    width, ascent, descent = text_metrics(draw, fonts, text, actual)
    height = ascent + descent
    x, y = xy
    baseline = y + ascent
    if anchor == "ra":
        x -= width
    elif anchor == "ma":
        x -= width / 2
    elif anchor == "mm":
        x -= width / 2
        baseline = y - height / 2 + ascent
    elif anchor == "rm":
        x -= width
        baseline = y - height / 2 + ascent

    cursor = x
    for ch in text:
        font = fonts.for_char(ch, actual)
        box = draw.textbbox((0, 0), ch, font=font)
        try:
            draw.text((cursor, baseline), ch, fill=fill, font=font, anchor="ls")
        except Exception:
            draw.text((cursor, baseline - ascent), ch, fill=fill, font=font)
        cursor += box[2] - box[0]
    return actual


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask


def clear_rect(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill=BG) -> None:
    draw.rectangle(box, fill=fill)


def trim_transparent_or_white(img: Image.Image) -> Image.Image:
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] < 255:
        bbox = alpha.getbbox()
        return rgba.crop(bbox) if bbox else rgba
    bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    diff = ImageChops.difference(rgba, bg).convert("L")
    diff = Image.eval(diff, lambda p: 255 if p > 12 else 0)
    bbox = diff.getbbox()
    return rgba.crop(bbox) if bbox else rgba


def paste_uniform_canvas(
    base: Image.Image,
    src: Image.Image,
    center_x: int,
    center_y: int,
    box_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    rgba = src.convert("RGBA")
    slot_w, slot_h = box_size
    canvas = Image.new("RGBA", (slot_w, slot_h), (0, 0, 0, 0))
    rgba.thumbnail((slot_w, slot_h), Image.Resampling.LANCZOS)
    px = (slot_w - rgba.width) // 2
    py = (slot_h - rgba.height) // 2
    canvas.paste(rgba, (px, py), rgba)
    paste_x = round(center_x - slot_w / 2)
    paste_y = round(center_y - slot_h / 2)
    base.paste(canvas, (paste_x, paste_y), canvas)
    bbox = canvas.getchannel("A").getbbox()
    if not bbox:
        return (paste_x, paste_y, paste_x, paste_y)
    return (paste_x + bbox[0], paste_y + bbox[1], paste_x + bbox[2], paste_y + bbox[3])


def save_downsampled(img: Image.Image, out_path: Path, out_w: int) -> None:
    out_h = round(img.height * out_w / img.width)
    resized = img.convert("RGB").resize((out_w, out_h), Image.Resampling.LANCZOS)
    resized = resized.filter(ImageFilter.UnsharpMask(radius=0.6, percent=80, threshold=3))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    resized.save(out_path, quality=94, optimize=True)


def drop_empty_columns(headers: list[str], rows: list[list[Any]]) -> tuple[list[str], list[list[Any]]]:
    keep: list[int] = []
    for idx, _ in enumerate(headers):
        values = [normalize_missing(row[idx]) if idx < len(row) else "" for row in rows]
        if idx == 0 or any(values):
            keep.append(idx)
    return [headers[i] for i in keep], [[row[i] if i < len(row) else "" for i in keep] for row in rows]


def size_table_header_label(header: Any, index: int) -> str:
    text = normalize_missing(header)
    if index == 0 and text.lower().replace(" ", "") in {"尺码/cm", "尺码／cm", "size/cm"}:
        return "尺码"
    return text


def latest_archived_product_data(product_dir: Path, data_dir: Path) -> Path | None:
    direct = sorted(data_dir.glob(f"{product_dir.name}-product_data-*.json"))
    if direct:
        return direct[-1]
    matches: list[Path] = []
    for path in sorted(data_dir.glob("*-product_data-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("source_product_folder") == product_dir.name:
            matches.append(path)
    return matches[-1] if matches else None


def load_product_data(product_dir: Path, data_dir: Path | None = None) -> dict[str, Any] | None:
    candidates = [
        product_dir / "product_data.json",
        product_dir / "产品数据.json",
    ]
    if data_dir:
        archived = latest_archived_product_data(product_dir, data_dir) if data_dir.exists() else None
        candidates.extend(
            [
                data_dir / f"{product_dir.name}.json",
                data_dir / f"{product_dir.name}.product_data.json",
            ]
        )
        if archived:
            candidates.insert(0, archived)
    for path in candidates:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


def latest_visual_model_selection() -> Path | None:
    if not DEFAULT_VISUAL_MODEL_SELECTION_DIR.exists():
        return None
    dated = sorted(DEFAULT_VISUAL_MODEL_SELECTION_DIR.glob("visual_model_selection-*.json"))
    if dated:
        return dated[-1]
    plain = DEFAULT_VISUAL_MODEL_SELECTION_DIR / "visual_model_selection.json"
    return plain if plain.exists() else None


def load_visual_model_selection(value: str | None) -> tuple[dict[str, Any] | None, Path | None]:
    path = Path(value) if value else latest_visual_model_selection()
    if path is None:
        return None, None
    if not path.exists():
        raise FileNotFoundError(f"visual model selection file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"visual model selection root must be an object: {path}")
    return data, path


def visual_model_entry(
    selection: dict[str, Any] | None,
    product_name: str,
    output_name: str,
) -> dict[str, Any] | None:
    if not selection:
        return None
    products = selection.get("products", selection)
    if not isinstance(products, dict):
        return None
    product = products.get(product_name)
    if not isinstance(product, dict):
        return None
    entry = product.get(output_name)
    return entry if isinstance(entry, dict) else None


def template_path(template_dir: Path, name: str) -> Path:
    path = template_dir / name
    if not path.exists():
        raise FileNotFoundError(f"missing template: {path}")
    return path


def resolve_template_dir(value: str | None) -> Path:
    path = Path(value) if value else DEFAULT_TEMPLATE_DIR
    if not path.exists():
        raise FileNotFoundError(f"template directory not found: {path}")
    return path


def render_product_info(
    template_dir: Path,
    output_dir: Path,
    data: dict[str, Any],
    fonts: FontManager,
    out_w: int,
) -> None:
    info = data.get("info") or {}
    img = Image.open(template_path(template_dir, "01产品信息.jpg")).convert("RGB")
    draw = ImageDraw.Draw(img)
    clear_rect(draw, (880, 250, 1938, 1182), BG)
    rows = [
        ("名称", 347.5, 76, 1855, 1420),
        ("货号", 516.5, 76, 1855, 1420),
        ("材质", 699.5, 66, 1855, 1450),
        ("颜色", 884.5, 70, 1855, 1500),
        ("尺码", 1065.5, 70, 1855, 1420),
    ]
    for key, y, size, right, max_w in rows:
        if key == "材质":
            lines = [line for line in normalize_missing(info.get(key, "")).splitlines() if line.strip()]
            offset = -34 * (len(lines) - 1)
            for line in lines:
                mixed_text(draw, fonts, (right, y + offset), line, size, anchor="rm", max_width=max_w, min_size=48)
                offset += 68
            continue
        mixed_text(draw, fonts, (right, y), product_info_value(data, info, key), size, anchor="rm", max_width=max_w, min_size=48)
    save_downsampled(img, output_dir / "01产品信息.jpg", out_w)


def transparent_files(product_dir: Path, color_order: list[str] | None) -> list[Path]:
    source = product_dir / "透明图"
    files = sorted(source.glob("*.png"), key=lambda p: p.name) if source.exists() else []
    if not files:
        files = sorted(product_dir.glob("*.png"), key=lambda p: p.name)
    if color_order:
        order = {name: idx for idx, name in enumerate(color_order)}
        files = sorted(files, key=lambda p: order.get(p.stem, len(order) + files.index(p)))
    return files


def render_color_image(
    product_dir: Path,
    template_dir: Path,
    output_dir: Path,
    data: dict[str, Any],
    fonts: FontManager,
    out_w: int,
) -> bool:
    files = transparent_files(product_dir, data.get("colors"))
    if not files:
        return False
    img = Image.open(template_path(template_dir, "02透明图.jpg")).convert("RGB")
    draw = ImageDraw.Draw(img)
    clear_rect(draw, (82, 330, 1920, 1248), BG)
    layouts = {
        1: ([1000], (760, 760), 690, 74, 520),
        2: ([650, 1350], (680, 680), 690, 74, 500),
        3: ([385, 1000, 1615], (620, 620), 690, 74, 460),
        4: ([280, 760, 1240, 1720], (430, 620), 690, 62, 340),
        5: ([220, 610, 1000, 1390, 1780], (330, 620), 690, 56, 300),
    }
    centers, slot_size, image_center_y, text_size, text_max_w = layouts.get(
        len(files),
        ([220, 610, 1000, 1390, 1780], (330, 620), 690, 54, 290),
    )
    files = files[: len(centers)]
    bboxes = []
    for center, path in zip(centers, files):
        bboxes.append(paste_uniform_canvas(img, Image.open(path), center, image_center_y, slot_size))
    max_bottom = max((box[3] for box in bboxes), default=image_center_y)
    text_gap = 58 if len(files) <= 3 else 62
    text_y = max_bottom + text_gap
    max_text_y = 1068 if len(files) <= 3 else 1048
    if text_y > max_text_y:
        shift = text_y - max_text_y
        clear_rect(draw, (82, 330, 1920, 1248), BG)
        image_center_y -= shift
        bboxes = []
        for center, path in zip(centers, files):
            bboxes.append(paste_uniform_canvas(img, Image.open(path), center, image_center_y, slot_size))
        max_bottom = max((box[3] for box in bboxes), default=image_center_y)
        text_y = max_bottom + text_gap
    for center, path in zip(centers, files):
        mixed_text(draw, fonts, (center, text_y), path.stem, text_size, anchor="ma", max_width=text_max_w, min_size=38)
    save_downsampled(img, output_dir / "02透明图.jpg", out_w)
    return True


def render_size_table(
    template_dir: Path,
    output_dir: Path,
    data: dict[str, Any],
    fonts: FontManager,
    out_w: int,
) -> bool:
    table_data = data.get("size_table") or {}
    headers = table_data.get("headers") or []
    rows = table_data.get("rows") or []
    if not headers or not rows:
        return False
    img = Image.open(template_path(template_dir, "03选尺码.jpg")).convert("RGB")
    headers, rows = drop_empty_columns(headers, rows)
    left, top = 78, 604
    table_w = 1846
    header_h = 196
    row_h = 132
    table_h = header_h + row_h * len(rows)
    clear_rect(ImageDraw.Draw(img), (left - 8, top - 8, left + table_w + 8, 1760), BG)

    table = Image.new("RGB", (table_w, table_h), TABLE_ALT)
    td = ImageDraw.Draw(table)
    td.rectangle((0, 0, table_w, header_h), fill=TABLE_HEAD)
    col_w = table_w / len(headers)
    for idx, header in enumerate(headers):
        label = size_table_header_label(header, idx)
        mixed_text(td, fonts, (col_w * idx + col_w / 2, header_h / 2), label, 72, anchor="mm", max_width=int(col_w - 32), min_size=46)
    for r, row in enumerate(rows):
        y = header_h + row_h * r
        td.rectangle((0, y, table_w, y + row_h), fill=TABLE_ROW if r % 2 == 0 else TABLE_ALT)
        for c, value in enumerate(row):
            clean = normalize_missing(value)
            if clean:
                mixed_text(td, fonts, (col_w * c + col_w / 2, y + row_h / 2), clean, 66, anchor="mm", max_width=int(col_w - 32), min_size=42)
    img.paste(table, (left, top), rounded_mask((table_w, table_h), 36))
    save_downsampled(img, output_dir / "03选尺码.jpg", out_w)
    return True


def render_quick_size(
    template_dir: Path,
    output_dir: Path,
    data: dict[str, Any],
    fonts: FontManager,
    out_w: int,
) -> bool:
    quick = data.get("quick_size") or {}
    cols = quick.get("columns") or []
    rows = quick.get("rows") or []
    matrix = quick.get("data") or []
    if not cols or not rows or not matrix:
        return False
    img = Image.open(template_path(template_dir, "05尺码快选.jpg")).convert("RGB")
    draw = ImageDraw.Draw(img)
    left, top = 56, 252
    total_w = 1888
    row_label_w = 285
    header_h = 136
    row_h = 105
    table_h = header_h + row_h * len(rows)
    clear_rect(draw, (left - 10, top - 12, left + total_w + 10, 1190), BG)

    table = Image.new("RGB", (total_w, table_h), (255, 255, 255))
    td = ImageDraw.Draw(table)
    td.rounded_rectangle((0, 0, total_w - 1, table_h - 1), radius=20, fill=(255, 255, 255), outline=LINE, width=2)
    td.rounded_rectangle((0, 0, total_w - 1, header_h), radius=20, fill=GREEN)
    td.rectangle((0, header_h - 20, total_w, header_h), fill=GREEN)

    col_w = (total_w - row_label_w) / len(cols)
    mixed_text(td, fonts, (row_label_w / 2, header_h / 2), "身高/体重", 50, fill="white", anchor="mm", max_width=row_label_w - 20)
    for c, label in enumerate(cols):
        x = row_label_w + col_w * c
        td.line((x, header_h, x, table_h), fill=LINE, width=2)
        mixed_text(td, fonts, (x + col_w / 2, header_h / 2), label, 48, fill="white", anchor="mm", max_width=int(col_w - 22), min_size=34)
    for r, label in enumerate(rows):
        y = header_h + row_h * r
        td.rectangle((0, y, row_label_w, y + row_h), fill=LEFT_HEAD)
        td.line((0, y, total_w, y), fill=LINE, width=2)
        mixed_text(td, fonts, (row_label_w / 2, y + row_h / 2), label, 50, anchor="mm", max_width=row_label_w - 20)
        row_values = matrix[r] if r < len(matrix) else []
        for c, value in enumerate(row_values[: len(cols)]):
            x = row_label_w + col_w * c
            clean = normalize_missing(value)
            if clean:
                if clean.isdigit():
                    clean = f"{clean}码"
                mixed_text(td, fonts, (x + col_w / 2, y + row_h / 2), clean, 50, anchor="mm", max_width=int(col_w - 18), min_size=34)
    td.line((0, table_h - 1, total_w, table_h - 1), fill=LINE, width=2)
    td.line((total_w - 1, 0, total_w - 1, table_h), fill=LINE, width=2)
    img.paste(table, (left, top), rounded_mask((total_w, table_h), 20))
    save_downsampled(img, output_dir / "05尺码快选.jpg", out_w)
    return True


def model_source_file(product_dir: Path, index: int, preferred: str | None = None) -> Path | None:
    if preferred:
        path = product_dir / preferred
        if path.exists():
            return path
    candidates = [
        product_dir / f"模特{index}.jpg",
        product_dir / f"模特{index}.jpeg",
        product_dir / f"模特{index}.png",
        product_dir / f"模特图{index}.jpg",
        product_dir / f"模特图{index}.jpeg",
        product_dir / f"模特图{index}.png",
    ]
    return next((path for path in candidates if path.exists()), None)


def normalized_crop_box(
    raw_box: Any,
    src_size: tuple[int, int],
    target_size: tuple[int, int],
) -> tuple[int, int, int, int] | None:
    if not isinstance(raw_box, list | tuple) or len(raw_box) != 4:
        return None
    try:
        left, top, right, bottom = [float(value) for value in raw_box]
    except (TypeError, ValueError):
        return None
    src_w, src_h = src_size
    left = max(0.0, min(float(src_w), left))
    right = max(0.0, min(float(src_w), right))
    top = max(0.0, min(float(src_h), top))
    bottom = max(0.0, min(float(src_h), bottom))
    if right <= left or bottom <= top:
        return None

    target_ratio = target_size[0] / target_size[1]
    cx = (left + right) / 2
    cy = (top + bottom) / 2
    width = right - left
    height = bottom - top
    if width / height > target_ratio:
        width = height * target_ratio
    else:
        height = width / target_ratio

    width = min(width, float(src_w))
    height = min(height, float(src_h))
    if width / height > target_ratio:
        width = height * target_ratio
    else:
        height = width / target_ratio

    left = max(0.0, min(float(src_w) - width, cx - width / 2))
    top = max(0.0, min(float(src_h) - height, cy - height / 2))
    right = left + width
    bottom = top + height
    return (round(left), round(top), round(right), round(bottom))


def cover_resize(src: Image.Image, size: tuple[int, int], focus_y: float = 0.45) -> Image.Image:
    target_w, target_h = size
    src = src.convert("RGB")
    src_ratio = src.width / src.height
    target_ratio = target_w / target_h
    if src_ratio > target_ratio:
        crop_w = round(src.height * target_ratio)
        left = max(0, round((src.width - crop_w) / 2))
        box = (left, 0, left + crop_w, src.height)
    else:
        crop_h = round(src.width / target_ratio)
        top = max(0, min(src.height - crop_h, round((src.height - crop_h) * focus_y)))
        box = (0, top, src.width, top + crop_h)
    return src.crop(box).resize(size, Image.Resampling.LANCZOS)


def render_model_image(
    product_dir: Path,
    template_dir: Path,
    output_dir: Path,
    index: int,
    out_w: int,
    visual_selection: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    output_name = f"模特图{index}.jpg"
    entry = visual_model_entry(visual_selection, product_dir.name, output_name)
    preferred_source = normalize_missing(entry.get("source")) if entry else None
    src_path = model_source_file(product_dir, index, preferred_source)
    if src_path is None:
        return None

    template_name = f"模特图{index}.jpg"
    img = Image.open(template_path(template_dir, template_name)).convert("RGB")
    frames = {
        1: (24, 550, 1974, 3296),
        2: (260, 216, 1700, 2224),
        3: (24, 98, 1974, 2844),
    }
    radii = {1: 52, 2: 52, 3: 52}
    left, top, right, bottom = frames[index]
    frame_size = (right - left, bottom - top)
    src = Image.open(src_path)
    crop_box = normalized_crop_box(entry.get("crop_box"), src.size, frame_size) if entry else None
    if crop_box:
        photo = src.convert("RGB").crop(crop_box).resize(frame_size, Image.Resampling.LANCZOS)
        model_report = {
            "source": src_path.name,
            "mode": "visual_model_selection",
            "crop_box": list(crop_box),
            "reason": normalize_missing(entry.get("reason")) if entry else "",
        }
    else:
        photo = cover_resize(src, frame_size)
        model_report = {
            "source": src_path.name,
            "mode": "cover_crop",
        }
        if entry:
            model_report["visual_model_selection_warning"] = "missing or invalid crop_box; used cover_crop fallback"
    img.paste(photo, (left, top), rounded_mask(frame_size, radii[index]))

    if index == 2:
        overlay = template_dir / "模特图2覆盖.png"
        if overlay.exists():
            layer = Image.open(overlay).convert("RGBA")
            img = img.convert("RGBA")
            img.alpha_composite(layer)
            img = img.convert("RGB")

    save_downsampled(img, output_dir / output_name, out_w)
    return model_report


def render_product(
    product_dir: Path,
    template_dir: Path,
    output_dir: Path,
    data: dict[str, Any],
    fonts: FontManager,
    out_w: int,
    clean: bool = True,
    visual_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[str] = []
    skipped: dict[str, str] = {}
    model_images: dict[str, dict[str, Any]] = {}

    if data.get("info"):
        render_product_info(template_dir, output_dir, data, fonts, out_w)
        generated.append("01产品信息.jpg")
    else:
        skipped["01产品信息.jpg"] = "missing data.info"

    if render_color_image(product_dir, template_dir, output_dir, data, fonts, out_w):
        generated.append("02透明图.jpg")
    else:
        skipped["02透明图.jpg"] = "missing transparent PNG files"

    if render_size_table(template_dir, output_dir, data, fonts, out_w):
        generated.append("03选尺码.jpg")
    else:
        skipped["03选尺码.jpg"] = "missing data.size_table"

    if render_quick_size(template_dir, output_dir, data, fonts, out_w):
        generated.append("05尺码快选.jpg")
    else:
        skipped["05尺码快选.jpg"] = "missing data.quick_size"

    for index in (1, 2, 3):
        name = f"模特图{index}.jpg"
        model_report = render_model_image(product_dir, template_dir, output_dir, index, out_w, visual_selection)
        if model_report:
            generated.append(name)
            model_images[name] = model_report
        else:
            skipped[name] = f"missing model image {index}"

    return {
        "product": product_dir.name,
        "output": str(output_dir),
        "generated": generated,
        "skipped": skipped,
        "model_images": model_images,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Render visual detail-page modules from 2000px templates.")
    parser.add_argument("--input-root", required=True, help="Root folder containing product folders.")
    parser.add_argument(
        "--template-dir",
        help="Folder containing 2000px template images. Defaults to the skill bundled template/ folder.",
    )
    parser.add_argument("--output-root", required=True, help="Root folder for generated product output folders.")
    parser.add_argument(
        "--data-dir",
        help="Optional product data folder. Defaults to scripts/output/product_data when it exists.",
    )
    parser.add_argument(
        "--visual-model-selection",
        help="Optional visual_model_selection JSON. Defaults to the latest scripts/output/visual_model_selection/visual_model_selection-*.json when present.",
    )
    parser.add_argument("--out-width", type=int, default=OUT_W_DEFAULT, help="Final output width.")
    parser.add_argument("--keep-existing", action="store_true", help="Do not remove an existing product output folder before rendering.")
    args = parser.parse_args()

    input_root = Path(args.input_root)
    template_dir = resolve_template_dir(args.template_dir)
    output_root = Path(args.output_root)
    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_PRODUCT_DATA_DIR
    visual_selection, visual_selection_path = load_visual_model_selection(args.visual_model_selection)
    fonts = FontManager()

    output_root.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    missing_data: list[str] = []
    products = sorted([p for p in input_root.iterdir() if p.is_dir()], key=lambda p: p.name)
    for product_dir in products:
        data = load_product_data(product_dir, data_dir)
        if data is None:
            missing_data.append(product_dir.name)
            continue
        reports.append(
            render_product(
                product_dir=product_dir,
                template_dir=template_dir,
                output_dir=output_root / product_dir.name,
                data=data,
                fonts=fonts,
                out_w=args.out_width,
                clean=not args.keep_existing,
                visual_selection=visual_selection,
            )
        )

    report = {
        "input_root": str(input_root),
        "template_dir": str(template_dir),
        "output_root": str(output_root),
        "visual_model_selection_path": str(visual_selection_path) if visual_selection_path else "",
        "scanned_products": len(products),
        "rendered_products": len(reports),
        "missing_data_products": missing_data,
        "products": reports,
    }
    report_dir = DEFAULT_REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = report_dir / f"render_report-{timestamp}.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
