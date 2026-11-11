from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Any

from PIL import Image, ImageDraw

from detail_template_replacer_2000 import (
    BG,
    DEFAULT_PRODUCT_DATA_DIR,
    DEFAULT_REPORT_DIR,
    GREEN,
    LEFT_HEAD,
    LINE,
    OUT_W_DEFAULT,
    TABLE_ALT,
    TABLE_HEAD,
    TABLE_ROW,
    TEXT,
    FontManager,
    cover_resize,
    drop_empty_columns,
    load_product_data,
    load_visual_model_selection,
    mixed_text,
    model_source_file,
    normalize_missing,
    normalized_crop_box,
    product_info_value,
    render_product,
    resolve_template_dir,
    rounded_mask,
    size_table_header_label,
    template_path,
    transparent_files,
    visual_model_entry,
)


def ps_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def canvas_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as img:
        return img.size


def image_layer(name: str, path: Path, box: tuple[int, int, int, int], fit: str = "stretch", visible: bool = True) -> dict[str, Any]:
    return {
        "type": "image",
        "name": name,
        "path": ps_path(path),
        "box": list(box),
        "fit": fit,
        "visible": visible,
    }


def text_layer(
    name: str,
    contents: Any,
    x: float,
    y: float,
    size: int,
    align: str = "left",
    color: tuple[int, int, int] = TEXT,
) -> dict[str, Any] | None:
    text = normalize_missing(contents)
    if not text:
        return None
    return {
        "type": "text",
        "name": name,
        "contents": text,
        "x": x,
        "y": y,
        "size": size,
        "align": align,
        "color": list(color),
    }


def fill_rect_layer(name: str, box: tuple[int, int, int, int], color: tuple[int, int, int] = BG) -> dict[str, Any]:
    return {
        "type": "fill_rect",
        "name": name,
        "box": list(box),
        "color": list(color),
    }


def doc_shell(
    product_name: str,
    module_name: str,
    template_dir: Path,
    template_name: str,
    output_dir: Path,
) -> tuple[dict[str, Any], tuple[int, int], Path]:
    template = template_path(template_dir, template_name)
    width, height = canvas_size(template)
    psd_dir = output_dir / "_psd"
    layer_dir = output_dir / "_psd_layers" / module_name
    psd_dir.mkdir(parents=True, exist_ok=True)
    layer_dir.mkdir(parents=True, exist_ok=True)
    doc = {
        "name": f"{product_name}-{module_name}",
        "width": width,
        "height": height,
        "save_as": ps_path(psd_dir / f"{module_name}.psd"),
        "layers": [
            image_layer("00 模板背景", template, (0, 0, width, height)),
        ],
    }
    return doc, (width, height), layer_dir


def add_reference_layer(doc: dict[str, Any], output_dir: Path, module_name: str) -> None:
    preview = output_dir / f"{module_name}.jpg"
    if preview.exists():
        doc["layers"].append(
            image_layer(
                "99 成品参考（隐藏）",
                preview,
                (0, 0, int(doc["width"]), int(doc["height"])),
                visible=False,
            )
        )


def build_product_info_doc(
    product_dir: Path,
    template_dir: Path,
    output_dir: Path,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    if not data.get("info"):
        return None
    doc, _, _ = doc_shell(product_dir.name, "01产品信息", template_dir, "01产品信息.jpg", output_dir)
    doc["layers"].append(fill_rect_layer("10 数据区底色", (880, 250, 1938, 1182)))
    info = data.get("info") or {}
    rows = [
        ("名称", 347.5, 76),
        ("货号", 516.5, 76),
        ("材质", 699.5, 66),
        ("颜色", 884.5, 70),
        ("尺码", 1065.5, 70),
    ]
    for key, y, size in rows:
        value = product_info_value(data, info, key)
        if key == "材质":
            lines = [line for line in normalize_missing(value).splitlines() if line.strip()]
            offset = -34 * (len(lines) - 1)
            for line_no, line in enumerate(lines, start=1):
                layer = text_layer(f"20 {key}{line_no}", line, 1855, y + offset, size, "right")
                if layer:
                    doc["layers"].append(layer)
                offset += 68
            continue
        layer = text_layer(f"20 {key}", value, 1855, y, size, "right")
        if layer:
            doc["layers"].append(layer)
    add_reference_layer(doc, output_dir, "01产品信息")
    return doc


def contained_alpha_bbox(path: Path, slot_size: tuple[int, int], center_x: int, center_y: int) -> tuple[int, int, int, int]:
    img = Image.open(path).convert("RGBA")
    img.thumbnail(slot_size, Image.Resampling.LANCZOS)
    px = round(center_x - slot_size[0] / 2 + (slot_size[0] - img.width) / 2)
    py = round(center_y - slot_size[1] / 2 + (slot_size[1] - img.height) / 2)
    bbox = img.getchannel("A").getbbox()
    if bbox:
        return (px + bbox[0], py + bbox[1], px + bbox[2], py + bbox[3])
    return (px, py, px + img.width, py + img.height)


def build_color_doc(
    product_dir: Path,
    template_dir: Path,
    output_dir: Path,
    data: dict[str, Any],
) -> dict[str, Any] | None:
    files = transparent_files(product_dir, data.get("colors"))
    if not files:
        return None
    doc, _, _ = doc_shell(product_dir.name, "02透明图", template_dir, "02透明图.jpg", output_dir)
    doc["layers"].append(fill_rect_layer("10 透明图区域底色", (82, 330, 1920, 1248)))
    layouts = {
        1: ([1000], (760, 760), 690, 74, 520),
        2: ([650, 1350], (680, 680), 690, 74, 500),
        3: ([385, 1000, 1615], (620, 620), 690, 74, 460),
        4: ([280, 760, 1240, 1720], (430, 620), 690, 62, 340),
        5: ([220, 610, 1000, 1390, 1780], (330, 620), 690, 56, 300),
    }
    centers, slot_size, image_center_y, text_size, _ = layouts.get(
        len(files),
        ([220, 610, 1000, 1390, 1780], (330, 620), 690, 54, 290),
    )
    files = files[: len(centers)]
    boxes = [contained_alpha_bbox(path, slot_size, center, image_center_y) for center, path in zip(centers, files)]
    max_bottom = max((box[3] for box in boxes), default=image_center_y)
    text_gap = 58 if len(files) <= 3 else 62
    text_y = max_bottom + text_gap
    max_text_y = 1068 if len(files) <= 3 else 1048
    if text_y > max_text_y:
        image_center_y -= text_y - max_text_y
        boxes = [contained_alpha_bbox(path, slot_size, center, image_center_y) for center, path in zip(centers, files)]
        max_bottom = max((box[3] for box in boxes), default=image_center_y)
        text_y = max_bottom + text_gap
    for center, path in zip(centers, files):
        left = round(center - slot_size[0] / 2)
        top = round(image_center_y - slot_size[1] / 2)
        doc["layers"].append(
            image_layer(f"20 商品透明图-{path.stem}", path, (left, top, left + slot_size[0], top + slot_size[1]), "contain")
        )
    for center, path in zip(centers, files):
        layer = text_layer(f"30 颜色名-{path.stem}", path.stem, center, text_y, text_size, "center")
        if layer:
            doc["layers"].append(layer)
    add_reference_layer(doc, output_dir, "02透明图")
    return doc


def save_size_table_overlay(
    layer_dir: Path,
    template_dir: Path,
    data: dict[str, Any],
    fonts: FontManager,
) -> Path | None:
    table_data = data.get("size_table") or {}
    headers = table_data.get("headers") or []
    rows = table_data.get("rows") or []
    if not headers or not rows:
        return None
    width, height = canvas_size(template_path(template_dir, "03选尺码.jpg"))
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    headers, rows = drop_empty_columns(headers, rows)
    left, top = 78, 604
    table_w = 1846
    header_h = 196
    row_h = 132
    table_h = header_h + row_h * len(rows)
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((left - 8, top - 8, left + table_w + 8, 1760), fill=(*BG, 255))
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
    overlay.paste(table.convert("RGBA"), (left, top), rounded_mask((table_w, table_h), 36))
    out = layer_dir / "03-size-table-overlay.png"
    overlay.save(out)
    return out


def build_size_table_doc(
    product_dir: Path,
    template_dir: Path,
    output_dir: Path,
    data: dict[str, Any],
    fonts: FontManager,
) -> dict[str, Any] | None:
    doc, size, layer_dir = doc_shell(product_dir.name, "03选尺码", template_dir, "03选尺码.jpg", output_dir)
    overlay = save_size_table_overlay(layer_dir, template_dir, data, fonts)
    if overlay is None:
        return None
    doc["layers"].append(image_layer("20 尺码表图层", overlay, (0, 0, size[0], size[1])))
    add_reference_layer(doc, output_dir, "03选尺码")
    return doc


def save_quick_size_overlay(
    layer_dir: Path,
    template_dir: Path,
    data: dict[str, Any],
    fonts: FontManager,
) -> Path | None:
    quick = data.get("quick_size") or {}
    cols = quick.get("columns") or []
    rows = quick.get("rows") or []
    matrix = quick.get("data") or []
    if not cols or not rows or not matrix:
        return None
    width, height = canvas_size(template_path(template_dir, "05尺码快选.jpg"))
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    left, top = 56, 252
    total_w = 1888
    row_label_w = 285
    header_h = 136
    row_h = 105
    table_h = header_h + row_h * len(rows)
    draw.rectangle((left - 10, top - 12, left + total_w + 10, 1190), fill=(*BG, 255))
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
    overlay.paste(table.convert("RGBA"), (left, top), rounded_mask((total_w, table_h), 20))
    out = layer_dir / "05-quick-size-overlay.png"
    overlay.save(out)
    return out


def build_quick_size_doc(
    product_dir: Path,
    template_dir: Path,
    output_dir: Path,
    data: dict[str, Any],
    fonts: FontManager,
) -> dict[str, Any] | None:
    doc, size, layer_dir = doc_shell(product_dir.name, "05尺码快选", template_dir, "05尺码快选.jpg", output_dir)
    overlay = save_quick_size_overlay(layer_dir, template_dir, data, fonts)
    if overlay is None:
        return None
    doc["layers"].append(image_layer("20 尺码快选表图层", overlay, (0, 0, size[0], size[1])))
    add_reference_layer(doc, output_dir, "05尺码快选")
    return doc


def save_model_photo_layer(
    layer_dir: Path,
    product_dir: Path,
    index: int,
    frame_size: tuple[int, int],
    visual_selection: dict[str, Any] | None,
) -> tuple[Path, dict[str, Any]] | None:
    output_name = f"模特图{index}.jpg"
    entry = visual_model_entry(visual_selection, product_dir.name, output_name)
    preferred_source = normalize_missing(entry.get("source")) if entry else None
    src_path = model_source_file(product_dir, index, preferred_source)
    if src_path is None:
        return None
    src = Image.open(src_path)
    crop_box = normalized_crop_box(entry.get("crop_box"), src.size, frame_size) if entry else None
    if crop_box:
        photo = src.convert("RGB").crop(crop_box).resize(frame_size, Image.Resampling.LANCZOS)
        info = {
            "source": src_path.name,
            "mode": "visual_model_selection",
            "crop_box": list(crop_box),
        }
    else:
        photo = cover_resize(src, frame_size)
        info = {
            "source": src_path.name,
            "mode": "cover_crop",
        }
    layer = Image.new("RGBA", frame_size, (0, 0, 0, 0))
    layer.paste(photo, (0, 0), rounded_mask(frame_size, 52))
    out = layer_dir / f"model-{index}-photo.png"
    layer.save(out)
    return out, info


def build_model_doc(
    product_dir: Path,
    template_dir: Path,
    output_dir: Path,
    index: int,
    visual_selection: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    module_name = f"模特图{index}"
    doc, _, layer_dir = doc_shell(product_dir.name, module_name, template_dir, f"{module_name}.jpg", output_dir)
    frames = {
        1: (24, 550, 1974, 3296),
        2: (260, 216, 1700, 2224),
        3: (24, 98, 1974, 2844),
    }
    frame = frames[index]
    frame_size = (frame[2] - frame[0], frame[3] - frame[1])
    photo_result = save_model_photo_layer(layer_dir, product_dir, index, frame_size, visual_selection)
    if photo_result is None:
        return None
    photo_layer, info = photo_result
    doc["layers"].append(image_layer("20 模特照片", photo_layer, frame))
    if index == 2:
        overlay = template_dir / "模特图2覆盖.png"
        if overlay.exists():
            width, height = int(doc["width"]), int(doc["height"])
            doc["layers"].append(image_layer("30 模特图2覆盖", overlay, (0, 0, width, height)))
    add_reference_layer(doc, output_dir, module_name)
    return doc, info


JSX_TEMPLATE = r"""#target photoshop
app.displayDialogs = DialogModes.NO;

var MANIFEST_PATH = __MANIFEST_PATH__;
var originalRulerUnits = app.preferences.rulerUnits;
app.preferences.rulerUnits = Units.PIXELS;

function readText(path) {
    var file = new File(path);
    if (!file.exists) {
        throw new Error("Manifest not found: " + path);
    }
    file.encoding = "UTF8";
    file.open("r");
    var text = file.read();
    file.close();
    return text;
}

function px(value) {
    return UnitValue(Number(value), "px");
}

function solidColor(rgb) {
    var color = new SolidColor();
    color.rgb.red = Number(rgb[0]);
    color.rgb.green = Number(rgb[1]);
    color.rgb.blue = Number(rgb[2]);
    return color;
}

function boundsPx(layer) {
    var b = layer.bounds;
    return [b[0].as("px"), b[1].as("px"), b[2].as("px"), b[3].as("px")];
}

function fitLayerToBox(layer, box, fit) {
    var b = boundsPx(layer);
    var w = b[2] - b[0];
    var h = b[3] - b[1];
    var left = Number(box[0]);
    var top = Number(box[1]);
    var targetW = Number(box[2]) - left;
    var targetH = Number(box[3]) - top;
    if (w <= 0 || h <= 0 || targetW <= 0 || targetH <= 0) {
        return;
    }
    if (fit === "stretch") {
        layer.resize(targetW / w * 100, targetH / h * 100, AnchorPosition.TOPLEFT);
    } else {
        var scale = fit === "cover" ? Math.max(targetW / w, targetH / h) : Math.min(targetW / w, targetH / h);
        layer.resize(scale * 100, scale * 100, AnchorPosition.MIDDLECENTER);
    }
    b = boundsPx(layer);
    var newW = b[2] - b[0];
    var newH = b[3] - b[1];
    layer.translate(px(left + (targetW - newW) / 2 - b[0]), px(top + (targetH - newH) / 2 - b[1]));
}

function placeImage(spec) {
    var file = new File(spec.path);
    if (!file.exists) {
        throw new Error("Image not found: " + spec.path);
    }
    var desc = new ActionDescriptor();
    desc.putPath(charIDToTypeID("null"), file);
    desc.putEnumerated(charIDToTypeID("FTcs"), charIDToTypeID("QCSt"), charIDToTypeID("Qcsa"));
    executeAction(charIDToTypeID("Plc "), desc, DialogModes.NO);
    var layer = app.activeDocument.activeLayer;
    layer.name = spec.name || file.name;
    fitLayerToBox(layer, spec.box, spec.fit || "contain");
    if (spec.opacity !== undefined) {
        layer.opacity = Number(spec.opacity);
    }
    if (spec.visible === false) {
        layer.visible = false;
    }
}

function fillRect(spec) {
    var doc = app.activeDocument;
    var layer = doc.artLayers.add();
    layer.name = spec.name || "fill";
    var box = spec.box;
    doc.selection.select([
        [Number(box[0]), Number(box[1])],
        [Number(box[2]), Number(box[1])],
        [Number(box[2]), Number(box[3])],
        [Number(box[0]), Number(box[3])]
    ]);
    doc.selection.fill(solidColor(spec.color));
    doc.selection.deselect();
}

function addText(spec, defaultFont) {
    var layer = app.activeDocument.artLayers.add();
    layer.name = spec.name || "text";
    layer.kind = LayerKind.TEXT;
    var item = layer.textItem;
    item.kind = TextType.POINTTEXT;
    item.contents = spec.contents || "";
    item.size = px(spec.size || 48);
    item.color = solidColor(spec.color || [38, 38, 38]);
    item.position = [px(spec.x || 0), px(spec.y || 0)];
    try {
        item.font = spec.font || defaultFont;
    } catch (e) {}
    if (spec.align === "right") {
        item.justification = Justification.RIGHT;
    } else if (spec.align === "center") {
        item.justification = Justification.CENTER;
    } else {
        item.justification = Justification.LEFT;
    }
}

function applyLayer(spec, defaultFont) {
    if (spec.type === "image") {
        placeImage(spec);
    } else if (spec.type === "fill_rect") {
        fillRect(spec);
    } else if (spec.type === "text") {
        addText(spec, defaultFont);
    }
}

try {
    var manifest = JSON.parse(readText(MANIFEST_PATH));
    var docs = manifest.documents || [];
    for (var i = 0; i < docs.length; i++) {
        var spec = docs[i];
        var doc = app.documents.add(px(spec.width), px(spec.height), 72, spec.name, NewDocumentMode.RGB, DocumentFill.TRANSPARENT);
        var starterLayer = doc.activeLayer;
        for (var j = 0; j < spec.layers.length; j++) {
            applyLayer(spec.layers[j], manifest.default_font || "MicrosoftYaHeiUI");
        }
        try {
            starterLayer.remove();
        } catch (e) {}
        var saveFile = new File(spec.save_as);
        saveFile.parent.create();
        var options = new PhotoshopSaveOptions();
        options.layers = true;
        doc.saveAs(saveFile, options, true, Extension.LOWERCASE);
        doc.close(SaveOptions.DONOTSAVECHANGES);
    }
} finally {
    app.preferences.rulerUnits = originalRulerUnits;
}
"""


def write_jsx(jsx_path: Path, manifest_path: Path) -> None:
    jsx = JSX_TEMPLATE.replace("__MANIFEST_PATH__", json.dumps(ps_path(manifest_path), ensure_ascii=False))
    jsx_path.write_text(jsx, encoding="utf-8")


def build_documents(
    product_dir: Path,
    template_dir: Path,
    output_dir: Path,
    data: dict[str, Any],
    fonts: FontManager,
    visual_selection: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    model_images: dict[str, dict[str, Any]] = {}
    builders = [
        build_product_info_doc(product_dir, template_dir, output_dir, data),
        build_color_doc(product_dir, template_dir, output_dir, data),
        build_size_table_doc(product_dir, template_dir, output_dir, data, fonts),
        build_quick_size_doc(product_dir, template_dir, output_dir, data, fonts),
    ]
    docs.extend([doc for doc in builders if doc is not None])
    for index in (1, 2, 3):
        result = build_model_doc(product_dir, template_dir, output_dir, index, visual_selection)
        if result:
            doc, info = result
            docs.append(doc)
            model_images[f"模特图{index}.psd"] = info
    return docs, model_images


def main() -> None:
    parser = argparse.ArgumentParser(description="Create Photoshop layered PSD packages for detail-page modules.")
    parser.add_argument("--input-root", required=True, help="Root folder containing product folders.")
    parser.add_argument("--output-root", required=True, help="Root folder for generated product output folders.")
    parser.add_argument("--template-dir", help="Folder containing 2000px template images.")
    parser.add_argument("--data-dir", help="Optional product data folder.")
    parser.add_argument("--visual-model-selection", help="Optional visual_model_selection JSON.")
    parser.add_argument("--out-width", type=int, default=OUT_W_DEFAULT, help="Final JPG output width.")
    parser.add_argument("--keep-existing", action="store_true", help="Do not remove an existing product output folder before rendering.")
    parser.add_argument("--skip-jpg-render", action="store_true", help="Only build the PSD package from existing output JPGs.")
    args = parser.parse_args()

    input_root = Path(args.input_root)
    output_root = Path(args.output_root)
    template_dir = resolve_template_dir(args.template_dir)
    data_dir = Path(args.data_dir) if args.data_dir else DEFAULT_PRODUCT_DATA_DIR
    visual_selection, visual_selection_path = load_visual_model_selection(args.visual_model_selection)
    fonts = FontManager()

    output_root.mkdir(parents=True, exist_ok=True)
    package_dir = output_root / "_photoshop_layered"
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True, exist_ok=True)

    documents: list[dict[str, Any]] = []
    product_reports: list[dict[str, Any]] = []
    missing_data: list[str] = []
    products = sorted([p for p in input_root.iterdir() if p.is_dir()], key=lambda p: p.name)
    for product_dir in products:
        data = load_product_data(product_dir, data_dir)
        if data is None:
            missing_data.append(product_dir.name)
            continue
        output_dir = output_root / product_dir.name
        render_report: dict[str, Any] | None = None
        if not args.skip_jpg_render:
            render_report = render_product(
                product_dir=product_dir,
                template_dir=template_dir,
                output_dir=output_dir,
                data=data,
                fonts=fonts,
                out_w=args.out_width,
                clean=not args.keep_existing,
                visual_selection=visual_selection,
            )
        product_docs, model_images = build_documents(product_dir, template_dir, output_dir, data, fonts, visual_selection)
        documents.extend(product_docs)
        product_reports.append(
            {
                "product": product_dir.name,
                "output": str(output_dir),
                "psd_count": len(product_docs),
                "psd_files": [doc["save_as"] for doc in product_docs],
                "model_images": model_images,
                "jpg_render": render_report,
            }
        )

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input_root": str(input_root),
        "output_root": str(output_root),
        "template_dir": str(template_dir),
        "visual_model_selection_path": str(visual_selection_path) if visual_selection_path else "",
        "default_font": "MicrosoftYaHeiUI",
        "documents": documents,
    }
    manifest_path = package_dir / "layered_psd_manifest.json"
    jsx_path = package_dir / "build_layered_psd.jsx"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsx(jsx_path, manifest_path)
    runner_path = Path(__file__).with_name("run_photoshop_jsx.ps1")

    report = {
        "input_root": str(input_root),
        "template_dir": str(template_dir),
        "output_root": str(output_root),
        "visual_model_selection_path": str(visual_selection_path) if visual_selection_path else "",
        "scanned_products": len(products),
        "missing_data_products": missing_data,
        "psd_documents": len(documents),
        "manifest_path": str(manifest_path),
        "jsx_path": str(jsx_path),
        "run_in_photoshop": f"powershell -ExecutionPolicy Bypass -File \"{runner_path}\" -JsxPath \"{jsx_path}\"",
        "products": product_reports,
    }
    report_dir = DEFAULT_REPORT_DIR
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_path = report_dir / f"layered_psd_report-{timestamp}.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
