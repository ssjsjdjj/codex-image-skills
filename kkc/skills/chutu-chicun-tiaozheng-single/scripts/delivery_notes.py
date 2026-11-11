"""Truthful, reproducible text notes for a single delivery-package snapshot."""
import json
import os
import tempfile
from pathlib import Path


_PROMPT = """尺寸调整数据包3.4：主图/场景、编号命名与逐张预览确认调用模板

使用尺寸调整技能，为【人工填写款号】制作【主图/场景】数据包。
素材目录：【填写目录】；来源：【JPG/PNG等原始照片photos / 已有PSD】。主图和场景均可直接用照片；默认Python调整尺寸，并额外交付对应尺寸PSD，无需先将照片转存PSD。
输出根目录：【填写新目录，不覆盖已有成品】。

1. 先确定用途：主图main或场景scene。主图尺寸多选800×800、1440×1440、750×1000；场景尺寸多选750×1000、800×800、800×1200；两类都支持人工输入其他尺寸并多选。只出本批所选，不因截图示例每5张就固定图数。
2. 默认图片命名为同尺寸1—N，每个尺寸从1重新编号，无需再问我填写图片命名。默认PSD命名为款号_尺寸，每款每尺寸1份，内部图层/组仍为1—N。可告知该默认方案；我后来明确自定义图片命名或PSD命名时再覆盖。不得把旧版人工命名模板当默认，naming_source只说明配置来源，不伪称人工授权。
3. 图片保持已确认的像素尺寸，每张JPG/PNG按真实文件字节不超过500000 B（500KB按500000字节保守执行）验收。JPG必要时在允许范围降编码质量；PNG只无损优化，不能擅自量化、移除alpha、缩尺寸或转JPG。PSD未指定成品图片格式时默认JPG并告知，透明部分按JPG白底合成，需要透明可选PNG；格式不是新增必填项。无法满足时明确报告。
4. 目录分为“图片/本批尺寸”和“源文件”。每款、每个本批所选尺寸汇总1份PSD，图片像素图层或原生PSD分组按原图顺序命名1—N；多张图片不能交付成多份重复的单图PSD。
5. PSD默认用Python输出；当前输入支持平坦纯像素层和位图蒙版，不支持已有group源，包括本包输出的1—N分组PSD再次输入。复杂文字、智能对象、矢量、效果或组等受限时提示由我选PS或提供兼容副本，不能假支持，不能自动flatten或切换Photoshop。受支持的原层需逐项验收，不能把从JPG重建的PSD宣称为原生可编辑源文件。
6. 对PSD输入或含PSD交付的业务任务，先按实际source_viewport算scale=max(目标宽/取景宽,目标高/取景高)。scale>1即有风险；先聚合本轮所有尚未选择的放大项，按尺寸/明确范围一次告知倍率和可能模糊、细节变软，建议使用Photoshop（PS）放大，让我选择PS或继续Python。未选前返回requires_backend_choice，不生成该轮任何目标尺寸预览或正式输出，不偷偷默认Python。不是固定遇到1440就询问，Photoshop也不保证找回原本缺失的像素细节。仅安装/纯几何诊断、不输出PSD的合成PNG样例不冒充业务决策。
7. 我已针对本批具体输入、实际裁切和尺寸明确选过Python或Photoshop时，记录真实原文、basis和范围并复用，不重复询问。源文件/内容、裁切或尺寸变化后选择失效；本批选择不学成永久自动放大。Python默认不等于人类已确认放大。
8. 默认review_mode=individual，一次只生成当前张预览，真实确认后才生成下一张；全部候选逐张确认后正式输出。每张记录真实原文与digest；禁止用整批确认、风格授权或沉默代替逐张确认。
9. 生成“使用提示词.txt”和“本批处理说明.txt”，记录本批实际选择、命名、原文件、编码字节/质量、PSD、actual backend、scale/risk/basis及真实选择原文和完成/失败状态。PSD和说明源文件不受500KB图片限制。本机Photoshop COM原生路径尚未通过实机验收，该事实不阻断已支持的Python路径；我选PS后环境不可用则如实失败，不能自动退回Python。
10. 一份PSD的内部多图不自动拆成多个job。我明确选取01—05等图层/颜色范围后，每张建立同一input、不同source_layers的job；白底图选对应商品层和真实背景层，透明图不加背景，纳入整批分尺寸编号预览。未选范围不能自行拆图；metadata应说明保留的是所选源层子集，不是master全部层。
11. 我选PS且有source_layers时，仅对受支持平坦pixel源先由Python按原尺寸无缩放提取，再由PS执行真正目标重采样；复杂或group源的按层取图暂需先在PS拆成独立源文件，不能忽略selector。

此模板用于主图/场景。白底图不纳入本批，使用独立白底图流程。
"""

_PRIVATE_KEYS = {"owner_id", "user_sid", "sid", "feedback", "feedback.jsonl", "audit",
                 "personal_prompt", "other_accounts", "account_history", "account", "account_id",
                 "user_id", "username", "user_name", "owner", "profile_root", "personal_settings"}
_PRESERVATION_KEYS = {"original_layers_preserved", "original_layer_structure_preserved",
                      "source_layers_preserved", "layer_structure_preserved",
                      "native_layers_preserved", "layers_preserved",
                      "source_layer_retention_verified", "original_layers_verified",
                      "native_structure_verified"}


def _safe_value(value):
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()
                if str(key).lower() not in _PRIVATE_KEYS}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<binary {len(value)} bytes>"
    if isinstance(value, Path):
        return str(value)
    return value


def _json(value):
    return json.dumps(_safe_value(value), ensure_ascii=False, sort_keys=True,
                      indent=2, default=str, allow_nan=False)


def _value(value):
    return "未提供" if value is None else _json(value)


def _filename(value):
    return Path(str(value).replace("\\", "/")).name if value else "未提供"


def _preservation_flags(value, prefix=""):
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if str(key) in _PRESERVATION_KEYS and isinstance(item, bool):
                found.append((path, item))
            found.extend(_preservation_flags(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_preservation_flags(item, f"{prefix}[{index}]"))
    return found


def _processing_lines(job, item):
    """Describe observed execution separately from defaults and planned choices."""
    source = item.get('source_metadata', {})
    source = source if isinstance(source, dict) else {}
    processing = item.get('processing')
    origin = 'item.processing'
    if not isinstance(processing, dict):
        processing = source.get('processing')
        origin = 'item.source_metadata.processing'
    choice = job.get('_backend_choice')
    choice = choice if isinstance(choice, dict) else None
    lines = ['处理后端与放大决策（只按实际记录）：']
    if not isinstance(processing, dict):
        lines += ['实际processing：未记录，不能从Python默认规则猜测本项已经使用Python。']
        if source.get('backend') is not None:
            lines.append('source_metadata.backend标记（原样记录，不代替processing）：' + _value(source['backend']))
    else:
        risk = processing.get('risk')
        risk = risk if isinstance(risk, dict) else {}
        lines += ['processing记录来源：' + origin,
                  '实际backend：' + _value(processing.get('backend')),
                  '实际choice_source：' + _value(processing.get('choice_source')),
                  '实际scale：' + _value(risk.get('scale', source.get('scale'))),
                  '实际scale_x：' + _value(risk.get('scale_x')),
                  '实际scale_y：' + _value(risk.get('scale_y')),
                  '实际risk/basis评估记录：' + _value(risk)]
        if processing.get('choice_source') == 'default_python':
            lines.append('选择来源为Python默认；不是本项人工后端确认，也不代表已批准放大。')
        executed_choice = processing.get('choice')
        if isinstance(executed_choice, dict):
            lines += ['执行绑定的真实选择原文：' + _value(executed_choice.get('confirmation')),
                      '执行绑定的basis_digest：' + _value(executed_choice.get('basis_digest')),
                      '执行绑定的choice：' + _value(executed_choice)]
        elif processing.get('choice_source') == 'human':
            lines.append('processing声称human但未提供choice；真实选择原文未记录，不补造确认。')
    if choice is not None:
        lines += ['任务已记录的_backend_choice（计划/绑定范围）：' + _value(choice),
                  '任务真实选择原文：' + _value(choice.get('confirmation')),
                  '任务basis_digest：' + _value(choice.get('basis_digest'))]
    else:
        lines.append('任务_backend_choice：未提供；不把缺失选择填成人工同意。')
    return lines


def _review_lines(record):
    """Describe the supplied review evidence without inventing individual views."""
    mode = record.get("review_mode")
    lines = ["预览与确认实际记录：", "review_mode：" + _value(mode)]
    if mode == "batch":
        lines.append("本批记录为分尺寸分组的整批预览模式；是否已确认以下方实际记录为准，不声明人类逐张单独看过。")
    elif mode == "individual":
        lines.append("本批记录为逐张预览确认模式；确认范围仅以实际记录为准。")
    else:
        lines.append("未提供有效review_mode，不从默认规则猜测本批采用整批或单张确认。")
    groups = record.get("preview_groups")
    lines.append("preview_groups实际分尺寸编号与候选映射：" + _value(groups))
    confirmation = record.get("preview_confirmation")
    if confirmation is None:
        lines.append("preview_confirmation：未记录；不声明本批已获人工整批确认。")
    else:
        lines.append("preview_confirmation实际来源/原文/摘要/范围：" + _value(confirmation))
        lines.append("只复述传入确认记录，不从对象存在推断整批已完成或逐张人看。")
    return lines


def _inspect_output(value, root, max_bytes):
    lines = ["输出路径：" + str(value)]
    path = Path(str(value)).expanduser()
    path = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not path.is_relative_to(root):
        return lines + ["文件现状：未检查（路径不在交付根目录内）"]
    if not path.is_file():
        return lines + ["文件现状：缺失或不是普通文件；未验收通过"]
    lines.append(f"实际文件字节：{path.stat().st_size}")
    if path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
        within = path.stat().st_size <= max_bytes if type(max_bytes) is int else None
        lines.append("图片体积现查：" + ("在本批预算内" if within is True else
                                     "超出本批预算" if within is False else "未提供有效预算，未判定"))
        try:
            from PIL import Image
            with Image.open(path) as image:
                lines.append(f"成品像素尺寸：{image.width}x{image.height}；模式：{image.mode}")
                image.verify()
        except Exception as error:
            lines.append("图片重开检查异常（未标记通过）：" + str(error))
    else:
        lines.append("非图片交付项，不套用500KB图片限制")
    return lines


def _report(root, policy, jobs, record):
    cap = policy.get("max_bytes")
    lines = ["本批处理说明（传入批记录快照）", "",
             "本说明按调用方提供的真实policy、jobs和batch_record记录；不从文件存在推断整批完成。",
             "记录时批次ID：" + str(record.get("id", "未提供")),
             "记录时批次状态：" + str(record.get("status", "未提供；不推断为completed")),
             "款号：" + _value(policy.get("style_id")),
             "用途kind：" + _value(policy.get("kind")),
             "本批用途presets实际配置：" + _value(policy.get("presets")),
             "本批size_selections配置来源：" + _value(policy.get("size_selections")),
             "本批所选sizes：" + _value(policy.get("sizes")),
             "本批naming实际方案：" + _value(policy.get("naming")),
             "本批naming_source配置来源：" + _value(policy.get("naming_source")),
             "默认同尺寸图片1—N、每尺寸从1编号，PSD默认款号_尺寸；无需再索取固定编号命名。",
             "presets/size_selections/naming_source只说明spec配置来源，不等于真人授权或预览确认。",
             "source_type：" + _value(policy.get("source_type")),
             "本批图片预算字节：" + _value(cap),
             "500KB保守定义：500000字节；只限制图片，不限制PSD或说明源文件。",
             "实际说明目录：" + str(root), "", "本批policy："]
    # Avoid copying unrelated personal-account fields from a larger caller object.
    relevant = {key: policy[key] for key in ("style_id", "kind", "presets", "size_selections", "sizes", "naming", "naming_source", "source_type",
                                           "max_bytes", "format", "out_dir") if key in policy}
    lines += [_json(relevant), ""]
    lines.extend(_review_lines(record))
    lines += ["", "逐项任务和导出结果："]
    if record.get('naming_authorization') is not None:
        lines.append('本批真实命名授权记录：' + _value(record['naming_authorization']))
    if record.get('processing') is not None:
        lines.append('批次processing记录（不据此替代逐项实际结果）：' + _value(record['processing']))
    items = record.get("items", [])
    if not isinstance(items, list):
        raise ValueError("batch_record.items必须为列表")
    if not jobs:
        lines.append("未提供jobs，未执行原文件或逐项交付验收。")
    source_metadata = []
    if record.get("source_metadata") is not None:
        source_metadata.append({"来源": "batch_record.source_metadata", "记录": record["source_metadata"]})
    for index in range(max(len(jobs), len(items))):
        job = jobs[index] if index < len(jobs) else {}
        item = items[index] if index < len(items) else {}
        if not isinstance(item, dict):
            raise ValueError("batch_record.items各项必须为对象")
        meta = job.get("_delivery", {})
        if not isinstance(meta, dict):
            meta = {}
        encoding = item.get("encoding", {})
        if not isinstance(encoding, dict):
            encoding = {}
        lines += ["", f"任务 {index+1}",
                  "原图/原生PSD文件名：" + _filename(job.get("input")),
                  "原文件路径：" + _value(job.get("input")),
                  "本项尺寸：" + _value(job.get("size")),
                  "图片命名主体：" + _value(job.get("name")),
                  "本项_delivery编号/分组实际配置：" + _value(meta),
                  "计划汇总PSD文件名：" + _filename(meta.get("psd_path")),
                  "计划汇总PSD路径：" + _value(meta.get("psd_path")),
                  "记录的逐项状态：" + str(item.get("status", "未提供；未记录完成")),
                  "编码format：" + _value(encoding.get("format")),
                  "编码记录bytes：" + _value(encoding.get("bytes")),
                  "编码记录quality：" + (_value(encoding.get("quality")) if "quality" in encoding else "未记录"),
                  "编码记录max_bytes：" + _value(encoding.get("max_bytes"))]
        lines.extend(_processing_lines(job, item))
        if encoding.get("format") == "png" and encoding.get("quality") is None:
            lines.append("PNG质量参数不适用；只有编码器实际无损输出及实际字节记录可用于验收。")
        outputs = item.get("outputs", [])
        if not isinstance(outputs, list):
            raise ValueError("逐项outputs必须为列表")
        if not outputs:
            lines.append("实际输出：未记录；未声明导出成功。")
        for path in outputs:
            lines.extend(_inspect_output(path, root, cap))
        for key in ("error", "exception", "warnings"):
            if item.get(key) is not None:
                lines.append(f"逐项{key}：" + _value(item[key]))
        if item.get("source_metadata") is not None:
            source_metadata.append({"来源": f"items[{index}].source_metadata", "原文件": job.get("input"),
                                    "记录": item["source_metadata"]})
    lines += ["", "汇总PSD实际记录："]
    groups = record.get("grouped_psds", {})
    if not isinstance(groups, dict):
        raise ValueError("batch_record.grouped_psds必须为对象")
    completed = sum(isinstance(value, dict) and value.get("status") == "completed" for value in groups.values())
    lines += [f"grouped_psds记录数量：{len(groups)}", f"其中记录completed数量：{completed}",
              "数量只来自记录，不等于文件均已验收；没有记录的PSD不写通过。"]
    for key, group in groups.items():
        if not isinstance(group, dict):
            raise ValueError("grouped_psds各项必须为对象")
        metadata = group.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        outputs = group.get("outputs", [])
        if not isinstance(outputs, list):
            raise ValueError("grouped_psds.outputs必须为列表")
        path = group.get("path") or (outputs[0] if outputs else key)
        names = group.get("layer_names", metadata.get("panel_order"))
        lines += ["", "PSD文件名：" + _filename(path), "PSD路径：" + str(path),
                  "PSD记录状态：" + str(group.get("status", "未提供")),
                  "PSD尺寸：" + _value(group.get("size", metadata.get("size"))),
                  "PSD图层/组名称：" + _value(names),
                  "PSD元数据/实际验收记录：" + _value(metadata)]
        lines.extend(_inspect_output(path, root, None))
        for name in ("error", "exception", "warnings"):
            if group.get(name) is not None:
                lines.append(f"PSD{name}：" + _value(group[name]))
    lines += ["", "源类型和可编辑性边界：",
              "普通图片构建的PSD是独立像素图层，不代表恢复原生文字、矢量或智能对象。",
              "不得将从JPG重建的PSD标为原生可编辑；是否保留原层必须看下方专项实测记录。"]
    if policy.get("source_type") == "psd":
        lines += ["本批source_type=psd。PSD源质量风险须核对原始尺寸及实际source_viewport放大比例、已有栅格化或压缩；未记录项目视为未执行。",
                  "Python为默认PSD输出路径；实际已运行的后端及人工选择只以上方processing和_backend_choice为准。Photoshop也不保证找回缺失像素细节。",
                  "原生PSD source_metadata：" + (_json(source_metadata) if source_metadata else "未提供；未执行源质量及原层专项验收")]
        flags = _preservation_flags(source_metadata)
        if flags:
            lines.append("原层保留专项标记（只复述明确布尔记录）：")
            lines.append("标记仅描述其记录的核验范围；结构核验不等于全部素材可编辑或放大后清晰。")
            for name, value in flags:
                lines.append(f"{name}：{'通过（记录为true）' if value else '未通过（记录为false）'}")
        else:
            lines.append("原层保留验收：未提供明确的原层保留专项标记，未声明通过。")
    elif source_metadata:
        lines.append("提供的source_metadata（不据此推断原生可编辑）：" + _json(source_metadata))
    else:
        lines.append("未提供原生PSD元数据；未执行原层保留验收。")
    for key in ("error", "exception", "warnings", "group_failures"):
        if record.get(key) is not None:
            lines += ["", f"批次{key}：" + _value(record[key])]
    return "\n".join(lines).rstrip() + "\n"


def _matching_or_raise(path, data):
    if path.is_symlink():
        raise FileExistsError("说明目标是链接，拒绝复用或覆盖：" + str(path))
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise FileExistsError("已有说明内容冲突，不覆盖：" + str(path))
        return True
    return False


def _publish(path, data, engine):
    if _matching_or_raise(path, data):
        return
    if callable(getattr(engine, "publish_new", None)):
        try:
            engine.publish_new(path, lambda temporary: Path(temporary).write_bytes(data))
        except FileExistsError:
            if not _matching_or_raise(path, data):
                raise
    else:
        descriptor, name = tempfile.mkstemp(prefix=".delivery-notes-", suffix=".tmp", dir=path.parent)
        os.close(descriptor)
        temporary = Path(name)
        try:
            temporary.write_bytes(data)
            try:
                os.link(temporary, path)
            except FileExistsError:
                if not _matching_or_raise(path, data):
                    raise
        finally:
            temporary.unlink(missing_ok=True)
    if not path.is_file() or path.read_bytes() != data:
        raise ValueError("说明发布后内容不一致：" + str(path))


def write_notes(output_root, *, policy, jobs, batch_record, engine=None):
    """Create the two root notes, reusing only exactly identical existing bytes.

    Completion is never inferred from outputs. This is a snapshot of the supplied
    record, so pending/partial/failed stays explicit even when PSDs already exist.
    No account state, feedback log or other profile is read.
    """
    if not isinstance(policy, dict) or not isinstance(batch_record, dict):
        raise ValueError("policy和batch_record必须为对象")
    if not isinstance(jobs, list) or any(not isinstance(job, dict) for job in jobs):
        raise ValueError("jobs必须为对象列表")
    root = Path(output_root).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise ValueError("output_root必须是目录")
    documents = [(root / "使用提示词.txt", (_PROMPT.rstrip()+"\n").encode("utf-8")),
                 (root / "本批处理说明.txt", _report(root, policy, jobs, batch_record).encode("utf-8"))]
    # Check both known destinations before creating either document.
    for path, data in documents:
        _matching_or_raise(path, data)
    root.mkdir(parents=True, exist_ok=True)
    for path, data in documents:
        _publish(path, data, engine)
    return [str(path) for path, _ in documents]
