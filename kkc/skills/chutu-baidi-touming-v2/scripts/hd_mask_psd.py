"""High-resolution editable pixel layers and independent PSD layer masks.

JPG/PNG delivery pixels remain owned by the calling pipeline.  A larger PSD
canvas avoids reducing native product resolution; a hidden originals group
retains the input pixels independently of mask edits and color decontamination.
"""
from __future__ import annotations

import hashlib
import math

import numpy as np
from PIL import Image


ORIGINALS_GROUP = '原始素材（隐藏）'
MAX_PSD_SIDE = 30000


def _hash(image):
    return hashlib.sha256(image.tobytes()).hexdigest()


def _rgba(rgb, mask):
    image = rgb.convert('RGBA')
    image.putalpha(mask)
    return image


def build_style_assets(entries):
    """Return in-memory RGB/mask pairs and JSON-safe provenance for one style.

    Entries contain name, EXIF-oriented source RGBA, full-resolution candidate
    subject RGBA, fill and visible.  RGB data outside the cutout is retained;
    never create the pixel layer from an already-transparent product image.
    """
    if not entries:
        raise ValueError('高清PSD至少需要一个商品图层')
    prepared = []
    names = []
    side = 800
    for entry in entries:
        name = str(entry['name'])
        if not name or name in names:
            raise ValueError('高清PSD商品图层名为空或重复')
        names.append(name)
        source = entry['source'].convert('RGBA').copy()
        subject = entry['subject'].convert('RGBA').copy()
        if source.size != subject.size:
            raise ValueError('高清候选尺寸必须与EXIF转正后的原图一致')
        fill = float(entry.get('fill', .8))
        if not math.isfinite(fill) or not .5 <= fill <= .95:
            raise ValueError('高清PSD占比必须在0.50至0.95之间')
        bbox = subject.getchannel('A').getbbox()
        if bbox is None:
            raise ValueError('高清候选完全透明，不能生成商品PSD')
        longest = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
        side = max(side, math.ceil(longest / fill))
        prepared.append((entry, source, subject, fill, bbox, longest))
    if side > MAX_PSD_SIDE:
        raise ValueError(f'高清PSD画布需要{side}像素，超过PSD的30000像素限制；请另行选择PSB，不会自动降采样')

    products, originals, details = [], [], []
    for entry, source, subject, fill, bbox, longest in prepared:
        scale = side * fill / longest
        if scale < 1 - 1e-12:
            raise RuntimeError('高清PSD不得把原分辨率主体缩小')
        # Premultiplied RGBA resampling keeps a photograph's background RGB
        # from bleeding into the visible foreground at a soft cutout edge.
        # Match the 800px export's crop-before-resample geometry while
        # retaining the complete RGB frame for subsequent mask recovery.
        subject_size = (max(1, round((bbox[2]-bbox[0])*scale)),
                        max(1, round((bbox[3]-bbox[1])*scale)))
        anchor = (round(bbox[0]*scale), round(bbox[1]*scale))
        # Rounding the offset and the content dimensions independently can
        # exceed round(full_frame * scale) by one pixel at right/bottom edges.
        dimensions = tuple(max(1, round(d*scale), offset+extent)
                           for d,offset,extent in zip(source.size,anchor,subject_size))
        if max(*source.size, *dimensions) > MAX_PSD_SIDE:
            raise ValueError(f'高清PSD图层需要{dimensions}像素，超过PSD的30000像素限制；不会自动裁掉或降采样原图')
        rendered = subject.crop(bbox).resize(subject_size, Image.Resampling.LANCZOS)
        mask = Image.new('L', dimensions)
        mask.paste(rendered.getchannel('A'), anchor)
        rgb = source.convert('RGB').resize(dimensions, Image.Resampling.LANCZOS)
        rgb.paste(rendered.convert('RGB'), anchor, rendered.getchannel('A').point(lambda a: 255 if a else 0))
        rendered_bbox = mask.getbbox()
        left = (side - (rendered_bbox[2] - rendered_bbox[0])) // 2 - rendered_bbox[0]
        top = (side - (rendered_bbox[3] - rendered_bbox[1])) // 2 - rendered_bbox[1]
        product = dict(name=entry['name'], rgb=rgb, mask=mask, left=left, top=top,
                       visible=bool(entry.get('visible', len(products) == 0)))
        original = dict(name=entry['name'], rgb=source.convert('RGB'),
                        mask=source.getchannel('A'), left=0, top=0, visible=False)
        products.append(product)
        originals.append(original)
        source_alpha = np.asarray(source.getchannel('A'))
        candidate_alpha = np.asarray(subject.getchannel('A'))
        details.append(dict(name=entry['name'], source_size=list(source.size),
            source_rgba_sha256=_hash(source), candidate_rgba_sha256=_hash(subject),
            source_rgb_sha256=_hash(original['rgb']), source_alpha_sha256=_hash(original['mask']),
            candidate_alpha_bbox=list(bbox), requested_fill=fill, scale=scale,
            layer_size=list(dimensions), layer_offset=[left, top],
            rendered_alpha_bbox=[left+rendered_bbox[0], top+rendered_bbox[1],
                                 left+rendered_bbox[2], top+rendered_bbox[3]],
            rgb_sha256=_hash(rgb), mask_sha256=_hash(mask),
            native_removed_but_available_pixels=int(np.count_nonzero((source_alpha > 0) & (candidate_alpha == 0)))))
    return dict(size=(side, side), products=products, originals=originals,
        metadata=dict(format='high_resolution_pixels_with_independent_masks',
            canvas_size=[side, side], export_image_size=[800, 800],
            originals_group=ORIGINALS_GROUP, original_pixels_retained=True,
            downsampled_source=False, layers=details))


def _add_layer(document, data):
    # The name setter writes the Unicode tagged block and a safe Pascal name.
    layer = document.create_pixel_layer(data['rgb'].convert('RGB'), name='Layer',
        top=data['top'], left=data['left'])
    layer.name = data['name']
    layer.visible = data['visible']
    layer.create_mask(data['mask'], top=data['top'], left=data['left'])
    return layer


def write(path, assets, transparent=False):
    from psd_tools import PSDImage
    document = PSDImage.new('RGBA' if transparent else 'RGB', assets['size'])
    document.background_color = None
    if not transparent:
        background = document.create_pixel_layer(Image.new('RGB', assets['size'], 'white'), name='Background')
        background.name = '背景'
    for product in assets['products']:
        _add_layer(document, product)
    group = document.create_group(name='Originals', open_folder=False)
    group.name = ORIGINALS_GROUP
    group.visible = False
    for original in assets['originals']:
        group.append(_add_layer(document, original))
    # Groups add boundary records not counted by len(document/descendants).
    info = document._record.layer_and_mask_information.layer_info
    info.layer_count = (-1 if transparent else 1) * abs(info.layer_count)
    document.save(str(path))


def _exact(actual, expected, message):
    if actual is None or actual.size != expected.size or not np.array_equal(np.asarray(actual), np.asarray(expected)):
        raise RuntimeError(message)


def _same_composite(actual, expected, message):
    if actual is None or actual.size != expected.size:
        raise RuntimeError(message)
    a = np.asarray(actual.convert('RGBA')).astype(np.int16)
    b = np.asarray(expected.convert('RGBA')).astype(np.int16)
    # psd-tools' float compositor can round an opaque white background to
    # alpha 254; the independently stored mask itself is checked exactly.
    if np.max(np.abs(a[:, :, 3] - b[:, :, 3]), initial=0) > 1:
        raise RuntimeError(message + '（透明度不一致）')
    visible = b[:, :, 3] > 0
    if np.max(np.abs(a[:, :, :3][visible] - b[:, :, :3][visible]), initial=0) > 2:
        raise RuntimeError(message + '（可见RGB不一致）')


def _expected(assets, transparent, selected=None):
    result = Image.new('RGBA', assets['size'], (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    for index, data in enumerate(assets['products']):
        visible = data['visible'] if selected is None else index == selected
        if visible:
            result.alpha_composite(_rgba(data['rgb'], data['mask']), (data['left'], data['top']))
    return result


def _verify_layer(layer, data):
    if layer.name != data['name'] or layer.visible != data['visible']:
        raise RuntimeError('高清PSD图层名称或默认可见性错误')
    expected_bbox = (data['left'], data['top'], data['left']+data['rgb'].width, data['top']+data['rgb'].height)
    if tuple(layer.bbox) != expected_bbox or not layer.has_mask() or layer.mask.disabled:
        raise RuntimeError('高清PSD图层位置、独立蒙版或启用状态错误')
    if tuple(layer.mask.bbox) != expected_bbox:
        raise RuntimeError('高清PSD蒙版与像素层没有对齐')
    pixels = layer.topil(apply_icc=False)
    _exact(pixels.convert('RGB'), data['rgb'], '高清PSD RGB像素没有完整保存')
    if pixels.mode == 'RGBA' and pixels.getchannel('A').getextrema() != (255, 255):
        raise RuntimeError('高清PSD把抠图透明度重复写进像素层，导致蒙版无法恢复')
    _exact(layer.mask.topil(), data['mask'], '高清PSD独立蒙版像素不一致')


def verify(path, assets, transparent=False):
    """Reopen, validate recoverable RGB and masks, and switch every product."""
    from psd_tools import PSDImage
    document = PSDImage.open(path)
    expected_names = ([] if transparent else ['背景']) + [p['name'] for p in assets['products']] + [ORIGINALS_GROUP]
    if document.size != tuple(assets['size']) or [l.name for l in document] != expected_names:
        raise RuntimeError('高清PSD画布、图层顺序或命名错误')
    if not transparent:
        if not document[0].visible:
            raise RuntimeError('高清白底PSD背景不可见')
        _exact(document[0].topil().convert('RGB'), Image.new('RGB', assets['size'], 'white'), '高清PSD背景不是纯白')
    info = document._record.layer_and_mask_information.layer_info
    if transparent and (document.channels != 4 or info.layer_count >= 0):
        raise RuntimeError('高清透明PSD合并透明通道错误')
    products = list(document)[0 if transparent else 1:-1]
    group = document[-1]
    if not group.is_group() or group.visible or len(group) != len(assets['originals']):
        raise RuntimeError('高清PSD原始素材组缺失或没有隐藏')
    for layer, data in zip(products, assets['products']):
        _verify_layer(layer, data)
    for layer, data in zip(group, assets['originals']):
        _verify_layer(layer, data)
    _same_composite(document.composite(), _expected(assets, transparent), '高清PSD保存的默认合成图不一致')
    _same_composite(document.composite(force=True), _expected(assets, transparent), '高清PSD默认强制合成不一致')

    recovery_checks = []
    for index, (layer, data) in enumerate(zip(products, assets['products'])):
        for n, other in enumerate(products):
            other.visible = n == index
        _same_composite(document.composite(force=True), _expected(assets, transparent, index), '高清PSD逐层切换合成不一致')
        zeros = np.asarray(data['mask']) == 0
        # One-pixel viewport proves a disabled mask exposes saved RGB even
        # outside the document canvas, without allocating a huge composite.
        if zeros.any():
            y, x = map(int, np.unravel_index(int(zeros.argmax()), zeros.shape))
            left, top = data['left']+x, data['top']+y
            layer.mask.disabled = True
            restored = layer.composite(viewport=(left, top, left+1, top+1), force=True,
                                       layer_filter=lambda _: True)
            target = data['rgb'].crop((x, y, x+1, y+1)).convert('RGBA')
            _same_composite(restored, target, '高清PSD停用蒙版后不能恢复已保存像素')
            layer.mask.disabled = False
            recovery_checks.append(dict(name=data['name'], mask_disabled_reveals_rgb=True))
        else:
            recovery_checks.append(dict(name=data['name'], mask_disabled_reveals_rgb='not_applicable_no_fully_masked_pixels'))
    return dict(high_resolution_masks_verified=True, canvas_size=list(document.size),
        independent_product_masks=len(products), native_originals_verified=len(group),
        products_reopened_and_switched=True, source_rgb_and_alpha_exact=True,
        mask_recovery_checks=recovery_checks, merged_transparency_checked=bool(transparent))
