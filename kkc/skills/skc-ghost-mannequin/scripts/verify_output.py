"""Read-only image QA; no enhancement or source modification."""
import argparse
import json
from pathlib import Path
from PIL import Image, ImageChops, ImageDraw

Image.MAX_IMAGE_PIXELS = 500_000_000


def verify(before_path, after_path, expected_size=None, allowed_box=None):
    with Image.open(after_path) as after:
        after.load()
        result = {"size": list(after.size), "bytes": Path(after_path).stat().st_size}
        if expected_size and tuple(expected_size) != after.size:
            raise ValueError(f"Unexpected output size: {after.size}")
        if before_path:
            with Image.open(before_path) as before:
                if before.size != after.size:
                    raise ValueError("Pixel invariance requires same-size files.")
                box = None
                for top in range(0, after.height, 256):
                    region = (0, top, after.width, min(top + 256, after.height))
                    diff = ImageChops.difference(before.crop(region).convert("RGB"), after.crop(region).convert("RGB"))
                    bounds = [b for channel in diff.split() if (b := channel.getbbox())]
                    if not bounds:
                        continue
                    local = (min(b[0] for b in bounds), min(b[1] for b in bounds) + top,
                             max(b[2] for b in bounds), max(b[3] for b in bounds) + top)
                    box = local if box is None else (min(box[0], local[0]), min(box[1], local[1]),
                                                     max(box[2], local[2]), max(box[3], local[3]))
                result["actual_changed_bounds"] = list(box) if box else None
                if allowed_box:
                    if before.format != "PNG" or after.format != "PNG":
                        raise ValueError("Use lossless PNGs for outside-region invariance.")
                    ok = box is None or (box[0] >= allowed_box[0] and box[1] >= allowed_box[1]
                                         and box[2] <= allowed_box[2] and box[3] <= allowed_box[3])
                    result["outside_zipper_region_unchanged"] = ok
                    if not ok:
                        raise ValueError(f"Pixels changed outside allowed region: {box}")
    return result


def comparison(before_path, after_path, crops, output):
    if Path(output).exists():
        raise ValueError(f"Refusing to overwrite {output}")
    with Image.open(before_path) as before, Image.open(after_path) as after:
        if before.size != after.size or not crops:
            raise ValueError("Comparison requires same-size images and --crop.")
        width = max(r[2] - r[0] for r in crops)
        heights = [r[3] - r[1] for r in crops]
        sheet = Image.new("RGB", (width * 2 + 60, sum(heights) + 40 * len(crops)), "white")
        draw = ImageDraw.Draw(sheet)
        y = 0
        for region, height in zip(crops, heights):
            draw.text((10, y + 5), "BEFORE (same pixel scale)", fill="black")
            draw.text((width + 40, y + 5), "AFTER (same pixel scale)", fill="black")
            sheet.paste(before.crop(region).convert("RGB"), (10, y + 30))
            sheet.paste(after.crop(region).convert("RGB"), (width + 40, y + 30))
            y += height + 40
        sheet.save(output, quality=95, subsampling=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before")
    parser.add_argument("--after", required=True)
    parser.add_argument("--expected-size", nargs=2, type=int)
    parser.add_argument("--allowed-box", nargs=4, type=int)
    parser.add_argument("--report", required=True)
    parser.add_argument("--comparison")
    parser.add_argument("--crop", nargs=4, type=int, action="append", default=[])
    args = parser.parse_args()
    if Path(args.report).exists():
        raise ValueError("Choose a new report path; existing reports are preserved.")
    if args.allowed_box and not args.before:
        raise ValueError("--allowed-box requires --before.")
    result = verify(args.before, args.after, args.expected_size, args.allowed_box)
    if args.comparison:
        if not args.before:
            raise ValueError("--comparison requires --before.")
        comparison(args.before, args.after, args.crop, args.comparison)
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
