"""A scrollable, responsive preview of the current detail-page draft."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import copy
import math
from pathlib import Path
import time
import tkinter as tk
from tkinter import font as tkfont, ttk

from PIL import Image, ImageChops, ImageDraw, ImageOps, ImageTk, UnidentifiedImageError

from geometry import fit_text_layout, font_face, plan_layout, resolve_crop, text_descent, text_width

from workbench import SCENE_FRAMES, TABLE_NAMES, normalize_product_attributes, resolve_product_attributes, scene_rgb


FONT = "Microsoft YaHei UI"
INK = "#20332c"
MUTED = "#536b60"
GREEN = "#17664e"
PALE = "#e6f0e9"
BACKGROUND = "#e9efeb"
HERO_RATIO = 734 / 1850
TABLE_LABELS = ("S3  选尺码", "S4  尺码快选", "S5  试穿报告")
LOAD_TIMEOUT = 45


class PreviewImageError(Exception):
    """A readable loading error that can be retried by the user."""


def image_error(error):
    if isinstance(error, PreviewImageError):
        return str(error)
    if isinstance(error, FileNotFoundError):
        return "图片文件不存在，请重新选择文件。"
    if isinstance(error, PermissionError):
        return "无法读取图片，文件可能被占用或没有读取权限。"
    if isinstance(error, Image.DecompressionBombError):
        return "图片像素过大，无法生成预览。"
    if isinstance(error, UnidentifiedImageError):
        return "无法识别图片格式，文件可能已损坏。"
    if isinstance(error, MemoryError):
        return "读取图片时内存不足，请关闭大文件后重试。"
    detail = str(error).strip() or type(error).__name__
    return f"图片读取失败：{detail}"


def load_thumbnail(source, full):
    """Decode outside Tk's event loop and keep only preview-sized pixels."""
    try:
        with Image.open(source) as original:
            limit = (620, 16000) if full else (760, 1100)
            source_size = original.size
            if original.getexif().get(274, 1) in (5, 6, 7, 8):
                source_size = source_size[::-1]
            if original.format == "JPEG":
                original.draft("RGB", limit)
            image = ImageOps.exif_transpose(original)
            if "A" in image.getbands():
                visible_bounds = image.getchannel("A").getbbox()
            elif "transparency" in image.info:
                visible_bounds = image.convert("RGBA").getchannel("A").getbbox()
            else:
                visible_bounds = (0, 0, *source_size)
            if visible_bounds and ("A" in image.getbands() or "transparency" in image.info):
                visible_bounds = tuple(value * source_size[index % 2] / image.size[index % 2]
                                       for index, value in enumerate(visible_bounds))
            image.thumbnail(limit, Image.Resampling.LANCZOS)
            thumbnail = image.convert("RGBA")
            thumbnail.info["source_size"] = source_size
            thumbnail.info["visible_bounds"] = visible_bounds
            return thumbnail
    except Exception as error:
        raise PreviewImageError(image_error(error)) from error


class PreviewPane(ttk.Frame):
    """Editable proof on the right, with a separately identified final JPG."""

    def __init__(self, parent, on_slot_select=None, on_add_image=None,
                 on_repair_original=None, on_decoration_change=None):
        super().__init__(parent, padding=(12, 10))
        self.on_slot_select = on_slot_select
        self.on_add_image = on_add_image
        self.on_repair_original = on_repair_original
        self.on_decoration_change = on_decoration_change
        self.editing_enabled = True
        self.busy = False
        self.state_data = None
        self.mode = "live"
        self.final = None
        self.final_stale = False
        self.sections = {}
        self.slot_boxes = {}
        self.selected_slot = None
        self.content_height = 1
        self.paint_id = self.poll_id = None
        self.pending = {}
        self.pending_started = {}
        self.asset_stamps = {}
        self.asset_errors = {}
        self.invalid_masks = set()
        self.foreground_errors = {}
        self.decoration_errors = {}
        self.decoration_hits = []
        self.assets = OrderedDict()
        self.rasters = OrderedDict()
        self.final_raster = None
        self.original_raster = None
        self.original = None
        self.original_info = {}
        self.visible_images = []
        self.fonts = {}
        self.loader = ThreadPoolExecutor(max_workers=2, thread_name_prefix="detail-preview")

        style = ttk.Style(self)
        style.configure("PreviewButton.TButton", padding=(7, 4), font=(FONT, 9))
        style.configure("PreviewActive.TButton", padding=(7, 4), font=(FONT, 9), background="#dceee1", foreground=GREEN)
        heading = ttk.Frame(self)
        heading.pack(fill="x")
        ttk.Label(heading, text="页面预览", style="H2.TLabel").pack(side="left")
        self.final_button = ttk.Button(heading, text="成品", width=5, command=self.show_final, style="PreviewButton.TButton")
        self.final_button.pack(side="right")
        self.final_button.state(["disabled"])
        self.live_button = ttk.Button(heading, text="预览", width=5, command=self.show_live, style="PreviewActive.TButton")
        self.live_button.pack(side="right", padx=(0, 4))
        self.original_button = ttk.Button(heading, text="母版版式", width=8, command=self.show_original, style="PreviewButton.TButton")
        self.original_button.pack(side="right", padx=(0, 4))
        self.original_button.state(["disabled"])
        self.caption = ttk.Label(self, text="预览 · 修改后自动同步", style="Muted.TLabel", wraplength=300)
        self.caption.pack(anchor="w", pady=(4, 8))
        self.notice = ttk.Label(self, text="", foreground="#9b5428", wraplength=300)
        self.add_scene_button = ttk.Button(self, text="模特图 0/4 · 添加图片", command=self.add_next_scene,
                                          style="PreviewButton.TButton")
        self.add_scene_button.pack(fill="x", pady=(0, 7))
        self.add_scene_button.state(["disabled"])

        viewport = ttk.Frame(self)
        viewport.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(viewport, width=295, height=380, bg=BACKGROUND, highlightthickness=0,
                                yscrollincrement=20, takefocus=True)
        scrollbar = ttk.Scrollbar(viewport, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _event: self.schedule())
        self.canvas.bind("<MouseWheel>", self.scroll)
        self.canvas.bind("<ButtonPress-1>", self.pointer_down)
        self.canvas.bind("<Motion>", self.pointer_hover)
        self.canvas.bind("<Button-3>", self.show_decoration_menu)
        self.canvas.bind("<Escape>", self.dismiss_decoration_menu)
        self.canvas.bind("<Prior>", lambda _event: self.canvas.yview_scroll(-1, "pages"))
        self.canvas.bind("<Next>", lambda _event: self.canvas.yview_scroll(1, "pages"))
        self.decoration_menu = tk.Menu(self, tearoff=False)
        self.restore_decoration_menu = tk.Menu(self.decoration_menu, tearoff=False)
        self.decoration_menu.bind("<Escape>", self.dismiss_decoration_menu)
        self.restore_decoration_menu.bind("<Escape>", self.dismiss_decoration_menu)
        self.bind("<Destroy>", self.shutdown, add="+")

    def render(self, info, colors, products, scenes, tables, template_label, template_image=None, footer_image=None,
               layout="workbench", template_profile=None, template_full_image=None, views=None, extra_images=None,
               template_original_info=None, hidden_decorations=None):
        """Queue a draft without changing mode. Legacy per-image views are ignored."""
        data = (dict(info), tuple(colors), dict(products), tuple(scenes),
                {key: tuple(tuple(row) for row in matrix) for key, matrix in tables.items() if matrix},
                template_label, template_image, footer_image, layout, copy.deepcopy(template_profile),
                template_full_image, {}, dict(extra_images or {}), copy.deepcopy(template_original_info or {}),
                frozenset(hidden_decorations or ()))
        if data == self.state_data:
            return
        first_render = self.state_data is None
        if self.state_data and (self.state_data[5] != template_label or self.state_data[9] != template_profile):
            self.dismiss_decoration_menu()
            self.decoration_hits.clear()
        self.state_data = data
        if self.original != template_full_image or self.original_info != (template_original_info or {}):
            for key in [key for key in self.assets if key[1] == "original"]:
                self.assets.pop(key)
            for key in [key for key in self.pending if key[1] == "original"]:
                self.cancel_load(key)
            self.original_raster = None
        self.original = template_full_image
        self.original_info = dict(template_original_info or {})
        self.original_button.state(["!disabled"] if self.original or self.original_info else ["disabled"])
        sources = {str(path) for path in (*products.values(), *scenes, template_image, footer_image) if path}
        sources.update(str(path) for path in (extra_images or {}).values() if path)
        if template_profile:
            sources.update(str(path) for path in [template_profile.get("clean_preview"),
                           *[slot.get(key) for slot in template_profile.get("view_slots", {}).values()
                             for key in ("mask", "foreground", "original")]] if path)
            sources.update(str(item["image"]) for item in self.decoration_specs().values() if item.get("image"))
        for key in [key for key in self.pending if not key[1] and key[0] not in sources]:
            self.cancel_load(key)
        self.update_scene_entry()
        if first_render and not (any(info.values()) or colors or tables or any(scenes) or any(products.values())) and self.original:
            self.show_original()
        else:
            self.draft_changed()

    def draft_changed(self):
        if self.final:
            self.final_stale = True
            self.final_button.configure(text="上次成品")
        self.update_caption()
        self.schedule()

    def set_result(self, path):
        for key in [key for key in self.assets if key[1] is True]:
            self.assets.pop(key)
        for key in [key for key in self.pending if key[1] is True]:
            self.cancel_load(key)
        self.final = Path(path) if path else None
        self.final_raster = None
        self.final_stale = False
        self.final_button.configure(text="成品")
        if self.final is None:
            self.selected_slot = None
            if self.mode == "final":
                self.show_live()
            else:
                self.update_caption()
                self.schedule()
        else:
            self.show_final()

    def update_caption(self):
        if self.mode == "original":
            text = self.original_info.get("message") or "原始母版参考 · 保留示例画面"
        elif self.mode == "final":
            text = "上次导出的 JPG · 当前编辑尚未导出" if self.final_stale else "Photoshop 导出的整页 JPG"
        else:
            actual = self.state_data is not None and self.state_data[9]
            text = "预览 · 修改后自动同步 · 图位沿用所选母版" if actual else "预览 · 修改后自动同步"
            if self.decoration_editable() and self.decoration_specs():
                text += "\n右键绿线可删除，右键空白处可恢复"
        if self.pending:
            elapsed = max(time.monotonic() - self.pending_started.get(key, time.monotonic()) for key in self.pending)
            text += f"\n正在读取 {len(self.pending)} 张图片 · {elapsed:.1f} 秒"
        self.caption.configure(text=text)
        self.final_button.state(["!disabled"] if self.final else ["disabled"])

    def show_live(self):
        self.dismiss_decoration_menu()
        changed = self.mode != "live"
        self.mode = "live"
        self.update_caption()
        self.live_button.configure(style="PreviewActive.TButton")
        self.final_button.configure(style="PreviewButton.TButton")
        self.original_button.configure(style="PreviewButton.TButton")
        self.final_button.state(["!disabled"] if self.final else ["disabled"])
        if changed:
            self.canvas.yview_moveto(0)
        self.schedule()

    def show_final(self):
        if not self.final:
            return
        self.dismiss_decoration_menu()
        self.mode = "final"
        self.update_caption()
        self.live_button.configure(style="PreviewButton.TButton")
        self.final_button.configure(style="PreviewActive.TButton")
        self.original_button.configure(style="PreviewButton.TButton")
        self.final_button.state(["!disabled"])
        self.canvas.yview_moveto(0)
        self.schedule()

    def show_original(self):
        if not self.original and not self.original_info:
            return
        self.dismiss_decoration_menu()
        self.mode = "original"
        self.update_caption()
        self.original_button.configure(style="PreviewActive.TButton")
        self.live_button.configure(style="PreviewButton.TButton")
        self.final_button.configure(style="PreviewButton.TButton")
        self.canvas.yview_moveto(0)
        self.schedule()

    def retry_final(self):
        key = (str(self.final), True)
        self.assets.pop(key, None)
        self.final_raster = None
        self.schedule()

    def focus_section(self, section, *, reveal=False):
        if self.mode != "live":
            if not reveal:
                return
            self.show_live()
        self.selected_slot = None
        self.paint()
        position = self.sections.get(section)
        if position is not None:
            self.canvas.yview_moveto(position / self.content_height)

    def focus_slot(self, kind, key, *, reveal=True):
        """Show the selected image position while the user binds its source."""
        if kind == "scene" and key not in range(len(SCENE_FRAMES)):
            return
        self.selected_slot = (kind, kind) if kind in {"hero", "brand"} else (kind, key)
        if not reveal:
            if self.mode == "live":
                self.schedule()
            return
        self.show_live()
        self.paint()
        rectangle = self.slot_boxes.get(self.selected_slot)
        if rectangle is not None:
            top = max(0, rectangle[1] - 55)
            self.canvas.yview_moveto(top / self.content_height)

    def mark_slot(self, kind, key, x, y, width, height):
        slot = (kind, key)
        self.slot_boxes[slot] = (x, y, width, height)
        if self.selected_slot == slot:
            self.canvas.create_rectangle(x - 2, y - 2, x + width + 2, y + height + 2,
                                         outline="#209368", width=3)

    @staticmethod
    def slot_name(slot):
        kind, key = slot
        if kind == "scene":
            return f"模特图 {key + 1}"
        return {"hero": "主视觉", "brand": "品牌场景", "measurement": "量体示意图"}.get(kind, f"商品 · {key}")

    def slot_source(self, slot):
        if self.state_data is None:
            return None
        kind, key = slot
        colors, products, scenes = self.state_data[1:4]
        extra = self.state_data[12]
        if kind == "product":
            return products.get(key)
        if kind == "scene":
            return scenes[key] if key < len(scenes) else None
        if kind == "hero":
            return extra.get("hero") or next((products.get(color) for color in colors if products.get(color)), None)
        if kind == "brand":
            return extra.get("brand") or (scenes[0] if scenes else None)
        return extra.get(kind)

    def scene_slots(self):
        profile = self.state_data[9] if self.state_data else None
        return [("scene", int(key.split("_")[-1]) - 1) for key in (profile or {}).get("view_slots", {})
                if key.startswith("scene_")]

    def set_editing_enabled(self, ready, *, busy=False):
        changed = (self.editing_enabled, self.busy) != (bool(ready), bool(busy))
        self.editing_enabled, self.busy = bool(ready), bool(busy)
        if not self.editing_enabled or self.busy:
            self.dismiss_decoration_menu()
        self.update_scene_entry()
        if changed:
            self.update_caption()
        if changed and self.mode == "original":
            self.schedule()

    def update_scene_entry(self):
        slots = self.scene_slots()
        count = sum(bool(self.slot_source(slot)) for slot in slots)
        has_data = bool(self.state_data and (any(self.state_data[0].values()) or self.state_data[1]))
        action = "正在处理…" if self.busy else "添加图片" if self.editing_enabled and has_data else "请先导入商品"
        self.add_scene_button.configure(text=f"模特图 {count}/{len(slots)} · {action}" if slots else "此母版没有模特图位")
        self.add_scene_button.state(["!disabled"] if self.editing_enabled and not self.busy and has_data and count < len(slots) else ["disabled"])

    def add_next_scene(self):
        slot = next((slot for slot in self.scene_slots() if not self.slot_source(slot)), None)
        if slot:
            self.add_image(slot)

    def add_image(self, slot):
        if not self.editing_enabled or self.busy or not self.state_data or not (any(self.state_data[0].values()) or self.state_data[1]):
            return
        self.selected_slot = slot
        self.show_live()
        if self.on_slot_select:
            self.on_slot_select(*slot)
        if self.on_add_image:
            self.on_add_image(*slot)

    def hit_slot(self, event):
        if self.mode != "live":
            return None
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        return next((slot for slot, (left, top, width, height) in reversed(tuple(self.slot_boxes.items()))
                     if left <= x <= left + width and top <= y <= top + height), None)

    def decoration_specs(self):
        profile = (self.state_data[9] or {}) if self.state_data else {}
        items = profile.get("decorations")
        if not isinstance(items, list):
            return {}
        return {item["id"]: item for item in items
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]}

    def decoration_editable(self):
        return (self.mode == "live" and self.editing_enabled and not self.busy and
                self.on_decoration_change is not None and bool(self.state_data) and
                bool(any(self.state_data[0].values()) or self.state_data[1]))

    def dismiss_decoration_menu(self, _event=None):
        self.restore_decoration_menu.unpost()
        self.decoration_menu.unpost()
        self.decoration_menu.grab_release()
        return "break"

    def show_decoration_menu(self, event):
        if not self.decoration_editable():
            return
        items = self.decoration_specs()
        hidden = self.state_data[14]
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        hit = next((item_id for item_id, left, top, alpha in reversed(self.decoration_hits)
                    if item_id in items and item_id not in hidden and
                    left <= x < left + alpha.width and top <= y < top + alpha.height and
                    alpha.getpixel((int(x - left), int(y - top))) >= 24), None)
        hidden_ids = [item_id for item_id in items if item_id in hidden]
        if hit is None and not hidden_ids:
            return
        self.dismiss_decoration_menu()
        menu = self.decoration_menu
        menu.delete(0, "end")
        if hit is not None:
            menu.add_command(label="删除此装饰", command=lambda: self.set_decoration_hidden(hit, True))
        if len(hidden_ids) == 1:
            item_id = hidden_ids[0]
            label = items[item_id].get("label") or "装饰"
            menu.add_command(label=f"恢复{label}", command=lambda: self.set_decoration_hidden(item_id, False))
        elif hidden_ids:
            submenu = self.restore_decoration_menu
            submenu.delete(0, "end")
            for item_id in hidden_ids:
                label = items[item_id].get("label") or "装饰"
                submenu.add_command(label=label, command=lambda key=item_id: self.set_decoration_hidden(key, False))
            menu.add_cascade(label="恢复装饰", menu=submenu)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def set_decoration_hidden(self, item_id, hidden):
        self.dismiss_decoration_menu()
        if self.decoration_editable() and item_id in self.decoration_specs() and ((item_id in self.state_data[14]) != hidden):
            self.on_decoration_change(item_id, hidden)

    def pointer_down(self, event):
        self.canvas.focus_set()
        if not self.editing_enabled or self.busy:
            return
        slot = self.hit_slot(event)
        if slot is None:
            return
        self.selected_slot = slot
        if not self.slot_source(slot):
            self.add_image(slot)
            return
        if self.on_slot_select:
            self.on_slot_select(*slot)
        source = self.slot_source(slot)
        if (str(source), False) in self.asset_errors:
            self.refresh_asset(source)
        self.schedule()

    def pointer_hover(self, event):
        slot = self.hit_slot(event) if self.editing_enabled and not self.busy else None
        self.canvas.configure(cursor="hand2" if slot else "")

    def refresh_asset(self, path):
        """Call when the user reselects a file that may have changed on disk."""
        self.invalidate_asset(path)
        self.draft_changed()

    @staticmethod
    def file_stamp(path):
        try:
            stat = Path(path).stat()
            return stat.st_size, stat.st_mtime_ns
        except OSError:
            return None

    def cancel_load(self, key):
        future = self.pending.pop(key, None)
        if future is not None:
            future.cancel()
        self.pending_started.pop(key, None)

    def invalidate_asset(self, path, full=None):
        path = str(path)
        keys = set(self.assets) | set(self.pending) | set(self.asset_stamps) | set(self.asset_errors)
        for key in keys:
            if key[0] == path and (full is None or key[1] == full):
                self.assets.pop(key, None)
                self.asset_errors.pop(key, None)
                self.asset_stamps.pop(key, None)
                self.cancel_load(key)
        for key in list(self.rasters):
            if key[0][0] == path or path in key:
                self.rasters.pop(key)
        if path == str(self.original):
            self.original_raster = None
        if path == str(self.final):
            self.final_raster = None

    def scroll(self, event):
        if event.delta:
            self.canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")
        return "break"

    def schedule(self):
        if self.paint_id is not None:
            self.after_cancel(self.paint_id)
        self.paint_id = self.after(55, self.paint)

    def shutdown(self, event):
        if event.widget is self:
            for callback in (self.paint_id, self.poll_id):
                if callback is not None:
                    self.after_cancel(callback)
            self.loader.shutdown(wait=False, cancel_futures=True)

    def load(self, path, full=False):
        key = (str(path), full)
        stamp = self.file_stamp(path)
        if key in self.asset_stamps and self.asset_stamps[key] != stamp:
            self.invalidate_asset(path, full)
        if key in self.assets:
            self.assets.move_to_end(key)
            return key, self.assets[key]
        if key not in self.pending:
            self.asset_stamps[key] = stamp
            self.asset_errors.pop(key, None)
            self.pending[key] = self.loader.submit(load_thumbnail, path, full)
            self.pending_started[key] = time.monotonic()
            self.update_caption()
        if self.poll_id is None:
            self.poll_id = self.after(55, self.collect)
        return key, None

    def collect(self):
        self.poll_id = None
        changed = False
        for key, future in list(self.pending.items()):
            elapsed = time.monotonic() - self.pending_started.get(key, time.monotonic())
            if not future.done() and elapsed < LOAD_TIMEOUT:
                continue
            try:
                if not future.done():
                    raise PreviewImageError(f"读取图片已超过 {LOAD_TIMEOUT} 秒，请点击重试或更换文件。")
                image = future.result()
                if image is None:
                    raise PreviewImageError("未能生成图片预览，请点击重试或更换文件。")
                self.assets[key] = image
                self.asset_errors.pop(key, None)
            except Exception as error:
                self.assets[key] = None
                self.asset_errors[key] = image_error(error)
            self.cancel_load(key)
            if len(self.assets) > 22:
                expired, _ = self.assets.popitem(last=False)
                self.asset_stamps.pop(expired, None)
                self.asset_errors.pop(expired, None)
            changed = True
        self.update_caption()
        if changed:
            self.schedule()
        if self.pending:
            self.poll_id = self.after(55, self.collect)

    def font(self, size, bold=False):
        key = (size, bold)
        if key not in self.fonts:
            self.fonts[key] = tkfont.Font(self, family=FONT, size=-size, weight="bold" if bold else "normal")
        return self.fonts[key]

    def text(self, x, y, value, *, size=13, fill=INK, width=None, bold=False, anchor="nw"):
        return self.canvas.create_text(x, y, text=value, fill=fill, anchor=anchor, width=width,
                                       font=self.font(size, bold))

    def clipped_text(self, value, width, size, bold=False):
        font = self.font(size, bold)
        text = str(value or "")
        if font.measure(text) <= width:
            return text
        while text and font.measure(text + "…") > width:
            text = text[:-1]
        return text + "…" if text else ""

    def panel(self, x, y, width, height, color):
        self.canvas.create_rectangle(x, y, x + width, y + height, fill=color, outline="")

    def picture(self, x, y, width, height, path, *, crop=False, label="待绑定", background=PALE,
                crop_state=None, mask=None, frame_size=None, foreground=None):
        self.picture_base(x, y, width, height, path, crop=crop, label=label, background=background,
                          crop_state=crop_state, mask=mask, frame_size=frame_size)
        if not foreground:
            return
        key, image = self.load(foreground)
        if image is None:
            if key not in self.pending:
                self.foreground_errors[str(foreground)] = self.asset_errors.get(key, "装饰图片无法读取。")
            return
        low, high = image.getchannel("A").getextrema()
        if high == 0:
            return
        if low == 255:
            self.foreground_errors[str(foreground)] = "装饰图片缺少透明背景，已跳过以免遮住照片。"
            return
        width, height = max(1, round(width)), max(1, round(height))
        raster_key = (key, "slot-foreground", width, height)
        rendered = image.resize((width, height), Image.Resampling.LANCZOS) if raster_key not in self.rasters else None
        # Clicks are resolved by slot coordinates; the transparent foreground
        # has no independent interaction bindings.
        self.layout_raster(raster_key, rendered, x, y)

    def picture_base(self, x, y, width, height, path, *, crop=False, label="待绑定", background=PALE,
                     crop_state=None, mask=None, frame_size=None):
        width, height = max(1, round(width)), max(1, round(height))
        if background is not None:
            self.panel(x, y, width, height, background)
        image = None
        if path:
            key, image = self.load(path)
            if image is None:
                label = "正在读取图片" if key in self.pending else "图片无法显示"
            elif image.info.get("visible_bounds") is None and image.getchannel("A").getextrema()[1] == 0:
                self.asset_errors[key] = "图片完全透明，没有可显示的内容。"
                image = None
        if image is None:
            failed = bool(path) and key not in self.pending
            label = self.asset_errors.get(key, "图片无法显示。") + "\n点击重试" if failed else label
            item = self.text(x + width / 2, y + height / 2, label, size=11, fill="#9b5428" if failed else MUTED,
                             width=max(24, width - 12), anchor="center")
            if failed:
                self.canvas.tag_bind(item, "<Button-1>", lambda _event, source=path: self.refresh_asset(source))
            return
        # Every photo uses the same automatic centered fill. Saved views from
        # earlier workbench versions must never alter the current composition.
        state = {"zoom": 1, "focus": [0.5, 0.5]}
        crop_frame = tuple(frame_size or (width, height))
        alpha = None
        if mask:
            # Check the mask before using a cached photo raster, so repairing a
            # mask at the same path immediately invalidates its old raster.
            mask_key, mask_image = self.load(mask)
            if mask_image is None and mask_key in self.pending:
                self.text(x + width / 2, y + height / 2, "正在读取图框蒙版…", size=11,
                          fill=MUTED, width=width, anchor="center")
                return
            if mask_image is not None and mask_image.getchannel("A").getextrema()[1] > 0:
                alpha = mask_image.getchannel("A").resize((width, height), Image.Resampling.LANCZOS)
            else:
                self.invalid_masks.add(str(mask))
        raster_key = (key, width, height, crop, background, state.get("zoom", 1), tuple(state.get("focus", [0.5, 0.5])), str(mask), crop_frame)
        if raster_key not in self.rasters:
            if crop:
                source_w, source_h = image.info.get("source_size", image.size)
                box = resolve_crop(source_w, source_h, *crop_frame, state)
                thumbnail_box = (box[0] * image.width / source_w, box[1] * image.height / source_h,
                                 box[2] * image.width / source_w, box[3] * image.height / source_h)
                rendered = scene_rgb(image).convert("RGBA").transform(
                    (width, height), Image.Transform.EXTENT, thumbnail_box, Image.Resampling.BICUBIC,
                    fillcolor=(0, 0, 0, 0))
            else:
                source_w, source_h = image.info.get("source_size", image.size)
                scale = min(width / source_w, height / source_h)
                fitted = (max(1, round(source_w * scale)), max(1, round(source_h * scale)))
                product = image.resize(fitted, Image.Resampling.LANCZOS)
                rendered = Image.new("RGBA", (width, height), background or (0, 0, 0, 0))
                rendered.alpha_composite(product, ((width - product.width) // 2, (height - product.height) // 2))
            if alpha is not None:
                rendered.putalpha(ImageChops.multiply(rendered.getchannel("A"), alpha))
            self.rasters[raster_key] = ImageTk.PhotoImage(rendered, master=self)
        self.rasters.move_to_end(raster_key)
        while len(self.rasters) > 64:
            self.rasters.popitem(last=False)
        photo = self.rasters[raster_key]
        self.visible_images.append(photo)
        self.canvas.create_image(x, y, image=photo, anchor="nw")

    def paint(self):
        if self.paint_id is not None:
            self.after_cancel(self.paint_id)
        self.paint_id = None
        old_top = max(0, self.canvas.canvasy(0))
        self.canvas.delete("all")
        self.visible_images.clear()
        self.invalid_masks.clear()
        self.foreground_errors.clear()
        self.decoration_errors.clear()
        self.decoration_hits.clear()
        width = max(240, self.canvas.winfo_width())
        page = min(width - 20, 520)
        x = (width - page) / 2
        self.sections = {}
        self.slot_boxes = {}
        if self.mode == "original":
            height = self.paint_original(x, page)
        elif self.mode == "final":
            height = self.paint_final(x, page)
        else:
            height = self.paint_manifest(x, page) if self.state_data and self.state_data[9] else self.paint_live(x, page)
            paper = self.canvas.create_rectangle(x, 10, x + page, height, fill="#ffffff", outline="")
            self.canvas.tag_lower(paper)
        self.content_height = height + 12
        self.canvas.configure(scrollregion=(0, 0, width, self.content_height))
        self.canvas.yview_moveto(old_top / self.content_height)
        notices = []
        if self.invalid_masks:
            notices.append("图框蒙版无效，预览暂用矩形，请重新上传该母版。")
        if self.foreground_errors:
            notices.append("图框装饰无法显示：" + next(iter(self.foreground_errors.values())) + " 请重新读取母版。")
        if self.decoration_errors:
            notices.append("可选装饰无法显示：" + next(iter(self.decoration_errors.values())) + " 请重新读取母版。")
        if notices:
            self.notice.configure(text="\n".join(notices))
            if not self.notice.winfo_manager():
                self.notice.pack(fill="x", after=self.caption, pady=(0, 5))
        else:
            self.notice.pack_forget()

    def paint_final(self, x, page):
        key, image = self.load(self.final, full=True)
        if image is None:
            loading = key in self.pending
            message = "正在读取成品预览…" if loading else self.asset_errors.get(key, "成品预览无法打开。") + "\n点击重试。"
            item = self.text(x + 14, 28, message, fill=MUTED, width=page - 28)
            if not loading:
                self.canvas.tag_bind(item, "<Button-1>", lambda _event: self.retry_final())
            return 160
        height = max(1, round(image.height * page / image.width))
        if self.final_raster is None or self.final_raster[0] != page:
            self.final_raster = (page, ImageTk.PhotoImage(image.resize((page, height), Image.Resampling.LANCZOS), master=self))
        photo = self.final_raster[1]
        self.visible_images.append(photo)
        self.canvas.create_image(x, 10, anchor="nw", image=photo)
        return height + 10

    def paint_original(self, x, page):
        if not self.original:
            return self.paint_original_error(x, page, self.original_info.get("message") or "原始母版预览不可用，请重新选择原始 PSD/PSB。")
        key, image = self.load(self.original, full="original")
        if image is None:
            if key not in self.pending:
                return self.paint_original_error(x, page, self.asset_errors.get(key) or self.original_info.get("message") or "母版原稿预览无法打开，文件可能已移动或尚未成功读取。")
            self.text(x + 14, 28, "正在读取母版版式…", fill=MUTED, width=page - 28)
            return 160
        height = max(1, round(image.height * page / image.width))
        if self.original_raster is None or self.original_raster[0] != page:
            self.original_raster = (page, ImageTk.PhotoImage(image.resize((page, height), Image.Resampling.LANCZOS), master=self))
        photo = self.original_raster[1]
        self.visible_images.append(photo)
        self.canvas.create_image(x, 10, anchor="nw", image=photo)
        return height + 10

    def paint_original_error(self, x, page, message):
        self.text(x + 14, 26, "母版原稿暂不可用", size=15, bold=True, fill=INK, width=page - 28)
        item = self.text(x + 14, 60, message, size=12, fill=MUTED, width=page - 28)
        bottom = self.canvas.bbox(item)[3] + 18
        if self.on_repair_original:
            width = min(page - 28, 220)
            self.canvas.create_rectangle(x + 14, bottom, x + 14 + width, bottom + 40,
                                         fill="#e7ece9" if self.busy else GREEN, outline="", tags="repair-original")
            self.canvas.create_text(x + 14 + width / 2, bottom + 20,
                                    text="正在处理…" if self.busy else "重新读取母版原稿", fill=MUTED if self.busy else "white",
                                    font=self.font(12, True), tags="repair-original")
            self.canvas.tag_bind("repair-original", "<Button-1>", lambda _event: self.repair_original())
            bottom += 52
        return max(180, bottom + 12)

    def repair_original(self):
        if self.busy or self.on_repair_original is None:
            return
        for key in [key for key in self.assets if key[1] == "original"]:
            self.assets.pop(key)
        for key in [key for key in self.pending if key[1] == "original"]:
            self.cancel_load(key)
        self.original_raster = None
        self.on_repair_original()

    def layout_raster(self, key, image, x, y):
        if key not in self.rasters:
            self.rasters[key] = ImageTk.PhotoImage(image, master=self)
        self.rasters.move_to_end(key)
        while len(self.rasters) > 64:
            self.rasters.popitem(last=False)
        photo = self.rasters[key]
        self.visible_images.append(photo)
        self.canvas.create_image(x, y, anchor="nw", image=photo)

    @staticmethod
    def color(value, fallback="#263930"):
        if isinstance(value, str) and value.startswith("#"):
            return value
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return "#" + "".join(f"{min(255, max(0, round(component))):02x}" for component in value[:3])
        return fallback

    def module_skin(self, module, target, profile, clean, x, scale, next_top):
        rect = target["rect"]
        canvas = profile["canvas"]
        trim_left = max(0, -rect[0])
        trim_right = max(0, rect[0] + rect[2] - canvas["width"])
        visible_width = rect[2] - trim_left - trim_right
        if visible_width <= 0:
            return
        width, height = max(1, round(visible_width * scale)), max(1, round(rect[3] * scale))
        left, top = x + (rect[0] + trim_left) * scale, 10 + rect[1] * scale
        self.panel(left, top, width, height, self.color(module.get("fill"), "#ffffff"))
        if clean is None or module.get("generated"):
            return
        raw = list(module["rect"])
        original_bottom = raw[1] + raw[3]
        raw[3] = max(0, min(original_bottom, next_top) - raw[1])
        if raw[3] <= 0:
            return
        raw[0] += trim_left
        raw[2] -= trim_left + trim_right
        crop = [raw[0] * clean.width / canvas["width"], raw[1] * clean.height / canvas["height"],
                (raw[0] + raw[2]) * clean.width / canvas["width"],
                (raw[1] + raw[3]) * clean.height / canvas["height"]]
        split_at = None
        extra_height = round(target.get("table_height_delta", target.get("height_delta", 0)) * scale)
        measurement = profile.get("view_slots", {}).get("measurement", {})
        table_rect = module.get("table", {}).get("rect")
        if table_rect and extra_height > 0 and measurement.get("after_table") and measurement.get("role") == module["role"]:
            _, table_top, _, table_height = table_rect
            split_at = round((table_top + table_height - raw[1]) * scale)
        key = ((str(profile.get("clean_preview")), "skin"), tuple(raw), width, height, split_at,
               extra_height if split_at is not None else 0)
        if key not in self.rasters:
            slice_ = clean.crop(crop)
            sample = slice_.getpixel((0, 0)) if min(slice_.size) else (255, 255, 255, 255)
            image = Image.new("RGBA", (width, height), sample)
            original_height = max(1, round(raw[3] * scale))
            slice_ = slice_.resize((width, original_height), Image.Resampling.LANCZOS)
            if split_at is not None and 0 < split_at < original_height:
                # The size notes stay below the measurement diagram as rows are added.
                image.alpha_composite(slice_.crop((0, 0, width, split_at)), (0, 0))
                image.alpha_composite(slice_.crop((0, split_at, width, original_height)), (0, split_at + extra_height))
            else:
                image.alpha_composite(slice_, (0, 0))
        else:
            image = None
        self.layout_raster(key, image, left, top)
        if next_top > original_bottom:
            gap_height = max(1, round((next_top - original_bottom) * scale))
            gap_key = ((str(profile.get("clean_preview")), "gap"), original_bottom, next_top, scale)
            if gap_key not in self.rasters:
                gap = clean.crop((0, original_bottom * clean.height / canvas["height"], clean.width,
                                  next_top * clean.height / canvas["height"]))
                gap = gap.resize((max(1, round(canvas["width"] * scale)), gap_height), Image.Resampling.LANCZOS)
            else:
                gap = None
            self.layout_raster(gap_key, gap, x, top + height)

    @staticmethod
    def mixed_text(draw, value, x, baseline, px, fill, align="left"):
        pieces = []
        for char in str(value):
            kind = "digit" if char in "1%" else "latin" if char.isascii() and (char.isalnum() or char in ".+- ") else "cn"
            face = font_face(kind, px)
            pieces.append((char, face, face.getlength(char)))
        total = sum(piece[2] for piece in pieces)
        if align == "center":
            x -= total / 2
        elif align == "right":
            x -= total
        for char, face, length in pieces:
            draw.text((x, baseline), char, font=face, fill=fill, anchor="ls")
            x += length

    def field_raster(self, value, binding, x, scale, dy=0, *, layout=None):
        rect = layout["rect"] if layout is not None else binding.get("rect")
        if not rect or min(rect[2:]) <= 0:
            return
        style = binding.get("style") or {}
        width, height = max(1, round(rect[2])), max(1, round(rect[3]))
        key = (("field", str(value)), tuple(rect), str(style), scale, str(layout))
        if key not in self.rasters:
            image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            try:
                if layout is None:
                    layout = fit_text_layout(value, rect, style)
            except ValueError as error:
                self.text(x + rect[0] * scale, 10 + (rect[1] + dy) * scale, str(error),
                          size=11, fill="#a84a35", width=max(24, width * scale))
                return
            px = layout["px"]
            align = str(style.get("align", "left")).lower()
            anchor = width / 2 if align == "center" else width if align == "right" else 0
            baseline = px
            for line in layout["lines"]:
                self.mixed_text(draw, line, anchor, baseline, px, self.color(style.get("color")), align)
                baseline += layout["leading"]
            image = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS)
        else:
            image = None
        self.layout_raster(key, image, x + rect[0] * scale, 10 + (rect[1] + dy) * scale)

    def size_note_raster(self, note, target, value, planned, x, scale):
        if not note or not target or not target.get("visible", True):
            return
        titles = {tuple(title["path"]): title["rect"] for title in target.get("titles", []) if title.get("path")}
        note_tops = [titles[tuple(line["path"])][1] for line in note.get("lines", []) if tuple(line["path"]) in titles]
        if planned:
            self.sections["size_note"] = 10 + planned["rect"][1] * scale
        elif note_tops:
            self.sections["size_note"] = 10 + min(note_tops) * scale
        if value is not None:
            if value and planned:
                self.field_raster(value, note, x, scale, layout=planned)
            return
        for line in note.get("lines", []):
            rect = titles.get(tuple(line["path"]))
            if rect is None or not line.get("text"):
                continue
            value = line["text"]
            lines = value.split("\n")
            style = line.get("style") or {}
            px = float(style.get("size_px", 17))
            leading = px * 1.15
            # Native title bounds measure visible ink. Leave the font's ascent
            # and descent available when painting that same line on the canvas.
            width = max(rect[2], math.ceil(max(text_width(text, px) for text in lines) + 1))
            height = max(rect[3], math.ceil(px + (len(lines) - 1) * leading + text_descent(lines[-1], px)))
            align = style.get("align")
            offset = (width - rect[2]) * {"right": 1, "center": .5}.get(align, 0)
            layout = {"rect": [rect[0] - offset, rect[1], width, height], "lines": lines,
                      "px": px, "leading": leading}
            self.field_raster(value, line, x, scale, layout=layout)

    def table_raster(self, matrix, table, x, scale):
        region, plan, style = table["region"], table["plan"], table.get("spec", {})
        width, height = max(1, round(region[2])), max(1, round(plan["height"]))
        key = (("table", repr(matrix)), str(plan), str(style), scale)
        if key not in self.rasters:
            image = Image.new("RGBA", (width, height), "white")
            draw = ImageDraw.Draw(image)
            accent = bool(style.get("accent"))
            header_color = self.color(style.get("header_fill", style.get("header_color")), "#2e9e49" if accent else "#ededed")
            lead_color = self.color(style.get("lead_fill"), "#e8e8e8")
            stripe = self.color(style.get("stripe_fill"), "#f8f8f8")
            text_color = self.color(style.get("text_color"), "#363636")
            header_text_color = self.color(style.get("header_text_color"), "white" if accent else text_color)
            header = float(plan["header"])
            row_h, px = float(plan["row"]), float(plan["px"])
            draw.rectangle((0, 0, width, header), fill=header_color)
            if accent:
                draw.rectangle((0, header, plan["widths"][0], height), fill=lead_color)
            for row_index, values in enumerate(matrix):
                top = 0 if row_index == 0 else header + (row_index - 1) * row_h
                band_h = header if row_index == 0 else row_h
                if row_index and row_index % 2 == 0:
                    draw.rectangle((0, top, width, top + band_h), fill=stripe)
                    if accent:
                        draw.rectangle((0, top, plan["widths"][0], top + band_h), fill=lead_color)
                left = 0
                for value, cell_width in zip(values, plan["widths"]):
                    self.mixed_text(draw, value or " ", left + cell_width / 2, top + band_h / 2 + px * .33,
                                    px, header_text_color if row_index == 0 else text_color, "center")
                    left += cell_width
            image = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS)
        else:
            image = None
        self.layout_raster(key, image, x + region[0] * scale, 10 + region[1] * scale)

    def color_raster(self, image, asset_key, frame, x, page_scale, target_height):
        width, height = image.info["source_size"]
        bounds = image.info["visible_bounds"]
        image_scale = target_height / (bounds[3] - bounds[1])
        # Empty source padding stays in the embedded original. The preview only
        # allocates pixels around visible content and the resampling fringe.
        padding = 3 * max(width / image.width, height / image.height)
        crop = [max(0, bounds[0] - padding), max(0, bounds[1] - padding),
                min(width, bounds[2] + padding), min(height, bounds[3] + padding)]
        thumbnail_box = [crop[0] * image.width / width, crop[1] * image.height / height,
                         crop[2] * image.width / width, crop[3] * image.height / height]
        rendered_w = max(1, round((crop[2] - crop[0]) * image_scale * page_scale))
        rendered_h = max(1, round((crop[3] - crop[1]) * image_scale * page_scale))
        key = (asset_key, "shared-color-height", tuple(bounds), target_height, page_scale)
        if key not in self.rasters:
            rendered = image.crop(thumbnail_box).resize((rendered_w, rendered_h), Image.Resampling.LANCZOS)
        else:
            rendered = None
        left = frame[0] + frame[2] / 2 - (bounds[0] + bounds[2]) / 2 * image_scale + crop[0] * image_scale
        top = frame[1] + frame[3] - bounds[3] * image_scale + crop[1] * image_scale
        self.layout_raster(key, rendered, x + left * page_scale, 10 + top * page_scale)

    def paint_decorations(self, targets, canvas, x, scale):
        hidden = self.state_data[14]
        for item_id, item in self.decoration_specs().items():
            if item_id in hidden:
                continue
            target = targets.get(item.get("role", "scenes"))
            if not target or not target.get("visible", True):
                continue
            try:
                left, top, width, height = map(float, item["rect"])
                if not all(math.isfinite(value) for value in (left, top, width, height)) or min(width, height) <= 0:
                    raise ValueError("无效的装饰范围")
                source = item["image"]
                if not isinstance(source, (str, Path)) or not source:
                    raise ValueError("缺少装饰图片")
            except (KeyError, TypeError, ValueError):
                self.decoration_errors[item_id] = "装饰的图层信息不完整。"
                continue
            top += target.get("delta_y", 0)
            tx, ty, tw, th = target["rect"]
            clip_left, clip_top = max(0, tx, left), max(0, ty, top)
            clip_right = min(canvas["width"], tx + tw, left + width)
            clip_bottom = min(canvas["height"], ty + th, top + height)
            if clip_left >= clip_right or clip_top >= clip_bottom:
                continue
            asset_key, image = self.load(source)
            if image is None:
                if asset_key not in self.pending:
                    self.decoration_errors[item_id] = self.asset_errors.get(asset_key, "装饰图片无法读取。")
                continue
            low, high = image.getchannel("A").getextrema()
            if low == 255 or high == 0:
                self.decoration_errors[item_id] = "装饰图片缺少有效的透明内容。"
                continue
            canvas_left, canvas_top = round(x + clip_left * scale), round(10 + clip_top * scale)
            size = (max(1, round(x + clip_right * scale) - canvas_left),
                    max(1, round(10 + clip_bottom * scale) - canvas_top))
            crop = ((clip_left - left) * image.width / width, (clip_top - top) * image.height / height,
                    (clip_right - left) * image.width / width, (clip_bottom - top) * image.height / height)
            key = (asset_key, "decoration", size, crop)
            rendered = image.resize(size, Image.Resampling.LANCZOS, box=crop)
            self.layout_raster(key, rendered, canvas_left, canvas_top)
            self.decoration_hits.append((item_id, canvas_left, canvas_top, rendered.getchannel("A")))

    def paint_product_attributes(self, profile, values, x, scale, dy):
        binding = profile.get("product_attributes")
        if not binding:
            return
        try:
            values = normalize_product_attributes(values)
        except ValueError:
            values = {}
        values = resolve_product_attributes(profile, values)
        fit = next(option for option in binding["fit"]["options"] if option["value"] == values["版型"])
        key, source = self.load(fit["image"], full=True)
        left, top, width, height = binding["rect"]
        y = 10 + (top + dy) * scale
        self.sections["attributes"] = y
        if source is not None:
            size = (max(1, round(width * scale)), max(1, round(height * scale)))
            raster_key = (key, "product attributes", size)
            raster = source.resize(size, Image.Resampling.LANCZOS) if raster_key not in self.rasters else None
            self.layout_raster(raster_key, raster, x + left * scale, y)
        for field, style in binding["fields"].items():
            self.field_raster(values[field], style, x, scale, dy)

    def paint_manifest(self, x, page):
        info, colors, products, scenes, tables = self.state_data[:5]
        profile, _, _, extra_images = self.state_data[9:13]
        scene_count = max([0, *[index + 1 for index, source in enumerate(scenes) if source]])
        hero = extra_images.get("hero")
        product_hero = not hero
        hero = hero or next((products.get(color) for color in colors if products.get(color)), None)
        brand = extra_images.get("brand") or (scenes[0] if scenes else None)
        size_note = info.get("尺码备注")
        try:
            geometry = plan_layout(profile, max(1, len(colors)), tables, scene_count,
                                   has_hero=bool(hero), has_brand=bool(brand), size_note=size_note)
        except ValueError as error:
            self.text(x + 12, 30, str(error), fill="#a84a35", width=page - 24)
            return 180
        scale = page / geometry["canvas"]["width"]
        clean = None
        if profile.get("clean_preview"):
            _, clean = self.load(profile["clean_preview"], full="skin")
        modules = profile["modules"]
        modules = list(modules.values()) if isinstance(modules, dict) else modules
        targets = geometry["modules"]
        by_role = {module["role"]: module for module in modules}
        original_order = sorted(modules, key=lambda module: module["rect"][1])
        boundaries = {module["role"]: (original_order[index + 1]["rect"][1] if index + 1 < len(original_order)
                                       else profile["canvas"]["height"]) for index, module in enumerate(original_order)}
        for role in geometry.get("module_order", by_role):
            module, target = by_role.get(role), targets.get(role)
            if module and target and target.get("visible", True) and target["rect"][3] > 0:
                self.module_skin(module, target, profile, clean, x, scale, boundaries[role])
        self.sections["hero"] = 0
        for role, key in (("product", "product"), ("colors", "product"), ("size_table", "sizes"), ("scenes", "scenes")):
            module = targets.get(role)
            if module and module.get("visible", True) and key not in self.sections:
                self.sections[key] = 10 + module["rect"][1] * scale
        product_dy = targets.get("product", {}).get("delta_y", 0)
        self.paint_product_attributes(profile, info.get("STEP1 属性"), x, scale, product_dy)
        for field, binding in profile.get("fields", {}).items():
            items = binding.get("occurrences", [binding])
            for item in items:
                role = item.get("role", "product")
                dy = targets.get(role, {}).get("delta_y", product_dy)
                value = "/".join(colors) if field == "颜色" else info.get(field, "")
                self.field_raster(value, item, x, scale, dy)
                if item.get("generated") and item.get("label_rect"):
                    self.field_raster(field, {"rect": item["label_rect"], "style": {"size_px": 28, "align": "left"}}, x, scale, dy)
        note = profile.get("size_note") or {}
        note_paths = {tuple(line["path"]) for line in note.get("lines", [])}
        for role, module in by_role.items():
            if not targets.get(role, {}).get("visible", True):
                continue
            if clean is None or module.get("generated"):
                for title in module.get("titles", []):
                    if tuple(title.get("path", [])) not in note_paths:
                        self.field_raster(title.get("text", ""), title, x, scale, targets.get(role, {}).get("delta_y", 0))
            for binding in module.get("dynamic_texts", []):
                value = info.get(binding.get("field"), "")
                if binding.get("field") in {"颜色", "colors"}:
                    value = binding.get("separator", "/").join(colors)
                value = binding.get("prefix", "") + value
                self.field_raster(value, binding, x, scale, targets.get(role, {}).get("delta_y", 0))
        self.size_note_raster(note, targets.get("size_table"), size_note, geometry.get("size_note"), x, scale)
        color_spec = profile.get("colors", {})
        color_style = color_spec.get("label_style", color_spec.get("prototype", {}).get("style", {}))
        color_images = {}
        for color in colors:
            if products.get(color):
                key, image = self.load(products[color])
                if image is not None and image.info.get("visible_bounds"):
                    color_images[color] = (key, image)
        target_height = None
        if color_images:
            height_limits = [item["image_rect"][3] for item in geometry["colors"]["items"]]
            for item in geometry["colors"]["items"]:
                index = item["index"]
                if index < len(colors) and colors[index] in color_images:
                    bounds = color_images[colors[index]][1].info["visible_bounds"]
                    height_limits.append(item["image_rect"][2] * (bounds[3] - bounds[1]) / (bounds[2] - bounds[0]))
            target_height = min(height_limits)
        for item in geometry["colors"]["items"]:
            index = item["index"]
            if index >= len(colors):
                continue
            color = colors[index]
            rect = item["image_rect"]
            left, top, width, height = x + rect[0] * scale, 10 + rect[1] * scale, rect[2] * scale, rect[3] * scale
            if color in color_images and target_height is not None:
                key, image = color_images[color]
                self.color_raster(image, key, rect, x, scale, target_height)
            else:
                self.picture(left, top, width, height, products.get(color), label="待绑定", background=None)
            self.mark_slot("product", color, left, top, width, height)
            self.field_raster(color, {"rect": item["label_rect"], "style": {"size_px": 27, "align": "center", **color_style}}, x, scale)
        for name, table in geometry["tables"].items():
            self.table_raster(tables[name], table, x, scale)
        for slot_id, slot in geometry["view_slots"].items():
            if not slot.get("visible", True):
                continue
            if slot_id == "hero":
                source, kind, key, crop = hero, "hero", "hero", not product_hero
            elif slot_id == "brand":
                source, kind, key, crop = brand, "brand", "brand", True
            elif slot_id == "measurement":
                source, kind, key, crop = extra_images.get(slot_id) or slot.get("original"), slot_id, slot_id, False
            elif slot_id.startswith("scene_"):
                index = int(slot_id.split("_")[-1]) - 1
                source = scenes[index] if index < len(scenes) else None
                kind, key, crop = "scene", index, True
            else:
                continue
            rect = slot["rect"]
            left, top, width, height = x + rect[0] * scale, 10 + rect[1] * scale, rect[2] * scale, rect[3] * scale
            self.picture(left, top, width, height, source, crop=crop,
                         mask=slot.get("mask"), frame_size=rect[2:4],
                         label=f"{self.slot_name((kind, key))} · 未绑定", background=None,
                         foreground=slot.get("foreground"))
            self.mark_slot(kind, key, left, top, width, height)
        self.paint_decorations(targets, geometry["canvas"], x, scale)
        height = 10 + geometry["canvas"]["height"] * scale
        # A gap before an occupied slot already has an actionable placeholder
        # in the page. A duplicate card would overwrite its click/focus bounds.
        missing = [slot for slot in self.scene_slots() if not self.slot_source(slot) and slot not in self.slot_boxes]
        if missing:
            height += 20
            self.text(x + 10, height, "添加模特图片", size=13, bold=True, fill=GREEN)
            self.text(x + 10, height + 22, "以下是待选图位，未添加的内容不会导出。", size=10, fill=MUTED, width=page - 20)
            height += 50
            gap = 10
            card_width = (page - gap) / 2
            for index, slot in enumerate(missing):
                left, top = x + index % 2 * (card_width + gap), height + index // 2 * 76
                self.canvas.create_rectangle(left, top, left + card_width, top + 64,
                                             fill="#f1f7f2", outline="#8eb4a0", dash=(4, 3))
                self.text(left + card_width / 2, top + 32, f"＋ {self.slot_name(slot)}", size=11,
                          fill=GREEN, anchor="center", width=card_width - 12)
                self.mark_slot(*slot, left, top, card_width, 64)
            height += ((len(missing) + 1) // 2) * 76
        return height

    def paint_live(self, x, page):
        if self.state_data is None:
            return self.paint_empty(x, page)
        info, colors, products, scenes, tables, template, template_image, footer_image, layout = self.state_data[:9]
        if not (any(info.values()) or colors or any(products.values()) or any(scenes) or tables):
            return self.paint_empty(x, page)
        self.sections["hero"] = 0
        self.panel(x, 10, page, 56, GREEN)
        self.text(x + 14, 17, "商品详情", size=18, fill="#ffffff", bold=True)
        self.text(x + 14, 43, self.clipped_text(template or "", page - 28, 11), size=11, fill="#e1f4e8")
        y = 76
        if template_image and layout != "classic":
            height = round(page * 0.7)
            self.picture(x, y, page, height, template_image, label="母版页头", background="#f6f8f5")
            y += height

        if layout != "classic":
            title = self.text(x + 12, y + 10, info.get("名称") or "商品名称", size=19, bold=True, width=page - 24)
            subtitle = self.canvas.bbox(title)[3] + 5
            self.text(x + 12, subtitle, info.get("货号") or "待填写货号", size=11, fill=GREEN)
            image_y = subtitle + 23
            hero_height = min(round((page - 24) / HERO_RATIO), 480)
            hero = self.state_data[12].get("hero")
            if hero or self.selected_slot == ("hero", "hero"):
                hero_width = round(hero_height * HERO_RATIO)
                self.panel(x + 12, image_y, page - 24, hero_height, PALE)
                hero_x = x + (page - hero_width) / 2
                self.picture(hero_x, image_y, hero_width, hero_height, hero, crop=True, label="模特图 1 / 主视觉待绑定")
                self.mark_slot("hero", "hero", hero_x, image_y, hero_width, hero_height)
            else:
                hero = products.get(colors[0]) if colors else None
                self.picture(x + 12, image_y, page - 24, min(300, hero_height), hero, label="主视觉待绑定")
                hero_height = min(300, hero_height)
                self.mark_slot("hero", "hero", x + 12, image_y, page - 24, hero_height)
            y = image_y + hero_height + 10
            for text in ("配色  /  " + (" · ".join(colors) or "待填写"), "尺码  /  " + (info.get("尺码") or "待填写")):
                item = self.text(x + 12, y, text, size=12, fill=MUTED, width=page - 24)
                y = self.canvas.bbox(item)[3] + 6

        self.sections["product"] = y - 5
        y = self.paint_information(x, y + 8, page, info, colors, products, layout)
        self.sections["sizes"] = y - 4
        labels = ("选尺码", "尺码快选", "试穿报告") if layout == "classic" else TABLE_LABELS
        for key, label in zip(TABLE_NAMES, labels):
            matrix = tables.get(key)
            if matrix or key != "试穿报告":
                y = self.paint_table(x, y + 8, page, label, matrix)
        self.sections["scenes"] = y - 4
        selected_scene = self.selected_slot[1] if self.selected_slot and self.selected_slot[0] == "scene" else -1
        if any(scenes) or selected_scene > 0 or (layout == "classic" and selected_scene == 0):
            self.text(x + 12, y + 9, "模特展示", size=15, bold=True)
            y += 34
            last = max([selected_scene, *[i for i, scene in enumerate(scenes) if scene]])
            for index in range(min(last + 1, len(SCENE_FRAMES))):
                path = scenes[index] if index < len(scenes) else None
                frame = SCENE_FRAMES[index]
                width = page - (68 if index == 1 else 24)
                self.picture(x + (page - width) / 2, y, width, width * frame[1] / frame[0], path, crop=True,
                             label=f"模特图 {index + 1} 待绑定")
                if index > 0 or layout == "classic":
                    self.mark_slot("scene", index, x + (page - width) / 2, y, width, width * frame[1] / frame[0])
                y += round(width * frame[1] / frame[0]) + 9
        if layout == "classic":
            self.panel(x, y + 7, page, 30, PALE)
            self.text(x + 12, y + 14, "品牌故事", bold=True, fill=GREEN)
            y += 40
            if scenes and scenes[0]:
                self.picture(x + 12, y, page - 24, (page - 24) * 0.65, scenes[0], crop=True)
                y += round((page - 24) * 0.65) + 8
            else:
                self.text(x + 12, y, "沿用母版品牌文案", size=11, fill=MUTED)
                y += 24
        if footer_image:
            height = round(page * 1.9)
            self.picture(x, y + 7, page, height, footer_image, label="母版页尾", background="#f6f8f5")
            return y + height + 7
        self.panel(x, y + 7, page, 47, "#f6f8f5")
        self.text(x + 12, y + 23, "母版页尾", size=11, fill=MUTED)
        return y + 54

    def paint_empty(self, x, page):
        self.text(x + 16, 32, "先导入一款商品", size=18, bold=True, width=page - 32)
        self.text(x + 16, 69, "从左侧选择飞书表格或本地资料。\n导入后，修改字段、表格和配图都会在这里同步。",
                  size=13, fill=MUTED, width=page - 32)
        return 185

    def paint_information(self, x, y, page, info, colors, products, layout):
        self.panel(x, y, page, 28, PALE)
        self.text(x + 12, y + 6, "商品信息", bold=True, fill=GREEN)
        y += 36
        for key in ("名称", "货号", "尺码", "材质"):
            self.text(x + 12, y, key, size=11, fill=MUTED)
            value = self.text(x + 53, y, info.get(key) or "待填写", width=page - 65, size=12)
            y = self.canvas.bbox(value)[3] + 6
        self.text(x + 12, y + 8, "选颜色" if layout == "classic" else "S2  选颜色", bold=True, fill=GREEN)
        y += 31
        count = len(colors)
        if not count:
            self.text(x + 12, y, "暂无色图", size=11, fill=MUTED)
            return y + 25
        gap = 4
        width = (page - 24 - gap * (count - 1)) / count
        height = min(128, round(width * 1.43))
        for i, color in enumerate(colors):
            left = x + 12 + i * (width + gap)
            self.picture(left, y, width, height, products.get(color), label="待绑图")
            self.mark_slot("product", color, left, y, width, height)
            self.text(left + width / 2, y + height + 7, self.clipped_text(color, width - 3, 11),
                      size=11, anchor="n")
        return y + height + 28

    def paint_table(self, x, y, page, label, matrix):
        self.panel(x, y, page, 28, PALE)
        self.text(x + 12, y + 6, label, bold=True, fill=GREEN)
        y += 32
        if not matrix or not matrix[0]:
            self.text(x + 12, y + 2, "等待有效表格数据", size=11, fill=MUTED)
            return y + 24
        count = len(matrix[0])
        column = (page - 24) / count
        size = 11 if count <= 6 else 9
        for row_index, row in enumerate(matrix[:25]):
            self.panel(x + 12, y, page - 24, 20, "#d5e8dc" if row_index == 0 else ("#ffffff" if row_index % 2 else "#f6f8f5"))
            for index, cell in enumerate(row[:count]):
                value = self.clipped_text(cell, column - 4, size, row_index == 0)
                self.text(x + 12 + (index + 0.5) * column, y + 10, value, size=size,
                          bold=row_index == 0, anchor="center")
            y += 20
        if len(matrix) > 25:
            self.text(x + 12, y + 3, f"另有 {len(matrix) - 25} 行", size=11, fill=MUTED)
            y += 22
        return y + 6
