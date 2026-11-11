"""Limited RGB8 pixel-PSD renderer and grouped source writer. Never invokes Photoshop.

It edits the original layer records and their real RGB/alpha/mask channels.
It does not use the document's composite preview as a source image.
"""
import copy
import uuid
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageChops
from psd_tools import PSDImage
from psd_tools.constants import ColorMode, Compression, Resource, Tag
from psd_tools.api.layers import Group, PixelLayer, _issue_layer_ids
from layered_psd import _names
from psd_source import _execution_plan, inspect_source


def file_hash(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()


def raw_hash(data):return hashlib.sha256(data).hexdigest()


def blob(value):return value.tobytes().hex() if value is not None else None


def layer_state(layer):
    record=layer._record;mask=record.mask_data
    tags_without_id=copy.deepcopy(record.tagged_blocks)
    if Tag.LAYER_ID in tags_without_id:del tags_without_id[Tag.LAYER_ID]
    return {'name':layer.name,'kind':layer.kind,'visible':layer.visible,'opacity':record.opacity,
            'blend':record.blend_mode.name,'clipping':int(record.clipping),'flags':blob(record.flags),
            'tags':blob(record.tagged_blocks),'blending_ranges':blob(record.blending_ranges),
            'tags_without_layer_id':blob(tags_without_id),'layer_id':record.tagged_blocks.get_data(Tag.LAYER_ID),
            'channel_ids':[int(info.id) for info in record.channel_info],
            'bbox':[record.left,record.top,record.right,record.bottom],
            'mask':None if mask is None else {'bbox':[mask.left,mask.top,mask.right,mask.bottom],
                'background':mask.background_color,'flags':blob(mask.flags),'parameters':blob(mask.parameters),
                'real_bbox':None if mask.real_left is None else [mask.real_left,mask.real_top,mask.real_right,mask.real_bottom],
                'real_flags':blob(mask.real_flags),'real_background':mask.real_background_color}}


def channel_size(record, channel_id):
    mask=record.mask_data
    if channel_id==-2:
        if mask is None:raise ValueError('用户mask通道缺少真实MaskData')
        return mask.width,mask.height
    if channel_id==-3:
        if mask is None or mask.real_flags is None or any(v is None for v in (mask.real_left,mask.real_top,mask.real_right,mask.real_bottom)):
            raise ValueError('real mask通道和MaskData real_*字段不匹配')
        return mask.real_width,mask.real_height
    return record.right-record.left,record.bottom-record.top


def read_channels(layer):
    result={}
    for info,channel in zip(layer._record.channel_info,layer._channels):
        identifier=int(info.id);size=channel_size(layer._record,identifier)
        if min(size)<=0:raise ValueError('本次限定非空像素图层/蒙版，不猜测空通道几何')
        data=channel.get_data(*size,8,1)
        if len(data)!=size[0]*size[1]:raise ValueError('原生通道解码长度不符')
        result[identifier]=Image.frombytes('L',size,data)
    return result


class PythonPSDUnsupported(ValueError):
    """Valid PSD structure outside this backend's deliberately narrow scope."""


def _validate_structure(document):
    if document.color_mode!=ColorMode.RGB or document.depth!=8 or document._record.header.version!=1:
        raise ValueError('仅支持普通PSD的8位RGB，不支持其他模式/位深/PSB')
    if document.channels not in (3,4):raise ValueError('仅支持RGB及可识别的merged alpha，不处理额外spot/alpha通道')
    layer_info=document._record._get_layer_info()
    if (document.channels==4)!=(layer_info is not None and layer_info.layer_count<0):
        raise ValueError('第四merged通道必须明确标记为文档透明度，不能猜测额外alpha通道')
    if not len(document):raise ValueError('PSD必须有实际pixel图层')
    global_mask=document._record.layer_and_mask_information.global_layer_mask_info
    if global_mask is not None and global_mask.overlay_color is not None:
        raise ValueError('当前Python路径不支持文档级全局蒙版')
    if document._record.layer_and_mask_information.tagged_blocks:
        raise ValueError('本次未实现文档级特殊几何/动画/智能对象资源，拒绝静默处理')
    safe_tags={getattr(Tag,name) for name in ('UNICODE_LAYER_NAME','LAYER_ID','LAYER_PROTECTION','SHEET_COLOR_SETTING') if hasattr(Tag,name)}
    safe_resources={int(Resource.VERSION_INFO),int(Resource.ICC_PROFILE),int(Resource.RESOLUTION_INFO),int(Resource.IDS_SEED_NUMBER)}
    if any(int(key) not in safe_resources for key in document.image_resources):
        raise ValueError('PSD含未实现安全缩放的文档资源，需人工检查')
    for layer in document:
        if layer.kind!='pixel' or layer.is_group() or layer.has_vector_mask() or layer.has_effects():
            raise ValueError('仅支持纯pixel；text/smartobject/group/vector/effects均未实现，拒绝栅格化降级')
        if set(layer._record.tagged_blocks)-safe_tags:raise ValueError('图层有未实现的标签/几何/效果，拒绝静默保留错误坐标')
        identifiers=[int(info.id) for info in layer._record.channel_info]
        if len(set(identifiers))!=len(identifiers) or not {0,1,2}.issubset(identifiers) or set(identifiers)-{-3,-2,-1,0,1,2}:
            raise ValueError('图层通道结构不在本次实现范围')
        mask=layer._record.mask_data
        if mask is not None:
            if -2 not in identifiers:raise ValueError('MaskData存在但没有用户mask通道')
            if mask.flags.pos_relative_to_layer or (mask.real_flags is not None and mask.real_flags.pos_relative_to_layer):
                raise ValueError('暂不支持相对图层坐标的bitmap mask')
            if mask.parameters is not None or mask.flags.parameters_applied:
                raise ValueError('本次不处理density/feather参数，不能保留未缩放半径')
            if (mask.real_flags is not None)!=(-3 in identifiers):raise ValueError('real mask字段和-3通道不匹配')


def validate_supported(document):
    try:
        _validate_structure(document)
    except ValueError as error:
        raise PythonPSDUnsupported(str(error)) from error
    # A decode failure is corruption, not an unsupported-structure choice.
    for layer in document:read_channels(layer)


def check_python_support(path):
    document=PSDImage.open(path)
    try:validate_supported(document)
    except PythonPSDUnsupported as error:return {'supports':False,'reason':str(error)}
    return {'supports':True,'reason':None,'backend':'python-pixel-psd'}


def scaled_box(box,factor):return [round(value*factor) for value in box]


def _visible_rgb(image):
    rgba=image.convert('RGBA');base=Image.new('RGBA',rgba.size,'white')
    return Image.alpha_composite(base,rgba).convert('RGB')


BACKEND='python-pixel-psd'


def _pixel_checks(document):
    rows=[]
    for layer in document:
        rows.append({'state':layer_state(layer),'channels':[{'id':identifier,'size':list(image.size),'sha256':raw_hash(image.tobytes())}
                     for identifier,image in read_channels(layer).items()]})
    return rows


def _verify_pixels(document,expected,*,fresh_layer_ids=False):
    if len(document)!=len(expected):raise ValueError('保存后图层数量不一致')
    for layer,row in zip(document,expected):
        actual,wanted=layer_state(layer),copy.deepcopy(row['state'])
        if fresh_layer_ids:
            for state in (actual,wanted):
                state.pop('tags');state.pop('layer_id')
        if actual!=wanted:raise ValueError('保存后原像素图层/蒙版/元数据变化：'+layer.name)
        decoded=read_channels(layer)
        for channel in row['channels']:
            if list(decoded[channel['id']].size)!=channel['size'] or raw_hash(decoded[channel['id']].tobytes())!=channel['sha256']:
                raise ValueError('保存后原生RGB/alpha/mask通道不符：'+layer.name)
        if any(info.length!=data._length for info,data in zip(layer._record.channel_info,layer._channels)):
            raise ValueError('通道长度或RLE行表不符')


def _verify_merged(document):
    stored=document.composite(apply_icc=False)
    forced=document.composite(force=True,ignore_preview=True,apply_icc=False)
    if stored is None or forced is None or stored.size!=document.size:raise ValueError('PSD合成预览缺失或尺寸不符')
    alpha=ImageChops.difference(stored.convert('RGBA').getchannel('A'),forced.convert('RGBA').getchannel('A')).getextrema()[1]
    color=max(high for _,high in ImageChops.difference(_visible_rgb(stored),_visible_rgb(forced)).getextrema())
    if alpha>1 or color>1:raise ValueError('PSD stored预览与实际可见图层合成不一致')
    return stored.copy(),{'color_max_lsb':color,'alpha_max_lsb':alpha}


def _new_path(path):
    path=Path(path).expanduser().absolute()
    if path.suffix.lower()!='.psd':raise ValueError('PSD输出需要.psd扩展名')
    if path.exists() or path.is_symlink():raise FileExistsError('PSD已存在，不覆盖：'+str(path))
    return path


def _publish(stage,destination):
    destination=_new_path(destination)
    os.link(stage,destination)


def _select_layers(document,names):
    if names is None:return {'enabled':False,'all_layers_preserved':True}
    if not isinstance(names,list) or not names or any(not isinstance(name,str) or not name for name in names) or len(set(names))!=len(names):
        raise ValueError('source_layers必须为非空且无重复的显式顶层图层名字列表')
    existing={}
    for layer in document:existing.setdefault(layer.name,[]).append(layer)
    if any(name not in existing or len(existing[name])!=1 for name in names):raise ValueError('source_layers有不存在或同名歧义的层')
    selected=set(names)
    for layer in list(document):
        if layer.name not in selected:document.remove(layer)
        elif int(layer._record.clipping)!=0:raise ValueError('选择的图层有剪贴依赖，不能移除未声明的依赖层')
        else:layer.visible=True
    return {'enabled':True,'all_layers_preserved':False,'selected_names':names,
            'policy':'Only named top-level pixel layers retained; selected roots visible; masks and pixel channels preserved'}


def _transform(document,viewport,target):
    left,top,right,bottom=viewport;factor=target[0]/(right-left)
    def mapped(box,relative=False):
        return [round((value-(0 if relative else (left if index%2==0 else top)))*factor) for index,value in enumerate(box)]
    for layer in document:
        record=layer._record;channels=read_channels(layer)
        record.left,record.top,record.right,record.bottom=mapped([record.left,record.top,record.right,record.bottom])
        size=(record.right-record.left,record.bottom-record.top)
        if min(size)<=0 or max(size)>30000:raise ValueError('缩放后图层过大或为空，不能丢弃画布外原像素')
        if size == channels[0].size:
            # Identity geometry (including a pure canvas translation) must not
            # round-trip low-alpha RGB through 8-bit premultiplication.
            output={identifier:channels[identifier].copy() for identifier in (0,1,2,-1) if identifier in channels}
        elif -1 in channels:
            rgba=Image.merge('RGBA',(channels[0],channels[1],channels[2],channels[-1]))
            resized=rgba.convert('RGBa').resize(size,Image.Resampling.LANCZOS).convert('RGBA')
            output=dict(zip((0,1,2,-1),resized.split()))
        else:
            resized=Image.merge('RGB',(channels[0],channels[1],channels[2])).resize(size,Image.Resampling.LANCZOS)
            output=dict(zip((0,1,2),resized.split()))
        mask=record.mask_data
        if mask:
            mask.left,mask.top,mask.right,mask.bottom=mapped([mask.left,mask.top,mask.right,mask.bottom])
            if min(mask.width,mask.height)<=0 or max(mask.width,mask.height)>30000:raise ValueError('缩放后mask尺寸不支持')
            output[-2]=channels[-2].resize((mask.width,mask.height),Image.Resampling.LANCZOS)
            if -3 in channels:
                mask.real_left,mask.real_top,mask.real_right,mask.real_bottom=mapped([mask.real_left,mask.real_top,mask.real_right,mask.real_bottom])
                if min(mask.real_width,mask.real_height)<=0 or max(mask.real_width,mask.real_height)>30000:raise ValueError('缩放后real mask尺寸不支持')
                output[-3]=channels[-3].resize((mask.real_width,mask.real_height),Image.Resampling.LANCZOS)
        for info,data in zip(record.channel_info,layer._channels):
            image=output[int(info.id)];data.compression=Compression.RLE
            data.set_data(image.tobytes(),*image.size,8,1);info.length=data._length
        layer._invalidate_bbox()
    document._record.header.width,document._record.header.height=target
    document._update_record();document.mark_updated()
    return factor


def render_python_psd(job,cache_root,plan=None):
    """Scale original pixel/mask channels; preserve off-canvas pixels and source."""
    source=Path(job['input']).expanduser().resolve()
    if source.suffix.lower()!='.psd' or not source.is_file():raise ValueError('Python PSD后端需要真实PSD源')
    before=file_hash(source);source_info=inspect_source(source)
    if source_info['sha256']!=before:raise ValueError('读取期间源PSD变化')
    document=PSDImage.open(source);validate_supported(document)
    original_resources=document.image_resources.tobytes();original_channels=document.channels
    original_count=document._record.layer_and_mask_information.layer_info.layer_count
    selection=_select_layers(document,job.get('source_layers'))
    selection['master_source']=str(source);selection['master_sha256']=before
    selection['source_structure']=source_info['native_structure']
    selected_source=[layer_state(layer) for layer in document]
    executed,target=_execution_plan(job,source_info,plan)
    factor=_transform(document,executed['source_viewport_px'],target)
    expected=_pixel_checks(document)
    root=Path(cache_root).expanduser().resolve();root.mkdir(parents=True,exist_ok=True)
    directory=root/('python-psd-'+uuid.uuid4().hex);directory.mkdir()
    stage=directory/'variant-stage.psd';variant=directory/'variant.psd'
    try:
        document.save(stage)
        reopened=PSDImage.open(stage)
        if reopened.size!=target or reopened.channels!=original_channels:raise ValueError('保存后PSD尺寸或通道数不符')
        if reopened.image_resources.tobytes()!=original_resources:raise ValueError('保存后ICC/文档资源变化')
        if not selection['enabled'] and reopened._record.layer_and_mask_information.layer_info.layer_count!=original_count:
            raise ValueError('完整渲染发生层数或merged alpha符号变化')
        _verify_pixels(reopened,expected);image,merged=_verify_merged(reopened)
        profile=reopened.image_resources.get_data(Resource.ICC_PROFILE)
        if profile is not None:image.info['icc_profile']=profile
        if file_hash(source)!=before:raise ValueError('源PSD已变化，停止，不发布')
        _publish(stage,variant)
        details=inspect_source(variant)
        metadata={'backend':BACKEND,'native_structure_verified':True,'native_psd':True,
                  'source':str(source),'source_sha256':before,'source_hash_unchanged':True,
                  'source_structure':source_info['native_structure'],'selected_source_layers':selected_source,
                  'source_selection':selection,'all_layers_preserved':not selection['enabled'],
                  'variant_psd':str(variant),'variant_sha256':file_hash(variant),'sha256':file_hash(variant),
                  'variant_structure':details['native_structure'],'size':list(target),'scale':factor,'upscale_risk':factor>1+1e-7,
                  'quality':{'upsampling':factor>1+1e-7,'scale':factor,'note':'普通像素放大不增加原始细节'},
                  'algorithm':'Original RGB+intrinsic alpha premultiplied RGBa LANCZOS; independent user mask LANCZOS',
                  'off_canvas_pixels_preserved':True,'no_flattening':True,'no_jpeg_source':True,
                  'pixel_channels_verified':True,'merged_verified':merged,'cache_dir':str(directory)}
        (directory/'metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        return image,executed,metadata
    finally:
        if not source.is_file() or file_hash(source)!=before:raise ValueError('原始PSD在Python渲染期间变化')


def group_python_psd_sources(destination,variants,names=None):
    """Each verified pixel PSD becomes one independently visible, native group."""
    variants=list(variants)
    if not variants:raise ValueError('Python PSD分组列表不能为空')
    names=_names(names,len(variants));destination=_new_path(destination)
    sources=[]
    for item in variants:
        path=Path(item.get('variant_psd','') if isinstance(item,dict) else item).resolve()
        before=file_hash(path)
        if isinstance(item,dict) and item.get('variant_sha256',item.get('sha256')) not in (None,before):raise ValueError('源PSD变体哈希变化')
        document=PSDImage.open(path);validate_supported(document)
        sources.append((path,before,document,_pixel_checks(document)))
    first=sources[0][2];profile=first.image_resources.get_data(Resource.ICC_PROFILE)
    for _,_,document,_ in sources[1:]:
        if (document.size,document.depth,document.color_mode,document.channels)!=(first.size,first.depth,first.color_mode,first.channels):
            raise ValueError('Python PSD汇总必须同尺寸/位深/色彩模式/merged通道数')
        if document.image_resources.get_data(Resource.ICC_PROFILE)!=profile:raise ValueError('Python PSD汇总不能静默混合ICC')
    mode='RGBA' if first.channels==4 else 'RGB'
    output=PSDImage.frompil(Image.new(mode,first.size,(0,0,0,0) if mode=='RGBA' else (0,0,0)))
    output._record.image_resources=copy.deepcopy(first._record.image_resources)
    output._record.color_mode_data=copy.deepcopy(first._record.color_mode_data)
    output._merged_alpha=first.channels==4
    for index in reversed(range(len(sources))):
        group=Group.new(output,'Group');group.name=names[index];group.visible=index==0
        for layer in sources[index][2]:
            # Deep-copy the actual record and compressed native channels, not
            # rendered pixels. No color/depth conversion or layer flattening.
            child=PixelLayer(group,copy.deepcopy(layer._record),copy.deepcopy(layer._channels))
            group.append(child)
    # New groups and children need document-unique IDs. This only rewrites lyid;
    # the strict support gate disallows structures carrying ID references.
    output.image_resources[Resource.IDS_SEED_NUMBER]=_issue_layer_ids(output,[],output.descendants())
    output._update_record();output.mark_updated()
    destination.parent.mkdir(parents=True,exist_ok=True)
    descriptor,temp_name=tempfile.mkstemp(prefix='.python-group-',suffix='.psd',dir=destination.parent);os.close(descriptor)
    temporary=Path(temp_name)
    try:
        output.save(temporary);reopened=PSDImage.open(temporary)
        if reopened.size!=first.size or [group.name for group in reversed(list(reopened))]!=names:raise ValueError('Python分组PSD尺寸或组顺序错误')
        if [group.name for group in reopened if group.visible]!=[names[0]]:raise ValueError('Python分组PSD只应显示第1组')
        by_name={group.name:group for group in reopened}
        for name,(_,_,_,expected) in zip(names,sources):_verify_pixels(by_name[name],expected,fresh_layer_ids=True)
        identifiers=[layer._record.tagged_blocks.get_data(Tag.LAYER_ID) for layer in reopened.descendants()]
        if len(set(identifiers))!=len(identifiers) or any(not isinstance(identifier,int) or identifier<=0 for identifier in identifiers):
            raise ValueError('Python汇总PSD图层ID重复或无效')
        if reopened.image_resources.get_data(Resource.ICC_PROFILE)!=profile:raise ValueError('Python分组ICC未保留')
        image,merged=_verify_merged(reopened)
        for path,before,_,_ in sources:
            if file_hash(path)!=before:raise ValueError('分组期间源PSD变体变化')
        _publish(temporary,destination)
        details=inspect_source(destination)
        return {'path':str(destination),'sha256':file_hash(destination),'size':list(reopened.size),'group_count':len(sources),
                'panel_order':names,'api_layer_order':list(reversed(names)),'visible_groups':[names[0]],
                'native_structure_verified':True,'pixel_channels_verified':True,'native_structure':details['native_structure'],
                'backend':BACKEND,'no_flattening':True,'no_jpeg_source':True,'merged_verified':merged,
                'layer_ids_reissued':True,'source_layer_ids':[[row['state']['layer_id'] for row in expected] for _,_,_,expected in sources],
                'source_hashes':[before for _,before,_,_ in sources]}
    finally:
        temporary.unlink(missing_ok=True)
        for path,before,_,_ in sources:
            if not path.is_file() or file_hash(path)!=before:raise ValueError('Python分组后源PSD变体变化')


