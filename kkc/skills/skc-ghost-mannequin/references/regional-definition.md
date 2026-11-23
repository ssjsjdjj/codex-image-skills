# 已有成品的区域清晰增强 · V3

用于整体和材质已合格、但网眼/帽沿/拉链等仍轻微软的结果。沿当前有效 PSD 和同版 PNG 续修，保留此前有效修复。没有足够原像素时不编造网孔、针脚或齿纹；若图中已经有假格纹或碎白斑，先按保真回退流程处理，不能在错误纹理上再锐化。

## 定位与小样

1. 核对当前 PSD/PNG 同尺寸、同版本、可见状态，记录两份文件的 SHA-256。用户明确点名后，原默认保护部位可以成为本轮限定增强区；不把“保护”理解成永久不得提清晰度。
2. 在实际画布上沿布片画多边形，覆盖同材质全部可见部分，包边、接缝、遮挡和背景留合理缓冲。微距实拍只说明材质表现，不直接决定整图孔径或搬入不同姿态的褶皱。
3. 用当前完整图层像素做小半径镜头去模糊，各材质单独试强度；小样也是整图副本，不单独生成或合成拉链。对比原像素及最终显示尺度，检查更清楚的同时有没有粗纹、黑边、白斑、色偏。

## 方法与边界

本模块仅使用现有像素和 Photoshop 原生智能锐化。每区复制完整当前可见 PNG，滤镜仅作用于该选区，用独立可编辑蒙版控制；采用 DARKEN 贡献限制新增亮边。它保留已有细节布局，不会像生成模型那样重画网孔，但强度过大仍可能造成暗描边、粗黑孔或颗粒，必须实际看图。

高光淡化与亮边限制应分开评估：本案例在已有变暗混合限制时再用很高的高光淡化，清晰增量过弱；随后减少冗余衰减取得适度清晰提升。此观察不能推广为所有材质固定用低衰减。半径、降噪、强度与不透明度都依当前像素和面料试定，不能整批套本案例数值。

本机白底辅助模块会从当前 PNG 生成临时背景保护选区，扣除纯白及近白边界，合入实际区域蒙版，最后删除本次临时通道，保留原 PSD 的其他通道。适用于已核的8位RGB白底成品；透明图、高位深或其他色彩模式不能硬套。

## 配置与执行

`references/tested-regional-profile.json` 是本轮马甲的实测配置，只能配相应输入哈希和3000×4500画布。其他款、版本、裁切或尺寸必须重新定位和核图，不能直接照搬多边形或参数。配置由执行者根据实际看图生成，用户无需填写技术字段或额外批准内部小样。

schema=3 包括：

- baseline_png_sha256/baseline_psd_sha256、reference_size：绑定当前有效文件与画布。
- source_review.status=reviewed_baseline、notes：记录实际基线核准依据；不是自动识别结果。
- regions：各区 id、notes、polygons（可含多个同材质多边形）、feather_px、智能锐化 amount/radius_px/noise_reduction/highlight_fade/highlight_width/shadow_fade/shadow_width/tone_radius、opacity、blend=DARKEN。
- protected_regions：本轮仍需排除的实际部位，例如 Logo。点名的网眼不再作为整块保护区，白底仍排除。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-RegionalDefinition.ps1 -InputPsd 'D:\result\accepted.psd' -InputPng 'D:\result\accepted.png' -ConfigPath 'D:\work\regional-profile.json' -OutputDirectory 'D:\work\trial' -OutputStem 'style_trial' -PreviewOnly
```

小样通过后去掉 PreviewOnly，以新文件名输出 PSD/PNG。各候选从同一有效基线独立生成，不相互叠加。默认保留输入PSD全部图层，新增精确当前 PNG 底层和按区增强层；PSD保存后重开，确认新蒙版及混合模式再导出PNG。

## 最终验收

- 原像素和交付尺度都看过，三处相对基线确有清晰增益；孔型、疏密和方向未变粗变形，帽沿无白斑/双边，拉链无重画或描黑。
- 原图和上一版有效图层、智能对象与蒙版保留。开关新增强层可比较，修复层均有独立未烘焙蒙版。
- 从实际新蒙版确认目标范围；蒙版外、Logo、普通衣身及背景与上一版 PNG 逐像素一致。纯白背景不能进入新蒙版，临时通道清理后与输入通道数量相符。
- DARKEN 的“无新增变亮像素”是亮边控制证据，不是织纹真实性或无黑边的证明；仍以实拍和目视判断。
- PSD重开合成与PNG可见效果一致；缓存量化差最多1/255时单独记录，不用于放宽蒙版外零差异。

未通过则保留当前有效基线；只有新证据或方法依据再调整，不无限堆强度。程序通过、模型目视通过与用户采用分别记录。[本轮真实图片实测](regional-definition-regression.md)及具体配置随包提供，不含业务照片或成品。
