"""Write/verify 8-bit PNG + genuinely masked PSD. No image generation or visual verdicts."""
from pathlib import Path

import numpy as np
from PIL import Image


def same(a, b, message):
    if a is None or a.size != b.size or not np.array_equal(np.asarray(a), np.asarray(b)):
        raise ValueError(message)


def near_composite(a, b):
    if a is None or a.size != b.size:
        raise ValueError('PSD rendered dimensions differ')
    aa, bb = np.asarray(a.convert('RGBA')).astype('int16'), np.asarray(b.convert('RGBA')).astype('int16')
    visible = (aa[:, :, 3] > 0) | (bb[:, :, 3] > 0)
    delta = np.abs(aa - bb)
    maximum = int(delta[visible].max(initial=0))
    # Independent float rendering may round channel values at a masked edge.
    if maximum > 2:
        raise ValueError(f'PSD rendered layers disagree with PNG: max delta {maximum}')
    return maximum


def edited_extent(patches):
    return (min(p['xy'][0] for p in patches), min(p['xy'][1] for p in patches),
            max(p['xy'][0] + p['pixels'].width for p in patches),
            max(p['xy'][1] + p['pixels'].height for p in patches))


def verify(psd_path, png_path, source, baseline, patches):
    from psd_tools import PSDImage
    document = PSDImage.open(psd_path)
    final = Image.open(png_path)
    final.load()
    expected_names = ['Original'] + (['Baseline'] if baseline is not source else [])
    expected_names += [p['id'] for p in patches]
    if document.size != baseline.size or [l.name for l in document] != expected_names:
        raise ValueError('PSD layers/order/dimensions are not the requested stack')
    original = document[0]
    same(original.topil(apply_icc=False).convert('RGBA'), source.convert('RGBA'), 'Original pixels lost')
    if original.locks is None or not original.locks.complete:
        raise ValueError('Original layer is not locked')
    start = 1
    if len(expected_names) > len(patches) + 1:
        same(document[1].topil(apply_icc=False).convert('RGBA'), baseline.convert('RGBA'), 'Baseline pixels lost')
        start += 1
    for layer, patch in zip(list(document)[start:], patches):
        x, y = patch['xy']
        expected_box = (x, y, x + patch['pixels'].width, y + patch['pixels'].height)
        if tuple(layer.bbox) != expected_box or not layer.visible or not layer.has_mask() or layer.mask.disabled:
            raise ValueError('PSD patch position/visibility/editable mask invalid')
        same(layer.topil(apply_icc=False).convert('RGB'), patch['pixels'].convert('RGB'), 'Patch pixels were flattened or lost')
        same(layer.mask.topil(), patch['mask'], 'Editable mask differs from compositing mask')
        if tuple(layer.mask.bbox) != expected_box:
            raise ValueError('Mask offset differs from patch')
        # Disabling the mask must reveal the stored opaque candidate, including
        # the concealed portion; never bake edit opacity into both pixels+mask.
        layer.mask.disabled = True
        same(layer.composite(viewport=expected_box, force=True, apply_icc=False).convert('RGB'),
             patch['pixels'].convert('RGB'), 'Disabled mask does not reveal candidate pixels')
        layer.mask.disabled = False
    same(document.topil(apply_icc=False).convert('RGBA'), final.convert('RGBA'), 'PSD merged preview differs from PNG')
    extent = edited_extent(patches)
    delta = near_composite(document.composite(viewport=extent, force=True, apply_icc=False), final.crop(extent))
    for layer in list(document)[start:]:
        layer.visible = False
    near_composite(document.composite(viewport=extent, force=True, apply_icc=False), baseline.crop(extent))
    return {'original_pixels_preserved': True, 'editable_masks': len(patches),
            'merged_png_exact': True, 'independent_render_max_delta': delta,
            'layers_toggled_and_masks_disabled': True}


def write(psd_path, png_path, source, baseline, final, patches, icc=None):
    from psd_tools import PSDImage
    from psd_tools.constants import Tag
    from psd_tools.psd.image_resources import ImageResource
    from psd_tools.psd.tagged_blocks import ProtectedSetting
    if max(baseline.size) > 30000:
        raise ValueError('PSD exceeds 30000 px; no automatic resizing/PSB fallback')
    if any(p.mode not in ('RGB', 'RGBA') for p in (source, baseline, final)):
        raise ValueError('PSD helper supports 8-bit RGB/RGBA only')
    document = PSDImage.new('RGBA' if baseline.mode == 'RGBA' else 'RGB', baseline.size)
    document.background_color = None
    original = document.create_pixel_layer(source, name='Original')
    original.tagged_blocks.set_data(Tag.PROTECTED_SETTING, ProtectedSetting(2147483648))
    if baseline is not source:
        layer = document.create_pixel_layer(baseline, name='Baseline')
        layer.tagged_blocks.set_data(Tag.PROTECTED_SETTING, ProtectedSetting(2147483648))
    for patch in patches:
        x, y = patch['xy']
        layer = document.create_pixel_layer(patch['pixels'].convert('RGB'), name=patch['id'], left=x, top=y)
        layer.create_mask(patch['mask'], left=x, top=y)
    if icc:
        document.image_resources[1039] = ImageResource(key=1039, data=icc)
    # A negative layer count declares the merged transparency channel.
    if baseline.mode == 'RGBA':
        document._record.layer_and_mask_information.layer_info.layer_count = -len(document)
    # Render only the edited extent. Full-resolution unchanged photos need not
    # be recomposited repeatedly. The native layers and merged image remain full-size.
    extent = edited_extent(patches)
    near_composite(document.composite(viewport=extent, force=True, apply_icc=False), final.crop(extent))
    # Keep the exact integer preview only after the independent render agrees.
    # This small format adapter targets psd-tools 1.25+; reopen verification below
    # catches missing channels, masks or changed assumptions in future versions.
    document._record.image_data.set_data([c.tobytes() for c in final.split()], document._record.header)
    with open(psd_path, 'wb') as handle:
        document._record.write(handle)
    if Path(psd_path).stat().st_size >= 2_000_000_000:
        raise ValueError('PSD approaches format file-size limit; no silent flattening')
    final.save(png_path, format='PNG', compress_level=4, **({'icc_profile': icc} if icc else {}))
    return verify(psd_path, png_path, source, baseline, patches)
