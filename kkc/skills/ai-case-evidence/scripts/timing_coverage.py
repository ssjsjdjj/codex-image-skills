"""Review task coverage separately from the completeness of registered timers."""
import hashlib
import json

COMPONENTS = {'ai': ('ai_minutes', 'AI运行'), 'check': ('check_minutes', '人工检查'),
              'rework': ('rework_minutes', '返工及失败重试')}


def fingerprint(state):
    values = state.get('timing', {})
    summary = state.get('timing_journal', {}).get('summary', {})
    material = {
        'scope': {k: state.get('card', {}).get(k, {}).get('text') for k in ('what', 'ai_step')},
        'times': {k: values.get(k) for k in ('sample_count', 'ai_minutes', 'check_minutes', 'rework_minutes')},
        'journal': {k: summary.get(k) for k in ('workflow_closed', 'ai_complete', 'human_complete',
                                             'steps', 'human_sessions', 'incomplete', 'corrupt_events')},
    }
    if state.get('human_check_reports') or state.get('human_check_accounting'):
        material['human_check_reports'] = state.get('human_check_reports', [])
        material['human_check_accounting'] = state.get('human_check_accounting')
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def make_review(state, values):
    if not isinstance(values, dict) or set(values) != {'scope', 'components'}:
        raise ValueError('Coverage requires scope and components')
    if not isinstance(values['scope'], str) or not values['scope'].strip():
        raise ValueError('Describe the actual task scope covered by this review')
    if not isinstance(values['components'], dict) or set(values['components']) != set(COMPONENTS):
        raise ValueError('Review ai, check and rework separately')
    components = {}
    for name, value in values['components'].items():
        if not isinstance(value, dict) or set(value) != {'status', 'basis', 'sources', 'gaps'}:
            raise ValueError('Each component requires status, basis, sources and gaps')
        if value['status'] not in ('unknown', 'partial', 'complete'):
            raise ValueError('Coverage status must be unknown, partial or complete')
        if not isinstance(value['basis'], str):
            raise ValueError('Coverage basis must be text')
        for key in ('sources', 'gaps'):
            if not isinstance(value[key], list) or any(not isinstance(x, str) or not x.strip() for x in value[key]):
                raise ValueError('Coverage sources and gaps must be lists of nonempty text')
        if value['status'] == 'complete' and (not value['basis'].strip() or not value['sources'] or value['gaps']):
            raise ValueError('Complete coverage needs traceable sources, a basis and no unrecorded gaps')
        if value['status'] == 'partial' and not value['gaps']:
            raise ValueError('Partial coverage must identify the unrecorded scope')
        components[name] = dict(value)
    return {'schema': 1, 'scope': values['scope'].strip(), 'components': components,
            'binding': fingerprint(state)}


def assess(state):
    """Missing coverage is unknown for old cases; never promote a numeric value."""
    review = state.get('timing_coverage')
    valid = isinstance(review, dict) and review.get('schema') == 1
    if valid:
        try:
            make_review(state, {k: review[k] for k in ('scope', 'components')})
        except (ValueError, KeyError):
            valid = False
    stale = bool(valid and review.get('binding') != fingerprint(state))
    summary = state.get('timing_journal', {}).get('summary', {})
    issues, statuses = [], {}
    for name, (field, label) in COMPONENTS.items():
        item = review['components'][name] if valid and not stale else {}
        status = item.get('status', 'unknown')
        reasons = []
        if state.get('timing', {}).get(field) is None:
            reasons.append('尚缺耗时记录')
        if stale:
            reasons.append('范围或计时已变化，覆盖核对需重新进行')
        elif status != 'complete':
            reasons.extend(item.get('gaps') or ['尚未核实是否覆盖整项工作'])
        if summary:
            if name in ('ai', 'rework') and summary.get('ai_complete') is not True:
                reasons.append('已登记AI步骤尚未完整结束或日志存在问题')
            if name == 'check':
                human = state.get('human_check_accounting', {})
                reasons.extend(human.get('issues', []))
                sessions = summary.get('human_sessions', [])
                reported = human.get('source_kind') == 'user_report' and bool(human.get('report_ids'))
                if sessions and any(s.get('status') in ('running', 'paused') for s in sessions):
                    reasons.append('人工检查日志尚未完整结束')
                elif summary.get('human_complete') is not True and not reported:
                    reasons.append('人工检查日志或本人报告来源尚未核实')
        if reasons:
            issues.append(label + '：' + '；'.join(dict.fromkeys(reasons)))
        statuses[name] = 'complete' if not reasons else ('partial' if status == 'partial' else 'unknown')
    return {'complete': not issues, 'stale': stale, 'components': statuses, 'issues': issues,
            'note': '已登记步骤均结束只证明这些步骤计时完成；全流程覆盖须另据真实记录核对。'}
