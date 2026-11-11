"""Isolated HD-mask integration fixtures; does not accept real product images."""
import argparse
import copy
import json
from pathlib import Path
import sys
import traceback

import numpy as np
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--work', required=True)
    args = parser.parse_args()
    skill = Path(args.skill).resolve()
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(skill / 'scripts'))
    import quality_pipeline as pipe
    import edge_quality as edge
    import hd_mask_psd as hd
    from psd_tools import PSDImage

    checks = []
    report = dict(passed=False, checks=checks, isolated_synthetic_fixtures=True,
                  actual_model_inference=False, work=str(work))

    def check(name, value, detail=None):
        checks.append(dict(name=name, passed=bool(value), detail=detail))
        print(('PASS ' if value else 'FAIL ') + name, flush=True)
        if not value:
            raise AssertionError(name)

    def rejects(name, callback, formal=None):
        error = None
        try:
            callback()
        except (ValueError, RuntimeError, FileNotFoundError, FileExistsError, KeyError) as caught:
            error = str(caught)
        check(name, error is not None and (formal is None or not formal.exists()), error)

    def save_json(name, data):
        path = work / (name + '.json')
        pipe.write(path, data)
        return path

    def attest(cache):
        current = pipe.load_checked(cache)
        review = save_json('review-' + str(current['revision']), dict(
            reviewer='isolated HD-mask integration selftest',
            items=[dict(index=item['index'], status='passed',
                        note='Synthetic fixture only; this is an automated test, not visual acceptance of user images.')
                   for item in current['items']]))
        pipe.review(cache, review)
        return pipe.approve(cache, 'Explicitly authorized isolated synthetic fixture test', 'selftest')['approval']

    old_cutout, old_analyze, old_repair = pipe.engine.cutout, edge.analyze, edge.repair
    calls = dict(cutout=0, analyze=0, repair=0)

    def fixture_cutout(source, method='auto'):
        calls['cutout'] += 1
        alpha = Image.new('L', source.size)
        draw = ImageDraw.Draw(alpha)
        draw.rectangle((100, 100, source.width-101, source.height-101), fill=255)
        draw.rectangle((100, 100, source.width-101, 104), fill=128)
        # Deliberately discard real, opaque input pixels, including all RGB.
        draw.rectangle((450, 450, 580, 580), fill=0)
        result = source.copy()
        pixels = np.asarray(result).copy()
        pixels[:, :, 3] = np.minimum(np.asarray(alpha), pixels[:, :, 3])
        pixels[pixels[:, :, 3] == 0, :3] = 0
        return Image.fromarray(pixels)

    def fixture_analyze(image, regions=None):
        qa = old_analyze(image, regions)
        phase = calls['analyze'] % 3
        calls['analyze'] += 1
        qa['technical_pass'] = True
        qa['flags'] = ['suspected_dark_rim'] if phase == 0 else []
        qa['metrics']['rim_severity'] = (100, 50, 25)[phase]
        qa['metrics']['suspect_pixels'] = (100, 50, 25)[phase]
        return qa

    def fixture_repair(subject, round_number, scale, protected):
        calls['repair'] += 1
        pixels = np.asarray(subject).copy()
        pixels[200:300, 200:300, 0] = 60 + round_number*10
        return Image.fromarray(pixels), dict(accepted=True, fixture_only=True,
                                            alpha_unchanged=True, core_unchanged=True)

    try:
        runtime = json.loads((skill/'runtime.json').read_text(encoding='utf-8-sig'))
        check('account-specific Python', Path(sys.executable).resolve() == Path(runtime['python']).resolve())
        pipe.engine.cutout, edge.analyze, edge.repair = fixture_cutout, fixture_analyze, fixture_repair
        inputs = []
        originals = []
        for index, dimensions in enumerate(((1320, 1010), (960, 1120))):
            image = Image.new('RGBA', dimensions, (97+index*30, 151-index*20, 207, 255))
            # The second source also has intrinsic transparency and half alpha.
            if index:
                draw = ImageDraw.Draw(image)
                draw.rectangle((0, 0, 20, 20), fill=(29, 81, 122, 0))
                draw.rectangle((300, 300, 350, 350), fill=(127, 131, 207, 128))
            path = work / f'source-{index}.png'
            image.save(path)
            inputs.append(path)
            originals.append(image)
        source_hashes = {str(path): edge.sha(path) for path in inputs}
        formal = work/'formal'
        spec = save_json('job', dict(schema_version=2,
            defaults=dict(out_dir=str(formal), separate_image_folders=True, cutout='rembg'),
            jobs=[dict(style='高清测试', color='绿色', angle='正面', input=str(inputs[0]), fill=.8),
                  dict(style='高清测试', color='蓝色', angle='侧面', input=str(inputs[1]), fill=.7)]))
        cache = work/'cache'
        preview = pipe.prepare(spec, cache)
        state = pipe.load_checked(cache)
        check('preview writes no formal products', preview['formal_files_written'] == 0 and not formal.exists())
        check('exactly one cutout per source', calls['cutout'] == 2)
        check('both revision candidates retain native dimensions', all(
            candidate['native']['size'] == item['source_size']
            for item in state['items'] for candidate in item['candidates'].values()))
        check('each native revision exactly normalizes to matching 800 candidate', all(
            np.array_equal(np.asarray(pipe.normalize(Image.open(candidate['native']['path']).convert('RGBA'), job)),
                           np.asarray(Image.open(candidate['path']).convert('RGBA')))
            for item, job in zip(state['items'], state['plan']['jobs'])
            for candidate in item['candidates'].values()))
        check('automatic selected version has corresponding native repair2', all(
            item['selected_name'] == 'repair2' and 'repair2-full-alpha' in item['selected']['native']['path']
            for item in state['items']))
        auth = attest(cache)
        state = pipe.load_checked(cache)
        pristine_state = pipe.state_path(cache).read_bytes()
        for label, path in (
            ('native candidate cache', Path(state['items'][0]['selected']['native']['path'])),
            ('original source cache', Path(state['items'][0]['source_cache']['path'])),
            ('input source', inputs[0])):
            previous = path.read_bytes()
            path.write_bytes(previous+b'changed')
            rejects(label+' changes invalidate confirmed export', lambda: pipe.export(spec, cache, auth), formal)
            path.write_bytes(previous)
        # Valid per-file hashes still cannot pair a different native revision
        # with the selected 800px image.
        modified = pipe.read(pipe.state_path(cache))
        modified['items'][0]['selected']['native'] = copy.deepcopy(modified['items'][0]['candidates']['initial']['native'])
        modified['items'][0]['candidates']['repair2']['native'] = copy.deepcopy(modified['items'][0]['selected']['native'])
        pipe.write(pipe.state_path(cache), modified)
        rejects('mixed native and 800 revisions rejected even with valid individual hashes', lambda: pipe.load_checked(cache))
        pipe.state_path(cache).write_bytes(pristine_state)
        other_native = Path(state['items'][0]['candidates']['repair1']['native']['path'])
        previous = other_native.read_bytes()
        other_native.write_bytes(previous+b'changed')
        rejects('choosing tampered unselected native revision rejected', lambda: pipe.choose(cache, 1, 'repair1'))
        other_native.write_bytes(previous)
        binding = pipe.approval_binding(state)
        altered = copy.deepcopy(state)
        altered['items'][0]['selected']['native']['rgba_sha256'] = 'different'
        check('approval binds native candidate pixels', pipe.approval_binding(altered) != binding)
        altered = copy.deepcopy(state)
        altered['items'][0]['source_cache']['rgba_sha256'] = 'different'
        check('approval binds original source pixels', pipe.approval_binding(altered) != binding)
        pipe.choose(cache, 1, 'repair1')
        rejects('choosing a different version clears prior review and approval', lambda: pipe.export(spec, cache, auth), formal)
        chosen = pipe.load_checked(cache)
        check('choose switches native and 800 candidate together',
              chosen['items'][0]['selected_name'] == 'repair1' and
              'repair1-full-alpha' in chosen['items'][0]['selected']['native']['path'] and
              chosen['items'][0]['visual_review']['status'] == 'pending')
        auth = attest(cache)
        state = pipe.load_checked(cache)
        result = pipe.export(spec, cache, auth, work/'files.json')
        check('export succeeds with six formal files', result['passed'] and len(result['outputs']) == 6 and
              len([path for path in formal.rglob('*') if path.is_file()]) == 6)
        check('export never repeats cutout or repair', calls['cutout'] == 2 and calls['repair'] == 4, dict(calls))
        meta = result['psd_source_metadata']['高清测试']
        check('mixed source resolutions use shared high-resolution canvas without downsampling',
              meta['canvas_size'][0] > 800 and all(item['scale'] >= 1 for item in meta['layers']))
        for item, source in zip(meta['layers'], originals):
            bbox = item['rendered_alpha_bbox']
            size = meta['canvas_size'][0]
            check(item['name']+' preserves fill and centering',
                  abs(max(bbox[2]-bbox[0], bbox[3]-bbox[1])-size*item['requested_fill']) <= 1 and
                  abs(bbox[0]+bbox[2]-size) <= 1 and abs(bbox[1]+bbox[3]-size) <= 1)
        for job, item in zip(result['jobs'], state['items']):
            png = Image.open(job['transparent']).convert('RGBA')
            selected = Image.open(item['selected']['path']).convert('RGBA')
            check(job['layer_name']+' PNG remains exact approved 800 RGBA',
                  png.size == (800,800) and np.array_equal(np.asarray(png), np.asarray(selected)))
        for kind in ('white', 'transparent'):
            document = PSDImage.open(result['styles'][0]['psd'][kind])
            group = document[-1]
            products = list(document)[0 if kind == 'transparent' else 1:-1]
            check(kind+' originals hidden with native RGB and intrinsic alpha exactly retained',
                not group.visible and all(not layer.visible and layer.size == source.size and
                    np.array_equal(np.asarray(layer.topil().convert('RGB')), np.asarray(source.convert('RGB'))) and
                    np.array_equal(np.asarray(layer.mask.topil()), np.asarray(source.getchannel('A')))
                    for layer,source in zip(group,originals)))
            for index, (product, source, layer_meta) in enumerate(zip(products, originals, meta['layers'])):
                scale = layer_meta['scale']
                x, y = round(510*scale), round(510*scale)
                # This point was deliberately opaque in the original and was
                # zeroed in both RGB and alpha by the cutout fixture.
                check(kind+' '+str(index)+' erased opaque pixels survive beneath independent mask',
                    source.getpixel((510,510))[3] == 255 and
                    product.mask.topil().getpixel((x,y)) == 0 and
                    product.topil().getpixel((x,y))[:3] == source.getpixel((510,510))[:3])
                xx, yy = product.left+x, product.top+y
                product.mask.disabled = True
                recovered = product.composite(viewport=(xx,yy,xx+1,yy+1), force=True, layer_filter=lambda _: True)
                check(kind+' '+str(index)+' disabled mask exposes original opaque color',
                    recovered.getpixel((0,0)) == source.getpixel((510,510)))
                product.mask.disabled = False
            # Original semitransparent input is one alpha mask, never squared.
            second = products[1]
            check(kind+' pixel layers contain opaque RGB independent of alpha mask',
                  all(layer.topil().getchannel('A').getextrema() == (255,255) for layer in products))
        rejects('oversized PSD canvas is rejected before silent downsampling', lambda:
            hd.build_style_assets([dict(name='oversized', source=Image.new('RGBA',(15001,1),'red'),
                subject=Image.new('RGBA',(15001,1),'red'),fill=.5)]))
        edge_source = Image.new('RGBA', (85,85), (77,131,204,255))
        edge_subject = edge_source.copy()
        edge_alpha = Image.new('L', edge_source.size)
        ImageDraw.Draw(edge_alpha).rectangle((5,5,84,84), fill=255)
        edge_subject.putalpha(edge_alpha)
        edge_assets = hd.build_style_assets([dict(name='right-bottom-edge',
            source=edge_source,subject=edge_subject,fill=.51)])
        edge_layer = edge_assets['products'][0]
        # 85*5.1 rounds to433 but 5*5.1 rounds to26 and80*5.1=408.
        # Both the rightmost and bottommost content pixels need pixel434.
        check('fractional upscale retains right and bottom edge pixels',
              edge_layer['mask'].size == (434,434) and
              edge_layer['mask'].getbbox() == (26,26,434,434) and
              edge_layer['mask'].getpixel((433,433)) == 255)
        edge_psd = work/'right-bottom-edge.psd'
        hd.write(edge_psd,edge_assets,transparent=True)
        edge_verified = hd.verify(edge_psd,edge_assets,transparent=True)
        check('fractional edge pixels survive PSD roundtrip',
              edge_verified['high_resolution_masks_verified'] and
              PSDImage.open(edge_psd)[0].mask.topil().getpixel((433,433)) == 255)
        check('source files unchanged after all tests', source_hashes == {str(path):edge.sha(path) for path in inputs})
        report['passed'] = True
        report['result'] = dict(canvas_size=meta['canvas_size'], output_count=len(result['outputs']), inference_calls=calls['cutout'])
    except Exception as error:
        report['error'] = str(error)
        report['traceback'] = traceback.format_exc()
        print(report['traceback'], flush=True)
    finally:
        pipe.engine.cutout, edge.analyze, edge.repair = old_cutout, old_analyze, old_repair
        (work/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
