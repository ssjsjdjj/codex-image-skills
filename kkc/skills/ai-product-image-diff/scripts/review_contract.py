#!/usr/bin/env python3
"""Local review contract/selection validator. Bindings do not perform visual QA."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

SCHEMA_VERSION = 2
LOCATION_FIELDS = ('id', 'scene', 'person', 'group', 'feature')
STATE_FIELDS = ('diagnosis', 'repair', 'review', 'adoption')
ENUMS = {
    'diagnosis': {'confirmed', 'uncertain', 'withdrawn', 'no_difference'},
    'repair': {'pending', 'in_progress', 'executed', 'failed', 'not_executed'},
    'review': {'not_reviewed', 'needs_review', 'passed', 'failed', 'insufficient', 'revoked'},
    'adoption': {'not_adopted', 'adopted', 'withdrawn'},
}
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
QA_CHECKS = ('structure', 'color', 'texture', 'protection')


class ContractError(ValueError):
    """Invalid/unverifiable data: no repair authorization is produced."""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def people_key(scene, person):
    return canonical([scene, person])


def _text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f'{label}: nonempty string required')
    return value


def _state(value, field, label):
    if not isinstance(value, dict) or not isinstance(value.get('status'), str) or value['status'] not in ENUMS[field]:
        raise ContractError(f'{label}.{field}: explicit known status required; empty/unknown is not pending')
    return copy.deepcopy(value)


def legacy_states(text, group='D'):
    """Exact migration only. Legacy prose can never establish visual pass/adoption."""
    text = str(text or '').strip()
    result = {'diagnosis': {'status': 'uncertain' if group == 'R' else 'confirmed'},
              'repair': {'status': 'pending'}, 'review': {'status': 'needs_review'},
              'adoption': {'status': 'not_adopted'}}
    if text in {'未选择／未修复', '未选择/未修复', '未修复', '未执行'}:
        result['review']['status'] = 'not_reviewed'
    elif text in {'证据不足', '证据不足／待复核'}:
        result['diagnosis']['status'] = 'uncertain'
        result['review']['status'] = 'insufficient'
    elif text in {'撤销误判', '无需修复', '无须修复'}:
        result['diagnosis']['status'] = 'withdrawn' if text == '撤销误判' else 'no_difference'
    elif text in {'改善但未通过', '未通过', '仍需修'}:
        result['repair']['status'] = 'failed'
        result['review']['status'] = 'failed'
    elif text in {'已修复且复核通过', '已修复', '修复完成', '已采用', '终审通过', '确认采用'}:
        result['repair']['status'] = 'executed'
    return result


def normalize_status(text, group='D'):
    """Compatibility helper: text alone is deliberately never completed/passed."""
    value = legacy_states(text, group)
    if value['diagnosis']['status'] != 'confirmed' or group == 'R':
        return 'blocked'
    return 'needs_review' if value['review']['status'] == 'needs_review' else 'pending'


class Assets:
    def __init__(self, base, output):
        self.base, self.output = Path(base).resolve(), Path(output).resolve()
        self.records = {}

    def resolve(self, value):
        path = Path(value)
        return (path if path.is_absolute() else self.base / path).resolve()

    def fingerprint(self, value, role, required=False):
        if not value:
            if required:
                raise ContractError(f'{role}: file path required')
            return None
        if not isinstance(value, str):
            raise ContractError(f'{role}: file path must be a string')
        path = self.resolve(value)
        exists, key = path.is_file(), str(path)
        if required and not exists:
            raise ContractError(f'{role}: missing file: {path}')
        if key not in self.records:
            self.records[key] = {'path': key, 'exists': exists, 'sha256': sha256_file(path) if exists else None, 'roles': []}
        if role not in self.records[key]['roles']:
            self.records[key]['roles'].append(role)
        return {k: self.records[key][k] for k in ('path', 'exists', 'sha256')}

    def link(self, value):
        if not value:
            return ''
        path = self.resolve(value)
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            return ''
        try:
            return Path(os.path.relpath(path, self.output.parent)).as_posix()
        except ValueError:
            return ''


def _binding(value, assets, label, strict):
    if value is None:
        return None
    if not isinstance(value, dict):
        if strict:
            raise ContractError(f'{label}: output requires path/sha256/version, not filename alone')
        value = {'path': value, 'version': 'legacy-unverified'}
    path, version = _text(value.get('path'), f'{label}.path'), _text(value.get('version'), f'{label}.version')
    actual = assets.fingerprint(path, label)
    declared = value.get('sha256')
    if strict and (not isinstance(declared, str) or len(declared) != 64):
        raise ContractError(f'{label}.sha256: SHA256 binding required')
    return {'path': actual['path'], 'sha256': actual['sha256'], 'version': version,
            'binding_valid': bool(actual['exists'] and declared == actual['sha256'])}


def _walk_asset_paths(value, assets, role='metadata'):
    """Include declared evidence outside the standard image fields in revision."""
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str) and (key in {'path', 'source_path', 'comparison_image', 'native_ai', 'native_ref', 'file'} or key.endswith('_path')):
                assets.fingerprint(child, f'{role}:{key}')
            elif isinstance(child, (dict, list)):
                _walk_asset_paths(child, assets, f'{role}:{key}')
    elif isinstance(value, list):
        for child in value:
            _walk_asset_paths(child, assets, role)


def _verify_visual_review(issue, files, assets):
    """Check recorded observations/bindings, never infer a visual result from hashes."""
    review, output, reasons = issue['review'], issue['current_output'], []
    if issue['repair']['status'] != 'executed':
        reasons.append('repair execution and final output must precede visual pass')
    if not output or not output['binding_valid']:
        reasons.append('current final output missing or changed')
    else:
        for key, expected in [('output_sha256', output['sha256']), ('output_version', output['version'])]:
            if review.get(key) != expected:
                reasons.append(f'{key} does not bind current final output')
        if review.get('output_path') and str(assets.resolve(review['output_path'])) != output['path']:
            reasons.append('output_path does not bind current final output')
    if not isinstance(review.get('method'), str) or review['method'] not in {'visual', 'human_visual'}:
        reasons.append('recorded visual review method required')
    for field in ('reviewer', 'checked_at'):
        if not isinstance(review.get(field), str) or not review[field].strip():
            reasons.append(f'{field} required')
    checks = review.get('checks', {})
    mandatory_pass = {'color', 'protection'}
    if issue['group'] == 'Q':
        mandatory_pass.add('texture')
    if issue['group'] == 'D':
        mandatory_pass.add('structure')
    for key in QA_CHECKS:
        check = checks.get(key) if isinstance(checks, dict) else None
        if not isinstance(check, dict) or not isinstance(check.get('result'), str) or check['result'] not in {'passed', 'not_applicable'}:
            reasons.append(f'explicit {key} check result required')
        elif not isinstance(check.get('notes'), str) or not check['notes'].strip():
            reasons.append(f'{key} observations/reason required')
        elif key in mandatory_pass and check['result'] != 'passed':
            reasons.append(f'{key} must pass for this image repair; not_applicable cannot establish visual pass')
    refs = review.get('reference_ids')
    if not isinstance(refs, list) or not refs:
        reasons.append('reference_ids required')
    else:
        for ref_id in refs:
            ref = files.get(ref_id) if isinstance(ref_id, str) else None
            if not ref or ref.get('role') != 'reference' or not (ref.get('fingerprint') or {}).get('exists'):
                reasons.append(f'actual reference required: {ref_id}')
            elif not isinstance(review.get('reference_sha256'), dict) or review['reference_sha256'].get(ref_id) != ref['fingerprint']['sha256']:
                reasons.append(f'reference content binding missing/changed: {ref_id}')
        if set(ref for ref in refs if isinstance(ref, str)) != set(issue.get('reference_ids', [])):
            reasons.append('review references must match this issue reference_ids')
    input_fingerprint = (files.get(issue['scene'], {}).get('fingerprint') or {})
    if not input_fingerprint.get('exists') or review.get('input_sha256') != input_fingerprint.get('sha256'):
        reasons.append('AI input content binding missing/changed')
    evidence = review.get('evidence')
    fingerprints = []
    if not isinstance(evidence, list) or not evidence:
        reasons.append('visual comparison evidence required')
    else:
        for entry in evidence:
            if not isinstance(entry, dict) or not isinstance(entry.get('path'), str) or not entry['path']:
                reasons.append('evidence requires path/SHA256')
                continue
            actual = assets.fingerprint(entry['path'], f"qa-evidence:{issue['id']}")
            fingerprints.append(actual)
            if not actual['exists'] or entry.get('sha256') != actual['sha256'] or Path(entry['path']).suffix.lower() not in IMAGE_SUFFIXES:
                reasons.append('QA evidence missing or changed')
    review['evidence_fingerprints'] = fingerprints
    return reasons


def _dependency_order(rows, index):
    """Validate the small local issue graph and return prerequisites first."""
    order, visiting, visited = [], set(), set()
    def visit(iid):
        if iid in visiting:
            raise ContractError(f'Dependency cycle includes {iid}')
        if iid in visited:
            return
        visiting.add(iid)
        for dependency in index[iid]['dependencies']:
            if dependency not in index or dependency == iid:
                raise ContractError(f'issue {iid}: unknown/self dependency {dependency}')
            visit(dependency)
        visiting.remove(iid)
        visited.add(iid)
        order.append(iid)
    for row in rows:
        visit(row['id'])
    return order


def make_report(manifest, output, status_records=(), title=None):
    manifest, output = Path(manifest).resolve(), Path(output).resolve()
    status_records = list(status_records)
    raw = manifest.read_bytes()
    source = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(source, dict) or source.get('schema_version', 1) not in (1, 2):
        raise ContractError('Manifest object with supported schema_version required')
    legacy = source.get('schema_version', 1) == 1
    source_hash = hashlib.sha256(raw).hexdigest()
    dataset = source.get('dataset_id')
    if legacy:
        dataset = dataset or 'legacy-' + hashlib.sha256(str(manifest).encode('utf-8')).hexdigest()[:24]
    dataset = _text(dataset, 'dataset_id')
    diagnostics = ['Legacy manifest is read-only. Migrate identity/location/states and output/QA evidence before repair selection; completion prose is history only.'] if legacy else []
    assets = Assets(manifest.parent, output)
    _walk_asset_paths(source, assets, 'manifest')
    raw_files = source.get('files', [])
    if isinstance(raw_files, dict):
        raw_files = [dict(value, id=key) for key, value in raw_files.items()]
    if not isinstance(raw_files, list):
        raise ContractError('files must be a list or keyed object')
    files = {}
    for entry in raw_files:
        if not isinstance(entry, dict):
            raise ContractError('Every file entry must be an object')
        fid = _text(entry.get('id'), 'files.id')
        if fid in files:
            raise ContractError(f'Duplicate file ID: {fid}')
        row = copy.deepcopy(entry)
        path = row.get('path', row.get('source_path'))
        if not legacy:
            if not isinstance(row.get('role'), str) or row['role'] not in {'ai_input', 'reference', 'evidence', 'output'}:
                raise ContractError(f'files.{fid}: explicit file role required')
            _text(row.get('name'), f'files.{fid}.name')
            _text(path, f'files.{fid}.path')
        row['fingerprint'] = assets.fingerprint(path, f'file:{fid}', required=not legacy) if path else None
        row['name'], row['image'] = str(row.get('name', fid)), assets.link(path or f'scenes/{fid}.jpg')
        assets.fingerprint(f'scenes/{fid}.jpg', f'scene-preview:{fid}')
        files[fid] = row
    people = {}
    raw_people = source.get('people', [])
    if not isinstance(raw_people, list):
        raise ContractError('people must be a list')
    for entry in raw_people:
        if not isinstance(entry, dict):
            raise ContractError('Every person entry must be an object')
        pid, scene = _text(entry.get('id'), 'people.id'), str(entry.get('scene', ''))
        if not legacy and (not scene or scene not in files or files[scene].get('role') != 'ai_input'):
            raise ContractError(f'people.{pid}: scene must reference an ai_input file')
        key = people_key(scene, pid)
        if key in people:
            raise ContractError(f'Duplicate person within scene: {scene}/{pid}')
        row = copy.deepcopy(entry)
        row.update(id=pid, scene=scene, people_key=key)
        if not isinstance(row.get('conclusions', {}), dict):
            row['legacy_conclusions'] = row['conclusions']
            row['conclusions'] = {'summary': str(row['conclusions'])}
        people[key] = row
    issues = source.get('issues', [])
    if not isinstance(issues, list):
        raise ContractError('issues must be a list')
    rows, index = [], {}
    for original in issues:
        if not isinstance(original, dict):
            raise ContractError('Every issue must be an object')
        issue = copy.deepcopy(original)
        iid = _text(issue.get('id'), 'issues.id')
        if iid in index:
            raise ContractError(f'Duplicate issue ID: {iid}')
        if legacy and not issue.get('scene'):
            candidates = [p for p in people.values() if p['id'] == issue.get('person')]
            if len(candidates) == 1:
                issue['scene'] = candidates[0]['scene']
        for key in (*LOCATION_FIELDS[1:], 'title'):
            if not legacy:
                _text(issue.get(key), f'issue {iid}.{key}')
            issue[key] = str(issue.get(key, ''))
        if not legacy and issue['group'] not in {'D', 'Q', 'F', 'R'}:
            raise ContractError(f'issue {iid}: unknown group')
        key = people_key(issue['scene'], issue['person'])
        person = people.get(key, {})
        if not legacy and (issue['scene'] not in files or files[issue['scene']].get('role') != 'ai_input' or not person):
            raise ContractError(f'issue {iid}: invalid scene/person reference')
        if legacy:
            issue.update(legacy_states(issue.get('status'), issue.get('group')))
            issue['history'] = [{'legacy_status': original.get('status', ''), 'verified': False}]
        else:
            for field in STATE_FIELDS:
                issue[field] = _state(issue.get(field), field, f'issue {iid}')
            if 'status' in issue or 'repair_status' in issue:
                raise ContractError(f'issue {iid}: prose status is not a v2 state; move it into history')
        seq = issue.get('sequence', 0)
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
            raise ContractError(f'issue {iid}: nonnegative integer sequence required')
        dependencies = issue.get('dependencies', [])
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) or not dep for dep in dependencies) or len(dependencies) != len(set(dependencies)):
            raise ContractError(f'issue {iid}: dependencies must be unique issue IDs')
        issue['dependencies'] = dependencies
        issue.update(sequence=seq, people_key=key, position=str(person.get('position', '')), color=str(person.get('color', '')),
                     filename=files.get(issue['scene'], {}).get('name', issue['scene']))
        rows.append(issue)
        index[iid] = issue
    topological_order = _dependency_order(rows, index)
    record_sources, updates = [], []
    for record_path in status_records:
        record_path = Path(record_path).resolve()
        record = json.loads(record_path.read_text('utf-8-sig'))
        if not isinstance(record, dict) or record.get('schema_version') != 2 or record.get('dataset_id') != dataset or record.get('source_manifest_sha256') != source_hash:
            raise ContractError(f'{record_path}: status identity missing/mismatched. Migration required; bare-ID legacy completed states cannot be inherited.')
        if legacy:
            raise ContractError('Migrate legacy manifest to schema 2 before applying status updates')
        record_sources.append(record)
        _walk_asset_paths(record, assets, 'status-record')
        for container in ('updates', 'repairs', 'records', 'issues'):
            values = record.get(container, [])
            if not isinstance(values, list):
                raise ContractError(f'{record_path}: {container} must be a list')
            for update in values:
                if not isinstance(update, dict):
                    raise ContractError('Status update must be an object')
                issue = index.get(update.get('id')) if isinstance(update.get('id'), str) else None
                if issue is None or any(update.get(k) != issue[k] for k in LOCATION_FIELDS):
                    raise ContractError('Status update complete location does not match manifest')
                sequence = update.get('sequence')
                if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence <= issue['sequence']:
                    raise ContractError(f"issue {issue['id']}: explicit sequence newer than manifest required")
                if 'status' in update or 'repair_status' in update:
                    raise ContractError('Prose status unsupported in v2; use four explicit state objects')
                for field in STATE_FIELDS:
                    if field in update:
                        _state(update[field], field, f"issue {issue['id']} update")
                if 'current_output' in update and update['current_output'] is None:
                    raise ContractError('Explicit empty current_output is invalid')
                updates.append(copy.deepcopy(update))
    seen_sequences = set()
    for update in sorted(updates, key=lambda value: (value['sequence'], value['id'])):
        iid, sequence = update['id'], update['sequence']
        if (iid, sequence) in seen_sequences:
            raise ContractError(f'issue {iid}: duplicate sequence; container/file order is not precedence')
        seen_sequences.add((iid, sequence))
        issue = index[iid]
        issue.setdefault('history', []).append({'sequence': issue['sequence'], **{k: copy.deepcopy(issue[k]) for k in STATE_FIELDS}, 'current_output': copy.deepcopy(issue.get('current_output'))})
        for field in (*STATE_FIELDS, 'current_output'):
            if field in update:
                issue[field] = copy.deepcopy(update[field])
        issue['sequence'] = sequence
    for issue in rows:
        iid = issue['id']
        raw_output = issue.get('current_output')
        if raw_output is None and len({r['scene'] for r in rows}) == 1:
            raw_output = source.get('current_output')
        issue['current_output'] = _binding(raw_output, assets, f'output:{iid}', strict=not legacy)
        evidence = {}
        for key, default in [('comparison_image', f'issues/{iid}.jpg'), ('native_ai', f'native/{iid}_ai.png'), ('native_ref', f'native/{iid}_ref.png')]:
            value = issue.get(key, default)
            evidence[key] = assets.fingerprint(value, f'{key}:{iid}')
            issue['image' if key == 'comparison_image' else key] = assets.link(value)
        issue['asset_fingerprints'] = evidence
        if not legacy:
            refs = issue.get('reference_ids')
            if not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in files or files[ref].get('role') != 'reference' for ref in refs) or len(refs) != len(set(refs)):
                raise ContractError(f'issue {iid}: reference_ids must refer to reference files')
            if issue['diagnosis']['status'] == 'confirmed' and not refs:
                raise ContractError(f'issue {iid}: confirmed issue requires a specific reference')
            if issue['review']['status'] == 'passed':
                reasons = _verify_visual_review(issue, files, assets)
                if reasons:
                    issue.setdefault('history', []).append({'unverified_review': copy.deepcopy(issue['review']), 'reasons': reasons})
                    issue['review'] = {'status': 'needs_review', 'reasons': reasons}
                    diagnostics.append(f'{iid}: visual pass not established: ' + '; '.join(reasons))
            current_output = issue['current_output']
            if current_output and not current_output['binding_valid']:
                issue.setdefault('history', []).append({'unverified_output': copy.deepcopy(current_output)})
                issue['review'] = {'status': 'needs_review', 'reasons': ['current output changed since binding']}
                diagnostics.append(f'{iid}: output hash changed; previous QA/adoption does not apply')
            adoption = issue['adoption']
            if adoption['status'] == 'adopted':
                valid = (issue['review']['status'] == 'passed' and current_output and adoption.get('output_sha256') == current_output['sha256']
                         and adoption.get('output_version') == current_output['version'] and adoption.get('explicit_user_acceptance') is True
                         and isinstance(adoption.get('evidence'), str) and bool(adoption['evidence'].strip()))
                if not valid:
                    issue.setdefault('history', []).append({'unverified_adoption': copy.deepcopy(adoption)})
                    issue['adoption'] = {'status': 'not_adopted', 'reason': 'No verified explicit adoption bound to current reviewed output'}
                    diagnostics.append(f'{iid}: old/unbound adoption retained as history only')
        confirmed = issue['diagnosis']['status'] == 'confirmed' and issue['group'] != 'R'
        review_status, repair_status = issue['review']['status'], issue['repair']['status']
        issue['legacy_readonly'] = legacy
        issue['default_selectable'] = bool(not legacy and confirmed and review_status in {'not_reviewed', 'failed'}
                                            and repair_status in {'pending', 'failed', 'not_executed', 'executed'}
                                            and not (repair_status == 'executed' and review_status == 'not_reviewed'))
        issue['redo_selectable'] = bool(not legacy and confirmed and issue['current_output'] and issue['current_output']['binding_valid']
                                        and repair_status == 'executed' and review_status in {'not_reviewed', 'passed'})
        if legacy:
            state = 'readonly'
        elif not confirmed:
            state = 'blocked'
        elif review_status in {'needs_review', 'revoked', 'insufficient'}:
            state = 'needs_review'
        elif issue['adoption']['status'] == 'adopted':
            state = 'adopted'
        elif review_status == 'passed':
            state = 'verified'
        elif repair_status == 'executed' and review_status == 'not_reviewed':
            state = 'repaired'
        else:
            state = 'pending' if issue['default_selectable'] else 'blocked'
        issue['state'], issue['state_text'] = state, ' / '.join(issue[field]['status'] for field in STATE_FIELDS)
    for iid in topological_order:
        issue = index[iid]
        blockers = [dep for dep in issue['dependencies'] if not (index[dep]['review']['status'] == 'passed'
                    and index[dep]['current_output'] and index[dep]['current_output']['binding_valid']
                    and index[dep]['state'] in {'verified', 'adopted'} and not index[dep].get('dependency_blockers'))]
        issue['dependency_blockers'] = blockers
        issue['actionability_reason'] = 'Dependencies require a review bound to their current final output: ' + ', '.join(blockers) if blockers else ''
        if blockers:
            issue['default_selectable'] = issue['redo_selectable'] = False
            if not legacy:
                issue['state'] = 'blocked'
            diagnostics.append(f"{issue['id']}: {issue['actionability_reason']}")
    asset_records = sorted(assets.records.values(), key=lambda value: value['path'])
    for asset in asset_records:
        asset['roles'].sort()
    report = {'schema_version': 2, 'dataset_id': dataset, 'source_manifest_sha256': source_hash,
              'title': title or source.get('title') or 'AI商品差异 · 批量选择', 'scope': str(source.get('scope', '')),
              'disclaimer': str(source.get('disclaimer', '模型目视判断，建议人工复核。')), 'legacy_readonly': legacy,
              'diagnostics': diagnostics, 'issues': rows, 'people': list(people.values()), 'files': list(files.values()),
              'topological_order': topological_order,
              'asset_fingerprints': asset_records, 'qa_contract_notice': 'Hashes validate bindings, not visual correctness. Passed requires a recorded visual review; user adoption is separate.',
              'source_context': {'manifest_path': str(manifest), 'output_path': str(output), 'status_record_paths': [str(Path(p).resolve()) for p in status_records], 'title_override': title}}
    semantic_rows = [{k: v for k, v in row.items() if k not in {'image', 'native_ai', 'native_ref'}} for row in rows]
    revision_data = {'schema': 2, 'dataset': dataset, 'source': source, 'source_hash': source_hash,
                     'records': sorted(record_sources, key=canonical), 'issues': semantic_rows, 'assets': asset_records,
                     'title': report['title'], 'people': report['people']}
    report['revision'] = hashlib.sha256(canonical(revision_data).encode('utf-8')).hexdigest()
    return report


def selection_summary(items):
    return {'issues': len(items), 'scenes': len({i['scene'] for i in items}), 'people': len({people_key(i['scene'], i['person']) for i in items})}


def instruction_for(items):
    if not items:
        return ''
    text = '请修复：' + '、'.join(i['id'] for i in items)
    return text + ('；仅修改所选 Logo 及必要融合边缘；其余保持不动。' if all(i['group'] == 'D' and i['feature'] == 'logo' for i in items) else '；其余保持不动。')


def selection_payload(data, ids, allow_redo=False):
    """Reference exporter for tests/non-browser callers; UI uses the same contract."""
    lookup = {i['id']: i for i in data['issues']}
    if len(ids) != len(set(ids)) or any(i not in lookup for i in ids):
        raise ContractError('Selection has duplicate/unknown IDs')
    items = [lookup[i] for i in ids]
    keys = (*LOCATION_FIELDS, 'title', 'current_output', *STATE_FIELDS)
    return {'schema_version': 2, 'dataset_id': data['dataset_id'], 'review_revision': data['revision'],
            'source_manifest_sha256': data['source_manifest_sha256'], 'allow_redo': bool(allow_redo),
            'selected_issues': [{k: copy.deepcopy(i.get(k)) for k in keys} for i in items],
            'summary': selection_summary(items), 'instruction': instruction_for(items)}


def validate_selection(data, payload):
    """Re-read trusted sources/files before validating either copy or JSON input."""
    context = data.get('source_context')
    if not context:
        raise ContractError('Fresh source_context required for selection validation')
    current = make_report(context['manifest_path'], context['output_path'], context['status_record_paths'], context.get('title_override'))
    if not isinstance(payload, dict) or payload.get('schema_version') != 2:
        raise ContractError('Selection schema 2 required; resolve bare IDs within an explicit current batch first')
    for key, expected in [('dataset_id', current['dataset_id']), ('review_revision', current['revision']), ('source_manifest_sha256', current['source_manifest_sha256'])]:
        if payload.get(key) != expected:
            raise ContractError(f'Stale/cross-batch selection: {key} mismatch; regenerate current selection')
    if current['legacy_readonly']:
        raise ContractError('Legacy manifest is read-only; migration required before repair selection')
    if not isinstance(payload.get('allow_redo'), bool):
        raise ContractError('Selection requires explicit allow_redo boolean')
    selected = payload.get('selected_issues')
    if not isinstance(selected, list) or not selected:
        raise ContractError('selected_issues must be a nonempty list')
    lookup, items, seen = {i['id']: i for i in current['issues']}, [], set()
    for row in selected:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or row['id'] not in lookup or row['id'] in seen:
            raise ContractError('Selection contains invalid/unknown/duplicate ID')
        issue = lookup[row['id']]
        for key in (*LOCATION_FIELDS, 'current_output', *STATE_FIELDS):
            if key not in row or row[key] != issue.get(key):
                raise ContractError(f"Selection binding changed: {issue['id']}.{key}")
        if 'title' in row and row['title'] != issue['title']:
            raise ContractError('Selection title changed')
        if not (issue['default_selectable'] or (payload['allow_redo'] and issue['redo_selectable'])):
            raise ContractError(f"Issue is not actionable within this selection: {issue['id']}")
        seen.add(row['id'])
        items.append(issue)
    if payload.get('summary') != selection_summary(items):
        raise ContractError('Selection summary does not match actual scope')
    if payload.get('instruction') != instruction_for(items):
        raise ContractError('Instruction conflicts with structured selection scope')
    return {'valid': True, 'dataset_id': current['dataset_id'], 'review_revision': current['revision'],
            'selected_ids': [i['id'] for i in items], 'summary': selection_summary(items), 'instruction': instruction_for(items)}


def render_markdown(data):
    lines = [f"# {data['title']}", '', f"批次：`{data['dataset_id']}`", f"修订：`{data['revision']}`", '', data['scope'], '',
             '文件指纹只验证记录绑定，不代替目视复核。', '']
    lines += [f'- {message}' for message in data['diagnostics']]
    lines += ['', '|编号|图片/人物|当前状态|', '|---|---|---|']
    for i in data['issues']:
        values = [i['id'], f"{i['scene']}/{i['person']}", i['state_text']]
        lines.append('|' + '|'.join(str(v).replace('|', '\\|').replace('\n', ' ') for v in values) + '|')
    def display(value):
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    for issue in data['issues']:
        lines += ['', f"## {issue['id']} · {issue['title']}", '', f"图片/人物：{issue['scene']}/{issue['person']}", '']
        for key, label in [('description', '观察'), ('visibility', '可见性'), ('material_checks', '面料检查'), ('reference_ids', '参考编号')]:
            value = issue.get(key)
            if value is not None and value != '' and value != {}:
                lines += [f'{label}：{display(value)}', '']
        current_output = issue.get('current_output')
        if current_output:
            lines += [f"当前输出：{current_output['version']} · {current_output['path']}",
                      f"输出 SHA256：`{current_output['sha256']}`；绑定有效：{current_output['binding_valid']}", '']
        review = issue['review']
        checks = review.get('checks')
        if isinstance(checks, dict):
            for key in QA_CHECKS:
                check = checks.get(key)
                if isinstance(check, dict):
                    # Display only recorded observations. Missing checks/notes are not filled in.
                    parts = [str(check[field]) for field in ('result', 'notes') if field in check]
                    if parts:
                        lines += [f"QA {key}：{' · '.join(parts)}", '']
        for key, label in [('reasons', '复核诊断')]:
            if review.get(key):
                lines += [f'{label}：{display(review[key])}', '']
        if issue.get('actionability_reason'):
            lines += [f"执行限制：{issue['actionability_reason']}", '']
    return '\n'.join(lines + ['', data['disclaimer'], ''])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, help='HTML location for relative links; does not write HTML')
    parser.add_argument('--status-record', action='append', type=Path, default=[])
    parser.add_argument('--title')
    parser.add_argument('--validate-selection', type=Path)
    parser.add_argument('--report-json', type=Path)
    parser.add_argument('--report-md', type=Path)
    args = parser.parse_args()
    try:
        data = make_report(args.manifest, args.output or args.manifest.with_name('review.html'), args.status_record, args.title)
        result = validate_selection(data, json.loads(args.validate_selection.read_text('utf-8-sig'))) if args.validate_selection else {'schema_version': 2, 'dataset_id': data['dataset_id'], 'revision': data['revision'], 'issues': len(data['issues']), 'diagnostics': data['diagnostics']}
        for path, content in [(args.report_json, json.dumps(data, ensure_ascii=False, indent=2)), (args.report_md, render_markdown(data))]:
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
        print(json.dumps(result, ensure_ascii=True))
    except (ContractError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f'Review contract error: {exc}\n')


if __name__ == '__main__':
    main()
