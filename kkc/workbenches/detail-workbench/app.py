"""Windows desktop interface for one-product Photoshop detail-page jobs."""

import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from crop_editor import open_source_preview
from live_preview import PreviewPane
from package_io import (PackageError, PackageSelectionRequired, load_package, save_package,
                        source_stamp)
from templates import UnsupportedTemplateError, import_template, list_templates, remove_template
from workbench import (EXTRA_IMAGE_LABELS, FIELDS, PRODUCT_ATTRIBUTE_FIELDS, ROOT, TABLE_NAMES, export_detail,
                       fit_table, image_entry, normalize_product_attributes, normalize_size_note, normalize_table,
                       preflight, quick_table, read_data, resolve_product_attributes)

BG = "#edf3ef"
PAPER = "#ffffff"
INK = "#172c25"
MUTED = "#4c655a"
GREEN = "#12624c"
PALE = "#e5f2e9"
FONT = "Microsoft YaHei UI"
IMAGE_FILTER = [("图片", "*.png *.jpg *.jpeg")]
DEMO = ROOT.parent / "work/KQ26169-psd/product_data.json"
PACKAGE_CACHE = ROOT.parent / "work/detail-workbench-packages"
APP_VERSION = "0.5.11"


def program_stamp():
    files = [*ROOT.glob("*.py"), *(ROOT / "engine").glob("*.jsx")]
    return max(path.stat().st_mtime_ns for path in files if path.is_file())


SOURCE_STAMP = program_stamp()


def feishu_handoff_prompt(link, row, folder):
    from feishu_import import parse_link

    parse_link(link)
    if not re.fullmatch(r"[0-9]{1,5}", str(row).strip()) or not 1 <= int(row) <= 20000:
        raise ValueError("视图行号请填写 1–20000，表头下面的第一条数据为第 1 行。")
    if not str(folder).strip():
        raise ValueError("请选择整理结果文件夹。")
    destination = Path(folder).expanduser().resolve()
    schema = {
        "info": {"名称": "", "货号": "", "尺码": "", "材质": ""},
        "colors": [], "size_table": {"headers": [], "rows": []}, "size_note": None,
        "quick_size": {"columns": [], "rows": [], "data": []}, "try_on": None,
        "assets": {"products": {}, "scenes": [], **dict.fromkeys(EXTRA_IMAGE_LABELS)},
        "source_note": f"{link} · 视图第 {int(row)} 行", "warnings": [],
    }
    return (
        "请使用已登录的浏览器，读取下方飞书多维表格在当前视图中的指定行，"
        "整理成详情页套版工作台可导入的本地资料。\n\n"
        f"飞书链接\n{link}\n视图行号\n{int(row)}（表头下面的第一条数据为第 1 行）\n"
        f"保存文件夹\n{destination}\n\n"
        "先核对当前视图、行号、款号和商品名称，再读取本行的商品字段与可访问附件。"
        "将尺码表、尺码快选及试穿资料核对后转成完整表格矩阵，保留空格、斜杠、小数和单位。"
        "缺失内容保留空值，并在 warnings 记录具体缺项。\n"
        "将本行能取得的商品图和模特图保存在此文件夹的素材子目录，"
        "保留原文件名。依据本行证据确认颜色及图位后，在 assets.products 中填写"
        "「色名: 相对图片路径」，在 assets.scenes 中按图位顺序填写最多四张模特图的相对路径。"
        "待确认的颜色或图位在 warnings 中说明。\n"
        "将完整尺码表附件按原文件名保存到原始附件/尺码表/，保留备注和图示。"
        "将尺码表备注原文单独录入顶层 size_note，保留单位和换行。未取得或无法确认时填 null，并在 warnings 说明。"
        "若本行有明确对应这款商品的尺码测量示意图，优先保存独立原图。若图示嵌在尺码表中，只截取完整图示和量尺标注，"
        "避开表格和备注。把示意图单独存为素材目录中的 PNG 或 JPG，在 assets.measurement 填它的相对路径。"
        "在 source_record.json 记录原附件路径、示意图路径和裁切范围（若裁切）。"
        "没有示意图或无法确认款式、清晰度或裁切边界时，assets.measurement 留 null，在 warnings 写明原因，保留可取得的原附件。\n"
        "保存 product_data.json，结构如下。assets 路径相对该 JSON，source_note 保留来源链接与行号。"
        "保存后逐个检查 assets 中引用的文件确实存在，并给我完整资料文件夹或 ZIP，"
        "同时给出 JSON 的本地链接和仍需核对的事项，我会在工作台导入。\n\n"
        + json.dumps(schema, ensure_ascii=False, indent=2)
    )


class Workbench:
    def __init__(self, root):
        self.root = root
        root.title(f"详情页套版工作台 · v{APP_VERSION}")
        self.instance_handle = None
        self.other_instance = False
        if os.name == "nt":
            self.instance_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            self.instance_kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
            self.instance_kernel.CreateMutexW.restype = ctypes.c_void_p
            self.instance_kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            self.instance_handle = self.instance_kernel.CreateMutexW(None, False, "Local\\KocoDetailWorkbench.App")
            self.other_instance = bool(self.instance_handle and ctypes.get_last_error() == 183)
        scale = max(1.0, root.winfo_fpixels("1i") / 96)
        width = min(round(1370 * scale), root.winfo_screenwidth() - 60)
        height = min(round(825 * scale), root.winfo_screenheight() - 85)
        root.geometry(f"{width}x{height}")
        root.minsize(min(1050, width), min(round(700 * scale), height))
        root.configure(bg=BG)
        self.data = {}
        self.source = ""
        self.attachments = []
        self.products = {}
        self.scenes = [None] * 4
        self.extra_images = dict.fromkeys(EXTRA_IMAGE_LABELS)
        self.size_note = None
        self.views = {}
        self.hidden_decorations = {}
        self.package = None
        self.source_json = None
        self.package_root = None
        self.missing_assets = []
        self.version_task = None
        self.unsaved = False
        self.bound_colors = []
        self.rename_origins = {}
        self.binding_notice = ""
        self.slots = []
        self.job = None
        self.result = None
        self.busy = False
        self.ps_wait_started = None
        self.ps_wait_hint_shown = False
        self.events = queue.Queue()
        self.tables = {}
        self.edited_tables = set()
        self.templates = list_templates()
        self.template = next(iter(self.templates), None)
        self.loading = False
        self.pending_preview = None
        self.pending_validation = None
        self.validation_revision = 0
        self.last_displayed_slot = None
        self.refresh_poll_task = None
        self.refresh_pending = False
        self.cell_editor = None
        self.finish_cell = None
        self.fields = {name: tk.StringVar() for name in FIELDS}
        self.colors = tk.StringVar()
        self.output = tk.StringVar(value=str(ROOT.parent / "outputs" / "详情页工作台"))
        self.status = tk.StringVar(value="等待导入商品资料")
        self.configure_style()
        self.build()
        for value in [*self.fields.values(), self.colors]:
            value.trace_add("write", self.changed)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_task = self.root.after(150, self.handle_events)
        self.root.bind("<Destroy>", self.on_destroy, add="+")
        self.queue_preview()
        self.update_edit_controls()
        self.toggle_export()
        self.version_task = self.root.after(2500, self.check_source_version)

    def configure_style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background=PAPER)
        style.configure("Outer.TFrame", background=BG)
        style.configure("TLabel", background=PAPER, foreground=INK, font=(FONT, 10))
        style.configure("Muted.TLabel", background=PAPER, foreground=MUTED, font=(FONT, 9))
        style.configure("H2.TLabel", background=PAPER, foreground=INK, font=(FONT, 15, "bold"))
        style.configure("TButton", padding=(11, 8), font=(FONT, 10), foreground=INK, background=PALE)
        style.map("TButton", background=[("active", "#d5e9dc")])
        style.configure("Primary.TButton", foreground=PAPER, background=GREEN, font=(FONT, 11, "bold"))
        style.map("Primary.TButton", foreground=[("disabled", "#6c8277")],
                  background=[("disabled", "#dce8df"), ("active", "#0b4e3c")])
        style.configure("TCheckbutton", background=PAPER, foreground=INK, font=(FONT, 10))
        style.configure("TEntry", padding=6, font=(FONT, 10))
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure("TNotebook.Tab", background=PALE, padding=(16, 9), font=(FONT, 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", PAPER)], foreground=[("selected", GREEN)])
        style.configure("Treeview", rowheight=31, background=PAPER, fieldbackground=PAPER, font=(FONT, 10))
        style.configure("Treeview.Heading", background=PALE, foreground=INK, font=(FONT, 9, "bold"))
        style.map("Treeview", background=[("selected", "#d0e6d8")], foreground=[("selected", INK)])

    def build(self):
        header = tk.Frame(self.root, bg="#153e32", padx=24, pady=11)
        header.pack(fill="x")
        tk.Label(header, text="视觉部  /  商品设计工具", bg="#153e32", fg="#aee0c4", font=(FONT, 10)).pack(anchor="w")
        tk.Label(header, text="详情页套版工作台", bg="#153e32", fg=PAPER, font=(FONT, 21, "bold")).pack(anchor="w")
        tk.Label(header, text="商品资料与素材在左，页面随编辑在右更新",
                 bg="#153e32", fg="#d5eddd", font=(FONT, 10)).pack(anchor="w", pady=(4, 0))
        version_row = tk.Frame(header, bg="#153e32")
        version_row.pack(fill="x", pady=(3, 0))
        self.version_label = tk.Label(version_row, text=f"v{APP_VERSION} · 本次加载 {datetime.fromtimestamp(SOURCE_STAMP / 1e9):%m-%d %H:%M}",
                                      bg="#153e32", fg="#aee0c4", font=(FONT, 9))
        self.version_label.pack(side="left")
        self.refresh_button = ttk.Button(version_row, text="刷新工作台", command=self.refresh_application)
        self.refresh_button.pack(side="right")
        if self.other_instance:
            self.version_label.configure(text=f"v{APP_VERSION} · 已有其他工作台窗口，请核对正在操作的版本", fg="#ffe5a0")
        body = ttk.Frame(self.root, style="Outer.TFrame", padding=(14, 12))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(body, padding=11)
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        sidebar.columnconfigure(0, minsize=216)
        ttk.Label(sidebar, text="01  商品来源", font=(FONT, 11, "bold")).grid(sticky="w", pady=(0, 6))
        self.open_button = ttk.Button(sidebar, text="导入资料包 / JSON", command=self.import_data)
        self.open_button.grid(sticky="ew")
        self.data_label = ttk.Label(sidebar, text="等待导入商品资料", style="Muted.TLabel", wraplength=215)
        self.data_label.grid(sticky="w", pady=(6, 0))
        self.source_button = ttk.Button(sidebar, text="资料路径与缺图检查", command=self.show_source_details)
        self.source_button.grid(sticky="ew", pady=(5, 0))
        self.save_button = ttk.Button(sidebar, text="保存当前资料包", command=self.save_current_package)
        self.save_button.grid(sticky="ew", pady=(4, 0))
        ttk.Separator(sidebar).grid(sticky="ew", pady=10)
        ttk.Label(sidebar, text="02  母版", font=(FONT, 11, "bold")).grid(sticky="w")
        self.template_combo = ttk.Combobox(sidebar, state="readonly" if self.templates else "disabled", width=21,
                                           values=[item.label for item in self.templates])
        if self.template:
            self.template_combo.current(0)
        self.template_combo.grid(sticky="ew", pady=(5, 4))
        self.template_combo.bind("<<ComboboxSelected>>", self.choose_template)
        self.template_label = ttk.Label(sidebar, text=self.template_summary(),
                                        style="Muted.TLabel", wraplength=215)
        self.template_label.grid(sticky="w", pady=(0, 5))
        self.upload_button = ttk.Button(sidebar, text="上传本地母版", command=self.upload_template)
        self.upload_button.grid(sticky="ew")
        self.delete_template_button = ttk.Button(sidebar, text="删除模板", command=self.delete_template)
        self.delete_template_button.grid(sticky="ew", pady=(4, 0))
        ttk.Label(sidebar, text="使用保留套版图位的 PSD / PSB。", style="Muted.TLabel",
                  wraplength=215).grid(sticky="w", pady=(4, 0))
        ttk.Separator(sidebar).grid(sticky="ew", pady=10)
        ttk.Label(sidebar, text="03  输出", font=(FONT, 11, "bold")).grid(sticky="w")
        self.output_button = ttk.Button(sidebar, text="选择输出文件夹", command=self.choose_output)
        self.output_button.grid(sticky="ew", pady=(5, 0))
        self.output_label = ttk.Label(sidebar, text="", wraplength=215, style="Muted.TLabel")
        self.output_label.grid(sticky="w", pady=(5, 0))
        self.update_output_label()
        ttk.Separator(sidebar).grid(sticky="ew", pady=10)
        self.demo_button = ttk.Button(sidebar, text="试用马甲样例", command=self.load_demo)
        self.demo_button.grid(sticky="ew")
        if not DEMO.is_file():
            self.demo_button.state(["disabled"])
        ttk.Label(sidebar, text="载入现成资料与配图，方便试走流程。", style="Muted.TLabel",
                  wraplength=215).grid(sticky="w", pady=(5, 0))

        split = ttk.Panedwindow(body, orient="horizontal")
        split.grid(row=0, column=1, sticky="nsew")
        edit = ttk.Frame(split, style="Outer.TFrame", padding=(0, 0, 8, 0))
        self.preview = PreviewPane(split, on_slot_select=self.select_preview_slot,
                                   on_add_image=self.add_preview_image,
                                   on_repair_original=self.repair_template_reference,
                                   on_decoration_change=self.change_decoration)
        split.add(edit, weight=3)
        split.add(self.preview, weight=2)
        # The first timer can run before Tk has assigned the pane its width,
        # especially when a product package is loaded during startup.
        # Place the sash after the real geometry arrives so the editor stays
        # visible regardless of disk or preview-loading speed.
        initial_split = {"placed": False}
        def place_initial_split(_=None):
            if not initial_split["placed"] and split.winfo_width() > 400:
                initial_split["placed"] = True
                split.sashpos(0, round(split.winfo_width() * 0.62))
        split.bind("<Configure>", place_initial_split)
        self.root.after_idle(place_initial_split)
        self.tabs = ttk.Notebook(edit)
        self.tabs.pack(fill="both", expand=True)
        self.details = ttk.Frame(self.tabs, padding=13)
        self.images = ttk.Frame(self.tabs, padding=13)
        self.review = ttk.Frame(self.tabs, padding=13)
        for tab, name in ((self.details, "商品资料"), (self.images, "图片匹配"), (self.review, "检查结果")):
            self.tabs.add(tab, text=name)
        self.build_details()
        self.build_images()
        self.build_review()

        actions = ttk.Frame(self.root, padding=(14, 8))
        actions.pack(fill="x", side="bottom")
        self.export_button = ttk.Button(actions, text="生成可编辑文件", style="Primary.TButton", command=self.export)
        self.export_button.pack(side="right")
        self.result_button = ttk.Button(actions, text="打开成品文件夹", command=lambda: self.open_result(0))
        self.result_button.pack(side="right", padx=(0, 8))
        self.result_button.state(["disabled"])
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=90)
        ttk.Label(actions, textvariable=self.status, wraplength=560, style="Muted.TLabel").pack(side="left", padx=(0, 8))

    def build_details(self):
        ttk.Label(self.details, text="商品资料", style="H2.TLabel").pack(anchor="w")
        self.detail_hint = ttk.Label(self.details, text="先从左侧导入商品资料，或点击「试用马甲样例」。",
                                     style="Muted.TLabel", wraplength=430)
        self.detail_hint.pack(anchor="w", pady=(5, 10))
        form = ttk.Frame(self.details)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        self.entries = []
        for row, (field, value) in enumerate(self.fields.items()):
            ttk.Label(form, text=field).grid(row=row, column=0, sticky="w", padx=(0, 15), pady=3)
            entry = ttk.Entry(form, textvariable=value)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            entry.bind("<FocusIn>", lambda _, section="hero" if field in {"名称", "货号"} else "product":
                       self.preview.focus_section(section))
            self.entries.append(entry)
        ttk.Label(form, text="颜色").grid(row=4, column=0, sticky="w", pady=3)
        color_entry = ttk.Entry(form, textvariable=self.colors)
        color_entry.grid(row=4, column=1, sticky="ew", pady=3)
        color_entry.bind("<FocusIn>", lambda _: self.preview.focus_section("product"))
        self.entries.append(color_entry)
        ttk.Label(form, text="用顿号或逗号隔开，最多八色。", style="Muted.TLabel").grid(row=5, column=1, sticky="w")
        self.attributes_button = ttk.Button(form, text="编辑 STEP1 属性", command=self.edit_product_attributes)
        self.attributes_button.grid(row=6, column=1, sticky="w", pady=(5, 0))
        table_bar = ttk.Frame(self.details)
        table_bar.pack(fill="x", pady=(9, 5))
        ttk.Label(table_bar, text="双击单元格修改", style="Muted.TLabel").pack(side="left")
        self.edit_table_button = ttk.Button(table_bar, text="粘贴 / 编辑整表", command=self.edit_table)
        self.edit_table_button.pack(side="right")
        self.size_note_button = ttk.Button(table_bar, text="编辑尺码备注", command=self.edit_size_note)
        self.size_note_button.pack(side="right", padx=(0, 7))
        self.table_tabs = ttk.Notebook(self.details)
        self.table_tabs.pack(fill="both", expand=True, pady=(8, 0))
        self.populate_tables({})

    def edit_product_attributes(self):
        if self.busy or not self.source:
            return
        try:
            profile = self.template.profile() if self.template else {}
        except (OSError, ValueError) as error:
            messagebox.showinfo("STEP1 属性", str(error), parent=self.root)
            return
        binding = profile.get("product_attributes")
        if not binding:
            messagebox.showinfo("STEP1 属性", "当前母版没有可编辑的版型、触感、厚度和弹性组件。", parent=self.root)
            return
        original = self.data.get("product_attributes")
        defaults = resolve_product_attributes(profile, {})
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑 STEP1 属性")
        dialog.transient(self.root)
        dialog.grab_set()
        area = ttk.Frame(dialog, padding=16)
        area.pack(fill="both", expand=True)
        ttk.Label(area, text="留空时使用母版示例值。请按该款商品的实际属性填写。").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        entries = {}
        for row, field in enumerate(PRODUCT_ATTRIBUTE_FIELDS, 1):
            value = original.get(field, "") if isinstance(original, dict) else ""
            entries[field] = tk.StringVar(value=value if isinstance(value, str) else "")
            ttk.Label(area, text=field).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
            if field == "版型":
                options = [item["value"] for item in binding["fit"]["options"]]
                entry = ttk.Combobox(area, textvariable=entries[field], values=["", *options], state="readonly", width=16)
            else:
                entry = ttk.Entry(area, textvariable=entries[field], width=18)
            entry.grid(row=row, column=1, sticky="ew")
            ttk.Label(area, text=f"母版：{defaults[field]}", style="Muted.TLabel").grid(
                row=row, column=2, sticky="w", padx=(12, 0))
        error = ttk.Label(area, foreground="#9c3d2a", wraplength=380)
        error.grid(row=5, column=0, columnspan=3, sticky="w", pady=(5, 0))
        actions = ttk.Frame(area)
        actions.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(8, 0))

        def apply(use_template=False):
            try:
                values = {} if use_template else normalize_product_attributes(
                    {field: variable.get() for field, variable in entries.items()})
            except ValueError as problem:
                error.configure(text=str(problem))
                return
            dialog.destroy()
            if values != (original or {}):
                if values:
                    self.data["product_attributes"] = values
                else:
                    self.data.pop("product_attributes", None)
                self.invalidate()
                self.sync_preview()
                self.preview.focus_section("attributes", reveal=True)

        ttk.Button(actions, text="沿用母版", command=lambda: apply(True)).pack(side="left")
        ttk.Button(actions, text="应用", command=apply, style="Primary.TButton").pack(side="right")
        ttk.Button(actions, text="取消", command=dialog.destroy).pack(side="right", padx=(0, 8))
        dialog.bind("<Escape>", lambda _: dialog.destroy())

    def edit_size_note(self):
        if self.busy or not self.source:
            return
        try:
            profile = self.template.profile() if self.template else None
            note = (profile or {}).get("size_note") or {}
        except (OSError, ValueError):
            note = {}
        original = note.get("text", "")
        shown = original if self.size_note is None else self.size_note
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑尺码备注")
        dialog.transient(self.root)
        dialog.grab_set()
        area = ttk.Frame(dialog, padding=16)
        area.pack(fill="both", expand=True)
        source = "当前显示母版备注。" if self.size_note is None and note else "当前显示商品备注。"
        if not self.template:
            source = "尺码备注会随资料包保存。上传母版后可检查它的显示位置。"
        elif not note:
            source = "当前母版未识别到尺码备注区，编辑内容会随资料包保存。"
        ttk.Label(area, text=f"{source} 支持换行，最多 300 字。", wraplength=490).pack(anchor="w", pady=(0, 8))
        editor = tk.Text(area, height=6, width=56, wrap="word", font=(FONT, 10), padx=8, pady=6)
        editor.pack(fill="both", expand=True)
        editor.insert("1.0", shown)
        editor.focus_set()
        error = ttk.Label(area, foreground="#9c3d2a", wraplength=490)
        error.pack(anchor="w", pady=(5, 0))
        actions = ttk.Frame(area)
        actions.pack(fill="x", pady=(8, 0))

        def apply(use_template=False):
            try:
                value = None if use_template else normalize_size_note(editor.get("1.0", "end-1c"))
            except ValueError as problem:
                error.configure(text=str(problem))
                return
            if self.size_note is None and value == shown:
                value = None
            dialog.destroy()
            if value != self.size_note:
                self.size_note = value
                self.invalidate()
                self.sync_preview()
                self.preview.focus_section("size_note" if note else "sizes", reveal=True)

        ttk.Button(actions, text="沿用母版备注", command=lambda: apply(True)).pack(side="left")
        ttk.Button(actions, text="应用", command=apply, style="Primary.TButton").pack(side="right")
        ttk.Button(actions, text="取消", command=dialog.destroy).pack(side="right", padx=(0, 8))
        dialog.bind("<Escape>", lambda _: dialog.destroy())

    def populate_tables(self, tables):
        for child in self.table_tabs.winfo_children():
            child.destroy()
        for name in TABLE_NAMES:
            container = ttk.Frame(self.table_tabs, padding=8)
            self.table_tabs.add(container, text=name)
            matrix = tables.get(name)
            if not matrix:
                optional = name == "试穿报告"
                message = "选填，补充后会显示试穿报告。" if optional else "待补齐，点击上方「粘贴 / 编辑整表」。"
                ttk.Label(container, text=message if self.source else "导入商品后显示表格。",
                          style="Muted.TLabel").pack(anchor="w", pady=12)
                continue
            ids = list(map(str, range(len(matrix[0]))))
            tree = ttk.Treeview(container, columns=ids, show="headings", selectmode="browse")
            for column, label in zip(ids, matrix[0]):
                tree.heading(column, text=label)
                tree.column(column, width=88, minwidth=60, anchor="center")
            for row in matrix[1:]:
                tree.insert("", "end", values=row)
            ybar = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
            xbar = ttk.Scrollbar(container, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
            container.columnconfigure(0, weight=1)
            container.rowconfigure(0, weight=1)
            tree.grid(sticky="nsew")
            ybar.grid(row=0, column=1, sticky="ns")
            xbar.grid(row=1, column=0, sticky="ew")
            tree.bind("<Double-1>", lambda event, table=name: self.edit_cell(event, table))
        self.apply_template_capabilities()

    def apply_template_capabilities(self, profile=None):
        if profile is None:
            try:
                profile = self.template.profile() if self.template else {}
            except (OSError, ValueError):
                profile = {}
        bindings = profile.get("fields", {})
        missing = [name for name in self.fields if bindings and name not in bindings]
        for name, entry in zip(self.fields, self.entries):
            entry.state(["readonly"] if name in missing else ["!readonly"])
        if profile and not profile.get("product_attributes"):
            self.attributes_button.grid_remove()
        else:
            self.attributes_button.grid()
        modules = profile.get("modules", [])
        modules = modules.values() if isinstance(modules, dict) else modules
        tables = {module["table"]["key"] for module in modules if module.get("table")}
        for index, name in enumerate(TABLE_NAMES):
            self.table_tabs.tab(index, state="normal" if not profile or name in tables else "hidden")
        hint = "修改字段、颜色和表格，右侧立即显示草稿。" if self.source else "先从左侧导入商品资料，或点击「试用马甲样例」。"
        if missing:
            hint = f"此母版没有{'、'.join(missing)}字段，已有资料仍随资料包保存。 " + hint
        self.detail_hint.configure(text=hint)

    def edit_cell(self, event, name):
        tree = event.widget
        row, column = tree.identify_row(event.y), tree.identify_column(event.x)
        if self.busy or tree.identify_region(event.x, event.y) != "cell" or not row or not column:
            return
        self.open_cell(tree, name, row, column)

    def open_cell(self, tree, name, row, column):
        if self.finish_cell:
            self.finish_cell(True)
        index = int(column[1:]) - 1
        row_index = tree.index(row) + 1
        tree.see(row)
        box = tree.bbox(row, column)
        if not box:
            return
        x, y, width, height = box
        entry = ttk.Entry(tree)
        entry.insert(0, self.tables[name][row_index][index])
        entry.place(x=x, y=y, width=width, height=height)
        entry.focus_set()
        entry.selection_range(0, "end")
        self.cell_editor = entry
        self.preview.focus_section("sizes")

        def finish(save):
            if self.cell_editor is not entry:
                return
            self.cell_editor = None
            self.finish_cell = None
            value = entry.get().strip()
            entry.destroy()
            if save and value != self.tables[name][row_index][index]:
                self.tables[name][row_index][index] = value
                tree.set(row, column, value)
                self.edited_tables.add(name)
                self.invalidate()

        def advance(step):
            finish(True)
            columns = len(self.tables[name][0])
            position = (row_index - 1) * columns + index + step
            if 0 <= position < (len(self.tables[name]) - 1) * columns:
                next_row, next_column = divmod(position, columns)
                identifier = tree.get_children()[next_row]
                self.root.after_idle(lambda: self.open_cell(tree, name, identifier, f"#{next_column + 1}"))
            else:
                tree.focus_set()
            return "break"

        entry.bind("<Return>", lambda _: finish(True))
        entry.bind("<Tab>", lambda _: advance(1))
        entry.bind("<Shift-Tab>", lambda _: advance(-1))
        entry.bind("<FocusOut>", lambda _: finish(True))
        entry.bind("<Escape>", lambda _: finish(False))
        self.finish_cell = finish

    def edit_table(self):
        if self.busy or not self.source:
            return
        index = self.table_tabs.index("current")
        name = TABLE_NAMES[index]
        dialog = tk.Toplevel(self.root)
        dialog.title(f"编辑 {name}")
        dialog.transient(self.root)
        dialog.grab_set()
        area = ttk.Frame(dialog, padding=14)
        area.pack(fill="both", expand=True)
        self.preview.focus_section("sizes")
        ttk.Label(area, text="从表格复制后直接粘贴，第一行是表头，列之间用 Tab 分隔。",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 8))
        grid = ttk.Frame(area)
        grid.pack(fill="both", expand=True)
        grid.rowconfigure(0, weight=1)
        grid.columnconfigure(0, weight=1)
        editor = tk.Text(grid, width=65, height=13, wrap="none", font=(FONT, 10), undo=True)
        ybar = ttk.Scrollbar(grid, orient="vertical", command=editor.yview)
        xbar = ttk.Scrollbar(grid, orient="horizontal", command=editor.xview)
        editor.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        editor.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        default_headers = (("尺码", "衣长", "胸围"), ("身高/体重", "15-20", "20-25"),
                           ("用户试穿", "身高", "体重", "胸围", "腰围", "臀围", "试穿码数", "试穿反馈"))
        editor.insert("1.0", "\n".join("\t".join(row) for row in self.tables.get(name, [default_headers[index]])))

        def save():
            lines = [line.split("\t") for line in editor.get("1.0", "end-1c").splitlines() if line.strip()]
            if not lines and index == 2:
                self.tables.pop(name, None)
            else:
                try:
                    matrix = fit_table({"headers": lines[0], "rows": lines[1:]}) if index == 2 else normalize_table(lines[0], lines[1:])
                    if index == 1:
                        matrix[0][0] = "身高/体重"
                    self.tables[name] = matrix
                except (IndexError, ValueError) as error:
                    messagebox.showerror("表格格式有误", str(error) if lines else "需要表头及数据。", parent=dialog)
                    return
            self.edited_tables.add(name)
            self.populate_tables(self.tables)
            self.table_tabs.select(index)
            self.invalidate()
            dialog.destroy()

        ttk.Button(area, text="应用到当前商品", style="Primary.TButton", command=save).pack(anchor="e", pady=(10, 0))
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        editor.focus_set()

    def build_images(self):
        ttk.Label(self.images, text="给每个位置确认一张图", style="H2.TLabel").pack(anchor="w")
        ttk.Label(self.images, text="商品按色名绑定透明 PNG。场景和模特照片按图框自动等比填满、居中裁切。",
                  style="Muted.TLabel", wraplength=610).pack(anchor="w", pady=(5, 12))
        self.image_summary = ttk.Label(self.images, text="导入商品后按颜色配置图片。", style="Muted.TLabel")
        self.image_summary.pack(anchor="w", pady=(0, 7))
        slot_frame = ttk.Frame(self.images)
        slot_frame.pack(fill="x")
        self.slot_tree = ttk.Treeview(slot_frame, columns=("slot", "file"), show="headings", height=8, selectmode="browse")
        self.slot_tree.heading("slot", text="母版位置")
        self.slot_tree.heading("file", text="已绑定的源文件")
        self.slot_tree.column("slot", width=195, stretch=False)
        self.slot_tree.column("file", width=300)
        slot_scroll = ttk.Scrollbar(slot_frame, orient="vertical", command=self.slot_tree.yview)
        self.slot_tree.configure(yscrollcommand=slot_scroll.set)
        slot_scroll.pack(side="right", fill="y")
        self.slot_tree.pack(side="left", fill="x", expand=True)
        self.slot_tree.bind("<<TreeviewSelect>>", self.slot_selection_changed)
        self.slot_tree.bind("<Double-1>", lambda _: self.choose_image())
        buttons = ttk.Frame(self.images)
        buttons.pack(fill="x", pady=8)
        self.pick_button = ttk.Button(buttons, text="选择 / 替换图片", command=self.choose_image)
        self.pick_button.pack(side="left", padx=(0, 6))
        self.clear_button = ttk.Button(buttons, text="清除所选", command=self.clear_image)
        self.clear_button.pack(side="left")
        self.original_button = ttk.Button(buttons, text="打开原图", command=self.open_original)
        self.original_button.pack(side="left", padx=(6, 0))
        self.slot_path = ttk.Label(self.images, text="点击上方位置，查看图片及来源。", wraplength=620, style="Muted.TLabel")
        self.slot_path.pack(fill="x", pady=(0, 8))
        ttk.Label(self.images, text="选中图位后，右侧显示对应位置。双击列表可直接换图。",
                  wraplength=480, style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

    def build_review(self):
        ttk.Label(self.review, text="导出前核对", style="H2.TLabel").pack(anchor="w")
        ttk.Label(self.review, text="检查资料、表格和素材。点击「生成可编辑文件」时也会自动执行检查。",
                  style="Muted.TLabel").pack(anchor="w", pady=(5, 12))
        review_body = ttk.Frame(self.review)
        review_body.pack(fill="both", expand=True)
        self.review_log = tk.Text(review_body, bg="#f4f8f5", fg=INK, font=(FONT, 10), relief="flat",
                                  padx=12, pady=12, wrap="word", state="disabled")
        bar = ttk.Scrollbar(review_body, orient="vertical", command=self.review_log.yview)
        self.review_log.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.review_log.pack(side="left", fill="both", expand=True)
        navigation = ttk.Frame(self.review)
        navigation.pack(fill="x", pady=(8, 0))
        self.fix_data_button = ttk.Button(navigation, text="去补资料 / 表格", command=lambda: self.tabs.select(self.details))
        self.fix_data_button.pack(side="left", padx=(0, 6))
        self.fix_images_button = ttk.Button(navigation, text="去匹配图片", command=lambda: self.tabs.select(self.images))
        self.fix_images_button.pack(side="left")
        self.review_text("导入资料后自动检查；点击「生成可编辑文件」时再次核对最新资料。")

    def review_text(self, content):
        self.review_log.configure(state="normal")
        self.review_log.delete("1.0", "end")
        self.review_log.insert("1.0", content)
        self.review_log.configure(state="disabled")

    def invalidate(self):
        self.validation_revision += 1
        self.job = None
        self.toggle_export()
        if self.result:
            self.result_button.configure(text="打开上次成品")
        if self.source and not self.busy:
            self.unsaved = True
            self.status.set("草稿已更新 · 点击生成会自动检查")
            self.review_text("配置已变更。可直接点击生成，工作台会自动重新检查。")
        self.queue_preview()

    def changed(self, *_):
        if not self.loading:
            self.invalidate()

    def color_names(self):
        return [part.strip() for part in re.split(r"[,，、/]+", self.colors.get()) if part.strip()]

    def queue_preview(self):
        if self.pending_preview is not None:
            self.root.after_cancel(self.pending_preview)
        self.pending_preview = self.root.after(100, self.sync_preview)

    def queue_validation(self):
        if self.pending_validation is not None:
            self.root.after_cancel(self.pending_validation)
        self.pending_validation = self.root.after(350, self.validate_import)

    def validate_import(self):
        """Check an imported snapshot in the background while editing stays available."""
        self.pending_validation = None
        if not self.source or self.busy:
            return
        if self.template is None:
            self.review_text("商品资料已导入。上传本地母版后可检查版式和图位。")
            return
        self.flush_pending_sync()
        revision = self.validation_revision
        data = json.loads(json.dumps(self.current_data()))
        products, template = dict(self.products), self.template
        scenes = list(self.scenes)
        while scenes and scenes[-1] is None:
            scenes.pop()
        views = {}
        extra = dict(self.extra_images)
        def worker():
            try:
                result = preflight(data, products, scenes, template=template, views=views, extra_images=extra)
                self.events.put(("validation", (revision, result, None)))
            except Exception as error:
                self.events.put(("validation", (revision, None, str(error))))
        threading.Thread(target=worker, daemon=True).start()

    def flush_pending_sync(self):
        if self.pending_preview is not None:
            self.root.after_cancel(self.pending_preview)
            self.pending_preview = None
            self.sync_preview()
        elif self.color_names() != self.bound_colors:
            self.sync_preview()

    def confirm_data_replace(self, apply):
        if self.finish_cell:
            self.finish_cell(True)
        self.flush_pending_sync()
        if self.unsaved and self.source:
            answer = messagebox.askyesnocancel("保存当前商品调整", "当前商品资料或配图尚未保存。是否先保存，再载入新资料？", parent=self.root)
            if answer is True:
                self.save_current_package(on_saved=apply)
                return False
            if answer is None:
                return False
        apply()
        return True

    def sync_preview(self):
        self.pending_preview = None
        colors = self.color_names()
        if colors != self.bound_colors:
            changed = [index for index, pair in enumerate(zip(self.bound_colors, colors)) if pair[0] != pair[1]]
            if len(colors) == len(self.bound_colors) and len(changed) == 1:
                index = changed[0]
                old, new = self.bound_colors[index], colors[index]
                if old not in colors and new not in self.bound_colors and self.products.get(old):
                    self.products[new] = self.products.pop(old)
                    origin = self.rename_origins.pop(old, old)
                    self.rename_origins[new] = origin
                    self.binding_notice = f"已将「{origin}」的色图绑定移到「{new}」，请核对当前色名与图片。"
                    self.status.set(self.binding_notice)
            self.bound_colors = list(colors)
        template = self.template
        try:
            profile = template.profile() if template else None
        except (OSError, ValueError):
            profile = None
        slots = [("product", color) for color in dict.fromkeys(colors)]
        if self.source and profile:
            view_slots = profile.get("view_slots", {})
            if "hero" in view_slots:
                slots.append(("hero", "hero"))
            slots += [("scene", i) for i in range(4) if f"scene_{i + 1}" in view_slots]
            if "brand" in view_slots:
                slots.append(("brand", "brand"))
            if "measurement" in view_slots:
                slots.append(("measurement", "measurement"))
        if slots != self.slots:
            self.slots = slots
            self.refresh_slots()
        try:
            size_note = normalize_size_note(self.size_note)
        except ValueError:
            size_note = None
        self.preview.render(
            {**{key: value.get() for key, value in self.fields.items()}, "尺码备注": size_note,
             "STEP1 属性": self.data.get("product_attributes")}, colors, self.products, self.scenes,
            self.tables, template.label if template else "待上传母版", template_image=getattr(template, "preview", None),
            footer_image=getattr(template, "footer_preview", None),
            layout=getattr(template, "layout", "workbench"),
            template_profile=profile,
            template_full_image=getattr(template, "original_preview", None),
            template_original_info=template.original_preview_info() if template else None,
            views={}, extra_images=self.extra_images,
            hidden_decorations=self.hidden_decorations.get(template.id, []) if template else [],
        )

    def handoff_feishu(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("让 Codex 整理飞书资料")
        dialog.transient(self.root)
        dialog.grab_set()
        area = ttk.Frame(dialog, padding=16)
        area.pack(fill="both", expand=True)
        ttk.Label(area, text="用已登录的浏览器整理资料", style="H2.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(area, text="填好后复制任务，粘贴到 Codex。整理完成后，将 product_data.json 导入本工作台。",
                  style="Muted.TLabel", wraplength=650).pack(anchor="w", pady=(0, 12))
        form = ttk.Frame(area)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        link = tk.StringVar(value=getattr(self, "last_feishu_url", ""))
        row = tk.StringVar(value=getattr(self, "last_feishu_row", ""))
        folder = tk.StringVar(value=getattr(self, "last_handoff_folder", str(ROOT.parent / "work/飞书商品资料")))
        for index, (label, value) in enumerate((("多维表格链接", link), ("视图行号", row), ("整理结果文件夹", folder))):
            ttk.Label(form, text=label).grid(row=index, column=0, sticky="w", padx=(0, 10), pady=4)
            entry = ttk.Entry(form, textvariable=value, width=54)
            entry.grid(row=index, column=1, sticky="ew", pady=4)
            if index == 0:
                entry.focus_set()

        def choose_folder():
            selected = filedialog.askdirectory(title="选择资料整理结果文件夹", parent=dialog)
            if selected:
                folder.set(selected)

        ttk.Button(form, text="选择", command=choose_folder).grid(row=2, column=2, padx=(6, 0))
        ttk.Label(area, text="行号按链接中的视图显示顺序计算，表头下第一条数据为第 1 行。",
                  style="Muted.TLabel", wraplength=650).pack(anchor="w", pady=(5, 10))
        prompt = tk.Text(area, width=76, height=10, wrap="word", font=(FONT, 9), bg="#f4f8f5",
                         fg=INK, relief="flat", padx=10, pady=8)
        prompt.insert("1.0", "复制后，这里会显示完整任务，包含来源、行号、输出位置及工作台资料格式。")
        prompt.configure(state="disabled")
        prompt.pack(fill="both", expand=True)
        hint = ttk.Label(area, text="", style="Muted.TLabel", wraplength=650)
        hint.pack(anchor="w", pady=(9, 7))

        def copy_task():
            try:
                task = feishu_handoff_prompt(link.get().strip(), row.get().strip(), folder.get().strip())
            except (OSError, ValueError) as error:
                hint.configure(text=str(error), foreground="#9c3d2a")
                return
            self.last_feishu_url = link.get().strip()
            self.last_feishu_row = str(int(row.get()))
            self.last_handoff_folder = folder.get().strip()
            dialog.clipboard_clear()
            dialog.clipboard_append(task)
            prompt.configure(state="normal")
            prompt.delete("1.0", "end")
            prompt.insert("1.0", task)
            prompt.configure(state="disabled")
            hint.configure(text="已复制。请粘贴到 Codex，资料整理完成后点「导入整理结果」。", foreground=GREEN)

        def open_table():
            from feishu_import import parse_link

            try:
                parse_link(link.get().strip())
            except ValueError as error:
                hint.configure(text=str(error), foreground="#9c3d2a")
                return
            webbrowser.open(link.get().strip())

        def import_result():
            selected = filedialog.askopenfilename(title="选择已整理的 JSON 或 ZIP 资料包", parent=dialog,
                                                  initialdir=folder.get().strip() or None,
                                                  filetypes=[("商品资料包", "*.json *.zip")])
            if selected:
                dialog.destroy()
                self.import_package_path(selected)

        buttons = ttk.Frame(area)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="打开飞书表格", command=open_table).pack(side="left")
        ttk.Button(buttons, text="导入整理结果", command=import_result).pack(side="right")
        ttk.Button(buttons, text="复制任务给 Codex", style="Primary.TButton", command=copy_task).pack(side="right", padx=(0, 7))
        dialog.bind("<Escape>", lambda _: dialog.destroy())

    def upload_template(self):
        selected = filedialog.askopenfilename(title="选择 Photoshop 母版",
                                              filetypes=[("Photoshop 母版", "*.psb *.psd")])
        if selected:
            self.start_task(lambda: import_template(Path(selected), notify=lambda stage: self.events.put(("status", stage))),
                            "正在检查母版图层并准备预览…",
                            self.receive_template, "母版导入失败")

    def delete_template(self):
        selected = self.template
        if self.busy or not selected or selected.id == "builtin":
            return
        if not messagebox.askyesno(
                "删除模板", f"将「{selected.label}」移出工作台模板列表？\n原始 PSD / PSB 不受影响。",
                parent=self.root):
            return

        def removed(_):
            self.templates = list_templates()
            self.template = None
            self.template_combo.configure(values=[item.label for item in self.templates],
                                          state="readonly" if self.templates else "disabled")
            if self.templates:
                self.template_combo.current(0)
                self.choose_template()
            else:
                self.template_combo.set("")
                self.apply_template_capabilities({})
                self.template_label.configure(text=self.template_summary())
                self.invalidate()
                self.sync_preview()
                self.update_edit_controls()
            self.status.set(f"已删除模板 · {selected.label}")

        self.start_task(lambda: remove_template(selected), "正在移除模板…", removed, "删除模板失败")

    def receive_template(self, item):
        self.templates = list_templates()
        self.template_combo.configure(state="readonly", values=[entry.label for entry in self.templates])
        index = next(index for index, entry in enumerate(self.templates) if entry.id == item.id)
        self.template_combo.current(index)
        self.choose_template()
        self.status.set(f"已上传并选用 · {self.template.label}")
        notices = self.template.profile().get("import_warnings", [])
        if notices and not self.source:
            self.review_text("\n".join(f"母版说明 · {note}" for note in notices))

    def template_summary(self):
        if not self.template:
            return "尚无母版 · 请上传本地 PSD / PSB"
        width, height = self.template.dimensions
        summary = f"{self.template.label}\n{width} × {height:,} px"
        if self.template.source_dimensions != self.template.dimensions:
            summary += "\n已整理为套版母版，完整原稿见右侧母版版式"
        return summary

    def choose_template(self, _=None):
        index = self.template_combo.current()
        if index >= 0:
            self.template = self.templates[index]
            self.update_edit_controls()
            from templates import TemplateUpgradeRequired, upgrade_template

            try:
                profile = self.template.profile()
            except TemplateUpgradeRequired:
                selected = self.template
                self.start_task(lambda: upgrade_template(selected), "正在为该母版准备图位和整页预览…",
                                self.receive_template_upgrade, "母版升级未完成")
                return
            self.apply_template_capabilities(profile)
            self.template_label.configure(text=self.template_summary())
            self.invalidate()
            self.status.set(f"当前母版 · {self.template.label}")
            self.sync_preview()
            self.preview.show_original()
            if self.source:
                self.queue_validation()

    def receive_template_upgrade(self, template):
        self.templates = list_templates()
        index = next((index for index, item in enumerate(self.templates) if item.id == template.id), 0)
        self.template_combo.configure(values=[item.label for item in self.templates])
        self.template_combo.current(index)
        self.choose_template()

    def repair_template_reference(self):
        if self.busy or self.template is None:
            return
        from templates import repair_original_preview

        template = self.template
        source = Path(template.source)
        if not source.is_file():
            selected = filedialog.askopenfilename(title="选择该母版的原始 PSD / PSB",
                                                  filetypes=[("Photoshop 母版", "*.psd *.psb")])
            if not selected:
                return
            source = Path(selected)
        def done(info):
            self.templates = list_templates()
            self.template = next((item for item in self.templates if item.id == template.id), template)
            self.template_combo.configure(values=[item.label for item in self.templates])
            self.template_combo.current(self.templates.index(self.template))
            self.sync_preview()
            self.preview.show_original()
            self.status.set("母版完整参考图已重新读取" if info.get("status") == "ready" else info.get("message", "原稿未能读取"))
        self.start_task(lambda: repair_original_preview(template, source=source),
                        "正在读取母版原稿完整画面…", done, "母版原稿读取失败")

    def import_data(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("导入一款商品资料")
        dialog.transient(self.root)
        dialog.grab_set()
        area = ttk.Frame(dialog, padding=18)
        area.pack(fill="both", expand=True)
        ttk.Label(area, text="导入商品资料", style="H2.TLabel").pack(anchor="w")
        ttk.Label(area, text="选择包含 product_data.json 和原始图片的文件夹或 ZIP。\n也可直接选择 JSON，图片按 JSON 所在目录定位。",
                  style="Muted.TLabel", wraplength=520).pack(anchor="w", pady=(8, 15))

        def select(folder):
            path = filedialog.askdirectory(title="选择完整商品资料目录", parent=dialog) if folder else filedialog.askopenfilename(
                title="选择 ZIP 资料包或 product_data.json", parent=dialog,
                filetypes=[("商品资料", "*.zip *.json"), ("ZIP 资料包", "*.zip"), ("商品 JSON", "*.json")])
            if path:
                dialog.destroy()
                self.import_package_path(path)

        ttk.Button(area, text="选择商品资料文件夹", style="Primary.TButton", command=lambda: select(True)).pack(fill="x")
        ttk.Button(area, text="选择 ZIP / JSON", command=lambda: select(False)).pack(fill="x", pady=(8, 0))
        ttk.Separator(area).pack(fill="x", pady=14)
        ttk.Label(area, text="还没有本地资料？", style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
        def handoff():
            dialog.destroy()
            self.handoff_feishu()
        ttk.Button(area, text="让 Codex 整理资料", command=handoff).pack(fill="x")
        ttk.Label(area, text="填写飞书链接和视图行号，复制任务给 Codex；完成后在这里导入整理结果。",
                  style="Muted.TLabel", wraplength=520).pack(anchor="w", pady=(6, 0))
        dialog.bind("<Escape>", lambda _: dialog.destroy())

    def import_package_path(self, path):
        def load():
            try:
                return load_package(path, cache_root=PACKAGE_CACHE)
            except PackageSelectionRequired as choices:
                return choices

        self.start_task(load, "正在读取资料与图片路径…", self.receive_package, "资料包导入失败", failure=self.package_import_error)

    def package_import_error(self, message):
        messagebox.showerror("资料包导入失败", message, parent=self.root)

    def load_demo(self):
        try:
            data = read_data(DEMO)
        except (OSError, ValueError) as error:
            messagebox.showerror("样例无法打开", str(error), parent=self.root)
            return
        assets = DEMO.parent / "assets"
        products = {color: assets / f"{color}-高清.png" for color in data["colors"]}
        scenes = [assets / f"scene-{tag}.jpg" for tag in ("top", "middle", "bottom")]
        scenes.append(ROOT.parent / "work/KQ26169-new-psb/assets/static-scene.jpg")
        code = data["info"].get("货号") or ""
        self.apply_data(data, str(DEMO), products, scenes, f"试用样例 · {code} 马甲".strip())

    def set_data(self, path):
        try:
            package = load_package(path, cache_root=PACKAGE_CACHE)
        except (OSError, ValueError) as error:
            messagebox.showerror("商品资料无法打开", str(error), parent=self.root)
            return False
        return self.receive_package(package)

    def receive_package(self, package, *, replace_confirmed=False):
        if isinstance(package, PackageSelectionRequired):
            dialog = tk.Toplevel(self.root)
            dialog.title("选择资料包中的商品")
            area = ttk.Frame(dialog, padding=15)
            area.pack(fill="both", expand=True)
            ttk.Label(area, text="资料包中有多款，请选择这一款的 product_data.json。", wraplength=600).pack(anchor="w", pady=(0, 8))
            choices = tk.Listbox(area, width=80, height=min(12, len(package.candidates)), exportselection=False)
            choices.pack(fill="both", expand=True)
            for candidate in package.candidates:
                choices.insert("end", str(candidate))
            choices.selection_set(0)

            def select():
                indexes = choices.curselection()
                if indexes:
                    selected = package.candidates[indexes[0]]
                    dialog.destroy()
                    self.import_package_path(selected)

            ttk.Button(area, text="导入所选商品", command=select, style="Primary.TButton").pack(anchor="e", pady=(10, 0))
            return
        if not replace_confirmed:
            return self.confirm_data_replace(lambda: self.receive_package(package, replace_confirmed=True))
        note = package.data.get("source_note")
        source = f"{note.strip()} · 本地资料 {package.json_path}" if isinstance(note, str) and note.strip() else str(package.json_path)
        self.apply_data(package.data, source, package.products, package.scenes,
                        f"{package.origin.name} · {package.data.get('info', {}).get('货号', '')}", replace_confirmed=True)
        self.package = package
        self.source_json = package.json_path
        self.package_root = package.root
        self.missing_assets = list(package.missing)
        self.extra_images = dict(package.extra_images)
        self.views = {}
        if package.selected_template:
            match = next((i for i, item in enumerate(self.templates) if item.id == package.selected_template), None)
            if match is not None:
                self.template_combo.current(match)
                self.choose_template()
            else:
                self.status.set("资料已导入，保存时使用的母版不在本机，请选择母版。")
        if self.missing_assets:
            self.status.set(f"已导入资料，{len(self.missing_assets)} 个素材未找到，可重新定位目录。")
            self.tabs.select(self.images)
        elif self.template is None:
            self.status.set("已导入资料 · 请上传本地母版")
        else:
            count = sum(bool(path) for path in self.products.values())
            self.status.set(f"资料已导入 · 商品色图 {count}/{len(self.color_names())}")
        self.queue_preview()
        self.unsaved = False
        self.update_edit_controls()
        self.sync_preview()
        self.preview.show_live()
        self.queue_validation()
        return True

    def show_source_details(self):
        if not self.source:
            messagebox.showinfo("先导入资料", "请选择一款商品的资料包或 JSON。", parent=self.root)
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("当前资料路径与素材检查")
        dialog.transient(self.root)
        area = ttk.Frame(dialog, padding=16)
        area.pack(fill="both", expand=True)
        ttk.Label(area, text="当前导入来源", style="H2.TLabel").pack(anchor="w")
        text = tk.Text(area, width=82, height=22, wrap="word", font=(FONT, 10), padx=10, pady=10)
        text.pack(fill="both", expand=True, pady=10)
        lines = [f"导入的文件或目录\n{self.package.origin if self.package else self.source_json or '界面导入'}",
                 f"\n本地 JSON\n{self.source_json or '当前资料来自界面导入，保存资料包后可复用'}",
                 f"\n资料目录\n{self.package_root or '尚未保存本地资料目录'}", f"\n来源说明\n{self.source}", "\n图片对应关系"]
        for kind, key in self.slots:
            source = self.slot_source(kind, key)
            fallback = "沿用母版示意图" if kind == "measurement" else "未配置"
            lines.append(f"{self.slot_label(kind, key)}\n  {source or fallback}")
        missing = self.current_missing_assets()
        if missing:
            lines += ["\n未找到的引用"]
            lines += [f"{item['label']}\n  预期位置 {item['expected']}" for item in missing]
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")
        row = ttk.Frame(area)
        row.pack(fill="x")
        ttk.Button(row, text="打开资料所在文件夹", command=lambda: self.reveal_path(self.source_json or self.package_root)).pack(side="left")
        ttk.Button(row, text="重新定位素材目录", command=self.relocate_assets).pack(side="left", padx=7)
        ttk.Button(row, text="关闭", command=dialog.destroy).pack(side="right")

    def current_missing_assets(self):
        labels = {self.slot_label(kind, key): self.slot_source(kind, key) for kind, key in self.slots}
        return [item for item in self.missing_assets
                if not labels.get(item["label"]) or not Path(labels[item["label"]]).is_file()]

    def relocate_assets(self):
        if self.busy:
            return
        if not self.source_json:
            messagebox.showinfo("重新定位素材", "当前资料尚未关联 JSON，请在图片匹配中选择素材，或先保存资料包。", parent=self.root)
            return
        selected = filedialog.askdirectory(title="选择包含原始附件或素材的目录", initialdir=str(self.package_root or self.source_json.parent))
        if selected:
            path = self.source_json
            self.start_task(lambda: load_package(path, cache_root=PACKAGE_CACHE, asset_root=selected),
                            "正在按原引用和同名文件定位素材…", self.receive_relocation, "素材重定位失败")

    def receive_relocation(self, package):
        def missing(source):
            return not source or not Path(source).is_file()

        assets = self.data.get("assets")
        cleared = {key for key in EXTRA_IMAGE_LABELS if isinstance(assets, dict) and
                   key in assets and assets[key] in (None, "")}
        colors = set(self.color_names())
        for name, source in package.products.items():
            if name in colors and source and missing(self.products.get(name)):
                self.products[name] = source
        for index, source in enumerate(package.scenes):
            if source and missing(self.scenes[index]):
                self.scenes[index] = source
        for name, source in package.extra_images.items():
            if name not in cleared and source and missing(self.extra_images.get(name)):
                self.extra_images[name] = source
        cleared_labels = {EXTRA_IMAGE_LABELS[key] for key in cleared}
        self.missing_assets = [item for item in package.missing if item["label"] not in cleared_labels]
        self.refresh_slots()
        self.invalidate()
        count = sum(bool(path) and Path(path).is_file() for path in self.products.values())
        remaining = len(self.current_missing_assets())
        self.status.set(f"已定位商品图 {count}/{len(self.color_names())}" + (f" · 仍有 {remaining} 个引用待处理" if remaining else " · 请确认右侧预览"))

    def save_current_package(self, on_saved=None):
        if self.busy or not self.source:
            return
        if self.finish_cell:
            self.finish_cell(True)
        self.flush_pending_sync()
        code = re.sub(r"[^A-Za-z0-9_-]", "_", self.fields["货号"].get().strip()) or "商品资料"
        selected = filedialog.asksaveasfilename(title="保存当前商品资料包", defaultextension=".zip",
                                               initialfile=f"{code}_资料包_{datetime.now():%Y%m%d-%H%M%S}.zip", filetypes=[("ZIP 资料包", "*.zip")])
        if not selected:
            return
        data = self.current_data()
        data["source_note"] = data.get("source_note") or self.source
        products = {color: self.products.get(color) for color in self.color_names()}
        scenes, extra = list(self.scenes), dict(self.extra_images)
        views = {}
        template_id, source_root = getattr(self.template, "id", None), self.package_root

        def saved(path):
            self.unsaved = False
            self.status.set(f"资料包已保存 · {path}")
            if on_saved:
                on_saved()

        self.start_task(lambda: save_package(selected, data, products, scenes, views=views, extra_images=extra,
                                             selected_template=template_id, source_root=source_root),
                        "正在保存商品资料与原始图片…", saved, "资料包保存失败")

    def check_source_version(self):
        self.version_task = None
        try:
            changed = program_stamp() != SOURCE_STAMP
        except OSError:
            changed = False
        if changed:
            self.version_label.configure(text="工作台程序已更新 · 点「刷新工作台」载入新版，当前草稿会保留", fg="#ffe5a0")
        self.version_task = self.root.after(5000, self.check_source_version)

    def refresh_application(self):
        if self.busy or self.refresh_pending:
            return
        from refresh_session import save_refresh_session, session_ready_path

        if self.finish_cell:
            self.finish_cell(True)
        self.flush_pending_sync()
        try:
            snapshot = save_refresh_session(self)
            ready = session_ready_path(snapshot)
            executable = Path(sys.executable)
            windowed = executable.with_name("pythonw.exe")
            if windowed.is_file():
                executable = windowed
            log_path = snapshot.with_suffix(".log")
            with log_path.open("w", encoding="utf-8") as log:
                process = subprocess.Popen([str(executable), str(ROOT / "app.py"), "--restore-session", str(snapshot)],
                                           cwd=ROOT, stdout=log, stderr=log,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, ValueError, TypeError) as error:
            messagebox.showerror("刷新未完成", f"当前窗口与草稿已保留。\n{error}", parent=self.root)
            return
        self.refresh_pending = True
        self.validation_revision += 1
        self.set_busy(True)
        self.status.set("正在刷新工作台 · 已保留当前商品资料与配图…")
        deadline = time.monotonic() + 45
        def poll():
            self.refresh_poll_task = None
            if ready.is_file():
                self.unsaved = False
                self.root.destroy()
                return
            if process.poll() is not None or time.monotonic() >= deadline:
                self.refresh_pending = False
                self.set_busy(False)
                self.status.set("刷新未完成，当前窗口和草稿已保留")
                messagebox.showerror("刷新未完成", f"当前窗口与草稿已保留，可以继续操作。\n日志：{log_path}", parent=self.root)
                return
            self.refresh_poll_task = self.root.after(120, poll)
        self.refresh_poll_task = self.root.after(120, poll)

    def restore_refresh_session(self, path):
        from refresh_session import read_refresh_session, mark_refresh_session_ready

        try:
            product_json, metadata = read_refresh_session(path)
            if product_json is not None:
                package = load_package(product_json, cache_root=PACKAGE_CACHE)
                self.receive_package(package, replace_confirmed=True)
                self.source = metadata.get("source") or self.source
                self.source_json = Path(metadata["source_json"]) if metadata.get("source_json") else None
                self.package_root = Path(metadata["package_root"]) if metadata.get("package_root") else None
                if metadata.get("origin"):
                    self.package.origin = Path(metadata["origin"])
                self.attachments = metadata.get("attachments", self.attachments)
                bindings = metadata.get("bindings", {})
                if isinstance(bindings, dict):
                    for attribute in ("products", "extra_images"):
                        values = bindings.get(attribute)
                        if isinstance(values, dict):
                            setattr(self, attribute, {key: Path(value) if value else None for key, value in values.items()})
                    if isinstance(bindings.get("scenes"), list):
                        self.scenes = ([Path(value) if value else None for value in bindings["scenes"]] + [None] * 4)[:4]
                self.views = {}
                self.binding_notice = metadata.get("binding_notice", "")
                self.rename_origins = metadata.get("rename_origins", self.rename_origins)
                self.unsaved = bool(metadata.get("unsaved"))
                self.output.set(metadata.get("output") or self.output.get())
                self.update_output_label()
                self.sync_preview()
                self.refresh_slots()
                selected = metadata.get("selected_slot")
                if isinstance(selected, list) and len(selected) == 2 and tuple(selected) in self.slots:
                    self.select_preview_slot(*selected)
                    self.preview.focus_slot(*selected, reveal=False)
                result = metadata.get("result")
                if isinstance(result, list) and len(result) >= 3 and Path(result[2]).is_file():
                    self.result = tuple(Path(value) for value in result)
                    self.result_button.state(["!disabled"])
                    self.preview.set_result(self.result[2])
                    self.preview.final_stale = bool(metadata.get("final_stale") or metadata.get("views"))
                mode = metadata.get("preview_mode")
                if mode == "original":
                    self.preview.show_original()
                elif mode == "final" and self.result:
                    self.preview.show_final()
                else:
                    self.preview.show_live()
                tab = {0: self.details, 1: self.images, 2: self.review,
                       "details": self.details, "images": self.images, "review": self.review}.get(metadata.get("tab"))
                if tab:
                    self.tabs.select(tab)
                def scroll_back(attempt=0):
                    if self.preview.pending and attempt < 60:
                        self.root.after(100, lambda: scroll_back(attempt + 1))
                    else:
                        self.preview.canvas.yview_moveto(float(metadata.get("preview_scroll", 0)))
                self.root.after(200, scroll_back)
            else:
                chosen = metadata.get("selected_template")
                index = next((index for index, item in enumerate(self.templates) if item.id == chosen), None)
                if index is not None:
                    self.template_combo.current(index)
                    self.choose_template()
                self.output.set(metadata.get("output") or self.output.get())
                self.update_output_label()
            self.version_label.configure(text=f"v{APP_VERSION} · 已刷新并恢复当前工作", fg="#aee0c4")
            self.status.set("工作台已刷新 · 当前草稿已恢复" + ("，尚未保存为资料包" if self.unsaved else ""))
            self.update_edit_controls()
            mark_refresh_session_ready(path)
        except Exception as error:
            self.status.set("刷新恢复未完成，原窗口与会话快照仍保留")
            messagebox.showerror("草稿恢复未完成", f"原窗口会继续保留，请返回原窗口操作。\n{error}", parent=self.root)

    def apply_data(self, data, source, products, scenes, label, *, attachments=(), replace_confirmed=False):
        if not replace_confirmed:
            return self.confirm_data_replace(lambda: self.apply_data(data, source, products, scenes, label,
                                                                     attachments=attachments, replace_confirmed=True))
        data = dict(data)
        if data.pop("views", None):
            note = "已忽略旧手动取景，按图框自动居中填满。"
            warnings = list(data.get("warnings", []))
            if note not in warnings:
                warnings.append(note)
            data["warnings"] = warnings
        self.loading = True
        self.data, self.source = data, source
        self.size_note = data.get("size_note")
        if self.size_note is not None and not isinstance(self.size_note, str):
            self.size_note = None
            warnings = data.get("warnings")
            data["warnings"] = [*(warnings if isinstance(warnings, list) else []), "尺码备注格式有误，请重新填写文字。"]
        raw_decorations = data.get("hidden_decorations", {})
        self.hidden_decorations = {}
        if isinstance(raw_decorations, dict):
            for template_id, ids in raw_decorations.items():
                if isinstance(template_id, str) and isinstance(ids, list):
                    self.hidden_decorations[template_id] = list(dict.fromkeys(item for item in ids if isinstance(item, str)))
        else:
            notes = list(data.get("warnings", []))
            notes.append("隐藏装饰记录格式无效，已恢复默认装饰。")
            self.data["warnings"] = notes
        self.attachments = list(attachments)
        self.data_label.configure(text=label)
        for name, value in self.fields.items():
            value.set(str(data["info"].get(name) or ""))
        colors = data.get("colors", [])
        self.colors.set("、".join(color.strip() for color in colors if isinstance(color, str))
                        if isinstance(colors, list) else "")
        self.loading = False
        self.products = dict(products or {})
        self.scenes = (list(scenes or []) + [None] * 4)[:4]
        self.extra_images = dict.fromkeys(EXTRA_IMAGE_LABELS)
        self.views = {}
        self.package = None
        self.source_json = None
        self.package_root = None
        self.missing_assets = []
        self.bound_colors = self.color_names()
        self.rename_origins = {color: color for color in self.bound_colors}
        self.binding_notice = ""
        self.tables = {}
        self.edited_tables.clear()
        readers = (lambda: normalize_table(data["size_table"]["headers"], data["size_table"]["rows"]),
                   lambda: quick_table(data["quick_size"]), lambda: fit_table(data["try_on"]))
        for name, reader in zip(TABLE_NAMES, readers):
            try:
                self.tables[name] = reader()
            except (KeyError, TypeError, ValueError):
                continue
        self.cell_editor = None
        self.finish_cell = None
        self.populate_tables(self.tables)
        self.result = None
        self.result_button.configure(text="打开成品文件夹")
        self.result_button.state(["disabled"])
        self.preview.set_result(None)
        self.slots = []
        self.tabs.select(self.details)
        self.invalidate()
        self.update_edit_controls()
        self.status.set(f"已载入 · {label}")
        self.unsaved = False
        self.queue_validation()
        return True

    def refresh_slots(self):
        selection = self.slot_tree.selection()
        self.slot_tree.delete(*self.slot_tree.get_children())
        for i, (kind, key) in enumerate(self.slots):
            source = self.slot_source(kind, key)
            label = self.slot_label(kind, key)
            if not self.extra_images.get(kind) and source:
                if kind == "hero":
                    label += " · 默认商品图"
                elif kind == "brand":
                    label += " · 跟随模特图1"
            placeholder = "沿用母版示意图" if kind == "measurement" else "待绑定"
            self.slot_tree.insert("", "end", iid=str(i), values=(label, Path(source).name if source else placeholder))
        if selection and self.slot_tree.exists(selection[0]):
            self.slot_tree.selection_set(selection[0])
        elif self.slots:
            missing = next((index for index, (kind, key) in enumerate(self.slots)
                            if kind == "product" and not self.slot_source(kind, key)), 0)
            self.slot_tree.selection_set(str(missing))
        product_slots = [key for kind, key in self.slots if kind == "product"]
        count = sum(bool(self.products.get(color)) for color in product_slots)
        scene_indexes = [index for kind, index in self.slots if kind == "scene"]
        scene_count = sum(bool(self.scenes[index]) for index in scene_indexes)
        model_hint = (f"模特展示 {scene_count} 张（选填，最多{len(scene_indexes)}张）" if scene_count else
                      "未启用模特展示（选填）" if scene_indexes else "本母版无模特展示图位")
        last_bound = max((index for index in scene_indexes if self.scenes[index]), default=-1)
        gaps = [f"模特图{index + 1}" for index in scene_indexes if index < last_bound and not self.scenes[index]]
        if gaps:
            model_hint += " · " + "、".join(gaps) + "未绑定"
        self.image_summary.configure(text=f"商品色图已配 {count}/{len(product_slots)} · {model_hint}")
        self.show_slot()

    def selected_slot(self):
        selection = self.slot_tree.selection()
        return self.slots[int(selection[0])] if selection and int(selection[0]) < len(self.slots) else None

    @staticmethod
    def slot_label(kind, key):
        if kind == "product":
            return f"商品图 · {key}"
        if kind == "scene":
            return f"模特图 {key + 1}"
        return EXTRA_IMAGE_LABELS[kind]

    @staticmethod
    def slot_key(kind, key):
        return f"scene_{key + 1}" if kind == "scene" else str(key) if kind in EXTRA_IMAGE_LABELS else f"product:{key}"

    def slot_source(self, kind, key):
        if kind == "product":
            return self.products.get(key)
        if kind == "scene":
            return self.scenes[key]
        if self.extra_images.get(kind):
            return self.extra_images[kind]
        if kind == "hero":
            return next((self.products.get(color) for color in self.color_names() if self.products.get(color)), None)
        if kind == "brand" and self.scenes and self.scenes[0]:
            return self.scenes[0]
        return None

    def slot_selection_changed(self, _=None):
        self.show_slot(reveal=self.selected_slot() != self.last_displayed_slot)

    def show_slot(self, *, reveal=False):
        slot = self.selected_slot()
        self.last_displayed_slot = slot
        if not slot:
            self.slot_path.configure(text="点击上方位置，查看图片及来源。")
            self.update_edit_controls()
            return
        kind, key = slot
        source = self.slot_source(kind, key)
        label = self.slot_label(kind, key)
        self.pick_button.configure(text=f"替换 {label}" if source else f"选择 {label} 图片")
        description = str(source) if source else f"{label} 待绑定。点击上方按钮选择图片。"
        if source and kind == "hero" and not self.extra_images.get("hero"):
            description += "\n当前默认使用第一色商品图，与模特图独立；也可单独选择主视觉照片。"
        elif kind == "measurement":
            if not source:
                description = "当前沿用母版的尺码测量示意图。可选择本款的示意图。"
            description += "\n示意图按比例完整显示，保留量尺标注。"
        elif source and kind != "product":
            description += "\n照片自动等比填满图框、居中裁切；原始图片保持不变。"
        self.slot_path.configure(text=description)
        clear_labels = {"hero": "恢复默认商品图", "brand": "恢复默认来源", "measurement": "恢复母版示意图"}
        self.clear_button.configure(text=clear_labels.get(kind, "清除所选"))
        self.update_edit_controls()
        if reveal or self.preview.selected_slot == (kind, key):
            self.preview.focus_slot(kind, key, reveal=reveal)

    def select_preview_slot(self, kind, key):
        """Keep preview selection and the source list in sync without scrolling again."""
        slot = (kind, key)
        if self.busy or slot not in self.slots:
            return
        self.last_displayed_slot = slot
        self.slot_tree.selection_set(str(self.slots.index(slot)))
        self.show_slot(reveal=False)

    def add_preview_image(self, kind, key):
        if self.busy or not self.source or (kind, key) not in self.slots:
            return
        self.select_preview_slot(kind, key)
        self.choose_image()

    def change_decoration(self, decoration_id, hidden):
        if self.busy or not self.source or self.template is None:
            return
        try:
            profile = self.template.profile() or {}
            decorations = {item["id"]: item for item in profile.get("decorations", [])}
        except (OSError, ValueError, KeyError, TypeError):
            return
        if decoration_id not in decorations:
            return
        selected = set(self.hidden_decorations.get(self.template.id, []))
        if (decoration_id in selected) == hidden:
            return
        if hidden:
            selected.add(decoration_id)
        else:
            selected.discard(decoration_id)
        if selected:
            self.hidden_decorations[self.template.id] = sorted(selected)
        else:
            self.hidden_decorations.pop(self.template.id, None)
        self.invalidate()
        label = decorations[decoration_id].get("label", "装饰")
        self.status.set(f"已删除{label} · 右键预览可恢复" if hidden else f"已恢复{label}")

    def choose_image(self):
        slot = self.selected_slot()
        if slot is None or self.busy:
            return
        kind, key = slot
        current = self.slot_source(kind, key)
        selected = filedialog.askopenfilename(title="为选中的位置选择图片",
                                              initialdir=str(Path(current).parent) if current else str(ROOT.parent),
                                              filetypes=[("透明商品 PNG", "*.png")] if kind == "product" else IMAGE_FILTER)
        if selected:
            self.start_task(lambda: image_entry(selected, str(key), product=kind == "product"),
                            "正在检查所选图片…", lambda _: self.set_image(kind, key, Path(selected)), "图片不适用")

    def open_original(self):
        slot = self.selected_slot()
        if slot:
            kind, key = slot
            source = self.slot_source(kind, key)
            if source:
                open_source_preview(self.root, source)

    def reveal_path(self, path):
        if not path:
            return
        path = Path(path)
        try:
            if path.is_file():
                subprocess.Popen(["explorer.exe", "/select," + str(path)], creationflags=subprocess.CREATE_NO_WINDOW)
            elif path.is_dir():
                subprocess.Popen(["explorer.exe", str(path)], creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                messagebox.showinfo("路径未找到", f"此位置当前不可用\n{path}\n请重新定位资料目录。", parent=self.root)
        except OSError as error:
            messagebox.showerror("无法打开资料位置", f"{path}\n{error}", parent=self.root)

    def clear_image(self):
        slot = self.selected_slot()
        if slot is not None and not self.busy:
            self.set_image(*slot, None)

    def set_image(self, kind, key, path):
        if kind == "product":
            self.products[key] = path
        elif kind == "scene":
            self.scenes[key] = path
        else:
            self.extra_images[kind] = path
        assets = self.data.setdefault("assets", {})
        if isinstance(assets, dict):
            stored_path = str(Path(path).resolve()) if path else None
            if kind == "product":
                mapping = assets.setdefault("products", {})
                if isinstance(mapping, dict):
                    mapping[key] = stored_path
            elif kind == "scene":
                entries = assets.setdefault("scenes", [])
                if isinstance(entries, list):
                    while len(entries) <= key:
                        entries.append(None)
                    entries[key] = stored_path
            else:
                assets[kind] = stored_path
        label = self.slot_label(kind, key)
        self.missing_assets = [item for item in self.missing_assets if item["label"] != label]
        if path:
            self.preview.refresh_asset(path)
        self.refresh_slots()
        self.invalidate()
        # Selecting/replacing a picture is an explicit preview action. Show the
        # changed product rather than leave the user looking at the master.
        self.sync_preview()
        self.preview.focus_slot(kind, key, reveal=True)

    def choose_output(self):
        selected = filedialog.askdirectory(title="选择交付文件夹")
        if selected:
            self.output.set(selected)
            self.update_output_label()

    def update_output_label(self):
        self.output_label.configure(text=self.output.get())

    def current_data(self):
        data = {**self.data, "info": {key: value.get() for key, value in self.fields.items()},
                "colors": self.color_names(),
                "size_note": self.size_note,
                "hidden_decorations": {key: list(ids) for key, ids in self.hidden_decorations.items() if ids}}
        if TABLE_NAMES[0] in self.edited_tables:
            head, *rows = self.tables[TABLE_NAMES[0]]
            data["size_table"] = {"headers": head, "rows": rows}
        if TABLE_NAMES[1] in self.edited_tables:
            head, *rows = self.tables[TABLE_NAMES[1]]
            data["quick_size"] = {"axis_label": head[0], "columns": head[1:], "rows": [row[0] for row in rows], "data": [row[1:] for row in rows]}
        if TABLE_NAMES[2] in self.edited_tables:
            trial = self.tables.get(TABLE_NAMES[2])
            data["try_on"] = {"headers": trial[0], "rows": trial[1:]} if trial else None
        if self.attachments or self.source.startswith("飞书"):
            names = ("尺码表", "尺码快选", "试穿报告")
            filled = tuple(f"{label}未取得" for key, label in zip(TABLE_NAMES, names)
                           if key in self.edited_tables and self.tables.get(key))
            notes = data.get("warnings", [])
            if isinstance(notes, list):
                data["warnings"] = [note for note in notes if isinstance(note, str) and not note.startswith(filled)]
        if self.binding_notice:
            notes = list(data.get("warnings", [])) if isinstance(data.get("warnings"), list) else []
            if self.binding_notice not in notes:
                data["warnings"] = [*notes, self.binding_notice]
        return data

    def check(self, *, generate=False):
        if self.busy:
            return
        self.validation_revision += 1
        if self.finish_cell:
            self.finish_cell(True)
        self.flush_pending_sync()
        if not self.source:
            self.tabs.select(self.review)
            self.review_text("请先从飞书或本地文件导入一款商品，也可以试用马甲样例。")
            self.status.set("请先导入商品资料")
            messagebox.showinfo("先导入一款商品", "请点击左侧「导入资料包 / JSON」，或「试用马甲样例」。", parent=self.root)
            return
        if self.template is None:
            self.tabs.select(self.review)
            self.review_text("请在左侧上传本地母版，再检查版式和图位。")
            self.status.set("请先上传本地母版")
            return
        data, products, template = self.current_data(), dict(self.products), self.template
        views, extra_images = {}, dict(self.extra_images)
        scenes = list(self.scenes)
        while scenes and scenes[-1] is None:
            scenes.pop()
        self.job = None
        self.tabs.select(self.review)
        self.review_text("正在核对表格、图片和母版，请稍候。")
        self.start_task(lambda: preflight(data, products, scenes, template=template, views=views, extra_images=extra_images),
                        "正在预检表格和素材…", lambda result: self.receive_check(result, generate=generate), "预检未完成")

    def receive_check(self, result, *, generate=False, quiet=False):
        job, errors, warnings = result
        self.job = None if errors else job
        report = [f"当前母版 · {self.template.label}", f"资料来源 · {self.source}", ""]
        if errors:
            report += ["待处理", *[f"  •  {error}" for error in errors], ""]
        else:
            report += [f"通过 · {job['info']['货号']}  {job['info']['名称']}", ""]
        report.extend(f"{name}   {len(matrix) - 1} 行 × {len(matrix[0])} 列" for name, matrix in job["tables"].items())
        report += ["", "素材对应关系"]
        report.extend(f"{item['label']}  ←  {item['source']}" for item in job["products"] + job["scenes"])
        if job.get("measurement"):
            report.append(f"{EXTRA_IMAGE_LABELS['measurement']}  ←  {job['measurement']['source']}")
        if self.attachments:
            report += ["", "飞书行中的附件", *[f"  •  {item['field']} · {item['name']}" for item in self.attachments[:12]]]
            if len(self.attachments) > 12:
                report.append(f"  … 共 {len(self.attachments)} 个附件")
        if warnings:
            report += ["", "需要留意", *[f"  •  {warning}" for warning in warnings]]
        self.review_text("\n".join(report))
        self.toggle_export()
        if not quiet:
            self.tabs.select(self.review)
        self.status.set(f"发现 {len(errors)} 项待处理，可在「检查结果」查看" if errors else (
            f"资料检查通过 · {len(warnings)} 项提示，可在「检查结果」查看" if warnings else "资料检查通过，可以生成"))
        if generate and not errors:
            job, output, source = self.job, self.output.get(), self.source
            self.start_task(lambda: export_detail(job, output, source, lambda status: self.events.put(("status", status))),
                            "正在准备 Photoshop 交付…", self.display_result, "套版生成失败")

    def toggle_export(self):
        self.export_button.state(["disabled"] if self.busy or self.template is None else ["!disabled"])

    def export(self):
        if self.busy:
            return
        self.check(generate=True)

    def start_task(self, action, status, success, error_title, *, failure=None):
        if self.busy:
            return
        self.set_busy(True)
        self.ps_wait_started = time.monotonic() if "Photoshop" in status or "母版" in status else None
        self.ps_wait_hint_shown = False
        self.status.set(status)
        self.progress.pack(side="left")
        self.progress.start(13)

        def worker():
            try:
                result = action()
            except UnsupportedTemplateError as error:
                self.events.put(("error", ("母版结构需要配置", str(error), failure)))
            except Exception as error:
                self.events.put(("error", (error_title, str(error), failure)))
            else:
                self.events.put(("result", (success, result)))

        threading.Thread(target=worker, daemon=True).start()

    def set_busy(self, busy):
        self.busy = busy
        if not busy:
            self.ps_wait_started = None
        buttons = (self.open_button, self.demo_button, self.output_button, self.upload_button, self.refresh_button)
        for control in buttons:
            control.state(["disabled"] if busy else ["!disabled"])
        self.template_combo.configure(state="disabled" if busy or not self.templates else "readonly")
        if not DEMO.is_file():
            self.demo_button.state(["disabled"])
        self.update_edit_controls()
        self.toggle_export()

    def update_edit_controls(self):
        ready = bool(self.source) and not self.busy
        can_delete = not self.busy and self.template and self.template.id != "builtin"
        self.delete_template_button.state(["!disabled"] if can_delete else ["disabled"])
        self.preview.set_editing_enabled(ready, busy=self.busy)
        for control in [*self.entries, self.edit_table_button, self.size_note_button, self.attributes_button,
                        self.fix_data_button, self.fix_images_button, self.save_button, self.source_button]:
            control.state(["!disabled"] if ready else ["disabled"])
        slot = self.selected_slot()
        source = None
        measurement_reference = False
        if slot:
            kind, key = slot
            source = self.slot_source(kind, key)
            assets = self.data.get("assets")
            measurement_reference = kind == "measurement" and isinstance(assets, dict) and bool(assets.get(kind))
        self.pick_button.state(["!disabled"] if ready and slot else ["disabled"])
        self.clear_button.state(["!disabled"] if ready and (source or measurement_reference) else ["disabled"])
        self.original_button.state(["!disabled"] if source and Path(source).is_file() else ["disabled"])

    def handle_events(self):
        self.poll_task = None
        while not self.events.empty():
            kind, value = self.events.get()
            if kind == "validation":
                revision, result, error = value
                if revision == self.validation_revision and not self.busy:
                    if error:
                        self.review_text(f"自动检查暂未完成：{error}\n点击生成时会重新检查最新资料。")
                    else:
                        self.receive_check(result, quiet=True)
                continue
            if kind == "status":
                self.status.set(value)
                continue
            self.progress.stop()
            self.progress.pack_forget()
            self.set_busy(False)
            if kind == "error":
                title, description, failure = value
                self.status.set(title)
                if failure:
                    failure(description)
                else:
                    messagebox.showerror(title, description, parent=self.root)
            else:
                success, result = value
                success(result)
            if not self.root.winfo_exists():
                return
        if (self.busy and self.ps_wait_started is not None and not self.ps_wait_hint_shown
                and time.monotonic() - self.ps_wait_started >= 60):
            current = self.status.get()
            if current.startswith("母版解析 · "):
                self.status.set(current + " · 处理较久，若 Photoshop 有弹窗请查看")
            else:
                self.status.set("Photoshop 仍在处理；如有待确认提示，请切到 Photoshop 确认。")
            self.ps_wait_hint_shown = True
        self.poll_task = self.root.after(150, self.handle_events)

    def on_destroy(self, event):
        if event.widget is self.root:
            for callback in (self.pending_preview, self.poll_task, self.version_task, self.pending_validation, self.refresh_poll_task):
                if callback is not None:
                    self.root.after_cancel(callback)
            if self.instance_handle:
                self.instance_kernel.CloseHandle(self.instance_handle)
                self.instance_handle = None

    def display_result(self, result):
        self.result = result
        self.result_button.configure(text="打开成品文件夹")
        self.result_button.state(["!disabled"])
        self.status.set("PSB 已生成 · Photoshop 重开核验通过")
        self.preview.set_result(result[2])

    def open_result(self, index):
        if self.result:
            if index == 0:
                self.reveal_path(self.result[0])
                return
            try:
                os.startfile(self.result[index])
            except OSError as error:
                messagebox.showerror("无法打开文件", str(error), parent=self.root)

    def close(self):
        if self.busy:
            messagebox.showinfo("当前操作进行中", "请等待当前操作完成后关闭工作台。", parent=self.root)
        elif self.unsaved and self.source:
            answer = messagebox.askyesnocancel("保存本次调整", "商品资料或配图已修改。是否先保存资料包？", parent=self.root)
            if answer is True:
                self.save_current_package(on_saved=self.root.destroy)
            elif answer is False:
                self.root.destroy()
        else:
            self.root.destroy()


def create_window():
    ctypes.windll.user32.SetProcessDPIAware()
    window = tk.Tk()
    return window, Workbench(window)


if __name__ == "__main__":
    window, application = create_window()
    if len(sys.argv) == 3 and sys.argv[1] == "--restore-session":
        window.after(150, lambda: application.restore_refresh_session(sys.argv[2]))
    elif len(sys.argv) > 1:
        window.after(150, lambda: application.import_package_path(sys.argv[1]))
    window.mainloop()
