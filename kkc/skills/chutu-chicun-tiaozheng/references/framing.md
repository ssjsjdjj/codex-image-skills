# 3.4用途选项、整批预览和调整命令

下文python替换为runtime.json专用解释器，路径绝对、JSON为UTF-8。先确定main或scene：

~~~powershell
python scripts/resize_assets.py delivery-options --kind main
python scripts/resize_assets.py delivery-options --kind scene
~~~

main预设800x800、1440x1440、750x1000；scene预设750x1000、800x800、800x1200，各支持多选及合法自定义，只出所选。不要把截图每5张当固定数量。

~~~json
{
  "delivery": {
    "kind": "scene",
    "style_id": "实际款号",
    "out_dir": "D:/工作/新数据包",
    "sizes": ["750x1000", "800x1200", "1200x1600"],
    "max_bytes": 500000
  },
  "product_focus": {"category": "裤子", "emphasis": "裤型和裤脚"},
  "jobs": [
    {"input": "D:/素材/原图1.jpg", "focus": [0.5, 0.7]},
    {"input": "D:/素材/原图2.jpg", "focus": [0.55, 0.7]}
  ]
}
~~~

naming缺省numbered：每size图片从1编号到N；PSD默认款号_尺寸，内部1—N。无需再问固定图片命名。用户后来明确自定义时可提供naming覆盖，不能默认套旧style_size_index模板。naming_source只说明配置来源。main和scene均可直接输入JPG、PNG等照片或已有PSD，同单照片与PSD不混合；默认Python调整尺寸并额外交付每款每尺寸一份PSD，不要求照片先转存PSD。PNG默认保持alpha，JPG保持JPG；PSD未设图片format默认JPG并告知，透明部分白底合成，需要透明可选PNG，format非新增必填。

## 多图PSD的选择

Python输入只支持平坦pixel层及位图mask，已有group源不支持，包括本包输出group1—N再次输入。复杂/组源提示用户选PS或兼容副本，不自动flatten或假支持。

一个input不自动拆内部多图。用户明确取01—05后，按实际层名建立独立job；示例名不是固定标准：

~~~json
{
  "jobs": [
    {"input": "D:/素材/多图源.psd", "source_layers": ["01", "背景"]},
    {"input": "D:/素材/多图源.psd", "source_layers": ["02", "背景"]},
    {"input": "D:/素材/多图源.psd", "source_layers": ["03", "背景"]},
    {"input": "D:/素材/多图源.psd", "source_layers": ["04", "背景"]},
    {"input": "D:/素材/多图源.psd", "source_layers": ["05", "背景"]}
  ]
}
~~~

白底含真实商品/背景层，透明不加背景；未选范围不能自行拆。所选源层子集须在metadata说明，不等于保留全部master。选PS且有selector时，仅受支持pixel源先Python原尺寸无缩放提取，再由PS做目标重采样；复杂/group源按图提取须先在PS拆独立源文件，不能忽略selector。

## 先聚合后端风险，再整批目标预览

~~~powershell
python scripts/resize_assets.py review-start --spec "D:/工作/本批.json"
python scripts/resize_assets.py review-preview-all --review "<review_id>"
~~~

默认Python，但PSD输入或含PSD输出业务须先对全部候选按实际source_viewport算scale=max(目标宽/取景宽,目标高/取景高)。scale>1的未选项先聚合返回requires_backend_choice，按size/明确范围一次告知倍率及可能模糊、细节变软，建议用Photoshop（PS）进行放大，由用户选择PS或继续Python。建议不代表自动选择，PSD格式本身不提升清晰度。该轮任何目标预览或正式输出都要等待所需选择齐备，不能偷偷给未选项默认Python。

~~~powershell
python scripts/resize_assets.py review-select-backend --review "<review_id>" --backend python --size "800x1200" --confirmation-file "D:/工作/真实后端选择.txt"
python scripts/resize_assets.py review-select-backend --review "<review_id>" --backend photoshop --indices "1,3" --confirmation-file "D:/工作/另一范围真实选择.txt"
python scripts/resize_assets.py review-preview-all --review "<review_id>"
~~~

indices是明确全局候选index范围，必须按实际返回的候选映射填写，示例不是自动范围。确认文件写真实用户原文。已绑定同源/内容、裁切和目标的选择复用，不重问；改变任一依据失效。PS也不保证找回缺失细节，当前PS COM未通过实机验收，选PS失败不自动换Python。安装合成PNG/无PSD几何诊断不作业务人工决定。

## 分尺寸总览、点名调整、整批确认

预览一次生成整批，同size放一起，每size有1—N编号总览与单图。用户说“800×1200第3张”时，从返回groups找到对应全局candidate index，不能把3直接当global index：

~~~powershell
python scripts/resize_assets.py review-adjust-item --review "<review_id>" --index "<groups对应全局index>" --patch "D:/工作/指定张调整.json"
python scripts/resize_assets.py review-preview-all --review "<review_id>"
~~~

patch如{"focus":[0.5,0.42],"zoom":1.05}，null删除可选项。裁切basis变化先更新风险/选择，再出新目标预览。向用户展示全部所选尺寸分组、编号及最新摘要：

~~~powershell
python scripts/resize_assets.py review-confirm-all --review "<review_id>" --digest "<最新整批预览digest>" --confirmation-file "D:/工作/真实整批确认.txt"
python scripts/resize_assets.py batch --review "<review_id>"
~~~

整批确认须是真人针对最新预览的真实原文，不从沉默或预览生成推断确认；不称逐张人类看过。用户明确要求单张方式时可用旧review-next/review-adjust/review-confirm，不能继续作为默认。整批确认/风格授权均不替代放大后端选择。规格变化另建任务，命名按明确需求更新且须以最终预览/摘要确认。

## 恢复与参数

~~~powershell
python scripts/resize_assets.py batch --review "<review_id>" --resume
~~~

恢复须源、规则版本与既有产物哈希一致，已完成图片/PSD不重写；待发布PSD凭隔离暂存及可信哈希恢复，不从压缩JPG反推。JPG/PNG≤500000B，PSD/TXT不限500KB。

crop_box/focus/protect_box/subject_box/position/offset/zoom/subject_fill继续支持，框基于EXIF纠正源图归一化，逐图观察不固定坐标。补边/拉伸仅在本次明确允许和实现范围；不支持的PSD变换报限制。旧无delivery队列仅低层诊断，不能冒充3.4数据包。

