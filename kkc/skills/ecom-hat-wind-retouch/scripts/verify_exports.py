"""Read-only checks for local retouch delivery exports."""

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from psd_tools import PSDImage


def rgb(image):
    return np.asarray(image.convert("RGB"), dtype=np.int16)


def load_rgb(path):
    with Image.open(path) as image:
        return rgb(ImageOps.exif_transpose(image))


def find_layer(document, name):
    matches = [layer for layer in document if layer.name == name]
    if len(matches) != 1:
        raise ValueError(f"Expected one top-level layer named {name!r}, found {len(matches)}.")
    return matches[0]


def active_pixels(layer, canvas):
    if not layer.has_mask() or layer.mask.disabled:
        raise ValueError(f"{layer.name!r} must have an enabled raster mask.")
    mask = layer.mask
    if mask.background_color != 0:
        raise ValueError(f"{layer.name!r} mask must default to black outside its bounds.")
    data = np.asarray(mask.topil().convert("L"))
    left, top, right, bottom = mask.bbox
    if data.shape != (bottom - top, right - left):
        raise ValueError(f"{layer.name!r} mask dimensions do not match its bounds.")
    x = max(0, left)
    y = max(0, top)
    end_x = min(canvas[1], right)
    end_y = min(canvas[0], bottom)
    result = np.zeros(canvas, dtype=bool)
    if x < end_x and y < end_y:
        result[y:end_y, x:end_x] = data[y - top:end_y - top, x - left:end_x - left] > 0
    if not np.any(result):
        raise ValueError(f"{layer.name!r} mask has no active pixels in the canvas.")
    return result


def max_error(first, second):
    return int(np.abs(first - second).max(initial=0))


def verify(args):
    document = PSDImage.open(args.psd)
    width, height = document.size
    source = load_rgb(args.source)
    base = find_layer(document, args.base)
    if base.bbox != (0, 0, width, height) or not base.visible or base.has_mask():
        raise ValueError("The untouched source must be a full-canvas visible layer without a mask.")
    base_image = base.topil()
    if base_image is None or source.shape != (height, width, 3):
        raise ValueError("The source does not match the PSD canvas or base layer.")
    base_error = max_error(rgb(base_image), source)
    if base_error > args.source_tolerance:
        raise ValueError(f"Source and PSD base differ (max {base_error}).")

    layer_names = [name for name, _ in args.variant]
    if len(set(layer_names)) != len(layer_names) or args.base in layer_names:
        raise ValueError("Use a distinct top-level layer for the base and each variant.")
    variants = [(find_layer(document, name), path) for name, path in args.variant]
    for layer, path in variants:
        mask = active_pixels(layer, source.shape[:2])
        for item, _ in variants:
            item.visible = item is layer
        exported = load_rgb(path)
        if exported.shape != source.shape:
            raise ValueError(f"{path}: wrong export dimensions.")
        if not np.any(np.abs(exported[mask] - source[mask]) > args.source_tolerance):
            raise ValueError(f"{path}: no visible edit detected in the mask.")
        outside_error = max_error(exported[~mask], source[~mask])
        if outside_error > args.source_tolerance:
            raise ValueError(f"{path}: pixels outside the active mask differ (max {outside_error}).")
        rendered = rgb(document.composite(force=True))
        export_error = max_error(rendered, exported)
        if export_error > args.export_tolerance:
            raise ValueError(f"{path}: PSD recomposition differs from the export (max {export_error}).")
        print(f"{path.name}: mask covers {mask.mean():.2%}, outside delta {outside_error}, "
              f"PSD/export delta {export_error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--psd", required=True, type=Path)
    parser.add_argument("--base", required=True)
    parser.add_argument("--variant", required=True, nargs=2, action="append", metavar=("LAYER", "PNG"))
    parser.add_argument("--source-tolerance", type=int, choices=range(4), default=0, metavar="0-3")
    parser.add_argument("--export-tolerance", type=int, choices=range(4), default=1, metavar="0-3")
    args = parser.parse_args()
    args.variant = [(name, Path(path)) for name, path in args.variant]
    try:
        verify(args)
    except (OSError, TypeError, ValueError) as error:
        parser.exit(1, f"Validation failed: {error}\n")


if __name__ == "__main__":
    main()

