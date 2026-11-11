"""Encode JPG/PNG within an explicit byte budget without resizing pixels.

JPG may lower its integer quality (and uses ordinary 4:2:0 encoding). PNG stays
lossless: no palette quantization, alpha removal, resizing or format fallback.
"""
import io

from PIL import Image

DEFAULT_MAX_BYTES = 500_000


def _integer(value, name, lower, upper=None):
    if type(value) is not int or value < lower or (upper is not None and value > upper):
        extent = f"{lower}~{upper}" if upper is not None else f">={lower}"
        raise ValueError(f"{name}必须是{extent}的整数")
    return value


def _icc(image, explicit):
    value = image.info.get("icc_profile") if explicit is None else explicit
    if value is None:
        return {}
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ValueError("icc_profile必须是bytes或None")
    return {"icc_profile": bytes(value)}


def _jpeg_pixels(image):
    if image.mode == "CMYK":
        raise ValueError("CMYK图片需先执行明确的色彩管理转换，不能静默转为RGB")
    if image.mode not in ("RGB", "RGBA", "L", "LA", "P", "1"):
        raise ValueError(f"JPG不支持直接导出图像模式{image.mode}")
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(white, rgba).convert("RGB")
    return image.convert("RGB")


def encode_image(image, fmt, *, max_bytes=DEFAULT_MAX_BYTES,
                 min_quality=60, max_quality=95, icc_profile=None):
    """Return ``(encoded_bytes, metadata)`` or reject an unattainable budget.

    ``fmt`` accepts jpg/jpeg/png (case insensitive). JPG searches quality from
    max_quality down to min_quality inclusive and returns the highest fitting
    integer quality. The source Image and its pixel dimensions are unchanged.
    RGB ICC metadata is carried through unless explicitly overridden. No color
    management conversion is performed here.
    """
    if not isinstance(image, Image.Image) or image.width < 1 or image.height < 1:
        raise ValueError("image必须是非空Pillow Image")
    if not isinstance(fmt, str):
        raise ValueError("format必须是jpg/jpeg/png")
    fmt = fmt.strip().lower()
    fmt = "jpg" if fmt == "jpeg" else fmt
    if fmt not in ("jpg", "png"):
        raise ValueError("format只支持jpg/jpeg/png")
    _integer(max_bytes, "max_bytes", 1)
    _integer(min_quality, "min_quality", 1, 100)
    _integer(max_quality, "max_quality", 1, 100)
    if min_quality > max_quality:
        raise ValueError("min_quality不能大于max_quality")
    color_metadata = _icc(image, icc_profile)

    if fmt == "png":
        if image.mode not in ("1", "L", "LA", "P", "RGB", "RGBA", "I;16"):
            # Pillow can clip 32-bit I samples to 16-bit while saving PNG. Refuse
            # such implicit conversions instead of reporting a lossless export.
            raise ValueError(f"PNG不能保证图像模式{image.mode}的原始像素无损导出")
        stream = io.BytesIO()
        try:
            # Copy protects caller state while retaining palette/transparency info.
            image.copy().save(stream, format="PNG", optimize=True,
                              compress_level=9, **color_metadata)
        except (OSError, ValueError, SystemError) as error:
            raise ValueError(f"PNG不能在保持原像素及颜色模式时导出：{error}") from error
        data = stream.getvalue()
        if len(data) > max_bytes:
            raise ValueError(f"PNG无损优化后为{len(data)}字节，超过预算{max_bytes}字节；"
                             "未量化、未缩尺寸、未移除alpha或转为JPG")
        return data, {"format": "png", "bytes": len(data),
                      "quality": None, "max_bytes": max_bytes}

    pixels = _jpeg_pixels(image)
    # A non-RGB embedded profile cannot safely be attached after an implicit RGB
    # conversion. Explicit ICC is a caller-supplied RGB profile.
    if icc_profile is None and image.mode not in ("RGB", "RGBA"):
        color_metadata = {}
    smallest = None
    for quality in range(max_quality, min_quality - 1, -1):
        stream = io.BytesIO()
        pixels.save(stream, format="JPEG", quality=quality, subsampling=2,
                    optimize=True, **color_metadata)
        data = stream.getvalue()
        smallest = len(data) if smallest is None else min(smallest, len(data))
        if len(data) <= max_bytes:
            return data, {"format": "jpg", "bytes": len(data),
                          "quality": quality, "max_bytes": max_bytes}
    raise ValueError(f"JPG在质量{min_quality}~{max_quality}范围内最小为{smallest}字节，"
                     f"仍超过预算{max_bytes}字节；像素尺寸保持{image.width}x{image.height}")
