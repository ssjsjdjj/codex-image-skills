"""Bounded image encoding; preserve exact PNG pixels and verify every delivered byte count."""
from io import BytesIO
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFile

MAX_IMAGE_BYTES = 500_000
MAX_JPEG_MEAN_ERROR = 5.0
IMAGE_SIZE = (800, 800)


def verify_image_file(path):
    path = Path(path)
    size = path.stat().st_size
    if size > MAX_IMAGE_BYTES:
        raise RuntimeError(f"图片超限：{path}，{size}字节 > {MAX_IMAGE_BYTES}字节")
    expected_format = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG'}[path.suffix.lower()]
    with Image.open(path) as image:
        image.load()
        if image.format != expected_format or image.size != IMAGE_SIZE:
            raise RuntimeError(f"图片格式或800×800尺寸错误：{path}")
        if expected_format == 'PNG':
            low, high = image.convert('RGBA').getchannel('A').getextrema()
            if low == 255 or high == 0:
                raise RuntimeError(f"PNG缺少有效商品透明通道：{path}")
    return dict(bytes=size, max_bytes=MAX_IMAGE_BYTES, size_passed=True)


def _exact_palette(image):
    # Enumerate actual RGBA tuples instead of lossy quantization; alpha remains exact.
    colors = image.getcolors(maxcolors=256)
    if colors is None:
        return None
    palette = [rgba for _, rgba in colors]
    lookup = {rgba: index for index, rgba in enumerate(palette)}
    indexed = Image.new('P', image.size)
    indexed.putdata([lookup[pixel] for pixel in image.getdata()])
    rgb = [channel for rgba in palette for channel in rgba[:3]]
    indexed.putpalette(rgb + [0] * (768 - len(rgb)))
    indexed.info['transparency'] = bytes(rgba[3] for rgba in palette)
    return indexed


def save_limited_image(image, path, kind):
    """Try encoding changes, reopen candidates, then reject unresolved limits before publication."""
    path = Path(path)
    if kind not in ('white', 'transparent'):
        raise ValueError(f"未知图片类型：{kind}")
    image = image.convert('RGB' if kind == 'white' else 'RGBA')
    if image.size != IMAGE_SIZE:
        raise ValueError('正式图片必须为800×800，不通过缩小尺寸规避文件大小限制')
    expected_suffixes = ('.jpg', '.jpeg') if kind == 'white' else ('.png',)
    if path.suffix.lower() not in expected_suffixes:
        raise ValueError('输出扩展名与图片类型不一致')
    reference = np.asarray(image).astype(np.int16)
    attempts = []
    best = None

    def attempt(candidate, strategy, options):
        nonlocal best
        stream = BytesIO()
        # Pillow's optimized JPEG buffer estimate can be too small for detailed 4:4:4 images.
        # Exporters encode serially; restore the process setting after each candidate.
        previous_block = ImageFile.MAXBLOCK
        try:
            if kind == 'white':
                ImageFile.MAXBLOCK = max(previous_block, image.width * image.height * 4)
            candidate.save(stream, format='JPEG' if kind == 'white' else 'PNG', **options)
        finally:
            ImageFile.MAXBLOCK = previous_block
        data = stream.getvalue()
        with Image.open(BytesIO(data)) as decoded:
            decoded.load()
            actual = np.asarray(decoded.convert(image.mode)).astype(np.int16)
        error = float(np.mean(np.abs(actual - reference)))
        quality_ok = error <= MAX_JPEG_MEAN_ERROR if kind == 'white' else np.array_equal(actual, reference)
        detail = dict(strategy=strategy, bytes=len(data), quality_passed=bool(quality_ok),
                      mean_error=error, parameters=options)
        attempts.append(detail)
        if quality_ok and (best is None or len(data) < len(best)):
            best = data
        if len(data) <= MAX_IMAGE_BYTES and quality_ok:
            path.write_bytes(data)
            checked = verify_image_file(path)
            return dict(**checked, strategy=strategy, attempts=attempts,
                        compression_applied=len(attempts) > 1,
                        pixels_exact=kind == 'transparent', mean_error=error)
        return None

    if kind == 'white':
        result = attempt(image, 'jpeg-default', dict(quality=95, subsampling=0))
        if result:
            return result
        # Keep full chroma resolution; reject a smaller candidate if it exceeds the quality tolerance.
        for quality in (95, 93, 90, 87, 85, 82, 80, 77, 75):
            result = attempt(image, 'jpeg-optimized', dict(quality=quality, subsampling=0, optimize=True))
            if result:
                return result
    else:
        for strategy, options in (
            ('png-default', {}),
            ('png-lossless', dict(optimize=True, compress_level=9)),
        ):
            result = attempt(image, strategy, options)
            if result:
                return result
        indexed = _exact_palette(image)
        if indexed is not None:
            result = attempt(indexed, 'png-exact-palette', dict(optimize=True, compress_level=9))
            if result:
                return result

    # Preserve the best quality-valid candidate and the attempts in the staging area for diagnosis.
    if best is not None:
        path.write_bytes(best)
    detail_path = path.with_name(path.name + '.compression.json')
    detail_path.write_text(json.dumps(dict(max_bytes=MAX_IMAGE_BYTES, attempts=attempts,
                                          best_quality_valid_bytes=len(best) if best is not None else None),
                                     ensure_ascii=False, indent=2), encoding='utf-8')
    raise RuntimeError(f"图片自动压缩后仍无法同时满足500KB与画质要求：{path}；"
                       f"最小合格画质文件{len(best) if best is not None else '无'}字节；"
                       f"已尝试{len(attempts)}组参数；详情：{detail_path}。须调整方案并重新预览确认。")
