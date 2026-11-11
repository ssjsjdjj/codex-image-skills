"""Small local draft snapshots for a parent/child refresh handshake.

This module never starts a process, closes a window, copies an image, or changes
a product package.  The child must finish restoring the returned data and UI
metadata before calling ``mark_refresh_session_ready``.  Until that marker
exists, the parent should keep its current window and draft intact.
"""

import copy
import hashlib
import json
import math
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from workbench import EXTRA_IMAGE_LABELS


SESSIONS_ROOT = Path(__file__).resolve().parent.parent / "work" / "detail-workbench-sessions"
MAX_SESSION_BYTES = 8 * 1024 * 1024
VERSION = 1


class RefreshSessionError(ValueError):
    pass


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set)):
        return [_jsonable(item) for item in value]
    return value


def _absolute(value, base):
    if value is None or value == "":
        return None
    if not isinstance(value, (str, Path)):
        return _jsonable(value)
    path = Path(value).expanduser()
    return str((path if path.is_absolute() else base / path).resolve())


def _stamp(path):
    try:
        value = Path(path).stat()
        return [value.st_size, value.st_mtime_ns]
    except (OSError, TypeError, ValueError):
        return None


def _views(views, base):
    result = {}
    for template_id, slots in (views or {}).items():
        if not isinstance(slots, dict):
            continue
        result[str(template_id)] = {}
        for slot, original in slots.items():
            if not isinstance(original, dict):
                continue
            state = copy.deepcopy(original)
            state["source"] = _absolute(state.get("source"), base)
            # No image is copied. Prefer the current file stamp to a package hash.
            state.pop("source_sha256", None)
            current = _stamp(state.get("source"))
            previous = state.get("source_stamp")
            if current is not None:
                if previous is None or list(previous) == current:
                    state["source_stamp"] = current
                else:
                    # Keep the stale stamp so load_package still rejects an old crop.
                    state["snapshot_source_stamp"] = current
            result[str(template_id)][str(slot)] = _jsonable(state)
    return result


def _value(value, fallback=None):
    getter = getattr(value, "get", None)
    return getter() if callable(getter) else value if value is not None else fallback


def _ui_metadata(workbench, base):
    preview = getattr(workbench, "preview", None)
    tabs = getattr(workbench, "tabs", None)
    try:
        tab = tabs.index(tabs.select())
    except (AttributeError, TypeError, ValueError):
        tab = 0
    try:
        scroll = float(preview.canvas.yview()[0])
        scroll = min(1., max(0., scroll)) if math.isfinite(scroll) else 0.
    except (AttributeError, TypeError, ValueError, IndexError):
        scroll = 0.
    selector = getattr(workbench, "selected_slot", None)
    selected = selector() if callable(selector) else getattr(preview, "selected_slot", None)
    package = getattr(workbench, "package", None)
    template = getattr(workbench, "template", None)
    result = getattr(workbench, "result", None)
    return {
        "source": getattr(workbench, "source", ""),
        "source_json": _absolute(getattr(workbench, "source_json", None), base),
        "package_root": _absolute(getattr(workbench, "package_root", None), base),
        "origin": _absolute(getattr(package, "origin", None), base),
        "unsaved": bool(getattr(workbench, "unsaved", False)),
        "output": _absolute(_value(getattr(workbench, "output", None)), base),
        "tab": tab, "preview_mode": getattr(preview, "mode", "live"),
        "preview_scroll": scroll, "selected_slot": _jsonable(selected),
        "selected_template": getattr(template, "id", None),
        "result": [_absolute(item, base) for item in result] if isinstance(result, (list, tuple)) else None,
        "final_stale": bool(getattr(preview, "final_stale", False)),
        "attachments": _jsonable(getattr(workbench, "attachments", [])),
        "binding_notice": getattr(workbench, "binding_notice", ""),
        "rename_origins": _jsonable(getattr(workbench, "rename_origins", {})),
    }


def _encode(value):
    try:
        encoded = json.dumps(_jsonable(value), ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RefreshSessionError(f"当前草稿无法写入刷新快照：{error}") from error
    if len(encoded) > MAX_SESSION_BYTES:
        raise RefreshSessionError("刷新快照超出轻量会话范围，旧窗口与草稿已保留。")
    return encoded


def _atomic_write(path, encoded):
    staged = path.with_name(path.name + ".part")
    with staged.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    staged.replace(path)


def _session_path(path):
    root = SESSIONS_ROOT.resolve()
    candidate = Path(path).expanduser().resolve()
    if candidate.name != "session.json" or candidate.parent.parent != root or not candidate.is_relative_to(root):
        raise RefreshSessionError("刷新会话路径必须位于工作台 sessions 目录内。")
    if not candidate.parent.name.startswith("session-"):
        raise RefreshSessionError("刷新会话目录名称无效。")
    return candidate


def _read_json(path):
    try:
        if path.stat().st_size > MAX_SESSION_BYTES:
            raise RefreshSessionError("刷新会话文件过大。")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RefreshSessionError(f"刷新会话无法读取，旧草稿应保留：{error}") from error
    if not isinstance(value, dict):
        raise RefreshSessionError("刷新会话结构无效，旧草稿应保留。")
    return value


def save_refresh_session(workbench):
    """Commit pending edits, write a private lightweight snapshot, return session.json."""
    finish = getattr(workbench, "finish_cell", None)
    if callable(finish):
        finish(True)
    flush = getattr(workbench, "flush_pending_sync", None)
    if callable(flush):
        flush()
    root = SESSIONS_ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)
    folder = root / ("session-" + uuid4().hex)
    folder.mkdir()
    source_json = getattr(workbench, "source_json", None)
    base = Path(getattr(workbench, "package_root", None) or (Path(source_json).parent if source_json else Path.cwd())).resolve()
    metadata = _ui_metadata(workbench, base)
    product_path = None
    product_hash = None
    if getattr(workbench, "source", ""):
        data = copy.deepcopy(workbench.current_data())
        if not isinstance(data, dict) or not isinstance(data.get("info"), dict):
            raise RefreshSessionError("当前草稿缺少商品资料结构，旧窗口与草稿已保留。")
        previous = data.get("assets") if isinstance(data.get("assets"), dict) else {}
        previous_products = previous.get("products") if isinstance(previous.get("products"), dict) else {}
        previous_scenes = previous.get("scenes") if isinstance(previous.get("scenes"), list) else []
        products = dict(getattr(workbench, "products", {}))
        scenes = list(getattr(workbench, "scenes", []))
        extra = dict(getattr(workbench, "extra_images", {}))
        colors = data.get("colors", []) if isinstance(data.get("colors"), list) else []
        data["assets"] = {
            "products": {color: _absolute(products.get(color) or previous_products.get(color), base)
                         for color in colors if isinstance(color, str)},
            "scenes": [_absolute(value or (previous_scenes[index] if index < len(previous_scenes) else None), base)
                       for index, value in enumerate(scenes)],
            **{key: _absolute(extra.get(key) or previous.get(key), base) for key in EXTRA_IMAGE_LABELS},
        }
        data["views"] = _views(getattr(workbench, "views", {}), base)
        data["selected_template"] = metadata["selected_template"]
        # Keep inactive/missing bindings too; they may belong to an incomplete draft.
        metadata["bindings"] = {"products": {key: _absolute(value, base) for key, value in products.items()},
                                "scenes": [_absolute(value, base) for value in scenes],
                                "extra_images": {key: _absolute(value, base) for key, value in extra.items()}}
        metadata["views"] = copy.deepcopy(data["views"])
        encoded = _encode(data)
        product_path = folder / "product_data.json"
        _atomic_write(product_path, encoded)
        product_hash = hashlib.sha256(encoded).hexdigest()
    session = {"version": VERSION, "id": folder.name, "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
               "product_data": product_path.name if product_path else None, "product_sha256": product_hash,
               "metadata": metadata}
    path = folder / "session.json"
    _atomic_write(path, _encode(session))
    return path


def read_refresh_session(path):
    """Return (product_data.json Path or None, metadata); never apply or erase a draft."""
    path = _session_path(path)
    session = _read_json(path)
    if session.get("version") != VERSION or session.get("id") != path.parent.name or not isinstance(session.get("metadata"), dict):
        raise RefreshSessionError("刷新会话版本或身份无效，旧草稿应保留。")
    product = session.get("product_data")
    product_path = None
    if product is not None:
        if product != "product_data.json":
            raise RefreshSessionError("刷新会话中的商品路径无效。")
        product_path = (path.parent / product).resolve()
        if product_path.parent != path.parent:
            raise RefreshSessionError("刷新会话中的商品路径越界。")
        data = _read_json(product_path)
        digest = hashlib.sha256(product_path.read_bytes()).hexdigest()
        if digest != session.get("product_sha256") or not isinstance(data.get("info"), dict):
            raise RefreshSessionError("刷新商品快照不完整，旧草稿应保留。")
    return product_path, copy.deepcopy(session["metadata"])


def session_ready_path(path):
    """The parent may close only after this unique session's ready marker exists."""
    return _session_path(path).with_suffix(".ready")


def mark_refresh_session_ready(path):
    """Call in the child only AFTER data and UI restoration both succeed."""
    path = _session_path(path)
    read_refresh_session(path)
    marker = session_ready_path(path)
    _atomic_write(marker, _encode({"version": VERSION, "session_id": path.parent.name, "pid": os.getpid(),
                                  "restored_at": datetime.now().astimezone().isoformat(timespec="seconds")}))
    return marker
