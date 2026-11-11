"""Isolated queue regression; no Photoshop, real user tasks or global queue are used.

The result JSON fixtures exercise evidence validation only. Their photoshop_used
flag is synthetic test data, never evidence that this test invoked Photoshop.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from PIL import Image

import ps_retouch_queue as module


class Checks:
    def __init__(self):
        self.results = []

    def check(self, name, condition):
        self.results.append(dict(name=name, passed=bool(condition)))

    def rejects(self, name, action, expected=(ValueError, RuntimeError)):
        try:
            action()
        except expected as error:
            self.results.append(dict(name=name, passed=True, error=str(error)))
        except Exception as error:
            self.results.append(dict(name=name, passed=False,
                                     error=type(error).__name__ + ': ' + str(error)))
        else:
            self.results.append(dict(name=name, passed=False, error='operation was accepted'))

    def scenario(self, name, action):
        try:
            action()
        except Exception as error:
            self.results.append(dict(name=name + ': unexpected error', passed=False,
                                     error=type(error).__name__ + ': ' + str(error)))


class Marker:
    def __init__(self):
        self.value = dict(available=True, input_tick=100, idle_seconds=0)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return dict(self.value)


def image(path, color=(60, 120, 180, 255)):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGBA', (24, 32), color).save(path)
    return path.resolve()


def fixture(work, name):
    root = work / name
    task_root = root / 'task-root'
    task_root.mkdir(parents=True)
    marker = Marker()
    queue = module.Queue(root / 'isolated-queue.json', snapshot=marker)

    def task(title, reference=False):
        source = image(root / (title + '.png'))
        row = dict(input=str(source), label=title)
        if reference:
            row['reference'] = str(image(root / (title + '-reference.png')))
        return dict(title=title, scope='synthetic edge test', enqueue_evidence='选项3：后续排队',
                    task_root=str(task_root.resolve()), items=[row])

    return queue, marker, task


def result_fixture(task, name='result', review='passed'):
    work = Path(task['work_dir'])
    work.mkdir(parents=True, exist_ok=True)
    preview = image(work / (name + '-preview.png'))
    work_file = image(work / (name + '-work.png'), (80, 160, 200, 255))
    record = dict(photoshop_used=True, synthetic_test_fixture=True,
                  visual_review=dict(status=review,
                                     note='Synthetic schema fixture; no actual Photoshop use is claimed.'),
                  preview=str(preview), work_file=str(work_file))
    path = work / (name + '.json')
    path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    return path, record


def write_record(path, record):
    path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')


def run_checks(work, checks):
    def lifecycle():
        queue, marker, task = fixture(work, 'lifecycle')
        first_task = task('first')
        source_before = hashlib.sha256(Path(first_task['items'][0]['input']).read_bytes()).hexdigest()
        first = queue.enqueue(first_task)
        first_id = first['task']['id']
        checks.check('option 3 enqueues pending without Photoshop start',
                     first['status'] == 'pending' and first['photoshop_started'] is False)
        checks.check('enqueue does not even consult the input/idle monitor', marker.calls == 0)
        checks.check('enqueue does not create a retouch work directory',
                     not Path(first['task']['work_dir']).exists())
        reopened = module.Queue(queue.path, snapshot=marker)
        checks.check('queue persistence survives a new Queue instance',
                     reopened.read()['items'][0]['id'] == first_id)
        duplicate = reopened.enqueue(first_task)
        checks.check('pending duplicate enqueue returns existing task',
                     duplicate['already_queued'] and duplicate['task']['id'] == first_id
                     and len(reopened.read()['items']) == 1)
        second = reopened.enqueue(task('second'))
        third = reopened.enqueue(task('third'))
        checks.check('persistent FIFO order matches enqueue order',
                     [row['id'] for row in reopened.read()['items']]
                     == [first_id, second['task']['id'], third['task']['id']])

        for phrase in ('', '开始精修', '帮我开始PS精修', '开始PS精修吧', '开始PS精修 && calc'):
            checks.rejects('reject non-exact start phrase: ' + repr(phrase),
                           lambda phrase=phrase: reopened.start(phrase))
        checks.check('rejected start phrases leave every item pending',
                     all(row['status'] == 'pending' for row in reopened.read()['items']))
        checks.check('start phrase ignores PS case, whitespace and fullwidth Latin letters',
                     all(module.is_start_phrase(value) for value in
                         ('开始ps精修', ' 开 始 pS 精 修 \n', '开始ＰＳ精修')))
        started = reopened.start(' 开 始 pS 精 修 ')
        session = started['session']
        checks.check('explicit command starts at idle zero and claims first FIFO task',
                     started['status'] == 'running' and started['task']['id'] == first_id
                     and started['resume_required'] is False
                     and reopened.read()['run']['start_idle_seconds'] == 0)
        repeated = reopened.start('开始PS精修')
        checks.check('repeated command while running does not create another session',
                     repeated['status'] == 'already_running' and repeated['session'] == session)
        checks.check('running duplicate enqueue does not append a new task',
                     reopened.enqueue(first_task)['already_queued'] and len(reopened.read()['items']) == 3)
        current = reopened.next(session)
        checks.check('next preserves in-flight task and flags resume_required',
                     current['task']['id'] == first_id and current['resume_required'] is True)
        stable_bytes = queue.path.read_bytes()
        for operation, action in (
            ('check', lambda: reopened.check('wrong-session')),
            ('next', lambda: reopened.next('wrong-session')),
            ('pause', lambda: reopened.pause('wrong-session', 'test')),
            ('complete', lambda: reopened.finish('wrong-session', first_id))):
            checks.rejects('wrong session rejected by ' + operation, action)
        checks.check('wrong-session attempts preserve persisted queue bytes', queue.path.read_bytes() == stable_bytes)

        marker.value['input_tick'] += 1
        paused = reopened.check(session)
        checks.check('new input event safely pauses active run',
                     paused['status'] == 'paused' and paused['reason'] == 'new_input_event')
        checks.check('next cannot silently resume after input event',
                     reopened.next(session)['status'] == 'paused')
        marker.value['input_tick'] += 1
        checks.check('check cannot silently resume after additional input events',
                     reopened.check(session)['status'] == 'paused')
        checks.rejects('resume also requires the exact explicit phrase', lambda: reopened.start('继续'))
        resumed = reopened.start('开始ps精修')
        new_session = resumed['session']
        checks.check('new command resumes same in-flight task without re-claiming',
                     resumed['task']['id'] == first_id and resumed['resume_required'] is True
                     and new_session != session)
        checks.check('resume records the new input baseline',
                     reopened.read()['run']['input_tick'] == marker.value['input_tick'])
        checks.rejects('superseded session can no longer finish',
                       lambda: reopened.finish(session, first_id))

        record_path, record = result_fixture(resumed['task'])
        outside_record = work / 'outside-result.json'
        write_record(outside_record, record)
        checks.rejects('completion rejects missing result record',
                       lambda: reopened.finish(new_session, first_id, record_path.parent / 'missing.json'))
        checks.rejects('completion rejects result record outside task work_dir',
                       lambda: reopened.finish(new_session, first_id, outside_record))
        mutations = (
            ('Photoshop not actually used flag', lambda x: x.update(photoshop_used=False)),
            ('missing actual visual review', lambda x: x.pop('visual_review')),
            ('empty review note', lambda x: x['visual_review'].update(note=' ')),
            ('rejected visual review', lambda x: x['visual_review'].update(status='rejected')),
            ('missing preview file', lambda x: x.update(preview=str(record_path.parent / 'missing.png'))),
            ('preview outside task work_dir', lambda x: x.update(preview=first_task['items'][0]['input'])),
            ('missing work file', lambda x: x.update(work_file=str(record_path.parent / 'missing-work.png'))),
            ('work file outside task work_dir', lambda x: x.update(work_file=first_task['items'][0]['input'])),
        )
        for label, mutate in mutations:
            invalid = copy.deepcopy(record)
            mutate(invalid)
            write_record(record_path, invalid)
            checks.rejects('completion rejects ' + label,
                           lambda: reopened.finish(new_session, first_id, record_path))
        checks.check('failed evidence checks keep task running', reopened.read()['items'][0]['status'] == 'running')
        write_record(record_path, record)
        completed = reopened.finish(new_session, first_id, record_path)
        persisted = reopened.read()['items'][0]
        checks.check('valid synthetic evidence reaches preview_ready only',
                     completed['status'] == persisted['status'] == 'preview_ready'
                     and completed['final_export_authorized'] is False
                     and persisted['final_export_authorized'] is False)
        checks.check('preview and work files are retained with verifiable hashes',
                     all(module.sha(info['path']) == info['sha256'] for info in persisted['outputs'].values()))
        checks.rejects('duplicate completion is rejected',
                       lambda: reopened.finish(new_session, first_id, record_path))
        next_task = reopened.next(new_session)
        checks.check('next after completion continues FIFO with the second task',
                     next_task['task']['id'] == second['task']['id']
                     and next_task['resume_required'] is False)
        failed = reopened.finish(new_session, second['task']['id'], error='synthetic PS operation failed')
        state = reopened.read()
        checks.check('failure pauses queue and preserves later pending work',
                     failed['status'] == 'failed' and state['run']['status'] == 'paused'
                     and state['items'][2]['status'] == 'pending')
        checks.check('next cannot bypass failure pause', reopened.next(new_session)['status'] == 'paused')
        last = reopened.start('开始PS精修')
        checks.check('fresh command continues pending work after failed task', last['task']['id'] == third['task']['id'])
        last_path, _ = result_fixture(last['task'], review='hold')
        checks.check('honest hold review can be sent for human preview',
                     reopened.finish(last['session'], third['task']['id'], last_path)['status'] == 'preview_ready')
        checks.check('drained queue reports finished_with_issues when a task failed',
                     reopened.next(last['session'])['status'] == 'finished_with_issues')
        checks.check('preview-ready files alone grant no new work/export authorization',
                     reopened.start('开始PS精修')['status'] == 'no_pending_tasks'
                     and all(not row.get('final_export_authorized', False) for row in reopened.read()['items']))
        checks.check('source image was never modified by queue lifecycle',
                     hashlib.sha256(Path(first_task['items'][0]['input']).read_bytes()).hexdigest() == source_before)

    def stale():
        queue, marker, task = fixture(work, 'stale')
        first_task = task('first', reference=True)
        first = queue.enqueue(first_task)
        second = queue.enqueue(task('second'))
        image(first_task['items'][0]['reference'], (1, 2, 3, 255))
        rejected = queue.start('开始PS精修')
        checks.check('changed queued reference is marked stale and never returned as task',
                     rejected['status'] == 'paused' and rejected['reason'] == 'source_changed'
                     and 'task' not in rejected and queue.read()['items'][0]['status'] == 'stale')
        checks.check('stale FIFO item pauses before claiming following pending work',
                     queue.read()['items'][1]['status'] == 'pending'
                     and queue.next(rejected['session'])['status'] == 'paused')
        running = queue.start('开始PS精修')
        checks.check('explicit new command can claim the following unchanged task',
                     running['task']['id'] == second['task']['id'])
        image(running['task']['items'][0]['input'], (2, 3, 4, 255))
        result_path, _ = result_fixture(running['task'])
        finished = queue.finish(running['session'], running['task']['id'], result_path)
        checks.check('source changed during retouch cannot be marked preview_ready',
                     finished['status'] == 'stale' and queue.read()['run']['status'] == 'paused')

    def monitor_and_pause():
        queue, marker, task = fixture(work, 'monitor')
        queue.enqueue(task('first'))
        marker.value['available'] = False
        checks.rejects('unavailable input monitor prevents startup', lambda: queue.start('开始PS精修'))
        checks.check('unavailable monitor leaves task pending', queue.read()['items'][0]['status'] == 'pending')
        marker.value['available'] = True
        running = queue.start('开始PS精修')
        paused = queue.pause(running['session'], 'user requested pause')
        checks.check('explicit pause preserves in-flight task',
                     paused['status'] == 'paused' and queue.read()['items'][0]['status'] == 'running')
        resumed = queue.start('开始PS精修')
        checks.check('explicitly paused task resumes with manual state inspection required',
                     resumed['task']['id'] == running['task']['id'] and resumed['resume_required'] is True)
        marker.value['available'] = False
        checks.check('losing input monitor during run pauses safely',
                     queue.check(resumed['session'])['reason'] == 'input_monitor_unavailable')

    def boundaries():
        queue, marker, task = fixture(work, 'boundaries')
        checks.check('empty queue never starts a Photoshop session',
                     queue.start('开始PS精修')['status'] == 'empty'
                     and queue.read()['run']['status'] == 'idle' and marker.calls == 0)
        good = task('valid')
        for suffix in ('.py', '.ps1', '.jsx'):
            script = Path(good['task_root']) / ('not-an-image' + suffix)
            script.write_text('THIS IS INERT SYNTHETIC TEST DATA', encoding='utf-8')
            invalid = copy.deepcopy(good)
            invalid['items'][0]['input'] = str(script)
            checks.rejects('script input rejected: ' + suffix, lambda invalid=invalid: queue.enqueue(invalid))
        invalid = copy.deepcopy(good)
        invalid['items'][0]['reference'] = str(script)
        checks.rejects('script reference rejected', lambda: queue.enqueue(invalid))
        invalid = copy.deepcopy(good)
        invalid['items'][0]['input'] = 'relative.png'
        checks.rejects('non-absolute input path rejected', lambda: queue.enqueue(invalid))
        entry = queue.enqueue(good)
        before = queue.path.read_bytes()
        lock = queue.path.with_name(queue.path.name + '.lock')
        lock.write_text('existing owner test fixture', encoding='utf-8')
        checks.rejects('exclusive queue lock rejects a competing mutation', lambda: queue.enqueue(task('other')))
        checks.check('lock conflict preserves queue bytes and original lock owner',
                     queue.path.read_bytes() == before and lock.read_text(encoding='utf-8') == 'existing owner test fixture')
        lock.unlink()
        checks.check('original queue remains readable after lock release',
                     queue.read()['items'][0]['id'] == entry['task']['id'])
        malformed = work / 'malformed.json'
        malformed.write_text('{not json', encoding='utf-8')
        broken = module.Queue(malformed, snapshot=marker)
        checks.rejects('malformed queue is rejected without reset', lambda: broken.enqueue(good))
        checks.check('malformed queue bytes are preserved', malformed.read_text(encoding='utf-8') == '{not json')
        unsupported = work / 'unsupported.json'
        unsupported.write_text('{"schema_version": 999, "items": [], "run": {}}', encoding='utf-8')
        unsupported_before = unsupported.read_bytes()
        checks.rejects('unsupported queue schema is rejected',
                       lambda: module.Queue(unsupported, snapshot=marker).enqueue(good))
        checks.check('unsupported queue bytes are preserved', unsupported.read_bytes() == unsupported_before)

    for name, action in (('lifecycle', lifecycle), ('stale', stale),
                         ('monitor and pause', monitor_and_pause), ('boundaries', boundaries)):
        checks.scenario(name, action)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', required=True, help='A new isolated test directory; must not already exist')
    args = parser.parse_args(argv)
    work = Path(args.work).resolve()
    work.mkdir(parents=True, exist_ok=False)
    checks = Checks()
    run_checks(work, checks)
    failed = [item for item in checks.results if not item['passed']]
    report = dict(passed=not failed, checks=len(checks.results), passed_checks=len(checks.results) - len(failed),
                  failed_checks=len(failed), actual_photoshop_invoked=False, global_queue_used=False,
                  synthetic_result_evidence_only=True, work=str(work), results=checks.results)
    report_path = work / 'report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(passed=report['passed'], checks=report['checks'],
                         passed_checks=report['passed_checks'], failed_checks=report['failed_checks'],
                         failures=failed, report=str(report_path)), ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
