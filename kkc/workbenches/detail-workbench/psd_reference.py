"""Read the saved RGB composite without opening Photoshop or decoding layers."""

import os
import struct
import tempfile
import zlib
from pathlib import Path

from PIL import Image, ImageMath


MAX_COMPOSITE_BYTES = 512 * 1024 * 1024


def _read(source, length):
    data = source.read(length)
    if len(data) != length:
        raise ValueError("Incomplete Photoshop composite")
    return data


def _number(source, version=1):
    return struct.unpack(">I" if version == 1 else ">Q", _read(source, 4 if version == 1 else 8))[0]


def _skip(source, length, end):
    target = source.tell() + length
    if target > end:
        raise ValueError("Photoshop section extends beyond the file")
    source.seek(target)


def _resources(source, end):
    profile = None
    while source.tell() < end:
        if _read(source, 4) not in {b"8BIM", b"MeSa"}:
            raise ValueError("Invalid Photoshop image resource")
        resource = struct.unpack(">H", _read(source, 2))[0]
        name_length = _read(source, 1)[0]
        _skip(source, name_length + ((name_length + 1) % 2), end)
        length = _number(source)
        if source.tell() + length + length % 2 > end:
            raise ValueError("Invalid Photoshop resource length")
        if resource == 1057:
            if length < 5 or _read(source, 5)[4] == 0:
                raise ValueError("Photoshop saved without a real merged image")
            _skip(source, length - 5, end)
        elif resource == 1039 and length <= 4 * 1024 * 1024:
            profile = _read(source, length)
        else:
            _skip(source, length, end)
        _skip(source, length % 2, end)
    return profile


def _packbits_plane(data, counts, width, height):
    offset = 0
    for count in counts:
        end = offset + count
        decoded = 0
        while offset < end:
            control = data[offset]
            offset += 1
            if control <= 127:
                length = control + 1
                offset += length
                decoded += length
            elif control >= 129:
                offset += 1
                decoded += 257 - control
            if offset > end or decoded > width:
                raise ValueError("Invalid Photoshop RLE row")
        if decoded != width:
            raise ValueError("Incomplete Photoshop RLE row")
    return Image.frombytes("L", (width, height), data, "packbits", "L")


def _planes(source, compression, width, height, channels, count, version, file_size):
    plane_size = width * height
    total = plane_size * channels
    if compression == 0:
        if source.tell() + total != file_size:
            raise ValueError("Invalid raw composite length")
        return [Image.frombytes("L", (width, height), _read(source, plane_size)) for _ in range(count)]
    if compression == 1:
        row_count = height * channels
        row_format = "H" if version == 1 else "I"
        lengths = struct.unpack(">" + row_format * row_count, _read(source, row_count * (2 if version == 1 else 4)))
        if source.tell() + sum(lengths) != file_size:
            raise ValueError("Invalid RLE composite length")
        result = []
        for index in range(count):
            rows = lengths[index * height : (index + 1) * height]
            result.append(_packbits_plane(_read(source, sum(rows)), rows, width, height))
        return result
    if compression not in {2, 3}:
        raise ValueError("Unsupported Photoshop composite compression")
    remaining = file_size - source.tell()
    if remaining > total + 1024 * 1024:
        raise ValueError("Oversized ZIP composite")
    decoder = zlib.decompressobj()
    data = decoder.decompress(_read(source, remaining), total + 1)
    if len(data) != total or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError("Invalid ZIP composite length")
    result = []
    for index in range(count):
        plane = data[index * plane_size : (index + 1) * plane_size]
        if compression == 3:
            plane = bytearray(plane)
            for row in range(height):
                start = row * width
                for column in range(start + 1, start + width):
                    plane[column] = (plane[column] + plane[column - 1]) & 255
            plane = bytes(plane)
        result.append(Image.frombytes("L", (width, height), plane))
    return result


def _transparent_image(planes, width, height):
    colors = []
    # Photoshop saves the RGB composite over white. Remove that matte only
    # for a transparent PNG, in strips to bound floating-point work buffers.
    for plane in planes[:3]:
        color = Image.new("L", (width, height))
        for top in range(0, height, 512):
            region = (0, top, width, min(height, top + 512))
            strip = ImageMath.lambda_eval(
                lambda values: values["convert"](
                    (values["float"](values["color"]) + values["alpha"] - 255) * 255
                    / values["float"](values["max"](values["alpha"], 1)), "L"),
                color=plane.crop(region), alpha=planes[3].crop(region))
            color.paste(strip, region)
        colors.append(color)
    return Image.merge("RGBA", colors + [planes[3]])


def extract_merged_preview(source, output):
    """Save a full saved-composite reference, or return False for native fallback.

    Only RGB 8-bit PSD/PSB composites are supported. Spot channels are ignored.
    A fourth channel is transparency only when the layer count declares it so.
    """
    temporary = None
    try:
        source, output = Path(source), Path(output)
        if source.resolve() == output.resolve() or (output.exists() and source.samefile(output)):
            return False
        suffix = output.suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png"}:
            return False
        before = source.stat()
        with source.open("rb") as stream:
            signature, version, reserved, channels, height, width, depth, mode = struct.unpack(
                ">4sH6sHIIHH", _read(stream, 26))
            if (signature != b"8BPS" or version not in {1, 2} or reserved != bytes(6)
                    or not 3 <= channels <= 56 or depth != 8 or mode != 3
                    or not 1 <= width <= 300000 or not 1 <= height <= 300000
                    or width * height * channels > MAX_COMPOSITE_BYTES):
                return False
            _skip(stream, _number(stream), before.st_size)
            resource_end = stream.tell() + 4
            resource_end += _number(stream)
            if resource_end > before.st_size:
                return False
            profile = _resources(stream, resource_end)
            layer_length = _number(stream, version)
            layer_start = stream.tell()
            if layer_start + layer_length > before.st_size:
                return False
            transparency = False
            if layer_length:
                info_length = _number(stream, version)
                if info_length > layer_length - (4 if version == 1 else 8):
                    return False
                if info_length >= 2:
                    transparency = struct.unpack(">h", _read(stream, 2))[0] < 0
            stream.seek(layer_start + layer_length)
            compression = struct.unpack(">H", _read(stream, 2))[0]
            count = 4 if transparency and channels >= 4 else 3
            planes = _planes(stream, compression, width, height, channels, count, version, before.st_size)
        image = (_transparent_image(planes, width, height) if count == 4 and suffix == ".png"
                 else Image.merge("RGB", planes[:3]))
        scale = min(1, 790 / width, 60000 / height)
        if scale < 1:
            image = image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.LANCZOS)
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return False
        with tempfile.NamedTemporaryFile(prefix=".reference-", suffix=suffix, dir=output.parent, delete=False) as staged:
            temporary = Path(staged.name)
        options = {"icc_profile": profile} if profile else {}
        if suffix == ".png":
            image.save(temporary, format="PNG", **options)
        else:
            image.save(temporary, format="JPEG", quality=95, **options)
        os.replace(temporary, output)
        return True
    except (OSError, ValueError, struct.error, zlib.error, MemoryError, OverflowError):
        return False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
