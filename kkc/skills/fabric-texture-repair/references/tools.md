# 工具与批量：按需读取

先按[repair.md](repair.md)的细腻标准制作和检查候选，再选当前可用且宿主允许的合成路径。原生Photoshop流程与下文Python脚本是两条可选路径，不要求重复合成或把原生PSD强行转换成脚本job。

Python脚本负责原始裁片、内容缓存、蒙版回贴和文件校验，**不识别面料、不生成候选、不自动目视通过**。简短单图口头检查无需建任务单；采用脚本路径时依赖本机Python、Pillow、NumPy、psd-tools 1.25+。缺失时报出，不自动联网安装。数据与候选保存在任务work，不能放进技能目录；宿主限制图像编辑途径时，遵从限制，脚本只做获准的准备或校验工作。

## 原生Photoshop路径

适用于需要原生修复层、混合模式、精细边界或已有PSD的任务。沿用下文相同的范围、版本和验收要求，记录可从简，不伪造脚本receipt或audit通过状态。

1. 先确认打开文档及目标文件。保留完整原图和必要的当前有效基线，不假设启动时已有活动文档；逐图保存，同一PSD写入串行。
2. 原尺寸裁片保存坐标，候选须保持同一构图和纵横比。生成结果只有采样尺寸不同且几何一致时，可在原生工具中按原裁片尺寸等比例重采样并检查配准；形状、透视或构图变化不靠拉伸修正。记录映射，检查颜色配置。脚本compose仍要求输入候选事先与box完全同尺寸。
3. 创建实际允许蒙版，并核对遮挡和材质边界。暂存选区到辅助Alpha通道后，显式切回RGB复合通道再导入、复制或修改像素；操作后检查目标文档、图层数量和像素位置，避免把像素处理写入选区通道或原图层。
4. 将合格微纹理放入独立修复层，使用未烘焙图层蒙版。若需减弱旧粗纹或亮边，单独保留相应处理层；强度按图判断。先检查蒙版的语义范围，再检查变化是否限于允许范围，尤其是皮肤、白包边、Logo、缝线和同色背景。
5. 保存前只删除本次创建的临时辅助通道；保留原文件的有效透明度、用户通道及图层蒙版。原图为不透明RGB且无用户Alpha时，输出文档应保持RGB三通道，避免辅助选区被查看器误当整图透明度。已有透明源图不套用“三通道”限制。
6. 保存分层PSD并重新打开，从重开的当前可见状态导出同版PNG。核对尺寸、色彩配置、原图/基线像素、可编辑层与蒙版、PNG与PSD存储合成，以及保护区和允许范围外无变化；再完成原像素与整件目视验收。关闭时不将检查用的隐藏图层状态覆盖到正式PSD。

仅在确有需要时校验其他查看器兼容性；没有成功打开观察，不声称该查看器已验证。模型目视、实际人工确认和用户采纳分别记录。

## 1. 检查清单与证据

由助手根据真实图片建立JSON，用户无需填写。路径相对清单文件；坐标都是**原文件EXIF转正后的像素**，不能直接使用聊天缩小图坐标。`box`为左、上、右、下，右下不包含。每张图的id唯一，每个同面料组限定商品对象；组内区域id唯一。

```json
{"schema":1,"images":[{"id":"S01","source":"ai.png","groups":[
  {"id":"M01","object":"P01外层短裤","label":"主面料","reference":"real.jpg",
   "features":"根据实拍填写实际织纹、尺度依据和限制",
   "regions":[
     {"id":"R01","box":[10,20,110,180],"reference_box":[30,40,130,200],"verdict":"abnormal","note":"实际差异与可比依据"},
     {"id":"R02","box":[130,20,230,180],"reference_box":[30,40,130,200],"verdict":"normal","note":"正常对照区及受光依据"}
   ]}
]}]}
```

`baseline`可指定当前有效修复版本，默认source。两者须同尺寸、同色彩配置的8位RGB/RGBA；高位深、CMYK等先明确处理副本或用原生应用，不暗中转换。区域verdict为`unreviewed/normal/abnormal/uncertain/natural_soft/occluded`，判断后必填具体note。遮挡区可不填box；其余必填。没有实拍时可准备检查证据，但不能通过脚本交付“已按实物修好”的成图。

```powershell
python "<skill>/scripts/fabric_tools.py" prepare --manifest "work/batch.json" --work "work/evidence"
```

生成inventory、原像素PNG裁片及导航PNG；默认无网页。缓存键包含源内容指纹、EXIF坐标和工具版本，复用前核验裁片内容。导航图独立缩放，仅用于定位，不作色彩判定；同商品尺度需另按实物地标判断，色彩看带配置的原图/原生应用。源参考不做锐化、改色或降噪。

## 2. 修复回贴与PNG/PSD

用宿主允许的图像编辑工具准备合格候选。每张图单独job；`authorized:true`只记录已有授权，不能代替用户选择。文件绑定SHA256取inventory或运行：

```powershell
python -c "import hashlib; print(hashlib.file_digest(open(r'work/candidate.png','rb'),'sha256').hexdigest())"
```

```json
{"image_id":"S01","output_stem":"S01-v1",
 "source":{"path":"ai.png","sha256":"实际64位指纹"},
 "baseline":{"path":"ai.png","sha256":"实际64位指纹"},
 "protect_mask":{"path":"protect.png","sha256":"实际64位指纹"},
 "patches":[{"id":"Q01","group":"M01","regions":["R01"],"authorized":true,
   "box":[10,20,110,180],
   "candidate":{"path":"candidate.png","sha256":"实际64位指纹"},
   "mask":{"path":"edit-mask.png","sha256":"实际64位指纹"},
   "allowed_mask":{"path":"allowed.png","sha256":"实际64位指纹"}}]}
```

- protect为全画布L灰度二值图：白保护、黑可考虑修改；allowed为补丁局部L二值图：白为已授权异常及必要融合区。edit-mask为同局部尺寸L灰度：白替换、黑保持、灰融合。三者意义不同，实际编辑必须同时满足。
- candidate、edit-mask、allowed尺寸必须恰好等于box宽高。candidate在修改区不透明且与基线同配置；不自动缩放、对齐、补alpha或大范围调色。
- 修改区只能落在绑定的abnormal区域及其允许蒙版内；区域定位应包含已授权的必要融合范围。零蒙版、保护区命中、正常/待证区域、补丁相互叠加、陈旧指纹全部拒绝。先把相互重叠修复合成一个已验证补丁。
- PSD保留Original锁定底层、必要Baseline及独立补丁像素层和可编辑蒙版。覆盖PNG以外的格式不输出；部分透明原图边缘的修改交原生工具，脚本不猜透明合成。

```powershell
python "<skill>/scripts/fabric_tools.py" compose --manifest "work/batch.json" --job "work/S01-job.json" --work "work/S01-candidate"
python "<skill>/scripts/fabric_tools.py" audit --receipt "work/S01-candidate/S01-v1.receipt.json" --work "work/S01-audit"
```

compose检查修改范围，并重新打开PSD逐层检查原图、蒙版像素、停用蒙版与切换图层。PNG与PSD存储合成像素完全一致；独立浮点渲染允许最大2/255取整差，不能用该容差解释色差或放宽PNG保护区。强制渲染只在补丁联合范围内进行，避免反复计算整张高清图；完整原图与合成仍原尺寸保存。

audit从实际PNG取全部可见区域的修前/修后/实拍裁片，并附整件导航和补丁外围上下文。其结果始终为not_reviewed；助手须打开原像素裁片与整件图实际检查。正常及合理虚化区是对照区，同样验收；遮挡保留限制。

## 3. 记录实际目视结果，正式输出仅两份文件

把真实观察写在work中的review.json。`audit_sha256`取audit命令返回值，reviewer如`model:当前模型`或实际人工身份；没有看图不填写通过。

```json
{"audit_sha256":"实际audit指纹","reviewer":"model:实际执行者",
 "checks":{
   "texture_reference":{"result":"passed","notes":"孔型/织纹与参考的实际观察"},
   "color_edges":{"result":"passed","notes":"颜色、光向及补丁四周的实际观察"},
   "protection":{"result":"passed","notes":"正常面料、Logo等保护区观察"},
   "whole_garment":{"result":"passed","notes":"交付尺度整件质感观察"}},
 "groups":[{"id":"M01","consistency":{"result":"passed","notes":"同组各部位的关系与正常明暗差异"},
   "regions":{"R01":{"result":"passed","notes":"修后实际结果"},"R02":{"result":"passed","notes":"正常对照未退化"}}}]}
```

全部组及区域逐一对应；可见区未解决/待证不能标passed。原遮挡区用`occluded`及说明；不能将可见失败区改成遮挡来放行。格式校验不能验证观察真假，最终仍依赖真实视觉复核。

```powershell
python "<skill>/scripts/fabric_tools.py" release --audit "work/S01-audit/audit.json" --review "work/S01-review.json" --output "outputs"
```

release复核源图、基线、参考、候选、蒙版、该图覆盖记录、PNG、PSD及证据的内容版本，拒绝过期QA和覆盖已有文件，仅复制PNG/PSD；不推定用户采用。其他图片的单独更新不使此图QA失效；该图记录或共享参考改变则需要重核。逐图执行，失败只保留该图候选，继续其余授权图；缺少可用PSD不标完整交付。

## 维护验证与参考

`python scripts/selftest.py`检查缓存、越界拒绝、分层蒙版、版本失效和交付格式；合成数据只验证程序，不代表真实面料识别或修复成功率。评估真实效果时对同一批图片用旧/新流程对照，记录误报、漏检、待证、返修、新增瑕疵与实际用时，不编造节省比例。

方法参考（不自动加载）：[服装表面/结构/行为](https://github.com/Marketplace-Lompa/media-shopee/blob/main/.agent/skills/moda/SKILL.md)、[裁片和视觉对比](https://github.com/dzhng/skills/blob/main/skills/visual/compare-screenshots/SKILL.md)、[分层精修与最终导出验收](https://github.com/calesthio/generative-media-skills/blob/main/skills/production/post-production/still-image-retouching-finishing/SKILL.md)。按本机任务验证，不引入其固定镜头、固定参数或额外平台要求。
