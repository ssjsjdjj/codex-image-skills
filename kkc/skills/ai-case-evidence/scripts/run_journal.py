"""Durable per-event timing; no daemon, fabricated durations or remote service."""
import argparse
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from datetime import datetime, timezone
import functools
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

_ACTIVE = ContextVar('active_journal', default=None)
_PARENT = ContextVar('parent_step', default=None)


def atomic_json(path, value, exclusive=False):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8')
    if exclusive:
        with path.open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    else:
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.pending')
        with temporary.open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)


def event_time():
    return dict(at=datetime.now(timezone.utc).isoformat(), wall_ns=time.time_ns(), monotonic_ns=time.monotonic_ns())


class Journal:
    def __init__(self, root, mode='real'):
        if mode != 'real': raise ValueError('Only real task journals are supported')
        self.root = Path(root).resolve(); self.events_dir = self.root / 'events'
        self.events_dir.mkdir(parents=True, exist_ok=True)
        meta = self.root / 'journal.json'
        if not meta.exists():
            try: atomic_json(meta, dict(schema=1, mode=mode, created_at=event_time()['at']), True)
            except FileExistsError: pass
        self.mode = json.loads(meta.read_text(encoding='utf-8'))['mode']
        if self.mode != mode: raise ValueError('Journal mode differs from the current real task')

    def event(self, event, **fields):
        value = dict(schema=1, event=event, mode=self.mode, pid=os.getpid(), **event_time(), **fields)
        atomic_json(self.events_dir / (str(value['wall_ns']) + '-' + uuid.uuid4().hex + '.json'), value, True)
        return value

    @contextmanager
    def activate(self):
        token = _ACTIVE.set(self)
        try: yield self
        finally: _ACTIVE.reset(token)

    @contextmanager
    def step(self, label, kind='ai', category='ai', metadata=None):
        step_id = uuid.uuid4().hex
        start = self.event('started', step_id=step_id, parent_id=_PARENT.get() or os.environ.get('AI_TIMING_PARENT_ID'), label=label, kind=kind, category=category, metadata=metadata or {})
        token = _PARENT.set(step_id)
        try:
            yield step_id
        except BaseException as error:
            if isinstance(error,SystemExit) and error.code in (None,0):
                self.event('ended',step_id=step_id,seconds=(time.monotonic_ns()-start['monotonic_ns'])/1e9)
            else:
                self.event('errored', step_id=step_id, seconds=(time.monotonic_ns()-start['monotonic_ns'])/1e9,
                           error_type=type(error).__name__, error=str(error)[:2000])
            raise
        else:
            self.event('ended', step_id=step_id, seconds=(time.monotonic_ns()-start['monotonic_ns'])/1e9)
        finally: _PARENT.reset(token)

    def records(self):
        result=[]; corrupt=[]
        for path in self.events_dir.glob('*.json'):
            try:
                value=json.loads(path.read_text(encoding='utf-8'))
                if value.get('mode')!=self.mode: raise ValueError('mode mismatch')
                if not isinstance(value.get('wall_ns'),int) or not isinstance(value.get('event'),str): raise ValueError('invalid event schema')
                result.append(value)
            except (ValueError,OSError) as error: corrupt.append(dict(file=path.name,error=str(error)))
        return sorted(result,key=lambda x:x['wall_ns']),corrupt


@contextmanager
def step(label, kind='ai', category='ai', metadata=None):
    journal=_ACTIVE.get()
    with (journal.step(label,kind,category,metadata) if journal else nullcontext()) as value: yield value


def instrument(module, name, label):
    original=getattr(module,name)
    @functools.wraps(original)
    def wrapped(*args,**kwargs):
        with step(label): return original(*args,**kwargs)
    setattr(module,name,wrapped)


@contextmanager
def human_lock(journal):
    path=journal.root/'human.lock'
    with path.open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        try: yield
        finally:
            stream.seek(0)
            if os.name=='nt': msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(stream.fileno(),fcntl.LOCK_UN)


def human_sessions(records):
    sessions={}
    for event in records:
        if not event['event'].startswith('human_'): continue
        sid=event['session_id'];kind=event['event']
        if kind=='human_started': sessions[sid]=dict(id=sid,status='running',segments=[],start=event)
        elif sid in sessions:
            session=sessions[sid]
            if kind=='human_resumed': session.update(status='running',start=event)
            elif kind in ('human_paused','human_finished'):
                if 'segment_seconds' in event: session['segments'].append(event['segment_seconds'])
                session['status']='paused' if kind=='human_paused' else 'finished'
                session['finish_event']=event
            elif kind=='human_cancelled': session['status']='cancelled'
    return list(sessions.values())


def human(journal, action, evidence):
    if action!='status' and not evidence.strip(): raise ValueError('Human timer requires an actual instruction or evidence')
    with human_lock(journal):
        records,bad=journal.records()
        if bad: raise RuntimeError('Journal has unreadable events; preserve and inspect them')
        sessions=human_sessions(records);active=[s for s in sessions if s['status'] in ('running','paused')]
        if action=='status': return dict(sessions=sessions)
        if action=='start':
            if active: raise RuntimeError('Human review already running or paused')
            sid=uuid.uuid4().hex;journal.event('human_started',session_id=sid,evidence=evidence)
            return dict(session_id=sid,status='running')
        if len(active)!=1: raise RuntimeError('No active human review; cannot infer a start time')
        session=active[0];fields=dict(session_id=session['id'],evidence=evidence)
        if action=='resume':
            if session['status']!='paused': raise RuntimeError('Review is not paused')
            journal.event('human_resumed',**fields);status='running'
        elif action in ('pause','finish'):
            if action=='pause' and session['status']!='running': raise RuntimeError('Review is already paused')
            if session['status']=='running':
                mono=(time.monotonic_ns()-session['start']['monotonic_ns'])/1e9
                wall=(time.time_ns()-session['start']['wall_ns'])/1e9
                if mono<0 or abs(mono-wall)>3: raise RuntimeError('Clock changed or computer restarted; duration needs manual verification')
                fields['segment_seconds']=mono
            journal.event('human_paused' if action=='pause' else 'human_finished',**fields)
            status='paused' if action=='pause' else 'finished'
        elif action=='cancel': journal.event('human_cancelled',**fields);status='cancelled'
        else: raise ValueError('Unknown human timer action')
        return dict(session_id=session['id'],status=status)


def union_ns(intervals):
    merged=[]
    for start,end in sorted(intervals):
        if merged and start<=merged[-1][1]: merged[-1][1]=max(merged[-1][1],end)
        else: merged.append([start,end])
    return sum(end-start for start,end in merged)/1e9


def summary(journal):
    records,bad=journal.records();starts={};ends={};problems=[]
    for event in records:
        if event['event']=='started': starts[event['step_id']]=event
        elif event['event'] in ('ended','errored'): ends[event['step_id']]=event
    business={key:value for key,value in starts.items() if value['kind']=='ai'}
    top={key:value for key,value in business.items() if value.get('parent_id') not in business}
    ai=[];rework=[];details=[]
    for key,start in business.items():
        end=ends.get(key)
        details.append(dict(id=key,label=start['label'],parent_id=start.get('parent_id'),category=start['category'],
                            status=end['event'] if end else 'incomplete',seconds=end.get('seconds') if end else None))
        if not end: problems.append('未结束的步骤：'+start['label']);continue
        wall=(end['wall_ns']-start['wall_ns'])/1e9
        if abs(wall-end['seconds'])>3 or wall<0: problems.append('计时钟不一致：'+start['label']);continue
        if key in top:
            (rework if start['category']=='rework' else ai).append((start['wall_ns'],end['wall_ns']))
    sessions=human_sessions(records)
    unfinished=[s for s in sessions if s['status']!='finished']
    closed_events=[e for e in records if e['event']=='workflow_finished']
    started_events=[e for e in records if e['event']=='workflow_started']
    closed=bool(started_events and closed_events and closed_events[-1]['wall_ns']>=started_events[-1]['wall_ns'] and
                closed_events[-1]['wall_ns']>=max((ends[k]['wall_ns'] for k in business if k in ends),default=0))
    complete=bool(top and closed and not problems and not bad)
    ai_seconds=union_ns(ai);all_seconds=union_ns(ai+rework)
    human_complete=bool(sessions and not unfinished and not bad)
    human_seconds=sum(sum(s['segments']) for s in sessions if s['status']=='finished')
    return dict(schema=1,mode=journal.mode,root=str(journal.root),workflow_closed=closed,
                ai_complete=complete,ai_seconds=ai_seconds if complete else None,
                ai_recorded_seconds=ai_seconds,rework_seconds=round(all_seconds-ai_seconds,9) if complete else None,
                rework_count=sum(s['category']=='rework' for s in top.values()) if complete else None,
                human_complete=human_complete,human_seconds=human_seconds if human_complete else None,
                human_recorded_seconds=human_seconds,human_sessions=sessions,steps=details,
                errors=[dict(label=starts[k]['label'],error_type=e.get('error_type'),error=e.get('error'),seconds=e.get('seconds')) for k,e in ends.items() if e['event']=='errored' and k in starts],
                incomplete=problems,corrupt_events=bad,
                accounting='AI uses the union of top-level recorded execution windows; nested steps are not added. Rework overlaps already included in AI are not subtracted twice. Human time is explicitly started/stopped active review, excluding pauses; model-internal uninstrumented work is not inferred.')


def lifecycle(journal,action,evidence):
    if not evidence.strip(): raise ValueError('A workflow boundary needs a scope or actual completion note')
    if action=='start': journal.event('workflow_started',scope=evidence)
    elif action=='finish':
        report=summary(journal)
        if report['incomplete'] or report['corrupt_events']: raise RuntimeError('Incomplete steps cannot be marked fully timed')
        if any(s['status'] in ('running','paused') for s in report['human_sessions']): raise RuntimeError('Finish or cancel human review first')
        journal.event('workflow_finished',evidence=evidence)
    return summary(journal)


def peel_options(argv, default_root):
    argv=list(argv);root=os.environ.get('AI_TIMING_ROOT');mode=os.environ.get('AI_TIMING_MODE','real')
    for flag in ('--journal-root','--timing-mode'):
        if argv.count(flag)>1: raise ValueError('Duplicate timing option')
        if flag in argv:
            index=argv.index(flag)
            if index+1>=len(argv): raise ValueError('Missing timing option value')
            if flag=='--journal-root': root=argv[index+1]
            else: mode=argv[index+1]
            del argv[index:index+2]
    if mode != 'real': raise ValueError('Only real task timing is supported')
    return argv,Path(root or default_root).resolve(),mode


def flag_path(argv, flags, fallback):
    for flag in flags:
        if flag in argv and argv.index(flag)+1<len(argv): return Path(argv[argv.index(flag)+1]).resolve()
    return Path(fallback).resolve()


def control(journal, command, argv):
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',default='');a=parser.parse_args(argv)
    if command.startswith('check-'): return human(journal,command[6:],a.evidence)
    if command.startswith('workflow-'): return lifecycle(journal,command[9:],a.evidence)
    return summary(journal)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--journal-root',required=True);ap.add_argument('--mode',choices=('real',),default='real')
    ap.add_argument('command',choices=('check-start','check-pause','check-resume','check-finish','check-cancel','check-status','workflow-start','workflow-finish','summary','mark-start','mark-finish','mark-error','run'))
    ap.add_argument('--evidence',default='');ap.add_argument('--label',default='AI external step');ap.add_argument('--id');ap.add_argument('--category',choices=('ai','rework'),default='ai')
    raw=sys.argv[1:];extra=[]
    if '--' in raw: index=raw.index('--');extra=raw[index+1:];raw=raw[:index]
    a=ap.parse_args(raw);j=Journal(a.journal_root,a.mode)
    if a.command=='mark-start':
        sid=uuid.uuid4().hex;j.event('started',step_id=sid,parent_id=None,label=a.label,kind='ai',category=a.category,metadata=dict(evidence=a.evidence));result=dict(id=sid)
    elif a.command in ('mark-finish','mark-error'):
        records,_=j.records();start=next((e for e in records if e.get('step_id')==a.id and e['event']=='started'),None)
        if not start or any(e.get('step_id')==a.id and e['event'] in ('ended','errored') for e in records): raise ValueError('Missing or already closed external step')
        if not a.evidence.strip(): raise ValueError('External completion needs actual evidence')
        seconds=(time.monotonic_ns()-start['monotonic_ns'])/1e9
        if seconds<0 or abs((time.time_ns()-start['wall_ns'])/1e9-seconds)>3: raise RuntimeError('Clock changed; do not guess duration')
        j.event('ended' if a.command=='mark-finish' else 'errored',step_id=a.id,seconds=seconds,evidence=a.evidence,error_type='ExternalStepError' if a.command=='mark-error' else None)
        result=summary(j)
    elif a.command=='run':
        args=extra
        if not args: raise ValueError('Missing executable')
        with j.activate(),j.step(a.label,category=a.category) as sid:
            child_env=dict(os.environ,AI_TIMING_ROOT=str(j.root),AI_TIMING_MODE=j.mode,AI_TIMING_PARENT_ID=sid,AI_TIMING_CATEGORY=a.category)
            code=subprocess.call(args,env=child_env)
            if code: raise subprocess.CalledProcessError(code,Path(args[0]).name)
        result=summary(j)
    else:
        argv=['--evidence',a.evidence] if a.evidence else []
        result=control(j,a.command,argv)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
