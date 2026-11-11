"""Local evidence preparation. No scoring, business actions, or inferred acceptance."""
import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parent))
import timing_coverage


def timing_api():
    return SimpleNamespace(load=load,save=save,validate_timing=validate_timing,
                           submission_status=submission_status)

FIELDS = ('what', 'ai_step', 'human_judgment', 'application', 'evidence', 'reuse')
LABELS = ('工作', 'AI步骤', '本人判断', '实际应用', '证据位置', '复用记录')
ROLES = ('original', 'ai_first', 'issue', 'final', 'application', 'acceptance', 'other')
ROLE_LABELS = ('原始输入', 'AI第一版', '问题与修正依据', '人工复核终版', '实际应用', '验收记录', '其他')
NUMBERS = ('baseline_minutes', 'ai_minutes', 'check_minutes', 'rework_minutes', 'rework_count', 'sample_count')
MANUAL_TIME_FACTS = {'baseline_minutes':'人工基线分钟', 'measurement_kind':'实测或估算性质', 'baseline_basis':'人工基线依据', 'same_scope':'同口径范围', 'check_minutes':'人工检查用时', 'unlogged_human_minutes':'计时外人工用时', 'unlogged_human_kind':'额外人工用时性质'}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def load(case):
    root = Path(case).resolve()
    state = read(root / 'case.json')
    if state['mode'] != 'real':
        raise ValueError('Invalid mode')
    return root, state


def save(root, state, action):
    state['updated_at'] = now()
    temp = root / 'case.pending.json'
    if temp.exists():
        raise FileExistsError('Another write or incomplete operation exists')
    write(temp, state)
    temp.replace(root / 'case.json')
    with (root / 'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(dict(at=now(), action=action, state_sha256=sha(root / 'case.json'), mode=state['mode']), ensure_ascii=False) + '\n')


def init(out, mode, title):
    if mode != 'real': raise ValueError('This skill now accepts real work cases only')
    root = Path(out).resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'evidence').mkdir()
    state = dict(schema=1, mode=mode, title=title, created_at=now(), card={}, timing={}, artifacts=[],
                 closeout={})
    import timing_commands
    timing_commands.attach(root, state)
    save(root, state, 'init')
    return root


def check_kind(state, kind):
    if state['mode'] != 'real' or kind not in ('observed', 'user_report'):
        raise ValueError('Only observed evidence or actual user reports can enter real cases')


def set_field(case, field, text, kind, source):
    root, state = load(case)
    check_kind(state, kind)
    if not text.strip() or not source.strip():
        raise ValueError('Text and source are required')
    state['card'][field] = dict(text=text.strip(), kind=kind, source=source.strip())
    save(root, state, 'set:' + field)


def validate_timing(state, values):
    if set(values) - set(NUMBERS) - {'same_scope', 'measurement_kind', 'basis', 'rework_count_kind', 'rework_count_basis'}:
        raise ValueError('Unexpected timing field')
    for key in NUMBERS:
        value = values.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('Invalid nonnegative finite number: ' + key)
        if key in ('sample_count', 'rework_count') and (int(value) != value or (key == 'sample_count' and value == 0)):
            raise ValueError('Invalid count: ' + key)
    if values.get('same_scope') is not None and type(values['same_scope']) is not bool:
        raise ValueError('same_scope must be true, false, or null')
    kind = values.get('measurement_kind', 'unknown')
    if kind not in ('measured', 'estimate', 'unknown'):
        raise ValueError('Invalid measurement_kind')
    if kind != 'unknown':
        check_kind(state, 'user_report')
    if not isinstance(values.get('basis', ''), str):
        raise ValueError('basis must be text')
    if values.get('rework_count_kind', 'unknown') not in ('unknown', 'human_return', 'revision_round'):
        raise ValueError('Invalid rework_count_kind')
    if not isinstance(values.get('rework_count_basis', ''), str):
        raise ValueError('rework_count_basis must be text')
    if values.get('rework_count_kind', 'unknown') != 'unknown' and values.get('rework_count') is not None and not values.get('rework_count_basis', '').strip():
        raise ValueError('Actual rework counts need their counting scope and source')


def timing(case, values):
    root, state = load(case)
    validate_timing(state, values)
    state['timing'] = values
    if values.get('baseline_minutes') is not None and values.get('basis', '').strip() and not values['basis'].startswith('自动计时来源：'):
        state.setdefault('closeout', {})['baseline_basis'] = values['basis'].strip()
    deferred=set(state.get('closeout',{}).get('deferred_fields',[]))
    for key in ('baseline_minutes','measurement_kind','same_scope'):
        if (key=='baseline_minutes' and values.get(key) is not None) or (key=='measurement_kind' and values.get(key,'unknown')!='unknown') or (key=='same_scope' and values.get(key) is True):
            deferred.discard(key)
    if state.get('closeout',{}).get('baseline_basis','').strip():deferred.discard('baseline_basis')
    if 'deferred_fields' in state.get('closeout',{}):state['closeout']['deferred_fields']=sorted(deferred)
    save(root, state, 'timing')


def calculate(values):
    # Counts never enter the time subtraction. The sample scope must still be known.
    required = ('baseline_minutes', 'ai_minutes', 'check_minutes', 'rework_minutes', 'sample_count')
    missing = [k for k in required if values.get(k) is None]
    if missing or values.get('same_scope') is not True or not values.get('basis', '').strip() or values.get('measurement_kind', 'unknown') == 'unknown':
        return None, '待补数据或核对口径，暂不能证明净改善'
    result = round(values['baseline_minutes'] - values['ai_minutes'] - values['check_minutes'] - values['rework_minutes'], 6)
    prefix = {'estimate': '估算：', 'measured': '按所填记录计算：'}[values['measurement_kind']]
    conclusion = '未提效' if result <= 0 else '有净节省，仍须核对计时证据与质量'
    return result, prefix + conclusion


def closeout(case, values):
    """Record actual responses; null is unknown, zero explicitly means none."""
    root, state = load(case)
    allowed = {'claim_focus', 'net_savings_requested', 'collect_timing', 'check_time_complete', 'baseline_basis', 'unlogged_human_minutes', 'unlogged_human_kind', 'production_status', 'quality_status', 'deferred_fields', 'source'}
    if set(values) - allowed:
        raise ValueError('Unexpected closeout field')
    if values.get('claim_focus', 'unspecified') not in ('speed', 'quality', 'volume', 'cost', 'unspecified'):
        raise ValueError('Invalid claim_focus')
    if 'net_savings_requested' in values and type(values['net_savings_requested']) is not bool:
        raise ValueError('net_savings_requested must be true or false')
    for flag in ('collect_timing', 'check_time_complete'):
        if flag in values and type(values[flag]) is not bool:
            raise ValueError(flag + ' must be true or false')
    extra = values.get('unlogged_human_minutes')
    if extra is not None and (isinstance(extra, bool) or not isinstance(extra, (int, float)) or not math.isfinite(extra) or extra < 0):
        raise ValueError('Invalid unlogged_human_minutes')
    if values.get('unlogged_human_kind', 'unknown') not in ('measured', 'estimate', 'unknown'):
        raise ValueError('Invalid unlogged_human_kind')
    if values.get('production_status', 'unknown') not in ('unknown', 'in_progress', 'completed'):
        raise ValueError('Invalid production_status')
    if values.get('quality_status', 'unknown') not in ('unknown', 'needs_revision', 'usable'):
        raise ValueError('Invalid quality_status')
    if 'deferred_fields' in values and (not isinstance(values['deferred_fields'],list) or any(not isinstance(k,str) or k not in MANUAL_TIME_FACTS for k in values['deferred_fields'])):
        raise ValueError('deferred_fields must name actual unknown manual time facts')
    for key in ('baseline_basis', 'source'):
        if key in values and not isinstance(values[key], str):
            raise ValueError(key + ' must be text')
    if set(values) - {'source'} and not values.get('source', '').strip():
        raise ValueError('Closeout facts and conclusions need an actual source')
    state.setdefault('closeout', {}).update(values)
    answers=state['closeout']
    deferred=set(answers.get('deferred_fields',[]))
    for key in ('baseline_basis','unlogged_human_minutes','unlogged_human_kind'):
        if key in values and ((key=='baseline_basis' and values[key].strip()) or (key=='unlogged_human_minutes' and values[key] is not None) or (key=='unlogged_human_kind' and values[key]!='unknown')):
            deferred.discard(key)
    if 'deferred_fields' in answers:answers['deferred_fields']=sorted(deferred)
    if values.get('check_time_complete') is True:
        answers['deferred_fields'] = [k for k in answers.get('deferred_fields', []) if k != 'check_minutes']
    sources = state.setdefault('closeout_sources', {})
    for key in values:
        if key != 'source': sources[key] = values['source'].strip()
    save(root, state, 'closeout')
    return submission_status(state)


def time_comparison_requested(state):
    answers = state.get('closeout', {})
    return answers.get('net_savings_requested') is True or answers.get('claim_focus') == 'speed'


def check_time_missing(state):
    if state.get('timing', {}).get('check_minutes') is None:
        return True
    answer = state.get('closeout', {}).get('check_time_complete')
    if answer is not None:
        return answer is False
    review = state.get('timing_coverage')
    components = review.get('components') if isinstance(review, dict) else None
    check = components.get('check', {}) if isinstance(components, dict) else {}
    if not isinstance(check, dict):
        return False  # A malformed coverage record is an AI follow-up, not a guessed human fact.
    return check.get('status') == 'partial'


def missing_manual_time_facts(state):
    values=state['timing'];answers=state.get('closeout',{});missing=[]
    if values.get('baseline_minutes') is None:missing.append('baseline_minutes')
    if values.get('measurement_kind','unknown')=='unknown':missing.append('measurement_kind')
    if not answers.get('baseline_basis','').strip():missing.append('baseline_basis')
    if values.get('same_scope') is None:missing.append('same_scope')
    if check_time_missing(state):missing.append('check_minutes')
    extra=answers.get('unlogged_human_minutes')
    if extra is None:missing.append('unlogged_human_minutes')
    elif extra>0 and answers.get('unlogged_human_kind','unknown')=='unknown':missing.append('unlogged_human_kind')
    return missing


def submission_calculation(state):
    if not time_comparison_requested(state):
        return None, '本次未主张时间改善'
    if state['timing'].get('same_scope') is False:
        return None, '已知人工基线与实际工作范围不同，无法核算净节省'
    missing = missing_manual_time_facts(state)
    if missing:
        labels = '、'.join(MANUAL_TIME_FACTS[key] for key in missing)
        return None, '现有记录无法核实净节省，缺少可用依据：' + labels
    if not timing_coverage.assess(state)['complete']:
        return None, '有部分计时，但全流程覆盖未核实或不完整，暂不能证明完整净节省'
    net, conclusion = calculate(state['timing'])
    if net is None: return net, conclusion
    answers = state.get('closeout', {})
    extra = answers['unlogged_human_minutes']
    net = round(net - extra, 6)
    estimated = state['timing'].get('measurement_kind') == 'estimate' or (extra > 0 and answers.get('unlogged_human_kind') == 'estimate')
    prefix = '估算：' if estimated else '按所填记录计算：'
    return net, prefix + ('未提效' if net <= 0 else '有净节省，仍须核对计时证据与质量')


def submission_binding(state):
    """Bind the author's confirmation to substantive facts, not read/log timestamps."""
    timing = {k: state['timing'].get(k) for k in (*NUMBERS, 'same_scope', 'measurement_kind', 'basis', 'rework_count_kind', 'rework_count_basis')}
    answers = {k: v for k, v in state.get('closeout', {}).items() if k != 'source'}
    material = dict(title=state['title'], card=state['card'], timing=timing, closeout=answers,
                    artifacts=[{k: a[k] for k in ('id', 'role', 'kind', 'note', 'sha256')} for a in state['artifacts'] if a['role'] != 'other'])
    if time_comparison_requested(state) and state.get('timing_coverage') is not None:
        material['timing_coverage'] = state['timing_coverage']
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def submission_status(state):
    missing = [LABELS[FIELDS.index(k)] for k in FIELDS[:5] if k not in state['card']]
    compares_time = time_comparison_requested(state)
    net, conclusion = submission_calculation(state)
    coverage = timing_coverage.assess(state) if compares_time else None
    pending_timing = list(coverage['issues']) if coverage else []
    if compares_time and state['timing'].get('sample_count') is None:
        pending_timing.append('样本范围尚缺记录')
    limits = []
    if compares_time and net is None:
        limits.append(conclusion)
    if compares_time and state['timing'].get('measurement_kind') == 'estimate':
        limits.append('人工基线为本人估算')
    ready = not missing
    confirmation = state.get('submission_confirmation', {})
    confirmed = bool(ready and confirmation.get('binding') == submission_binding(state) and confirmation.get('evidence', '').strip())
    status = '可提交' if confirmed else ('待本人核对' if ready else '案例待补信息')
    production = state.get('closeout', {}).get('production_status', 'unknown')
    quality = state.get('closeout', {}).get('quality_status', 'unknown')
    if confirmed:
        next_action = '按已授权范围提交'
    elif ready:
        next_action = '请本人核对当前案例内容、证据和已注明的结论限制'
    else:
        next_action = '核对尚缺的案例事实'
    return dict(status=status, submission_status=status,
                production_status={'unknown':'产物状态未确认','in_progress':'产物进行中','completed':'产物完成'}[production],
                quality_status={'unknown':'效果结论未确认','needs_revision':'需要修改','usable':'本人确认当前版可用'}[quality],
                ready_for_author_review=ready, time_comparison_requested=compares_time,
                known_timing=dict(state['timing'], unlogged_human_minutes=state.get('closeout',{}).get('unlogged_human_minutes')),
                ready_to_submit=confirmed,
                author_confirmation='current' if confirmed else ('stale' if confirmation else 'pending'),
                missing_card_facts=missing, net_minutes=net, conclusion=conclusion,
                missing_timing_records=pending_timing, timing_coverage=coverage, evidence_limits=limits,
                next_action=next_action,
                note='可提交表示本人已核对当前案例稿；证据限制仍有效，业务验收另有来源。')


def coverage_review(case, values, out=None):
    root, state = load(case)
    review = timing_coverage.make_review(state, values)
    if out:
        target = Path(out).resolve()
        if target == root or target.is_relative_to(root):
            raise ValueError('Read-only coverage review must be saved outside the source case')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as f:
            json.dump(review, f, ensure_ascii=False, indent=2)
    else:
        state['timing_coverage'] = review
        save(root, state, 'timing-coverage-review')
    state['timing_coverage'] = review
    return dict(review=review, assessment=timing_coverage.assess(state))


def confirm_submission(case, evidence):
    if not evidence.strip(): raise ValueError('An actual author confirmation of the case contents is required')
    import timing_commands
    timing_commands.sync(timing_api(), case)
    root, state = load(case)
    verified_files(root, state)
    status = submission_status(state)
    if not status['ready_for_author_review']:
        raise ValueError('The five case facts must be recorded before author confirmation')
    state['submission_confirmation'] = dict(binding=submission_binding(state), evidence=evidence.strip(), recorded_at=now())
    save(root, state, 'confirm-submission')
    return submission_status(state)


def add(case, role, path, kind, note):
    root, state = load(case)
    check_kind(state, kind)
    source = Path(path).resolve(strict=True)
    if not source.is_file() or not note.strip():
        raise ValueError('A file and an explanation are required')
    digest = sha(source)
    index = len(state['artifacts']) + 1
    dest = root / 'evidence' / f'{index:03d}-{role}{source.suffix.lower()}'
    if dest.exists():
        raise FileExistsError(dest)
    shutil.copyfile(source, dest)
    if sha(dest) != digest:
        raise RuntimeError('Copy integrity mismatch')
    state['artifacts'].append(dict(id=f'E{index:03d}', role=role, kind=kind, note=note, source=str(source), copy=dest.relative_to(root).as_posix(), bytes=dest.stat().st_size, sha256=digest, collected_at=now(), semantic_acceptance='not_inferred'))
    save(root, state, 'add:' + role)


def verified_files(root, state):
    files = []
    for record in state['artifacts']:
        p = (root / record['copy']).resolve()
        if not p.is_relative_to(root / 'evidence') or not p.is_file() or sha(p) != record['sha256']:
            raise ValueError('Evidence missing, changed, or outside evidence directory: ' + record['id'])
        files.append((record, p))
    return files


def render_audit(case, out):
    import timing_commands
    timing_commands.sync(timing_api(), case)
    root, state = load(case)
    files = verified_files(root, state)
    validate_timing(state, state['timing'])
    target = Path(out).resolve()
    if target == root or target.is_relative_to(root) or root.is_relative_to(target):
        raise ValueError('Export must be separate from the case directory')
    target.mkdir(parents=True, exist_ok=False)
    (target / 'evidence').mkdir()
    for record, source in files:
        shutil.copyfile(source, target / record['copy'])
        if sha(target / record['copy']) != record['sha256']:
            raise RuntimeError('Export integrity mismatch')
    banner = '【本地审计档案；提交状态见case.json，不自动代表业务验收】'
    lines = []
    for field, label in zip(FIELDS[:5], LABELS[:5]):
        item = state['card'].get(field)
        text = '待补' if not item else ' '.join(item['text'].splitlines()).rstrip('。')
        lines.append(label + '：' + text + '。')
    (target / '01-案例卡.txt').write_text(banner + '\n' + '\n'.join(lines), encoding='utf-8-sig')
    values = state['timing']
    net, conclusion = submission_calculation(state)
    with (target / '02-耗时基线.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['记录性质', '人工基线分钟', 'AI运行分钟', '人工检查分钟', '返工总分钟', '登记次数原值', '样本数', '次数口径', '次数依据', '内部技术返工步骤数', '同口径', '数据类型', '人工基线依据', '自动计时范围', '未计入前三项的额外人工分钟', '净节省分钟', '结论'])
        writer.writerow([banner] + [values.get(k) for k in NUMBERS] + [values.get('rework_count_kind', 'unknown'), values.get('rework_count_basis'), state.get('timing_journal', {}).get('technical_rework_step_count'), values.get('same_scope'), values.get('measurement_kind'), state.get('closeout', {}).get('baseline_basis') or values.get('basis'), state.get('timing_journal', {}).get('accounting_basis'), state.get('closeout', {}).get('unlogged_human_minutes'), net, conclusion])
    write(target / '03-证据清单.json', dict(mode=state['mode'], disclaimer=banner, semantic_verification='文件复制和哈希一致不代表人工或业务验收', artifacts=state['artifacts']))
    status = submission_status(state)
    pending = [banner]
    if status['missing_card_facts']:
        pending.append('缺失案例事实：' + '、'.join(status['missing_card_facts']))
    pending.extend(status['evidence_limits'])
    pending.extend(status['missing_timing_records'])
    (target / '04-待确认.txt').write_text('\n'.join(pending), encoding='utf-8-sig')
    reuse = state['card'].get('reuse', {}).get('text', '尚无可核验的复用记录，不推断第二批或多周期已完成')
    (target / '05-复用记录.txt').write_text(banner + '\n' + reuse, encoding='utf-8-sig')
    shutil.copyfile(root / 'case.json', target / 'case.json')
    shutil.copyfile(root / 'events.jsonl', target / 'events.jsonl')
    if state.get('timing_journal'):
        import run_journal
        timing_journal=run_journal.Journal(state['timing_journal']['root'],state['mode'])
        write(target/'06-自动计时汇总.json',run_journal.summary(timing_journal))
        shutil.copytree(timing_journal.root,target/'timing',ignore=shutil.ignore_patterns('*.lock','*.pending'))
    return dict(out=str(target), profile='audit', mode=state['mode'], net_minutes=net, conclusion=conclusion, artifacts=len(files))


def render_submission(case, out, evidence_ids=()):
    """One compact authoring draft, never a duplicate full audit directory."""
    import timing_commands
    timing_commands.sync(timing_api(), case)
    root, state = load(case)
    files = verified_files(root, state)
    validate_timing(state, state['timing'])
    selected = set(evidence_ids)
    by_id = {a['id']: (a, path) for a, path in files}
    if selected - set(by_id): raise ValueError('Unknown evidence IDs: ' + ', '.join(sorted(selected-set(by_id))))
    target = Path(out).resolve()
    if target == root or target.is_relative_to(root) or root.is_relative_to(target):
        raise ValueError('Export must be separate from the case directory')
    target.mkdir(parents=True, exist_ok=False)
    status = submission_status(state)
    lines = [state['title'], '产物状态：' + status['production_status'], '提交状态：' + status['status'], '效果状态：' + status['quality_status'], '', '案例五项事实']
    for field, label in zip(FIELDS[:5], LABELS[:5]):
        item = state['card'].get(field)
        content = '待补' if not item else ' '.join(item['text'].splitlines()).rstrip('。')
        lines.append(label + '：' + content + '。')
    values=state['timing']; answers=state.get('closeout', {})
    label={'speed':'快','quality':'好','volume':'多','cost':'省'}.get(answers.get('claim_focus'),'待确认')
    lines.extend(['', '价值与证据', '主张方向：' + label + '；多快好省只取证据最强的一项，不叠加。'])
    if status['time_comparison_requested']:
        for key, title in [('baseline_minutes','人工基线'),('ai_minutes','AI运行（不含单列返工）'),('check_minutes','人工检查'),('rework_minutes','返工总用时')]:
            value = values.get(key)
            if value is not None:
                lines.append(title + '：' + str(value) + '分钟')
        extra = answers.get('unlogged_human_minutes')
        if extra is not None:
            lines.append('未计入以上项目的额外人工：' + str(extra) + '分钟')
        if values.get('measurement_kind') in ('measured', 'estimate'):
            lines.append('人工基线性质：' + {'measured':'实测','estimate':'估算'}[values['measurement_kind']])
        if answers.get('baseline_basis'):
            lines.append('人工基线依据：' + answers['baseline_basis'])
        if status['net_minutes'] is not None:
            lines.extend(['净节省：' + str(status['net_minutes']) + '分钟', '结论：' + status['conclusion']])
    else:
        lines.append('按所选价值呈现实际前后对照。')
    count_kind=values.get('rework_count_kind', 'unknown')
    if values.get('rework_count') is not None and count_kind!='unknown' and values.get('rework_count_basis', '').strip():
        lines.append({'human_return':'本人退回次数','revision_round':'实际修订轮次'}[count_kind]+'：'+str(values['rework_count'])+'；依据：'+values['rework_count_basis'])
    lines.extend(['', '关键证据'])
    if selected:
        for identifier in sorted(selected):
            record, path = by_id[identifier]
            lines.append(identifier+'：'+record['note'])
            lines.append('供文档作者读取并内嵌的本地材料：'+str(path))
    else:
        lines.append('待按主张选择最少且可读的原始证据；不要自动选择全部文件。图片案例优先把同一样本的原图、问题和修后结果合为一张对照，并在文档内嵌。')
    lines.extend(['', '复用记录', state['card'].get('reuse',{}).get('text','未提供，不主张持续复用。')])
    if status['missing_card_facts']:
        lines.append('缺失案例事实：' + '、'.join(status['missing_card_facts']))
    limits = status['evidence_limits'] + status['missing_timing_records']
    if limits:
        lines.extend(['', '证据限制', *limits])
    lines.extend(['', '编制说明：本稿用于制作单份提交文档；本地源路径、日志和哈希留在work审计档案。飞书提交时将关键图证直接内嵌到一份DOCX，不把本地路径当作线上可访问证据，不自动上传或发布。'])
    file=target/'案例提交内容草稿.txt'
    file.write_text('\n'.join(lines),encoding='utf-8-sig')
    return dict(out=str(file), profile='submission', artifacts_copied=0, selected_evidence_ids=sorted(selected), **status)


def render(case, out, profile='submission', evidence_ids=()):
    if profile == 'audit': return render_audit(case, out)
    if profile == 'submission': return render_submission(case, out, evidence_ids)
    raise ValueError('Invalid render profile')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('init'); p.add_argument('--out', required=True); p.add_argument('--mode', choices=('real',), default='real'); p.add_argument('--title', required=True)
    p = sub.add_parser('set'); p.add_argument('--case', required=True); p.add_argument('--field', choices=FIELDS, required=True); p.add_argument('--text', required=True); p.add_argument('--kind', choices=('observed', 'user_report'), required=True); p.add_argument('--source', required=True)
    p = sub.add_parser('timing'); p.add_argument('--case', required=True); p.add_argument('--file', required=True)
    p = sub.add_parser('coverage'); p.add_argument('--case', required=True); p.add_argument('--file', required=True); p.add_argument('--out')
    p = sub.add_parser('add'); p.add_argument('--case', required=True); p.add_argument('--role', choices=ROLES, required=True); p.add_argument('--path', required=True); p.add_argument('--kind', choices=('observed', 'user_report'), required=True); p.add_argument('--note', required=True)
    p = sub.add_parser('closeout'); p.add_argument('--case', required=True); p.add_argument('--file', required=True)
    p = sub.add_parser('submission-status'); p.add_argument('--case', required=True)
    p = sub.add_parser('confirm-submission'); p.add_argument('--case', required=True); p.add_argument('--evidence', required=True)
    p = sub.add_parser('review-report'); p.add_argument('--case', required=True); p.add_argument('--seconds', type=float, required=True); p.add_argument('--review-id', required=True); p.add_argument('--evidence', required=True); p.add_argument('--timer-session-id'); p.add_argument('--independent-of-timer', action='store_true'); p.add_argument('--all-checks-accounted', action='store_true')
    p = sub.add_parser('render'); p.add_argument('--case', required=True); p.add_argument('--out', required=True); p.add_argument('--profile',choices=('submission','audit'),default='submission'); p.add_argument('--evidence-id',action='append',default=[])
    for command in ('review-start','review-pause','review-resume','review-finish','review-cancel','review-status','workflow-start','workflow-finish','timer-sync','timer-status'):
        p=sub.add_parser(command);p.add_argument('--case',required=True);p.add_argument('--evidence',default='')
    a = ap.parse_args()
    if a.command == 'init': result = dict(case=str(init(a.out, a.mode, a.title)))
    elif a.command == 'set': result = set_field(a.case, a.field, a.text, a.kind, a.source)
    elif a.command == 'timing': result = timing(a.case, read(a.file))
    elif a.command == 'coverage': result = coverage_review(a.case, read(a.file), a.out)
    elif a.command == 'add': result = add(a.case, a.role, a.path, a.kind, a.note)
    elif a.command=='closeout': result = closeout(a.case, read(a.file))
    elif a.command=='submission-status':
        import timing_commands
        timing_commands.sync(timing_api(), a.case)
        _,state=load(a.case);result=submission_status(state)
    elif a.command=='confirm-submission': result = confirm_submission(a.case, a.evidence)
    elif a.command=='review-report':
        import timing_commands
        result = timing_commands.report_review(timing_api(), a.case, a.seconds, a.review_id, a.evidence,
                                              a.timer_session_id, a.independent_of_timer, a.all_checks_accounted)
    elif a.command=='render': result = render(a.case, a.out, a.profile, a.evidence_id)
    else:
        import timing_commands,run_journal
        result=timing_commands.run_control(timing_api(),a.case,a.command,a.evidence,run_journal._ACTIVE.get())
    print(json.dumps(result or {'saved': True}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        # Historical review must not create events in the original business journal.
        if len(sys.argv) > 1 and sys.argv[1] == 'coverage' and '--out' in sys.argv:
            main()
        else:
            import timing_commands
            args,j=timing_commands.setup(sys.argv[1:]);sys.argv=[sys.argv[0],*args]
            with j.activate(),j.step('evidence:'+(args[0] if args else 'help'),kind='recording'):
                main()
    except (ValueError, OSError, KeyError, RuntimeError) as error:
        raise SystemExit('ERROR: ' + str(error))
