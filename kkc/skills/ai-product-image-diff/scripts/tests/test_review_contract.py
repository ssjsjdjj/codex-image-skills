"""Regression fixtures are synthetic bytes; these tests do not perform visual QA."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import review_contract as contract
from build_bulk_review import build

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aXioAAAAASUVORK5CYII=')


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    return Path(path)


def make_fixture(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for filename in ('input.png', 'ref.png', 'final.png', 'comparison.png'):
        (folder / filename).write_bytes(PNG + filename.encode())
    issue = {'id': 'D01', 'scene': 'S01', 'person': 'P01', 'group': 'D', 'feature': 'logo', 'title': 'Synthetic logo issue',
             'reference_ids': ['REF1'], 'comparison_image': 'comparison.png',
             'diagnosis': {'status': 'confirmed'}, 'repair': {'status': 'pending'},
             'review': {'status': 'not_reviewed'}, 'adoption': {'status': 'not_adopted'}, 'dependencies': []}
    source = {'schema_version': 2, 'dataset_id': 'test-stable-batch', 'title': 'Synthetic review',
              'files': [{'id': 'S01', 'name': 'input', 'role': 'ai_input', 'path': 'input.png'},
                        {'id': 'REF1', 'name': 'reference', 'role': 'reference', 'path': 'ref.png'}],
              'people': [{'id': 'P01', 'scene': 'S01', 'position': 'left', 'color': 'red', 'conclusions': {'logo': 'test'}}],
              'issues': [issue]}
    return write_json(folder / 'manifest.json', source), source


def passing_review(folder):
    return {'status': 'passed', 'output_sha256': contract.sha256_file(folder / 'final.png'), 'output_version': 'v1',
            'input_sha256': contract.sha256_file(folder / 'input.png'),
            'reference_ids': ['REF1'], 'reference_sha256': {'REF1': contract.sha256_file(folder / 'ref.png')},
            'method': 'visual', 'reviewer': 'synthetic-fixture-only', 'checked_at': '2026-11-13T00:00:00Z',
            'checks': {key: {'result': 'passed', 'notes': 'Synthetic record; no actual visual QA performed.'} for key in contract.QA_CHECKS},
            'evidence': [{'path': 'comparison.png', 'sha256': contract.sha256_file(folder / 'comparison.png')}]}


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='contract-fixture-', dir=Path(__file__).parent)
        self.folder = Path(self.temp.name)
        self.manifest, self.source = make_fixture(self.folder)
        self.output = self.folder / 'review.html'

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        write_json(self.manifest, self.source)

    def report(self, records=()):
        return contract.make_report(self.manifest, self.output, records)

    def record(self, updates, filename='record.json', **identity):
        data = {'schema_version': 2, 'dataset_id': self.source['dataset_id'],
                'source_manifest_sha256': contract.sha256_file(self.manifest), 'updates': updates}
        data.update(identity)
        return write_json(self.folder / filename, data)

    def update(self, sequence, **fields):
        return {**{key: self.source['issues'][0][key] for key in contract.LOCATION_FIELDS}, 'sequence': sequence, **fields}

    def set_pass(self, adopted=False):
        issue = self.source['issues'][0]
        issue['repair'] = {'status': 'executed'}
        issue['current_output'] = {'path': 'final.png', 'sha256': contract.sha256_file(self.folder / 'final.png'), 'version': 'v1'}
        issue['review'] = passing_review(self.folder)
        if adopted:
            issue['adoption'] = {'status': 'adopted', 'output_sha256': issue['current_output']['sha256'], 'output_version': 'v1',
                                 'explicit_user_acceptance': True, 'evidence': 'Synthetic user acceptance record'}
        self.save()

    def test_valid_pending_selection_and_html_md_share_report(self):
        data = build(self.manifest, self.output)
        payload = contract.selection_payload(data, ['D01'])
        self.assertTrue(contract.validate_selection(data, payload)['valid'])
        self.assertTrue(data['issues'][0]['default_selectable'])
        self.assertIn(data['issues'][0]['state_text'], contract.render_markdown(data))
        self.assertIn(data['revision'], self.output.read_text('utf-8'))
        self.assertEqual(data['source_context']['output_path'], str(self.output))

    def test_C01_foreign_identity_or_location_never_applies(self):
        for identity in ({'dataset_id': 'other'}, {'source_manifest_sha256': '0' * 64}, {'schema_version': 1}):
            with self.subTest(identity=identity):
                record = self.record([self.update(1, repair={'status': 'executed'})], **identity)
                with self.assertRaisesRegex(contract.ContractError, 'identity'):
                    self.report([record])
        update = self.update(1, repair={'status': 'executed'})
        update['person'] = 'OTHER'
        with self.assertRaisesRegex(contract.ContractError, 'location'):
            self.report([self.record([update])])
        write_json(self.folder / 'legacy_record.json', {'records': [{'id': 'D01', 'status': '已修复且复核通过'}]})
        with self.assertRaisesRegex(contract.ContractError, 'Migration'):
            self.report([self.folder / 'legacy_record.json'])

    def test_C02_exact_legacy_mapping_never_confers_pass(self):
        for text in ('终审通过，现已撤销通过', '已采用；用户撤销采用', '撤回已修复结论，重新复核',
                     '已修复且复核通过', '已采用', 'repaired', 'blocked', '证据不足，现补证确认需修'):
            with self.subTest(text=text):
                self.assertEqual(contract.normalize_status(text), 'needs_review')

    def test_C02_explicit_revocation_removes_pass_and_adoption(self):
        self.set_pass(adopted=True)
        record = self.record([self.update(1, review={'status': 'revoked'})])
        issue = self.report([record])['issues'][0]
        self.assertEqual(issue['state'], 'needs_review')
        self.assertEqual(issue['adoption']['status'], 'not_adopted')
        self.assertFalse(issue['default_selectable'])
        self.assertTrue(issue['history'])

    def test_C03_missing_update_state_does_not_overwrite(self):
        record = self.record([self.update(1, repair={'status': 'failed'}, review={'status': 'failed'}), self.update(2)])
        issue = self.report([record])['issues'][0]
        self.assertEqual(issue['repair']['status'], 'failed')
        self.assertEqual(issue['review']['status'], 'failed')
        self.assertTrue(issue['default_selectable'])

    def test_C03_empty_unknown_or_prose_update_is_error(self):
        for value in (None, '', {}, {'status': ''}, {'status': 'repaired'}, {'status': []}):
            with self.subTest(value=value), self.assertRaises(contract.ContractError):
                self.report([self.record([self.update(1, repair=value)])])
        with self.assertRaisesRegex(contract.ContractError, 'Prose'):
            self.report([self.record([self.update(1, status='已修复')])])

    def test_sequence_not_container_or_file_order_controls_updates(self):
        r1 = self.record([self.update(2, repair={'status': 'failed'}, review={'status': 'failed'})], 'later.json')
        r2 = self.record([self.update(1, repair={'status': 'in_progress'})], 'earlier.json')
        first, second = self.report([r1, r2]), self.report([r2, r1])
        self.assertEqual(first['issues'][0]['repair']['status'], 'failed')
        self.assertEqual(first['revision'], second['revision'])
        r3 = self.record([self.update(2)], 'conflict.json')
        with self.assertRaisesRegex(contract.ContractError, 'duplicate sequence'):
            self.report([r1, r3])

    def test_C04_image_replacement_keeps_batch_but_changes_revision_and_rejects_old_selection(self):
        for filename in ('input.png', 'ref.png', 'comparison.png'):
            with self.subTest(filename=filename):
                old = self.report()
                payload = contract.selection_payload(old, ['D01'])
                path = self.folder / filename
                path.write_bytes(path.read_bytes() + b'replaced')
                new = self.report()
                self.assertEqual(old['dataset_id'], new['dataset_id'])
                self.assertNotEqual(old['revision'], new['revision'])
                with self.assertRaisesRegex(contract.ContractError, 'Stale'):
                    contract.validate_selection(old, payload)

    def test_W01_W04_passed_enum_or_hash_alone_is_not_visual_pass(self):
        self.source['issues'][0]['review'] = {'status': 'passed'}
        self.save()
        issue = self.report()['issues'][0]
        self.assertEqual(issue['review']['status'], 'needs_review')
        self.assertFalse(issue['default_selectable'])
        self.set_pass()
        for field in ('method', 'reviewer', 'checked_at', 'input_sha256', 'reference_sha256', 'evidence', 'checks', 'output_version'):
            with self.subTest(field=field):
                self.set_pass()
                del self.source['issues'][0]['review'][field]
                self.save()
                self.assertEqual(self.report()['issues'][0]['review']['status'], 'needs_review')
        for check in contract.QA_CHECKS:
            self.set_pass()
            del self.source['issues'][0]['review']['checks'][check]
            self.save()
            self.assertEqual(self.report()['issues'][0]['review']['status'], 'needs_review')

    def test_valid_recorded_visual_qa_is_separate_from_user_adoption(self):
        self.set_pass()
        issue = self.report()['issues'][0]
        self.assertEqual(issue['state'], 'verified')
        self.assertEqual(issue['adoption']['status'], 'not_adopted')
        self.assertFalse(issue['default_selectable'])
        self.assertTrue(issue['redo_selectable'])
        data = self.report()
        self.assertEqual(data['source_context']['output_path'], str(self.output))
        with self.assertRaisesRegex(contract.ContractError, 'not actionable'):
            contract.validate_selection(data, contract.selection_payload(data, ['D01']))
        self.assertTrue(contract.validate_selection(data, contract.selection_payload(data, ['D01'], True))['valid'])

    def test_markdown_reports_actual_observations_and_never_invents_missing_notes(self):
        issue = self.source['issues'][0]
        issue['description'] = 'Specific visible synthetic observation'
        issue['visibility'] = {'collar': 'occluded in this synthetic fixture'}
        issue['material_checks'] = {'scale': 'specific recorded scale observation'}
        self.set_pass()
        issue['review']['checks']['texture']['notes'] = 'Specific recorded texture QA observation'
        self.save()
        data = self.report()
        markdown = contract.render_markdown(data)
        for text in ('Specific visible synthetic observation', 'occluded in this synthetic fixture', 'specific recorded scale observation',
                     'REF1', 'Specific recorded texture QA observation', 'final.png', 'v1'):
            self.assertIn(text, markdown)
        issue.pop('material_checks')
        issue.pop('visibility')
        issue['review'] = {'status': 'not_reviewed'}
        self.save()
        markdown = contract.render_markdown(self.report())
        self.assertNotIn('面料检查：', markdown)
        self.assertNotIn('可见性：', markdown)
        self.assertNotIn('QA texture：', markdown)
        self.assertNotIn('Specific recorded texture QA observation', markdown)
        issue['review'] = {'status': 'passed'}
        self.save()
        self.assertIn('复核诊断：', contract.render_markdown(self.report()))

    def test_relevant_QA_dimensions_cannot_all_be_not_applicable(self):
        for group, mandatory in [('D', ('structure', 'color', 'protection')), ('Q', ('texture', 'color', 'protection'))]:
            for key in mandatory:
                with self.subTest(group=group, key=key):
                    self.set_pass()
                    self.source['issues'][0]['group'] = group
                    self.source['issues'][0]['review']['checks'][key] = {'result': 'not_applicable', 'notes': 'Synthetic attempted bypass'}
                    self.save()
                    self.assertEqual(self.report()['issues'][0]['review']['status'], 'needs_review')

    def test_changed_final_input_reference_or_evidence_revokes_current_qa_and_adoption(self):
        for filename in ('final.png', 'input.png', 'ref.png', 'comparison.png'):
            with self.subTest(filename=filename):
                self.set_pass(adopted=True)
                path = self.folder / filename
                path.write_bytes(path.read_bytes() + b'changed-after-QA')
                issue = self.report()['issues'][0]
                self.assertEqual(issue['review']['status'], 'needs_review')
                self.assertEqual(issue['adoption']['status'], 'not_adopted')
                self.assertFalse(issue['redo_selectable'])
                self.assertTrue(any('unverified_adoption' in event for event in issue['history']))

    def test_missing_final_output_is_diagnostic_not_a_pass(self):
        self.set_pass(adopted=True)
        (self.folder / 'final.png').unlink()
        issue = self.report()['issues'][0]
        self.assertEqual(issue['review']['status'], 'needs_review')
        self.assertEqual(issue['adoption']['status'], 'not_adopted')

    def test_C05_required_location_and_reference_fields(self):
        for field in (*contract.LOCATION_FIELDS, 'title', 'reference_ids'):
            with self.subTest(field=field):
                saved = self.source['issues'][0].pop(field)
                self.save()
                with self.assertRaises(contract.ContractError):
                    self.report()
                self.source['issues'][0][field] = saved
        self.source['issues'][0]['person'] = 'UNKNOWN'
        self.save()
        with self.assertRaisesRegex(contract.ContractError, 'scene/person'):
            self.report()

    def test_C05_people_composite_keys_preserve_both_scenes(self):
        self.source['files'].append({'id': 'S02', 'name': 'second input', 'role': 'ai_input', 'path': 'input.png'})
        self.source['people'].append({'id': 'P01', 'scene': 'S02', 'position': 'right', 'color': 'blue'})
        second = copy.deepcopy(self.source['issues'][0])
        second.update(id='D02', scene='S02')
        self.source['issues'].append(second)
        self.save()
        data = self.report()
        self.assertEqual([(i['position'], i['color']) for i in data['issues']], [('left', 'red'), ('right', 'blue')])
        self.assertEqual(len(data['people']), 2)
        self.assertEqual(contract.selection_summary(data['issues'])['people'], 2)

    def test_C06_selection_tampering_or_scope_conflict_is_rejected(self):
        data = self.report()
        for field, value in [('dataset_id', 'other'), ('review_revision', 'old'), ('source_manifest_sha256', 'bad'), ('instruction', '请修复：其他编号'), ('summary', {})]:
            payload = contract.selection_payload(data, ['D01'])
            payload[field] = value
            with self.subTest(field=field), self.assertRaises(contract.ContractError):
                contract.validate_selection(data, payload)
        payload = contract.selection_payload(data, ['D01'])
        payload['selected_issues'][0]['scene'] = 'OTHER'
        with self.assertRaisesRegex(contract.ContractError, 'binding'):
            contract.validate_selection(data, payload)

    def test_dependencies_block_until_bound_pass_and_reject_invalid_graphs(self):
        q = copy.deepcopy(self.source['issues'][0])
        q.update(id='Q01', group='Q', feature='texture', dependencies=['D01'])
        self.source['issues'].append(q)
        self.save()
        data = self.report()
        self.assertFalse(data['issues'][1]['default_selectable'])
        self.assertEqual(data['issues'][1]['dependency_blockers'], ['D01'])
        self.set_pass()
        self.assertTrue(self.report()['issues'][1]['default_selectable'])
        for dependencies in (['UNKNOWN'], ['Q01']):
            self.source['issues'][1]['dependencies'] = dependencies
            self.save()
            with self.assertRaisesRegex(contract.ContractError, 'dependency'):
                self.report()
        self.source['issues'][1]['dependencies'] = ['D01']
        self.source['issues'][0]['dependencies'] = ['Q01']
        self.save()
        with self.assertRaisesRegex(contract.ContractError, 'cycle'):
            self.report()

    def test_executed_failed_is_actionable_and_revoked_is_not(self):
        issue = self.source['issues'][0]
        issue['repair']['status'], issue['review']['status'] = 'executed', 'failed'
        self.save()
        self.assertTrue(self.report()['issues'][0]['default_selectable'])
        self.assertEqual(self.report()['issues'][0]['state'], 'pending')
        issue['review']['status'] = 'revoked'
        self.save()
        self.assertFalse(self.report()['issues'][0]['default_selectable'])

    def test_legacy_manifest_is_readonly_and_keeps_old_claim_as_history(self):
        self.source.pop('schema_version')
        self.source.pop('dataset_id')
        for field in contract.STATE_FIELDS:
            self.source['issues'][0].pop(field)
        self.source['issues'][0]['status'] = '已修复且复核通过（v1，v2保留）'
        self.source['people'][0]['conclusions'] = '旧稿声称通过'
        self.save()
        data = build(self.manifest, self.output)
        self.assertTrue(data['legacy_readonly'])
        self.assertEqual(data['issues'][0]['review']['status'], 'needs_review')
        self.assertEqual(data['issues'][0]['state'], 'readonly')
        self.assertIn('legacy_status', data['issues'][0]['history'][0])
        self.assertIsInstance(data['people'][0]['conclusions'], dict)
        with self.assertRaisesRegex(contract.ContractError, 'read-only'):
            contract.validate_selection(data, contract.selection_payload(data, ['D01']))

    def test_cli_validation_rehashes_and_does_not_write_without_output_flags(self):
        data = self.report()
        selection = write_json(self.folder / 'selection.json', contract.selection_payload(data, ['D01']))
        cmd = [sys.executable, str(SCRIPTS / 'review_contract.py'), '--manifest', str(self.manifest), '--validate-selection', str(selection)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['valid'])
        self.assertFalse(self.output.exists())
        (self.folder / 'input.png').write_bytes(PNG + b'replaced')
        result = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Stale', result.stderr)


if __name__ == '__main__':
    unittest.main()
