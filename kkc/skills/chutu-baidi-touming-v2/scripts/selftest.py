"""Isolated synthetic acceptance; no user-product acceptance is fabricated."""
import argparse,copy,hashlib,json,os,sys,traceback
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--skill',required=True);ap.add_argument('--work',required=True);a=ap.parse_args()
    skill=Path(a.skill).resolve();work=Path(a.work).resolve();work.mkdir(parents=True,exist_ok=False)
    config=json.loads((skill/'runtime.json').read_text(encoding='utf-8-sig'))
    os.environ['NUMBA_DISABLE_JIT']='1';os.environ['U2NET_HOME']=config['model_dir'];os.environ['OMP_NUM_THREADS']='2'
    sys.path.insert(0,str(skill/'scripts'))
    import quality_pipeline as pipe
    import edge_quality as edge
    import local_masks
    checks=[];report=dict(passed=False,checks=checks,model_inference=False,work=str(work))
    def check(name,value,detail=None):
        checks.append(dict(name=name,passed=bool(value),detail=detail));print(('PASS ' if value else 'FAIL ')+name,flush=True)
        if not value:raise AssertionError(name)
    def rejects(name,fn,absent=None):
        error=None
        try:fn()
        except (ValueError,RuntimeError,FileNotFoundError,FileExistsError,KeyError) as e:error=str(e)
        check(name,error is not None and (absent is None or not absent.exists()),error)
    def store(name,value):
        p=work/(name+'.json');pipe.write(p,value);return p
    def attest(cache):
        s=pipe.load_checked(cache)
        decision=store('review-'+Path(cache).name,dict(reviewer='isolated synthetic selftest',items=[dict(index=i['index'],status='passed',note='Synthetic fixture only; test authorization, not a claim of real visual acceptance.') for i in s['items']]))
        pipe.review(cache,decision)
        return pipe.approve(cache,'Synthetic test fixture explicitly authorized for isolated selftest','selftest')['approval']
    try:
        check('account-specific Python',Path(sys.executable).resolve()==Path(config['python']).resolve())
        source=work/'src';source.mkdir();inputs=[]
        for i,color in enumerate([(160,70,120),(30,120,180),(230,170,50),(50,160,90),(170,90,30)]):
            im=Image.new('RGBA',(360,520));d=ImageDraw.Draw(im);d.rounded_rectangle((70,35,280,480),25,fill=(*color,255));d.line((280,170,325,240),fill=(*color,255),width=3)
            p=source/f'{i}.png';im.save(p);inputs.append(p)
        hashes={str(p):edge.sha(p) for p in inputs}
        halo=Image.new('RGBA',(800,800));d=ImageDraw.Draw(halo);d.rectangle((200,100,600,700),fill=(70,70,70,255));d.rectangle((204,104,596,696),fill=(235,200,210,255))
        black=Image.new('RGBA',(800,800));ImageDraw.Draw(black).rectangle((200,100,600,700),fill=(15,15,15,255))
        check('dark rim fixture raises suspicion','suspected_dark_rim' in edge.analyze(halo)['flags'])
        check('genuine black product not flagged as black rim','suspected_dark_rim' not in edge.analyze(black)['flags'])
        protected=Image.new('L',halo.size);ImageDraw.Draw(protected).rectangle((190,90,220,710),fill=255)
        fixed,guard=edge.repair(halo,2,1,protected)
        mask=np.asarray(protected)>0
        check('explicit protection pixels unchanged',np.array_equal(np.asarray(fixed)[mask],np.asarray(halo)[mask]) and guard['protected_details_unchanged'])
        check('opaque interior preserved',guard['core_unchanged'])
        soft=Image.new('RGBA',(800,800));sd=ImageDraw.Draw(soft)
        sd.rectangle((200,100,600,700),fill=(20,30,40,180));sd.rectangle((207,107,593,693),fill=(210,180,150,255))
        for number in (1,2):
            cleaned,meta=edge.repair(soft,number,1,protected)
            old=np.asarray(soft).astype(int);new=np.asarray(cleaned).astype(int)
            check(f'color round {number} preserves exact alpha',meta['alpha_unchanged'] and np.array_equal(new[:,:,3],old[:,:,3]))
            check(f'color round {number} is bounded and actually edits',meta['modified_pixels']>0 and np.max(abs(new[:,:,:3]-old[:,:,:3]))<=meta['max_channel_delta'])
            check(f'color round {number} protects explicit region',np.array_equal(new[mask],old[mask]))
        original=Image.new('RGBA',(40,40),(80,130,190,255));cut=original.copy();cut.putpixel((10,10),(0,0,0,0))
        keep=Image.new('L',(40,40));keep.putpixel((10,10),255)
        remove=Image.new('L',(40,40));remove.putpixel((20,20),255);remove.putpixel((21,20),128)
        edited,edit_protect,edit_meta=local_masks.apply(cut,original,{'keep_mask':keep,'remove_mask':remove})
        check('keep mask restores source RGBA',edited.getpixel((10,10))==original.getpixel((10,10)))
        check('remove mask supports full and partial alpha',edited.getpixel((20,20))[3]==0 and edited.getpixel((21,20))[3]==127)
        check('explicit local edits leave all other pixels intact',edit_meta['outside_edit_masks_unchanged'] and edited.getpixel((30,30))==cut.getpixel((30,30)))
        check('keep mask also protects later color repair',edit_protect.getpixel((10,10))==255)
        wrong=work/'wrong-size.png';Image.new('L',(2,2),255).save(wrong)
        rejects('wrong-size local mask rejected',lambda:local_masks.load({'remove_mask':str(wrong)},(40,40)))
        overlap=work/'overlap.png';keep.save(overlap)
        rejects('ambiguous keep and delete overlap rejected',lambda:local_masks.load({'keep_mask':str(overlap),'remove_mask':str(overlap)},(40,40)))
        qa=edge.analyze(soft,[[450,200,600,350]])
        diagnostic=edge.diagnostics(soft,qa,pipe.engine._font(16));box=edge.diagnostic_boxes(soft,qa)[0]
        for col,color in [(1,'white'),(2,(80,80,80,255)),(3,'black')]:
            patch=diagnostic.crop((col*320,400,col*320+320,720))
            check(f'100 percent crop {col} uses same native pixels',np.array_equal(np.asarray(patch),np.asarray(edge.composite(soft.crop(box),color))))
        check('explicit inspection region is prioritized',box==(365,115,685,435))
        fragments=halo.copy();ImageDraw.Draw(fragments).rectangle((700,700,710,710),fill=(30,30,30,255))
        check('detached foreground triggers review','suspected_detached_detail_or_background' in edge.analyze(fragments)['flags'])
        for separate in (True,False):
            for counts in ((3,),(2,3)):
                tag=('separate' if separate else 'together')+'-'+'-'.join(map(str,counts));jobs=[];cursor=0
                for s,count in enumerate(counts):
                    for n in range(count):
                        jobs.append(dict(style='Style'+str(s),color='Color'+str(cursor),input=str(inputs[cursor])));cursor+=1
                spec=store(tag,dict(defaults=dict(out_dir=str(work/(tag+'-formal')),separate_image_folders=separate),jobs=jobs))
                cache=work/(tag+'-cache');result=pipe.prepare(spec,cache)
                check(tag+' preview zero formal files',result['formal_files_written']==0 and not (work/(tag+'-formal')).exists())
                state=pipe.load_checked(cache)
                check(tag+' alpha inputs preserved without repair',all(i['reused_existing_alpha'] and not i['attempts'] for i in state['items']))
                rejects(tag+' cannot approve before visual review',lambda:pipe.approve(cache,'test','selftest'))
                rejects(tag+' cannot export without approval',lambda:pipe.export(spec,cache,cache/'missing.json'),work/(tag+'-formal'))
                auth=attest(cache);manifest=work/(tag+'-files.json');exported=pipe.export(spec,cache,auth,manifest)
                expected=2*sum(counts)+2*len(counts)
                actual=[p for p in Path(exported['out_dir']).rglob('*') if p.is_file()]
                check(tag+' correct 2N+2K and reopened PSDs',exported['passed'] and len(actual)==expected and len(exported['verification'])==sum(counts)+2*len(counts))
                check(tag+' images within 500KB',all(Path(j[k]).stat().st_size<=500_000 for j in exported['jobs'] for k in ('white','transparent')))
                check(tag+' saved manifest agrees',pipe.read(manifest)==exported)
                before={str(p):edge.sha(p) for p in actual}
                rejects(tag+' existing outputs never overwritten',lambda:pipe.export(spec,cache,auth))
                check(tag+' existing output hashes unchanged',before=={str(p):edge.sha(p) for p in actual})
        spec=store('binding',dict(defaults=dict(out_dir=str(work/'binding-formal'),separate_image_folders=True,fill=.7),jobs=[dict(style='Angle',color='Pink',angle='front',input=str(inputs[0])),dict(style='Angle',color='Pink',angle='side',fill=.8,input=str(inputs[0]))]))
        cache=work/'binding-cache';pipe.prepare(spec,cache);auth=attest(cache)
        raw=inputs[0].read_bytes();inputs[0].write_bytes(raw+b'changed')
        rejects('source changes invalidate approval',lambda:pipe.export(spec,cache,auth),work/'binding-formal');inputs[0].write_bytes(raw)
        state=pipe.load_checked(cache);png=Path(state['items'][0]['selected']['path']);raw=png.read_bytes();png.write_bytes(raw+b'changed')
        rejects('cached render tampering invalidates approval',lambda:pipe.export(spec,cache,auth),work/'binding-formal');png.write_bytes(raw)
        changed=pipe.read(spec);changed['defaults']['fill']=.8;other=store('changed-settings',changed)
        rejects('parameter changes invalidate approval',lambda:pipe.export(other,cache,auth),work/'binding-formal')
        pipe.choose(cache,1,'initial')
        rejects('choosing candidate resets visual review',lambda:pipe.approve(cache,'test','selftest'))
        rejects('previous confirmation invalid after selection change',lambda:pipe.export(spec,cache,auth),work/'binding-formal')
        auth=attest(cache)
        exported=pipe.export(spec,cache,auth)
        check('same color angles and 70 percent supported',len(exported['jobs'])==2 and [j['layer_name'] for j in exported['jobs']]==['Pink-front','Pink-side'])
        sizes=[]
        for j in exported['jobs']:
            with Image.open(j['transparent']) as im:
                box=im.getchannel('A').getbbox();sizes.append(max(box[2]-box[0],box[3]-box[1]))
        check('same source with different parameters keeps independent approved renders',sizes==[560,640],sizes)
        spec2=store('partial',dict(defaults=dict(out_dir=str(work/'partial-formal'),separate_image_folders=True),jobs=[dict(style='A',color=str(i),input=str(p)) for i,p in enumerate(inputs[:3])]))
        partial=work/'partial-cache';pipe.prepare(spec2,partial,limit=2)
        decision=store('partial-review',dict(reviewer='selftest',items=[dict(index=i,status='passed',note='Synthetic test only') for i in (1,2,3)]));pipe.review(partial,decision)
        rejects('partial preview cannot approve full batch',lambda:pipe.approve(partial,'test','selftest'))
        bad=pipe.read(spec2);bad['jobs'][1]['color']='0';badpath=store('duplicate',bad)
        rejects('duplicate output names blocked',lambda:pipe.plan_for(badpath),work/'partial-formal')
        bad=pipe.read(spec2);bad['jobs'][0]['color']='CON';badpath=store('reserved',bad)
        rejects('Windows reserved names blocked',lambda:pipe.plan_for(badpath))
        fail_spec=store('failure',dict(defaults=dict(out_dir=str(work/'failure-formal'),separate_image_folders=False),jobs=[dict(style='A',color='B',input=str(inputs[0]))]))
        failcache=work/'failure-cache';pipe.prepare(fail_spec,failcache);failauth=attest(failcache)
        writer=pipe.engine.write_psd
        def broken(*args,**kwargs):raise RuntimeError('injected PSD failure')
        pipe.engine.write_psd=broken
        rejects('PSD failure writes no formal outputs',lambda:pipe.export(fail_spec,failcache,failauth),work/'failure-formal');pipe.engine.write_psd=writer
        check('failed export preserves staging',bool(list(failcache.glob('export-*'))))
        pipe.feedback(failcache,1,'Synthetic human reports rim defect')
        rejects('human rejection invalidates old approval',lambda:pipe.export(fail_spec,failcache,failauth),work/'failure-formal')
        # Explicit mask paths/content, previews and code are all bound before export.
        mask_remove=Image.new('L',(360,520));ImageDraw.Draw(mask_remove).rectangle((140,180,170,220),fill=255)
        remove_path=source/'remove.png';mask_remove.save(remove_path)
        keep_path=source/'keep.png';Image.new('L',(360,520)).save(keep_path)
        protect_path=source/'protect.png';Image.new('L',(360,520)).save(protect_path)
        mask_spec=store('local-masks',dict(defaults=dict(out_dir=str(work/'masks-formal'),separate_image_folders=True),
            jobs=[dict(style='A',color='B',input=str(inputs[0]),remove_mask=str(remove_path),keep_mask=str(keep_path),protect_mask=str(protect_path),review_regions=[[300,300,500,500]])]))
        mask_cache=work/'masks-cache';pipe.prepare(mask_spec,mask_cache);mask_auth=attest(mask_cache)
        state=pipe.load_checked(mask_cache)
        check('explicit mask metadata kept in cache',state['items'][0]['local_edits']['removed_alpha_pixels']>0)
        for name,path in [('remove',remove_path),('keep',keep_path),('protect',protect_path),('preview',Path(state['preview'])),('diagnostic',Path(state['items'][0]['diagnostic']))]:
            raw=path.read_bytes();path.write_bytes(raw+b'changed')
            rejects(name+' changes invalidate bound confirmation',lambda:pipe.export(mask_spec,mask_cache,mask_auth),work/'masks-formal')
            path.write_bytes(raw)
        raw=mask_spec.read_bytes();mask_spec.write_bytes(raw+b' ')
        rejects('changing original task file invalidates confirmation',lambda:pipe.load_checked(mask_cache));mask_spec.write_bytes(raw)
        fingerprint=pipe.processor_fingerprint
        pipe.processor_fingerprint=lambda:'changed processing code'
        rejects('processing code update invalidates cache',lambda:pipe.load_checked(mask_cache));pipe.processor_fingerprint=fingerprint
        initial=pipe.read(mask_auth)['binding']
        pipe.review(mask_cache,store('mask-review-again',dict(reviewer='selftest',items=[dict(index=1,status='passed',note='Synthetic review changed; old authorization must expire')])))
        rejects('re-review invalidates previous authorization',lambda:pipe.export(mask_spec,mask_cache,mask_auth),work/'masks-formal')
        mask_auth=attest(mask_cache)
        cutout=pipe.engine.cutout
        def no_inference(*args,**kwargs):raise AssertionError('Export attempted to rerun segmentation')
        pipe.engine.cutout=no_inference
        mask_result=pipe.export(mask_spec,mask_cache,mask_auth)
        pipe.engine.cutout=cutout
        with Image.open(mask_result['jobs'][0]['transparent']) as actual,Image.open(state['items'][0]['selected']['path']) as expected:
            check('export reuses cached RGBA without any inference',np.array_equal(np.asarray(actual.convert('RGBA')),np.asarray(expected.convert('RGBA'))))
        invisible_a=Image.new('RGBA',(2,2));invisible_b=invisible_a.copy();invisible_b.putpixel((0,0),(1,0,0,0))
        check('exact PNG check includes invisible RGB',not pipe.same_rgba(invisible_a,invisible_b,0))
        print('RUN actual local u2net CPU inference',flush=True)
        opaque=Image.new('RGB',(360,520),(225,230,218));mask=Image.open(inputs[0]);opaque.paste(mask,mask=mask.getchannel('A'));p=source/'cpu.jpg';opaque.save(p)
        model_spec=store('model',dict(defaults=dict(out_dir=str(work/'model-formal'),separate_image_folders=True,cutout='rembg'),jobs=[dict(style='Model',color='Pink',input=str(p))]))
        model=pipe.prepare(model_spec,work/'model-cache')
        s=pipe.load_checked(work/'model-cache')
        check('CPU inference produced valid alpha',s['items'][0]['qa']['technical_pass'] and not s['items'][0]['reused_existing_alpha'])
        check('automatic repair bounded to two rounds',len(s['items'][0]['attempts'])<=2)
        check('model preview remains visually pending',s['items'][0]['visual_review']['status']=='pending' and not (work/'model-formal').exists())
        report['model_inference']=True
        md5=hashlib.md5((Path(config['model_dir'])/'u2net.onnx').read_bytes()).hexdigest()
        check('local upstream u2net checksum',md5=='60024c5c889badc19c04ad937298a77b',md5)
        check('source hashes preserved',hashes=={str(p):edge.sha(p) for p in inputs})
        import yaml
        meta=yaml.safe_load((skill/'SKILL.md').read_text(encoding='utf-8').split('---',2)[1])
        check('skill metadata version and name',meta['name']=='chutu-baidi-touming-v2' and meta['metadata'].get('image_pipeline_version',meta['metadata']['version'])==edge.VERSION and meta['metadata']['version']==config['skill_version'])
        report['passed']=True
    except Exception as e:
        report.update(error=str(e),traceback=traceback.format_exc());print(report['traceback'],file=sys.stderr)
    report['passed_checks']=sum(c['passed'] for c in checks);report['total_checks']=len(checks)
    (work/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['passed','passed_checks','total_checks','model_inference']},ensure_ascii=False),flush=True)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
