"""Account-local CPU runtime with durable command and phase timing."""
import json,os,sys
from pathlib import Path
import run_journal as timing

def main():
    original=sys.argv[1:]
    task=timing.flag_path(original,('--spec','--cache'),Path.cwd()/'task')
    args,journal_root,mode=timing.peel_options(original,task.parent/'timing')
    command=args[0] if args else 'help'
    j=timing.Journal(journal_root,mode)
    controls={'check-start','check-pause','check-resume','check-finish','check-cancel','check-status','workflow-start','workflow-finish','timing-status'}
    kind='recording' if command in controls or command.startswith('queue') or command in ('-h','--help','help','idle','approve','feedback') else 'ai'
    with j.activate(),j.step('white:'+command,kind=kind,category=os.environ.get('AI_TIMING_CATEGORY','ai')):
        if command in controls:
            print(json.dumps(timing.control(j,command,args[1:]),ensure_ascii=False,indent=2));return
        root=Path(__file__).resolve().parents[1]
        import ps_retouch_queue
        if command in ps_retouch_queue.COMMANDS:
            with timing.step('runtime:validate_queue_interpreter'):
                config=json.loads((root/'runtime.json').read_text(encoding='utf-8-sig'))
                if Path(sys.executable).resolve()!=Path(config['python']).resolve():
                    raise RuntimeError('请使用本技能run_bg.ps1或runtime.json指定的专用Python')
            with timing.step('ps_queue:'+command):
                ps_retouch_queue.main(args,skill_root=root)
            return
        if command in ('-h','--help','help'):
            print('PS精修队列：queue / queue-list / queue-start / queue-check / queue-next / queue-complete / queue-fail / queue-pause；在聊天中输入“开始PS精修”启动。')
            if command=='help':args=['-h']
        with timing.step('runtime:validate'):
            config=json.loads((root/'runtime.json').read_text(encoding='utf-8-sig'))
            if Path(sys.executable).resolve()!=Path(config['python']).resolve():
                raise RuntimeError('请使用本技能run_bg.ps1或runtime.json指定的专用Python')
            if not (Path(config['model_dir'])/'u2net.onnx').is_file():
                raise RuntimeError('缺少已安装的本地u2net模型；请先恢复同一账号的技能环境')
            os.environ['U2NET_HOME']=config['model_dir'];os.environ['OMP_NUM_THREADS']=str(config.get('cpu_threads',2))
            os.environ['PYTHONDONTWRITEBYTECODE']='1'
            if config.get('disable_numba_jit',True):os.environ['NUMBA_DISABLE_JIT']='1'
        with timing.step('runtime:import'):
            import quality_pipeline as pipeline
        for module,name,label in [
            (pipeline.engine,'load_plan','plan:read_and_preflight'),
            (pipeline.engine,'cutout','image:cutout'),
            (pipeline.local_masks,'apply','image:explicit_local_masks'),
            (pipeline.quality,'repair','image:edge_repair_candidate'),
            (pipeline.quality,'diagnostics','image:four_background_diagnostics'),
            (pipeline.engine,'save_limited_image','export:compress_and_check_image_size'),
            (pipeline.engine,'write_psd','export:write_layered_psd'),
            (pipeline,'verify','export:reopen_and_verify_files_and_layers'),
            (pipeline,'prepare','preview:prepare_all'),
            (pipeline,'review','review:save_actual_visual_findings'),
            (pipeline,'export','export:confirmed_cached_batch')
        ]:timing.instrument(module,name,label)
        sys.argv=[sys.argv[0],*args]
        pipeline.main()

if __name__=='__main__':
    try:main()
    except (ValueError,FileExistsError,FileNotFoundError,RuntimeError,KeyError) as error:
        print(f'错误：{error}',file=sys.stderr)
        raise SystemExit(1)
