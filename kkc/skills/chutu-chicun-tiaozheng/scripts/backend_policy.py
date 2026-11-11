"""Read-only backend selection from actual source/viewport geometry.

Call resolve_backend before rendering or creating pixel outputs. A Python
default is not a human approval to upscale. The caller must verify that the
stored confirmation is an actual user message; this module checks its binding.
"""
import copy
import hashlib
import math
from pathlib import Path

from task_spec import digest


BACKENDS = {'python', 'photoshop'}
UPSCALE_EPSILON = 1e-6


class BackendChoiceRequired(ValueError):
    """A current, nonempty human selection is required; report is JSON-safe."""
    def __init__(self, report):
        self.report = copy.deepcopy(report)
        super().__init__(report.get('choice_error') or report['message'])


def _size(value, field):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f'{field}必须是两个正整数')
    if any(type(v) is not int or v <= 0 for v in value):
        raise ValueError(f'{field}必须是两个正整数')
    return list(value)


def _box(value, field):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f'{field}必须是四个有限像素坐标')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value):
        raise ValueError(f'{field}必须是四个有限像素坐标')
    box = [float(v) for v in value]
    if box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError(f'{field}必须具有正宽高')
    return box


def _source(path):
    if not isinstance(path, str) or not path:
        raise ValueError('当前job必须有真实input文件路径')
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError('input文件不存在或不是普通文件')
    before = source.stat()
    result = hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            result.update(block)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError('评估期间input文件变化，请重新评估后选择')
    return str(source), result.hexdigest()


def assess_risk(job, plan):
    """Assess actual scale without decoding images, rendering, or writing files."""
    if not isinstance(job, dict) or not isinstance(plan, dict):
        raise ValueError('job和plan必须为对象')
    source, source_sha256 = _source(job.get('input'))
    source_size = _size(plan.get('source_size'), 'plan.source_size')
    output_size = _size(plan.get('output_size'), 'plan.output_size')
    domain = _box(plan.get('source_domain_px'), 'plan.source_domain_px')
    viewport = _box(plan.get('source_viewport_px'), 'plan.source_viewport_px')
    effective_fit = plan.get('effective_fit')
    if not isinstance(effective_fit, str) or not effective_fit.strip():
        raise ValueError('plan.effective_fit不能为空')
    scope = {'kind':'current_job_and_size', 'input':source, 'output_size':output_size,
             'size':f'{output_size[0]}x{output_size[1]}'}
    if job.get('_backend_review') is not None:
        scope['review_id'] = job['_backend_review']
    # Delivery rows are distinct tasks even when two rows happen to reuse a file.
    meta = job.get('_delivery')
    if isinstance(meta, dict):
        identity = {key:meta[key] for key in ('style_id','kind','index') if key in meta}
        if identity:
            scope['delivery_job'] = identity
    basis = {'input':source, 'input_sha256':source_sha256, 'source_size':source_size,
             'output_size':output_size, 'source_domain_px':domain,
             'source_viewport_px':viewport, 'effective_fit':effective_fit, 'scope':scope}
    # Choosing another top-level PSD layer is another source selection even if
    # the document bytes and viewport happen to remain identical.
    if 'source_layers' in job:
        basis['source_layers'] = copy.deepcopy(job['source_layers'])
    viewport_size = [viewport[2]-viewport[0], viewport[3]-viewport[1]]
    scale_x, scale_y = output_size[0]/viewport_size[0], output_size[1]/viewport_size[1]
    scale = max(scale_x, scale_y)
    risk = scale > 1.0 + UPSCALE_EPSILON
    message = (f'当前取景需要放大{scale:.3f}倍，可能模糊或细节变软；建议使用Photoshop（PS）进行放大处理，请选择PS或继续使用Python。'
               if risk else '当前取景不需要放大，默认使用Python；仍可明确选择Photoshop。')
    detail_notice = 'Photoshop也不能凭空恢复原图不存在的细节；选择仅限当前任务和当前尺寸，不成为长期默认。'
    return {'input':source, 'input_sha256':source_sha256, 'source_size':source_size,
            'source_domain_px':domain, 'source_viewport_px':viewport,
            'viewport_size':viewport_size, 'output_size':output_size, 'target_size':output_size,
            'effective_fit':effective_fit, 'scale_x':scale_x, 'scale_y':scale_y, 'scale':scale,
            'basis_digest':digest(basis), 'scope':scope, 'risk':risk, 'needs_choice':risk,
            'risk_kind':'upscale' if risk else 'none', 'default_backend':'python',
            'message':message, 'detail_notice':detail_notice,
            'options':[{'backend':'python', 'label':'Python',
                        'description':'使用本次支持的Python图层/像素处理；放大仍可能显软。'},
                       {'backend':'photoshop', 'label':'Photoshop',
                        'description':'使用Photoshop后端；也不能凭空恢复缺失细节。'}]}


def _confirmation(backend, confirmation):
    if not isinstance(backend, str) or backend not in BACKENDS:
        raise ValueError('backend只能是python或photoshop')
    if not isinstance(confirmation, str) or not confirmation.strip():
        raise ValueError('必须记录用户本次对后端的真实非空选择原文')


def make_choice(job, plan, backend, confirmation):
    """Return a bound choice; preserve the actual user text without inventing it."""
    _confirmation(backend, confirmation)
    report = assess_risk(job, plan)
    return {'backend':backend, 'confirmation':confirmation,
            'basis_digest':report['basis_digest'], 'scope':copy.deepcopy(report['scope'])}


def resolve_backend(job, plan):
    """Resolve a current human choice, or Python only when no upscale is needed."""
    report = assess_risk(job, plan)
    choice = job.get('_backend_choice')
    if choice is None:
        if report['needs_choice']:
            report.update(backend=None, choice_valid=False, selection='required',
                          choice_error='需要放大，必须先提示并由人工选择Photoshop或Python；默认Python不等于人工批准')
            raise BackendChoiceRequired(report)
        report.update(backend='python', choice_valid=False, selection='default', confirmation=None)
        return report
    try:
        if not isinstance(choice, dict):
            raise ValueError('_backend_choice必须是本次真实人工选择对象')
        _confirmation(choice.get('backend'), choice.get('confirmation'))
        if choice.get('basis_digest') != report['basis_digest']:
            raise ValueError('原图、取景、目标尺寸或任务范围已变化，旧后端选择失效，请重新评估并选择')
        if 'scope' in choice and choice['scope'] != report['scope']:
            raise ValueError('后端选择范围不是当前任务和尺寸')
    except ValueError as error:
        report.update(needs_choice=True, backend=None, choice_valid=False, selection='required', choice_error=str(error))
        raise BackendChoiceRequired(report) from error
    report.update(needs_choice=False, backend=choice['backend'], choice_valid=True,
                  selection='human', confirmation=choice['confirmation'],
                  choice={'backend':choice['backend'], 'confirmation':choice['confirmation'],
                          'basis_digest':choice['basis_digest'], 'scope':copy.deepcopy(report['scope'])})
    return report
