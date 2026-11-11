"""Explicit per-image mask edits; no guessed holes or product-specific coordinates."""
from pathlib import Path
import numpy as np
from PIL import Image

MASK_FIELDS = ('protect_mask', 'keep_mask', 'remove_mask')


def validate_job(job):
    for field in MASK_FIELDS:
        value = job.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f'{field}须为绝对路径')
        if not Path(value).is_file():
            raise FileNotFoundError(value)
        job[field] = str(Path(value).resolve())
    if 'repair_existing_alpha' in job and type(job['repair_existing_alpha']) is not bool:
        raise ValueError('repair_existing_alpha必须为JSON布尔值')
    regions = job.get('review_regions', [])
    if not isinstance(regions, list):
        raise ValueError('review_regions须为800×800预览坐标的矩形列表')
    for box in regions:
        if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
            raise ValueError('review_regions每项须为四个整数[left,top,right,bottom]')
        if not (0 <= box[0] < box[2] <= 800 and 0 <= box[1] < box[3] <= 800):
            raise ValueError('review_regions须位于800×800预览内')


def load(job, size):
    masks = {}
    for field in MASK_FIELDS:
        if job.get(field):
            with Image.open(job[field]) as image:
                if image.size != size:
                    raise ValueError(f'{field}尺寸必须与EXIF转正后的原图一致：{size}')
                masks[field] = image.convert('L').copy()
    keep = np.asarray(masks['keep_mask']) > 0 if 'keep_mask' in masks else np.zeros(size[::-1], bool)
    protect = np.asarray(masks['protect_mask']) > 0 if 'protect_mask' in masks else np.zeros(size[::-1], bool)
    remove = np.asarray(masks['remove_mask']) > 0 if 'remove_mask' in masks else np.zeros(size[::-1], bool)
    if np.any(remove & (keep | protect)):
        raise ValueError('删除蒙版与保留/保护蒙版重叠，请先明确该区域的处理意图')
    return masks


def apply(subject, source, masks):
    """White keep restores original RGBA; white remove clears alpha; gray blends coverage."""
    before = np.asarray(subject.convert('RGBA')).copy()
    original = np.asarray(source.convert('RGBA'))
    result = before.copy()
    if 'keep_mask' in masks:
        weight = np.asarray(masks['keep_mask'], dtype=np.uint32)[:, :, None]
        result = ((result.astype(np.uint32) * (255-weight) + original.astype(np.uint32)*weight + 127)//255).astype(np.uint8)
    if 'remove_mask' in masks:
        weight = np.asarray(masks['remove_mask'], dtype=np.uint32)
        result[:, :, 3] = ((result[:, :, 3].astype(np.uint32)*(255-weight)+127)//255).astype(np.uint8)
    protected = np.zeros(subject.size[::-1], np.uint8)
    for field in ('protect_mask', 'keep_mask'):
        if field in masks:
            protected = np.maximum(protected, np.asarray(masks[field]))
    protected_image = Image.fromarray(protected) if protected.any() else None
    changed = np.any(result != before, axis=2)
    active = np.zeros(subject.size[::-1], bool)
    for field in ('keep_mask', 'remove_mask'):
        if field in masks:
            active |= np.asarray(masks[field]) > 0
    if np.any(changed & ~active):
        raise RuntimeError('局部蒙版编辑越界')
    metadata = dict(applied=[field for field in ('keep_mask','remove_mask') if field in masks],
                    modified_pixels=int(changed.sum()), outside_edit_masks_unchanged=True,
                    removed_alpha_pixels=int(np.count_nonzero((before[:,:,3]>0)&(result[:,:,3]==0))))
    return Image.fromarray(result), protected_image, metadata
