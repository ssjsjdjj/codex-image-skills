"""Prepare dated requests, read-only history navigation and evidence preflight.

The index is NOT a report, accepted work count, or evidence of business value.
Only Python's standard library is required. No credentials or message bodies copied.
"""
import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

SHANGHAI = timezone(timedelta(hours=8), name='Asia/Shanghai')
SKILL = Path(__file__).resolve().parents[1]


def dump(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def parse_date(value):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('Dates must use YYYY-MM-DD')
    return date.fromisoformat(value)


def full(value):
    return f'{value.year}年{value.month}月{value.day}日'


def period(start_date, end_date, now=None):
    start, end = parse_date(start_date), parse_date(end_date)
    if start > end:
        raise ValueError('Start date must not follow end date')
    if end == date.max:
        raise ValueError('End date must allow an exclusive next-day boundary')
    current = now or datetime.now(SHANGHAI)
    if current.utcoffset() is None:
        raise ValueError('Current time must include a timezone')
    current = current.astimezone(SHANGHAI)
    left = datetime.combine(start, time.min, SHANGHAI)
    right = datetime.combine(end + timedelta(days=1), time.min, SHANGHAI)
    cutoff = min(right, current)
    return {
        'start_date': start.isoformat(), 'end_date': end.isoformat(),
        'timezone': 'Asia/Shanghai', 'start_inclusive': left.isoformat(),
        'requested_end_exclusive': right.isoformat(), 'cutoff_exclusive': cutoff.isoformat(),
        'created_at': current.isoformat(),
        'status': 'not_started' if cutoff <= left else ('in_progress' if current < right else 'closed'),
        'truncated_to_current_time': current < right,
    }


def render_prompt(window):
    start, end = parse_date(window['start_date']), parse_date(window['end_date'])
    end_title = f'{end.month}月{end.day}日' if start.year == end.year else full(end)
    variables = {
        'TITLE_RANGE': full(start) + '-' + end_title,
        'START_FULL': full(start), 'END_FULL': full(end),
    }
    template = (SKILL / 'assets' / 'codex-usage-prompt.txt').read_text(encoding='utf-8-sig')
    if set(re.findall(r'\{\{([A-Z_]+)\}\}', template)) != set(variables):
        raise ValueError('Fixed template variables do not match the renderer')
    for key, value in variables.items():
        template = template.replace('{{' + key + '}}', value)
    return template, variables


def prepare(start_date, end_date, kind, out, now=None):
    if kind != 'usage':
        raise ValueError('Invalid writing kind')
    window = period(start_date, end_date, now)
    prompt, variables = render_prompt(window)
    root = Path(out).resolve()
    root.mkdir(parents=True, exist_ok=False)
    request = {
        'schema': 1, 'kind': kind, 'mode': 'real', 'period': window,
        'template': 'assets/codex-usage-prompt.txt', 'variables': variables,
        'template_sha256': hashlib.sha256((SKILL / 'assets' / 'codex-usage-prompt.txt').read_bytes()).hexdigest(),
        'status': 'awaiting_evidence_review',
        'notice': 'This directory is authoring input, not a completed report or user approval.',
    }
    dump(root / 'request.json', request)
    (root / '使用报告固定提示词.txt').write_text(prompt, encoding='utf-8-sig')
    # Navigation only: the agent populates factual rows after reading primary records.
    dump(root / 'evidence-register.json', {
        'schema': 1, 'period': window, 'review_status': 'not_reviewed',
        'sources': [], 'tasks': [], 'claims': [], 'missing': [],
        'task_fields': ['id', 'time', 'task', 'codex_actions', 'output_version', 'result_status',
                        'human_judgment', 'correction_actor', 'reverification_basis',
                        'source_locations', 'account_scope', 'period_verified', 'limitations',
                        'time_comparison', 'case_path', 'coverage_path'],
        'claim_fields': ['id', 'text', 'kind:confirmed|classification|unknown', 'evidence_ids'],
    })
    return {'request': str(root / 'request.json'), 'kind': kind, 'period': window,
            'next': 'Read references/writing.md, inspect primary evidence, run preflight and resolve/disclose gaps before delivery.'}


def parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.utcoffset() is not None else None
    except ValueError:
        return None


def identity(payload):
    # Only compared in memory. Never serialized or printed.
    return tuple(payload.get(key) for key in ('creator_account_id', 'creator_user_id'))


def activity(row):
    pay = row.get('payload')
    if not isinstance(pay, dict):
        return False
    if row.get('type') == 'event_msg':
        return pay.get('type') in ('user_message', 'agent_message')
    if row.get('type') != 'response_item':
        return False
    if pay.get('type') == 'message':
        return pay.get('role') in ('user', 'assistant') and pay.get('channel') != 'analysis'
    return pay.get('type') in ('function_call', 'function_call_output', 'custom_tool_call', 'custom_tool_call_output')


def read_history(path, left, cutoff):
    meta, lines, types = {}, [], Counter()
    bad, missing_time, matched, first, last = 0, 0, 0, None, None
    with path.open(encoding='utf-8-sig') as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(row, dict):
                bad += 1
                continue
            if row.get('type') == 'session_meta' and isinstance(row.get('payload'), dict):
                meta = row['payload']
                continue
            if not activity(row):
                continue
            stamp = parse_timestamp(row.get('timestamp'))
            if stamp is None:
                missing_time += 1
                continue
            if left <= stamp < cutoff:
                matched += 1
                if len(lines) < 40:
                    lines.append(number)
                types[row['type']] += 1
                first = min(first, stamp) if first else stamp
                last = max(last, stamp) if last else stamp
    sid = meta.get('session_id') or meta.get('id')
    if not isinstance(sid, str) or not sid:
        sid = 'path-' + hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:20]
    parent = meta.get('parent_thread_id')
    return {
        'path': str(path), 'session_id': sid, 'parent_thread_id': parent if isinstance(parent, str) else None,
        'matching_line_numbers': lines, 'locations_truncated': matched > len(lines),
        'activity_rows_before_deduplication': matched,
        'event_types': dict(types),
        'first_activity': first.astimezone(SHANGHAI).isoformat() if first else None,
        'last_activity': last.astimezone(SHANGHAI).isoformat() if last else None,
        'invalid_json_rows': bad, 'activity_rows_missing_aware_time': missing_time,
        '_owner': identity(meta),
    }


def owner_scope(owner, anchor):
    if anchor is None:
        return 'unknown'
    compared = [(a, b) for a, b in zip(owner, anchor) if isinstance(a, str) and a and isinstance(b, str) and b]
    if any(a != b for a, b in compared):
        return 'different_account_or_user'
    # Both account and user must be known to claim current personal ownership.
    return 'current_account_and_user' if len(compared) == 2 else 'unknown'


def scan(request_path, out, codex_home=None, current_thread=None):
    request = load(request_path)
    window = request['period']
    if request.get('mode') != 'real' or window.get('timezone') != 'Asia/Shanghai':
        raise ValueError('A real Asia/Shanghai request is required')
    left = parse_timestamp(window['start_inclusive'])
    cutoff = parse_timestamp(window['cutoff_exclusive'])
    if left is None or cutoff is None:
        raise ValueError('Invalid report time boundaries')
    target = Path(out).resolve()
    if target.exists():
        raise FileExistsError('Scan output already exists')
    home = Path(codex_home or os.environ.get('CODEX_HOME') or (Path.home() / '.codex')).resolve()
    current = current_thread or os.environ.get('CODEX_THREAD_ID')
    candidates, inventory, diagnostics = [], [], []
    anchor = None
    for name in ('sessions', 'archived_sessions'):
        root = home / name
        source = {'category': name, 'status': 'not_found', 'files_read': 0, 'files_failed': 0}
        inventory.append(source)
        if not root.is_dir():
            continue
        source['status'] = 'readable'
        try:
            paths = sorted(root.rglob('*.jsonl'))
        except OSError as error:
            source['status'] = 'unreadable'
            source['error_type'] = type(error).__name__
            continue
        for path in paths:
            # Do not read a symlink pointing outside its configured history directory.
            if not path.resolve().is_relative_to(root.resolve()):
                source['files_failed'] += 1
                continue
            try:
                record = read_history(path, left, cutoff)
                source['files_read'] += 1
            except (OSError, UnicodeError) as error:
                source['files_failed'] += 1
                diagnostics.append({'path': str(path), 'error_type': type(error).__name__})
                continue
            if current and record['session_id'] == current:
                found = record['_owner']
                # Conflicting anchors cannot establish personal ownership.
                if anchor is not None and found != anchor:
                    anchor = ('__conflicting_anchor__', '__conflicting_anchor__')
                else:
                    anchor = found
            if record['activity_rows_before_deduplication']:
                candidates.append(record)
            if record['invalid_json_rows'] or record['activity_rows_missing_aware_time']:
                diagnostics.append({k: record[k] for k in ('path', 'invalid_json_rows', 'activity_rows_missing_aware_time')})
        if source['files_failed']:
            source['status'] = 'partially_readable'
    if anchor == ('__conflicting_anchor__', '__conflicting_anchor__'):
        anchor = None
    for record in candidates:
        record['account_scope'] = owner_scope(record.pop('_owner'), anchor)
    value = {
        'schema': 1, 'mode': 'real', 'period': window,
        'coverage': '部分可读，无法读取完整 Codex 记录',
        'personal_ownership_anchor_available': anchor is not None and all(isinstance(x, str) and x for x in anchor),
        'source_inventory': inventory, 'diagnostics': diagnostics,
        'candidate_files': candidates,
        'work_session_count': None, 'work_task_count': None, 'verified_output_count': None,
        'notice': 'Candidate navigation only. Verify ownership, work relevance, duplicates, period, outputs and human judgment before counting. No message bodies copied.',
        'other_sources': 'App history, projects, workspace outputs, nonsecret config and Git require separate targeted review; this scan does not inspect them.',
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    dump(target, value)
    return {'index': str(target), 'candidate_files': len(candidates), 'coverage': value['coverage'],
            'work_session_count': None, 'status': 'needs_primary_evidence_review'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare')
    p.add_argument('--start-date', required=True)
    p.add_argument('--end-date', required=True)
    p.add_argument('--kind', choices=('usage',), default='usage')
    p.add_argument('--out', required=True)
    p = commands.add_parser('scan')
    p.add_argument('--request', required=True)
    p.add_argument('--codex-home')
    p.add_argument('--current-thread')
    p.add_argument('--out', required=True)
    p = commands.add_parser('preflight')
    p.add_argument('--request')
    p.add_argument('--register', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--delivery', action='store_true')
    args = vars(parser.parse_args())
    command = args.pop('command')
    if command == 'preflight':
        from report_preflight import preflight
        delivery = args.pop('delivery')
        args['register_path'] = args.pop('register')
        args['request_path'] = args.pop('request')
        result = preflight(**args)
        print(json.dumps(result, ensure_ascii=False))
        if delivery and not result['ready_for_delivery']:
            raise SystemExit(2)
        return
    if command == 'scan':
        args['request_path'] = args.pop('request')
    result = prepare(**args) if command == 'prepare' else scan(**args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit('ERROR: ' + str(error))
