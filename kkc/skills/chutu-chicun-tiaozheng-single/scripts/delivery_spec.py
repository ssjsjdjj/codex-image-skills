"""Normalize a single-style delivery package without creating files or directories."""
import json
import re
import string
import unicodedata
from pathlib import Path, PurePosixPath

from task_spec import load_jobs


KINDS = {"main", "scene"}
NAMING = {"numbered", "style_size_index", "original"}
_SIZE_PRESETS = {'main':('800x800','1440x1440','750x1000'),
                 'scene':('750x1000','800x800','800x1200')}
_DELIVERY_KEYS = {"kind", "style_id", "out_dir", "sizes", "max_bytes", "naming", "format", "source_type"}
_PHOTO_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.tif', '.tiff', '.bmp', '.gif', '.avif'}
_RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$",
             *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}


def size_options(kind):
    """Return this entry's menu; other legal sizes remain available as custom."""
    if not isinstance(kind,str) or kind not in KINDS:
        raise ValueError('尺寸菜单仅支持main/scene入口')
    return {'kind':kind,'presets':list(_SIZE_PRESETS[kind]),
            'custom':{'enabled':True,'min':1,'max':10000}}


def _safe_filename(value, field):
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field}必须是非空安全文件名，不得有首尾空白")
    if value in (".", "..") or value.endswith((".", " ")):
        raise ValueError(f"{field}不是安全文件名")
    if any(c in '<>:"/\\|?*' or unicodedata.category(c) in ("Cc", "Cf") for c in value):
        raise ValueError(f"{field}包含路径分隔符、控制字符或Windows非法字符")
    if value.split(".", 1)[0].upper() in _RESERVED:
        raise ValueError(f"{field}不能是Windows保留设备名")
    if len(value.encode("utf-16-le")) // 2 > 255:
        raise ValueError(f"{field}过长，无法安全命名")
    return value


def _size(value):
    if not isinstance(value, str):
        raise ValueError("delivery.sizes的每项必须为尺寸字符串")
    match = re.fullmatch(r"\s*(\d+)\s*[xX×*]\s*(\d+)\s*", value)
    if not match:
        raise ValueError(f"无效交付尺寸：{value}")
    width, height = map(int, match.groups())
    if not (1 <= width <= 10000 and 1 <= height <= 10000):
        raise ValueError("交付尺寸范围为1~10000像素")
    return f"{width}x{height}"


def _format(value):
    if not isinstance(value, str):
        raise ValueError("交付format只能是jpg或png")
    value = value.lower()
    if value == "jpeg":
        value = "jpg"
    if value not in ("jpg", "png"):
        raise ValueError("交付format只能是jpg或png")
    return value


def _root(value):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError("delivery.out_dir必须是非空输出根目录")
    try:
        root = Path(value).expanduser().resolve()
        ancestor = root
        while not ancestor.exists():
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            raise ValueError("输出根目录或其父目录被文件占用")
    except (OSError, RuntimeError) as exc:
        raise ValueError("delivery.out_dir无法安全解析") from exc
    return root


def _template(value, field, allowed):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field}必须是非空命名模板，可含匹配的文件扩展名")
    try:
        parts = list(string.Formatter().parse(value))
    except ValueError as exc:
        raise ValueError(f"{field}模板语法不正确") from exc
    for _, name, format_spec, conversion in parts:
        if name is None:
            continue
        if name not in allowed or conversion:
            raise ValueError(f"{field}仅允许字段：{','.join(sorted(allowed))}")
        if name == 'index':
            if format_spec and not re.fullmatch(r'(?:0?[1-9]\d?)?d', format_spec):
                raise ValueError("index只支持整数序号格式，如{index}或{index:02d}")
        elif format_spec:
            raise ValueError(f"{name}不支持格式修饰")
    return value


def _naming(value):
    if isinstance(value, str):
        if value not in NAMING:
            raise ValueError("delivery.naming只能是numbered、style_size_index、original或包含image/psd的命名对象")
        templates = {'image': {'numbered':'{index}','style_size_index':'{style_id}_{size}_{index}',
                               'original':'{original_stem}'}[value],
                     'psd': '{style_id}_{size}'}
        return value, templates
    if not isinstance(value, dict) or set(value) != {'image', 'psd'}:
        raise ValueError("请人工明确输入图片命名image和PSD命名psd；命名对象必须同时包含这两项")
    image = _template(value['image'], 'naming.image', {'style_id','size','index','original_stem'})
    psd = _template(value['psd'], 'naming.psd', {'style_id','size'})
    return {'image':image, 'psd':psd}, {'image':image, 'psd':psd}


def _render_stem(template, values, extension, field):
    """Strip an explicitly supplied matching suffix, never a dot within a field."""
    rendered = _safe_filename(template.format(**values), field)
    explicit_suffix = re.search(r'\.([A-Za-z0-9]+)$', template)
    if explicit_suffix:
        suffix = explicit_suffix.group(1).lower()
        allowed = {'jpg', 'jpeg'} if extension == 'jpg' else {extension}
        if suffix not in allowed:
            raise ValueError(f"{field}扩展名.{suffix}与实际.{extension}不匹配，请人工修改命名")
        rendered = rendered[:-(len(explicit_suffix.group(1)) + 1)]
    return _safe_filename(rendered, field)


def _sources(jobs, declared, kind):
    if declared is not None and declared not in ('photos', 'psd'):
        raise ValueError('delivery.source_type只能是photos或psd')
    detected = set()
    for job in jobs:
        source = job['input']
        suffix = PurePosixPath(source.replace('\\', '/')).suffix.lower()
        if suffix == '.psd':
            source_type = 'psd'
            path = Path(source).expanduser()
            if path.is_file():
                try:
                    with path.open('rb') as stream:
                        if stream.read(4) != b'8BPS':
                            raise ValueError('PSD输入文件头不正确，不得将JPG等图片改后缀冒充PSD')
                except OSError as exc:
                    raise ValueError('PSD输入文件无法读取') from exc
        elif suffix in _PHOTO_SUFFIXES:
            source_type = 'photos'
        else:
            raise ValueError('输入必须是PSD或支持的图片文件')
        if declared is not None and source_type != declared:
            raise ValueError('声明的source_type与实际输入扩展名不一致')
        if 'source_type' in job and job['source_type'] != source_type:
            raise ValueError('job.source_type与实际输入扩展名不一致')
        detected.add(source_type)
    if len(detected) != 1:
        raise ValueError('同一交付任务不能混合照片和PSD，请分开建立任务')
    source_type = next(iter(detected))
    # Main/scene describe usage, independently of photo/PSD input.
    # Every delivery still adds one grouped PSD per selected size.
    return source_type


def _output(root, *parts):
    path = root.joinpath(*parts)
    try:
        if not path.resolve().is_relative_to(root):
            raise ValueError("交付路径越过输出根目录")
        ancestor = path.parent
        while not ancestor.exists():
            ancestor = ancestor.parent
        if not ancestor.is_dir():
            raise ValueError("交付图片或源文件目录被文件占用")
        if path.exists():
            raise ValueError(f"交付文件已存在，请使用新输出目录：{path.name}")
    except (OSError, RuntimeError) as exc:
        raise ValueError("交付路径无法安全解析") from exc
    return path


def normalize_delivery(spec_path):
    """Return normalized policy and size-major jobs, or None for legacy specs.

    ``delivery.sizes`` controls expansion even when legacy job/default size exists.
    Default numbered naming uses the source row's 1-based index for every size.
    Explicit naming remains a task override, not evidence of user authorization.
    Geometry and other
    rendering fields remain intact; delivery-owned output/PSD/cap fields override
    per-job values. No source image is decoded and no filesystem mutation occurs.
    """
    raw = json.loads(Path(spec_path).read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("任务单必须为对象")
    if "delivery" not in raw:
        return None
    delivery = raw["delivery"]
    if not isinstance(delivery, dict):
        raise ValueError("delivery必须为对象")
    unknown = set(delivery) - _DELIVERY_KEYS
    if unknown:
        raise ValueError("delivery含不支持字段：" + ",".join(sorted(unknown)))
    kind = delivery.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("delivery.kind仅支持main/scene，本轮不提供white/transparent操作入口")
    style_id = _safe_filename(delivery.get("style_id"), "delivery.style_id")
    root = _root(delivery.get("out_dir"))
    requested_sizes = delivery.get("sizes")
    if not isinstance(requested_sizes, list) or not requested_sizes:
        raise ValueError("请先提醒人工选择输出尺寸或输入自定义尺寸；delivery.sizes必须为非空列表，没有默认全出")
    sizes = [_size(value) for value in requested_sizes]
    if len(sizes) != len(set(sizes)):
        raise ValueError("delivery.sizes存在重复尺寸")
    cap = delivery.get("max_bytes", 500000)
    if type(cap) is not int or not 1 <= cap <= 500000:
        raise ValueError("delivery.max_bytes必须是1~500000的整数")
    naming, templates = _naming(delivery.get("naming","numbered"))
    menu = size_options(kind)
    size_selections = [{'size':size,'source':'preset' if size in menu['presets'] else 'custom'} for size in sizes]
    size_sources = {item['size']:item['source'] for item in size_selections}
    # Explicit export choices override source type. Otherwise existing PNGs stay
    # PNG, so simply omitting format cannot silently flatten their alpha.
    selected_format = _format(delivery['format']) if 'format' in delivery else None
    jobs = load_jobs(spec_path, require_size=False)
    source_type = _sources(jobs, delivery.get('source_type'), kind)
    source_count = len(jobs)
    policy = {"kind": kind, "style_id": style_id, "out_dir": str(root), "sizes": sizes,
              "max_bytes": cap, "naming": naming, "format": selected_format or 'source',
              "source_count": source_count, "source_type": source_type,
              "presets":menu['presets'],"size_selections":size_selections,
              "naming_source":"explicit" if 'naming' in delivery else "default"}
    expanded, image_paths, psd_paths, psd_path_keys = [], set(), {}, set()
    prepared = []
    for index, job in enumerate(jobs, 1):
        if "_delivery" in job or "delivery" in job:
            raise ValueError("不得在jobs或defaults中注入delivery元数据")
        if "style_id" in job and job["style_id"] != style_id:
            raise ValueError("一个delivery只能包含同一款号，不得混款")
        if "kind" in job and job["kind"] != kind:
            raise ValueError("一个delivery只能包含同一交付kind")
        if "name" in job and job["name"] is not None:
            _safe_filename(job["name"], "job.name")
        stem = PurePosixPath(job["input"].replace("\\", "/")).stem
        if naming == "original":
            _safe_filename(stem, "原图stem")
        if job.get('format') is not None:
            image_format = _format(job['format'])
            format_source = 'job'
        elif selected_format is not None:
            image_format = selected_format
            format_source = 'delivery'
        else:
            suffix = PurePosixPath(job['input'].replace('\\', '/')).suffix.lower()
            image_format = 'png' if suffix == '.png' else 'jpg'
            format_source = 'psd_default' if source_type == 'psd' else 'input_suffix'
        prepared.append((index,job,stem,image_format,format_source))
    for size in sizes:
        for index,job,stem,image_format,format_source in prepared:
            values = {'style_id':style_id,'size':size,'index':index,'original_stem':stem}
            name = _render_stem(templates['image'], values, image_format, '交付图片名主体')
            _safe_filename(f"{name}.{image_format}", "交付图片名")
            image_dir = root / "图片" / size
            image_path = _output(root, "图片", size, f"{name}.{image_format}")
            image_key = str(image_path.resolve()).casefold()
            if image_key in image_paths:
                raise ValueError("存在重复生成路径，请更换命名方式或素材名称")
            image_paths.add(image_key)
            psd_stem = _render_stem(templates['psd'], values, 'psd', '交付PSD名主体')
            psd_name = _safe_filename(f"{psd_stem}.psd", "交付PSD名")
            if size not in psd_paths:
                psd_path = _output(root, "源文件", psd_name)
                psd_key = str(psd_path.resolve()).casefold()
                if psd_key in psd_path_keys:
                    raise ValueError('不同尺寸PSD生成路径重复，请在PSD命名中区分尺寸')
                psd_path_keys.add(psd_key)
                psd_paths[size] = str(psd_path)
            item = dict(job)
            item.update(size=size, name=name, out_dir=str(image_dir), format=image_format,
                        psd=False, max_bytes=cap,
                        _delivery={"style_id": style_id, "kind": kind, "size": size, "index": index,
                                   "layer_name": str(index), "psd_path": psd_paths[size], "source_count": source_count,
                                   "source_type": source_type, "format_source": format_source,
                                   "format_explicit": format_source in ('delivery', 'job'),
                                   "size_source":size_sources[size]})
            expanded.append(item)
    formats = {job['format'] for job in expanded}
    policy['format'] = next(iter(formats)) if len(formats) == 1 else 'source'
    return {"policy": policy, "jobs": expanded}
