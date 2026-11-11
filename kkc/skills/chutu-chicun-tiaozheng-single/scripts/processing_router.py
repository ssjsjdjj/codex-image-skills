"""Python-first PSD routing with a read-only, geometry-bound upscale choice gate."""
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from backend_policy import BackendChoiceRequired, assess_risk, resolve_backend


def attach_routing(module):
    photo_render = module._render

    def processing_plan(job, *, require_choice=True):
        source = Path(job['input']).expanduser().resolve()
        is_psd = source.suffix.lower() == '.psd'
        if is_psd:
            from psd_source import inspect_source, _execution_plan
            details = inspect_source(source)
            source_size = tuple(details['size'])
            from python_psd import check_python_support
            support = check_python_support(source)
        else:
            with Image.open(source) as opened:
                source_size = ImageOps.exif_transpose(opened).size
        plan, resolved = module.framing_plan(source_size, module.parse_size(job['size']), job)
        if is_psd:
            plan, _ = _execution_plan(job, details, plan)
        gated = is_psd or bool(job.get('_delivery')) or bool(job.get('psd'))
        def capability(report):
            if is_psd:
                report['python_supported']=support['supports']
                report['python_support_reason']=support.get('reason')
                report['options']=[{**option, **({'available':support['supports']} if option['backend']=='python'
                    else {'requires_local_photoshop':True,'availability_checked':False})} for option in report['options']]
            return report
        if require_choice and gated:
            try:
                decision = capability(resolve_backend(job, plan))
            except BackendChoiceRequired as error:
                raise BackendChoiceRequired(capability(error.report)) from error
            if is_psd and decision['backend']=='python' and not support['supports']:
                decision.update(needs_choice=True,backend=None,
                    choice_error='Python无法安全保留当前PSD结构：'+support['reason'],
                    message='请人工选择PS或提供受支持的像素层副本，不自动切换或合并图层。')
                raise BackendChoiceRequired(decision)
        else:
            decision = capability(assess_risk(job, plan))
            decision.update(backend='python', selection='default', choice_valid=False, confirmation=None)
        processing = {'backend':decision['backend'], 'risk':decision,
                      'choice':decision.get('choice'),
                      'choice_source':'human' if decision.get('choice_valid') else 'default_python'}
        return {'source':source, 'is_psd':is_psd, 'plan':plan, 'resolved':resolved,
                'processing':processing, 'gated':gated}

    def render(job):
        analysis = processing_plan(job)
        source, plan, resolved = analysis['source'], analysis['plan'], analysis['resolved']
        processing = analysis['processing']
        backend = processing['backend']
        # Plain photo diagnostic renders do not export PSDs and retain their
        # existing legacy pixel rounding. Every production delivery is gated.
        if not analysis['is_psd'] and backend == 'python':
            if analysis['gated']:
                with Image.open(source) as opened:
                    image = ImageOps.exif_transpose(opened)
                    image.load()
                    if image.mode == 'CMYK':
                        raise ValueError('CMYK素材需先明确色彩管理转换为RGB/sRGB')
                    profile = image.info.get('icc_profile')
                    image = image.convert('RGBA' if module.has_alpha(image) else 'RGB')
                    image = module._paint(image, module.parse_size(job['size']), plan, resolved['bg'])
                    if profile:image.info['icc_profile'] = profile
            else:
                source, image, plan, resolved = photo_render(job)
            metadata = {'backend':'python-photo', 'processing':processing,
                        'scale':processing['risk']['scale'], 'upscale_risk':processing['risk']['risk']}
        else:
            base = getattr(module, 'native_cache_root', None)
            if base is not None:Path(base).mkdir(parents=True, exist_ok=True)
            cache = Path(tempfile.mkdtemp(prefix='psd-processing-', dir=base))
            if backend == 'python':
                from python_psd import render_python_psd, PythonPSDUnsupported
                try:
                    image, plan, metadata = render_python_psd(job, cache, plan=plan)
                except PythonPSDUnsupported as error:
                    report = dict(processing['risk'])
                    report.update(needs_choice=True, backend=None, python_supported=False,
                                  choice_error=str(error), message='Python无法安全保留当前PSD结构，请人工选择PS或提供支持的源文件。')
                    raise BackendChoiceRequired(report) from error
            else:
                from psd_source import render_psd
                psd_job = dict(job)
                selection_metadata = None
                if analysis['is_psd'] and job.get('source_layers') is not None:
                    from python_psd import render_python_psd, PythonPSDUnsupported
                    # Split only verified pixel records at their original
                    # resolution. Photoshop still performs the chosen target
                    # resize. Complex source trees require native splitting.
                    preparation={'input':str(source),'size':'x'.join(map(str,plan['source_size'])),
                                 'source_layers':job['source_layers']}
                    try:
                        _,_,selection_metadata=render_python_psd(preparation,cache/'selected-original-layers')
                    except PythonPSDUnsupported as error:
                        raise ValueError('PS路径按层取图需要先在PS中拆分此复杂源文件；未执行缩放，未自动栅格化：'+str(error)) from error
                    psd_job['input']=selection_metadata['variant_psd']
                    psd_job.pop('source_layers',None)
                elif not analysis['is_psd']:
                    # A photo has no native edit tree. This independent,
                    # uncompressed pixel PSD supplies Photoshop its real source
                    # pixels; no already-rendered JPG is used as the source.
                    from layered_psd import write_layered_psd
                    with Image.open(source) as opened:
                        original = ImageOps.exif_transpose(opened).copy()
                    if original.mode == 'CMYK':raise ValueError('CMYK照片须先明确色彩转换')
                    profile = original.info.get('icc_profile')
                    original = original.convert('RGBA' if module.has_alpha(original) else 'RGB')
                    if profile:original.info['icc_profile'] = profile
                    staged = cache/'original-photo-pixels.psd'
                    write_layered_psd(staged, [original], names=['原照片像素'])
                    psd_job['input'] = str(staged)
                image, plan, metadata = render_psd(psd_job, cache, plan=plan)
                if selection_metadata is not None:
                    metadata['derived_source_psd']=metadata['source']
                    metadata['source']=str(source)
                    metadata['source_sha256']=processing['risk']['input_sha256']
                    metadata['source_selection']=selection_metadata['source_selection']
                    metadata['selection_preprocessing']={'backend':'python','target_resampling':False,
                        'original_size':analysis['plan']['source_size'],'preserves_original_channels':True}
                    metadata['all_layers_preserved']=False
                if not analysis['is_psd']:
                    metadata['derived_source_psd'] = metadata['source']
                    metadata['source'] = str(source)
                    metadata['source_sha256'] = processing['risk']['input_sha256']
                    metadata['photo_source_has_no_native_edit_tree'] = True
            metadata['processing'] = processing
        resolved.update(input=str(source), _source_metadata=metadata, _processing=processing)
        return source, image, plan, resolved

    module.processing_plan = processing_plan
    module._render = render
    return module
