"""Import and keep local copies of compatible Photoshop detail-page templates."""

import json
import math
import shutil
import struct
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from uuid import uuid4

from PIL import Image

ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / "templates"
TEMPLATE_SIZE = (790, 13395)
TEMPLATE_LABEL = "小山行风感洞洞裤 · 工作台母版 V1"
TEMPLATE = ROOT / "template.psb"
SOURCE_SIZE = (790, 40000)
DEFAULT_SOURCE = ROOT.parent / "详情页母版" / "小山行风感洞洞裤-终.psb"
ASSET_KEYS = {"mask", "foreground", "clean_preview", "original_preview", "working_preview", "image", "original"}
COMPACT_VERSION = 1
COMPACT_ROLES = {"header", "hero", "product", "colors", "size_table", "quick_size", "try_on",
                 "measurement_method", "scenes"}


class TemplateUpgradeRequired(ValueError):
    pass


class UnsupportedTemplateError(ValueError):
    pass


def _needs_product_attributes(profile):
    return ("product_attributes" not in profile and profile.get("family") == "classic"
            and any(path[-1:] == ["组 1024"] for path in profile.get("omitted_paths", [])))


def _resolve_profile_assets(value, folder):
    if isinstance(value, dict):
        return {key: str((folder / item).resolve()) if key in ASSET_KEYS and isinstance(item, str)
                else _resolve_profile_assets(item, folder) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_profile_assets(item, folder) for item in value]
    return value


def validate_compact_profile(profile):
    """A full original must not silently become the preview or export template."""
    if profile.get("compact_version") != COMPACT_VERSION:
        raise TemplateUpgradeRequired("该母版需要更新为仅保留必要页面的精简工作母版。")
    roles = {module.get("role") for module in profile.get("modules", [])}
    if not {"product", "colors"} <= roles or not roles <= COMPACT_ROLES:
        raise ValueError("精简母版的保留模块记录无效，请重新整理母版。")


@dataclass(frozen=True)
class Template:
    id: str
    label: str
    path: Path
    source: str
    dimensions: tuple[int, int] = TEMPLATE_SIZE
    preview: Path | None = None
    footer_preview: Path | None = None
    layout: str = "workbench"
    source_dimensions: tuple[int, int] | None = None
    original_preview: Path | None = None
    profile_path: Path | None = None

    def profile(self):
        path = self.profile_path or self.path.parent / "profile.json"
        if not path.is_file():
            raise TemplateUpgradeRequired(f"母版「{self.label}」需要提取真实图层布局，请先升级母版。")
        profile = json.loads(path.read_text(encoding="utf-8"))
        if profile.get("version") != 1 or not profile.get("modules") or profile.get("canvas") != {
            "width": self.dimensions[0], "height": self.dimensions[1]
        }:
            raise TemplateUpgradeRequired(f"母版「{self.label}」的布局记录需要重新提取。")
        if _needs_product_attributes(profile):
            raise TemplateUpgradeRequired(f"母版「{self.label}」需要重新提取 STEP1 属性组件。")
        validate_compact_profile(profile)
        return _resolve_profile_assets(profile, path.parent)

    def working_preview_info(self):
        """Describe only the compact, editable working master used for generation."""
        info = {"version": 1, "scope": "compact", "status": "unavailable", "preview": None,
                "working_dimensions": list(self.dimensions), "preview_dimensions": None,
                "message": "精简母版预览尚未准备完成，请重新整理该母版。"}
        try:
            profile = self.profile()
            path = Path(profile["working_preview"])
            if path.name == Path(profile.get("original_preview") or "original.jpg").name:
                raise ValueError("精简母版预览不能使用完整原稿参考图。")
            if path.parent.resolve() != self.path.parent.resolve():
                raise ValueError("精简母版预览不在当前母版资源目录中。")
            with Image.open(path) as image:
                dimensions = list(image.size)
                if image.width < 1 or abs(image.height - round(image.width * self.dimensions[1] / self.dimensions[0])) > 1:
                    raise ValueError("精简母版预览尺寸与工作母版不一致。")
            info.update(status="ready", preview=str(path.resolve()), preview_dimensions=dimensions,
                        kept_roles=[item["role"] for item in profile["modules"]],
                        message="精简母版版式 · 仅显示必要页面，示例图片用于参考")
        except (OSError, ValueError, KeyError, TypeError) as error:
            info["message"] = f"精简母版预览不可用：{error}"
        return info

    def original_preview_info(self):
        """Describe the full source reference, separately from the working layout."""
        path = reference_metadata_path(self)
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            if info.get("version") != 1 or info.get("status") not in {"ready", "unavailable", "archived"}:
                raise ValueError("原稿参考记录无效。")
        except (OSError, ValueError, TypeError):
            return {"version": 1, "status": "legacy", "source": self.source,
                    "source_dimensions": list(self.source_dimensions or self.dimensions),
                    "working_dimensions": list(self.dimensions), "preview_dimensions": None, "preview": None,
                    "message": "母版原稿参考尚未核对，请从原稿重新提取完整参考图。"}
        info = dict(info)
        info["working_dimensions"] = list(self.dimensions)
        if info["status"] == "ready":
            try:
                with Image.open(self.original_preview) as image:
                    if list(image.size) != info.get("preview_dimensions"):
                        raise ValueError("完整参考图尺寸与记录不符。")
                info["preview"] = str(self.original_preview.resolve())
            except (OSError, TypeError, ValueError) as error:
                info.update(status="unavailable", preview=None, message=f"母版原稿参考图不可读：{error}")
        else:
            info["preview"] = None
        return info

    def snapshot(self):
        if template_header(self.path) != (2, *self.dimensions):
            raise ValueError("工作台母版尺寸或格式不符，请重新选择母版。")
        stats = self.path.stat()
        return {"id": self.id, "label": self.label, "path": str(self.path), "source": self.source,
                "dimensions": list(self.dimensions), "layout": self.layout,
                "source_dimensions": list(self.source_dimensions or self.dimensions),
                "original_reference": self.original_preview_info(),
                "working_reference": self.working_preview_info(),
                "profile": self.profile(),
                "stamp": [stats.st_size, stats.st_mtime_ns]}


def default_template():
    source, source_dimensions = str(DEFAULT_SOURCE), SOURCE_SIZE
    dimensions = TEMPLATE_SIZE
    try:
        metadata = json.loads((ROOT / "template-reference.json").read_text(encoding="utf-8"))
        source = metadata.get("source") or source
        source_dimensions = tuple(metadata.get("source_dimensions") or source_dimensions)
    except (OSError, ValueError, TypeError):
        pass
    try:
        profile = json.loads((ROOT / "template-profile.json").read_text(encoding="utf-8"))
        if profile.get("compact_version") == COMPACT_VERSION:
            dimensions = (profile["canvas"]["width"], profile["canvas"]["height"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return Template("builtin", TEMPLATE_LABEL, TEMPLATE, source, dimensions=dimensions, source_dimensions=source_dimensions,
                    preview=ROOT / "template-header.jpg", footer_preview=ROOT / "template-footer.jpg",
                    original_preview=ROOT / "template-original.jpg", profile_path=ROOT / "template-profile.json")


def template_header(path):
    with Path(path).open("rb") as file:
        header = file.read(26)
    if len(header) != 26 or header[:6] not in {b"8BPS\0\1", b"8BPS\0\2"}:
        raise ValueError("请选择 Photoshop PSD 或 PSB 源文件。")
    height, width, depth, mode = struct.unpack(">IIHH", header[14:26])
    if depth != 8 or mode != 3:
        raise ValueError("母版需要使用 RGB、8 位/通道。")
    return header[5], width, height


def saved_template(folder, metadata):
    label, source = metadata["label"], metadata["source"]
    if not isinstance(label, str) or not label.strip() or not isinstance(source, str):
        raise ValueError("母版来源记录无效。")
    dimensions = tuple(metadata.get("dimensions", TEMPLATE_SIZE))
    source_dimensions = tuple(metadata.get("source_dimensions", dimensions))
    layout = metadata.get("layout", "workbench")
    if len(dimensions) != 2 or any(type(value) is not int or value < 1 for value in dimensions) or layout not in {"workbench", "classic"}:
        raise ValueError("母版版式记录无效。")
    return Template(folder.name, label, folder / "base.psb", source, dimensions,
                    preview=folder / "header.jpg" if (folder / "header.jpg").is_file() else None,
                    footer_preview=folder / "footer.jpg" if (folder / "footer.jpg").is_file() else None, layout=layout,
                    source_dimensions=source_dimensions, original_preview=folder / "original.jpg",
                    profile_path=folder / "profile.json")


def list_templates():
    templates = []
    for metadata_path in LIBRARY.glob("*/template.json"):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            item = saved_template(metadata_path.parent, metadata)
            if item.path.is_file():
                templates.append(item)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    templates.sort(key=lambda item: (item.label.casefold(), item.id))
    if TEMPLATE.is_file():
        templates.insert(0, default_template())
    return templates


def remove_template(template):
    if template.id == "builtin":
        raise ValueError("内置母版无法删除。")
    library = LIBRARY.resolve()
    folder = library / template.id
    if (folder.parent != library or folder != folder.resolve()
            or template.path.resolve() != folder / "base.psb"
            or not (folder / "template.json").is_file() or not template.path.is_file()):
        raise ValueError("该母版已移除，或无法核对它在工作台中的位置。")
    archive = library / ".removed"
    if archive.resolve() != archive:
        raise ValueError("无法核对母版回收目录。")
    archive.mkdir(exist_ok=True)
    destination = archive / (template.id + "-" + uuid4().hex[:8])
    folder.rename(destination)
    return destination


def clean_copy(source, destination):
    """Preserve the document bytes while dropping unusually large XMP history."""
    file_size = source.stat().st_size
    with source.open("rb") as original, destination.open("xb") as copy:
        header = original.read(30)
        (mode_length,) = struct.unpack(">I", header[-4:])
        if len(header) != 30 or mode_length > 64 * 1024 * 1024 or 34 + mode_length > file_size:
            raise ValueError("母版的 Photoshop 颜色数据无效。")
        copy.write(header + original.read(mode_length))
        (resources_length,) = struct.unpack(">I", original.read(4))
        resource_size_offset = copy.tell()
        copy.write(b"\0" * 4)
        resource_end = original.tell() + resources_length
        if resource_end + 4 > file_size:
            raise ValueError("母版图像资源块损坏。")
        while original.tell() < resource_end:
            start = original.tell()
            signature, resource_id = struct.unpack(">4sH", original.read(6))
            if signature != b"8BIM":
                raise ValueError("母版包含不支持的图像资源块。请在 Photoshop 中另存后重试。")
            name_length = original.read(1)[0]
            original.seek(name_length + (name_length + 1) % 2, 1)
            (length,) = struct.unpack(">I", original.read(4))
            end = original.tell() + length + length % 2
            if end > resource_end:
                raise ValueError("母版图像资源块损坏。")
            if resource_id == 1060 and length > 8_000_000:
                original.seek(end)
            else:
                original.seek(start)
                while original.tell() < end:
                    chunk = original.read(min(end - original.tell(), 2 * 1024 * 1024))
                    if not chunk:
                        raise ValueError("母版图像资源块不完整。")
                    copy.write(chunk)
        size = copy.tell() - resource_size_offset - 4
        copy.seek(resource_size_offset)
        copy.write(struct.pack(">I", size))
        copy.seek(0, 2)
        shutil.copyfileobj(original, copy, length=2 * 1024 * 1024)


def run_template_action(folder, script_files, call, spec, *, bounded=False, notify=None):
    from workbench import PhotoshopTimeoutError, run_photoshop

    marker = folder / f"{call}.done"
    request = {**spec, "done": str(marker)}
    progress = folder / f"{call}.progress"
    for stale in (marker, progress, progress.with_suffix(".cancel")):
        stale.unlink(missing_ok=True)
    if bounded:
        request.update(progress=str(progress), cancel=str(progress.with_suffix(".cancel")))
    payload = json.dumps(request, ensure_ascii=True)
    engine = "\n\n".join((ROOT / "engine" / name).read_text(encoding="utf-8-sig") for name in script_files)
    script = folder / f"{call}.jsx"
    script.write_text(
        engine + f"\nvar request = {payload};\n{call}(request);\n"
        'var done = new File(request.done); if (!done.open("w")) throw new Error("无法写入母版验证记录");\n'
        'done.write("OK"); done.close();\n', encoding="utf-8-sig",
    )
    try:
        if bounded:
            run_photoshop(script, timeout=180, progress_path=progress, notify=notify)
        else:
            run_photoshop(script)
    except PhotoshopTimeoutError:
        raise
    except RuntimeError as error:
        if not marker.is_file():
            diagnostic = request.get("diagnosticsOutput")
            if diagnostic and Path(diagnostic).is_file():
                try:
                    details = json.loads(Path(diagnostic).read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    details = {}
                if not isinstance(details, dict):
                    details = {}
                if details.get("status") == "unsupported":
                    reports = LIBRARY / ".diagnostics" / uuid4().hex
                    reports.mkdir(parents=True)
                    report_path = reports / "structure.json"
                    _write_json_atomic(report_path, details)
                    original = request.get("originalPreview")
                    if original and Path(original).is_file():
                        shutil.copy2(original, reports / "original.jpg")
                    reason = details.get("message") or "当前母版版式尚未匹配，需要核对字段、表格和图片图位。"
                    label = request.get("sourceLabel") or "所选母版"
                    raise UnsupportedTemplateError(f"{label}\n{reason}\n结构报告已保存到 {report_path}") from error
            raise
    if not marker.is_file() or marker.read_text(encoding="ascii") != "OK":
        raise ValueError("Photoshop 未完成母版校验。")


MANIFEST_SCRIPTS = ("mixed_detail_fonts.jsx", "editable_long_psd.jsx", "classic_workbench.jsx", "workbench.jsx",
                    "template_reference.jsx", "prepare_template.jsx", "template_manifest.jsx",
                    "compact_template.jsx", "section_template.jsx", "template_classifier.jsx")


@contextmanager
def template_import_scratch():
    from workbench import PhotoshopTimeoutError

    library = LIBRARY.resolve()
    scratch = Path(mkdtemp(prefix=".import-", dir=library)).resolve()
    if scratch.parent != library:
        raise RuntimeError("母版临时目录不在模板库中")
    keep = False
    try:
        yield scratch
    except PhotoshopTimeoutError:
        # Photoshop may still be in a native step when its caller times out.
        keep = True
        raise
    finally:
        if not keep:
            shutil.rmtree(scratch)


def prepare_profile_assets(folder, spec):
    folder = Path(folder)
    spec.update(profileOutput=str(folder / "profile.json"), originalPreview=str(folder / "original.jpg"),
                workingPreview=str(folder / "working.jpg"),
                cleanPreview=str(folder / "clean.jpg"), assetsFolder=str(folder))
    return spec


def finish_profile_assets(folder):
    folder = Path(folder)
    path = folder / "profile.json"
    profile = json.loads(path.read_text(encoding="utf-8"))
    def relative_assets(value):
        if isinstance(value, dict):
            return {key: Path(item).name if key in ASSET_KEYS
                    and isinstance(item, str) else relative_assets(item) for key, item in value.items()}
        if isinstance(value, list):
            return [relative_assets(item) for item in value]
        return value
    profile = relative_assets(profile)
    validate_profile_masks(profile, folder)
    finalize_profile_foregrounds(profile, folder)
    validate_profile_decorations(profile, folder)
    validate_profile_measurement(profile, folder)
    for image_path in folder.glob("*.jpg"):
        with Image.open(image_path) as image:
            staged = image_path.with_suffix(".compact.jpg")
            image.convert("RGB").save(staged, quality=94, optimize=True, icc_profile=image.info.get("icc_profile"))
        staged.replace(image_path)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def validate_profile_masks(profile, folder):
    """Reject an empty silhouette before an imported template can be published."""
    result = {}
    for key, slot in profile.get("view_slots", {}).items():
        if key == "measurement":
            continue
        path = Path(slot["mask"])
        path = path if path.is_absolute() else Path(folder) / path
        with Image.open(path) as original:
            image = original.convert("RGBA")
            alpha = image.getchannel("A")
            if alpha.getextrema()[1] == 0 or alpha.getbbox() is None:
                raise ValueError(f"母版图位 {key} 的轮廓蒙版为空，未发布此母版；请重新提取原生图框蒙版。")
            expected = [math.ceil(value) for value in slot["rect"][2:]]
            if list(image.size) != expected:
                raise ValueError(f"母版图位 {key} 的蒙版尺寸与真实图框不一致。")
            result[key] = {"size": list(image.size), "alpha_range": list(alpha.getextrema()),
                           "alpha_bbox": list(alpha.getbbox()), "center_alpha": alpha.getpixel((image.width // 2, image.height // 2)),
                           "corner_alpha": [alpha.getpixel(point) for point in ((0, 0), (image.width - 1, 0),
                                             (0, image.height - 1), (image.width - 1, image.height - 1))]}
            # Keep a consistent alpha-bearing format, including fully opaque frames.
            if original.mode != "RGBA":
                staged = path.with_name(path.stem + ".validated.png")
                image.save(staged, format="PNG")
            else:
                staged = None
        if staged:
            staged.replace(path)
    return result


def finalize_profile_foregrounds(profile, folder):
    """Keep native transparent overlays; never publish an opaque gray cover."""
    report = {}
    for key, slot in profile.get("view_slots", {}).items():
        if not slot.get("foreground"):
            continue
        path = Path(slot["foreground"])
        path = path if path.is_absolute() else Path(folder) / path
        with Image.open(path) as original:
            image = original.convert("RGBA")
            expected = [math.ceil(value) for value in slot["rect"][2:]]
            if list(image.size) != expected:
                raise ValueError(f"母版图位 {key} 的固定前景尺寸与真实图框不一致。")
            alpha = image.getchannel("A")
            minimum, maximum = alpha.getextrema()
            if maximum == 0:
                slot.pop("foreground", None)
                slot.pop("foreground_layers", None)
                report[key] = {"status": "empty"}
                continue
            if minimum == 255:
                paths = [" / ".join(parts) for parts in slot.get("foreground_layers", [])]
                raise ValueError(f"母版图位 {key} 的上层内容导出为整框不透明图，未发布以免遮住照片。"
                                 f"请核对固定前景分层：{'；'.join(paths) or '上层固定图层'}")
            report[key] = {"status": "ready", "size": list(image.size), "alpha_range": [minimum, maximum],
                           "alpha_bbox": list(alpha.getbbox()), "layers": slot.get("foreground_layers", [])}
            staged = path.with_name(path.stem + ".rgba.png") if original.mode != "RGBA" else None
            if staged:
                image.save(staged, format="PNG")
        if staged:
            staged.replace(path)
    return report


def validate_profile_decorations(profile, folder):
    """A removable native decoration needs its own usable transparent overlay."""
    result = {}
    for decoration in profile.get("decorations", []):
        path = Path(decoration["image"])
        path = path if path.is_absolute() else Path(folder) / path
        with Image.open(path) as image:
            expected = tuple(math.ceil(value) for value in decoration["rect"][2:])
            alpha = image.convert("RGBA").getchannel("A")
            low, high = alpha.getextrema()
            if image.size != expected or high == 0 or low == 255:
                raise ValueError(f"绿线装饰独立预览缺少正确的透明图层：{' / '.join(decoration['path'])}")
            result[decoration["id"]] = {"size": list(image.size), "alpha_range": [low, high],
                                        "alpha_bbox": list(alpha.getbbox())}
    return result


def validate_profile_measurement(profile, folder):
    slot = profile.get("view_slots", {}).get("measurement")
    if slot is None:
        return None
    path = Path(slot["original"])
    path = path if path.is_absolute() else Path(folder) / path
    with Image.open(path) as image:
        expected = tuple(math.ceil(value) for value in slot["rect"][2:])
        if image.size != expected or image.convert("RGBA").getchannel("A").getbbox() is None:
            raise ValueError("母版尺码测量示意图未能提取有效预览。")
        return {"size": list(image.size), "path": slot["path"]}


def repair_template_preview_assets(template):
    """Refresh clean art and independently replaceable image/decoration previews."""
    profile = template.profile()
    prefix = "template-" if template.id == "builtin" else ""
    with TemporaryDirectory(prefix=".preview-repair-", dir=ROOT) as temporary:
        scratch = Path(temporary)
        assets = scratch / "assets"
        assets.mkdir()
        source = scratch / "source.psb"
        clean_copy(template.path, source)
        run_template_action(scratch, MANIFEST_SCRIPTS, "repairManifestPreviewAssets",
                            {"source": str(source), "profile": profile, "assetsFolder": str(assets),
                             "profileOutput": str(assets / "profile.json")})
        generated = json.loads((assets / "profile.json").read_text(encoding="utf-8-sig"))
        masks = validate_profile_masks(generated, assets)
        foregrounds = finalize_profile_foregrounds(generated, assets)
        decorations = validate_profile_decorations(generated, assets)
        measurement = validate_profile_measurement(generated, assets)
        for image_path in assets.glob("*.jpg"):
            with Image.open(image_path) as image:
                compact = image_path.with_name(image_path.stem + ".compact.jpg")
                image.convert("RGB").save(compact, quality=94, optimize=True, icc_profile=image.info.get("icc_profile"))
            compact.replace(image_path)
        for asset in assets.iterdir():
            if asset.name == "profile.json":
                continue
            target = template.path.parent / (prefix + asset.name)
            staged = target.with_name(target.name + ".part")
            shutil.copyfile(asset, staged)
            staged.replace(target)
        profile_path = template.profile_path or template.path.parent / "profile.json"
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
        raw["clean_preview"] = prefix + "clean.jpg"
        raw["mask_version"] = 2
        raw["foreground_version"] = 1
        raw["decoration_version"] = generated["decoration_version"]
        raw["decorations"] = [{**entry, "image": prefix + Path(entry["image"]).name}
                              for entry in generated["decorations"]]
        raw["original_images"] = generated["original_images"]
        raw["omitted_paths"] = generated["omitted_paths"]
        if generated.get("size_note"):
            raw["size_note"] = generated["size_note"]
        else:
            raw.pop("size_note", None)
        raw["view_slots"].pop("measurement", None)
        if measurement:
            slot = generated["view_slots"]["measurement"]
            raw["view_slots"]["measurement"] = {**slot, "original": prefix + Path(slot["original"]).name}
        size_module = next((item for item in generated["modules"] if item["role"] == "size_table"), None)
        if size_module:
            raw["modules"] = [size_module if item["role"] == "size_table" else item for item in raw["modules"]]
        for key, slot in raw["view_slots"].items():
            if key == "measurement":
                continue
            slot["mask"] = prefix + "mask-" + key + ".png"
            new = generated["view_slots"][key]
            if new.get("foreground"):
                slot["foreground"] = prefix + Path(new["foreground"]).name
                slot["foreground_layers"] = new.get("foreground_layers", [])
            else:
                slot.pop("foreground", None)
                slot.pop("foreground_layers", None)
        _write_json_atomic(profile_path, raw)
    return {"masks": masks, "foregrounds": foregrounds, "decorations": decorations,
            "measurement": measurement}


def repair_template_masks(template):
    """Re-export exact native frame shapes from a private working-master copy."""
    profile = template.profile()
    with TemporaryDirectory(prefix=".mask-repair-", dir=ROOT) as temporary:
        scratch = Path(temporary)
        assets = scratch / "assets"
        assets.mkdir()
        source = scratch / "source.psb"
        clean_copy(template.path, source)
        run_template_action(scratch, MANIFEST_SCRIPTS, "repairManifestMasks",
                            {"source": str(source), "profile": profile, "assetsFolder": str(assets)})
        validation_profile = {"view_slots": {key: {**slot, "mask": f"mask-{key}.png"}
                                             for key, slot in profile["view_slots"].items() if key != "measurement"}}
        report = validate_profile_masks(validation_profile, assets)
        for key, slot in profile["view_slots"].items():
            if key == "measurement":
                continue
            target = Path(slot["mask"]).resolve()
            if target.parent != template.path.parent.resolve():
                raise ValueError("母版蒙版缓存路径不在当前母版目录内。")
            staged = target.with_name(target.name + ".part")
            shutil.copyfile(assets / f"mask-{key}.png", staged)
            staged.replace(target)
    profile_path = template.profile_path or template.path.parent / "profile.json"
    raw_profile = json.loads(profile_path.read_text(encoding="utf-8"))
    raw_profile["mask_version"] = 2
    _write_json_atomic(profile_path, raw_profile)
    return report


def reference_metadata_path(template):
    name = "template-reference.json" if template.id == "builtin" else "reference.json"
    return template.path.parent / name


def _write_json_atomic(path, value):
    staged = path.with_name(path.name + ".part")
    staged.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    staged.replace(path)


def _reference_capture(template, scratch, output, *, source=None):
    """Open only a private copy; never close or save the user's open document."""
    source = Path(source or template.source).resolve(strict=True)
    version, width, height = template_header(source)
    before = source.stat()
    stamp = [before.st_size, before.st_mtime_ns]
    private_source = scratch / ("original-source.psb" if version == 2 else "original-source.psd")
    clean_copy(source, private_source)
    copied = source.stat()
    if [copied.st_size, copied.st_mtime_ns] != stamp:
        raise ValueError("复制过程中原母版发生变化，请先保存原稿后重试。")
    run_template_action(scratch, ("template_reference.jsx",), "snapshotTemplateReference",
                        {"source": str(private_source), "output": str(output)})
    after = source.stat()
    if [after.st_size, after.st_mtime_ns] != stamp:
        raise ValueError("提取期间原母版发生变化，请先保存原稿后重试。")
    with Image.open(output) as image:
        preview_dimensions = list(image.size)
        compact = output.with_name(output.stem + ".compact.jpg")
        image.convert("RGB").save(compact, quality=94, optimize=True, icc_profile=image.info.get("icc_profile"))
    compact.replace(output)
    return {"version": 1, "status": "ready", "source": str(source), "source_stamp": stamp,
            "source_dimensions": [width, height], "working_dimensions": list(template.dimensions),
            "preview_dimensions": preview_dimensions, "preview": output.name,
            "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "message": "原稿完整参考（含原稿中可见的示例图片）；套版使用独立工作副本。"}


def _unavailable_reference(template, error, *, source=None):
    return {"version": 1, "status": "unavailable", "source": str(source or template.source),
            "source_dimensions": list(template.source_dimensions or template.dimensions),
            "working_dimensions": list(template.dimensions), "preview_dimensions": None, "preview": None,
            "message": f"无法读取母版原稿完整参考，请重新指定可读取的原始 PSD / PSB。{error}"}


def repair_original_preview(template, *, source=None):
    """Repair a source reference in a worker; a missing original is reported, not disguised."""
    target = template.original_preview or template.path.parent / "original.jpg"
    profile_path = template.profile_path or template.path.parent / "profile.json"
    prefix = "template-" if template.id == "builtin" else ""
    working_target = template.path.parent / (prefix + "working.jpg")
    profile = None
    if profile_path.is_file():
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if not profile.get("working_preview") and target.is_file() and not working_target.exists():
            # Older original.jpg was a snapshot of the working copy; retain it as such.
            staged = working_target.with_name(working_target.name + ".part")
            shutil.copyfile(target, staged)
            staged.replace(working_target)
    try:
        with TemporaryDirectory(prefix=".reference-repair-", dir=ROOT) as temporary:
            scratch = Path(temporary)
            output = scratch / "original.jpg"
            info = _reference_capture(template, scratch, output, source=source)
            staged = target.with_name(target.name + ".part")
            shutil.copyfile(output, staged)
            staged.replace(target)
        info["preview"] = target.name
    except (OSError, ValueError, RuntimeError, struct.error, IndexError) as error:
        info = _unavailable_reference(template, error, source=source)
    _write_json_atomic(reference_metadata_path(template), info)
    if profile is not None:
        if working_target.is_file():
            profile["working_preview"] = working_target.name
        profile["original_preview"] = target.name
        dimensions = info.get("source_dimensions")
        if dimensions:
            profile["source_canvas"] = {"width": dimensions[0], "height": dimensions[1]}
        _write_json_atomic(profile_path, profile)
    if source is not None and template.id != "builtin" and info["status"] == "ready":
        metadata_path = template.path.parent / "template.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata.update(source=info["source"], source_dimensions=info["source_dimensions"])
        _write_json_atomic(metadata_path, metadata)
    return template.original_preview_info()


def upgrade_product_attributes(template, profile_path, profile):
    """Add the STEP1 layers to an existing classic profile and reuse its page previews."""
    with TemporaryDirectory(prefix=".step1-upgrade-", dir=ROOT) as temporary:
        scratch = Path(temporary)
        source = scratch / "source.psb"
        output = scratch / "attributes.json"
        clean_copy(template.path, source)
        run_template_action(scratch, MANIFEST_SCRIPTS, "reviewManifestProductAttributes",
                            {"source": str(source), "assetsFolder": str(scratch), "output": str(output)})
        attributes = json.loads(output.read_text(encoding="utf-8-sig"))
        if attributes:
            for option in attributes["fit"]["options"]:
                preview = Path(option["image"])
                with Image.open(preview) as image:
                    if image.size != tuple(attributes["rect"][2:]) or not image.convert("RGBA").getchannel("A").getbbox():
                        raise ValueError("STEP1 属性预览的尺寸或内容有误。")
                target = template.path.parent / preview.name
                staged = target.with_suffix(".png.part")
                shutil.copyfile(preview, staged)
                staged.replace(target)
                option["image"] = target.name
            product = next(item for item in profile["modules"] if item["role"] == "product")
            product["move_paths"].append(attributes["path"])
        profile["product_attributes"] = attributes
        _write_json_atomic(profile_path, profile)
    return template


def _compact_reference(folder, source, source_dimensions, dimensions):
    """Keep source provenance without publishing full-original image caches."""
    profile_path = folder / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    profile.pop("original_preview", None)
    _write_json_atomic(profile_path, profile)
    (folder / "original.jpg").unlink(missing_ok=True)
    _write_json_atomic(folder / "reference.json", {
        "version": 1, "status": "archived", "source": str(source),
        "source_dimensions": list(source_dimensions), "working_dimensions": list(dimensions),
        "preview_dimensions": None, "preview": None,
        "message": "原稿来源记录保留；工作台只显示和使用精简母版。"})


def _copy_missing_profile_assets(profile, folder):
    """Preserve native assets still referenced by the new profile, never old page caches."""
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in ASSET_KEYS and isinstance(item, str) and key != "original_preview":
                    source = Path(item)
                    target = folder / source.name
                    if not target.exists():
                        if not source.is_absolute() or not source.is_file():
                            raise ValueError(f"精简母版缺少引用的资源：{source.name}")
                        shutil.copy2(source, target)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(profile)


def _upgrade_attributes_in_stage(profile, source, scratch, assets):
    if not _needs_product_attributes(profile):
        return
    output = scratch / "attributes.json"
    run_template_action(scratch, MANIFEST_SCRIPTS, "reviewManifestProductAttributes",
                        {"source": str(source), "assetsFolder": str(assets), "output": str(output)})
    attributes = json.loads(output.read_text(encoding="utf-8-sig"))
    profile["product_attributes"] = attributes
    if attributes:
        product = next(item for item in profile["modules"] if item["role"] == "product")
        if attributes["path"] not in product["move_paths"]:
            product["move_paths"].append(attributes["path"])


def _publish_builtin_compact(template, assets, profile):
    """Retain the legacy built-in entry while committing its base/profile last."""
    backup = LIBRARY / ".backups" / ("builtin-" + uuid4().hex)
    backup.mkdir(parents=True)
    def prefix_assets(value):
        if isinstance(value, dict):
            return {key: "template-" + item if key in ASSET_KEYS and isinstance(item, str)
                    else prefix_assets(item) for key, item in value.items()}
        if isinstance(value, list):
            return [prefix_assets(item) for item in value]
        return value
    _write_json_atomic(assets / "profile.json", prefix_assets(profile))
    paths = [p for p in assets.iterdir() if p.is_file() and p.name not in {"base.psb", "profile.json", "template.json"}]
    paths += [assets / "base.psb", assets / "profile.json"]
    published, saved = [], []
    try:
        for asset in paths:
            target = template.path if asset.name == "base.psb" else ROOT / ("template-" + asset.name)
            if target.exists():
                shutil.copy2(target, backup / target.name)
                saved.append(target)
            staged = target.with_name(target.name + ".compact-" + uuid4().hex)
            shutil.copy2(asset, staged)
            staged.replace(target)
            published.append(target)
    except BaseException:
        for target in reversed(published):
            if target in saved:
                shutil.copy2(backup / target.name, target)
            else:
                target.unlink(missing_ok=True)
        raise
    return default_template()


def upgrade_template(template):
    """Publish a compact base and matching assets together under the original ID."""
    destination = template.path.parent.resolve()
    profile_path = template.profile_path or destination / "profile.json"
    try:
        existing = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = {}
    if existing.get("compact_version") == COMPACT_VERSION and not _needs_product_attributes(existing):
        template.profile()
        return template
    LIBRARY.mkdir(exist_ok=True)
    if template.id != "builtin" and (destination.parent != LIBRARY.resolve() or destination.name != template.id):
        raise ValueError("无法核对母版升级目录，原母版未更改。")
    before = template.path.stat()
    stamp = (before.st_size, before.st_mtime_ns)
    with template_import_scratch() as scratch:
        assets = scratch / "publish"
        assets.mkdir()
        source = scratch / "source.psb"
        clean_copy(template.path, source)
        spec = prepare_profile_assets(assets, {"source": str(source), "output": str(assets / "base.psb"),
            "normalizedOutput": str(assets / "base.psb"), "originalPreviewReady": True,
            "headerPreview": str(assets / "header.jpg"), "footerPreview": str(assets / "footer.jpg"),
            "sourceIsWorking": False, "sourceCanvas": list(template.source_dimensions or template.dimensions)})
        if (existing.get("version") == 1 and existing.get("canvas") ==
                {"width": template.dimensions[0], "height": template.dimensions[1]}):
            profile = _resolve_profile_assets(existing, profile_path.parent)
            _upgrade_attributes_in_stage(profile, source, scratch, assets)
            spec["profile"] = profile
            action = "compactWorkbenchTemplate"
        else:
            action = "reviewUploadedTemplate"
        run_template_action(scratch, MANIFEST_SCRIPTS, action, spec, bounded=True)
        profile = json.loads((assets / "profile.json").read_text(encoding="utf-8-sig"))
        _copy_missing_profile_assets(profile, assets)
        profile.pop("original_preview", None)
        _write_json_atomic(assets / "profile.json", profile)
        profile = finish_profile_assets(assets)
        validate_compact_profile(profile)
        dimensions = tuple(template_header(assets / "base.psb")[1:])
        if profile["canvas"] != {"width": dimensions[0], "height": dimensions[1]}:
            raise ValueError("精简母版与版式记录尺寸不一致，未发布升级。")
        _compact_reference(assets, template.source, template.source_dimensions or template.dimensions, dimensions)
        metadata = {"label": template.label, "source": template.source, "dimensions": list(dimensions),
                    "source_dimensions": list(template.source_dimensions or template.dimensions),
                    "layout": template.layout, "compact_version": COMPACT_VERSION}
        _write_json_atomic(assets / "template.json", metadata)
        staged_template = saved_template(assets, metadata)
        staged_template.snapshot()
        if staged_template.working_preview_info()["status"] != "ready":
            raise ValueError("精简母版示例预览未通过核验，未发布升级。")
        after = template.path.stat()
        if (after.st_size, after.st_mtime_ns) != stamp:
            raise ValueError("整理期间母版发生变化，原母版未更改，请重试。")
        if template.id == "builtin":
            return _publish_builtin_compact(template, assets, profile)
        backups = LIBRARY / ".backups"
        backups.mkdir(exist_ok=True)
        if backups.resolve().parent != LIBRARY.resolve():
            raise ValueError("无法核对母版归档目录。")
        backup = backups / (template.id + "-" + uuid4().hex)
        destination.rename(backup)
        try:
            assets.rename(destination)
        except BaseException:
            backup.rename(destination)
            raise
    return saved_template(destination, metadata)


def repair_working_preview(template):
    """Refresh only the compact master reference, without requiring the full original."""
    try:
        profile = template.profile()
    except TemplateUpgradeRequired:
        return upgrade_template(template).working_preview_info()
    target = Path(profile["working_preview"])
    with TemporaryDirectory(prefix=".working-preview-", dir=ROOT) as temporary:
        scratch = Path(temporary)
        output = scratch / "working.jpg"
        _reference_capture(template, scratch, output, source=template.path)
        staged = target.with_name(target.name + ".part")
        shutil.copyfile(output, staged)
        staged.replace(target)
    return template.working_preview_info()


def import_template(path, *, notify=None):
    from workbench import PhotoshopTimeoutError, PhotoshopUnavailableError

    source = Path(path).resolve(strict=True)
    if not source.is_file() or source.suffix.lower() not in {".psb", ".psd"}:
        raise ValueError("请选择 Photoshop PSD 或 PSB 源文件。")
    version, *dimensions = template_header(source)
    if (version == 2) != (source.suffix.lower() == ".psb"):
        raise ValueError("母版扩展名与 Photoshop 文件类型不一致。")
    size = tuple(dimensions)
    if size[0] != 790 or size[1] < 1000:
        raise ValueError(f"{source.name} 的实际尺寸为 {size[0]} × {size[1]} px。"
                         "当前支持 790 px 宽的工作台母版和产品信息／产品信息T母版，需保留对应的可编辑图层。")

    before = source.stat()
    existing = list_templates()
    existing_labels = {item.label for item in existing}
    label = source.stem
    index = 2
    while label in existing_labels:
        label = f"{source.stem}（{index}）"
        index += 1
    metadata = {"label": label, "source": str(source), "source_dimensions": list(size)}
    LIBRARY.mkdir(exist_ok=True)
    destination = LIBRARY / uuid4().hex
    with template_import_scratch() as scratch:
        publish = scratch / "publish"
        publish.mkdir()
        master = publish / "base.psb"
        from psd_reference import extract_merged_preview

        if notify:
            notify("正在读取文件内的完整原稿预览…")
        original_preview_ready = extract_merged_preview(source, publish / "original.jpg")
        try:
            if notify:
                notify("正在复制母版到工作目录…")
            clean_copy(source, master if version == 2 else scratch / "source.psd")
        except (struct.error, IndexError) as error:
            raise ValueError("母版文件不完整，无法读取 Photoshop 图像资源。") from error
        except (PhotoshopTimeoutError, PhotoshopUnavailableError):
            raise
        except RuntimeError as error:
            raise ValueError(f"{source.name} 的实际尺寸为 {size[0]} × {size[1]} px。"
                             "母版导入未完成，以下是具体步骤和原因。\n" + str(error)) from error
        stats = source.stat()
        if (stats.st_size, stats.st_mtime_ns) != (before.st_size, before.st_mtime_ns):
            raise ValueError("读取过程中原母版发生变化。请重新选择已保存的文件。")
        layout_report = scratch / "layout.txt"
        normalized = scratch / "section-normalized.psb"
        try:
            run_template_action(scratch, MANIFEST_SCRIPTS, "reviewUploadedTemplate", prepare_profile_assets(publish, {
                "source": str(master if version == 2 else scratch / "source.psd"),
                "output": "" if version == 2 else str(master), "layoutReport": str(layout_report),
                "normalizedOutput": str(normalized),
                "diagnosticsOutput": str(scratch / "structure.json"),
                "sourceLabel": source.name, "originalSource": str(source),
                "originalPreviewReady": original_preview_ready,
                "headerPreview": str(publish / "header.jpg"), "footerPreview": str(publish / "footer.jpg"),
                "sourceIsWorking": True, "sourceCanvas": list(size),
            }), bounded=True, notify=notify)
        except (PhotoshopTimeoutError, PhotoshopUnavailableError):
            raise
        except RuntimeError as error:
            raise ValueError(f"{source.name} 的实际尺寸为 {size[0]} × {size[1]} px。"
                             "母版导入未完成，以下是具体步骤和原因。\n" + str(error)) from error
        if normalized.is_file():
            if template_header(normalized)[1] != 790:
                raise ValueError("整理后的工作母版宽度无效，未导入此母版。")
            normalized.replace(master)
        metadata["layout"] = layout_report.read_text(encoding="ascii")
        metadata["dimensions"] = list(template_header(master)[1:])
        metadata["compact_version"] = COMPACT_VERSION
        if notify:
            notify("正在校验图位和预览文件…")
        _compact_reference(publish, source, size, metadata["dimensions"])
        profile = finish_profile_assets(publish)
        validate_compact_profile(profile)
        item = saved_template(publish, metadata)
        item.snapshot()
        if item.working_preview_info()["status"] != "ready":
            raise ValueError("Photoshop 未生成精简母版预览。")
        (publish / "template.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        publish.rename(destination)
    return saved_template(destination, metadata)
