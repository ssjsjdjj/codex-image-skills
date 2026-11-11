"""Edit one image frame while retaining its original-pixel crop coordinates."""

import copy
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, ImageTk

from geometry import contain_zoom, normalize_view, resolve_crop


FONT = "Microsoft YaHei UI"


class CropEditor(tk.Toplevel):
    def __init__(self, parent, *, source, frame_size, initial_state=None, on_save=None,
                 title="调整图片取景", mask=None):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        scale = max(1, self.winfo_fpixels("1i") / 96)
        self.geometry(f"{min(round(960 * scale), self.winfo_screenwidth() - 70)}x"
                      f"{min(round(720 * scale), self.winfo_screenheight() - 110)}")
        self.minsize(620, 460)
        self.source = Path(source)
        self.frame_size = tuple(map(float, frame_size))
        self.mask_source = Path(mask) if mask else None
        self.mask_image = None
        self.on_save = on_save
        self.state = normalize_view(initial_state)
        self.result = None
        self.image = None
        self.image_size = None
        self.history = []
        self.drag = None
        self.render_task = None
        self.poll_task = None
        self.syncing = False
        self.preset_note = ""
        self.messages = queue.Queue()
        self.zoom_value = tk.DoubleVar(value=self.state["zoom"])
        self.zoom_text = tk.StringVar(value=f"{self.state['zoom'] * 100:.0f}")
        self.readout = tk.StringVar(value="正在载入原图…")

        area = ttk.Frame(self, padding=12)
        area.pack(fill="both", expand=True)
        ttk.Label(area, text=title, font=(FONT, 14, "bold")).pack(anchor="w")
        ttk.Label(area, text="拖动图片调整位置，滚轮或下方滑杆缩放。绿色图框内为保存后的内容，缩小时空白沿用母版底色。",
                  font=(FONT, 9), wraplength=900).pack(anchor="w", pady=(4, 8))
        self.canvas = tk.Canvas(area, background="#23352d", highlightthickness=0, cursor="fleur")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self.schedule())
        self.canvas.bind("<ButtonPress-1>", self.drag_start)
        self.canvas.bind("<B1-Motion>", self.drag_move)
        self.canvas.bind("<ButtonRelease-1>", self.drag_end)
        self.canvas.bind("<MouseWheel>", self.wheel)

        toolbar = ttk.Frame(area)
        toolbar.pack(fill="x", pady=(10, 6))
        ttk.Label(toolbar, text="等比缩放", font=(FONT, 10, "bold")).pack(side="left", padx=(0, 12))
        self.slider = ttk.Scale(toolbar, from_=.1, to=8, variable=self.zoom_value,
                                command=self.slider_changed)
        self.slider.pack(side="left", fill="x", expand=True)
        self.slider.bind("<ButtonRelease-1>", lambda _: self.commit())
        self.numeric = ttk.Entry(toolbar, width=7, textvariable=self.zoom_text, justify="right")
        self.numeric.pack(side="left", padx=(10, 3))
        self.numeric.bind("<Return>", self.numeric_changed)
        self.numeric.bind("<FocusOut>", self.numeric_changed)
        ttk.Label(toolbar, text="%", font=(FONT, 10)).pack(side="left")
        presets = ttk.Frame(area)
        presets.pack(fill="x", pady=(0, 6))
        self.contain_button = ttk.Button(presets, text="完整显示", command=self.contain)
        self.contain_button.pack(side="left")
        self.fill_button = ttk.Button(presets, text="填满图框", command=self.reset)
        self.fill_button.pack(side="left", padx=7)
        ttk.Label(presets, text="100% 填满 · 10–800% 可调 · 方格表示透明留空", font=(FONT, 9)).pack(side="left", padx=4)
        ttk.Label(area, textvariable=self.readout, font=(FONT, 9), wraplength=1000).pack(anchor="w")
        buttons = ttk.Frame(area)
        buttons.pack(fill="x", pady=(10, 0))
        self.reset_button = ttk.Button(buttons, text="复位", command=self.reset)
        self.reset_button.pack(side="left")
        self.undo_button = ttk.Button(buttons, text="撤销", command=self.undo)
        self.undo_button.pack(side="left", padx=(7, 0))
        ttk.Button(buttons, text="查看原图", command=self.open_original).pack(side="left", padx=7)
        ttk.Button(buttons, text="取消", command=self.destroy).pack(side="right")
        self.save_button = ttk.Button(buttons, text="保存此图取景", style="Primary.TButton", command=self.save)
        self.save_button.pack(side="right", padx=7)
        self.controls = (self.slider, self.numeric, self.contain_button, self.fill_button,
                         self.reset_button, self.undo_button, self.save_button)
        for control in self.controls:
            control.state(["disabled"])
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _: self.destroy())
        self.bind("<Control-z>", lambda _: self.undo())
        self.bind("<Destroy>", self.cleanup, add="+")

        def load():
            try:
                with Image.open(self.source) as original:
                    oriented = ImageOps.exif_transpose(original)
                    size = oriented.size
                    oriented.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
                    image = oriented.convert("RGBA")
                alpha = None
                if self.mask_source:
                    with Image.open(self.mask_source) as mask_image:
                        alpha = mask_image.convert("RGBA").getchannel("A")
                self.messages.put((image, size, alpha, None))
            except (OSError, ValueError, Image.DecompressionBombError) as error:
                self.messages.put((None, None, None, str(error)))

        threading.Thread(target=load, daemon=True).start()
        self.poll_task = self.after(40, self.loaded)

    def loaded(self):
        self.poll_task = None
        try:
            image, size, alpha, error = self.messages.get_nowait()
        except queue.Empty:
            self.poll_task = self.after(40, self.loaded)
            return
        if error:
            self.readout.set(f"原图无法打开 · {error}")
            return
        self.image, self.image_size, self.mask_image = image, size, alpha
        self.normalize()
        self.history.append(copy.deepcopy(self.state))
        for control in self.controls:
            control.state(["!disabled"])
        self.undo_button.state(["disabled"])
        self.schedule()

    def cleanup(self, event):
        if event.widget is self:
            for task in (self.render_task, self.poll_task):
                if task is not None:
                    self.after_cancel(task)

    def crop_box(self):
        return resolve_crop(*self.image_size, *self.frame_size, self.state)

    def normalize(self):
        self.state = normalize_view(self.state)
        box = self.crop_box()
        self.state["focus"] = [(box[0] + box[2]) / (2 * self.image_size[0]),
                               (box[1] + box[3]) / (2 * self.image_size[1])]
        self.syncing = True
        self.zoom_value.set(self.state["zoom"])
        self.zoom_text.set(f"{self.state['zoom'] * 100:.0f}")
        self.syncing = False

    def schedule(self):
        if self.render_task is not None:
            self.after_cancel(self.render_task)
        self.render_task = self.after(16, self.paint)

    def paint(self):
        self.render_task = None
        if self.image is None:
            return
        width, height = max(2, self.canvas.winfo_width()), max(2, self.canvas.winfo_height())
        if min(width, height) < 72:
            return
        ratio = self.frame_size[0] / self.frame_size[1]
        frame_w = min(width - 56, (height - 56) * ratio)
        frame_h = frame_w / ratio
        left, top = (width - frame_w) / 2, (height - frame_h) / 2
        self.frame_display = (left, top, frame_w, frame_h)
        box = self.crop_box()
        self.display_scale = frame_w / (box[2] - box[0])
        thumb_scale_x = self.image.width / self.image_size[0]
        thumb_scale_y = self.image.height / self.image_size[1]
        transform = (thumb_scale_x / self.display_scale, 0,
                     (box[0] - left / self.display_scale) * thumb_scale_x,
                     0, thumb_scale_y / self.display_scale,
                     (box[1] - top / self.display_scale) * thumb_scale_y)
        pixels = self.image.transform((width, height), Image.Transform.AFFINE, transform,
                                      Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0))
        rendered = Image.new("RGBA", (width, height), (239, 243, 241, 255))
        checker = ImageDraw.Draw(rendered)
        cell = 14
        for y in range(0, height, cell):
            for x in range(0, width, cell):
                if (x // cell + y // cell) % 2:
                    checker.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(213, 223, 217, 255))
        rendered.alpha_composite(pixels)
        stencil = Image.new("L", (width, height), 0)
        if self.mask_image is None:
            ImageDraw.Draw(stencil).rectangle((round(left), round(top), round(left + frame_w), round(top + frame_h)), fill=255)
        else:
            stencil.paste(self.mask_image.resize((max(1, round(frame_w)), max(1, round(frame_h))), Image.Resampling.LANCZOS),
                          (round(left), round(top)))
        shade = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        shade.putalpha(ImageOps.invert(stencil).point(lambda value: round(value * 140 / 255)))
        rendered.alpha_composite(shade)
        border = ImageChops.subtract(stencil.filter(ImageFilter.MaxFilter(3)), stencil.filter(ImageFilter.MinFilter(3)))
        outline = Image.new("RGBA", (width, height), (104, 227, 166, 0))
        outline.putalpha(border)
        rendered.alpha_composite(outline)
        self.photo = ImageTk.PhotoImage(rendered, master=self)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.readout.set(f"原图 {self.image_size[0]} × {self.image_size[1]} px   ·   "
                         f"图框比例 {self.frame_size[0]:g} ∶ {self.frame_size[1]:g}   ·   "
                         f"取景 [{box[0]:.1f}, {box[1]:.1f}, {box[2]:.1f}, {box[3]:.1f}]" + self.preset_note)

    def commit(self):
        if self.image is None:
            return
        self.normalize()
        if self.history[-1] != self.state:
            self.history.append(copy.deepcopy(self.state))
            self.history = self.history[-35:]
        self.undo_button.state(["!disabled"] if len(self.history) > 1 else ["disabled"])

    def slider_changed(self, value):
        if self.syncing or self.image is None:
            return
        self.preset_note = ""
        self.state["zoom"] = min(8, max(.1, float(value)))
        self.normalize()
        self.schedule()

    def numeric_changed(self, _=None):
        if self.image is None:
            return
        try:
            value = float(self.zoom_text.get())
            if not 10 <= value <= 800:
                raise ValueError
        except ValueError:
            self.zoom_text.set(f"{self.state['zoom'] * 100:.0f}")
            self.readout.set("缩放请输入 10–800，100% 为居中填满，小于 100% 可留空。")
            return
        self.preset_note = ""
        self.state["zoom"] = value / 100
        self.normalize()
        self.commit()
        self.schedule()

    def wheel(self, event):
        if self.image is not None and event.delta:
            self.preset_note = ""
            self.state["zoom"] = min(8, max(.1, self.state["zoom"] * (1.10 if event.delta > 0 else 1 / 1.10)))
            self.normalize()
            self.commit()
            self.schedule()
        return "break"

    def drag_start(self, event):
        if self.image is not None and hasattr(self, "display_scale"):
            self.drag = (event.x, event.y, self.state["focus"][:])

    def drag_move(self, event):
        if self.drag is None:
            return
        x, y, focus = self.drag
        self.state["focus"] = [focus[0] - (event.x - x) / (self.display_scale * self.image_size[0]),
                               focus[1] - (event.y - y) / (self.display_scale * self.image_size[1])]
        self.normalize()
        self.schedule()

    def drag_end(self, _):
        if self.drag is not None:
            self.drag = None
            self.commit()

    def reset(self):
        if self.image is not None:
            self.preset_note = ""
            self.state = {"zoom": 1.0, "focus": [0.5, 0.5]}
            self.normalize()
            self.commit()
            self.schedule()

    def contain(self):
        if self.image is not None:
            self.state = {"zoom": contain_zoom(*self.image_size, *self.frame_size), "focus": [.5, .5]}
            self.normalize()
            box = self.crop_box()
            complete = box[0] <= .001 and box[1] <= .001 and box[2] >= self.image_size[0] - .001 and box[3] >= self.image_size[1] - .001
            self.preset_note = "" if complete else " · 原图比例超过 10% 缩放范围，请选择比例更接近的图片"
            self.commit()
            self.schedule()

    def undo(self):
        if len(self.history) > 1:
            self.preset_note = ""
            self.history.pop()
            self.state = copy.deepcopy(self.history[-1])
            self.normalize()
            self.undo_button.state(["!disabled"] if len(self.history) > 1 else ["disabled"])
            self.schedule()

    def open_original(self):
        open_source_preview(self, self.source, image=self.image, original_size=self.image_size)

    def save(self):
        if self.image is None:
            return
        self.numeric_changed()
        self.result = {**copy.deepcopy(self.state), "crop_box": list(self.crop_box())}
        if self.on_save is not None:
            self.on_save(self.result)
        self.destroy()


def open_source_preview(parent, source, *, image=None, original_size=None):
    return SourcePreview(parent, source, image=image, original_size=original_size)


class SourcePreview(tk.Toplevel):
    """View a source image inside the workbench without file associations."""

    def __init__(self, parent, source, *, image=None, original_size=None):
        super().__init__(parent)
        self.source = Path(source)
        self.title(f"原图预览 · {self.source.name}")
        self.transient(parent)
        self.previous_grab = self.grab_current()
        self.grab_set()
        scale = max(1, self.winfo_fpixels("1i") / 96)
        self.geometry(f"{min(round(1050 * scale), self.winfo_screenwidth() - 80)}x"
                      f"{min(round(780 * scale), self.winfo_screenheight() - 110)}")
        self.minsize(540, 400)
        self.image, self.original_size = image, original_size
        self.render_task = self.poll_task = None
        self.messages = queue.Queue()
        self.caption = tk.StringVar(value="正在载入原图…")
        area = ttk.Frame(self, padding=12)
        area.pack(fill="both", expand=True)
        ttk.Label(area, text=self.source.name, font=(FONT, 12, "bold")).pack(anchor="w")
        ttk.Label(area, textvariable=self.caption, font=(FONT, 9)).pack(anchor="w", pady=(4, 8))
        self.canvas = tk.Canvas(area, background="#e2e9e3", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self.schedule())
        buttons = ttk.Frame(area)
        buttons.pack(fill="x", pady=(9, 0))
        ttk.Button(buttons, text="复制原图路径", command=self.copy_path).pack(side="left")
        ttk.Button(buttons, text="关闭", command=self.destroy).pack(side="right")
        self.bind("<Escape>", lambda _: self.destroy())
        self.bind("<Destroy>", self.cleanup, add="+")
        if self.image is not None:
            self.show_dimensions()
            self.schedule()
            return

        def load():
            try:
                with Image.open(self.source) as original:
                    oriented = ImageOps.exif_transpose(original)
                    size = oriented.size
                    oriented.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
                    loaded = oriented.convert("RGBA")
                self.messages.put((loaded, size, None))
            except (OSError, ValueError, Image.DecompressionBombError) as error:
                self.messages.put((None, None, str(error)))

        threading.Thread(target=load, daemon=True).start()
        self.poll_task = self.after(40, self.loaded)

    def loaded(self):
        self.poll_task = None
        try:
            image, size, error = self.messages.get_nowait()
        except queue.Empty:
            self.poll_task = self.after(40, self.loaded)
            return
        if error:
            self.caption.set(f"原图无法打开 · {error}")
            return
        self.image, self.original_size = image, size
        self.show_dimensions()
        self.schedule()

    def show_dimensions(self):
        size = self.original_size or self.image.size
        self.caption.set(f"{size[0]} × {size[1]} px · 完整适应窗口")

    def schedule(self):
        if self.render_task is not None:
            self.after_cancel(self.render_task)
        self.render_task = self.after(30, self.paint)

    def paint(self):
        self.render_task = None
        if self.image is None:
            return
        width, height = max(1, self.canvas.winfo_width() - 30), max(1, self.canvas.winfo_height() - 30)
        image = ImageOps.contain(self.image, (width, height), Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image, master=self)
        self.canvas.delete("all")
        self.canvas.create_image(self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2, image=self.photo)

    def copy_path(self):
        self.clipboard_clear()
        self.clipboard_append(str(self.source))

    def cleanup(self, event):
        if event.widget is self:
            for task in (self.render_task, self.poll_task):
                if task is not None:
                    self.after_cancel(task)
            if self.previous_grab is not None and self.previous_grab.winfo_exists():
                self.previous_grab.grab_set()
