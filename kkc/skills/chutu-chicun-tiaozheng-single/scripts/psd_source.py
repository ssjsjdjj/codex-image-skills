"""Read-only PSD inspection and a Photoshop-native, non-flattening source backend.

psd-tools is used only to inspect structure. Native input documents are never
written by Pillow or psd-tools: PowerShell COM and a fixed JSX worker operate on
independent cache copies. PNG is only the rendered preview, never a PSD source.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from PIL import Image, ImageCms

BACKEND_VERSION = 'photoshop-native-1'
SCRIPT_ROOT = Path(__file__).resolve().parent
WORKER = SCRIPT_ROOT.parent/'assets/psd_source_worker.jsx'
BRIDGE = SCRIPT_ROOT/'run_photoshop.ps1'


class NativePSDError(RuntimeError):
    pass


class PhotoshopUnavailableError(NativePSDError):
    pass


def _configured_progid(environment=None):
    environment=os.environ if environment is None else environment
    value=environment.get('CHUTU_PHOTOSHOP_PROGID') or 'Photoshop.Application'
    if not isinstance(value,str) or not re.fullmatch(r'Photoshop\.Application(?:\.[0-9]+)?',value):
        raise ValueError('CHUTU_PHOTOSHOP_PROGID仅允许Photoshop.Application或数字版本后缀')
    return value


def _hash(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            result.update(block)
    return result.hexdigest()


def _source_path(path):
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() != '.psd' or not source.is_file():
        raise ValueError('原生PSD后端需要实际存在的.psd源文件')
    with source.open('rb') as stream:
        signature = stream.read(6)
    if signature != b'8BPS\x00\x01':
        raise ValueError('输入不是有效PSD；不能将JPG/PNG改名冒充源文件')
    return source


def _layer_tree(document):
    def visit(layer):
        item = {'name':layer.name, 'kind':layer.kind, 'visible':bool(layer.visible),
                'mask':bool(layer.has_mask()), 'vector_mask':bool(layer.has_vector_mask())}
        if layer.is_group():
            item['children'] = [visit(child) for child in layer]
        if layer.kind == 'smartobject':
            try:
                item['smart_object_kind'] = layer.smart_object.kind
            except Exception:
                item['smart_object_kind'] = 'unknown'
        return item
    # psd-tools iteration is bottom-to-top; expose panel order consistently.
    def reverse_tree(items):
        result = list(reversed(items))
        for item in result:
            if 'children' in item:
                item['children'] = reverse_tree(item['children'])
        return result
    return reverse_tree([visit(layer) for layer in document])


def inspect_source(path):
    """Return metadata without rasterizing or modifying the native PSD."""
    from psd_tools import PSDImage
    from psd_tools.constants import Resource

    source = _source_path(path)
    before = _hash(source)
    document = PSDImage.open(source)
    tree = _layer_tree(document)
    counts = {'layers':0, 'groups':0, 'text':0, 'smart_objects':0, 'masks':0, 'vector_masks':0}
    linked = []
    def count(items):
        for item in items:
            counts['layers'] += 1
            counts['groups'] += int(item['kind']=='group')
            counts['text'] += int(item['kind']=='type')
            counts['smart_objects'] += int(item['kind']=='smartobject')
            counts['masks'] += int(item['mask'])
            counts['vector_masks'] += int(item['vector_mask'])
            if item.get('smart_object_kind') in ('external','alias'):linked.append(item['name'])
            count(item.get('children', []))
    count(tree)
    profile = document.image_resources.get_data(Resource.ICC_PROFILE)
    if _hash(source) != before:
        raise NativePSDError('读取期间源PSD发生变化，停止')
    return {'path':str(source), 'size':list(document.size), 'depth':document.depth,
            'color_mode':document.color_mode.name, 'sha256':before,
            'icc_sha256':hashlib.sha256(profile).hexdigest() if profile else None,
            'native_structure':tree, 'structure':tree, 'counts':counts,
            'linked_smart_objects':linked,
            'quality':{'native_size':list(document.size), 'raster_layers_present':counts['layers']>counts['groups']+counts['text']}}


def _canonical_structure(items):
    # Visibility is preserved within each source. IDs, geometry and type sizes
    # legitimately change during native resizing and are not structure keys.
    return [{'name':item['name'], 'kind':item['kind'], 'visible':item['visible'],
             'mask':item['mask'], 'vector_mask':item['vector_mask'],
             'smart_object_kind':item.get('smart_object_kind'),
             'children':_canonical_structure(item.get('children', []))} for item in items]


def _reject_external(source):
    if source.get('linked_smart_objects'):
        raise ValueError('源PSD含外链智能对象；请先在原PSD中嵌入或人工补齐并确认资源，再处理，不能复制到缓存后静默丢链')


def _invoke_photoshop(request, directory, *, timeout=180):
    progid=_configured_progid()
    if os.name != 'nt':
        raise PhotoshopUnavailableError('原生PSD处理仅支持Windows Photoshop；不降级为平面图')
    powershell = shutil.which('powershell.exe')
    if not powershell:
        raise PhotoshopUnavailableError('找不到Windows PowerShell；无法调用Photoshop原生后端')
    if not BRIDGE.is_file() or not WORKER.is_file():
        raise NativePSDError('缺少固定Photoshop桥接脚本或JSX worker')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    request_path, response_path = directory/'request.json', directory/'response.json'
    request = copy.deepcopy(request)
    request['response_path'] = str(response_path)
    request['photoshop_progid'] = progid
    with request_path.open('x', encoding='utf-8') as stream:
        json.dump(request, stream, ensure_ascii=True, allow_nan=False)
    command = [powershell, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(BRIDGE),
               '-RequestPath', str(request_path)]
    try:
        result = subprocess.run(command, shell=False, capture_output=True, encoding='utf-8',
                                errors='replace', timeout=timeout)
    except (FileNotFoundError, OSError) as exc:
        raise PhotoshopUnavailableError('Photoshop COM调用不可用，不降级：'+str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise NativePSDError('Photoshop原生调用超时；保留缓存与日志，不自动降级或关闭用户文档') from exc
    (directory/'bridge.log').write_text(result.stdout+'\n'+result.stderr, encoding='utf-8')
    if response_path.is_file():
        response = json.loads(response_path.read_text(encoding='utf-8-sig'))
        if not response.get('ok'):
            error = response.get('error', 'Photoshop原生处理失败')
            if response.get('code') == 'PHOTOSHOP_UNAVAILABLE':
                raise PhotoshopUnavailableError(error)
            raise NativePSDError(error)
    else:
        raise PhotoshopUnavailableError('Photoshop未返回原生处理结果，不降级：'+result.stderr[-2000:])
    if result.returncode:
        raise NativePSDError('Photoshop桥接进程失败：'+result.stderr[-2000:])
    if not response.get('owned_documents_closed') or not response.get('preferences_restored') or not response.get('active_document_restored'):
        raise NativePSDError('Photoshop任务文档或首选项恢复未通过验收，请检查缓存日志')
    response['bridge_progid']=progid
    return response


def _parse_size(value):
    if isinstance(value, (list, tuple)) and len(value)==2:
        parts = value
    else:
        parts = str(value).lower().replace('×','x').replace('*','x').split('x')
    try: width,height = map(int,parts)
    except (ValueError, TypeError):raise ValueError('目标size必须为有效宽x高') from None
    if not 1 <= width <= 30000 or not 1 <= height <= 30000:
        raise ValueError('PSD目标尺寸须为1~30000像素')
    return width,height


def _execution_plan(job, source, plan):
    width,height = source['size']
    target = _parse_size(job['size'])
    if plan is None:
        if any(key in job for key in ('focus','zoom','position','offset','subject_box')):
            raise ValueError('复杂构图须由正式裁切器提供plan，原生后端不猜测坐标')
        crop = job.get('crop_box',[0,0,1,1])
        if isinstance(crop,str):crop=crop.split(',')
        if len(crop)!=4:raise ValueError('crop_box需要4个坐标')
        domain = [float(crop[0])*width,float(crop[1])*height,float(crop[2])*width,float(crop[3])*height]
        plan = {'source_size':[width,height], 'source_domain_px':domain,
                'source_viewport_px':domain, 'output_size':list(target),'effective_fit':'cover','warnings':[]}
    plan = copy.deepcopy(plan)
    if plan.get('source_size') != [width,height] or plan.get('output_size') != list(target):
        raise ValueError('原生计划与源尺寸/目标尺寸不一致')
    if job.get('fit')=='stretch' or plan.get('effective_fit')=='stretch':
        raise ValueError('原生PSD后端拒绝非等比拉伸')
    viewport=plan.get('source_viewport_px',[])
    if len(viewport)!=4 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in viewport):
        raise ValueError('原生取景框必须为有限像素坐标')
    left,top,right,bottom=viewport
    if not 0<=left<right<=width or not 0<=top<bottom<=height:
        raise ValueError('原生PSD暂不支持越界补边，不能降级或拉伸')
    domain=plan.get('source_domain_px',[])
    if len(domain)!=4 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in domain):
        raise ValueError('原生计划源区域无效')
    if not 0<=domain[0]<=left<right<=domain[2]<=width or not 0<=domain[1]<=top<bottom<=domain[3]<=height:
        raise ValueError('原生取景框超出允许的源区域')
    if abs((right-left)/(bottom-top)/(target[0]/target[1])-1)>1e-6:
        raise ValueError('原生取景比例与目标冲突；请先调整裁切计划，不能静默拉伸')
    common=math.gcd(*target);unit_w,unit_h=target[0]//common,target[1]//common
    scale=math.floor(min((right-left)/unit_w,(bottom-top)/unit_h)+1e-8)
    if scale<1:raise ValueError('源取景框无法形成目标比例的整数像素裁切')
    crop_w,crop_h=unit_w*scale,unit_h*scale
    low_x,high_x=math.ceil(left-1e-8),math.floor(right-crop_w+1e-8)
    low_y,high_y=math.ceil(top-1e-8),math.floor(bottom-crop_h+1e-8)
    if low_x>high_x or low_y>high_y:raise ValueError('整数原生裁切无法落在已批准取景范围内，请调整裁切框')
    x=max(low_x,min(high_x,round((left+right-crop_w)/2)))
    y=max(low_y,min(high_y,round((top+bottom-crop_h)/2)))
    executed=[x,y,x+crop_w,y+crop_h]
    for key in ('protect_box','subject_box'):
        if key in job:
            values=job[key].split(',') if isinstance(job[key],str) else job[key]
            if len(values)!=4:raise ValueError('保护框必须为4个坐标')
            values=list(map(float,values))
            if any(not math.isfinite(v) or not 0<=v<=1 for v in values) or values[0]>=values[2] or values[1]>=values[3]:
                raise ValueError('保护框必须为有效归一化区域')
            box=[float(values[0])*width,float(values[1])*height,float(values[2])*width,float(values[3])*height]
            if box[0]<x-1e-6 or box[1]<y-1e-6 or box[2]>x+crop_w+1e-6 or box[3]>y+crop_h+1e-6:
                raise ValueError('原生整数取景会切掉保护区域，请调整裁切计划')
    plan['requested_viewport_px']=list(viewport)
    plan['source_viewport_px']=executed
    plan['native_integer_crop']=True
    return plan,target


def _publish_new(source,destination):
    destination=Path(destination)
    if destination.exists() or destination.is_symlink():raise FileExistsError('PSD交付文件已存在，不覆盖：'+str(destination))
    os.link(source,destination)


def render_psd(job, cache_root, *, plan=None):
    source=inspect_source(job['input'])
    _reject_external(source)
    if source['depth'] not in (8,16):raise ValueError('当前原生PSD预览支持8/16位，其他位深需明确转换方案')
    executed,target=_execution_plan(job,source,plan)
    root=Path(cache_root).expanduser().resolve();root.mkdir(parents=True,exist_ok=True)
    directory=root/('native-'+uuid.uuid4().hex);directory.mkdir()
    source_copy=directory/'source-copy.psd';shutil.copyfile(source['path'],source_copy)
    if _hash(source_copy)!=source['sha256']:raise NativePSDError('PSD缓存副本与源文件不一致')
    staged_psd,staged_png=directory/'variant-stage.psd',directory/'preview-stage.png'
    request={'action':'render','source_copy':str(source_copy),'variant_path':str(staged_psd),
             'preview_path':str(staged_png),'viewport':executed['source_viewport_px'],'size':list(target)}
    try:
        response=_invoke_photoshop(request,directory)
        details=inspect_source(staged_psd)
        _reject_external(details)
        if details['size']!=list(target) or details['depth']!=source['depth'] or details['color_mode']!=source['color_mode']:
            raise NativePSDError('Photoshop保存后的尺寸、位深或色彩模式不一致')
        if _canonical_structure(details['native_structure'])!=_canonical_structure(source['native_structure']):
            raise NativePSDError('Photoshop原生变体的文字/组/蒙版/智能对象结构发生非预期变化')
        with Image.open(staged_png) as opened:
            if opened.format!='PNG' or opened.size!=target:raise NativePSDError('Photoshop无损PNG预览尺寸不符')
            image=opened.copy()
        if image.mode not in ('RGB','RGBA'):raise NativePSDError('Photoshop预览不是RGB/RGBA')
        # The worker converts only its independent preview copy to sRGB.
        if not image.info.get('icc_profile'):
            image.info['icc_profile']=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        if _hash(source['path'])!=source['sha256']:raise NativePSDError('原始PSD在处理期间变化，停止，不发布')
        variant,preview=directory/'variant.psd',directory/'preview.png'
        _publish_new(staged_psd,variant);_publish_new(staged_png,preview)
        ratio=target[0]/(executed['source_viewport_px'][2]-executed['source_viewport_px'][0])
        metadata={'backend':BACKEND_VERSION,'native_psd':True,'source':source['path'],'source_sha256':source['sha256'],
                  'variant_psd':str(variant),'variant_sha256':_hash(variant),'sha256':_hash(variant),
                  'preview_png':str(preview),'preview_sha256':_hash(preview),'size':list(target),
                  'source_structure':source['native_structure'],'variant_structure':details['native_structure'],
                  'native_structure_verified':True,'source_hash_unchanged':True,'scale':ratio,
                  'upscale_risk':ratio>1+1e-7,'quality':{'upsampling':ratio>1+1e-7,'scale':ratio,
                  'note':'原生图层保留；放大不能凭空增加普通像素图层细节' if ratio>1 else '未放大源取景像素'},
                  'photoshop':response,'cache_dir':str(directory),'preview_color_space':'sRGB'}
        (directory/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        return image,executed,metadata
    finally:
        if not Path(source['path']).is_file() or _hash(source['path'])!=source['sha256']:
            raise NativePSDError('源PSD消失或被改动；保留缓存，不能声称原图未变')


def group_psd_sources(destination, variants, names=None):
    from layered_psd import _names
    variants=list(variants)
    if not variants:raise ValueError('原生PSD分组列表不能为空')
    layer_names=_names(names,len(variants))
    paths=[]
    for item in variants:
        if isinstance(item,dict):
            path=item.get('variant_psd')
            if not path:raise ValueError('原生分组需要variant_psd，不能使用JPG/PNG代替')
            actual=inspect_source(path)
            expected=item.get('variant_sha256',item.get('sha256'))
            if expected and actual['sha256']!=expected:raise NativePSDError('PSD变体哈希发生变化')
        else:
            actual=inspect_source(item)
        _reject_external(actual)
        paths.append(actual)
    first=paths[0]
    if any((p['size'],p['depth'],p['color_mode'],p['icc_sha256'])!=(first['size'],first['depth'],first['color_mode'],first['icc_sha256']) for p in paths[1:]):
        raise ValueError('原生PSD分组要求同尺寸、位深、色彩模式及ICC，不自动转换或拉伸')
    destination=Path(destination).expanduser().absolute()
    if destination.suffix.lower()!='.psd':raise ValueError('原生分组输出必须为.psd')
    if destination.exists() or destination.is_symlink():raise FileExistsError('已存在目标PSD，不覆盖')
    directory=Path(tempfile.mkdtemp(prefix='resize-native-group-'))
    copies=[]
    for index,source in enumerate(paths):
        copied=directory/f'source-{index+1}.psd';shutil.copyfile(source['path'],copied)
        if _hash(copied)!=source['sha256']:raise NativePSDError('原生分组缓存复制不一致')
        copies.append(str(copied))
    staged=directory/'grouped-stage.psd'
    try:
        response=_invoke_photoshop({'action':'group','source_copies':copies,'names':layer_names,'destination':str(staged)},directory)
        result=inspect_source(staged)
        _reject_external(result)
        tree=result['native_structure']
        if result['size']!=first['size'] or [node['name'] for node in tree]!=layer_names or any(node['kind']!='group' for node in tree):
            raise NativePSDError('原生PSD分组顺序、尺寸或组类型不符')
        for index,(group,source) in enumerate(zip(tree,paths)):
            if group['visible']!=(index==0):raise NativePSDError('原生PSD只应显示第1组')
            if _canonical_structure(group.get('children',[]))!=_canonical_structure(source['native_structure']):
                raise NativePSDError('原生分组内部结构变化：'+layer_names[index])
        for source in paths:
            if _hash(source['path'])!=source['sha256']:raise NativePSDError('PSD分组期间源变体发生变化')
        destination.parent.mkdir(parents=True,exist_ok=True)
        # Stage on the destination volume, then atomically publish without replace.
        handle,publish_name=tempfile.mkstemp(prefix='.native-group-',suffix='.psd',dir=destination.parent);os.close(handle)
        publish=Path(publish_name)
        try:
            shutil.copyfile(staged,publish);_publish_new(publish,destination)
        finally:publish.unlink(missing_ok=True)
        return {'path':str(destination),'sha256':_hash(destination),'size':result['size'],
                'group_count':len(paths),'panel_order':layer_names,'visible_groups':[layer_names[0]],
                'native_structure_verified':True,'native_structure':tree,'backend':BACKEND_VERSION,
                'source_hashes':[p['sha256'] for p in paths],'photoshop':response,'cache_dir':str(directory)}
    finally:
        for source in paths:
            if not Path(source['path']).is_file() or _hash(source['path'])!=source['sha256']:
                raise NativePSDError('PSD分组后源变体校验失败；不自动降级')
