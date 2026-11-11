"""Fixed grouped-PSD delivery, using uncompressed render caches instead of JPG pixels."""
import hashlib
import io
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from PIL import Image

from layered_psd import write_layered_psd
from user_profile import file_hash, write_json


def group_jobs(jobs):
    marked=[bool(job.get('_delivery')) for job in jobs]
    if not any(marked):return {}
    if not all(marked):raise ValueError('数据包任务不能混入未声明交付规则的图片')
    groups={};styles=set();sources={}
    for position,job in enumerate(jobs):
        meta=job['_delivery']
        required={'style_id','kind','size','index','layer_name','psd_path','source_count'}
        if not required.issubset(meta):raise ValueError('缺少数据包分组信息')
        if meta['kind'] not in ('main','scene'):raise ValueError('本版仅主图/场景图，白底图操作未启用')
        styles.add(meta['style_id'])
        if type(meta['source_count']) is not int or meta['source_count']<1:
            raise ValueError('数据包源图数量无效')
        if type(meta['index']) is not int or not 1<=meta['index']<=meta['source_count']:
            raise ValueError('数据包图片序号无效')
        if meta['layer_name']!=str(meta['index']):raise ValueError('图层必须按原图顺序命名1—N')
        size=meta['size']
        try:
            width,height=map(int,size.split('x'))
        except (AttributeError,ValueError):
            raise ValueError('数据包人工输入尺寸无效') from None
        if not (1<=width<=10000 and 1<=height<=10000) or job['size']!=size:
            raise ValueError('数据包尺寸与已确认规格不符')
        if job.get('psd') or job.get('format') not in ('jpg','png'):
            raise ValueError('数据包图片仅JPG/PNG，PSD必须按款式和尺寸汇总')
        if type(job.get('max_bytes')) is not int or not 1<=job['max_bytes']<=500000:
            raise ValueError('数据包图片必须设置不超过500000字节')
        folder=Path(job['out_dir']).resolve();psd=Path(meta['psd_path']).resolve()
        if folder.name!=size or folder.parent.name!='图片' or psd.parent!=folder.parent.parent/'源文件' or psd.suffix.lower()!='.psd':
            raise ValueError('交付须分为图片/尺寸和源文件两个目录')
        key=str(psd)
        group=groups.setdefault(key,{'path':psd,'size':tuple(map(int,size.split('x'))),
                                     'source_count':meta['source_count'],'indices':[],'names':[],
                                     'source_type':meta.get('source_type','photos')})
        if group['source_type']!=meta.get('source_type','photos'):raise ValueError('一个PSD不能混合照片与主图PSD源')
        if group['size']!=tuple(map(int,size.split('x'))) or group['source_count']!=meta['source_count']:
            raise ValueError('同一个PSD混入不同尺寸或款式')
        group['indices'].append(position);group['names'].append(meta['layer_name'])
        identity=(str(Path(job['input']).resolve()),tuple(job.get('source_layers') or []))
        previous=sources.setdefault(meta['index'],identity)
        if previous!=identity:raise ValueError('不同尺寸的同一序号不是同一原图及图层选择')
    if len(styles)!=1:raise ValueError('一份数据包仅一个款号，多个款号请分别建单')
    for group in groups.values():
        if len(group['indices'])!=group['source_count'] or set(group['names'])!={str(i) for i in range(1,group['source_count']+1)}:
            raise ValueError('PSD组缺少图片或图片序号重复')
        ordered=sorted(zip(group['indices'],group['names']),key=lambda pair:int(pair[1]))
        group['indices'],group['names']=map(list,zip(*ordered))
    return groups


def preflight_groups(groups, batch_record, state_root=None):
    existing=batch_record.get('grouped_psds',{})
    for key,group in groups.items():
        path=group['path'];entry=existing.get(key,{})
        if entry.get('status')=='completed':
            if not path.is_file() or file_hash(path)!=entry['sha256']:
                raise ValueError('已完成PSD变化或缺失，不能续跑：'+key)
        elif entry.get('status')=='pending_publication':
            _pending_publication(group,entry,batch_record,state_root=state_root)
        elif path.exists():raise ValueError('PSD目标已存在但不属于本批成功记录，拒绝覆盖：'+key)
        ancestor=path.parent
        while not ancestor.exists():ancestor=ancestor.parent
        if not ancestor.is_dir():raise ValueError('PSD目录被文件阻挡：'+str(ancestor))


def _verified_metadata(metadata,group):
    if not isinstance(metadata,dict) or tuple(metadata.get('size',[]))!=group['size']:
        raise ValueError('PSD暂存验证尺寸不符')
    if metadata.get('panel_order')!=group['names']:
        raise ValueError('PSD暂存验证图层/组名称不符')
    verified=(metadata.get('native_structure_verified') is True if group['source_type']=='psd'
              else metadata.get('verified') is True)
    if not verified:
        raise ValueError('PSD暂存缺少实际图层/原生结构验证，不发布')


def _pending_publication(group,entry,record,*,state_root=None):
    """Only a prior, hash-bound verified stage may explain an existing target."""
    stage_root=record.get('grouped_staging_root')
    if not stage_root or entry.get('destination')!=str(group['path']):
        raise ValueError('PSD待发布检查点与交付目标不一致')
    stage_root=Path(stage_root).resolve();stage=Path(entry.get('staged_path','')).resolve()
    if state_root is not None:
        expected=Path(state_root).resolve()/'batches'/record['id']/'grouped-psd-staging'
        if stage_root!=expected:
            raise ValueError('PSD暂存检查点不属于本账号本批隔离目录')
    if stage.parent!=stage_root or stage.suffix.lower()!='.psd' or stage.is_symlink():
        raise ValueError('PSD暂存检查点路径越界')
    digest=entry.get('sha256')
    if not isinstance(digest,str) or len(digest)!=64 or not stage.is_file() or file_hash(stage)!=digest:
        raise ValueError('PSD已验证暂存版本缺失或哈希变化，不能恢复发布')
    _verified_metadata(entry.get('metadata'),group)
    if entry['metadata'].get('sha256')!=digest:
        raise ValueError('PSD验证报告与暂存版本哈希不一致')
    if tuple(entry.get('size',[]))!=group['size'] or entry.get('layer_names')!=group['names']:
        raise ValueError('PSD待发布检查点规格变化')
    target=group['path']
    if target.is_symlink() or (target.exists() and (not target.is_file() or file_hash(target)!=digest)):
        raise ValueError('PSD目标已存在且不匹配可信暂存版本，拒绝覆盖：'+str(target))
    return stage


def _publish_group(stage,target,digest):
    """Publish beside target volume, with atomic no-replace and exact reuse."""
    target=Path(target)
    if target.exists():
        if target.is_file() and not target.is_symlink() and file_hash(target)==digest:return
        raise ValueError('PSD目标已存在且与本批可信暂存不一致，拒绝覆盖')
    target.parent.mkdir(parents=True,exist_ok=True)
    handle,name=tempfile.mkstemp(prefix='.delivery-psd-',suffix='.psd',dir=target.parent);os.close(handle)
    temporary=Path(name)
    try:
        shutil.copyfile(stage,temporary)
        if file_hash(temporary)!=digest:raise ValueError('PSD同卷发布副本哈希不符')
        try:os.link(temporary,target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or file_hash(target)!=digest:
                raise ValueError('PSD发布时目标冲突，拒绝覆盖') from None
    finally:temporary.unlink(missing_ok=True)
    if file_hash(target)!=digest:raise ValueError('PSD发布后哈希不符')


def _save_group(store,batch_id,key,value,stage_root=None):
    with store.lock():
        current=store.batch_record(batch_id)
        current.setdefault('grouped_psds',{})[key]=value
        if stage_root is not None:current['grouped_staging_root']=str(stage_root)
        write_json(store.root/'batches'/(batch_id+'.json'),current)


def capture_callback(engine, cache_root, position):
    cache_root=Path(cache_root).resolve()
    path=cache_root/f'{position+1:04d}.png'
    if path.parent!=cache_root:raise ValueError('缓存路径越界')
    def capture(image):
        stream=io.BytesIO();options={}
        if image.info.get('icc_profile'):options['icc_profile']=image.info['icc_profile']
        image.save(stream,format='PNG',compress_level=1,**options)
        data=stream.getvalue();sha=hashlib.sha256(data).hexdigest()
        if path.exists():
            if file_hash(path)!=sha:raise ValueError('本批无损源缓存变化，停止：'+str(path))
        else:engine.publish_new(path,lambda temp:temp.write_bytes(data))
        return {'path':str(path),'sha256':sha,'size':list(image.size),'encoding':'lossless_png'}
    return capture


def build_groups(store,batch_id,groups):
    for key,group in groups.items():
        record=store.batch_record(batch_id)
        prior=record.get('grouped_psds',{}).get(key,{})
        if prior.get('status')=='completed':continue
        images=[]
        try:
            if prior.get('status')=='pending_publication':
                stage=_pending_publication(group,prior,record,state_root=store.root)
                pending=prior
            else:
                stage_root=(store.root/'batches'/batch_id/'grouped-psd-staging').resolve()
                expected_root=(store.root.resolve()/'batches'/batch_id/'grouped-psd-staging')
                if stage_root!=expected_root or stage_root.is_symlink():
                    raise ValueError('本批PSD隔离暂存目录异常')
                stage_root.mkdir(parents=True,exist_ok=True)
                stage=stage_root/(uuid.uuid4().hex+'.psd')
                metadata=None
            if prior.get('status')!='pending_publication' and group['source_type']=='psd':
                variants=[]
                for index in group['indices']:
                    item=record['items'][index];source=item.get('source_metadata',{})
                    if item['status']!='completed' or not source.get('variant_psd'):
                        raise ValueError('缺少保留原结构的PSD变体，拒绝从JPG重建')
                    variants.append(source)
                backends=[value.get('backend') for value in variants]
                if all(value=='python-pixel-psd' for value in backends):
                    from python_psd import group_python_psd_sources
                    metadata=group_python_psd_sources(stage,variants,names=group['names'])
                    metadata['packaging_backend']='python'
                elif all(value=='python-pixel-psd' or isinstance(value,str) and value.startswith('photoshop-') for value in backends):
                    from psd_source import group_psd_sources
                    metadata=group_psd_sources(stage,variants,names=group['names'])
                    metadata['packaging_backend']='photoshop'
                else:
                    raise ValueError('PSD变体没有明确的实际处理后端，不能猜测或自动降级')
                metadata['render_backends']=backends
            elif prior.get('status')!='pending_publication':
                for index in group['indices']:
                    item=record['items'][index]
                    cache=item.get('source_cache')
                    if item['status']!='completed' or not cache or file_hash(cache['path'])!=cache['sha256']:
                        raise ValueError('PSD缺少已完成图片的无损源缓存')
                    with Image.open(cache['path']) as opened:
                        if opened.size!=group['size']:raise ValueError('PSD无损源缓存尺寸不符')
                        images.append(opened.copy())
                metadata=write_layered_psd(stage,images,names=group['names'],visible_index=0)
                metadata['packaging_backend']='python'
            if prior.get('status')!='pending_publication':
                _verified_metadata(metadata,group)
                digest=file_hash(stage)
                if metadata.get('sha256')!=digest:
                    raise ValueError('PSD生成后至检查点前暂存文件变化，停止发布')
                pending={'status':'pending_publication','outputs':[],'destination':key,'staged_path':str(stage),
                         'sha256':digest,'size':list(group['size']),
                         'layer_names':group['names'],'metadata':metadata}
                # The trusted verified-stage checkpoint must reach disk before any final PSD.
                _save_group(store,batch_id,key,pending,stage_root)
            _publish_group(stage,group['path'],pending['sha256'])
            metadata=dict(pending['metadata']);metadata['path']=key
            value={**pending,'status':'completed','outputs':[key],'metadata':metadata}
            value.pop('error',None)
            _save_group(store,batch_id,key,value)
        except Exception as error:
            current=store.batch_record(batch_id)
            checkpoint=current.get('grouped_psds',{}).get(key,{})
            if checkpoint.get('status')=='pending_publication':
                value={**checkpoint,'error':str(error)}
                if group['path'].is_file() and file_hash(group['path'])==checkpoint['sha256']:
                    value['published_outputs']=[key]
            elif checkpoint.get('status')=='completed':
                # An uncertain write may have committed before raising. Preserve
                # that verified receipt rather than losing its publication proof.
                value={**checkpoint}
                value.setdefault('publication_warnings',[]).append(str(error))
            else:
                value={'status':'failed','outputs':[],'error':str(error),'size':list(group['size'])}
            _save_group(store,batch_id,key,value)
            raise
        finally:
            for image in images:image.close()


def clean_caches(record,cache_root):
    root=Path(cache_root).resolve()
    for item in record['items']:
        cache=item.get('source_cache')
        if not cache:continue
        path=Path(cache['path']).resolve()
        if path.parent!=root or path.suffix!='.png':raise ValueError('拒绝清理本批缓存目录外的文件')
        if path.exists() and file_hash(path)==cache['sha256']:path.unlink()
