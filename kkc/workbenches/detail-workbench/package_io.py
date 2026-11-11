"""Portable product packages, relative assets and per-template crop sessions."""

import copy
import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from PIL import Image
from workbench import EXTRA_IMAGE_LABELS, read_data

MAX_PACKAGE_BYTES = 3 * 1024 ** 3
MAX_FILES = 2000


class PackageError(ValueError):
    pass


class PackageSelectionRequired(PackageError):
    def __init__(self, candidates):
        self.candidates = candidates
        super().__init__("资料包中找到多个 product_data.json，请选择需要导入的一款。")


@dataclass
class ProductPackage:
    data: dict
    json_path: Path
    root: Path
    origin: Path
    products: dict
    scenes: list
    extra_images: dict
    views: dict
    selected_template: str | None
    missing: list


def source_stamp(path):
    value = Path(path).stat()
    return [value.st_size, value.st_mtime_ns]


def source_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bounded_files(folder, max_depth=5):
    count = 0
    for current, directories, names in os.walk(folder, followlinks=False):
        current = Path(current)
        depth = len(current.relative_to(folder).parts)
        directories[:] = [name for name in directories if depth < max_depth - 1 and not (current / name).is_symlink()]
        count += len(names)
        if count > MAX_FILES:
            raise PackageError("此目录包含的文件较多，请选择当前商品的资料子文件夹。")
        for name in names:
            yield current / name


def _find_json(folder):
    direct = folder / "product_data.json"
    if direct.is_file():
        return direct
    candidates = [path for path in _bounded_files(folder)
                  if path.name.casefold() == "product_data.json" and "__MACOSX" not in path.parts]
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        raise PackageSelectionRequired(candidates)
    raise PackageError("所选资料包中没有 product_data.json，请选择包含该文件的资料目录。")


def _extract_zip(path, cache_root):
    cache_root.mkdir(parents=True, exist_ok=True)
    destination = Path(tempfile.mkdtemp(prefix="资料包-", dir=cache_root))
    try:
        with zipfile.ZipFile(path) as archive:
            records = archive.infolist()
            if len(records) > MAX_FILES or sum(item.file_size for item in records) > MAX_PACKAGE_BYTES:
                raise PackageError("资料包超出支持范围，请保留当前款的 JSON 和所需原始素材后再导入。")
            seen = set()
            for item in records:
                relative = PurePosixPath(item.filename.replace("\\", "/"))
                if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} or ":" in part for part in relative.parts):
                    raise PackageError("ZIP 中存在不安全的文件路径，请重新打包该款资料。")
                if stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1:
                    raise PackageError("请使用包含普通文件、未加密的 ZIP 资料包。")
                for part in relative.parts:
                    stem = part.split(".")[0].upper()
                    if part.rstrip(" .") != part or stem in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
                        raise PackageError("ZIP 内含 Windows 无法直接使用的文件名，请更名后打包。")
                key = str(relative).casefold()
                if key in seen:
                    raise PackageError("ZIP 中含有同名冲突文件，请整理后重新打包。")
                seen.add(key)
                target = destination.joinpath(*relative.parts)
                if item.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as source, target.open("xb") as output:
                        shutil.copyfileobj(source, output)
        return destination
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as error:
        if destination.resolve().is_relative_to(cache_root.resolve()):
            shutil.rmtree(destination)
        if isinstance(error, PackageError):
            raise
        raise PackageError("无法解开资料包，请确认 ZIP 文件完整且可读取。") from None


def load_package(path, *, cache_root, asset_root=None):
    origin = Path(path).expanduser().resolve()
    try:
        if origin.is_dir():
            json_path = _find_json(origin)
        elif origin.suffix.lower() == ".zip":
            json_path = _find_json(_extract_zip(origin, Path(cache_root).resolve()))
        elif origin.suffix.lower() == ".json" and origin.is_file():
            json_path = origin
        else:
            raise PackageError("请选择商品资料文件夹、ZIP 资料包或 product_data.json。")
        data = read_data(json_path)
    except (OSError, ValueError) as error:
        if isinstance(error, PackageError):
            raise
        raise PackageError(f"商品资料无法读取 · {error}") from None
    root = json_path.parent
    remap_root = Path(asset_root).expanduser().resolve() if asset_root else None
    missing = []
    notes = [note for note in data.get("warnings", []) if isinstance(note, str)] if isinstance(data.get("warnings"), list) else []

    def resolve(value, label, *, required=True):
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            notes.append(f"{label}的素材路径格式有误，请重新选择文件。")
            return None
        try:
            source = Path(value).expanduser()
            selected = (remap_root or root) / source
            if selected.is_file():
                return selected.resolve()
            if remap_root and source.name:
                candidates = [candidate for candidate in _bounded_files(remap_root)
                              if candidate.name.casefold() == source.name.casefold() and candidate.is_file()]
                if len(candidates) == 1:
                    return candidates[0].resolve()
                if len(candidates) > 1:
                    notes.append(f"{label}找到多个同名素材，请在图片匹配中确认。")
            if required:
                missing.append({"label": label, "relative": value, "expected": str(selected.resolve())})
        except (OSError, ValueError) as error:
            if isinstance(error, PackageError):
                notes.append(str(error))
            if required:
                missing.append({"label": label, "relative": value, "expected": value})
        return None

    colors = data.get("colors", [])
    colors = [color.strip() for color in colors if isinstance(color, str) and color.strip()] if isinstance(colors, list) else []
    products = {}
    for color in colors:
        if Path(color).name == color and (root / "透明图" / f"{color}.png").is_file():
            products[color] = (root / "透明图" / f"{color}.png").resolve()
    scenes = [next(((root / "模特图" / f"{index}{suffix}").resolve() for suffix in (".jpg", ".jpeg", ".png")
                   if (root / "模特图" / f"{index}{suffix}").is_file()), None) for index in range(1, 5)]
    extra = dict.fromkeys(EXTRA_IMAGE_LABELS)
    assets = data.get("assets") or {}
    if not isinstance(assets, dict):
        raise PackageError("assets 需要包含 products、scenes 等素材路径字段。")
    mapping = assets.get("products", {})
    if not isinstance(mapping, dict):
        raise PackageError("assets.products 需要按色名填写图片路径。")
    for color, value in mapping.items():
        if color in colors:
            products[color] = resolve(value, f"商品图 · {color}")
        else:
            notes.append(f"素材映射中的颜色「{color}」未出现在商品颜色中，请核对。")
    if "scenes" in assets:
        values = assets["scenes"]
        if not isinstance(values, list) or len(values) > 4:
            raise PackageError("assets.scenes 需要按顺序填写最多四张图片路径。")
        scenes = [resolve(value, f"模特图 {index}") for index, value in enumerate(values, 1)]
    for kind, label in EXTRA_IMAGE_LABELS.items():
        if kind in assets:
            extra[kind] = resolve(assets[kind], label)
    views = {}
    raw_views = data.get("views", {})
    if isinstance(raw_views, dict):
        for template_id, slots in raw_views.items():
            if not isinstance(template_id, str) or not isinstance(slots, dict):
                continue
            views[template_id] = {}
            for slot, state in slots.items():
                if not isinstance(slot, str) or not isinstance(state, dict):
                    continue
                source = resolve(state.get("source"), f"取景 · {slot}", required=False)
                if source is None:
                    continue
                saved_hash = state.get("source_sha256")
                stamp = source_stamp(source)
                if saved_hash and source_hash(source) != saved_hash or not saved_hash and state.get("source_stamp") != stamp:
                    notes.append(f"{slot} 的源图已变更，已恢复默认取景。")
                    continue
                views[template_id][slot] = {**state, "source": str(source), "source_stamp": stamp}
    data = {**data, "warnings": notes}
    return ProductPackage(data, json_path, root, origin, products, scenes, extra, views,
                          data.get("selected_template"), missing)


def save_package(destination, data, products, scenes, *, views=None, extra_images=None,
                 selected_template=None, source_root=None):
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise PackageError("保存位置已存在，请使用新的资料包名称。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".资料包保存-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        content = staging / "content"
        content.mkdir()
        copied = {}
        original_root = Path(source_root).resolve() if source_root else None

        def copy_image(value, label):
            if not value:
                return None
            source = Path(value).resolve()
            if not source.is_file():
                raise PackageError(f"无法保存缺失的素材 · {label} · {source}")
            if source.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                raise PackageError(f"{label}需要使用 PNG 或 JPG 图片。")
            try:
                with Image.open(source) as image:
                    if image.format not in {"PNG", "JPEG"}:
                        raise ValueError
                    image.verify()
            except (OSError, ValueError, Image.DecompressionBombError):
                raise PackageError(f"图片无法读取，未保存该素材 · {label} · {source}") from None
            key = str(source).casefold()
            if key not in copied:
                relative = source.relative_to(original_root) if original_root and source.is_relative_to(original_root) else None
                if relative and relative.parts[0] in {"素材", "原始附件"}:
                    target = content / relative
                else:
                    target = content / "素材" / source.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    target = target.with_name(f"{source.stem}-{uuid.uuid4().hex[:8]}{source.suffix}")
                before = source_stamp(source)
                # A portable working copy must remain writable.  In particular,
                # inheriting a Windows source's read-only bit makes ZIP staging
                # cleanup fail even after the archive has been saved.
                shutil.copyfile(source, target)
                if source_stamp(source) != before:
                    raise PackageError(f"保存过程中素材已修改，请重新保存 · {source.name}")
                copied[key] = (target.relative_to(content).as_posix(), source_hash(target))
            return copied[key][0]

        result = copy.deepcopy(data)
        previous_assets = result.get("assets") if isinstance(result.get("assets"), dict) else {}
        previous_products = previous_assets.get("products") if isinstance(previous_assets.get("products"), dict) else {}
        previous_scenes = previous_assets.get("scenes") if isinstance(previous_assets.get("scenes"), list) else []
        result["assets"] = {"products": {color: copy_image(source, color) if source else previous_products.get(color)
                                           for color, source in products.items()},
                            "scenes": [copy_image(source, f"模特图 {index + 1}") if source else
                                       previous_scenes[index] if index < len(previous_scenes) else None
                                       for index, source in enumerate(scenes)]}
        while result["assets"]["scenes"] and result["assets"]["scenes"][-1] is None:
            result["assets"]["scenes"].pop()
        for kind, label in EXTRA_IMAGE_LABELS.items():
            value = (extra_images or {}).get(kind)
            if value:
                result["assets"][kind] = copy_image(value, label)
            elif previous_assets.get(kind):
                result["assets"][kind] = previous_assets[kind]
        result["views"] = {}
        for template_id, slots in (views or {}).items():
            result["views"][template_id] = {}
            for slot, state in slots.items():
                if not isinstance(state, dict) or not state.get("source"):
                    continue
                path = Path(state["source"])
                if not path.is_file() or source_stamp(path) != state.get("source_stamp"):
                    continue
                relative = copy_image(state["source"], f"取景 · {slot}")
                fingerprint = copied[str(Path(state["source"]).resolve()).casefold()][1]
                result["views"][template_id][slot] = {**state, "source": relative, "source_sha256": fingerprint}
        if selected_template:
            result["selected_template"] = selected_template
        if source_root:
            original = original_root
            for name in ("source_record.json", "导入说明.txt"):
                if (original / name).is_file():
                    shutil.copyfile(original / name, content / name)
            attachments = original / "原始附件"
            if attachments.is_dir():
                files = [path for path in attachments.rglob("*") if path.is_file() and not path.is_symlink()]
                if len(files) > MAX_FILES or sum(path.stat().st_size for path in files) > MAX_PACKAGE_BYTES:
                    raise PackageError("原始附件过多，请先整理当前款所需的资料。")
                for source in files:
                    target = content / "原始附件" / source.relative_to(attachments)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        shutil.copyfile(source, target)
        (content / "product_data.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        if destination.suffix.lower() == ".zip":
            pending = staging / "package.zip"
            with zipfile.ZipFile(pending, "x", compression=zipfile.ZIP_STORED) as archive:
                for source in content.rglob("*"):
                    if source.is_file():
                        archive.write(source, source.relative_to(content).as_posix())
            if destination.exists():
                raise PackageError("保存位置已被使用，请另选资料包名称。")
            os.rename(pending, destination)
        else:
            os.rename(content, destination)
    return destination
