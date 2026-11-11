---
name: chutu-chicun-tiaozheng
description: 电商主图和场景图裁切及数据包交付，按用途多选尺寸，同尺寸编号并整批分组预览确认。主图可直接用JPG/PNG，Python调整尺寸并额外交付对应PSD；实际放大提示可能变软、建议PS，由用户选PS或Python；图片500KB，不抠图换背景。
---

# 出图-尺寸调整（主图场景与整批预览版3.4）

按本次商品和用途逐图规划构图。先分main主图或scene场景，用途不由尺寸猜测。主图和场景图均可直接使用JPG、PNG或已有PSD；默认用Python调整尺寸，并额外生成每款每尺寸一份汇总PSD，无需先把照片转成PSD。PSD输入当前支持平坦纯像素层和位图蒙版；已有group源不支持，包括本包输出的1—N分组PSD再次输入。复杂文字、智能对象、矢量、效果、组或其他未安全支持特征须说明限制，由用户选PS或提供兼容副本，不能假支持、自动flatten或自动切PS。

本机Photoshop COM原生路径尚未通过实机验收；不阻断已支持的Python路径。人工选PS后连接/结构验收失败应如实停止，不能自动退回Python。PS也不保证找回缺失像素细节。详见[delivery.md](references/delivery.md)。

## 运行与本批信息

读runtime.json，使用专用Python或scripts/run_resize.ps1、scripts/run_profile.ps1。正式入口scripts/resize_assets.py，先用user_profile.py status读取当前Windows账号已批准规则，正常不传--state。安装及批准流程见[windows-portable.md](references/windows-portable.md)，不复制其他账号状态或批准。

缺项合并收集，已给信息不重问：

1. 明确main/scene、款号、输入、主体、数量与新输出目录。前N张按自然文件名排序固定清单；截图每5张只是例子，不限制本批图数。
2. main提供800×800、1440×1440、750×1000和自定义；scene提供750×1000、800×800、800×1200和自定义。支持多选，只出本批所选，不默认全选，不能沿用旧版一套通用预设。
3. 同尺寸图片默认1—N，每个尺寸从1重新编号，固定编号无需再问图片命名。PSD默认款号_尺寸，每款每尺寸1份，内部层/组仍1—N。告知默认方案即可；用户明确自定义后再覆盖，不把旧人工命名模板当默认。naming_source只表示spec配置来源，不等于真人授权。
4. main和scene均可直接使用JPG、PNG等原始照片或已有PSD；同单照片与PSD不混合。PSD是额外交付，不是主图的输入前提。已有PNG未改格式时保留PNG及alpha；PSD未指定成品格式默认JPG并告知，透明部分按JPG白底合成，需要透明可选PNG，format不新增必填阻断。

一份PSD内有多图不会自动拆job。用户明确取01—05等层/颜色范围后，每张建立同一input、不同source_layers的job，白底选对应商品和真实背景层，透明不加背景。保留的是所选源层子集，metadata须说明并非master所有层，未选范围不能自行拆。人工选PS且有source_layers时，仅对受支持平坦pixel源先Python原尺寸无缩放提取，再由PS真正目标重采样；复杂/group源按图提取暂须先在PS拆独立源文件，不能忽略selector。示例见[framing.md](references/framing.md)。

本版不做白底生成、抠图或换背景。已有白底PSD仅改尺寸且背景原样保留时按PSD源能力与明确范围处理。

## 放大选择先于整轮目标预览

PSD输入或含PSD交付的正式任务均需检查，照片业务也适用。按实际source_viewport计算scale_x=目标宽/取景宽、scale_y=目标高/取景高、scale=max两者。scale>1即风险，不按1440一刀切。

先检查整轮候选，聚合所有未作选择的放大项，按尺寸/明确范围一次展示源尺寸、取景框、目标与比例，提示可能模糊或细节变软，建议使用Photoshop（PS）进行放大处理，由用户选择PS或继续Python；建议不代表自动选择。PSD格式本身不提升清晰度。返回requires_backend_choice时不生成该轮任何目标尺寸预览或正式输出，不偷偷默认Python。仅安装合成PNG或无PSD交付的几何诊断不冒充业务决策。

已明确绑定本批源/内容、实际裁切、目标尺寸的后端选择直接复用，不重复问；改变任一依据使选择失效，重新聚合提示。选择仅在真实范围有效，不学成永久自动放大。Python默认、整批确认和风格授权都不替代尚未作出的后端选择。历史案例的成功检查只对应该次源与目标，不批准其他任务。

## 默认整批分组预览与确认

读[product-focus.md](references/product-focus.md)，逐图观察商品、朝向、遮挡、边界，设置focus/crop_box/protect_box；不统一套坐标。等比、不拉伸、不新增补边依已批准规则与本次明确覆盖；冲突说明，不缩保护框绕过、不补造源图缺失部分。

默认review_mode=batch：后端选择齐备后一次生成整批全部预览，同尺寸放一起，每个尺寸有1—N编号总览和单张候选，方便集中确认和点名“800×1200第3张”修改。通过groups映射找到全局候选index再review-adjust-item；不能把尺寸内编号直接当全局index。调整后刷新该轮预览/摘要，依据变化重新过后端选择。

展示全部尺寸分组与预览，取得绑定最新digest的真实整批人工确认，再batch --review正式输出。不把分组整批确认记成逐张人看，不因工具生成预览就猜用户已确认。旧review-next/confirm仅在用户明确要求单张方式时使用，不能继续把它当默认。命令见[framing.md](references/framing.md)。

## 交付与真实记录

- JPG/PNG实际≤500000字节且像素尺寸不变；JPG可降合理编码质量，PNG仅无损优化，不能擅自量化、去alpha、缩尺寸或转格式，达不到须报告。PSD和说明不受此限制。
- 图片/尺寸/1.jpg…N.jpg或相应PNG；源文件/款号_尺寸.psd。N图、S尺寸为N×S图片和S个PSD，每款每尺寸1份，层/组1—N，默认仅1可见。照片PSD从无损像素缓存构建，不从压缩JPG重建；PSD源保层以实际支持与验证为准。
- 使用提示词.txt和本批处理说明.txt记录真实kind、presets、size_selections、naming及来源、review_mode、preview_groups与确认来源/原文、actual backend、scale/risk/basis、字节/质量和完成/失败状态。缺记录不猜执行；默认Python不称人工选择，整批确认不称逐张人看。

## 反馈与异常

全批成功后只询问一次反馈。按用途、品类、尺寸、源/结果和真实反馈提炼适用条件，不把案例坐标或一次选择提升为长期固定规则。明确长期立即提案，普通同类反馈3个不同批次再提案；验证、展示差异与预览后真实批准，见[feedback-workflow.md](references/feedback-workflow.md)。

保留完成/失败/待处理清单与可信PSD发布检查点。--resume仅复用本批哈希一致的已完成结果，不覆盖未知同名文件、不从JPG重建；缓存清理失败仅警告。缺交付项不标整批完成，异常不自动回退；规则回退需用户批准，保留当前及前两版共3版。固定入口/后端选择/验证器升级须审阅，不能借图片任务改个人状态。

