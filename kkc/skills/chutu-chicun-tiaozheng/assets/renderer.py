#!/usr/bin/env python3
"""后台调整图片尺寸；支持构图参数、人工主体框、品类预设和参数重放。

依赖 Python 3.9+、Pillow 9.1+；生成单图层 PSD 时另需 psd-tools。所有框坐标均相对
EXIF 方向纠正后的原图归一化为 0~1，不自动检测或移动独立主体。
"""
import argparse
import hashlib
import io
import json
import math
import os
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

VERSION = "3.4.0"
FITS = ("contain", "cover", "stretch", "subject")
PRESETS = {
    "product": {"label": "商品全貌", "fit": "subject", "subject_fill": 0.80,
                "position": [0.5, 0.5], "fallback_fit": "cover"},
    "full_body": {"label": "全身模特", "fit": "subject", "subject_fill": 0.88,
                  "position": [0.5, 0.5], "fallback_fit": "cover"},
    "half_body": {"label": "半身展示", "fit": "cover", "focus": [0.5, 0.38]},
    "detail": {"label": "局部特写", "fit": "cover", "zoom": 1.15},
}
FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def parse_size(value):
    parts = str(value).lower().replace("×", "x").replace("*", "x").replace(" ", "").split("x")
    try:
        w, h = map(int, parts)
    except (ValueError, TypeError):
        raise ValueError(f"尺寸格式不对：{value}；示例：800x800") from None
    if not (1 <= w <= 10000 and 1 <= h <= 10000):
        raise ValueError("尺寸范围为 1~10000 像素")
    return w, h


def numbers(value, length, field, lower=0, upper=1):
    try:
        result = [float(x) for x in (value.split(",") if isinstance(value, str) else value)]
    except (TypeError, ValueError):
        raise ValueError(f"{field} 需要 {length} 个数值") from None
    if len(result) != length or any(not math.isfinite(x) or not lower <= x <= upper for x in result):
        raise ValueError(f"{field} 需要 {length} 个 {lower}~{upper} 范围内的有限数值")
    if length == 4 and (result[0] >= result[2] or result[1] >= result[3]):
        raise ValueError(f"{field} 必须满足 left < right、top < bottom")
    return result


def scalar(value, field, lower, upper):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} 必须是数值") from None
    if not math.isfinite(value) or not lower <= value <= upper:
        raise ValueError(f"{field} 范围为 {lower}~{upper}")
    return value


def has_alpha(im):
    return im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)


def resolve_job(job):
    preset = job.get("preset")
    if preset is not None and preset not in PRESETS:
        raise ValueError(f"未知预设：{preset}；可选 {tuple(PRESETS)}")
    defaults = {k: v for k, v in PRESETS.get(preset, {}).items() if k not in ("label", "fallback_fit")}
    resolved = {**defaults, **{k: v for k, v in job.items() if v is not None}}
    resolved.setdefault("fit", "cover")
    resolved.setdefault("bg", "white")
    resolved.setdefault("zoom", 1.0)
    resolved.setdefault("position", [0.5, 0.5])
    resolved.setdefault("offset", [0.0, 0.0])
    resolved.setdefault("on_conflict", "error")
    resolved.setdefault("allow_padding", False)
    resolved.setdefault("allow_stretch", False)
    resolved.setdefault("save_recipe", bool(preset))
    if resolved["fit"] not in FITS:
        raise ValueError(f"适配方式只能是 {FITS}")
    if resolved["bg"] not in ("white", "transparent"):
        raise ValueError("bg 只能是 white 或 transparent；只控制新增补边，PNG源alpha保留")
    if resolved["on_conflict"] not in ("contain", "error"):
        raise ValueError("on_conflict 只能是 contain 或 error")
    if not isinstance(resolved["save_recipe"], bool):
        raise ValueError("save_recipe 必须是 JSON 布尔值")
    for key in ("allow_padding", "allow_stretch"):
        if not isinstance(resolved[key], bool):
            raise ValueError(f"{key} 必须是 JSON 布尔值")
    if resolved["fit"] == "stretch" and not resolved["allow_stretch"]:
        raise ValueError("当前个人规则禁止拉伸；仅在用户明确要求本次拉伸时设置 allow_stretch=true")
    for key in ("crop_box", "subject_box", "protect_box"):
        if key in resolved:
            resolved[key] = numbers(resolved[key], 4, key)
    for key in ("focus", "position"):
        if key in resolved:
            resolved[key] = numbers(resolved[key], 2, key)
    resolved["offset"] = numbers(resolved["offset"], 2, "offset", -1, 1)
    resolved["zoom"] = scalar(resolved["zoom"], "zoom", 0.05, 10)
    resolved["subject_fill"] = scalar(resolved.get("subject_fill", 0.8), "subject_fill", 0.05, 1)
    warnings = []
    if resolved["fit"] == "subject" and "subject_box" not in resolved:
        fallback = PRESETS.get(preset, {}).get("fallback_fit")
        if not fallback:
            raise ValueError("subject 模式需要 subject_box；脚本不自动识别主体")
        resolved["fit"] = fallback
        warnings.append("未提供主体框，改用铺满裁切；请查看预览并设置焦点，不代表自动识别了主体")
    if resolved["fit"] == "contain" and resolved["zoom"] > 1:
        raise ValueError("contain 为完整显示，zoom 不能大于 1；要放大裁切请使用 cover")
    if resolved["fit"] == "cover" and resolved["zoom"] < 1:
        raise ValueError("cover 要铺满画布，zoom 不能小于 1；要缩小补边请使用 contain")
    if resolved["fit"] == "subject" and resolved["zoom"] != 1:
        raise ValueError("subject 模式请用 subject_fill 调整大小，zoom 保持 1")
    if resolved["fit"] == "stretch" and any(k in job for k in ("focus", "position", "offset", "zoom", "subject_box", "protect_box", "preset")):
        raise ValueError("stretch 不支持构图参数；商品图建议 contain、cover 或 subject")
    return resolved, warnings


def _pixels(box, size):
    w, h = size
    return box[0] * w, box[1] * h, box[2] * w, box[3] * h


def _inside(inner, outer):
    return all((inner[0] >= outer[0] - 1e-7, inner[1] >= outer[1] - 1e-7,
                inner[2] <= outer[2] + 1e-7, inner[3] <= outer[3] + 1e-7))


def _clamp(value, low, high):
    return max(low, min(high, value))


def _place(start, length, lo, hi):
    # 窗口小于原图时不越界；窗口更大时补边并尽量包含原图。
    return _clamp(start, lo, hi - length) if length <= hi - lo else _clamp(start, hi - length, lo)


def framing_plan(source_size, size, job):
    j, warnings = resolve_job(job)
    sw, sh = source_size
    W, H = size
    domain = _pixels(j.get("crop_box", [0, 0, 1, 1]), source_size)
    left, top, right, bottom = domain
    dw, dh = right - left, bottom - top
    protected = [_pixels(j[key], source_size) for key in ("subject_box", "protect_box") if key in j]
    if any(not _inside(box, domain) for box in protected):
        raise ValueError("crop_box 已排除主体或保护区域；请扩大 crop_box")
    px, py = j["position"]
    ox, oy = j["offset"]
    fit = j["fit"]
    if fit == "stretch":
        viewport = domain
    elif fit == "contain":
        scale = min(W / dw, H / dh) * j["zoom"]
        vw, vh = W / scale, H / scale
        want_x, want_y = (px + ox) * W - dw * scale / 2, (py + oy) * H - dh * scale / 2
        x = _clamp(want_x, 0, W - dw * scale)
        y = _clamp(want_y, 0, H - dh * scale)
        viewport = left - x / scale, top - y / scale, left - x / scale + vw, top - y / scale + vh
        if "focus" in j:
            warnings.append("contain 使用 position/offset 放置完整图片，focus 不参与构图")
        if abs(x - want_x) > 1e-6 or abs(y - want_y) > 1e-6:
            warnings.append("为保证完整显示，位置/偏移已限制在画布范围内")
    else:
        if fit == "subject":
            if "focus" in j:
                warnings.append("subject 使用主体框中心，focus 不参与构图")
            box = _pixels(j["subject_box"], source_size)
            bw, bh = box[2] - box[0], box[3] - box[1]
            vw = max(bw / j["subject_fill"], bh * W / H / j["subject_fill"])
            vh = vw * H / W
            fx, fy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        else:
            scale = max(W / dw, H / dh) * j["zoom"]
            vw, vh = W / scale, H / scale
            if "focus" in j:
                fx, fy = j["focus"][0] * sw, j["focus"][1] * sh
            else:
                fx, fy = (left + right) / 2, (top + bottom) / 2
        want_x, want_y = fx - (px + ox) * vw, fy - (py + oy) * vh
        x, y = _place(want_x, vw, left, right), _place(want_y, vh, top, bottom)
        viewport = x, y, x + vw, y + vh
        if abs(x - want_x) > 1e-6 or abs(y - want_y) > 1e-6:
            warnings.append("位置已受原图边界限制，无法完全达到指定焦点/偏移")
    if any(not _inside(box, viewport) for box in protected):
        if j["on_conflict"] == "error":
            raise ValueError("当前构图会裁切指定主体或保护区域")
        if not j["allow_padding"]:
            raise ValueError("个人规则禁止补边，不能自动退回 contain；请调整构图或询问用户")
        fallback_job = {**j, "fit": "contain", "zoom": 1, "position": [0.5, 0.5], "offset": [0, 0]}
        fallback_job.pop("focus", None)
        plan, _ = framing_plan(source_size, size, fallback_job)
        viewport = plan["source_viewport_px"]
        fit = "contain"
        warnings.append("当前构图无法完整保护指定区域，已退回完整显示；请确认留白")
    if not j["allow_padding"] and not _inside(viewport, domain):
        raise ValueError("当前构图会新增白边或透明边；个人规则禁止补边，请调整裁切框/主体占比")
    plan = {
        "effective_fit": fit, "source_size": list(source_size), "output_size": list(size),
        "source_domain_px": list(domain), "source_viewport_px": list(viewport), "warnings": warnings,
    }
    return plan, j


def _canvas(size, im, bg):
    if has_alpha(im):
        return Image.new("RGBA", size, (0, 0, 0, 0) if bg == "transparent" else (255, 255, 255, 255))
    return Image.new("RGB", size, "white")


def _paint(im, size, plan, bg):
    """直接重采样有效源区域，避免大 zoom 创建巨幅中间图。"""
    canvas = _canvas(size, im, bg)
    vl, vt, vr, vb = plan["source_viewport_px"]
    dl, dt, dr, db = plan["source_domain_px"]
    sl, st, sr, sb = max(vl, dl), max(vt, dt), min(vr, dr), min(vb, db)
    if sr <= sl or sb <= st:
        raise ValueError("构图窗口没有包含有效原图")
    W, H = size
    x1, y1 = round((sl - vl) * W / (vr - vl)), round((st - vt) * H / (vb - vt))
    x2, y2 = round((sr - vl) * W / (vr - vl)), round((sb - vt) * H / (vb - vt))
    if x2 <= x1 or y2 <= y1:
        return canvas
    patch = im.resize((x2 - x1, y2 - y1), Image.Resampling.LANCZOS, box=(sl, st, sr, sb))
    # Replace source-covered pixels, including their alpha. bg only affects newly padded area.
    canvas.paste(patch, (x1, y1))
    return canvas


def resize(im, size, fit, bg="white", **framing):
    """兼容原有函数签名；新构图参数作为关键字参数传入。"""
    out, _, _ = _render_image(im, size, {"fit": fit, "bg": bg, **framing})
    return out


def _render_image(im, size, job):
    if im.mode == "CMYK":
        raise ValueError("CMYK素材需先经明确的色彩管理转换为RGB/sRGB，不直接丢弃配置转换")
    im = im.convert("RGBA" if has_alpha(im) else "RGB")
    plan, resolved = framing_plan(im.size, size, job)
    # 无新增构图参数时沿用旧版像素取整，保持普通旧任务的输出一致。
    new_keys = ("preset", "focus", "position", "offset", "zoom", "crop_box", "subject_box", "protect_box")
    if not any(key in job for key in new_keys) and resolved["fit"] in ("cover", "contain", "stretch"):
        W, H = size
        sw, sh = im.size
        if resolved["fit"] == "stretch":
            return im.resize(size, Image.Resampling.LANCZOS), plan, resolved
        scale = (max if resolved["fit"] == "cover" else min)(W / sw, H / sh)
        rw, rh = max(1, round(sw * scale)), max(1, round(sh * scale))
        r = im.resize((rw, rh), Image.Resampling.LANCZOS)
        if resolved["fit"] == "cover":
            l, t = (rw - W) // 2, (rh - H) // 2
            plan["source_viewport_px"] = [l * sw / rw, t * sh / rh, (l + W) * sw / rw, (t + H) * sh / rh]
            return r.crop((l, t, l + W, t + H)), plan, resolved
        canvas = _canvas(size, im, resolved["bg"])
        xy = ((W - rw) // 2, (H - rh) // 2)
        canvas.paste(r, xy)
        return canvas, plan, resolved
    return _paint(im, size, plan, resolved["bg"]), plan, resolved


def _render(job):
    src = Path(job["input"]).expanduser().resolve()
    with Image.open(src) as opened:
        im = ImageOps.exif_transpose(opened)
        im.load()
        img, plan, resolved = _render_image(im, parse_size(job["size"]), job)
        if im.info.get("icc_profile"):
            img.info["icc_profile"] = im.info["icc_profile"]
    resolved["input"] = str(src)
    return src, img, plan, resolved


def render(job):
    src, img, _, _ = _render(job)
    return src, img


def out_format(job, src, img):
    fmt = str(job.get("format") or "keep").lower()
    if fmt == "keep":
        fmt = {"jpeg": "jpg"}.get(src.suffix.lower().lstrip("."), src.suffix.lower().lstrip("."))
        if fmt not in ("jpg", "png", "webp"):
            fmt = "png" if img.mode == "RGBA" else "jpg"
    if fmt not in ("jpg", "png", "webp"):
        raise ValueError("format 只能是 keep / jpg / png / webp")
    return fmt


def write_psd(path, img):
    try:
        from psd_tools import PSDImage
        from psd_tools.api.layers import PixelLayer
        psd = PSDImage.new("RGB", img.size)
        layer = PixelLayer.frompil(img.convert("RGBA"), psd, "Layer", 0, 0)
        layer.name = "图像"
        psd.append(layer)
        psd.save(str(path))
        return True
    except ImportError as exc:
        raise ValueError("请求了PSD但缺少psd-tools，请补齐专用环境依赖") from exc
    except Exception as exc:
        raise ValueError(f"PSD生成失败：{exc}") from exc


def _name(job, src):
    name = str(job.get("name") or src.stem)
    if name in (".", "..") or any(char in name for char in '<>:"/\\|?*') or name.rstrip(" .") != name:
        raise ValueError("name 只能是文件名，不含路径或 Windows 特殊字符")
    if name.split('.')[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        raise ValueError("name不能是Windows保留设备名")
    return name


def _digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _output_paths(job, src, img):
    out_dir = Path(job.get("out_dir", ".")).expanduser().resolve()
    name = _name(job, src)
    image_path = out_dir / f"{name}.{out_format(job, src, img)}"
    paths = [image_path]
    if job.get("psd"):
        paths.append(out_dir / f"{name}.psd")
    if job.get("save_recipe"):
        paths.append(out_dir / f"{name}.framing.json")
    if src in paths:
        raise ValueError("输出路径与原图相同；请指定新名称或输出文件夹")
    return image_path, paths


class DeliveryError(ValueError):
    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


def publish_new(path, writer):
    """Write beside target, publish without replacement even when two workers race."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".resize-", suffix=path.suffix, dir=path.parent)
    os.close(handle)
    temporary = Path(temporary)
    try:
        if path.exists():
            raise FileExistsError(f"输出已存在，请使用新名称或新目录：{path}")
        writer(temporary)
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def preflight(jobs, completed=None):
    """Path and header checks only; full resampling occurs once in make."""
    completed = completed or {}
    inputs = {Path(j["input"]).expanduser().resolve() for j in jobs}
    seen = set()
    for job in jobs:
        resolved, _ = resolve_job(job)
        parse_size(job["size"])
        src = Path(job["input"]).expanduser().resolve()
        with Image.open(src) as opened:
            projected = Image.new("RGBA" if has_alpha(opened) else "RGB", (1, 1))
            _, paths = _output_paths(resolved, src, projected)
        for path in paths:
            if path in inputs:
                raise ValueError("输出会覆盖任务原图，请使用单独输出目录")
            reusable = str(path) in completed and path.is_file() and _digest(path) == completed[str(path)]
            if path in seen or (path.exists() and not reusable):
                raise ValueError(f"输出冲突或已存在，请使用新名称或新目录：{path}")
            seen.add(path)
            ancestor = path.parent
            while not ancestor.exists():
                ancestor = ancestor.parent
            if not ancestor.is_dir():
                raise ValueError(f"输出目录被文件阻挡：{ancestor}")


def make(job, completed=None, capture=None):
    src, img, plan, resolved = _render(job)
    out, paths = _output_paths(resolved, src, img)
    completed = completed or {}
    def reusable(path):
        return str(path) in completed and path.is_file() and _digest(path) == completed[str(path)]
    for path in paths:
        if path.exists() and not reusable(path):
            raise ValueError(f"输出已存在，请使用新名称或新目录：{path}")
    out.parent.mkdir(parents=True, exist_ok=True)
    result = {"input": str(src), "outputs": [], "size": list(img.size), "framing": plan, "status": "completed"}
    if resolved.get('_source_metadata'):
        result['source_metadata']=resolved['_source_metadata']
    if resolved.get('_processing'):
        result['processing']=resolved['_processing']
    from export_policy import DEFAULT_MAX_BYTES, encode_image
    limit=resolved.get('max_bytes',DEFAULT_MAX_BYTES)
    if type(limit) is not int or not 1 <= limit <= DEFAULT_MAX_BYTES:
        raise ValueError('图片字节上限必须为1至500000，不能超过500KB')
    fmt=out.suffix.lstrip('.')
    if fmt in ('jpg','png'):
        data,encoding=encode_image(img,fmt,max_bytes=limit)
    else:
        buffer=io.BytesIO()
        icc={'icc_profile':img.info['icc_profile']} if img.info.get('icc_profile') else {}
        img.save(buffer,format='WEBP',**icc)
        data=buffer.getvalue()
        if len(data)>limit:
            raise ValueError('WebP超过500KB；请明确采用JPG或PNG交付，不擅自改尺寸')
        encoding={'format':'webp','bytes':len(data),'max_bytes':limit,'quality':None}
    result['encoding']=encoding
    # Capture lossless rendered pixels for the grouped PSD, before JPEG encoding is written.
    if capture is not None:
        result['source_cache']=capture(img)
    if not reusable(out):
        publish_new(out, lambda temp: temp.write_bytes(data))
    if out.stat().st_size>limit:
        raise ValueError('实际图片字节超过已批准上限')
    result["outputs"].append(str(out))
    try:
        if resolved.get("psd"):
            psd = out.with_suffix(".psd")
            def save_psd(temp):
                if not write_psd(temp, img):
                    raise ValueError("PSD生成器未成功返回")
            if not reusable(psd):
                publish_new(psd, save_psd)
            result["outputs"].append(str(psd))
        if resolved["save_recipe"]:
            recipe = out.parent / f"{out.stem}.framing.json"
            replay_job = {**job, "input": str(src), "out_dir": str(out.parent)}
            text = json.dumps({"version": VERSION, "input_sha256": _digest(src), "job": replay_job,
                               "framing": plan}, ensure_ascii=False, indent=2)
            if not reusable(recipe):
                publish_new(recipe, lambda temp: temp.write_text(text, encoding="utf-8"))
            result["outputs"].append(str(recipe))
            result["recipe"] = str(recipe)
    except Exception as exc:
        result.update(status="partial", error=str(exc))
        raise DeliveryError(str(exc), result) from exc
    return result


def load_jobs(spec_path):
    from task_spec import load_jobs as fixed_load_jobs
    jobs = fixed_load_jobs(spec_path)
    if not jobs:
        raise ValueError("任务单 jobs 不能为空")
    keys = []
    for job in jobs:
        if "input" not in job or "size" not in job:
            raise ValueError("每项任务需要 input 和 size")
        src = Path(job["input"])
        key = (os.path.normcase(str(Path(job.get("out_dir", ".")).resolve())), os.path.normcase(_name(job, src)))
        if key in keys:
            raise ValueError(f"任务单中存在同目录同名输出：{key[1]}")
        keys.append(key)
    return jobs


def batch(jobs):
    preflight(jobs)
    return [make(job) for job in jobs]


def _font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def preview(jobs, out_path, thumb=320, limit=6):
    if limit < 0 or not jobs:
        raise ValueError("limit 必须大于等于 0，且任务单不能为空；0 表示全部")
    if Path(out_path).expanduser().resolve() in {Path(j["input"]).expanduser().resolve() for j in jobs}:
        raise ValueError("预览路径与原图相同；请使用其他预览文件名")
    selected = jobs if limit == 0 else jobs[:limit]
    cols, pad, lab = min(3, len(selected)), 16, 72
    rows = (len(selected) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (thumb + pad) + pad, rows * (thumb + lab + pad) + pad), (60, 60, 64))
    draw, font = ImageDraw.Draw(sheet), _font(14)
    for index, job in enumerate(selected):
        src, img, plan, resolved = _render(job)
        tile = img.copy()
        tile.thumbnail((thumb, thumb), Image.Resampling.LANCZOS)
        base = Image.new("RGB", (thumb, thumb), (90, 90, 96))
        xy = ((thumb - tile.width) // 2, (thumb - tile.height) // 2)
        base.paste(tile, xy, tile.getchannel("A") if tile.mode == "RGBA" else None)
        x, y = pad + (index % cols) * (thumb + pad), pad + (index // cols) * (thumb + lab + pad)
        sheet.paste(base, (x, y))
        label = f"{job.get('name') or src.stem}  {img.width}x{img.height}"
        label += f"\n{resolved.get('preset', '自定义')} / {plan['effective_fit']}"
        if plan["warnings"]:
            label += "\n注意：" + plan["warnings"][0][:18]
        draw.multiline_text((x, y + thumb + 6), label, font=font, fill=(240, 240, 240), spacing=3)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    publish_new(out_path, lambda temp: sheet.save(temp))
    return {"preview": str(out_path), "shown": len(selected), "total_jobs": len(jobs)}


def replay(recipe_path, out_dir=None, name=None):
    recipe = json.loads(Path(recipe_path).read_text(encoding="utf-8-sig"))
    if recipe.get("version") != VERSION:
        raise ValueError("参数文件版本与脚本不同；请使用对应版本重放")
    job = dict(recipe["job"])
    if _digest(job["input"]) != recipe["input_sha256"]:
        raise ValueError("原图内容已改变，无法保证复现；请重新预览")
    if out_dir is not None:
        job["out_dir"] = out_dir
    if name is not None:
        job["name"] = name
    return make(job)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="cmd", required=True)
    single = sub.add_parser("make", help="处理一张图片")
    single.add_argument("--input", required=True)
    single.add_argument("--size", required=True)
    single.add_argument("--fit", choices=FITS)
    single.add_argument("--preset", choices=tuple(PRESETS))
    single.add_argument("--out-dir", default=".")
    single.add_argument("--name")
    single.add_argument("--format", choices=("keep", "jpg", "png", "webp"))
    single.add_argument("--bg", choices=("white", "transparent"))
    single.add_argument("--psd", action="store_true")
    single.add_argument("--save-recipe", action=argparse.BooleanOptionalAction, default=None)
    for key in ("focus", "position", "offset", "crop-box", "subject-box", "protect-box"):
        single.add_argument("--" + key, help="逗号分隔的归一化坐标，详见 references/framing.md")
    single.add_argument("--zoom", type=float)
    single.add_argument("--subject-fill", type=float)
    single.add_argument("--on-conflict", choices=("contain", "error"))
    single.add_argument("--allow-padding", action=argparse.BooleanOptionalAction, default=None)
    single.add_argument("--allow-stretch", action=argparse.BooleanOptionalAction, default=None)
    many = sub.add_parser("batch", help="按 JSON 任务单批量生成")
    many.add_argument("--spec", required=True)
    pv = sub.add_parser("preview", help="仅生成预览")
    pv.add_argument("--spec", required=True)
    pv.add_argument("--out", default="preview.png")
    pv.add_argument("--limit", type=int, default=6, help="0 表示全部")
    again = sub.add_parser("replay", help="用保存的参数文件重做")
    again.add_argument("--recipe", required=True)
    again.add_argument("--out-dir")
    again.add_argument("--name")
    sub.add_parser("presets", help="列出预设及其起始值")
    args = vars(parser.parse_args())
    cmd = args.pop("cmd")
    try:
        if cmd == "make":
            result = make({key: value for key, value in args.items() if value is not None})
        elif cmd == "batch":
            result = batch(load_jobs(args["spec"]))
        elif cmd == "preview":
            result = preview(load_jobs(args["spec"]), args["out"], limit=args["limit"])
        elif cmd == "replay":
            result = replay(args["recipe"], args["out_dir"], args["name"])
        else:
            result = PRESETS
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.exit(2, f"[错误] {exc}\n")


if __name__ == "__main__":
    main()
