"""Integration helpers for the evidence workflow; standard library only."""
import json
import math
import os
from pathlib import Path
import sys
import run_journal as journal
import timing_coverage


def setup(argv):
    case=journal.flag_path(argv,('--case','--out'),Path.cwd()/'case')
    existing={}
    if (case/'case.json').is_file(): existing=json.loads((case/'case.json').read_text(encoding='utf-8-sig'))
    default=existing.get('timing_journal',{}).get('root') or str(case.parent/(case.name+'-timing'))
    cleaned,root,mode=journal.peel_options(argv,default)
    if '--timing-mode' not in argv and 'AI_TIMING_MODE' not in os.environ:
        if existing: mode=existing['mode']
        elif '--mode' in cleaned: mode=cleaned[cleaned.index('--mode')+1]
    if mode != 'real': raise ValueError('This skill now accepts real work cases only')
    return cleaned,journal.Journal(root,mode)


def attach(root,state):
    j=journal._ACTIVE.get()
    if j: state['timing_journal']=dict(root=str(j.root),mode=j.mode)


def review_key(value):
    if value.get('review_id'):
        return str(value['review_id'])
    if value.get('revision_reviewed') is not None:
        return 'revision-' + str(value['revision_reviewed'])
    return None


def check_accounting(state, report):
    """Keep reported reviews separate from timers; combine only proven disjoint scopes."""
    sessions = {s['id']: s for s in report.get('human_sessions', [])}
    finished = [s for s in sessions.values() if s['status'] == 'finished']
    known = sum(sum(s['segments']) for s in finished)
    seen, issues, reports_used = {}, [], []
    for value in state.get('human_check_reports', []):
        key, seconds = review_key(value), value.get('seconds')
        if (key is None or isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not math.isfinite(seconds) or seconds < 0 or not value.get('source', '').strip()):
            issues.append('本人检查报告缺少稳定轮次、有效秒数或来源，需先核对原话')
            continue
        if key in seen:
            if seen[key] != seconds:
                issues.append('同一检查轮次有不同秒数，需核对：' + key)
            continue
        seen[key] = seconds
        linked = value.get('timer_session_id')
        if linked:
            if linked not in sessions or sessions[linked]['status'] != 'finished':
                issues.append('本人报告关联的计时会话未完成或未找到：' + key)
            # A report about a timed review is evidence, not another duration to add.
            continue
        if sessions and not value.get('independent_of_timer'):
            issues.append('本人报告与自动检查会话是否重叠尚未核对：' + key)
            continue
        known += seconds
        reports_used.append(key)
    source_kind = 'mixed' if finished and reports_used else ('journal' if finished else ('user_report' if reports_used else 'unknown'))
    if not finished and not reports_used:
        # Preserve old numeric facts instead of silently erasing them on timer-sync.
        minutes = state.get('timing', {}).get('check_minutes')
        if minutes is not None:
            source_kind = 'legacy'
            issues.append('已有人工检查分钟保留，计时或本人报告来源仍需核对')
    else:
        minutes = known / 60
    return dict(minutes=minutes, known_seconds=known if finished or reports_used else None,
                source_kind=source_kind, report_ids=reports_used, issues=list(dict.fromkeys(issues)))


def report_review(api, case, seconds, review_id, evidence, timer_session_id=None,
                  independent_of_timer=False, all_checks_accounted=False):
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds < 0 or not review_id.strip() or not evidence.strip()):
        raise ValueError('A review report needs nonnegative seconds, a stable review ID and actual user evidence')
    root, state = api.load(case)
    for old in state.get('human_check_reports', []):
        if review_key(old) == review_id:
            if old.get('seconds') != seconds or old.get('timer_session_id') != timer_session_id:
                raise ValueError('Conflicting report for this review ID; preserve and resolve the original evidence')
            if all_checks_accounted and state.get('closeout', {}).get('check_time_complete') is not True:
                state.setdefault('closeout', {})['check_time_complete'] = True
                state['closeout']['deferred_fields'] = [x for x in state['closeout'].get('deferred_fields', []) if x != 'check_minutes']
                state.setdefault('closeout_sources', {})['check_time_complete'] = evidence
                api.save(root, state, 'review-coverage-user-confirmed')
            return dict(review_id=review_id, status='already_recorded', timer_unchanged=True,
                        closeout_review=api.submission_status(state))
    value = dict(review_id=review_id, seconds=seconds, kind='user_report', source=evidence,
                 measured_by_journal=False, timer_session_id=timer_session_id,
                 independent_of_timer=independent_of_timer)
    state.setdefault('human_check_reports', []).append(value)
    answers = state.setdefault('closeout', {})
    answers['check_time_complete'] = bool(all_checks_accounted)
    state.setdefault('closeout_sources', {})['check_time_complete'] = evidence
    if all_checks_accounted:
        answers['deferred_fields'] = [x for x in answers.get('deferred_fields', []) if x != 'check_minutes']
    pointer = state.get('timing_journal', {})
    j = journal._ACTIVE.get() or journal.Journal(pointer.get('root') or root.parent / (root.name + '-timing'), state['mode'])
    state['timing_journal'] = dict(pointer, root=str(j.root), mode=j.mode)
    api.save(root, state, 'review-user-report')
    j.event('reported_check_duration', review_id=review_id, seconds=seconds, evidence=evidence)
    sync(api, case, j)
    _, state = api.load(case)
    return dict(review_id=review_id, status='recorded', closeout_review=api.submission_status(state))


def sync(api,case,j=None):
    root,state=api.load(case)
    if j is None:
        pointer=state.get('timing_journal')
        if not pointer: return None
        j=journal.Journal(pointer['root'],state['mode'])
    if j.mode!=state['mode']: raise ValueError('Journal mode differs from the real case')
    report=journal.summary(j)
    state['timing_journal']=dict(root=str(j.root),mode=j.mode,summary=report)
    state['timing_journal']['technical_rework_step_count']=report['rework_count']
    accounting='自动计时来源：'+str(j.root)+'；仅计已接入步骤；AI及额外返工按窗口并集去重，失败保留；人工计时按真实起止排除暂停，本人直接报告按轮次及来源另记并核对重叠。技术返工步骤数不等于人工退回次数或实际修订轮次。'
    state['timing_journal']['accounting_basis']=accounting
    human = check_accounting(state, report)
    state['human_check_accounting'] = human
    values=dict(state['timing'])
    if report['steps']:
        values.update(ai_minutes=None if report['ai_seconds'] is None else report['ai_seconds']/60,
                      rework_minutes=None if report['rework_seconds'] is None else report['rework_seconds']/60)
        # Preserve explicit business counts, and leave legacy unknown counts unclassified.
        # The journal's top-level step count stays solely in timing_journal above.
        values.setdefault('measurement_kind','unknown')
        values.setdefault('rework_count_kind','unknown')
        if not values.get('basis','').strip():
            values['basis']=state.get('closeout',{}).get('baseline_basis') or accounting
    if human['minutes'] is not None or 'check_minutes' not in values:
        values['check_minutes'] = human['minutes']
    api.validate_timing(state,values);state['timing']=values
    api.save(root,state,'timing-auto-sync')
    return report


def run_control(api,case,command,evidence,j):
    root,state=api.load(case)
    if command=='timer-sync': return sync(api,case,j)
    mapped={'review-start':'check-start','review-pause':'check-pause','review-resume':'check-resume','review-finish':'check-finish','review-cancel':'check-cancel','review-status':'check-status','workflow-start':'workflow-start','workflow-finish':'workflow-finish','timer-status':'summary'}[command]
    if command in ('review-start','review-finish'):
        records,bad=j.records()
        if bad:raise RuntimeError('Journal has unreadable events; preserve and inspect them')
        sessions=journal.human_sessions(records)
        active=[s for s in sessions if s['status'] in ('running','paused')]
        if command=='review-start' and active:
            if not evidence.strip():raise ValueError('Human timer requires an actual instruction or evidence')
            j.event('review_start_repeated',session_id=active[-1]['id'],evidence=evidence)
            sync(api,case,j)
            return dict(session_id=active[-1]['id'],status='already_'+active[-1]['status'],timer_unchanged=True,quality_confirmation='not_inferred')
        finished=[s for s in sessions if s['status']=='finished']
        if command=='review-finish' and not active and finished:
            if not evidence.strip():raise ValueError('Human timer requires an actual instruction or evidence')
            j.event('review_finish_repeated',session_id=finished[-1]['id'],evidence=evidence)
            sync(api,case,j)
            return dict(session_id=finished[-1]['id'],status='already_finished',timer_unchanged=True,quality_confirmation='not_inferred')
    result=journal.control(j,mapped,['--evidence',evidence] if evidence else [])
    sync(api,case,j)
    if command == 'workflow-finish':
        _, state = api.load(case)
        result = dict(result, closeout_review=api.submission_status(state))
    return result
