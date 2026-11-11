# 3.4用途、交付与真实性

## 用途、尺寸与编号

先选main主图或scene场景，不用尺寸猜用途：

- main：800×800、1440×1440、750×1000，加合法自定义。
- scene：750×1000、800×800、800×1200，加合法自定义。

两类均多选，只出所选；尺寸范围1—10000。截图每5张是举例，实际数量按明确输入。policy保留实际kind、presets、size_selections[{size,source:preset|custom}]，配置来源不冒充真人授权。

默认naming为numbered：图片在每个尺寸目录独立1—N编号；PSD为款号_尺寸，每款每尺寸一份，内部层/组1—N。固定编号无需每批重新问图片命名，可告知PSD默认名；用户明确自定义图片/PSD名时才override。naming_source=default|explicit说明spec配置来源，不等于真实人工确认。

~~~text
款式数据包/
  图片/
    已选尺寸A/1.jpg ... N.jpg
    已选尺寸B/1.jpg ... N.jpg
  源文件/款号_尺寸A.psd
           款号_尺寸B.psd
  使用提示词.txt
  本批处理说明.txt
~~~

N图、S尺寸为N×S张图片、S份PSD。各PSD面板从上到下1—N，默认仅1可见。不同款分单。main和scene均可直接使用JPG、PNG等照片或已有PSD，同单照片与PSD不混合；默认Python完成尺寸调整并额外交付对应尺寸PSD，不要求照片先转存PSD。照片PSD从无损渲染像素构建，不读压缩成品JPG重建，也不声称恢复文字/矢量等原生编辑源层。

已有PNG未改格式时保持PNG/alpha；已有PSD未指定图片format默认JPG并告知，透明区域按JPG白底合成，需要透明可选PNG。format不新增必填。图片真实文件≤500000字节，保持所选像素尺寸；JPG允许合理降编码质量，PNG仅无损优化，不擅自量化、去alpha、缩尺寸或转JPG，预算无法达到就报告。PSD与说明不受图片限制。

## PSD实际支持边界

Python默认支持平坦纯pixel层与位图蒙版，不支持已有group源，本包生成的1—N分组PSD再次作为Python输入也不支持。复杂文字、智能对象、矢量、效果、组、色彩/位深等超出支持时提示限制，由用户选PS或提供兼容副本，不能假支持、自动flatten或自动切PS。

一份PSD的内部多图不会自动变多个job。用户明确选层/颜色范围后，每图用相同input、不同source_layers建job，白底含对应商品和真实背景层，透明不额外加背景。未选范围不能自行拆；metadata注明保留所选源层子集而非master全部层，all_layers_preserved=false。

选PS且有source_layers时，受支持平坦pixel源先Python原尺寸无缩放提取，再由PS执行真正目标重采样。复杂/group源按图提取暂需先在PS拆独立源文件，不能忽略selector或以当前整幅合成替代。

本机PS COM原生路径尚未通过实机验收；不阻断受支持Python路径。人工选PS后环境或结构失败就如实停，不自动退Python。两种插值均不保证找回缺失像素细节。

## 风险先聚合、预览整批确认

PSD输入或含PSD交付的业务先按实际source_viewport算scale=max(目标宽/取景宽,目标高/取景高)。scale>1即风险，不按1440固定判断。先聚合本轮所有未选放大项，按尺寸/明确范围一次提示倍率和可能模糊、细节变软，建议使用Photoshop（PS）放大，由用户选择PS或继续Python；建议不代表自动选择，PSD格式本身不提高画质；未选返回requires_backend_choice，不生成该轮任何目标预览或正式输出。已绑定源/内容、裁切、目标的真实选择直接复用，改变依据失效，不学成永久自动放大。无PSD交付的安装合成PNG/几何诊断不代替业务决定。

默认review_mode=individual。风险选择齐备后，一张一张生成对照预览；真实确认当前张后才能预览下一张。全部候选逐张确认后正式导出；记录每张确认原文和digest，不使用整批确认或风格授权跳过。详见framing.md。

## 记录、恢复与验收

说明按真实policy/jobs/batch快照记录kind/presets/size_selections/naming/source_type、review_mode、preview_groups、preview_confirmation实际来源/原文/摘要/范围、actual backend、scale/risk/basis、编码字节/质量、PSD层名数量及完成/失败状态。未提供processing不猜执行后端，default_python不写人工选择；有确认对象不等于整批已完成，未执行的结构/编辑性/清晰度/PS环境不写通过。

PSD隔离暂存验证、持久化哈希检查点后发布；中断恢复只接受本批可信暂存与匹配已发布哈希，不覆盖未知同名PSD。已完整交付后缓存清理失败仅警告，不降成失败。部分失败如实保留已完成清单。

当前帽子白底PSD曾经明确授权Python800→1440，11像素层及蒙版通过337项独立检查，只展示粉色01。它仅对应该源/该次尺寸与裁切，不授权其他输入，也不证明PS插值一致或所有PSD类型。历史测试数量不冒充3.4新验收；验收以本版实际记录为准。白底生成、抠图、换背景不纳入；已有白底PSD仅改尺寸、不改背景时按明确任务处理。

