"""Local evidence, bounded composition, editable PSD, and final-file release.

No fabric detector, sharpness score, generation engine, or automatic visual pass.
Run --help; read references/tools.md only when using this helper.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageOps

VERSION = '1'
VERDICTS = {'unreviewed', 'normal', 'abnormal', 'uncertain', 'natural_soft', 'occluded'}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def resolve(value, root):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('A real file path is required')
    p = Path(value)
    p = (root / p if not p.is_absolute() else p).resolve()
    if not p.is_file():
        raise ValueError(f'Input does not exist: {p}')
    return p


def ident(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
        raise ValueError(f'Invalid/unsafe ID or output stem: {value!r}')
    if re.fullmatch(r'CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]', value, re.I):
        raise ValueError('Windows reserved filename')
    return value


def bounds(value, size):
    if not isinstance(value, list) or len(value) != 4 or any(type(v) is not int for v in value):
        raise ValueError('box must be integer [left,top,right,bottom], EXIF-oriented pixels')
    l, t, r, b = value
    if not (0 <= l < r <= size[0] and 0 <= t < b <= size[1]):
        raise ValueError(f'Crop out of bounds: {value} for {size}')
    return tuple(value)


class Assets:
    """Hash content once per command, hold at most two decoded photographs."""
    def __init__(self):
        self.fingerprints = {}
        self.decoded = OrderedDict()

    def bind(self, path):
        path = Path(path).resolve()
        key = str(path)
        if key not in self.fingerprints:
            self.fingerprints[key] = digest(path)
        return {'path': key, 'sha256': self.fingerprints[key]}

    def image(self, path):
        key = str(Path(path).resolve())
        if key in self.decoded:
            self.decoded.move_to_end(key)
            return self.decoded[key]
        self.bind(path)
        with Image.open(path) as source:
            if source.mode not in ('RGB', 'RGBA', 'L'):
                raise ValueError(f'Unsupported mode {source.mode}: explicitly normalize a copy first')
            image = ImageOps.exif_transpose(source)
            image.load()
            image = image.copy()
        self.decoded[key] = image
        while len(self.decoded) > 2:
            self.decoded.popitem(last=False)
        return image

    def bound_input(self, data, root):
        if not isinstance(data, dict) or not re.fullmatch(r'[a-f0-9]{64}', data.get('sha256', '')):
            raise ValueError('Repair inputs require an explicit content SHA256')
        path = resolve(data.get('path'), root)
        binding = self.bind(path)
        if binding['sha256'] != data['sha256']:
            raise ValueError(f'Stale/replaced input: {path}')
        return path

    def snapshot(self):
        return [{'path': p, 'sha256': h} for p, h in sorted(self.fingerprints.items())]


def load_manifest(path, assets, image_id=None):
    path = Path(path).resolve()
    data = read_json(path)
    if data.get('schema') != 1 or not isinstance(data.get('images'), list) or not data['images']:
        raise ValueError('Expected schema:1 and a nonempty images list')
    seen_images = set()
    images = []
    for entry in data['images']:
        iid = ident(entry.get('id'))
        if iid in seen_images:
            raise ValueError('Duplicate image ID')
        seen_images.add(iid)
        if image_id is not None and iid != image_id:
            continue
        source = resolve(entry.get('source'), path.parent)
        baseline = resolve(entry.get('baseline', entry['source']), path.parent)
        src, base = assets.image(source), assets.image(baseline)
        if src.size != base.size or src.mode != base.mode or src.mode not in ('RGB', 'RGBA'):
            raise ValueError('Source and baseline must be same-size RGB/RGBA; no implicit conversion')
        if src.info.get('icc_profile') != base.info.get('icc_profile'):
            raise ValueError('Source/baseline profiles differ; normalize explicitly')
        groups, seen_groups = [], set()
        for group in entry.get('groups', []):
            gid = ident(group.get('id'))
            if gid in seen_groups or not group.get('object') or not group.get('label'):
                raise ValueError('Group needs unique ID, object and material label')
            seen_groups.add(gid)
            reference = resolve(group['reference'], path.parent) if group.get('reference') else None
            ref = assets.image(reference) if reference else None
            regions, seen_regions = [], set()
            for region in group.get('regions', []):
                rid, verdict = ident(region.get('id')), region.get('verdict', 'unreviewed')
                if rid in seen_regions or verdict not in VERDICTS:
                    raise ValueError('Duplicate region ID or unknown verdict')
                seen_regions.add(rid)
                box = None if region.get('box') is None else bounds(region['box'], base.size)
                if box is None and verdict != 'occluded':
                    raise ValueError('Visible/unreviewed regions require coordinates')
                if verdict != 'unreviewed' and not str(region.get('note', '')).strip():
                    raise ValueError('Every visual judgment needs a real observation')
                rb = bounds(region['reference_box'], ref.size) if ref is not None and region.get('reference_box') else None
                if region.get('reference_box') and ref is None:
                    raise ValueError('Reference crop requires a real reference')
                regions.append(dict(region, id=rid, verdict=verdict, box=box, reference_box=rb))
            if not regions:
                raise ValueError('Material group needs visible/occluded coverage records')
            groups.append(dict(group, id=gid, reference=str(reference) if reference else None, regions=regions))
        if not groups:
            raise ValueError('Image needs material groups')
        images.append(dict(entry, id=iid, source=str(source), baseline=str(baseline), groups=groups))
    return images


def save_png(image, path):
    image.save(path, format='PNG', compress_level=4,
               **({'icc_profile': image.info['icc_profile']} if image.info.get('icc_profile') else {}))


def cached_crop(path, box, cache, assets):
    binding = assets.bind(path)
    key = hashlib.sha256(json.dumps([VERSION, binding['sha256'], box, 'exif-oriented']).encode()).hexdigest()
    target, meta = cache / f'{key}.png', cache / f'{key}.json'
    try:
        cached_hash = digest(target) if target.is_file() else None
        valid_cache = cached_hash is not None and meta.is_file() and read_json(meta).get('sha256') == cached_hash
    except (ValueError, OSError):
        valid_cache = False
    if valid_cache:
        return {'path': str(target), 'sha256': cached_hash, 'source': binding, 'box': box, 'cached': True}
    cropped = assets.image(path).crop(box)
    save_png(cropped, target)
    write_json(meta, {'sha256': digest(target)})
    return {'path': str(target), 'sha256': digest(target), 'source': binding, 'box': box, 'cached': False}


def contact_sheet(rows, path, width=360, height=300):
    # Independently fitted thumbnails are NAVIGATION ONLY, never a scale match.
    cols = max(len(row) for row in rows)
    sheet = Image.new('RGB', (cols * width, len(rows) * height), 'white')
    draw = ImageDraw.Draw(sheet)
    for r, row in enumerate(rows):
        for c, (label, asset) in enumerate(row):
            draw.text((c * width + 6, r * height + 4), label, fill='black')
            if asset:
                with Image.open(asset) as im:
                    im = im.convert('RGB')
                    im.thumbnail((width - 12, height - 30))
                    sheet.paste(im, (c * width + 6, r * height + 24))
    save_png(sheet, path)


def prepare(manifest, work):
    assets = Assets()
    assets.bind(manifest)
    images = load_manifest(manifest, assets)
    work = Path(work).resolve()
    cache = work / 'crop-cache'
    cache.mkdir(parents=True, exist_ok=True)
    inventories = []
    for entry in images:
        groups = []
        for group in entry['groups']:
            rows, regions = [], []
            for region in group['regions']:
                item = dict(region)
                if region['box'] is not None:
                    item['native'] = cached_crop(entry['baseline'], region['box'], cache, assets)
                    item['reference_native'] = cached_crop(group['reference'], region['reference_box'], cache, assets) if region['reference_box'] else None
                    rows.append([(f"{region['id']} baseline native crop", item['native']['path']),
                                 ('Reference native crop', item['reference_native']['path'] if item['reference_native'] else None)])
                regions.append(item)
            sheet = work / f"{entry['id']}-{group['id']}-navigation.png"
            if rows:
                contact_sheet(rows, sheet)
            groups.append(dict(group, regions=regions, navigation=str(sheet) if rows else None))
        inventories.append(dict(entry, groups=groups))
    record = work / 'inventory.json'
    write_json(record, {'schema': 1, 'coordinate_space': 'EXIF-oriented source pixels',
                       'navigation': 'Independent thumbnail fit; inspect native crops and match garment landmarks',
                       'visual_status': 'not_reviewed', 'images': inventories, 'inputs': assets.snapshot()})
    return {'inventory': str(record), 'images': len(images), 'visual_status': 'not_reviewed'}


def load_mask(path, size, assets, binary=False):
    im = assets.image(path)
    if im.mode != 'L' or im.size != size:
        raise ValueError('Masks must be explicit grayscale L, exact native dimensions')
    arr = np.asarray(im)
    if binary and np.any((arr != 0) & (arr != 255)):
        raise ValueError('Allowed/protection masks must be binary 0/255')
    return im.copy(), arr


def compose(manifest, job_path, work):
    assets = Assets()
    job_path = Path(job_path).resolve()
    assets.bind(job_path)
    job = read_json(job_path)
    images = load_manifest(manifest, assets, image_id=job.get('image_id'))
    matches = [entry for entry in images if entry['id'] == job.get('image_id')]
    if len(matches) != 1:
        raise ValueError('Repair job must identify one manifest image')
    entry = matches[0]
    src_path = assets.bound_input(job.get('source'), job_path.parent)
    base_path = assets.bound_input(job.get('baseline'), job_path.parent)
    if str(src_path) != entry['source'] or str(base_path) != entry['baseline']:
        raise ValueError('Job image identity differs from coverage manifest')
    source, baseline = assets.image(src_path), assets.image(base_path)
    baseline_alpha = np.asarray(baseline.getchannel('A')) if baseline.mode == 'RGBA' else None
    final = baseline.copy()
    protection_path = assets.bound_input(job.get('protect_mask'), job_path.parent)
    _, protected = load_mask(protection_path, baseline.size, assets, binary=True)
    union = np.zeros((baseline.height, baseline.width), dtype=bool)
    patches, ids = [], set()
    jobs = job.get('patches')
    if not isinstance(jobs, list) or not jobs:
        raise ValueError('A repair job requires actual authorized patches')
    for patch in jobs:
        pid = ident(patch.get('id'))
        if pid in ids or patch.get('authorized') is not True:
            raise ValueError('Duplicate patch ID or no existing user authorization')
        ids.add(pid)
        groups = [g for g in entry['groups'] if g['id'] == patch.get('group')]
        if len(groups) != 1:
            raise ValueError('Patch must bind one existing material group')
        group = groups[0]
        selected = patch.get('regions')
        if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected):
            raise ValueError('Patch must list unique covered abnormal region IDs')
        regions = [r for r in group['regions'] if r['id'] in selected]
        if len(regions) != len(selected) or any(r['verdict'] != 'abnormal' for r in regions):
            raise ValueError('Normal/uncertain/unreviewed/unknown regions cannot be edited')
        if not group['reference'] or not all(r['reference_box'] is not None for r in regions):
            raise ValueError('Confirmed texture repair needs traceable reference crops')
        l, t, r, b = bounds(patch.get('box'), baseline.size)
        size = (r - l, b - t)
        candidate_path = assets.bound_input(patch.get('candidate'), job_path.parent)
        mask_path = assets.bound_input(patch.get('mask'), job_path.parent)
        allowed_path = assets.bound_input(patch.get('allowed_mask'), job_path.parent)
        candidate = assets.image(candidate_path)
        if candidate.mode not in ('RGB', 'RGBA') or candidate.size != size:
            raise ValueError('Candidate must match local box exactly; no automatic resizing')
        if candidate.info.get('icc_profile') != baseline.info.get('icc_profile'):
            raise ValueError('Candidate profile differs; explicitly normalize color space first')
        mask, mask_arr = load_mask(mask_path, size, assets)
        _, allowed = load_mask(allowed_path, size, assets, binary=True)
        support = mask_arr > 0
        coverage = np.zeros_like(support)
        for region in regions:
            rl, rt, rr, rb = region['box']
            xl, yt, xr, yb = max(l, rl), max(t, rt), min(r, rr), min(b, rb)
            if xr > xl and yb > yt:
                coverage[yt-t:yb-t, xl-l:xr-l] = True
        if not support.any() or np.any((allowed > 0) & ~coverage) or np.any(support & (allowed == 0)):
            raise ValueError('Empty mask or mask/allowed zone exceeds confirmed region coverage')
        if np.any(support & (protected[t:b, l:r] > 0)) or np.any(support & union[t:b, l:r]):
            raise ValueError('Patch hits protection or overlaps an earlier patch')
        if baseline_alpha is not None and np.any(baseline_alpha[t:b, l:r][support] != 255):
            raise ValueError('Editing partially transparent source edges is outside this helper')
        if np.any(np.asarray(candidate.convert('RGBA'))[:, :, 3][support] != 255):
            raise ValueError('Candidate alpha would bake edit opacity into pixels')
        final.paste(candidate.convert(baseline.mode), (l, t), mask)
        union[t:b, l:r] |= support
        patches.append({'id': pid, 'group': group['id'], 'regions': selected, 'xy': (l, t),
                        'pixels': candidate.copy(), 'mask': mask, 'box': (l, t, r, b)})
    before, after = np.asarray(baseline), np.asarray(final)
    changed = np.any(before != after, axis=2)
    if np.any(changed & ~union) or np.any(changed & (protected > 0)):
        raise ValueError('Pixel protection invariant failed')
    if not changed.any():
        raise ValueError('No changed pixels: do not report a no-op as a repair')
    stem = ident(job.get('output_stem'))
    work = Path(work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    png, psd, receipt_path = [work / f'{stem}{suffix}' for suffix in ('.png', '.psd', '.receipt.json')]
    if any(p.exists() for p in (png, psd, receipt_path)):
        raise ValueError('Version already exists; choose a new output_stem')
    from psd_pair import write
    with tempfile.TemporaryDirectory(prefix='.fabric-stage-', dir=work) as staging:
        staged_png, staged_psd = Path(staging) / 'final.png', Path(staging) / 'final.psd'
        file_checks = write(staged_psd, staged_png, source, baseline, final, patches, baseline.info.get('icc_profile'))
        staged_png.rename(png)
        try:
            staged_psd.rename(psd)
        except Exception:
            png.unlink()
            raise
    receipt = {'schema': 1, 'image': entry, 'inputs': assets.snapshot(),
               'coverage': {'path': str(Path(manifest).resolve()), 'image_id': entry['id'],
                            'entry_sha256': hashlib.sha256(json.dumps(entry, ensure_ascii=False, sort_keys=True).encode()).hexdigest()},
               'outputs': [{'path': str(p), 'sha256': digest(p)} for p in (png, psd)],
               'patches': [{k: v for k, v in p.items() if k not in ('pixels', 'mask')} for p in patches],
               'technical_checks': dict(file_checks, outside_mask_exact=True, protection_exact=True,
                                        changed_pixels=int(changed.sum())), 'visual_status': 'not_reviewed'}
    write_json(receipt_path, receipt)
    return {'receipt': str(receipt_path), 'png': str(png), 'psd': str(psd), 'visual_status': 'not_reviewed'}


def verify_bindings(bindings):
    for item in bindings:
        if not Path(item['path']).is_file() or digest(item['path']) != item['sha256']:
            raise ValueError(f"Missing/replaced file invalidates QA: {item['path']}")


def verify_receipt(receipt):
    verify_bindings(receipt['inputs'] + receipt['outputs'])
    coverage = receipt['coverage']
    current = load_manifest(coverage['path'], Assets(), image_id=coverage['image_id'])
    if len(current) != 1 or hashlib.sha256(json.dumps(current[0], ensure_ascii=False, sort_keys=True).encode()).hexdigest() != coverage['entry_sha256']:
        raise ValueError('This image material coverage changed; refresh its evidence and QA')


def audit(receipt_path, work):
    receipt_path = Path(receipt_path).resolve()
    receipt = read_json(receipt_path)
    verify_receipt(receipt)
    entry, assets = receipt['image'], Assets()
    png = next(p['path'] for p in receipt['outputs'] if p['path'].lower().endswith('.png'))
    work = Path(work).resolve()
    cache = work / 'crop-cache'
    cache.mkdir(parents=True, exist_ok=True)
    evidence, groups, crops = [], [], []
    full = work / 'whole-garment-navigation.png'
    contact_sheet([[('Baseline whole frame', entry['baseline']), ('Final PNG whole frame', png)]], full, width=720, height=1080)
    evidence.append(assets.bind(full))
    for group in entry['groups']:
        rows = []
        for region in group['regions']:
            if region['box'] is None:
                continue
            a = cached_crop(entry['baseline'], region['box'], cache, assets)
            b = cached_crop(png, region['box'], cache, assets)
            ref = cached_crop(group['reference'], region['reference_box'], cache, assets) if region['reference_box'] else None
            evidence.extend([assets.bind(a['path']), assets.bind(b['path'])])
            if ref:
                evidence.append(assets.bind(ref['path']))
            crops.append({'group': group['id'], 'region': region['id'], 'baseline': a, 'final': b, 'reference': ref})
            rows.append([(f"{region['id']} baseline", a['path']), ('Final native', b['path']),
                         ('Reference native', ref['path'] if ref else None)])
        if rows:
            sheet = work / f"{entry['id']}-{group['id']}-navigation.png"
            contact_sheet(rows, sheet)
            evidence.append(assets.bind(sheet))
        groups.append({'id': group['id'], 'object': group['object'],
                       'regions': [{'id': r['id'], 'verdict': r['verdict']} for r in group['regions']]})
    for patch in receipt['patches']:
        l, t, r, b = patch['box']
        pad = max(8, round(max(r-l, b-t) * .15))
        w, h = assets.image(png).size
        context = (max(0, l-pad), max(0, t-pad), min(w, r+pad), min(h, b+pad))
        for image_path in (entry['baseline'], png):
            crop = cached_crop(image_path, context, cache, assets)
            evidence.append(assets.bind(crop['path']))
            crops.append({'patch': patch['id'], 'kind': 'edge_context', 'crop': crop})
    # Preserve coordinates and reference identities in the navigable receipt.
    path = work / 'audit.json'
    write_json(path, {'schema': 1, 'receipt': {'path': str(receipt_path), 'sha256': digest(receipt_path)},
                      'groups': groups, 'crops': crops, 'evidence': list({e['path']: e for e in evidence}.values()),
                      'navigation_only': True, 'visual_status': 'not_reviewed'})
    return {'audit': str(path), 'audit_sha256': digest(path), 'groups': groups, 'visual_status': 'not_reviewed'}


def observed_pass(value):
    return isinstance(value, dict) and value.get('result') == 'passed' and bool(str(value.get('notes', '')).strip())


def release(audit_path, review_path, output):
    audit_path = Path(audit_path).resolve()
    data, review = read_json(audit_path), read_json(review_path)
    if review.get('audit_sha256') != digest(audit_path) or not str(review.get('reviewer', '')).strip():
        raise ValueError('Visual review must identify reviewer and the actual audit version')
    verify_bindings([data['receipt']] + data['evidence'])
    receipt = read_json(data['receipt']['path'])
    verify_receipt(receipt)
    required = {'texture_reference', 'color_edges', 'protection', 'whole_garment'}
    if not all(observed_pass(review.get('checks', {}).get(key)) for key in required):
        raise ValueError('All four visual checks require actual observations and passed results')
    actual_groups = review.get('groups', [])
    if not isinstance(actual_groups, list) or len(actual_groups) != len(data['groups']):
        raise ValueError('Whole-image review must cover every material group')
    if len({g.get('id') for g in actual_groups}) != len(actual_groups):
        raise ValueError('Duplicate material group review')
    for group in data['groups']:
        found = [g for g in actual_groups if g.get('id') == group['id']]
        if len(found) != 1 or not observed_pass(found[0].get('consistency')):
            raise ValueError('Every same-material group requires consistency observations')
        rows = found[0].get('regions', {})
        if set(rows) != {r['id'] for r in group['regions']}:
            raise ValueError('Missing/extra regions in visual coverage')
        for region in group['regions']:
            row = rows[region['id']]
            if region['verdict'] == 'occluded':
                if row.get('result') != 'occluded' or not str(row.get('notes', '')).strip():
                    raise ValueError('Occluded region requires an explicit limitation')
            elif not observed_pass(row):
                raise ValueError('Visible region remains unresolved or unreviewed')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    targets = [(Path(p['path']), output / Path(p['path']).name) for p in receipt['outputs']]
    if {p.suffix.lower() for _, p in targets} != {'.png', '.psd'} or len(targets) != 2:
        raise ValueError('Formal deliverables must be exactly one PNG + one PSD')
    if any(dst.exists() for _, dst in targets):
        raise ValueError('Formal output exists; never overwrite silently')
    created = []
    try:
        for src, dst in targets:
            with src.open('rb') as inp, dst.open('xb') as out:
                created.append(dst)
                shutil.copyfileobj(inp, out, length=1024 * 1024)
            expected = next(p['sha256'] for p in receipt['outputs'] if p['path'] == str(src))
            if digest(dst) != expected:
                raise ValueError('Released copy differs from audited file')
    except Exception:
        for p in created:
            p.unlink(missing_ok=True)
        raise
    return {'outputs': [str(dst) for _, dst in targets], 'visual_review_by': review['reviewer'],
            'user_adoption': 'not_inferred'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare', help='Cache unaltered native evidence; no visual conclusions')
    p.add_argument('--manifest', required=True)
    p.add_argument('--work', required=True)
    p = sub.add_parser('compose', help='Apply existing authorized candidates via exact masks; build PNG/PSD')
    p.add_argument('--manifest', required=True)
    p.add_argument('--job', required=True)
    p.add_argument('--work', required=True)
    p = sub.add_parser('audit', help='Reopen final-file bindings and create whole/group/native evidence')
    p.add_argument('--receipt', required=True)
    p.add_argument('--work', required=True)
    p = sub.add_parser('release', help='Check recorded visual QA and release only PNG/PSD')
    p.add_argument('--audit', required=True)
    p.add_argument('--review', required=True)
    p.add_argument('--output', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args.manifest, args.work)
        elif args.command == 'compose':
            result = compose(args.manifest, args.job, args.work)
        elif args.command == 'audit':
            result = audit(args.receipt, args.work)
        else:
            result = release(args.audit, args.review, args.output)
        print(json.dumps(result, ensure_ascii=True))
    except (ValueError, OSError, KeyError, TypeError, ImportError) as error:
        parser.exit(2, f'Fabric workflow error: {error}\n')


if __name__ == '__main__':
    main()
