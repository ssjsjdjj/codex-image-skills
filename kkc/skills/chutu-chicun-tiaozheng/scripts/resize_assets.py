#!/usr/bin/env python3
"""正式入口：逐张预览确认后交付，保存每项状态和失败时的实际产物。"""
import argparse
import json
import sys
from pathlib import Path

from user_profile import Store, default_root, effective_job, file_hash
from validate_candidate import assert_render, load_engine
from review_queue import ReviewQueue
from PIL import Image


def queue_command(queue, argv, *, allow_legacy=False):
    parser = argparse.ArgumentParser(description='逐张预览与确认')
    sub = parser.add_subparsers(dest='cmd', required=True)
    start = sub.add_parser('review-start'); start.add_argument('--spec', required=True)
    for mode in ('review-next', 'review-adjust', 'review-confirm','review-authorize-style','review-select-backend',
                 'review-preview-all','review-confirm-all','review-adjust-item'):
        p = sub.add_parser(mode); p.add_argument('--review', required=True)
        if mode in ('review-adjust','review-adjust-item'):
            p.add_argument('--patch', required=True, help='当前图片的参数修改JSON')
            if mode=='review-adjust-item':p.add_argument('--index',type=int,required=True)
        if mode=='review-select-backend':
            p.add_argument('--backend',required=True,choices=('python','photoshop'))
            scope=p.add_mutually_exclusive_group()
            scope.add_argument('--through-index',type=int)
            scope.add_argument('--indices',help='明确选择的全局候选序号，逗号分隔')
            scope.add_argument('--size',help='明确选择当前尺寸组全部候选，如1440x1440')
        if mode in ('review-confirm','review-confirm-all','review-authorize-style','review-select-backend'):
            if mode in ('review-confirm','review-confirm-all'):p.add_argument('--digest', required=True)
            elif mode=='review-authorize-style':
                p.add_argument('--reference-index',type=int,required=True)
                p.add_argument('--from-index',type=int);p.add_argument('--to-index',type=int)
            group = p.add_mutually_exclusive_group(required=True)
            group.add_argument('--confirmation-file'); group.add_argument('--confirmation')
    args = parser.parse_args(argv)
    if args.cmd == 'review-start':
        if not allow_legacy and 'delivery' not in json.loads(Path(args.spec).read_text(encoding='utf-8-sig')):
            raise ValueError('请先人工选择主图/场景、款号、输出尺寸及图片/PSD命名，写入delivery后再建立数据包任务')
        return queue.start(args.spec)
    if args.cmd == 'review-next':
        return queue.next(args.review)
    if args.cmd == 'review-preview-all':
        return queue.preview_all(args.review)
    if args.cmd == 'review-adjust':
        return queue.adjust(args.review, json.loads(Path(args.patch).read_text(encoding='utf-8-sig')))
    if args.cmd == 'review-adjust-item':
        return queue.adjust_item(args.review,args.index,json.loads(Path(args.patch).read_text(encoding='utf-8-sig')))
    confirmation = Path(args.confirmation_file).read_text(encoding='utf-8-sig') if args.confirmation_file else args.confirmation
    if args.cmd=='review-select-backend':
        indices=None
        if args.indices:
            try:indices=[int(part.strip()) for part in args.indices.split(',')]
            except ValueError:raise ValueError('--indices必须是逗号分隔的整数序号') from None
        if args.size:
            from delivery_spec import _size
            size=_size(args.size);record=queue.load(args.review)
            indices=[i+1 for i,item in enumerate(record['items']) if item['job']['size']==size]
            if not indices:raise ValueError('当前批次没有该尺寸组')
        return queue.select_backend(args.review,args.backend,confirmation,args.through_index,indices=indices)
    if args.cmd=='review-confirm-all':
        return queue.confirm_all(args.review,args.digest,confirmation)
    if args.cmd=='review-authorize-style':
        return queue.authorize_style(args.review,confirmation,args.reference_index,args.from_index,args.to_index)
    return queue.confirm(args.review, args.digest, confirmation)


def deliver(store, engine, jobs, revision, settings, queue=None, review_id=None, resume=False):
    from delivery_pack import group_jobs,preflight_groups,capture_callback,build_groups,clean_caches
    groups=group_jobs(jobs)
    record = queue.ready(review_id) if queue else None
    previous_id = record.get('execution_batch') if record else None
    if previous_id:
        batch_id = previous_id
        previous = store.batch_record(batch_id)
        if previous['status'] == 'completed':
            raise ValueError('本队列已出图完成；不重复生成。请读取原批次结果')
        if not resume:
            raise ValueError('本队列存在未完成批次，请检查清单后使用--resume续跑')
    else:
        context=None
        if record and record.get('delivery_policy'):
            context={'image_kind':record['delivery_policy']['kind'],
                     'category':record.get('product_focus',{}).get('category','未指定')}
        batch_id = store.begin_batch(jobs, revision, context=context)
        if queue:
            queue.bind_batch(review_id, batch_id)
    batch_path = store.root / 'batches' / (batch_id + '.json')
    cache_root=(queue.path(review_id).parent/'psd-render-cache' if queue else store.root/'batches'/batch_id/'psd-render-cache')
    try:
        previous = store.batch_record(batch_id)
        completed = {p: sha for item in previous['items'] for p, sha in item.get('output_sha256', {}).items()}
        for path, sha in completed.items():
            if not Path(path).is_file() or file_hash(path) != sha:
                raise ValueError('已生成文件变化或缺失，不能自动续跑：' + path)
        pending_jobs = [job for i,job in enumerate(jobs) if previous['items'][i]['status'] != 'completed']
        preflight_groups(groups,previous,state_root=store.root)
        engine.preflight(pending_jobs, completed=completed)
        for index, job in enumerate(jobs):
            old = previous['items'][index]
            if old['status'] == 'completed':
                continue
            result = {}
            try:
                if store.active()[0] != revision:
                    raise ValueError('正式版本在出图期间变化，停止；请用新版本重新预览')
                expected_source = record['items'][index]['source_sha256'] if record else file_hash(job['input'])
                if file_hash(job['input']) != expected_source:
                    raise ValueError('原图与已确认预览不一致，停止出图')
                options={'completed':old.get('output_sha256', {})}
                if groups and job['_delivery'].get('source_type','photos')=='photos':
                    options['capture']=capture_callback(engine,cache_root,index)
                result = engine.make(job, **options)
                for output in result.get('outputs',[]):
                    path=Path(output)
                    if path.suffix.lower() in ('.jpg','.png','.webp'):
                        if path.stat().st_size>job.get('max_bytes',500000):
                            raise ValueError('实际图片文件超过500KB：'+output)
                        with Image.open(path) as saved:
                            if saved.size!=tuple(map(int,job['size'].lower().replace('×','x').replace('*','x').replace(' ','').split('x'))):
                                raise ValueError('实际图片文件尺寸不符：'+output)
                if file_hash(job['input']) != expected_source:
                    raise ValueError('出图期间原图发生变化，保留部分结果并停止')
                result['output_sha256'] = {p: file_hash(p) for p in result['outputs']}
                store.update_batch(batch_id, index, result)
            except Exception as exc:
                result = dict(getattr(exc, 'result', result))
                result['output_sha256'] = {p: file_hash(p) for p in result.get('outputs', []) if Path(p).is_file()}
                store.update_batch(batch_id, index, result, error=str(exc))
                raise
        if groups:build_groups(store,batch_id,groups)
        if groups and record and record.get('delivery_policy'):
            from delivery_notes import write_notes
            notes_record=store.batch_record(batch_id)
            notes_record['status']='completed'
            notes_record['review_mode']=record.get('review_mode','individual')
            notes_record['preview_confirmation']=record.get('batch_confirmation')
            notes_record['preview_groups']=record.get('batch_preview',{}).get('groups')
            if notes_record.get('error'):
                notes_record.setdefault('resolved_errors',[]).append(notes_record.pop('error'))
            notes=write_notes(record['delivery_policy']['out_dir'],policy=record['delivery_policy'],
                              jobs=jobs,batch_record=notes_record)
            with store.lock():
                from user_profile import write_json
                notes_record['delivery_notes']=notes
                write_json(batch_path,notes_record)
        final = store.update_batch(batch_id, complete=True, feedback_mode=settings['feedback']['mode'])
        results = final['items']
        if results:
            results[0]['feedback'] = {'batch_id': batch_id, 'feedback_due': final['feedback_due']}
            if groups:
                results[0]['source_files']=[path for entry in final['grouped_psds'].values() for path in entry['outputs']]
                results[0]['delivery']={'images':len(jobs),'psds':len(groups),'max_image_bytes':500000}
        if groups:
            try:
                clean_caches(final,cache_root)
            except Exception as cleanup_error:
                warning='交付已完成；临时缓存清理未完成：'+str(cleanup_error)
                if results:results[0].setdefault('cleanup_warnings',[]).append(warning)
                try:
                    with store.lock():
                        from user_profile import write_json
                        saved=store.batch_record(batch_id)
                        saved.setdefault('cleanup_warnings',[]).append(warning)
                        write_json(batch_path,saved)
                except Exception as audit_error:
                    warning+='；清理警告持久化失败：'+str(audit_error)
                # Cache housekeeping must not turn a fully verified delivery into partial.
                print(json.dumps({'batch_id':batch_id,'status':'completed','cleanup_warning':warning},ensure_ascii=False),file=sys.stderr)
        return results
    except Exception as exc:
        final = store.update_batch(batch_id, error=str(exc))
        pending_publications=[{'destination':value.get('destination'),'status':value['status'],
                               'published_outputs':value.get('published_outputs',[]),'staged_path':value.get('staged_path')}
                              for value in final.get('grouped_psds',{}).values()
                              if value.get('status')=='pending_publication']
        store.incident(str(exc), {'batch_id': batch_id, 'completed_outputs': final['outputs'], 'record': str(batch_path),
                                 'pending_psd_publications':pending_publications})
        print(json.dumps({'batch_id': batch_id, 'status': final['status'], 'completed_outputs': final['outputs'],
                          'items': final['items'], 'record': str(batch_path), 'automatic_rollback': False,
                          'pending_psd_publications':pending_publications}, ensure_ascii=False), file=sys.stderr)
        raise


def run(store, argv, *, review_required=True):
    if argv and argv[0]=='delivery-options':
        from delivery_spec import size_options
        parser=argparse.ArgumentParser(description='先选择用途，再选择尺寸')
        parser.add_argument('command');parser.add_argument('--kind',required=True,choices=('main','scene'))
        args=parser.parse_args(argv)
        print(json.dumps(size_options(args.kind),ensure_ascii=False,indent=2))
        return
    # Python-only isolation fixture option; main() never provides a CLI bypass.
    if not review_required and store.root == default_root().resolve():
        raise ValueError('正式账号不能跳过逐张预览确认')
    with store.lock():
        revision, folder, settings = store.active()
        engine = load_engine(folder)
        engine.native_cache_root=store.root/'native-psd-cache'
    original_render = engine._render
    def render(job):
        actual = effective_job(settings, job)
        src, image, plan, resolved = original_render(actual)
        assert_render(image, plan, actual)
        return src, image, plan, resolved
    engine._render = render
    queue = ReviewQueue(store, engine)
    if argv and argv[0].startswith('review-'):
        result = queue_command(queue, argv,allow_legacy=not review_required)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if argv and argv[0] == 'batch' and ('--review' in argv or review_required):
        parser = argparse.ArgumentParser(description='全批逐张确认后出图')
        parser.add_argument('command'); parser.add_argument('--review', required=True)
        parser.add_argument('--resume', action='store_true')
        args = parser.parse_args(argv)
        record = queue.ready(args.review)
        if review_required and not record.get('delivery_policy'):
            raise ValueError('旧裁切队列缺少新版数据包交付方案；请补充人工尺寸/命名并重新建立任务')
        result = deliver(store, engine, [i['job'] for i in record['items']], revision, settings,
                         queue, args.review, args.resume)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if review_required and argv and argv[0] in ('make', 'replay'):
        raise ValueError('请把待处理图片放入任务单，用review-start、review-preview-all、集中确认后batch --review出图')
    # Diagnostic preview/presets and isolated low-level regression fixtures.
    original_make = engine.make
    import types
    engine_for_delivery = types.SimpleNamespace(make=original_make, preflight=engine.preflight)
    def make(job, **kwargs):
        return deliver(store, engine_for_delivery, [effective_job(settings, job)], revision, settings)[0]
    def batch(jobs):
        return deliver(store, engine_for_delivery, [effective_job(settings, job) for job in jobs], revision, settings)
    engine.make, engine.batch = make, batch
    previous = sys.argv
    sys.argv = [str(folder / 'renderer.py'), *argv]
    try:
        engine.main()
    finally:
        sys.argv = previous


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--state')
    args, remaining = parser.parse_known_args()
    if not remaining or '--help' in remaining or '-h' in remaining:
        if remaining and remaining[0].startswith('review-'):
            queue_command(None,[remaining[0],'--help'])
        else:
            print('尺寸调整3.4：用途分支、同尺寸编号、整批预览与集中确认')
            print('delivery-options --kind main|scene')
            print('review-start --spec <JSON>')
            print('review-preview-all --review <ID>')
            print('review-select-backend --review <ID> --backend python|photoshop --size <尺寸> --confirmation-file <原文>')
            print('review-adjust-item --review <ID> --index <候选序号> --patch <JSON>')
            print('review-confirm-all --review <ID> --digest <摘要> --confirmation-file <原文>')
            print('batch --review <ID> [--resume]')
            print('help和用途菜单只读，不初始化或锁定个人配置。')
        return
    try:
        run(Store(args.state), remaining)
    except Exception as exc:
        print('[错误] ' + str(exc), file=sys.stderr)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
