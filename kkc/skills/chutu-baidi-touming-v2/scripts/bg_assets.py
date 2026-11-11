#!/usr/bin/env python3
"""白底透明图：800×800、默认主体80%；每张两张图片，每款两份分层PSD。

任务单显式指定 style/color/input/out_dir/separate_image_folders；同色多角度用angle区分。
N张、K款共2N+2K个正式文件。preview只写预览，batch在用户确认后运行。
"""
import argparse, json, os, platform, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
import numpy as np
from image_size_limit import save_limited_image, verify_image_file, MAX_IMAGE_BYTES

SIZE = (800, 800)
DEFAULT_FILL = 0.80
QUEUE_FILE = "ps_queue.jsonl"
SUFFIX_WHITE = "-白底"
SUFFIX_TRANS = "-透明"
_SESSION = None


# ---------------- 抠图 ----------------
def has_real_alpha(im):
    if im.mode != "RGBA":
        return False
    a = np.asarray(im.getchannel("A"))
    return (a < 250).mean() > 0.01


def cutout_threshold(im, tol=28):
    """从四边泛洪去掉与边角颜色相近的连通背景，适合白底/纯色底原图。"""
    rgb = im.convert("RGB")
    arr = np.asarray(rgb).astype(np.int16)
    h, w, _ = arr.shape
    corners = np.array([arr[0, 0], arr[0, w - 1], arr[h - 1, 0], arr[h - 1, w - 1]])
    bgc = np.median(corners, axis=0)
    near = (np.abs(arr - bgc).max(axis=2) <= tol).astype(np.uint8) * 255
    mask = Image.fromarray(near).convert("L").copy()
    for x in range(0, w, max(1, w // 20)):
        for y in (0, h - 1):
            if mask.getpixel((x, y)) == 255:
                ImageDraw.floodfill(mask, (x, y), 128)
    for y in range(0, h, max(1, h // 20)):
        for x in (0, w - 1):
            if mask.getpixel((x, y)) == 255:
                ImageDraw.floodfill(mask, (x, y), 128)
    bg = np.asarray(mask) == 128
    alpha = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8), "L")
    alpha = alpha.filter(ImageFilter.GaussianBlur(0.8))
    out = rgb.convert("RGBA")
    out.putalpha(alpha)
    return out


def cutout(im, method="auto"):
    if method == "none":
        return im.convert("RGBA")
    if method == "auto" and has_real_alpha(im):
        return im.convert("RGBA")
    if method == "threshold":
        return cutout_threshold(im)
    if method not in ("auto", "rembg"):
        raise ValueError(f"未知抠图方式：{method}")
    global _SESSION
    from rembg import remove, new_session
    if _SESSION is None:
        _SESSION = new_session("u2net", providers=["CPUExecutionProvider"])
    # Failure is explicit: never silently substitute threshold cutout for u2net.
    return remove(im.convert("RGBA"), session=_SESSION)


def place_subject(subject, fill):
    """把抠好的主体按 fill 比例居中放进 800x800 画布，返回 (主体图层, left, top)。"""
    W, H = SIZE
    bbox = subject.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("抠图结果完全透明，不能生成商品文件")
    subj = subject.crop(bbox)
    sw, sh = subj.size
    scale = min(W * fill / sw, H * fill / sh)
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    subj = subj.resize((nw, nh), Image.LANCZOS)
    return subj, (W - nw) // 2, (H - nh) // 2


# ---------------- PSD ----------------
def write_psd(path, layers, transparent=False, hd_assets=None):
    """自下而上写入(名称, RGBA, left, top, visible)；失败抛出，不转队列冒充成功。"""
    if hd_assets is not None:
        import hd_mask_psd
        return hd_mask_psd.write(path,hd_assets,transparent=transparent)
    from psd_tools import PSDImage
    # Keep alpha on every product layer, including in the white-background PSD.
    document = PSDImage.new("RGBA", SIZE)
    document.background_color = None
    for name, picture, left, top, visible in layers:
        layer = document.create_pixel_layer(picture.convert("RGBA"), name="Layer", top=top, left=left)
        layer.name = name
        layer.visible = visible
    document._record.layer_and_mask_information.layer_info.layer_count = -len(document)
    document.save(str(path))


# ---------------- 主流程 ----------------
def check_fill(fill):
    fill = float(fill)
    if not 0.5 <= fill <= 0.95:
        raise ValueError(f"占比 {fill} 超出范围，应在 0.5~0.95 之间")
    return fill


def render(job):
    """只渲染不落盘：返回白底、透明及带正确位置的产品图层。"""
    with Image.open(job["input"]) as source:
        im = source.convert("RGBA")
    fill = check_fill(job.get("fill", DEFAULT_FILL))
    subj, left, top = place_subject(cutout(im, job.get("cutout", "auto")), fill)
    bg = Image.new("RGBA", SIZE, (255, 255, 255, 255))
    white = bg.copy()
    white.alpha_composite(subj, (left, top))
    trans = Image.new("RGBA", SIZE, (0, 0, 0, 0))
    trans.alpha_composite(subj, (left, top))
    return white.convert("RGB"), trans, (job["layer_name"], subj, left, top)


def check_name(value, field):
    if not isinstance(value, str) or not value or value in (".", ".."):
        raise ValueError(f"{field}不能为空，且必须是明确名称")
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value.endswith((".", " ")):
        raise ValueError(f"{field}含Windows非法字符或结尾点/空格：{value!r}")
    stem = value.split(".", 1)[0].upper()
    if stem in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", stem):
        raise ValueError(f"{field}是Windows保留名称：{value!r}")
    return value


def path_key(path):
    return str(Path(path).resolve()).casefold()


def existing_casefold(path):
    """Also catches casing conflicts when tests run on a case-sensitive filesystem."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        return path
    if path.parent.is_dir():
        return next((p for p in path.parent.iterdir() if p.name.casefold() == path.name.casefold()), None)
    return None


def preflight(plan):
    seen = set()
    sources = {path_key(j["input"]) for j in plan["jobs"]}
    for value in plan["outputs"]:
        key = path_key(value)
        if key in seen:
            raise ValueError(f"Windows大小写不敏感的输出同名冲突：{value}")
        seen.add(key)
        if key in sources:
            raise ValueError(f"输出将覆盖原图：{value}")
        if existing_casefold(value) is not None:
            raise FileExistsError(f"目标已存在，未经确认不覆盖；请换目录或改名：{value}")
        for parent in Path(value).parents:
            found = existing_casefold(parent)
            if found is not None and not found.is_dir():
                raise FileExistsError(f"输出目录被文件占用：{found}")


def build_plan(spec):
    defaults = spec.get("defaults", {})
    raw_jobs = spec.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise ValueError("任务单jobs必须包含至少一张图片")
    jobs, missing = [], []
    for i, raw in enumerate(raw_jobs, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"第{i}项必须是任务对象")
        j = {**defaults, **raw}
        absent = [k for k in ("style", "color", "input", "out_dir", "separate_image_folders") if k not in j or j[k] is None or j[k] == ""]
        if absent:
            missing.append(f"第{i}项缺少：{', '.join(absent)}")
            continue
        j["style"] = check_name(j["style"], f"第{i}项款式")
        j["color"] = check_name(j["color"], f"第{i}项颜色")
        angle = j.get("angle")
        if angle is not None:
            angle = check_name(angle, f"第{i}项角度/序号")
        j["angle"] = angle
        j["layer_name"] = j["color"] + ("-" + angle if angle else "")
        check_name(j["layer_name"], f"第{i}项图层名")
        if type(j["separate_image_folders"]) is not bool:
            raise ValueError("separate_image_folders必须是true或false，请先选择图片存放方式")
        for k in ("input", "out_dir"):
            if not Path(j[k]).is_absolute():
                raise ValueError(f"第{i}项{k}必须是绝对路径")
            j[k] = str(Path(j[k]).resolve())
        if not Path(j["input"]).is_file():
            raise FileNotFoundError(f"原图不存在：{j['input']}")
        j["fill"] = check_fill(j.get("fill", DEFAULT_FILL))
        if j.get("cutout", "auto") not in ("auto", "rembg", "threshold", "none"):
            raise ValueError("未知cutout参数")
        jobs.append(j)
    if missing:
        raise ValueError("请一次确认以下任务信息（不猜测款式/颜色/目录选项）：\n" + "\n".join(missing))
    roots = {path_key(j["out_dir"]) for j in jobs}
    modes = {j["separate_image_folders"] for j in jobs}
    if len(roots) != 1 or len(modes) != 1:
        raise ValueError("同一批任务须明确一个输出根目录和一种图片存放方式；不同批请分任务单")
    root, separate = Path(jobs[0]["out_dir"]), jobs[0]["separate_image_folders"]
    groups, styles_by_key = {}, {}
    for j in jobs:
        style = j["style"]
        key = style.casefold()
        if key in styles_by_key and styles_by_key[key] != style:
            raise ValueError(f"款式名称大小写冲突，请确认归属：{styles_by_key[key]} / {style}")
        styles_by_key[key] = style
        group = groups.setdefault(style, {"style": style, "images": [], "psd": {
            "white": str(root / style / f"{style}-白底.psd"),
            "transparent": str(root / style / f"{style}-透明.psd")}})
        label, directory = j["layer_name"], root / style
        j["white"] = str(directory / "白底图" / f"{label}.jpg" if separate else directory / f"{label}-白底.jpg")
        j["transparent"] = str(directory / "透明图" / f"{label}.png" if separate else directory / f"{label}-透明.png")
        group["images"].append(j)
    outputs, files = [], []
    for group in groups.values():
        for j in group["images"]:
            for kind in ("white", "transparent"):
                outputs.append(j[kind])
                files.append({"path": j[kind], "kind": kind + "_image", "style": j["style"], "layer_name": j["layer_name"], "input": j["input"]})
        for kind, value in group["psd"].items():
            outputs.append(value)
            files.append({"path": value, "kind": kind + "_psd", "style": group["style"]})
    plan = {"schema_version": 2, "input_count": len(jobs), "style_count": len(groups),
            "image_count": 2 * len(jobs), "psd_count": 2 * len(groups), "total_files": len(outputs),
            "separate_image_folders": separate, "out_dir": str(root), "styles": list(groups.values()),
            "jobs": jobs, "outputs": outputs, "files": files}
    preflight(plan)
    return plan


def load_plan(spec_path):
    return build_plan(json.loads(Path(spec_path).read_text(encoding="utf-8-sig")))


def auxiliary_path(path, plan):
    path = Path(path).resolve()
    if path.is_relative_to(Path(plan["out_dir"])) or path_key(path) in {path_key(j["input"]) for j in plan["jobs"]}:
        raise ValueError("预览/清单必须位于正式输出目录之外，且不能覆盖原图")
    if existing_casefold(path) is not None:
        raise FileExistsError(f"预览/清单目标已存在，请换名：{path}")
    return path


def batch(plan, manifest=None):
    """先在临时目录生成完整批次，再排他写入正式文件；PSD失败绝不算完成。"""
    preflight(plan)
    manifest = auxiliary_path(manifest, plan) if manifest else None
    stage = Path(tempfile.mkdtemp(prefix="chutu-style-psd-"))
    staged = {}
    compression = {}
    try:
        for group in plan["styles"]:
            products = []
            for index, job in enumerate(group["images"]):
                white, trans, product = render(job)
                for kind, image in (("white", white), ("transparent", trans)):
                    destination = Path(job[kind])
                    temporary = stage / f"{len(staged):06d}{destination.suffix}"
                    compression[str(destination)] = save_limited_image(image, temporary, kind)
                    staged[str(destination)] = temporary
                products.append((*product, index == 0))
            background = ("背景", Image.new("RGBA", SIZE, "white"), 0, 0, True)
            for kind, layers in (("white", [background, *products]), ("transparent", products)):
                destination = group["psd"][kind]
                temporary = stage / f"{len(staged):06d}.psd"
                write_psd(temporary, layers, transparent=kind == "transparent")
                staged[destination] = temporary
        for destination in compression:
            verify_image_file(staged[destination])
        preflight(plan)
        for destination in plan["outputs"]:
            target = Path(destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            if existing_casefold(target) is not None:
                raise FileExistsError(f"写入前发现目标已存在：{target}")
            with staged[destination].open("rb") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
        image_sizes = {p: verify_image_file(p) for p in compression}
        result = dict(plan, passed=True, max_image_bytes=MAX_IMAGE_BYTES,
                      image_compression=compression, image_size_verification=image_sizes)
        if manifest:
            manifest.parent.mkdir(parents=True, exist_ok=True)
            with manifest.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
        shutil.rmtree(stage)
        return result
    except Exception as error:
        raise RuntimeError(f"批次未完整完成；保留暂存现场：{stage}；原因：{error}") from error


# ---------------- 预览 ----------------
FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
    "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]


def _font(size):
    from PIL import ImageFont
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _checker(size, cell=16):
    im = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(im)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                d.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(225, 225, 225))
    return im


def preview(plan, out_path, thumb=320, limit=4, offset=0):
    """每张原图一行：左白底、右透明（棋盘格底）。不写正式文件。"""
    if limit < 0 or offset < 0 or offset >= plan["input_count"]:
        raise ValueError("预览offset/limit越界；limit=0表示全部")
    out_path = auxiliary_path(out_path, plan)
    jobs = plan["jobs"][offset:offset + limit if limit else None]
    rows = []
    for j in jobs:
        white, trans, _ = render(j)
        name = f"{j['style']} / {j['layer_name']}"
        fill = int(round(float(j.get("fill", DEFAULT_FILL)) * 100))
        w = white.copy(); w.thumbnail((thumb, thumb), Image.LANCZOS)
        t = trans.copy(); t.thumbnail((thumb, thumb), Image.LANCZOS)
        tb = _checker(t.size); tb.paste(t, (0, 0), t)
        rows.append([(w, f"{name} 白底  占比{fill}%"),
                     (tb, f"{name} 透明  占比{fill}%")])
    pad, lab = 16, 34
    W = 2 * (thumb + pad) + pad
    H = len(rows) * (thumb + lab + pad) + pad
    sheet = Image.new("RGB", (W, H), (60, 60, 64))
    d = ImageDraw.Draw(sheet)
    f = _font(15)
    for r, row in enumerate(rows):
        for c, (img, label) in enumerate(row):
            cx, cy = pad + c * (thumb + pad), pad + r * (thumb + lab + pad)
            sheet.paste(img, (cx, cy))
            d.rectangle((cx, cy, cx + thumb - 1, cy + thumb - 1), outline=(120, 120, 128))
            d.text((cx, cy + thumb + 8), label, fill=(240, 240, 240), font=f)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("xb") as stream:
        sheet.save(stream, format="PNG")
    return dict(plan, preview=str(out_path), shown=len(rows), offset=offset,
                remaining=max(0, plan["input_count"] - offset - len(rows)), formal_files_written=0)


# ---------------- PS 队列 / 空闲检测 ----------------
def queue_add(task, qpath):
    task = dict(task, created=time.strftime("%Y-%m-%d %H:%M:%S"), status="pending")
    Path(qpath).parent.mkdir(parents=True, exist_ok=True)
    with open(qpath, "a", encoding="utf-8") as f:
        f.write(json.dumps(task, ensure_ascii=False) + "\n")


def idle_seconds():
    sysname = platform.system()
    if sysname == "Windows":
        import ctypes
        class LII(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        lii = LII(); lii.cbSize = ctypes.sizeof(LII)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0
    if sysname == "Darwin":
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "HIDIdleTime" in line:
                return int(line.split("=")[-1].strip()) / 1e9
    return -1.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("make", help="单张任务，必须指定款式、颜色和图片存放方式")
    m.add_argument("--input", required=True)
    m.add_argument("--out-dir", required=True)
    m.add_argument("--style", required=True)
    m.add_argument("--color", required=True)
    m.add_argument("--angle", help="同色多角度时明确填写角度或序号")
    mode = m.add_mutually_exclusive_group(required=True)
    mode.add_argument("--separate-image-folders", dest="separate_image_folders", action="store_true")
    mode.add_argument("--same-image-folder", dest="separate_image_folders", action="store_false")
    m.add_argument("--fill", type=float, default=DEFAULT_FILL, help="主体占比，默认 0.80")
    m.add_argument("--cutout", choices=["auto", "rembg", "threshold", "none"], default="auto")

    b = sub.add_parser("batch")
    b.add_argument("--spec", required=True, help="JSON任务单：defaults含out_dir/separate_image_folders，jobs含style/color/input")
    b.add_argument("--manifest", help="可选JSON文件清单，必须放在正式输出目录之外")

    planning = sub.add_parser("plan", help="只核对任务单与文件数，不渲染、不写文件")
    planning.add_argument("--spec", required=True)

    pv = sub.add_parser("preview")
    pv.add_argument("--spec", required=True)
    pv.add_argument("--out", default="preview.png")
    pv.add_argument("--limit", type=int, default=4)
    pv.add_argument("--offset", type=int, default=0, help="分页起点；limit=0一次预览全部")

    q = sub.add_parser("queue")
    q.add_argument("--file", default=QUEUE_FILE)
    q.add_argument("--task", required=True)

    sub.add_parser("idle")

    a = ap.parse_args()
    if a.cmd == "make":
        job = {k: v for k, v in vars(a).items() if k != "cmd" and v is not None}
        print(json.dumps(batch(build_plan({"jobs": [job]})), ensure_ascii=False, indent=2))
    elif a.cmd == "batch":
        print(json.dumps(batch(load_plan(a.spec), a.manifest), ensure_ascii=False, indent=2))
    elif a.cmd == "plan":
        print(json.dumps(load_plan(a.spec), ensure_ascii=False, indent=2))
    elif a.cmd == "preview":
        print(json.dumps(preview(load_plan(a.spec), a.out, limit=a.limit, offset=a.offset), ensure_ascii=False, indent=2))
    elif a.cmd == "queue":
        queue_add(json.loads(a.task), a.file)
        print(f"已加入 PS 队列: {a.file}")
    elif a.cmd == "idle":
        print(f"{idle_seconds():.0f}")


if __name__ == "__main__":
    raise SystemExit('V2请通过scripts/launch.py运行，必须先预览、复核和确认。')
