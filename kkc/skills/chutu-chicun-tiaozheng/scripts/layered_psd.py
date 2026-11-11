"""Lossless, independently switchable full-image layers for one Photoshop document.

The Photoshop panel reads from top to bottom in input order. psd-tools iterates
bottom to top, so its API layer order is the reverse of the input sequence.
All inputs must be RGB/RGBA, the same size, and carry the same ICC profile.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import unicodedata
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageChops


def _names(values: Sequence[str] | None, count: int) -> list[str]:
    if values is not None and (isinstance(values, (str, bytes, bytearray)) or not isinstance(values, Sequence)):
        raise ValueError("图层名称必须为文本序列，不能是单个字符串")
    result = [str(index + 1) for index in range(count)] if values is None else list(values)
    if len(result) != count:
        raise ValueError("图层名称数量必须与图片数量一致")
    seen = set()
    for name in result:
        if not isinstance(name, str) or not name or name.strip() != name:
            raise ValueError("图层名称必须为非空文本，且不含前后空白")
        if any(unicodedata.category(char).startswith('C') for char in name):
            raise ValueError("图层名称不能包含控制字符或无效Unicode字符")
        if len(name.encode('utf-16-be')) // 2 > 255:
            raise ValueError("图层名称不能超过255个UTF-16字符")
        key = unicodedata.normalize('NFC', name).casefold()
        if key in seen:
            raise ValueError("图层名称不能重复（忽略大小写和等价Unicode写法）")
        seen.add(key)
    return result


def _new_document(mode: str, size: tuple[int, int]):
    from psd_tools import PSDImage

    # frompil leaves the compositing backdrop transparent. PSDImage.new assigns
    # an opaque background color even for an RGBA canvas in psd-tools 1.25.
    document = PSDImage.frompil(Image.new(mode, size, (0, 0, 0, 0) if mode == 'RGBA' else (0, 0, 0)))
    if mode == 'RGBA':
        # psd-tools 1.25 uses this flag to write a negative layer count: the
        # merged image's fourth channel is transparency, not a spare alpha.
        # Without it reopening composite() discards the merged transparency.
        # The compatibility handling is local; installed psd-tools is unchanged.
        if not hasattr(document, '_merged_alpha'):
            raise RuntimeError("当前psd-tools不支持可靠的RGBA合成透明通道，请检查依赖版本")
        document._merged_alpha = True
    return document


def _rgba(image: Image.Image) -> Image.Image:
    return image if image.mode == 'RGBA' else image.convert('RGBA')


def _visible_pixels(image: Image.Image) -> Image.Image:
    rgba = _rgba(image)
    backdrop = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
    return Image.alpha_composite(backdrop, rgba).convert('RGB')


def _assert_composite(composite: Image.Image | None, source: Image.Image) -> None:
    if composite is None or composite.size != source.size:
        raise ValueError("PSD合成结果缺失或尺寸不符")
    rgba = _rgba(composite)
    expected = _rgba(source)
    if rgba.getchannel('A').tobytes() != expected.getchannel('A').tobytes():
        raise ValueError("PSD合成结果的透明通道与可见图片不一致")
    # A PSD's 8-bit, white-matted merged preview can differ by one LSB after
    # unmatting. Each individual layer is separately checked byte-for-byte,
    # including RGB values hidden by zero alpha; the preview is checked for
    # visible equivalence rather than comparing undefined transparent RGB.
    difference = ImageChops.difference(_visible_pixels(rgba), _visible_pixels(expected))
    if any(high > 1 for _, high in difference.getextrema()):
        raise ValueError("PSD合成结果与当前可见图片不符")


def _verify(path: Path, images: list[Image.Image], names: list[str], visible_index: int,
            profile: bytes | None) -> dict:
    from psd_tools import PSDImage
    from psd_tools.constants import Resource

    reopened = PSDImage.open(path)
    if reopened.size != images[0].size or len(reopened) != len(images):
        raise ValueError("重新打开PSD后尺寸或图层数量不符")
    expected_api_order = list(reversed(names))
    if [layer.name for layer in reopened] != expected_api_order:
        raise ValueError("重新打开PSD后图层顺序或名称不符")
    if reopened.image_resources.get_data(Resource.ICC_PROFILE) != profile:
        raise ValueError("重新打开PSD后ICC配置不一致")
    if [layer.name for layer in reopened if layer.visible] != [names[visible_index]]:
        raise ValueError("PSD必须仅显示指定的一个图片图层")
    by_name = {layer.name: layer for layer in reopened}
    layers = []
    for index, (source, name) in enumerate(zip(images, names)):
        layer = by_name[name]
        if layer.offset != (0, 0) or layer.size != source.size:
            raise ValueError("PSD图片图层位置或尺寸不符")
        decoded = layer.topil(apply_icc=False)
        if decoded is None or _rgba(decoded).tobytes() != _rgba(source).tobytes():
            raise ValueError("PSD图层像素与源图片不一致：" + name)
        layers.append({'index': index, 'name': name, 'visible': index == visible_index,
                       'pixel_sha256': hashlib.sha256(_rgba(source).tobytes()).hexdigest()})
    # Verify both the stored merged preview and recomposition after independent
    # layer switching. These in-memory switches do not alter the staged file.
    _assert_composite(reopened.composite(apply_icc=False), images[visible_index])
    for source, name in zip(images, names):
        for layer in reopened:
            layer.visible = layer.name == name
        _assert_composite(reopened.composite(force=True, ignore_preview=True, apply_icc=False), source)
    return {'size': list(reopened.size), 'layer_count': len(images), 'layers': layers,
            'panel_order': names, 'api_layer_order': expected_api_order,
            'visible_index': visible_index, 'visible_layers': [names[visible_index]],
            'icc_preserved': profile is not None, 'verified': True,
            'verification': {'exact_layer_pixels': True, 'independent_visibility': True,
                             'stored_composite': True, 'composite_visible_tolerance_lsb': 1}}


def write_layered_psd(path: str | os.PathLike, images: Iterable[Image.Image], *,
                      names: Sequence[str] | None = None, visible_index: int = 0) -> dict:
    """Write a verified multi-layer PSD without JPEG conversion or replacement.

    Input index 0 becomes panel layer ``1`` (top) by default. Exactly the input
    at ``visible_index`` is visible. Other images remain independent, full-size
    pixel layers that a designer can switch on. ICC data must match on all
    inputs, including absence; conflicting profiles require an explicit color
    management decision before constructing a document with one global profile.
    The PSD has no JPEG byte-size limit.
    """
    try:
        sources = list(images)
    except TypeError as exc:
        raise ValueError("images必须为PIL图片序列") from exc
    if not sources:
        raise ValueError("图片列表不能为空")
    if any(not isinstance(image, Image.Image) for image in sources):
        raise ValueError("每项输入必须为PIL.Image图片")
    if any(image.mode not in ('RGB', 'RGBA') for image in sources):
        raise ValueError("多图层PSD仅接受RGB或RGBA，不静默转换其他色彩模式")
    size = sources[0].size
    if min(size) < 1 or max(size) > 30000 or any(image.size != size for image in sources):
        raise ValueError("所有图片必须同尺寸，且各边在PSD支持的1~30000像素范围内")
    if type(visible_index) is not int or not 0 <= visible_index < len(sources):
        raise ValueError("visible_index必须是图片列表范围内的整数索引")
    layer_names = _names(names, len(sources))
    profiles = [image.info.get('icc_profile') or None for image in sources]
    if any(value is not None and not isinstance(value, bytes) for value in profiles):
        raise ValueError("ICC配置必须为原始bytes数据")
    if any(value != profiles[0] for value in profiles[1:]):
        raise ValueError("源图片ICC配置不一致，不能静默合并到同一个PSD色彩空间")
    destination = Path(path).expanduser().absolute()
    if destination.suffix.lower() != '.psd':
        raise ValueError("输出文件必须使用.psd扩展名")
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("PSD已存在，不覆盖：" + str(destination))

    from psd_tools.api.layers import PixelLayer
    from psd_tools.constants import Resource
    from psd_tools.psd.image_resources import ImageResource

    mode = 'RGBA' if any(image.mode == 'RGBA' for image in sources) else 'RGB'
    document = _new_document(mode, size)
    profile = profiles[0]
    if profile is not None:
        document.image_resources[Resource.ICC_PROFILE] = ImageResource(key=Resource.ICC_PROFILE, data=profile)
    # append() adds at the panel top. Insert input N first, then N-1 ... 1.
    for index in reversed(range(len(sources))):
        layer = PixelLayer.frompil(sources[index], document, 'Layer', 0, 0)
        # The public setter writes the Unicode name plus a safe Pascal fallback.
        layer.name = layer_names[index]
        layer.visible = index == visible_index

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix='.layered-psd-', suffix='.psd', dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        document.save(temporary)
        metadata = _verify(temporary, sources, layer_names, visible_index, profile)
        # Hard-link publication on the same volume is atomic and never replaces
        # an existing destination, including one created while we were saving.
        os.link(temporary, destination)
        metadata.update(path=str(destination), mode=mode, file_bytes=destination.stat().st_size,
                        sha256=hashlib.sha256(destination.read_bytes()).hexdigest())
        return metadata
    finally:
        temporary.unlink(missing_ok=True)
