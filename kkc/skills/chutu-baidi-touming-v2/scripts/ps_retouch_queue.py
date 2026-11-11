"""Persistent PS task queue; the Codex skill performs the actual PS/visual work."""
import argparse
from contextlib import contextmanager
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import unicodedata
import uuid

COMMANDS={'queue','queue-list','queue-start','queue-check','queue-next','queue-complete','queue-fail','queue-pause'}
IMAGE_SUFFIXES={'.jpg','.jpeg','.png','.tif','.tiff','.webp','.bmp','.psd','.psb'}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def is_start_phrase(text):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',str(text))).casefold()=='开始ps精修'


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def input_snapshot():
    """Session input marker, not a physical-human detector; handles DWORD wrap."""
    if platform.system()!='Windows':
        return dict(available=False,reason='Windows input monitor unavailable')
    import ctypes
    class LastInput(ctypes.Structure):
        _fields_=[('cbSize',ctypes.c_uint32),('dwTime',ctypes.c_uint32)]
    value=LastInput();value.cbSize=ctypes.sizeof(value)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(value)):
        return dict(available=False,reason='GetLastInputInfo failed')
    tick=ctypes.windll.kernel32.GetTickCount
    tick.restype=ctypes.c_uint32
    elapsed=(int(tick())-int(value.dwTime))&0xffffffff
    return dict(available=True,input_tick=int(value.dwTime),idle_seconds=elapsed/1000.)


def default_file(skill_root):
    config=json.loads((Path(skill_root)/'runtime.json').read_text(encoding='utf-8-sig'))
    return Path(config['cache_dir']).resolve()/'ps-retouch-queue.json'


def absolute_file(value,label):
    path=Path(str(value))
    if not path.is_absolute() or not path.is_file():raise ValueError(label+'须为存在的绝对文件路径')
    return path.resolve()


class Queue:
    def __init__(self,path,snapshot=None):
        self.path=Path(path).resolve()
        self.snapshot=snapshot or input_snapshot

    def read(self):
        if not self.path.exists():return dict(schema_version=1,items=[],run=dict(status='idle'))
        try:data=json.loads(self.path.read_text(encoding='utf-8-sig'))
        except (json.JSONDecodeError,UnicodeError) as error:
            raise ValueError('队列不是有效JSON；保留原文件，不自动覆盖或迁移旧JSONL') from error
        if data.get('schema_version')!=1 or not isinstance(data.get('items'),list) or not isinstance(data.get('run'),dict):
            raise ValueError('不支持的PS队列结构，未修改原文件')
        return data

    @contextmanager
    def edit(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        lock=self.path.with_name(self.path.name+'.lock')
        try:stream=lock.open('x',encoding='utf-8')
        except FileExistsError as error:raise RuntimeError('队列正被占用；先核对现有运行，不启动重复任务') from error
        try:
            with stream:
                json.dump(dict(pid=os.getpid(),created_at=now()),stream);stream.flush();os.fsync(stream.fileno())
            data=self.read()
            yield data
            temporary=self.path.with_name(self.path.name+'.tmp-'+uuid.uuid4().hex)
            with temporary.open('x',encoding='utf-8') as output:
                json.dump(data,output,ensure_ascii=False,indent=2);output.flush();os.fsync(output.fileno())
            os.replace(temporary,self.path)
        finally:
            lock.unlink()

    def enqueue(self,task):
        title=str(task.get('title','')).strip();scope=str(task.get('scope','')).strip()
        evidence=str(task.get('enqueue_evidence','')).strip()
        root=Path(str(task.get('task_root','')))
        if not title or not scope or not evidence or not root.is_absolute() or not root.is_dir():
            raise ValueError('入队须有title、scope、enqueue_evidence及现有绝对task_root')
        if not isinstance(task.get('items'),list) or not task['items']:
            raise ValueError('入队至少明确一张图片')
        items=[];snapshots={}
        for item in task['items']:
            path=absolute_file(item.get('input',''),'input')
            if path.suffix.lower() not in IMAGE_SUFFIXES:raise ValueError('队列input必须为图片或PSD，不能是执行脚本')
            row=dict(input=str(path),label=str(item.get('label',path.stem)),scope=str(item.get('scope',scope)))
            snapshots[str(path)]=sha(path)
            if item.get('reference'):
                reference=absolute_file(item['reference'],'reference')
                if reference.suffix.lower() not in IMAGE_SUFFIXES:raise ValueError('reference必须为原始参考图片')
                row['reference']=str(reference);snapshots[str(reference)]=sha(reference)
            items.append(row)
        identity=dict(title=title,task_root=str(root.resolve()),scope=scope,items=items,source_sha256=snapshots)
        fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        with self.edit() as data:
            duplicate=next((x for x in data['items'] if x.get('fingerprint')==fingerprint and x['status'] in ('pending','running','preview_ready')),None)
            if duplicate:return dict(status=duplicate['status'],already_queued=True,task=duplicate)
            task_id=uuid.uuid4().hex
            entry=dict(identity,id=task_id,fingerprint=fingerprint,status='pending',enqueue_evidence=evidence,
                created_at=now(),work_dir=str(root.resolve()/'PS精修队列'/task_id),progress={})
            data['items'].append(entry)
            return dict(status='pending',already_queued=False,task=entry,photoshop_started=False)

    def _inputs_current(self,task):
        return all(Path(path).is_file() and sha(path)==expected for path,expected in task['source_sha256'].items())

    def _monitor(self,data):
        marker=self.snapshot();run=data['run']
        if not marker.get('available'):
            run.update(status='paused',reason='input_monitor_unavailable',paused_at=now())
        elif marker['input_tick']!=run['input_tick']:
            run.update(status='paused',reason='new_input_event',paused_at=now())
        return dict(status=run['status'],reason=run.get('reason'),input=marker,session=run['id'])

    def _session(self,data,session):
        if not session or data['run'].get('id')!=session:raise RuntimeError('执行会话不匹配，不能操作另一个队列运行')

    def _claim(self,data):
        run=data['run']
        if run['status']!='running':return dict(status=run['status'],reason=run.get('reason'),session=run['id'])
        current=next((x for x in data['items'] if x['id']==run.get('current_task_id') and x['status']=='running'),None)
        if current:
            if not self._inputs_current(current):
                current.update(status='stale',error='queued input changed')
                run.update(status='paused',reason='source_changed',current_task_id=None)
                return dict(status='paused',reason='source_changed',task_id=current['id'],session=run['id'])
            return dict(status='running',task=current,session=run['id'],resume_required=True)
        task=next((x for x in data['items'] if x['status']=='pending'),None)
        if task is None:
            issues=any(x['status'] in ('failed','stale') for x in data['items'])
            run.update(status='finished_with_issues' if issues else 'completed',current_task_id=None,finished_at=now())
            return dict(status=run['status'],session=run['id'],preview_ready=[x['id'] for x in data['items'] if x['status']=='preview_ready'])
        if not self._inputs_current(task):
            task.update(status='stale',error='queued input changed')
            run.update(status='paused',reason='source_changed',current_task_id=None)
            return dict(status='paused',reason='source_changed',task_id=task['id'],session=run['id'])
        task.update(status='running',run_id=run['id'],started_at=now())
        run['current_task_id']=task['id']
        return dict(status='running',task=task,session=run['id'],resume_required=False)

    def start(self,evidence):
        if not is_start_phrase(evidence):raise ValueError('开始口令须来自用户本次明确输入“开始PS精修”')
        with self.edit() as data:
            if data['run'].get('status')=='running':
                return dict(status='already_running',session=data['run']['id'],current_task_id=data['run'].get('current_task_id'))
            if not any(x['status'] in ('pending','running') for x in data['items']):
                return dict(status='empty' if not data['items'] else 'no_pending_tasks',preview_ready=[x['id'] for x in data['items'] if x['status']=='preview_ready'])
            marker=self.snapshot()
            if not marker.get('available'):raise RuntimeError('无法监测新输入事件，保留队列，暂不启动PS')
            previous=next((x for x in data['items'] if x['status']=='running'),None)
            data['run']=dict(id=uuid.uuid4().hex,status='running',started_at=now(),authorization_evidence=evidence,
                input_tick=marker['input_tick'],start_idle_seconds=marker.get('idle_seconds'),
                current_task_id=previous['id'] if previous else None)
            if previous:previous['run_id']=data['run']['id']
            return self._claim(data)

    def check(self,session):
        with self.edit() as data:
            self._session(data,session)
            if data['run']['status']!='running':return dict(status=data['run']['status'],reason=data['run'].get('reason'),session=session)
            return self._monitor(data)

    def next(self,session):
        with self.edit() as data:
            self._session(data,session)
            if data['run']['status']=='running':self._monitor(data)
            return self._claim(data)

    def pause(self,session,reason):
        if not str(reason).strip():raise ValueError('暂停须说明原因')
        with self.edit() as data:
            self._session(data,session)
            data['run'].update(status='paused',reason=reason,paused_at=now())
            return dict(status='paused',session=session,reason=reason)

    def finish(self,session,task_id,result_file=None,error=None):
        with self.edit() as data:
            self._session(data,session)
            task=next((x for x in data['items'] if x['id']==task_id),None)
            if not task or task['status']!='running' or task.get('run_id')!=session or data['run'].get('current_task_id')!=task_id:
                raise RuntimeError('任务不是本会话正在处理的项目，不能重复完成或改写其他任务')
            if error:
                task.update(status='failed',error=str(error),finished_at=now())
                data['run'].update(status='paused',reason='task_failed',current_task_id=None)
                return dict(status='failed',task_id=task_id,queue_status='paused')
            path=absolute_file(result_file,'result_file');work=Path(task['work_dir']).resolve()
            if not path.is_relative_to(work):raise ValueError('结果记录必须位于本任务work_dir内')
            result=json.loads(path.read_text(encoding='utf-8-sig'))
            if result.get('photoshop_used') is not True:raise ValueError('不能把未实际使用PS的结果记作PS精修完成')
            review=result.get('visual_review',{})
            if review.get('status') not in ('passed','hold') or not str(review.get('note','')).strip():
                raise ValueError('须记录实际看图结果；不通过的返修不得冒充预览就绪')
            result_hashes={}
            for field in ('preview','work_file'):
                file=absolute_file(result.get(field,''),field)
                if not file.is_relative_to(work):raise ValueError(field+'越出本任务work_dir')
                result_hashes[field]=dict(path=str(file),sha256=sha(file))
            if not self._inputs_current(task):
                task.update(status='stale',error='inputs changed during retouch')
                data['run'].update(status='paused',reason='source_changed',current_task_id=None)
                return dict(status='stale',task_id=task_id,queue_status='paused')
            task.update(status='preview_ready',finished_at=now(),result_file=str(path),result_sha256=sha(path),
                outputs=result_hashes,visual_review=review,final_export_authorized=False)
            data['run']['current_task_id']=None
            if data['run']['status']=='running':self._monitor(data)
            return dict(status='preview_ready',task_id=task_id,queue_status=data['run']['status'],final_export_authorized=False)


def main(argv=None,skill_root=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=sorted(COMMANDS))
    parser.add_argument('--file');packet=parser.add_mutually_exclusive_group()
    packet.add_argument('--task');packet.add_argument('--task-file')
    parser.add_argument('--evidence');parser.add_argument('--session');parser.add_argument('--id')
    parser.add_argument('--result-file');parser.add_argument('--reason')
    args=parser.parse_args(argv)
    root=Path(skill_root or Path(__file__).resolve().parents[1])
    queue=Queue(args.file or default_file(root))
    if args.command=='queue':
        if args.task_file:task=json.loads(absolute_file(args.task_file,'task-file').read_text(encoding='utf-8-sig'))
        elif args.task:task=json.loads(args.task)
        else:raise ValueError('queue需要--task-file或--task')
        result=queue.enqueue(task)
    elif args.command=='queue-list':result=queue.read()
    elif args.command=='queue-start':result=queue.start(args.evidence or '')
    elif args.command=='queue-check':result=queue.check(args.session)
    elif args.command=='queue-next':result=queue.next(args.session)
    elif args.command=='queue-pause':result=queue.pause(args.session,args.reason or '')
    elif args.command=='queue-complete':result=queue.finish(args.session,args.id,args.result_file)
    elif args.command=='queue-fail':
        if not args.reason:raise ValueError('queue-fail需要--reason')
        result=queue.finish(args.session,args.id,error=args.reason)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result


if __name__=='__main__':main()
