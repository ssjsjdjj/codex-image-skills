"""Input validation and local Photoshop export for the detail workbench."""

import base64
import json
import math
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageOps

from templates import ROOT, TEMPLATE, TEMPLATE_LABEL, TEMPLATE_SIZE, default_template
from geometry import MAX_COLORS, normalize_view, plan_layout, resolve_crop, resolve_text_layout

TABLE_NAMES = ("03选尺码", "05尺码快选", "试穿报告")
FIELDS = {"名称": 28, "货号": 40, "尺码": 28, "材质": 140}
PRODUCT_ATTRIBUTE_FIELDS = ("版型", "触感", "厚度", "弹性")
IMAGE_TYPES = {".jpg", ".jpeg", ".png"}
EXTRA_IMAGE_LABELS = {"hero": "主视觉", "brand": "品牌场景", "measurement": "量体示意图"}
SCENE_FRAMES = ((768, 1081), (601, 788), (768, 1010), (768, 1010))
LEGACY_VIEW_WARNING = "已忽略旧手动取景，按图框自动居中填满"
ENGINE_FILES = ("mixed_detail_fonts.jsx", "native_detail_template.jsx", "adaptive_detail_tables.jsx",
                "editable_long_psd.jsx", "classic_workbench.jsx", "template_manifest.jsx",
                "manifest_workbench.jsx", "workbench.jsx")


def read_data(path):
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("info"), dict):
        raise ValueError("商品资料应包含 info、colors、size_table 和 quick_size。")
    return data


def cell_text(cell):
    if cell is None:
        return ""
    if type(cell) not in (str, int, float) or (isinstance(cell, float) and not math.isfinite(cell)):
        raise ValueError("单元格只接受文字、有限数值和空值。")
    value = str(cell).strip()
    if any(ord(char) < 32 for char in value):
        raise ValueError("单元格内容请保持单行。")
    return value


def normalize_size_note(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("尺码备注请填写文字。")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if len(value) > 300 or any(ord(char) < 32 and char != "\n" for char in value):
        raise ValueError("尺码备注请使用普通文字和换行，最多 300 字。")
    return value if value.strip() else ""


def normalize_product_attributes(values):
    if values is None:
        return {}
    if not isinstance(values, dict):
        raise ValueError("STEP1 属性需要按项目填写。")
    result = {}
    for field in PRODUCT_ATTRIBUTE_FIELDS:
        value = values.get(field)
        if value is None or isinstance(value, str) and not value.strip():
            continue
        if not isinstance(value, str) or any(ord(char) < 32 for char in value):
            raise ValueError(f"{field}请填写单行文字。")
        value = value.strip()
        if field == "版型" and value not in ("宽松", "修身", "紧身"):
            raise ValueError("版型请选择宽松、修身或紧身。")
        if len(value) > 4:
            raise ValueError(f"{field}最多填写 4 个字。")
        result[field] = value
    return result


def resolve_product_attributes(profile, values):
    attributes = (profile or {}).get("product_attributes")
    if not attributes:
        return {}
    return {"版型": attributes["fit"]["default_value"],
            **{name: binding["text"] for name, binding in attributes["fields"].items()},
            **values}


def normalize_table(headers, rows):
    if not isinstance(headers, list) or len(headers) < 2 or not isinstance(rows, list) or not rows:
        raise ValueError("需要至少两列及一行有效数据。")
    headers = [cell_text(cell) for cell in headers]
    if not all(headers):
        raise ValueError("表头存在空列。")
    matrix = [headers]
    for index, row in enumerate(rows, 1):
        if not isinstance(row, list) or len(row) != len(headers):
            raise ValueError(f"第 {index} 行列数与表头不一致。")
        row = [cell_text(cell) for cell in row]
        if not row[0] or not any(row[1:]):
            raise ValueError(f"第 {index} 行缺少行标题或有效数据。")
        matrix.append(row)
    return matrix


def quick_table(quick):
    if not isinstance(quick, dict):
        raise ValueError("需要包含身高、体重区间与推荐数据的对象。")
    columns, labels, rows = (quick[key] for key in ("columns", "rows", "data"))
    if not all(isinstance(value, list) for value in (columns, labels, rows)) or len(labels) != len(rows):
        raise ValueError("身高区间与推荐行数不一致。")
    if not all(isinstance(row, list) for row in rows):
        raise ValueError("快选数据需要二维数组。")
    return normalize_table([quick.get("axis_label", "身高/体重"), *columns],
                           [[label, *row] for label, row in zip(labels, rows)])


def fit_table(trial):
    if not isinstance(trial, dict):
        raise ValueError("需要包含 headers 与 rows 的对象。")
    matrix = normalize_table(trial["headers"], trial["rows"])
    if matrix[0] != ["姓名", "性别", "身高", "体重", "试穿尺码", "胸围/腰围/臀围"]:
        return matrix
    rows = []
    for label, gender, height, weight, result, measurements in matrix[1:]:
        parts = measurements.split("/") if measurements else ["", "", ""]
        if len(parts) != 3:
            raise ValueError("胸围/腰围/臀围应为三个以 / 分隔的值。")
        match = re.fullmatch(r"(\d+)(?:码)?\s*(.*)", result)
        size, feedback = match.groups() if match else (result, "")
        rows.append([f"{label}（{gender}）" if gender else label, height, weight, *parts, size, feedback])
    return [["用户试穿", "身高", "体重", "胸围", "腰围", "臀围", "试穿码数", "试穿反馈"], *rows]


def image_entry(value, label, product=False):
    path = Path(value).resolve(strict=True)
    if path.suffix.lower() not in IMAGE_TYPES or not path.is_file():
        raise ValueError("请选择 PNG 或 JPG 图片。")
    with Image.open(path) as image:
        if image.format not in {"JPEG", "PNG"} or getattr(image, "n_frames", 1) != 1:
            raise ValueError("仅支持静态 PNG 和 JPEG。")
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        if product and (image.format != "PNG" or not has_alpha):
            raise ValueError("商品图需要带透明通道的 PNG。")
        width, height = image.size
        if min(width, height) < 32 or width * height > 50_000_000:
            raise ValueError("图片单边至少 32 px，像素总数最多 5000 万。")
        if image.getexif().get(274, 1) in {5, 6, 7, 8}:
            width, height = height, width
        oriented = ImageOps.exif_transpose(image)
        visible = (0, 0, width, height)
        if has_alpha:
            alpha = oriented.convert("RGBA").getchannel("A")
            low, high = alpha.getextrema()
            if product and (high == 0 or low == 255):
                raise ValueError("商品图需要同时包含可见商品和透明背景。")
            if high == 0:
                raise ValueError("图片完全透明，请选择有可见内容的图片。")
            if product:
                visible = alpha.getbbox()
    with Image.open(path) as image:
        image.verify()
    stats = path.stat()
    return {"label": label, "source": str(path), "width": width, "height": height,
            "visible_bounds": list(visible or (0, 0, width, height)), "is_product": bool(product),
            "stamp": [stats.st_size, stats.st_mtime_ns]}


def psb_size(path):
    with Path(path).open("rb") as stream:
        header = stream.read(26)
    if len(header) != 26 or header[:6] != b"8BPS\0\2":
        raise ValueError("不是有效的 Photoshop PSB 文件。")
    return int.from_bytes(header[18:22], "big"), int.from_bytes(header[14:18], "big")


def resolve_hidden_decorations(profile, requested, warnings):
    """Only an explicitly parsed optional decoration may be hidden."""
    if not isinstance(requested, list):
        warnings.append("隐藏装饰记录格式无效，已使用默认装饰。")
        return []
    allowed = {item.get("id") for item in (profile or {}).get("decorations", [])
               if isinstance(item, dict) and isinstance(item.get("id"), str)}
    selected, unmatched = [], 0
    for item in requested:
        if not isinstance(item, str) or item not in allowed:
            unmatched += 1
        elif item not in selected:
            selected.append(item)
    if unmatched:
        warnings.append(f"{unmatched} 条隐藏装饰记录未匹配当前母版，已忽略；其他图层保持不变。")
    return selected


def preflight(data, products, scenes, template=None, *, views=None, extra_images=None):
    errors, warnings = [], []
    if views:
        warnings.append(LEGACY_VIEW_WARNING)
    job = {"info": {}, "tables": {}, "products": [], "scenes": []}
    try:
        job["template"] = (template or default_template()).snapshot()
    except (OSError, ValueError) as error:
        errors.append(f"工作台母版不可用 · {error}")
    selected = job.get("template", {})
    profile = selected.get("profile")
    required_fields = {"名称", "货号"} | (set(profile.get("fields", {})) if profile else set(FIELDS))
    for field, limit in FIELDS.items():
        try:
            value = cell_text(data.get("info", {}).get(field))
            if (field in required_fields and not value) or len(value) > limit:
                raise ValueError(f"需要填写，最多 {limit} 个字符。")
            job["info"][field] = value
        except (AttributeError, ValueError) as error:
            errors.append(f"{field} · {error}")
    code = job["info"].get("货号", "")
    if code and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", code):
        errors.append("货号只支持字母、数字、下划线和短横线。")

    readers = (
        lambda: normalize_table(data["size_table"]["headers"], data["size_table"]["rows"]),
        lambda: quick_table(data["quick_size"]),
        lambda: fit_table(data["try_on"]),
    )
    available_tables = None
    if profile:
        modules = profile.get("modules", [])
        modules = modules.values() if isinstance(modules, dict) else modules
        available_tables = {module["table"]["key"] for module in modules if module.get("table")}
    for title, reader in zip(TABLE_NAMES, readers):
        if available_tables is not None and title not in available_tables:
            payload = data.get({"03选尺码": "size_table", "05尺码快选": "quick_size", "试穿报告": "try_on"}[title])
            if isinstance(payload, dict) and any(payload.get(key) for key in ("headers", "columns", "rows", "data")):
                warnings.append(f"当前母版没有{title}模块，本次不输出该表，数据保留在资料包中。")
            continue
        trial = data.get("try_on")
        if title == "试穿报告" and (trial is None or (isinstance(trial, dict) and trial.get("rows") == [])):
            warnings.append("未提供试穿数据，将收起母版中的试穿报告模块。")
            continue
        try:
            job["tables"][title] = reader()
        except (KeyError, TypeError, ValueError) as error:
            errors.append(f"{title} · {error}")

    colors = data.get("colors")
    if not isinstance(colors, list) or not 1 <= len(colors) <= MAX_COLORS or any(
        not isinstance(color, str) or not color.strip() or len(color.strip()) > 8 or
        any(ord(char) < 32 for char in color) for color in colors
    ):
        errors.append(f"颜色需要 1–{MAX_COLORS} 个，每个 1–8 字。")
    elif len({color.strip() for color in colors}) != len(colors):
        errors.append("颜色名重复。")
    else:
        for color in (color.strip() for color in colors):
            validate_image(job["products"], errors, products.get(color), color, product=True)
    if not scenes:
        warnings.append("未绑定模特图，首个颜色商品图将作为主视觉，成品省略模特展示。")
    elif len(scenes) > 4 or any(not source for source in scenes):
        errors.append("模特图按 1–4 顺序连续填写。")
    else:
        available_scenes = len([key for key in profile.get("view_slots", {}) if key.startswith("scene_")]) if profile else 4
        if len(scenes) > available_scenes:
            warnings.append(f"当前母版有 {available_scenes} 个模特图位，本次使用前 {available_scenes} 张图片。")
        for index, source in enumerate(scenes[:available_scenes], 1):
            validate_image(job["scenes"], errors, source, f"模特图 {index}")
    extras = extra_images if isinstance(extra_images, dict) else {}
    if profile:
        warnings.extend(f"母版说明 · {note}" for note in profile.get("import_warnings", [])
                        if isinstance(note, str))
    job["product_attributes"] = {}
    try:
        attributes = normalize_product_attributes(data.get("product_attributes"))
        job["product_attributes"] = resolve_product_attributes(profile, attributes)
        if attributes and profile and not job["product_attributes"]:
            warnings.append("当前母版没有可编辑的 STEP1 属性组件，已填写的属性保留在商品资料中。")
        inherited = [field for field in job["product_attributes"] if field not in attributes]
        if inherited:
            warnings.append(f"STEP1 的{'、'.join(inherited)}沿用母版示例，请核对该款商品的实际属性。")
    except ValueError as error:
        errors.append(str(error))
    job["size_note"] = None
    try:
        note = normalize_size_note(data.get("size_note"))
        if note is not None:
            if (profile or {}).get("size_note"):
                job["size_note"] = note
            else:
                warnings.append("当前母版未识别到尺码备注图位，备注保留在资料包中。")
    except ValueError as error:
        errors.append(str(error))
    hidden_map = data.get("hidden_decorations", {})
    if isinstance(hidden_map, dict):
        requested = hidden_map.get(selected.get("id"), [])
    else:
        warnings.append("隐藏装饰记录格式无效，已使用默认装饰。")
        requested = []
    job["hidden_decorations"] = resolve_hidden_decorations(profile, requested, warnings)
    if not scenes and profile:
        warnings = [note for note in warnings if not note.startswith("未绑定模特图，")]
        if "hero" not in profile.get("view_slots", {}):
            warnings.append("未启用模特展示；当前母版沿用商品信息与选颜色版式。")
        elif extras.get("hero"):
            warnings.append("未启用模特展示，主视觉使用单独选择的图片。")
        else:
            warnings.append("未启用模特展示，主视觉使用第一色商品图完整展示。")
    # Model slots never implicitly change an independently chosen hero.
    job["hero"] = job["products"][0] if job["products"] else None
    job["brand"] = job["scenes"][0] if job["scenes"] else None
    job["measurement"] = None
    for key, label in EXTRA_IMAGE_LABELS.items():
        if extras.get(key):
            if (profile or key == "measurement") and key not in (profile or {}).get("view_slots", {}):
                warnings.append(f"当前母版没有{label}独立图位，本次不使用该图片；切回对应母版可继续使用。")
                continue
            try:
                job[key] = image_entry(extras[key], label)
            except (OSError, ValueError, Image.DecompressionBombError) as error:
                errors.append(f"{label} · {error}")
    if not extras.get("measurement") and (profile or {}).get("view_slots", {}).get("measurement"):
        assets = data.get("assets")
        if isinstance(assets, dict) and assets.get("measurement"):
            warnings.append("资料包指定的量体示意图未找到，当前沿用母版示意图。")
        else:
            warnings.append("未绑定商品量体示意图，当前沿用母版示意图。")
    if profile:
        job["profile"] = profile
        if job["products"]:
            try:
                job["geometry"] = plan_layout(profile, len(job["products"]), job["tables"], len(job["scenes"]),
                                               has_hero=bool(job["hero"]), has_brand=bool(job["brand"]),
                                               size_note=job["size_note"])
                job["views"] = resolve_job_views(job, views or {}, warnings)
                job["text_layout"] = resolve_text_layout(profile, job["geometry"], job["info"],
                                                        [item["label"] for item in job["products"]])
            except (KeyError, TypeError, ValueError) as error:
                errors.append(f"版式与取景 · {error}")
    source_warnings = data.get("warnings", [])
    if isinstance(source_warnings, list):
        warnings.extend(f"资料备注 · {warning}" for warning in source_warnings if isinstance(warning, str))
    return job, errors, warnings


def resolve_job_views(job, states, warnings):
    """Build automatic frame crops; legacy manual view settings are ignored."""
    if states and LEGACY_VIEW_WARNING not in warnings:
        warnings.append(LEGACY_VIEW_WARNING)
    result = {}
    for key, slot in job["geometry"]["view_slots"].items():
        if key == "measurement":
            continue
        if key.startswith("scene_"):
            index = int(key.split("_")[-1]) - 1
            item = job["scenes"][index] if index < len(job["scenes"]) else None
        else:
            item = job.get(key)
        if not item or item.get("is_product") or not slot.get("visible", True):
            continue
        frame = slot["rect"]
        state = normalize_view()
        crop = resolve_crop(item["width"], item["height"], frame[2], frame[3], state)
        if min(crop[2] - crop[0], crop[3] - crop[1]) < 200 or frame[2] / (crop[2] - crop[0]) > 1.5:
            warnings.append(f"{key} · 原图或当前取景分辨率偏低，放大可能变软；请使用高清原图交付。")
        result[key] = {"source": item["source"], "source_size": [item["width"], item["height"]],
                       "source_box": crop, "crop_box": crop, "frame": frame, "state": state}
    return result


def validate_image(target, errors, value, label, product=False):
    if not value:
        errors.append(f"{label} · 缺少图片。")
        return
    try:
        target.append(image_entry(value, label, product))
    except (OSError, ValueError, Image.DecompressionBombError) as error:
        errors.append(f"{label} · {error}")


def scene_rgb(image):
    """Normalize a staged scene while retaining any original transparency."""
    if "A" in image.getbands() or "transparency" in image.info:
        return image.convert("RGBA")
    return image.convert("RGB")


class PhotoshopUnavailableError(RuntimeError):
    pass


class PhotoshopTimeoutError(RuntimeError):
    pass


def run_photoshop(script, *, progid="Photoshop.Application", timeout=None, progress_path=None, notify=None):
    command = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
function Get-NonRespondingPhotoshopId {
    try {
        $registry = 'Registry::HKEY_CLASSES_ROOT'
        $registration = Get-Item -LiteralPath "$registry\$($env:DETAIL_WORKBENCH_PHOTOSHOP_ID)\CLSID" -ErrorAction SilentlyContinue
        if (!$registration) { return }
        $classId = $registration.GetValue('')
        $server = Get-Item -LiteralPath "$registry\CLSID\$classId\LocalServer32" -ErrorAction SilentlyContinue
        if (!$server) { return }
        $serverCommand = [string]$server.GetValue('')
        if ($serverCommand -notmatch '^\s*(?:"(?<exe>[^"]+\.exe)"|(?<exe>.+?\.exe))(?=\s|$)') { return }
        $executable = [Environment]::ExpandEnvironmentVariables($Matches['exe'])
        $processName = [IO.Path]::GetFileNameWithoutExtension($executable)
        foreach ($instance in Get-Process -Name $processName -ErrorAction SilentlyContinue) {
            try {
                if ($instance.Path -eq $executable -and $instance.MainWindowHandle -ne 0 -and !$instance.Responding) {
                    return $instance.Id
                }
            } catch {}
        }
    } catch {}
}
try {
    $busyProcess = Get-NonRespondingPhotoshopId
    $recoveryDeadline = [DateTime]::UtcNow.AddSeconds(10)
    while ($busyProcess -and [DateTime]::UtcNow -lt $recoveryDeadline) {
        Start-Sleep -Milliseconds 500
        $busyProcess = Get-NonRespondingPhotoshopId
    }
    if ($busyProcess) {
        [Console]::Error.WriteLine("Photoshop 窗口无响应（进程 $busyProcess）。恢复 Photoshop 后再重试。")
        exit 2
    }
    try { $photoshop = [Runtime.InteropServices.Marshal]::GetActiveObject($env:DETAIL_WORKBENCH_PHOTOSHOP_ID) }
    catch {
        try { $photoshop = New-Object -ComObject $env:DETAIL_WORKBENCH_PHOTOSHOP_ID }
        catch {
            [Console]::Error.WriteLine("无法连接桌面版 Photoshop。请确认 Photoshop 已安装并可打开。 " + $_.Exception.Message)
            exit 2
        }
    }
    $taskDeadline = [DateTime]::UtcNow.AddSeconds(30)
    while ($true) {
        try {
            $photoshop.DoJavaScriptFile($env:DETAIL_WORKBENCH_JSX)
            break
        } catch {
            $taskError = $_.Exception
            $taskRetryable = $false
            while ($null -ne $taskError) {
                if ($taskError.HResult -in @(-2147417846, -2147418111)) { $taskRetryable = $true }
                $taskError = $taskError.InnerException
            }
            # These RPC errors mean Photoshop refused the call before running
            # it. Do not retry script failures after execution has begun.
            if (-not $taskRetryable) { throw }
            if ([DateTime]::UtcNow -ge $taskDeadline) {
                throw 'Photoshop 当前正忙或有待处理弹窗。请处理后再次生成。'
            }
            Start-Sleep -Milliseconds 500
        }
    }
} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }
"""
    encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded]
    options = dict(env={**os.environ, "DETAIL_WORKBENCH_JSX": str(script), "DETAIL_WORKBENCH_PHOTOSHOP_ID": progid},
                   encoding="utf-8", errors="replace", creationflags=subprocess.CREATE_NO_WINDOW)
    if timeout is None:
        result = subprocess.run(args, capture_output=True, **options)
        stdout, stderr, returncode = result.stdout, result.stderr, result.returncode
    else:
        progress_path = Path(progress_path) if progress_path else None
        last_stage = "等待 Photoshop 响应"
        started = last_progress = time.monotonic()
        with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options) as worker:
            while True:
                try:
                    stdout, stderr = worker.communicate(timeout=.5)
                    returncode = worker.returncode
                    break
                except subprocess.TimeoutExpired:
                    pass
                now = time.monotonic()
                if progress_path:
                    try:
                        stage = progress_path.read_text(encoding="utf-8-sig").strip()
                    except (OSError, UnicodeError):
                        stage = ""
                    if stage and stage != last_stage:
                        last_stage = stage
                        last_progress = now
                        if notify:
                            notify(f"母版解析 · {stage}")
                if now - last_progress >= timeout or now - started >= 600:
                    if progress_path:
                        try:
                            progress_path.with_suffix(".cancel").touch()
                        except OSError:
                            pass
                    # This is the PowerShell caller only. Photoshop can still
                    # be inside a native action with the private copy open.
                    worker.kill()
                    worker.communicate()
                    raise PhotoshopTimeoutError(
                        f"母版解析等待超时 · {last_stage}。工作台已结束等待。"
                        "Photoshop 恢复响应后再重试上传。")
    if returncode:
        message = stderr.strip() or stdout.strip()
        if returncode == 2:
            raise PhotoshopUnavailableError(message)
        raise RuntimeError(f"Photoshop 未完成本次处理。\n{message}")


def stage_image(item, folder, filename, transparent):
    source = Path(item["source"])
    destination = folder / (filename + ".png")
    stat = source.stat()
    if [stat.st_size, stat.st_mtime_ns] != item["stamp"]:
        raise ValueError(f"确认后素材已变更，请重新预检 · {source.name}")
    with Image.open(source) as original:
        oriented = ImageOps.exif_transpose(original)
        image = oriented.convert("RGBA") if transparent else scene_rgb(oriented)
        if transparent:
            alpha = image.getchannel("A")
            low, high = alpha.getextrema()
            if high == 0 or low == 255:
                raise ValueError(f"商品图需要可见商品和透明背景 · {source.name}")
        profile = original.info.get("icc_profile") if original.mode in {"RGB", "RGBA", "P"} else None
        options = {"icc_profile": profile} if profile else {}
        image.save(destination, compress_level=2, **options)
    stat = source.stat()
    if [stat.st_size, stat.st_mtime_ns] != item["stamp"]:
        raise ValueError(f"读取中素材已变更，请重新预检 · {source.name}")
    return {**item, "staged": str(destination)}


def export_detail(job, output_root, source_data="", notify=lambda message: None):
    # A job kept by an older window must not bypass automatic composition.
    job = {**job, "views": resolve_job_views(job, {}, []) if job.get("geometry") else {}}
    job["hidden_decorations"] = resolve_hidden_decorations(job.get("profile"), job.get("hidden_decorations", []), [])
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    code = job["info"]["货号"]
    selected = job.get("template") or default_template().snapshot()
    source = Path(selected["path"])
    stats = source.stat()
    if [stats.st_size, stats.st_mtime_ns] != selected["stamp"]:
        raise ValueError("确认后母版已变更，请重新运行预检。")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    final = output_root / f"{code}-{stamp}"
    with TemporaryDirectory(prefix=".套版暂存-", dir=output_root) as temporary:
        folder = Path(temporary)
        delivery = folder / "delivery"
        delivery.mkdir()
        notify("正在准备完整分辨率素材…")
        products = [stage_image(item, folder, f"product-{i}", True) for i, item in enumerate(job["products"], 1)]
        scenes = [stage_image(item, folder, f"scene-{i}", False) for i, item in enumerate(job["scenes"], 1)]
        staged = {(item["source"], bool(item.get("is_product"))): item for item in [*products, *scenes]}
        extras = {}
        for key in EXTRA_IMAGE_LABELS:
            item = job.get(key)
            if item:
                image_key = (item["source"], bool(item.get("is_product")))
                if image_key not in staged:
                    staged[image_key] = stage_image(item, folder, key, image_key[1])
                extras[key] = {**staged[image_key], "is_product": image_key[1]}
            else:
                extras[key] = None
        # A unique template path avoids Photoshop reusing a document from another window.
        template = Path(shutil.copyfile(source, folder / "base.psb"))
        stats = source.stat()
        if [stats.st_size, stats.st_mtime_ns] != selected["stamp"]:
            raise ValueError("读取过程中母版已变更，请重新运行预检。")
        psb = delivery / f"{code}_可编辑详情长图.psb"
        preview = delivery / f"{code}_详情预览.jpg"
        completed = folder / "photoshop-complete.txt"
        layout_verification = folder / "size-layout-verification.json"
        payload = {**job, "products": products, "scenes": scenes, **extras, "template": str(template),
                   "output": str(psb), "preview": str(preview), "completed": str(completed),
                   "layout_verification": str(layout_verification)}
        scripts = [(ROOT / "engine" / name).read_text(encoding="utf-8-sig") for name in ENGINE_FILES]
        args = json.dumps(payload, ensure_ascii=True, allow_nan=False)
        script = folder / "build.jsx"
        script.write_text("\n\n".join(scripts) + f"\nrunDetailWorkbench({args});\n", encoding="utf-8-sig")
        notify("Photoshop 正在套版、保存 PSB 并重开核验…")
        try:
            run_photoshop(script)
        except RuntimeError:
            if not completed.is_file():
                raise
        if not completed.is_file():
            raise ValueError("Photoshop 未完成重开核验。")
        dimensions = psb_size(psb)
        if dimensions != (TEMPLATE_SIZE[0], int(completed.read_text(encoding="ascii"))) or not preview.is_file():
            raise ValueError("成品尺寸或预览文件校验失败。")
        with Image.open(preview) as image:
            if image.width != 500 or abs(image.height - round(dimensions[1] * 500 / dimensions[0])) > 1:
                raise ValueError("JPG 预览的长宽比与 PSB 不一致。")
            thumbnail = image.copy()
            thumbnail.thumbnail((90, 1300))
            minimum, maximum = thumbnail.convert("L").getextrema()
            if maximum - minimum < 20:
                raise ValueError("JPG 预览疑似空白，请检查 Photoshop 合成结果。")
            if preview.stat().st_size > 5_000_000:
                compact = folder / "preview-compact.jpg"
                profile = image.info.get("icc_profile")
                image.convert("RGB").save(compact, quality=94, optimize=True, icc_profile=profile)
        if preview.stat().st_size > 5_000_000:
            compact.replace(preview)
        main = job.get("hero") or job["products"][0]
        record = {"母版": selected["label"], "母版来源": selected["source"], "画布": dimensions, "商品资料来源": source_data,
                  "主视觉来源": main["source"], **job,
                  "重开核验": "商品字段及表格为原生文字，商品图和模特图为独立嵌入式智能对象"}
        if layout_verification.is_file():
            record["尺码区域核验"] = json.loads(layout_verification.read_text(encoding="utf-8-sig"))
        (delivery / "素材与套版记录.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        delivery.rename(final)
    return final, final / psb.name, final / preview.name
