"""Preview -> risk review -> explicit user approval -> identical cached export."""
import argparse, hashlib, json, os, shutil, sys, tempfile, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageOps
import bg_assets as engine
import edge_quality as quality
import local_masks
import hd_mask_psd


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path,value,exclusive=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path if exclusive else path.with_name(path.name+'.tmp-'+str(time.time_ns()))
    with temporary.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.flush();os.fsync(stream.fileno())
    if not exclusive:os.replace(temporary,path)


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()


def state_path(cache):
    return Path(cache)/'state.json'


def plan_for(spec):
    plan=engine.load_plan(spec)
    for job in plan['jobs']:local_masks.validate_job(job)
    return plan


def identity(plan):
    jobs=[]
    for job in plan['jobs']:
        entry=dict(job,source_sha256=quality.sha(job['input']))
        entry['mask_sha256']={field:quality.sha(job[field]) for field in local_masks.MASK_FIELDS if job.get(field)}
        jobs.append(entry)
    return digest(jobs)


def processor_fingerprint():
    directory=Path(__file__).resolve().parent
    return digest({name:quality.sha(directory/name) for name in
        ('quality_pipeline.py','edge_quality.py','local_masks.py','bg_assets.py','image_size_limit.py','hd_mask_psd.py')})


def image_record(path):
    with Image.open(path) as image:
        pixels=np.asarray(image.convert('RGBA'))
        size=list(image.size)
    return dict(path=str(path),sha256=quality.sha(path),rgba_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),size=size)


def candidate_record(path,qa,native_path,**extra):
    return dict(**image_record(path),qa=qa,native=image_record(native_path),**extra)


def checked_image(record,cache,label):
    path=Path(record['path']).resolve()
    if not path.is_relative_to(Path(cache).resolve()) or quality.sha(path)!=record['sha256']:
        raise RuntimeError(label+'缓存改变，须重新预览和确认')
    with Image.open(path) as image:
        rgba=image.convert('RGBA')
    if list(rgba.size)!=record['size'] or hashlib.sha256(np.asarray(rgba).tobytes()).hexdigest()!=record['rgba_sha256']:
        raise RuntimeError(label+'像素或尺寸改变')
    return rgba


def normalize(subject,job):
    picture,left,top=engine.place_subject(subject,job['fill'])
    result=Image.new('RGBA',(800,800));result.alpha_composite(picture,(left,top))
    return result


def preview_sheet(items,path,font):
    canvas=Image.new('RGB',(688,len(items)*370+16),(60,60,64));draw=ImageDraw.Draw(canvas)
    for row,item in enumerate(items):
        im=Image.open(item['selected']['path']).convert('RGBA');im.thumbnail((320,320))
        white=quality.composite(im,'white');checker=engine._checker(im.size);checker.paste(im,(0,0),im)
        x,y=16,16+row*370;canvas.paste(white,(x,y));canvas.paste(checker,(352,y))
        draw.text((x,y+326),f"{item['style']} / {item['layer_name']} 白底",font=font,fill='white')
        label='透明 · 有边缘风险提示' if item['qa']['flags'] else '透明预览'
        draw.text((352,y+326),label,font=font,fill='white')
    with Path(path).open('xb') as stream:canvas.save(stream,format='PNG')


def prepare(spec,cache,out=None,offset=0,limit=0):
    plan=plan_for(spec);cache=Path(cache).resolve()
    initial_identity=identity(plan);spec_sha=quality.sha(spec);processor_sha=processor_fingerprint()
    if cache.is_relative_to(Path(plan['out_dir'])):
        raise ValueError('缓存和诊断必须位于正式输出目录之外')
    cache.mkdir(parents=True,exist_ok=False)
    out=engine.auxiliary_path(out or cache/'preview.png',plan)
    if offset<0 or offset>=plan['input_count'] or limit<0:raise ValueError('预览分页越界')
    items=[];font=engine._font(16)
    for number,job in enumerate(plan['jobs'],1):
        started=time.perf_counter();source_hash=quality.sha(job['input'])
        with Image.open(job['input']) as raw:
            source=ImageOps.exif_transpose(raw).convert('RGBA')
        source_path=cache/f'{number:04d}-source.png';source.save(source_path)
        reused_alpha=bool(job.get('cutout','auto')=='auto' and engine.has_real_alpha(source))
        masks=local_masks.load(job,source.size)
        subject=engine.cutout(source,job.get('cutout','auto'))
        if any(field in masks for field in ('keep_mask','remove_mask')):
            subject.save(cache/f'{number:04d}-full-alpha-before-edits.png')
        subject,protected,edits=local_masks.apply(subject,source,masks)
        native_path=cache/f'{number:04d}-full-alpha.png';subject.save(native_path)
        initial=normalize(subject,job);initial_path=cache/f'{number:04d}-initial.png';initial.save(initial_path)
        initial_qa=quality.analyze(initial,job.get('review_regions'))
        choices={'initial':candidate_record(initial_path,initial_qa,native_path)}
        selected='initial';best=initial_qa['metrics']['rim_severity'];attempts=[]
        bbox=subject.getchannel('A').getbbox()
        scale=800*job['fill']/max(bbox[2]-bbox[0],bbox[3]-bbox[1])
        do_repair=(not reused_alpha or job.get('repair_existing_alpha') is True)
        if do_repair and any('rim' in f for f in initial_qa['flags']):
            for round_number in (1,2):
                repaired,guard=quality.repair(subject,round_number,scale,protected)
                rendered=normalize(repaired,job);qa=quality.analyze(rendered,job.get('review_regions'))
                path=cache/f'{number:04d}-repair{round_number}.png';rendered.save(path)
                repaired_path=cache/f'{number:04d}-repair{round_number}-full-alpha.png';repaired.save(repaired_path)
                name=f'repair{round_number}'
                eligible=guard['accepted'] and qa['technical_pass']
                choices[name]=candidate_record(path,qa,repaired_path,guard=guard,eligible=eligible)
                improved=qa['metrics']['rim_severity']<best*.95 and qa['metrics']['suspect_pixels']<=initial_qa['metrics']['suspect_pixels']
                attempts.append(dict(candidate=name,guard=guard,risk=qa['metrics']['rim_risk_ratio'],selected=bool(eligible and improved)))
                if eligible and improved:selected=name;best=qa['metrics']['rim_severity']
        picked=choices[selected]
        qa=picked['qa'];diagnostic=cache/f'{number:04d}-diagnostic.png'
        quality.diagnostics(Image.open(picked['path']).convert('RGBA'),qa,font).save(diagnostic)
        item=dict(index=number,style=job['style'],layer_name=job['layer_name'],input=job['input'],source_sha256=source_hash,
            reused_existing_alpha=reused_alpha,candidates=choices,selected_name=selected,selected=picked,qa=qa,
            source_size=list(source.size),source_cache=image_record(source_path),local_edits=edits,
            diagnostic=str(diagnostic),diagnostic_sha256=quality.sha(diagnostic),attempts=attempts,elapsed_seconds=round(time.perf_counter()-started,3),
            visual_review=dict(status='pending'),human_confirmation=dict(status='pending'))
        items.append(item)
    if identity(plan)!=initial_identity or quality.sha(spec)!=spec_sha or processor_fingerprint()!=processor_sha:
        raise RuntimeError('处理期间原图、蒙版、任务单或处理代码发生改变')
    visible=items[offset:offset+limit if limit else None]
    out.parent.mkdir(parents=True,exist_ok=True)
    preview_sheet(visible,out,font)
    state=dict(version=quality.VERSION,spec=str(Path(spec).resolve()),spec_sha256=spec_sha,processor_sha256=processor_sha,
        plan=plan,identity=initial_identity,items=items,revision=0,
        preview=str(out),preview_sha256=quality.sha(out),shown=[x['index'] for x in visible],
        status='awaiting_visual_review',formal_files_written=0,created_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
    write(state_path(cache),state,True)
    return dict(cache=str(cache),state=str(state_path(cache)),preview=str(out),shown=len(visible),
        remaining=len(items)-len(visible),formal_files_written=0,total_files=plan['total_files'],
        suspected_images=[i['index'] for i in items if i['qa']['flags']],visual_review_required=[i['index'] for i in items])


def load_checked(cache):
    cache=Path(cache).resolve();state=read(state_path(cache));plan=state['plan']
    if state.get('version')!=quality.VERSION or state.get('processor_sha256')!=processor_fingerprint():
        raise RuntimeError('处理代码已更新，须重新生成预览缓存')
    if quality.sha(state['spec'])!=state.get('spec_sha256'):raise RuntimeError('任务单文件已改变，须重新预览')
    if identity(plan)!=state['identity']:raise RuntimeError('原图、参数或保护蒙版已变化，须重新预览')
    if quality.sha(state['preview'])!=state['preview_sha256']:raise RuntimeError('预览文件已改变，须重新预览')
    for item,job in zip(state['items'],plan['jobs']):
        if item['selected']!=item['candidates'][item['selected_name']]:raise RuntimeError('候选选择记录不一致')
        approved=checked_image(item['selected'],cache,'确认候选')
        native=checked_image(item['selected']['native'],cache,'高清候选')
        source=checked_image(item['source_cache'],cache,'原始素材')
        if approved.size!=(800,800) or native.size!=source.size or list(source.size)!=item['source_size']:
            raise RuntimeError('高清候选、原图或确认图尺寸不一致')
        if not np.array_equal(np.asarray(normalize(native,job)),np.asarray(approved)):
            raise RuntimeError('高清候选与800像素确认图不匹配')
        if quality.sha(item['diagnostic'])!=item['diagnostic_sha256']:raise RuntimeError('诊断图已改变，须重新看图复核')
    return state


def review(cache,decisions):
    state=load_checked(cache);data=read(decisions)
    entries=data.get('items',[])
    if len({e['index'] for e in entries})!=len(entries):raise ValueError('重复图号')
    by_index={i['index']:i for i in state['items']}
    for entry in entries:
        if entry['index'] not in by_index or entry.get('status') not in ('passed','hold','rejected'):
            raise ValueError('无效的复核图号或状态')
        item=by_index[entry['index']]
        if not str(entry.get('note','')).strip():raise ValueError('复核须说明实际查看结果和疑似问题判定')
        if not str(data.get('reviewer','')).strip():raise ValueError('缺少复核人或AI复核来源')
        item['visual_review']=dict(status=entry['status'],note=entry['note'],reviewer=data['reviewer'],
            selected_sha256=item['selected']['sha256'],checked_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
    invalidate_confirmation(state)
    state['status']='awaiting_user_confirmation' if all(i['visual_review']['status']=='passed' for i in state['items']) else 'visual_review_incomplete'
    write(state_path(cache),state)
    return dict(status=state['status'],held=[i['index'] for i in state['items'] if i['visual_review']['status']!='passed'])


def choose(cache,index,candidate):
    state=load_checked(cache);item=next((i for i in state['items'] if i['index']==index),None)
    if item is None or candidate not in item['candidates']:raise ValueError('候选或图号不存在')
    picked=item['candidates'][candidate]
    if candidate!='initial' and not picked.get('eligible'):raise ValueError('候选未通过细节保护检查，禁止采用')
    if quality.sha(picked['path'])!=picked['sha256']:raise RuntimeError('候选文件已改变')
    native=checked_image(picked['native'],cache,'高清候选')
    approved=checked_image(picked,cache,'确认候选')
    job=next(j for j in state['plan']['jobs'] if job_key(j)==job_key(item))
    if not np.array_equal(np.asarray(normalize(native,job)),np.asarray(approved)):
        raise RuntimeError('高清候选与确认图不匹配')
    item.update(selected_name=candidate,selected=picked,qa=picked['qa'],visual_review=dict(status='pending'))
    quality.diagnostics(Image.open(picked['path']).convert('RGBA'),item['qa'],engine._font(16)).save(item['diagnostic'])
    item['diagnostic_sha256']=quality.sha(item['diagnostic'])
    # New filename binds the next approval to a refreshed complete preview.
    path=Path(cache)/('preview-'+str(time.time_ns())+'.png');preview_sheet(state['items'],path,engine._font(16))
    state.update(preview=str(path),preview_sha256=quality.sha(path),shown=[i['index'] for i in state['items']],status='awaiting_visual_review')
    invalidate_confirmation(state)
    write(state_path(cache),state)
    return dict(preview=str(path),status=state['status'])


def approval_binding(state):
    return digest(dict(identity=state['identity'],spec_sha256=state['spec_sha256'],processor=state['processor_sha256'],
        revision=state['revision'],preview_sha256=state['preview_sha256'],shown=state['shown'],
        items=[dict(index=i['index'],sha256=i['selected']['sha256'],rgba_sha256=i['selected']['rgba_sha256'],
                    native=i['selected']['native'],source_cache=i['source_cache'],
                    diagnostic_sha256=i['diagnostic_sha256'],review=i['visual_review']) for i in state['items']]))


def invalidate_confirmation(state):
    state['revision']+=1
    state.pop('approval',None)
    for item in state['items']:item['human_confirmation']=dict(status='pending')


def check_approval(state,auth):
    if state.get('status')!='user_confirmed' or auth.get('binding')!=approval_binding(state):
        raise RuntimeError('确认已失效，须重新复核和确认')
    if not all(i['visual_review']['status']=='passed' and i['qa']['technical_pass'] and
               i['visual_review'].get('selected_sha256')==i['selected']['sha256'] for i in state['items']):
        raise RuntimeError('视觉复核未完成或不属于当前候选')


def approve(cache,evidence,actor):
    state=load_checked(cache)
    if not evidence.strip() or not actor.strip():raise ValueError('须提供用户明确确认的原话或可核验来源及确认人')
    if set(state['shown'])!={i['index'] for i in state['items']}:raise RuntimeError('尚未展示完整批次；重新预览全部图片后确认')
    if not all(i['qa']['technical_pass'] and i['visual_review']['status']=='passed' and
               i['visual_review'].get('selected_sha256')==i['selected']['sha256'] for i in state['items']):
        raise RuntimeError('存在未通过或未完成的视觉复核，不能确认交付')
    approval=dict(binding=approval_binding(state),actor=actor,evidence=evidence,
        recorded_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'),preview=state['preview'],preview_sha256=state['preview_sha256'],
        processor_sha256=state['processor_sha256'],revision=state['revision'],
        images=[dict(index=i['index'],path=i['selected']['path'],sha256=i['selected']['sha256'],rgba_sha256=i['selected']['rgba_sha256']) for i in state['items']])
    path=Path(cache)/('approval-'+str(time.time_ns())+'.json');write(path,approval,True)
    for item in state['items']:
        item['human_confirmation']=dict(status='confirmed',actor=actor,evidence=evidence,selected_sha256=item['selected']['sha256'])
    state.update(status='user_confirmed',approval=str(path))
    write(state_path(cache),state)
    return dict(approval=str(path),binding=approval['binding'])


def feedback(cache,index,evidence):
    state=load_checked(cache)
    if not evidence.strip():raise ValueError('缺少用户实际问题反馈')
    item=next((i for i in state['items'] if i['index']==index),None)
    if item is None:raise ValueError('图号不存在')
    invalidate_confirmation(state)
    item.setdefault('human_feedback',[]).append(dict(evidence=evidence,selected_sha256=item['selected']['sha256'],at=time.strftime('%Y-%m-%dT%H:%M:%S%z')))
    item['visual_review']=dict(status='rejected',note=evidence,reviewer='user feedback')
    item['human_confirmation']=dict(status='rejected',evidence=evidence)
    state['status']='correction_requested'
    write(state_path(cache),state)
    return dict(status=state['status'],index=index,old_approval_invalidated=True)


def same_rgba(actual,expected,tolerance=2):
    a=np.asarray(actual.convert('RGBA')).astype(int);b=np.asarray(expected.convert('RGBA')).astype(int)
    if tolerance==0:return bool(np.array_equal(a,b))
    if a.shape!=b.shape or np.max(np.abs(a[:,:,3]-b[:,:,3]))>tolerance:return False
    visible=b[:,:,3]>0
    return bool(np.max(np.abs(a[:,:,:3][visible]-b[:,:,:3][visible]),initial=0)<=tolerance)


def job_key(job):
    return (job['style'],job['layer_name'])


def verify(plan,paths,cached,hd_styles=None):
    from psd_tools import PSDImage
    checks=[]
    for group in plan['styles']:
        expected=[]
        for job in group['images']:
            png=Image.open(paths[job['transparent']]).convert('RGBA');jpg=Image.open(paths[job['white']]).convert('RGB')
            sizes={kind:engine.verify_image_file(paths[job[kind]]) for kind in ('white','transparent')}
            exact=cached[job_key(job)]
            if not same_rgba(png,exact,0) or png.size!=(800,800) or jpg.size!=(800,800):raise RuntimeError('PNG与确认图层不一致')
            if jpg.size!=(800,800) or any(min(jpg.getpixel(p))<250 for p in ((0,0),(799,0),(0,799),(799,799))):raise RuntimeError('JPG尺寸或白底检查失败')
            error=float(np.mean(np.abs(np.asarray(jpg).astype(float)-np.asarray(quality.composite(exact,'white')).astype(float))))
            if error>5:raise RuntimeError('JPG与确认版差异超过编码容差')
            checks.append(dict(file=job['transparent'],png_exact=True,jpg_mean_error=error,image_sizes=sizes));expected.append(png)
        names=[j['layer_name'] for j in group['images']]
        if hd_styles is not None:
            for kind in ('white','transparent'):
                details=hd_mask_psd.verify(paths[group['psd'][kind]],hd_styles[group['style']],transparent=kind=='transparent')
                checks.append(dict(file=group['psd'][kind],layers_reopened_and_compared=True,hd_mask_verification=details))
            continue
        for kind in ('white','transparent'):
            psd=PSDImage.open(paths[group['psd'][kind]]);white=kind=='white'
            products=list(psd)[1:] if white else list(psd)
            if psd.size!=(800,800) or [l.name for l in psd]!=(['背景'] if white else [])+names:raise RuntimeError('PSD图层名称或尺寸不一致')
            if [p.visible for p in products]!=[True]+[False]*(len(products)-1) or (white and not psd[0].visible):raise RuntimeError('PSD默认可见性错误')
            first=Image.new('RGBA',(800,800),'white') if white else Image.new('RGBA',(800,800))
            first.alpha_composite(expected[0])
            if not same_rgba(psd.composite(),first):raise RuntimeError('PSD保存的默认合成图与确认版不一致')
            if not white and (psd.channels!=4 or psd._record.layer_and_mask_information.layer_info.layer_count!=-len(products)):
                raise RuntimeError('透明PSD的合并透明通道错误')
            for index,png in enumerate(expected):
                for n,layer in enumerate(products):layer.visible=n==index
                exp=Image.new('RGBA',(800,800),'white') if white else Image.new('RGBA',(800,800))
                exp.alpha_composite(png)
                if not same_rgba(psd.composite(force=True),exp):raise RuntimeError('PSD独立图层透明合成与确认版不一致')
                if tuple(products[index].bbox)!=tuple(png.getchannel('A').getbbox()):raise RuntimeError('PSD图层位置与确认版不一致')
            checks.append(dict(file=group['psd'][kind],layers_reopened_and_compared=True))
    return checks


def export(spec,cache,approval,manifest=None):
    state=load_checked(cache);plan=plan_for(spec);auth=read(approval)
    if identity(plan)!=state['identity']:raise RuntimeError('导出任务单与已确认版本不一致')
    check_approval(state,auth)
    if quality.sha(state['preview'])!=auth.get('preview_sha256'):raise RuntimeError('确认预览被更改')
    manifest=engine.auxiliary_path(manifest,plan) if manifest else None
    stage=Path(tempfile.mkdtemp(prefix='export-',dir=Path(cache)))
    compression={}
    staged={};cached={job_key(i):Image.open(i['selected']['path']).convert('RGBA') for i in state['items']}
    items_by_key={job_key(i):i for i in state['items']};hd_styles={}
    try:
        for group in plan['styles']:
            layers=[]
            entries=[]
            for index,job in enumerate(group['images']):
                im=cached[job_key(job)];box=im.getchannel('A').getbbox()
                for kind,image in [('white',quality.composite(im,'white')),('transparent',im)]:
                    destination=job[kind];temporary=stage/(str(len(staged))+Path(destination).suffix)
                    compression[destination]=engine.save_limited_image(image,temporary,kind);staged[destination]=temporary
                layers.append((job['layer_name'],im.crop(box),box[0],box[1],index==0))
                item=items_by_key[job_key(job)]
                entries.append(dict(name=job['layer_name'],source=checked_image(item['source_cache'],cache,'原始素材'),
                    subject=checked_image(item['selected']['native'],cache,'高清候选'),fill=job['fill'],visible=index==0))
            hd_assets=hd_mask_psd.build_style_assets(entries);hd_styles[group['style']]=hd_assets
            background=('背景',Image.new('RGBA',(800,800),'white'),0,0,True)
            for kind,stack in [('white',[background,*layers]),('transparent',layers)]:
                destination=group['psd'][kind];temporary=stage/(str(len(staged))+'.psd')
                engine.write_psd(temporary,stack,transparent=kind=='transparent',hd_assets=hd_assets);staged[destination]=temporary
        verified=verify(plan,staged,cached,hd_styles)
        check_approval(load_checked(cache),auth);engine.preflight(plan)
        for destination in plan['outputs']:
            target=Path(destination);target.parent.mkdir(parents=True,exist_ok=True)
            with staged[destination].open('rb') as source,target.open('xb') as sink:shutil.copyfileobj(source,sink)
        verified=verify(plan,{p:Path(p) for p in plan['outputs']},cached,hd_styles)
        check_approval(load_checked(cache),auth)
        result=dict(plan,passed=True,quality_version=quality.VERSION,approval=auth,verification=verified,
                    max_image_bytes=engine.MAX_IMAGE_BYTES,image_compression=compression,
                    psd_source_mode='high_resolution_pixels_with_editable_masks',
                    psd_source_metadata={style:assets['metadata'] for style,assets in hd_styles.items()},
                    output_sha256={p:quality.sha(p) for p in plan['outputs']},cache=str(Path(cache).resolve()))
        if manifest:write(manifest,result,True)
        state.update(status='export_verified',formal_files_written=len(plan['outputs']),output_sha256=result['output_sha256'])
        write(state_path(cache),state);shutil.rmtree(stage)
        return result
    except Exception as error:
        raise RuntimeError(f'批次未完整完成；保留现场 {stage}；原因 {error}') from error


def main():
    ap=argparse.ArgumentParser(description=__doc__);sub=ap.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('plan');p.add_argument('--spec',required=True)
    p=sub.add_parser('preview');p.add_argument('--spec',required=True);p.add_argument('--cache',required=True);p.add_argument('--out');p.add_argument('--limit',type=int,default=0);p.add_argument('--offset',type=int,default=0)
    p=sub.add_parser('review');p.add_argument('--cache',required=True);p.add_argument('--decisions',required=True)
    p=sub.add_parser('choose');p.add_argument('--cache',required=True);p.add_argument('--index',type=int,required=True);p.add_argument('--candidate',required=True)
    p=sub.add_parser('approve');p.add_argument('--cache',required=True);p.add_argument('--actor',required=True);p.add_argument('--evidence',required=True)
    p=sub.add_parser('feedback');p.add_argument('--cache',required=True);p.add_argument('--index',type=int,required=True);p.add_argument('--evidence',required=True)
    p=sub.add_parser('batch');p.add_argument('--spec',required=True);p.add_argument('--cache',required=True);p.add_argument('--approval',required=True);p.add_argument('--manifest')
    p=sub.add_parser('queue');p.add_argument('--file',required=True);p.add_argument('--task',required=True)
    sub.add_parser('idle')
    a=ap.parse_args()
    if a.cmd=='plan':result=plan_for(a.spec)
    elif a.cmd=='preview':result=prepare(a.spec,a.cache,a.out,a.offset,a.limit)
    elif a.cmd=='review':result=review(a.cache,a.decisions)
    elif a.cmd=='choose':result=choose(a.cache,a.index,a.candidate)
    elif a.cmd=='approve':result=approve(a.cache,a.evidence,a.actor)
    elif a.cmd=='feedback':result=feedback(a.cache,a.index,a.evidence)
    elif a.cmd=='batch':result=export(a.spec,a.cache,a.approval,a.manifest)
    elif a.cmd=='queue':engine.queue_add(json.loads(a.task),a.file);result=dict(status='pending')
    elif a.cmd=='idle':result=dict(idle_seconds=engine.idle_seconds())
    print(json.dumps(result,ensure_ascii=False,indent=2))
