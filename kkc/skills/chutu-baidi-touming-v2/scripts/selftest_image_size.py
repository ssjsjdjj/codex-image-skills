"""Synthetic regression for compression, exact alpha, byte boundaries and export integration."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image
import image_size_limit as limit


def run_checks(work, check):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(42)
    rgba = np.zeros((800, 800, 4), dtype=np.uint8)
    noise = rng.integers(0, 128, (640, 640), dtype=np.uint8) * 2
    rgba[80:720, 80:720, :3] = noise[:, :, None]
    rgba[80:720, 80:720, 3] = 255
    source = Image.fromarray(rgba)
    source.save(work / 'source.png')
    before = hashlib.sha256((work / 'source.png').read_bytes()).hexdigest()
    png = work / 'compressed.png'
    result = limit.save_limited_image(source, png, 'transparent')
    check('PNG over 500KB auto-compresses and rechecks',
          result['attempts'][0]['bytes'] > 500_000 and result['compression_applied']
          and result['bytes'] == png.stat().st_size <= 500_000)
    with Image.open(png) as reopened:
        check('PNG palette preserves every RGBA pixel', np.array_equal(np.asarray(reopened.convert('RGBA')), rgba))
    alpha_rgba = np.zeros((800, 800, 4), dtype=np.uint8)
    alpha_rgba[80:720, 80:720] = (70, 120, 160, 128)
    alpha_rgba[160:640, 160:640] = (70, 120, 160, 255)
    semi = Image.fromarray(alpha_rgba)
    palette = limit._exact_palette(semi)
    check('lossless palette retains semi-transparent alpha',
          np.array_equal(np.asarray(palette.convert('RGBA')), alpha_rgba))

    gray = rng.integers(0, 256, (760, 760), dtype=np.uint8)
    rgb = np.full((800, 800, 3), 255, dtype=np.uint8)
    rgb[20:780, 20:780] = gray[:, :, None]
    jpg = work / 'compressed.jpg'
    jpeg = limit.save_limited_image(Image.fromarray(rgb), jpg, 'white')
    check('JPG over 500KB auto-compresses and rechecks',
          jpeg['attempts'][0]['bytes'] > 500_000 and jpeg['compression_applied']
          and jpg.stat().st_size == jpeg['bytes'] <= 500_000 and jpeg['mean_error'] <= 5)

    edge = work / 'boundary.png'
    data = png.read_bytes()
    edge.write_bytes(data + bytes(500_000 - len(data)))
    check('500000 bytes accepted after reopen', limit.verify_image_file(edge)['bytes'] == 500_000)
    edge.write_bytes(edge.read_bytes() + b'x')
    try:
        limit.verify_image_file(edge)
    except RuntimeError:
        rejected = True
    else:
        rejected = False
    check('500001 bytes rejected after reopen', rejected)

    bad = rgba.copy()
    bad[80:720, 80:720, :3] = rng.integers(0, 256, (640, 640, 3), dtype=np.uint8)
    try:
        limit.save_limited_image(Image.fromarray(bad), work / 'uncompressible.png', 'transparent')
    except RuntimeError as error:
        rejected = '500KB' in str(error) and (work / 'uncompressible.png.compression.json').is_file()
    else:
        rejected = False
    check('PNG never silently quantizes confirmed colors to reach limit', rejected)
    check('compression never modifies input file', before == hashlib.sha256((work / 'source.png').read_bytes()).hexdigest())
    return source, result, jpeg


def integration(work, source, check):
    import bg_assets as engine
    root = Path(__file__).resolve().parents[1]
    v2 = (root / 'scripts/quality_pipeline.py').is_file()
    if v2:
        import quality_pipeline as pipe

    def export_case(tag, picture, corrupt=False):
        src = work / (tag + '-source.png')
        picture.save(src)
        spec_path = work / (tag + '-spec.json')
        out = work / (tag + '-formal')
        spec = dict(defaults=dict(out_dir=str(out.resolve()), separate_image_folders=True),
                    jobs=[dict(style='Synthetic', color='Test', input=str(src.resolve()))])
        spec_path.write_text(json.dumps(spec), encoding='utf-8')
        manifest = work / (tag + '-manifest.json')
        if v2:
            cache = work / (tag + '-cache')
            pipe.prepare(spec_path, cache)
            decisions = work / (tag + '-review.json')
            decisions.write_text(json.dumps(dict(reviewer='synthetic regression only', items=[
                dict(index=1, status='passed', note='Synthetic fixture; not user product approval.')])), encoding='utf-8')
            pipe.review(cache, decisions)
            auth = pipe.approve(cache, 'Authorized synthetic compression regression', 'selftest')['approval']
            action = lambda: pipe.export(spec_path, cache, auth, manifest)
        else:
            plan = engine.load_plan(spec_path)
            action = lambda: engine.batch(plan, manifest)
        copier = shutil.copyfileobj

        def corrupt_copy(source, sink, *args, **kwargs):
            copier(source, sink, *args, **kwargs)
            if str(sink.name).lower().endswith('.png'):
                sink.write(bytes(500_001))

        if corrupt:
            shutil.copyfileobj = corrupt_copy
        try:
            return action(), out, manifest
        except RuntimeError as error:
            return error, out, manifest
        finally:
            shutil.copyfileobj = copier

    result, out, manifest = export_case('palette-export', source)
    check('real batch compresses oversize PNG and completes PSD verification',
          isinstance(result, dict) and result['passed'] and len(list(out.rglob('*.psd'))) == 2)
    png_job = result['jobs'][0]['transparent']
    detail = result['image_compression'][png_job]
    check('manifest records actual automatic compression and final size',
          detail['attempts'][0]['bytes'] > 500_000 and detail['compression_applied']
          and Path(png_job).stat().st_size <= 500_000 and manifest.is_file())

    failure, out, manifest = export_case('corrupt-publication', source, corrupt=True)
    check('post-write recheck rejects oversized final files without success manifest',
          isinstance(failure, RuntimeError) and not manifest.exists() and '超限' in str(failure))

    bad = np.asarray(source).copy()
    bad[80:720, 80:720, :3] = np.random.default_rng(93).integers(0, 256, (640, 640, 3), dtype=np.uint8)
    failure, out, manifest = export_case('uncompressible-export', Image.fromarray(bad))
    check('unresolved compression stops batch before any formal files',
          isinstance(failure, RuntimeError) and not out.exists() and not manifest.exists() and '500KB' in str(failure))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', required=True)
    args = parser.parse_args()
    checks = []

    def check(name, passed):
        checks.append(dict(name=name, passed=bool(passed)))
        print(('PASS ' if passed else 'FAIL ') + name, flush=True)
        if not passed:
            raise AssertionError(name)

    work = Path(args.work).resolve()
    source, png, jpg = run_checks(work, check)
    integration(work, source, check)
    report = dict(passed=True, checks=checks, png=png, jpg=jpg)
    (work / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=True, checks=len(checks), png_bytes=png['bytes'], jpg_bytes=jpg['bytes'])))


if __name__ == '__main__':
    main()
