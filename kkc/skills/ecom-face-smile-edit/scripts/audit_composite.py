#!/usr/bin/env python3
"""Read-only pixel audit for an original-scene face composite. Requires Pillow."""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops


def audit(base_path, result_path, mask_path, mask_channel="luminance"):
    with Image.open(base_path) as image:
        base = image.convert("RGBA")
    with Image.open(result_path) as image:
        result = image.convert("RGBA")
    with Image.open(mask_path) as image:
        if mask_channel == "alpha":
            if "A" not in image.getbands():
                raise ValueError("The mask has no alpha channel.")
            mask = image.getchannel("A")
        else:
            mask = image.convert("L")
    if base.size != result.size or base.size != mask.size:
        raise ValueError(
            "Base, result and mask must have identical canvas dimensions: "
            f"{base.size}, {result.size}, {mask.size}."
        )
    allowed = mask.point(lambda value: 255 if value > 0 else 0)
    total = base.width * base.height
    allowed_count = allowed.histogram()[255]
    if allowed_count == 0 or allowed_count == total:
        raise ValueError("The mask must contain both allowed and protected pixels.")
    protected = ImageChops.invert(allowed)
    channels = ImageChops.difference(base, result).split()
    maximum = channels[0]
    for channel in channels[1:]:
        maximum = ImageChops.lighter(maximum, channel)
    outside = ImageChops.multiply(maximum, protected)
    inside = ImageChops.multiply(maximum, allowed)
    outside_changed = total - outside.histogram()[0]
    inside_changed = total - inside.histogram()[0]
    return {
        "canvas": {"width": base.width, "height": base.height},
        "mask_channel": mask_channel,
        "allowed_pixels_including_feather": allowed_count,
        "protected_pixels": total - allowed_count,
        "outside_edit_mask_changed_pixels": outside_changed,
        "outside_edit_mask_max_channel_difference": outside.getextrema()[1],
        "inside_edit_mask_changed_pixels": inside_changed,
        "inside_edit_mask_max_channel_difference": inside.getextrema()[1],
        "protected_region_identical": outside_changed == 0,
        "scope": "Pixel protection only; does not assess likeness, expression or mask accuracy.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--mask", required=True, type=Path)
    parser.add_argument(
        "--mask-channel", choices=("luminance", "alpha"), default="luminance"
    )
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = audit(args.base, args.result, args.mask, args.mask_channel)
        status = 0 if report["protected_region_identical"] else 1
    except (OSError, ValueError) as error:
        report = {"error": str(error), "protected_region_identical": None}
        status = 2
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output:
        try:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(rendered + "\n", encoding="utf-8")
        except OSError as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False))
            return 2
    print(rendered)
    return status


if __name__ == "__main__":
    sys.exit(main())
