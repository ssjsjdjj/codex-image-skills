"""Read-only evidence check for Codex usage reports."""
import hashlib
import json
from pathlib import Path

import evidence


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def check(register, request=None):
    if not isinstance(register, dict):
        raise ValueError('Evidence register must be an object')
    blockers, limitations, cases = [], [], []
    if register.get('review_status') != 'reviewed':
        blockers.append('先回读原始记录并将证据清单标为reviewed；扫描候选不算核验。')
    if request is not None:
        if request.get('mode') != 'real' or request.get('period') != register.get('period'):
            blockers.append('编稿请求与证据清单的真实模式或日期范围不一致。')
    tasks = register.get('tasks')
    if not isinstance(tasks, list):
        raise ValueError('tasks must be a list')
    if not tasks and not nonempty(register.get('no_valid_work_evidence')):
        blockers.append('没有核验任务时需说明实际检索范围和未发现有效记录的限制。')
    seen = set()
    for task in tasks:
        if not isinstance(task, dict) or not nonempty(task.get('id')):
            blockers.append('每项已核验任务需有唯一id。')
            continue
        key = task['id']
        if key in seen:
            blockers.append(key + '：任务id重复，先去重。')
            continue
        seen.add(key)
        if type(task.get('time_comparison')) is not bool:
            blockers.append(key + '：需注明正文是否比较用时（time_comparison）。')
            continue
        state, source_hash, coverage_hash = None, None, None
        case_path = task.get('case_path')
        if case_path:
            path = Path(case_path)
            if not path.is_absolute():
                blockers.append(key + '：case_path需为真实案例的绝对目录。')
                continue
            try:
                _, state = evidence.load(path)
                source_hash = evidence.sha(path / 'case.json')
                if task.get('coverage_path'):
                    coverage_path = Path(task['coverage_path'])
                    if not coverage_path.is_absolute():
                        raise ValueError('coverage_path must be absolute')
                    state['timing_coverage'] = evidence.read(coverage_path)
                    coverage_hash = evidence.sha(coverage_path)
            except (OSError, ValueError, KeyError, TypeError) as error:
                blockers.append(key + '：案例或覆盖核对文件不可用（' + type(error).__name__ + '）。')
                continue
        result = {'id': key, 'time_comparison': task['time_comparison'],
                  'case_sha256': source_hash, 'coverage_sha256': coverage_hash}
        if task['time_comparison']:
            if state is None:
                limits = ['没有可回查的同口径计时证据，正文只能描述已有事实。']
            else:
                state.setdefault('closeout', {})['net_savings_requested'] = True
                try:
                    status = evidence.submission_status(state)
                except (ValueError, KeyError, TypeError) as error:
                    blockers.append(key + '：案例字段需先核对（' + type(error).__name__ + '）。')
                    continue
                limits = status['evidence_limits'] + status['missing_timing_records']
                result.update(net_minutes=status['net_minutes'], conclusion=status['conclusion'],
                              coverage=status['timing_coverage'])
            limitations.extend({'task_id': key, 'text': message} for message in limits)
        cases.append(result)
    ready = not blockers
    return {'schema': 1, 'ready_for_delivery': ready,
            'status': 'needs_attention' if blockers else ('limited_draft' if limitations else 'ready_for_author_review'),
            'blockers': blockers,
            'limitations': limitations, 'cases': cases,
            'register_sha256': digest(register), 'request_sha256': digest(request),
            'notice': '在对应章节注明证据限制，净节省仅引用已核算结果。通过预检表示可以展示待本人核对稿。'}


def preflight(register_path, out, request_path=None):
    register = evidence.read(register_path)
    request = evidence.read(request_path) if request_path else None
    target = Path(out).resolve()
    # Keep diagnostics in the new authoring directory, never in historical cases.
    for task in register.get('tasks', []):
        if isinstance(task, dict) and task.get('case_path'):
            if target.is_relative_to(Path(task['case_path']).resolve()):
                raise ValueError('Preflight output must be outside historical cases')
    result = check(register, request)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write('\n')
    return result
