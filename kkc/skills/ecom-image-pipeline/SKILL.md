---
name: "ecom-image-pipeline"
description: "电商图片出图（场景图改尺寸、白底图、透明PNG、PSD源文件、SKU）时使用：先用选项让用户选背景/尺寸/占比/位置/数量/命名，出预览确认后再后台Python生成，不占用Photoshop；必要步骤才进PS队列。"
---

# 电商图片素材：后台出图 + PS 队列

目标：出图时**不和用户抢 Photoshop**。能用 Python 做的全部在后台完成；只有确实需要 PS 的步骤才进队列。
流程固定为：**选参数（选项模式）→ 出预览 → 用户确认 → 正式生成**。用户确认预览之前，不写任何正式文件。

## 第 0 步：准备脚本（每台电脑首次使用）

本文中的 `PY` 表示 Python 命令：macOS 用 `python3`，Windows 用 `py`。先用 `uname` 或系统信息判断当前平台。
本文命令里的 `~/.ps-asset-pipeline/ps_assets.py` 是 macOS 写法。Windows 上 `~` 不会被展开：PowerShell 里写成 `$HOME\.ps-asset-pipeline\ps_assets.py`，cmd 里写成 `%USERPROFILE%\.ps-asset-pipeline\ps_assets.py`。Windows 的桌面可能被 OneDrive 接管（`%USERPROFILE%\OneDrive\Desktop`），先确认桌面的真实路径再写入。

**运行环境**：
- **能在用户电脑上执行命令时**（比如 Codex，或者本机运行的 Claude）：在用户电脑上安装并运行脚本。这是首选方式，因为可以用 rembg 抠图。
- **只能读写用户文件、不能在用户电脑上执行命令时**（比如云端 Claude 只连接了用户文件夹）：先申请访问原图所在文件夹和输出文件夹；把原图拷贝到云端，在云端运行脚本；预览图直接发给用户看，成品写回用户指定的文件夹。云端没有 rembg 时只能做纯色背景抠图，所以遇到复杂背景要先告诉用户，并建议改在本机运行，或者改用 Codex。

1. 检查 `~/.ps-asset-pipeline/ps_assets.py` 是否存在；不存在就把本文末尾「附：ps_assets.py」的代码原样写入该路径。
   已存在但没有 `preview` 子命令（`-h` 里看不到），或者 write_psd 里没有 `layer.name = name` 这一行时，用附录版本覆盖。
2. 安装依赖：`PY -m pip install pillow numpy psd-tools "rembg[cpu]" -i https://pypi.tuna.tsinghua.edu.cn/simple`。
   macOS 上报 externally-managed-environment 时，末尾加 `--user --break-system-packages`。出现 "not on PATH" 警告可以忽略。rembg 首次运行会下载约 170MB 的模型。
3. 用 `PY ~/.ps-asset-pipeline/ps_assets.py -h` 自检。

## 第 1 步：确认素材

找到用户给的原图：附件、路径或文件夹都可以。数一下原图张数，记为 N，后面的选项会用到。
找不到原图时先让用户提供，**不要猜**。

## 第 2 步：选项模式收集参数

**所有参数都让用户选，不要自己定。** 用户在需求里已经写明的参数，直接填进去，不再重复问。
用 AskUserQuestion 提问。每题都给选项，用户可以选"其他"自己输入。分两轮问，每轮最多 4 题。
没有 AskUserQuestion 工具时（比如在 Codex 里），用带编号的文字列出同样的题目和选项，请用户回复编号或自定义内容。

**第一轮：做成什么样**

| 题目（header） | 选项 |
|---|---|
| 背景类型（背景） | 白底图 / 透明PNG / 白底+透明各一套 / 场景图（保留原背景，只改尺寸） |
| 修改后的尺寸（尺寸） | 800×800（推荐） / 750×1000 / 1000×1000 / 其他：自定义 宽×高 |
| 画面占用率，即主体占画布的比例（占比） | 70%（留白多） / 78%（推荐） / 85%（饱满） / 其他：自定义百分比 |
| 是否同时生成 PSD 源文件（PSD） | 需要，每套一个分层 PSD / 不需要 |

说明：
- 选了"场景图"时，占比那题换成"适配方式"：完整显示、空白补白（contain，推荐） / 铺满裁切（cover） / 拉伸（stretch）。
- 自定义输入要先校验再用。尺寸必须是"数字×数字"；占比必须在 50%～95% 之间，超出范围就请用户重新输入。

**第二轮：存到哪、出几张、叫什么**

| 题目（header） | 选项 |
|---|---|
| 保存位置（位置） | 桌面新建文件夹（问文件夹名） / 原图所在文件夹下新建"输出" / 其他：自定义完整路径 |
| 生成数量（数量） | 每张原图各出 1 张，共 N 张 / 只处理其中几张（请用户指定） / 其他：自定义 |
| 命名方式（命名） | 按顺序 1、2、3… / 用原文件名 / 按颜色或款式名自定义（请用户按顺序输入，如 潮汐灰,雪雾紫,云落黑） / 其他：自定义前缀，如"主图-1" |

说明：
- 选了"白底+透明各一套"时，实际张数是 2 × 数量。命名会自动加后缀，例如 `潮汐灰-白底.jpg` 和 `潮汐灰-透明.png`。
- 用户自定义的名字个数和张数对不上时，列出对照表请用户确认，不要自己补名字。
- 保存位置解析成真实绝对路径（例如桌面在 macOS 上是 `~/Desktop`，在 Windows 上是 `C:/Users/<用户名>/Desktop`），文件夹不存在就新建。
- 输出目录里已有同名文件时，用选项问用户：覆盖 / 自动加后缀 `(2)` / 换个名字。

收齐后，用一张表复述全部参数（原图 → 输出文件名、尺寸、背景、占比、PSD、保存路径），然后进入预览。

## 第 3 步：判断分支

| 需求 | 分支 |
|---|---|
| 改尺寸、白底、透明 PNG、分层 PSD | A：后台 Python，不碰 PS |
| 调色/修图/液化/文字特效/智能对象/套公司 PSD 模板/SKU 拼版设计，或用户明确要求"用 PS 做" | B：PS 队列 |

## 第 4 步：预览（必须做）

1. 根据参数写任务单 `job.json`（格式见下方「分支 A」），放在临时目录，不要放进用户的输出目录。
2. 生成预览拼图。这一步不会写正式文件：
   ```
   PY ~/.ps-asset-pipeline/ps_assets.py preview --spec job.json --out <临时目录>/preview.png
   ```
   拼图最多显示前 6 张。透明图下面垫的是灰白棋盘格，每张下方标注文件名、尺寸、背景和占比。
3. 打开 preview.png 自己先看一遍，检查抠图边缘、是否居中、有没有被裁掉。然后把预览图发给用户。
4. 用 AskUserQuestion 在**同一次调用里问两题**：

   **题 1：效果确认（确认）**
   - 确认效果
   - 主体再小一点（占比 -7%）
   - 主体再大一点（占比 +7%）
   - 其他：自定义修改（换尺寸、换背景、改名字、某张抠图不好……）

   **题 2：是否使用 PS（PS）**
   - 不用 PS，全部后台生成（推荐）：只走分支 A，PS 完全不受影响
   - 后台生成后再进 PS 精修（排队）：先走分支 A 出图，再把精修任务写进 PS 队列，等用户空闲或同意后再执行
   - 现在就用 PS 做（会占用 PS）：先提醒用户，这期间不要操作 PS；然后按分支 B 的硬规则立即执行
   - 其他：说明哪几张图需要用 PS、做什么处理

   如果某张图抠图明显有问题，在题 2 的问题描述里写明是哪张，并建议这张选"进 PS 精修"。
5. 题 1 没选"确认效果"时，改任务单、重新预览，两题一起再问一次，直到确认为止。
6. 题 1 确认后，按题 2 的选择走：
   - 选"不用 PS"：进入第 5 步。
   - 选"进 PS 精修"：先做第 5 步，再对需要精修的图执行分支 B 的入队。精修内容先用选项问用户：调色 / 修瑕疵 / 套公司模板 / 其他。
   - 选"现在就用 PS"：先做第 5 步生成底图和 PSD，再立即执行分支 B，不用等空闲检测。

## 第 5 步：正式生成（分支 A）

用户确认后才运行：
```
PY ~/.ps-asset-pipeline/ps_assets.py batch --spec job.json
```

任务单格式：`defaults` 放公共参数，`jobs` 每项是一张输出图：
```json
{"defaults": {"size": "800x800", "out_dir": "/Users/xx/Desktop/暖兜兜连帽羽绒服", "fill": 0.78},
 "jobs": [
  {"input": "/Users/xx/素材/潮汐灰.jpg", "mode": "white",       "name": "潮汐灰-白底", "psd": "潮汐灰-白底.psd"},
  {"input": "/Users/xx/素材/潮汐灰.jpg", "mode": "transparent", "name": "潮汐灰-透明", "psd": true},
  {"input": "/Users/xx/素材/场景750.jpg", "mode": "scene", "fit": "contain", "name": "1"}
 ]}
```
各字段：
- `mode`：white / transparent / scene
- `fill`：占比，取 0.5～0.95
- `fit`：只对场景图生效，取 contain / cover / stretch
- `psd`：true 表示与图片同名；也可以直接写 PSD 文件名
- `format`：可选，jpg 或 png。透明图固定输出 png

规则：只写新文件，**不覆盖原图**。原图本身带透明通道时，脚本直接用，不重复抠图。

## 分支 B：PS 队列（只在用户不用 PS 时执行）

入队（不碰 PS）：
```
PY ~/.ps-asset-pipeline/ps_assets.py queue --file 输出目录/ps_queue.jsonl --task '{"action":"套模板","input":"绝对路径","template":"绝对路径.psd","output":"绝对路径","note":"用户原话"}'
```
入队后告诉用户：哪些图在队列里、为什么必须用 PS，并用选项问：现在可以占用 PS / 等我空闲时再做 / 取消这些任务。

**执行条件**，满足任一条才能调用 Photoshop MCP：
1. 用户选了"现在可以占用 PS"；
2. 无人值守时，`PY ~/.ps-asset-pipeline/ps_assets.py idle` 返回的空闲秒数 ≥ 600。

**执行时的硬规则**：
- 每个任务都在一段脚本里完成"按绝对路径打开 → 处理 → 另存为 → 关闭该文档"，不用 activeDocument。
- 不关闭、不修改用户自己打开的文档。
- 脚本开头设置 `app.displayDialogs = DialogModes.NO`。
- 每个任务开始前重新检查 idle；用户恢复操作（idle < 60）就停下，剩余任务留在队列里。
- 完成的任务把 status 改成 `done`，失败的改成 `failed` 并写明原因。

## 第 6 步：交付

列出生成的文件清单：文件名、尺寸、路径，有 PSD 的一并列出。再列出仍在 PS 队列里的任务（以及预览时选择的 PS 使用方式），以及需要用户人工检查的图。

## 附：ps_assets.py

```python
#!/usr/bin/env python3
"""电商图片素材后台处理脚本（不占用 Photoshop）。

子命令:
  make   单张出图：场景图改尺寸 / 白底图 / 透明 PNG，可选生成分层 PSD
  batch  按 JSON 任务单批量出图
  preview 按任务单渲染对比预览图（不写正式文件）
  queue  把必须用 PS 的任务写进队列（不碰 PS）
  idle   查询用户已空闲多少秒（用于判断能否执行 PS 队列）

依赖: pip install pillow numpy psd-tools rembg[cpu]
  - psd-tools 缺失: 不生成 PSD，自动转入 PS 队列
  - rembg 缺失: 退化为"纯色背景抠图"，只适合白底/纯色底原图
"""
import argparse, json, os, platform, subprocess, sys, time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
import numpy as np

QUEUE_FILE = "ps_queue.jsonl"


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
    if method in ("auto",) and has_real_alpha(im):
        return im.convert("RGBA")
    if method in ("auto", "rembg"):
        try:
            from rembg import remove
            return remove(im.convert("RGBA"))
        except ImportError:
            if method == "rembg":
                sys.exit("未安装 rembg：pip install \"rembg[cpu]\"")
            print("[提示] 未安装 rembg，使用纯色背景抠图（复杂背景效果差）", file=sys.stderr)
    return cutout_threshold(im)


# ---------------- 构图 ----------------
def place_subject(subject, size, fill):
    """把抠好的主体按 fill 比例居中放进画布，返回 (主体图层, left, top)。"""
    W, H = size
    bbox = subject.getchannel("A").getbbox() or (0, 0, *subject.size)
    subj = subject.crop(bbox)
    sw, sh = subj.size
    scale = min(W * fill / sw, H * fill / sh)
    nw, nh = max(1, round(sw * scale)), max(1, round(sh * scale))
    subj = subj.resize((nw, nh), Image.LANCZOS)
    return subj, (W - nw) // 2, (H - nh) // 2


def scene_resize(im, size, fit):
    W, H = size
    im = im.convert("RGB")
    if fit == "stretch":
        return im.resize((W, H), Image.LANCZOS)
    sw, sh = im.size
    if fit == "cover":
        s = max(W / sw, H / sh)
        r = im.resize((round(sw * s), round(sh * s)), Image.LANCZOS)
        l, t = (r.width - W) // 2, (r.height - H) // 2
        return r.crop((l, t, l + W, t + H))
    # contain：等比缩放，空白处补白
    s = min(W / sw, H / sh)
    r = im.resize((round(sw * s), round(sh * s)), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    canvas.paste(r, ((W - r.width) // 2, (H - r.height) // 2))
    return canvas


# ---------------- PSD ----------------
def write_psd(path, size, layers):
    """layers: [(名称, RGBA图, left, top)]，自下而上。失败返回 False。"""
    try:
        from psd_tools import PSDImage
        from psd_tools.api.layers import PixelLayer
    except ImportError:
        return False
    try:
        # 文档用 RGB 模式（RGBA 模式在 psd-tools 1.11 下合成预览会写坏文件）；
        # 图层本身仍带透明度。中文图层名要通过 layer.name 设置，
        # 直接传给 frompil 会按 Mac 旧编码写入而报错。
        psd = PSDImage.new("RGB", size)
        for name, img, left, top in layers:
            layer = PixelLayer.frompil(img.convert("RGBA"), psd, "Layer", top, left)
            layer.name = name
            psd.append(layer)
        psd.save(str(path))
        return True
    except Exception as e:  # 版本差异等
        print(f"[提示] PSD 生成失败: {e}", file=sys.stderr)
        return False


# ---------------- 主流程 ----------------
def parse_size(s):
    w, h = s.lower().replace("×", "x").split("x")
    return int(w), int(h)


def make(job):
    src = Path(job["input"])
    out_dir = Path(job.get("out_dir", "."))
    out_dir.mkdir(parents=True, exist_ok=True)
    size = parse_size(job.get("size", "800x800"))
    mode = job.get("mode", "white")  # scene | white | transparent
    name = job.get("name") or src.stem
    fmt = job.get("format") or ("png" if mode == "transparent" else "jpg")
    im = Image.open(src)
    im.load()
    result = {"input": str(src), "outputs": []}

    if mode == "scene":
        canvas = scene_resize(im, size, job.get("fit", "contain"))
        layers = [("图像", canvas.convert("RGBA"), 0, 0)]
        final = canvas
    else:
        subj = cutout(im, job.get("cutout", "auto"))
        subj, left, top = place_subject(subj, size, float(job.get("fill", 0.78)))
        if mode == "white":
            bg = Image.new("RGBA", size, (255, 255, 255, 255))
            final = bg.copy()
            final.alpha_composite(subj, (left, top))
            final = final.convert("RGB")
            layers = [("背景", bg, 0, 0), ("产品", subj, left, top)]
        else:
            final = Image.new("RGBA", size, (0, 0, 0, 0))
            final.alpha_composite(subj, (left, top))
            layers = [("产品", subj, left, top)]
            fmt = "png"

    out = out_dir / f"{name}.{fmt}"
    if fmt in ("jpg", "jpeg"):
        final.convert("RGB").save(out, quality=95, subsampling=0)
    else:
        final.save(out)
    result["outputs"].append(str(out))

    psd_name = job.get("psd")  # True 或 PSD 文件名
    if psd_name:
        psd_path = out_dir / (f"{name}.psd" if psd_name is True else f"{psd_name}")
        if write_psd(psd_path, size, layers):
            result["outputs"].append(str(psd_path))
        else:
            queue_add({"action": "make_psd", "from_job": job, "reason": "psd-tools 不可用"},
                      out_dir / QUEUE_FILE)
            result["queued"] = str(out_dir / QUEUE_FILE)
    return result


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


def preview(jobs, out_path, thumb=360, limit=6):
    """不写正式文件：把前 limit 个任务渲染到临时目录，拼成一张对比预览图。"""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="ps_preview_"))
    tiles = []
    for j in jobs[:limit]:
        r = make({**j, "out_dir": str(tmp), "psd": None})
        im = Image.open(r["outputs"][0])
        mode_cn = {"white": "白底", "transparent": "透明PNG", "scene": "场景图"}.get(j.get("mode", "white"), j.get("mode"))
        label = f"{j.get('name') or Path(j['input']).stem}  {im.width}x{im.height}  {mode_cn}"
        if j.get("mode") != "scene":
            label += f"  占比{int(float(j.get('fill', 0.78)) * 100)}%"
        t = im.copy()
        t.thumbnail((thumb, thumb), Image.LANCZOS)
        base = _checker(t.size) if t.mode == "RGBA" else Image.new("RGB", t.size, (255, 255, 255))
        if t.mode == "RGBA":
            base.paste(t, (0, 0), t)
        else:
            base.paste(t)
        tiles.append((base, label))
    pad, lab = 16, 34
    cols = min(3, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    W = cols * (thumb + pad) + pad
    H = rows * (thumb + lab + pad) + pad
    sheet = Image.new("RGB", (W, H), (60, 60, 64))
    d = ImageDraw.Draw(sheet)
    f = _font(16)
    for i, (t, label) in enumerate(tiles):
        cx = pad + (i % cols) * (thumb + pad)
        cy = pad + (i // cols) * (thumb + lab + pad)
        sheet.paste(t, (cx + (thumb - t.width) // 2, cy + (thumb - t.height) // 2))
        d.rectangle((cx, cy, cx + thumb - 1, cy + thumb - 1), outline=(120, 120, 128))
        d.text((cx, cy + thumb + 8), label, fill=(240, 240, 240), font=f)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return {"preview": str(out_path), "shown": len(tiles), "total_jobs": len(jobs)}


def queue_add(task, qpath):
    task = dict(task, created=time.strftime("%Y-%m-%d %H:%M:%S"), status="pending")
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

    m = sub.add_parser("make")
    m.add_argument("--input", required=True)
    m.add_argument("--out-dir", default=".")
    m.add_argument("--name")
    m.add_argument("--size", default="800x800")
    m.add_argument("--mode", choices=["scene", "white", "transparent"], default="white")
    m.add_argument("--fit", choices=["contain", "cover", "stretch"], default="contain")
    m.add_argument("--fill", type=float, default=0.78, help="主体占画布比例，0.7-0.85 为宜")
    m.add_argument("--cutout", choices=["auto", "rembg", "threshold", "none"], default="auto")
    m.add_argument("--format", choices=["png", "jpg"])
    m.add_argument("--psd", nargs="?", const=True, help="同时生成分层 PSD，可给文件名")

    b = sub.add_parser("batch")
    b.add_argument("--spec", required=True, help="JSON: {defaults:{...}, jobs:[{...}]}")

    pv = sub.add_parser("preview")
    pv.add_argument("--spec", required=True, help="与 batch 相同的任务单")
    pv.add_argument("--out", default="preview.png", help="预览拼图保存位置")
    pv.add_argument("--limit", type=int, default=6)

    q = sub.add_parser("queue")
    q.add_argument("--file", default=QUEUE_FILE)
    q.add_argument("--task", required=True, help="JSON 字符串，描述需要 PS 完成的操作")

    sub.add_parser("idle")

    a = ap.parse_args()
    if a.cmd == "make":
        job = {k: v for k, v in vars(a).items() if k != "cmd" and v is not None}
        print(json.dumps(make(job), ensure_ascii=False, indent=2))
    elif a.cmd == "batch":
        spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
        d = spec.get("defaults", {})
        results = [make({**d, **j}) for j in spec["jobs"]]
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif a.cmd == "preview":
        spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
        d = spec.get("defaults", {})
        jobs = [{**d, **j} for j in spec["jobs"]]
        print(json.dumps(preview(jobs, a.out, limit=a.limit), ensure_ascii=False, indent=2))
    elif a.cmd == "queue":
        queue_add(json.loads(a.task), a.file)
        print(f"已加入 PS 队列: {a.file}")
    elif a.cmd == "idle":
        print(f"{idle_seconds():.0f}")


if __name__ == "__main__":
    main()
```