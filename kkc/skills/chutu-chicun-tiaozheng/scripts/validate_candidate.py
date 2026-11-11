#!/usr/bin/env python3
"""固定验证器：独立检查输出尺寸、几何比例、补边政策和原图保护。"""
import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from user_profile import effective_job, file_hash, snapshot_digest, validate_settings


def source_size(path):
    if Path(path).suffix.lower()=='.psd':
        from psd_source import inspect_source
        return tuple(inspect_source(path)['size'])
    with Image.open(path) as opened:
        return ImageOps.exif_transpose(opened).size


def source_preview(path, source_layers=None):
    if Path(path).suffix.lower()=='.psd':
        from psd_tools import PSDImage
        doc=PSDImage.open(path)
        if source_layers is not None:
            if not isinstance(source_layers,list) or not source_layers or len(source_layers)!=len(set(source_layers)):
                raise ValueError('source_layers必须为明确且不重复的顶层名称列表')
            counts={name:sum(layer.name==name for layer in doc) for name in source_layers}
            if any(count!=1 for count in counts.values()):raise ValueError('PSD选择图层缺失或名称不唯一')
            for layer in doc:layer.visible=layer.name in source_layers
            image=doc.composite(force=True,ignore_preview=True,apply_icc=False)
        else:
            image=doc.composite(apply_icc=False)
        if image is None:raise ValueError('源PSD缺少可用的合成预览，请用Photoshop检查源文件')
        return image.copy()
    with Image.open(path) as opened:
        return ImageOps.exif_transpose(opened).copy()


def load_engine(snapshot):
    path = Path(snapshot) / "renderer.py"
    spec = importlib.util.spec_from_file_location("renderer_" + file_hash(path)[:12], path)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    from processing_router import attach_routing
    return attach_routing(module)


def assert_render(image, plan, job):
    parts = str(job["size"]).lower().replace("×", "x").replace("*", "x").replace(" ", "").split("x")
    expected = tuple(map(int, parts))
    if image.size != expected:
        raise ValueError(f"输出尺寸不符：应为 {expected}，实际 {image.size}")
    viewport, domain = plan["source_viewport_px"], plan["source_domain_px"]
    actual_source_size = source_size(job['input'])
    if list(actual_source_size) != plan.get("source_size"):
        raise ValueError("构图记录中的源尺寸与EXIF纠正后原图不符")
    def pixel_box(value):
        if isinstance(value, str):
            value = value.split(',')
        values = list(map(float, value))
        if len(values) != 4 or not all(math.isfinite(v) and 0 <= v <= 1 for v in values):
            raise ValueError("无效归一化保护框")
        if values[0] >= values[2] or values[1] >= values[3]:
            raise ValueError("无效归一化保护框")
        return [values[0]*actual_source_size[0], values[1]*actual_source_size[1],
                values[2]*actual_source_size[0], values[3]*actual_source_size[1]]
    expected_domain = pixel_box(job.get("crop_box", [0, 0, 1, 1]))
    if len(domain) != 4 or any(not math.isfinite(v) or abs(v-e) > 1e-6 for v,e in zip(domain, expected_domain)):
        raise ValueError("构图记录中的裁切区域与任务参数不符")
    if len(viewport) != 4 or not all(math.isfinite(value) for value in viewport):
        raise ValueError("无效构图数据")
    vw, vh = viewport[2] - viewport[0], viewport[3] - viewport[1]
    if vw <= 0 or vh <= 0:
        raise ValueError("无效取景范围")
    for key in ("protect_box", "subject_box"):
        if key in job:
            box = pixel_box(job[key])
            for outer in (domain, viewport):
                if box[0] < outer[0]-1e-6 or box[1] < outer[1]-1e-6 or box[2] > outer[2]+1e-6 or box[3] > outer[3]+1e-6:
                    raise ValueError(f"输出未完整保留{key}指定区域")
    if not job.get("allow_stretch", False):
        scale_x, scale_y = expected[0] / vw, expected[1] / vh
        if abs(scale_x / scale_y - 1) > .005:
            raise ValueError("检测到不符合个人规则的非等比拉伸")
    if not job.get("allow_padding", False):
        eps = 1e-6
        if viewport[0] < domain[0]-eps or viewport[1] < domain[1]-eps or viewport[2] > domain[2]+eps or viewport[3] > domain[3]+eps:
            raise ValueError("检测到新增白边或透明边，不符合个人规则")


def _font(size):
    for path in ("C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def preview_pair(source, output, path, title):
    sheet = Image.new("RGB", (1020, 600), "#282e35")
    draw = ImageDraw.Draw(sheet)
    draw.text((18, 10), title, font=_font(22), fill="white")
    for index, im in enumerate((source, output)):
        im = im.convert("RGBA").copy()
        im.thumbnail((480, 480), Image.Resampling.LANCZOS)
        background = Image.new('RGB', im.size, '#eeeeee')
        checker = ImageDraw.Draw(background)
        for y in range(0, im.height, 16):
            for x in range(0, im.width, 16):
                if (x//16+y//16) % 2:
                    checker.rectangle((x,y,x+15,y+15), fill='#cccccc')
        background.paste(im, (0,0), im.getchannel('A'))
        x = 20 + index * 500
        sheet.paste(background, (x + (480-im.width)//2, 65+(480-im.height)//2))
    draw.text((20, 560), "原图", font=_font(20), fill="white")
    draw.text((520, 560), "候选版本输出", font=_font(20), fill="white")
    sheet.save(path, quality=94)


def validate_snapshot(snapshot, artifacts, jobs=None):
    snapshot, artifacts = Path(snapshot), Path(artifacts)
    artifacts.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "candidate_digest": snapshot_digest(snapshot), "checks": [], "previews": [], "sources": []}
    try:
        settings = validate_settings(json.loads((snapshot / "settings.json").read_text(encoding="utf-8")))
        if not (snapshot / "personal_prompt.md").read_text(encoding="utf-8").strip():
            raise ValueError("个人提示词不能为空")
        engine = load_engine(snapshot)
        with tempfile.TemporaryDirectory(prefix="chutu-validation-") as directory:
            temp = Path(directory)
            portrait = Image.new("RGB", (240, 400), "#74b2db")
            draw = ImageDraw.Draw(portrait)
            draw.ellipse((65, 28, 175, 118), fill="#edba96")
            draw.rectangle((45, 120, 195, 350), fill="#d16452")
            source = temp / "source.png"
            portrait.save(source)
            original_hash = file_hash(source)
            for size in ("240x240", "300x180", "180x300"):
                job = effective_job(settings, {"input": str(source), "size": size})
                _, image, plan, _ = engine._render(job)
                assert_render(image, plan, job)
            report["checks"].append("三种目标比例输出尺寸、等比缩放和补边政策")
            if not settings["defaults"]["allow_padding"]:
                blocked = False
                try:
                    job = effective_job(settings, {"input": str(source), "size": "240x240", "fit": "contain"})
                    _, image, plan, _ = engine._render(job)
                    assert_render(image, plan, job)
                except ValueError:
                    blocked = True
                if not blocked:
                    raise ValueError("未阻止自动补边")
                report["checks"].append("无白边规则不会静默退回补白")
            if not settings["defaults"]["allow_stretch"]:
                blocked = False
                try:
                    job = effective_job(settings, {"input": str(source), "size": "240x240", "fit": "stretch"})
                    _, image, plan, _ = engine._render(job)
                    assert_render(image, plan, job)
                except ValueError:
                    blocked = True
                if not blocked:
                    raise ValueError("未阻止默认拉伸")
                report["checks"].append("不拉伸规则")
            try:
                engine.make(effective_job(settings, {"input": str(source), "size": "240x240", "out_dir": str(temp),
                                                       "name": "source", "format": "png", "save_recipe": False}))
            except ValueError:
                pass
            else:
                raise ValueError("未阻止覆盖原图")
            if file_hash(source) != original_hash:
                raise ValueError("验证过程中原图发生变化")
            report["checks"].append("禁止覆盖原图")
            job = effective_job(settings, {"input": str(source), "size": "240x240", "focus": [.5, .30]})
            _, image, plan, _ = engine._render(job)
            assert_render(image, plan, job)
            preview = artifacts / "synthetic-preview.jpg"
            preview_pair(portrait, image, preview, "几何规则测试示意图")
            report["previews"].append({"path": str(preview.resolve()), "sha256": file_hash(preview)})
        for index, raw_job in enumerate(jobs or []):
            job = effective_job(settings, raw_job)
            source = Path(job["input"]).resolve()
            before = file_hash(source)
            _, image, plan, _ = engine._render(job)
            assert_render(image, plan, job)
            with source_preview(source,job.get('source_layers')) as original:
                preview = artifacts / f"sample-{index+1:02d}.jpg"
                preview_pair(original, image, preview, f"实际素材测试 {index+1}：{source.name}")
            if file_hash(source) != before:
                raise ValueError("实际素材在测试中被改动")
            report["previews"].append({"path": str(preview.resolve()), "sha256": file_hash(preview)})
            report["sources"].append({"path": str(source), "sha256": before})
        report["checks"].append(f"实际素材预览 {len(jobs or [])} 张；审美效果需用户查看")
        report["passed"] = True
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
    return report
