# SKC 材质保真超清 · V3

保留原技能的首色预览、确认锁版、同款补色与逐色验收。新增的是清晰度处理方式：先检查候选，按实际布片选择增强区域，保护敏感材质，再从最终文件验证。生成空模仍使用当前 ImageGen；已有完整母图的清晰度处理优先走本机 Photoshop。

已有合格成品只是网眼、帽沿或拉链偏软时，先走[区域清晰增强](regional-definition.md)，沿当前 PSD 续修；不强制重做全图 AI。V2 的材质保护仍是起点，用户点名部位可在实测后成为限定增强区。

## 先确定版本和范围

区分未增强母图、AI 候选、当前问题图和实拍。失败图保留为对照，不作为正确材质标准；返回有依据的未损坏母图时，核对并保留此前有效修复，不能盲目丢掉已通过的部位。输出沿用本批已确认尺寸，未指定时默认有效 2×；比例不同按原技能等比及补白规则处理，不拉伸衣服。

## 候选和伪影检查

需要新 AI 候选时，以未增强的完整原尺寸 RGB 白底图运行 `scripts/Invoke-AiCandidate.ps1`，UltraSharp 原生 4×再缩至候选规格。不要先缩小母图或反复增强上一轮成品。已有同一母图的候选可按输入哈希复用，记录缓存使用，不能声称重新运行了模型。

执行者查看最终交付尺度与原像素裁片，至少覆盖本图实际可见的这些部位：

| 部位 | 拒绝信号 | 处理 |
| --- | --- | --- |
| 网眼、细密织纹 | 孔型/密度改变，粗格、指纹状弯线、假孔、纹理断层 | 保留未损坏母图像素，排除该候选区域；需要真实细节时用实拍保真路线 |
| 反光包边、针脚 | 新增碎白斑、双边、掉漆感或深黑描边 | 区分原有真实反光，避免全擦除；保护包边或减弱增强 |
| Logo、印花 | 点阵连成线、字形/位置变化、光晕 | 保护已核准原标识，拒绝改字形的候选 |
| 拉链、缝线 | 齿纹重排、黑线、断齿、颗粒 | 仅原位少量滤镜，复查强度；不生成替换件 |
| 普通衣身 | 新纹理、砂粒/塑料感、褶皱被改画 | 缩小允许区域、降低增强贡献或回退 |

局部更清楚不能抵消任一新差异。执行者记录真实观察；脚本不能自动判断面料是否正确，也不能把 hash 检查当成视觉通过。没有可辨依据时保持限制，不编造微纹理。

## 材质区域配置

`scripts/prepare_profile.py` 读取源图和候选，创建绑定 SHA-256 的待核配置。它不修图，不自动批准候选；技术字段由执行者依据实际看图填写，不能要求用户填写蒙版坐标或批准脚本参数。

```powershell
python .\scripts\prepare_profile.py --source 'D:\images\master.png' --candidate 'D:\work\candidate.png' --size 3000 4500 --output 'D:\work\profile.json'
```

配置 schema=2：

- `reference_size/output_size`：定位画布和最终像素；各多边形坐标以 reference_size 的左上角为原点。
- `candidate_review`：未核为 pending，失败为 rejected；实看通过的区域可记 approved_for_regions，并写具体观察。换输入哈希后重新核对。
- `ai_regions`：仅列有依据且通过小样的普通面料允许区，每区记录 id、polygon、review=approved、notes；没有允许区时不能整图套增强。
- `protected_regions`：实际网眼、包边、Logo、接缝、遮挡及背景保护区；从允许蒙版中扣除。查看边界语义，不能只验像素范围。
- `ai_opacity/feather_px`：按该图和输出尺寸试定，不把本次的 25% 或羽化 16px 当通用参数。
- `zipper`：默认 disabled。需要时填写本图 polygon、amount、radius_px、threshold、opacity、feather_px。仅原有完整图层像素；不导入、合成或贴入新拉链。

未检查/拒绝候选、源图或候选哈希改变、区域未核准会被运行入口阻止。视觉判断仍由执行者完成，这不是自动伪影检测器。

## 运行与分层

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-WholeImage.ps1 -InputImage 'D:\images\master.png' -AiCandidateImage 'D:\work\candidate.png' -ConfigPath 'D:\work\profile.json' -ProblemImage 'D:\images\problem.png' -OutputDirectory 'D:\result' -OutputStem 'style_color_front_v2'
```

ProblemImage 可选；提供时需与交付画布同尺寸，以完整像素保留问题版。最终 PSD 包含未修改问题图、嵌入式完整原生母图、可见未增强底图、AI 允许区增强层及可选原位拉链层。增强层是完整画布像素，配实际可编辑蒙版；未进入允许区的材质保留底图，AI 层采用明度混合以控制颜色漂移。原始高分辨率母图作为隐藏智能对象保留，先栅格化其副本作为稳定可见底图，避免智能对象预览重建导致保护区取整波动。

入口保存并重开 PSD，检查原图、原生智能对象与蒙版，再导出同版 PNG。运行记录先标 pending_final_file_review，不自动标视觉通过。历史拉链 400% 配置只作个案记录；旧 Invoke-Zipper 也要求当前源图哈希和实际核图记录，不能自动执行历史强参数。

## 最终文件验证

从实际 PNG 和重新打开的 PSD 检查：

1. 同一商品尺度对照问题版、新版和实拍，原像素检查网孔、包边、Logo 与拉链；参考不同视角时说明尺度限制。
2. 从实际图层蒙版核对修改范围；保护区和蒙版外与同尺寸未增强底图应逐像素一致。不能用允许误差掩盖保护区变化。
3. 原始问题图完整像素保留，嵌入母图保留原生像素；修复层与未烘焙蒙版可编辑。
4. PNG 与重开 PSD 的可见效果一致。Photoshop 缓存合成与 PNG 导出可能有 1/255 量化取整差，单独记录；此容差仅用于缓存比较，不放宽保护区零差异。
5. 明确视觉判断、程序验证与用户采用的区别。失败候选留在 work；只交付已核的 PNG、PSD 和对比，未解决项保留状态。

## 环境

Windows x64、Vulkan 显卡、本机 Photoshop；实测 RTX 4060、Photoshop 21.2.12。AI 候选无需 CUDA/PyTorch；Python/Pillow 仅辅助核图与配置准备。执行脚本和 Photoshop 使用同一 Windows 账户/权限级别。COM 80080005 先查权限与注册，不重跑 AI。超时先确认引擎恢复及输出状态，避免重复提交。

透明图沿用原 SKC Alpha/蒙版流程；这些辅助脚本面向不透明 RGB 白底图。PNG compression=1 为无损。模型作者许可 CC BY-NC-SA 4.0，商品商用前确认相应授权，见[来源与许可](third-party.md)。[本次真实图片回归](real-image-regression.md)记录已验证的范围，不代表其他款自动通过。
