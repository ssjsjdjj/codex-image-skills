"""Synthetic engineering fixtures. Does NOT test real fabric accuracy or repair quality."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

import fabric_tools as ft


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fabric-selftest-')
        self.root = Path(self.temp.name)
        original = Image.new('RGB', (128, 96), (90, 110, 130))
        draw = ImageDraw.Draw(original)
        for x in range(0, 128, 8):
            draw.line((x, 0, x, 95), fill=(75, 95, 115))
        original.save(self.root / 'source.png')
        original.save(self.root / 'ref.png')
        candidate = original.crop((8, 8, 40, 56))
        ImageDraw.Draw(candidate).rectangle((2, 2, 29, 45), fill=(100, 120, 140))
        candidate.save(self.root / 'candidate.png')
        edit = Image.new('L', (32, 48), 0)
        ImageDraw.Draw(edit).rectangle((2, 2, 29, 45), fill=128)
        edit.save(self.root / 'mask.png')
        Image.new('L', (32, 48), 255).save(self.root / 'allowed.png')
        Image.new('L', (128, 96), 0).save(self.root / 'protect.png')
        self.manifest = {'schema': 1, 'images': [{'id': 'S01', 'source': 'source.png', 'groups': [
            {'id': 'M01', 'object': 'P01 outer garment', 'label': 'synthetic grid', 'reference': 'ref.png',
             'regions': [{'id': 'R01', 'box': [8, 8, 40, 56], 'reference_box': [8, 8, 40, 56],
                          'verdict': 'abnormal', 'note': 'Synthetic fixture only; no real defect assertion'},
                         {'id': 'R02', 'box': [60, 8, 100, 56], 'reference_box': [60, 8, 100, 56],
                          'verdict': 'normal', 'note': 'Synthetic control region'}]}]}]}
        self.mp, self.jp = self.root / 'manifest.json', self.root / 'job.json'
        ft.write_json(self.mp, self.manifest)
        bind = lambda name: {'path': name, 'sha256': ft.digest(self.root / name)}
        self.job = {'image_id': 'S01', 'output_stem': 'S01-v1', 'source': bind('source.png'),
                    'baseline': bind('source.png'), 'protect_mask': bind('protect.png'),
                    'patches': [{'id': 'Q01', 'group': 'M01', 'regions': ['R01'], 'authorized': True,
                                 'box': [8, 8, 40, 56], 'candidate': bind('candidate.png'),
                                 'mask': bind('mask.png'), 'allowed_mask': bind('allowed.png')}]}
        self.save_job()

    def tearDown(self):
        self.temp.cleanup()

    def save_job(self):
        ft.write_json(self.jp, self.job)

    def update_binding(self, field, name, patch_field=False):
        target = self.job['patches'][0] if patch_field else self.job
        target[field] = {'path': name, 'sha256': ft.digest(self.root / name)}
        self.save_job()

    def compose(self):
        return ft.compose(self.mp, self.jp, self.root / 'candidate-work')

    def audited(self):
        result = self.compose()
        audit = ft.audit(result['receipt'], self.root / 'qa')
        # Recorded fixture data only; never claim this is a real visual review.
        observation = {'result': 'passed', 'notes': 'Synthetic schema fixture; no visual QA performed'}
        review = {'audit_sha256': audit['audit_sha256'], 'reviewer': 'synthetic-fixture-only',
                  'checks': {k: copy.deepcopy(observation) for k in ('texture_reference', 'color_edges', 'protection', 'whole_garment')},
                  'groups': [{'id': 'M01', 'consistency': copy.deepcopy(observation),
                              'regions': {r: copy.deepcopy(observation) for r in ('R01', 'R02')}}]}
        review_path = self.root / 'review.json'
        ft.write_json(review_path, review)
        return result, audit, review, review_path

    def test_content_cache_and_no_automatic_visual_pass(self):
        first = ft.prepare(self.mp, self.root / 'evidence')
        a = ft.read_json(first['inventory'])
        self.assertEqual(a['visual_status'], 'not_reviewed')
        second = ft.prepare(self.mp, self.root / 'evidence')
        b = ft.read_json(second['inventory'])
        crop = b['images'][0]['groups'][0]['regions'][0]['native']
        self.assertTrue(crop['cached'])
        original_hash = crop['sha256']
        Path(crop['path']).write_bytes(b'corrupt')
        third = ft.prepare(self.mp, self.root / 'evidence')
        c = ft.read_json(third['inventory'])['images'][0]['groups'][0]['regions'][0]['native']
        self.assertFalse(c['cached'])
        self.assertEqual(c['sha256'], original_hash)

    def test_native_crops_use_exif_oriented_coordinates(self):
        im = Image.new('RGB', (8, 12), 'red')
        exif = Image.Exif()
        exif[274] = 6
        im.save(self.root / 'oriented.jpg', exif=exif)
        assets = ft.Assets()
        self.assertEqual(assets.image(self.root / 'oriented.jpg').size, (12, 8))
        with Image.open(self.root / 'oriented.jpg') as native:
            self.assertEqual(native.size, (8, 12))

    def test_png_protection_and_editable_psd_pair(self):
        out = self.compose()
        before, after = np.asarray(Image.open(self.root / 'source.png')), np.asarray(Image.open(out['png']))
        region = np.zeros((96, 128), dtype=bool)
        region[8:56, 8:40] = np.asarray(Image.open(self.root / 'mask.png')) > 0
        self.assertTrue(np.array_equal(before[~region], after[~region]))
        self.assertTrue(np.any(before[region] != after[region]))
        receipt = ft.read_json(out['receipt'])
        self.assertEqual(receipt['visual_status'], 'not_reviewed')
        self.assertTrue(receipt['technical_checks']['merged_png_exact'])
        self.assertEqual(receipt['technical_checks']['editable_masks'], 1)

    def test_rgba_transparency_preserved(self):
        image = Image.open(self.root / 'source.png').convert('RGBA')
        image.putpixel((0, 0), (11, 22, 33, 0))
        image.save(self.root / 'source.png')
        self.update_binding('source', 'source.png')
        self.update_binding('baseline', 'source.png')
        result = self.compose()
        self.assertEqual(Image.open(result['png']).getpixel((0, 0)), (11, 22, 33, 0))

    def test_protected_pixels_rejected(self):
        protection = Image.open(self.root / 'protect.png')
        protection.putpixel((10, 10), 255)
        protection.save(self.root / 'protect.png')
        self.update_binding('protect_mask', 'protect.png')
        with self.assertRaisesRegex(ValueError, 'protection'):
            self.compose()

    def test_normal_uncertain_and_missing_authorization_rejected(self):
        for verdict in ('normal', 'uncertain', 'unreviewed', 'natural_soft'):
            with self.subTest(verdict=verdict):
                self.manifest['images'][0]['groups'][0]['regions'][0]['verdict'] = verdict
                ft.write_json(self.mp, self.manifest)
                with self.assertRaisesRegex(ValueError, 'cannot be edited'):
                    self.compose()
        self.manifest['images'][0]['groups'][0]['regions'][0]['verdict'] = 'abnormal'
        ft.write_json(self.mp, self.manifest)
        self.job['patches'][0]['authorized'] = False
        self.save_job()
        with self.assertRaisesRegex(ValueError, 'authorization'):
            self.compose()

    def test_stale_candidate_and_wrong_dimensions_rejected(self):
        Image.new('RGB', (32, 48), 'red').save(self.root / 'candidate.png')
        with self.assertRaisesRegex(ValueError, 'Stale'):
            self.compose()
        Image.new('RGB', (33, 48), 'red').save(self.root / 'candidate.png')
        self.update_binding('candidate', 'candidate.png', True)
        with self.assertRaisesRegex(ValueError, 'exactly'):
            self.compose()

    def test_zero_masks_and_outside_allowed_rejected(self):
        Image.new('L', (32, 48), 0).save(self.root / 'allowed.png')
        self.update_binding('allowed_mask', 'allowed.png', True)
        with self.assertRaisesRegex(ValueError, 'allowed zone'):
            self.compose()
        Image.new('L', (32, 48), 255).save(self.root / 'allowed.png')
        Image.new('L', (32, 48), 0).save(self.root / 'mask.png')
        self.update_binding('allowed_mask', 'allowed.png', True)
        self.update_binding('mask', 'mask.png', True)
        with self.assertRaisesRegex(ValueError, 'Empty mask'):
            self.compose()

    def test_overlapping_candidates_rejected(self):
        other = copy.deepcopy(self.job['patches'][0])
        other['id'] = 'Q02'
        self.job['patches'].append(other)
        self.save_job()
        with self.assertRaisesRegex(ValueError, 'overlaps'):
            self.compose()

    def test_same_material_group_is_not_global_edit_authorization(self):
        self.job['patches'][0]['regions'] = ['R02']
        self.save_job()
        with self.assertRaisesRegex(ValueError, 'cannot be edited'):
            self.compose()

    def test_failed_psd_leaves_no_formal_pair(self):
        with patch('psd_pair.write', side_effect=ValueError('simulated PSD failure')):
            with self.assertRaisesRegex(ValueError, 'simulated'):
                self.compose()
        self.assertEqual(list((self.root / 'candidate-work').glob('*.png')), [])
        self.assertEqual(list((self.root / 'candidate-work').glob('*.psd')), [])

    def test_release_requires_all_regions_and_only_outputs_png_psd(self):
        _, audit, review, rp = self.audited()
        saved = review['groups'][0]['regions'].pop('R02')
        ft.write_json(rp, review)
        with self.assertRaisesRegex(ValueError, 'Missing/extra'):
            ft.release(audit['audit'], rp, self.root / 'formal')
        review['groups'][0]['regions']['R02'] = saved
        ft.write_json(rp, review)
        result = ft.release(audit['audit'], rp, self.root / 'formal')
        self.assertEqual({p.suffix for p in (self.root / 'formal').iterdir()}, {'.png', '.psd'})
        self.assertEqual(result['user_adoption'], 'not_inferred')
        with self.assertRaisesRegex(ValueError, 'exists'):
            ft.release(audit['audit'], rp, self.root / 'formal')

    def test_changed_evidence_invalidates_release(self):
        _, audit, _, rp = self.audited()
        ad = ft.read_json(audit['audit'])
        target = Path(ad['evidence'][0]['path'])
        target.write_bytes(target.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'invalidates'):
            ft.release(audit['audit'], rp, self.root / 'formal')

    def test_changed_final_invalidates_release(self):
        result, audit, _, rp = self.audited()
        target = Path(result['png'])
        target.write_bytes(target.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'invalidates'):
            ft.release(audit['audit'], rp, self.root / 'formal')

    def test_changed_reference_invalidates_release(self):
        _, audit, _, rp = self.audited()
        target = self.root / 'ref.png'
        target.write_bytes(target.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'invalidates'):
            ft.release(audit['audit'], rp, self.root / 'formal')

    def test_outside_coverage_and_profile_mismatch_rejected(self):
        self.job['patches'][0]['box'] = [9, 8, 41, 56]
        self.save_job()
        with self.assertRaisesRegex(ValueError, 'exceeds confirmed'):
            self.compose()
        self.job['patches'][0]['box'] = [8, 8, 40, 56]
        with Image.open(self.root / 'candidate.png') as im:
            im.save(self.root / 'tagged.png', icc_profile=b'synthetic-mismatched-profile')
        self.update_binding('candidate', 'tagged.png', True)
        with self.assertRaisesRegex(ValueError, 'profile differs'):
            self.compose()

    def test_same_image_coverage_change_invalidates_qa(self):
        _, audit, _, rp = self.audited()
        self.manifest['images'][0]['groups'][0]['regions'][1]['note'] = 'Updated material evidence'
        ft.write_json(self.mp, self.manifest)
        with self.assertRaisesRegex(ValueError, 'coverage changed'):
            ft.release(audit['audit'], rp, self.root / 'formal')

    def test_other_image_update_does_not_invalidate_this_image(self):
        other = copy.deepcopy(self.manifest['images'][0])
        other['id'] = 'S02'
        self.manifest['images'].append(other)
        ft.write_json(self.mp, self.manifest)
        _, audit, _, rp = self.audited()
        self.manifest['images'][1]['groups'][0]['regions'][1]['note'] = 'Other image changed'
        ft.write_json(self.mp, self.manifest)
        ft.release(audit['audit'], rp, self.root / 'formal')


if __name__ == '__main__':
    unittest.main(verbosity=2)
