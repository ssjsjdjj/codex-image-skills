# 任务单与执行接口

运行入口为专用Python执行`scripts/launch.py`，或用`run_bg.ps1`转发同样的参数。旧版的直接`make/batch`工作流不适用于V2，单图也先预览。

## 任务单

```json
{
  "schema_version": 2,
  "defaults": {
    "out_dir": "D:/商品/正式输出",
    "separate_image_folders": true,
    "fill": 0.8,
    "cutout": "rembg"
  },
  "jobs": [
    {"style": "款式A", "color": "粉色", "angle": "正面", "input": "D:/素材/正面.jpg"},
    {"style": "款式A", "color": "粉色", "angle": "侧面", "input": "D:/素材/侧面.jpg"}
  ]
}
```

`separate_image_folders`必须是JSON布尔值。true输出`款式/白底图/粉色-正面.jpg`、`款式/透明图/粉色-正面.png`；false输出`款式/粉色-正面-白底.jpg`和`款式/粉色-正面-透明.png`。每款两份PSD始终为`款式/款式-白底.psd`、`款式/款式-透明.psd`。

可选字段均可放在对应job中，不默认加到所有任务：

- `keep_mask`：绝对路径灰度PNG，白色区域从原图恢复RGBA，用于保留误删的主体；黑色不动，灰色按比例混合。它同时保护该区域不被自动净化。
- `remove_mask`：绝对路径灰度PNG，白色区域透明alpha清零，灰色按比例降低alpha；只清理用户指定的背景。不能因为封闭孔洞、镜片反光或零碎区域而自动生成删除意图。
- `protect_mask`：绝对路径灰度图，非黑区域保护已有抠图像素，既不恢复原图，也不强制变为不透明。
- 三类蒙版尺寸必须与EXIF转正后的原图一致；`remove_mask`与保留/保护区域有重叠时报错。使用零蒙版可测试接入，不会改变像素。
- `review_regions`：800×800确认画布上的矩形列表，如`[[420,180,570,325]]`，每项为`[left,top,right,bottom]`。诊断优先提供该区域的白/深灰/黑底100%对照；只影响检查位置，不修改图像。
- `repair_existing_alpha:true`：用户要求修改已有透明图边缘时才用，必须为JSON布尔值。明确提供keep/remove蒙版会执行该局部编辑，即使已有透明输入没有开启自动净化。

蒙版内容和局部坐标属于具体任务素材，保存在任务目录，不能写进通用技能代码。编辑在原分辨率完成后再统一缩放。`*-full-alpha-before-edits.png`记录人工蒙版编辑前状态；`*-full-alpha.png`是局部编辑后原分辨率结果。色彩净化候选只调整软边RGB，不改变alpha或不透明内部。

## 执行

以下所有路径替换为实际绝对路径。缓存每轮使用新目录；已有目录不会被覆盖。

```text
plan --spec D:/工作/job.json
preview --spec D:/工作/job.json --cache D:/工作/cache-v1 --out D:/工作/preview-v1.png --limit 0
```

`preview`处理全部输入，`--offset/--limit`只限制该预览的展示范围，默认limit=0展示全部。缓存包括`state.json`、EXIF转正原始素材、原分辨率初抠图及原分辨率修订候选、800px初版和受保护修复候选、每图四背景诊断。高清候选与800px候选逐一绑定并校验。正式写入数始终为0。首版边缘指标是启发式提示，未做跨品类误报率标定。

查看每图`*-diagnostic.png`以及全批预览，记录实际观察结果：

```json
{
  "reviewer": "当前聊天AI视觉复核",
  "items": [
    {"index": 1, "status": "passed", "note": "已查看白灰黑背景和局部；疑似深色为原图帽檐缝线，发丝与细绳保持；未见明显残留"},
    {"index": 2, "status": "hold", "note": "右侧头发与背景边界不明确，需要用户判断"}
  ]
}
```

示例句子不能直接复制为真实结论。只有实际查看后才可填写。

```text
review --cache D:/工作/cache-v1 --decisions D:/工作/review.json
choose --cache D:/工作/cache-v1 --index 1 --candidate initial
```

`choose`可选`initial/repair1/repair2`，后两者仅在保护检查通过时存在可用候选。切换会刷新全批预览并清空该图复核状态；自动选择同样不等于视觉通过。存在无法自动解决的残留时可制作新的受控透明输入、记录与原图关系，再建新缓存预览，不硬编码某款图片坐标进通用技能。

用户退回某图时记录真实反馈，旧确认随即失效：

```text
feedback --cache D:/工作/cache-v1 --index 1 --evidence 用户指出人物周围有黑线
```

全部AI复核通过后向用户展示当前全批预览。得到明确确认后才记录：

```text
approve --cache D:/工作/cache-v1 --actor 用户 --evidence 用户在本聊天明确确认当前预览可用并同意生成
```

返回`approval`文件路径。该文件是操作证据记录，不是身份认证服务；AI不得自行伪造用户确认。

```text
batch --spec D:/工作/job.json --cache D:/工作/cache-v1 --approval D:/工作/cache-v1/实际返回的确认文件.json --manifest D:/工作/files.json
```

源文件、任务单、任一蒙版、处理代码、预览/诊断图、候选或复核记录变化会使确认失效。确认记录绑定文件哈希、解码RGBA哈希和版本；导出前及正式写入前再次检查。导出不会重新抠图，也不从320px预览放大。manifest位于正式输出目录之外。读取返回的`passed`、`verification`及输出哈希后再报告成功。

## 状态与保真边界

- `no_numeric_alert`仅表示数值指标未报警，`suspected`表示疑似，二者都要看图。
- 黑色服装、深色发丝和真实缝线可能正常；孤立区域可能是配件或绳线。
- `visual_review`与`approval`分开；无远程视觉后端时不能声称已经后台无人值守看图。
- 原图截断、透明材质和真实遮挡应记录限制，不补造商品结构。
- 两档候选仅净化半透明疑似边缘，每通道最大改变量为16/24，alpha、细线保护区和不透明内部保持一致。内部残留背景只能用明确局部蒙版纠错，边缘风险下降不能证明语义正确，仍需视觉复核。
- 失败时返回非零并保留现场；不自动删除原图或覆盖已有成品。

技术参考：[Adobe边缘杂色](https://helpx.adobe.com/photoshop/desktop/make-selections/refine-modify-selections/fringe-pixels-around-a-selection.html)、[PyMatting前景估计](https://pymatting.github.io/foreground.html)。

## 高清像素层与独立蒙版PSD

本版JPG/PNG仍为800×800。PSD每款共用高清正方形画布，边长至少800px，按各输入的抠图范围与fill计算，确保商品层不向下采样。小图可能放大以匹配同款占比，放大不会增加原有细节；清单记录每款画布及各层缩放与位置。超过PSD单边30000px限制时报错，不自动缩小素材。

产品层保存完整源图范围内RGB，抠图结果为独立灰度蒙版，包含半透明边缘。原图中被抠掉的区域仍有像素，可通过修改/禁用蒙版恢复；输入本身缺失的像素不能补回。选定的高清修订候选负责边缘颜色，删除区回填原图RGB，不改变蒙版透明度。

隐藏的「原始素材（隐藏）」组按颜色/角度保存EXIF转正、未经缩放的原始素材和原始alpha蒙版，组及组内各层默认隐藏。源图层可能超出画布范围，像素仍保存在PSD内，可扩大画布查看。白底版多一个背景层；透明版没有白色背景。

导出两份PSD后重开检查高清尺寸、名称、蒙版、RGB和偏移，逐层比较高清合成，核对原始素材未缩放且禁用蒙版可恢复被遮像素。800px PNG必须与确认缓存逐像素一致；高清PSD与PNG来自同一候选，跨尺寸插值不保证像素完全一致。普通像素层仍会在后续变换时重采样，需要回退时使用未缩放原始素材。


## 2.1计时

每次入口命令加相同--journal-root。自动步骤及人工检查命令见[timing.md](timing.md)，保留原有预览确认与像素验证约束。
