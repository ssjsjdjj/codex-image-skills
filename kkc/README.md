# kkc · 电商视觉 Skill 与详情页工作台

更新日期：2026-11-11。这里汇总已选定的 **11 项 Skill 和 1 个 Windows 详情页工作台**。尺寸调整保留整批与逐张两种确认方式，因此 `skills/` 内共有 12 个技能文件夹。

| 产出与源码 | 版本 | 用途 | 下载 |
|---|---|---|---|
| [白底透明图 V2](skills/chutu-baidi-touming-v2/) | 2.4.0 | 800×800 白底 JPG、透明 PNG；每款高清分层 PSD、独立蒙版；边缘检查与 PS 精修队列。 | [下载 ZIP](packages/chutu-baidi-touming-v2.zip) |
| [尺寸调整](skills/chutu-chicun-tiaozheng/) | 3.4.1（整批／逐张两版） | 主图和场景图按用途裁切、多尺寸导出、分组预览确认、图片与对应 PSD 数据包交付。 | [下载 ZIP](packages/chutu-chicun-tiaozheng.zip) |
| [小图找大图／同名替换](skills/replace-images-by-name/) | 2026-11-02 交付版 | 按文件名用高清原图替换已选小图，检查重名、缺失、备份和替换结果。 | [下载 ZIP](packages/replace-images-by-name.zip) |
| [AI 商品差异检测](skills/ai-product-image-diff/) | 2026-11-10 更新版 | 实拍与 AI 图按商品细节逐图对照，编号放大展示差异，并按指定位置修复复核。 | [下载 ZIP](packages/ai-product-image-diff.zip) |
| [SKU 同款换色场景套版](skills/ecom-color-scene-swap/) | 2026-10-27 版 | 按款号、颜色选产品与场景图，调整裁切，替换卡片内商品及颜色文字。 | [下载 ZIP](packages/ecom-color-scene-swap.zip) |
| [商品视觉审稿](skills/kocotree-visual-review/) | 2026-11-02 精简版 | 初稿、返稿、终稿九项审核；追踪问题关闭，保留本地审核记录和已解决案例库。 | [下载 ZIP](packages/kocotree-visual-review.zip) |
| [指定商品选区 PSD](skills/product-selection-psd/) | 2026-11-03 版 | 在原图中选择指定商品，保留完整原图、独立商品层和可编辑蒙版。 | [下载 ZIP](packages/product-selection-psd.zip) |
| [详情页图片处理 Skill](skills/visual-detail-image-processor/) | 2026-11-04 本地更新版 | 从 PSD／PSB 母版生成可编辑详情长图，保留智能对象、文案和表格，按需导出 JPG 模块。 | [下载 ZIP](packages/visual-detail-image-processor.zip) |
| [电商服饰视频提示词](skills/ecom-video-prompt/) | 2026-11-09 更新版 | 基于模特参考图、商品卖点和动作撰写中文图生视频提示词；处理布料、光影和动作的 AI 感。 | [下载 ZIP](packages/ecom-video-prompt.zip) |
| [Lovart 服装场景图提示词](skills/lovart-apparel-prompt/) | 2026-11-10 更新版 | 结合实拍、服装细节和动作场景参考，生成主提示词与局部返修词，约束质感、Logo 和指定模特。 | [下载 ZIP](packages/lovart-apparel-prompt.zip) |
| [AI 案例取证／使用报告](skills/ai-case-evidence/) | 1.5.0 | 整理原始证据、产物、反馈、计时与人工复核，生成案例提交稿和固定模板使用报告。 | [下载 ZIP](packages/ai-case-evidence.zip) |
| [详情页套版工作台](workbenches/detail-workbench/) | 0.5.11（含 5 套母版） | Windows 图形界面导入商品资料、绑定图片与表格、预览排版，再调用 Photoshop 生成可编辑 PSB。 | [完整五母版迁移包](https://github.com/ssjsjdjj/codex-image-skills/releases/download/kkc-2026-11-11/DetailWorkbench-v0.5.11-Windows-5-templates.zip) |

## 下载与安装

- 白底透明 V2 **2.4.0**、尺寸调整 **3.4.1** 的 ZIP 保留原有 Windows 安装器与依赖清单；完整解压后把包内“给Codex的安装提示词.txt”和包目录交给目标电脑上的 Codex。
- 尺寸调整默认使用[整批分组确认版](skills/chutu-chicun-tiaozheng/)，也可下载[逐张预览确认版](packages/chutu-chicun-tiaozheng-single.zip)。两版使用不同技能 ID，可独立安装。
- 其他 Skill 的 ZIP 为对应技能源码包，保留 `SKILL.md`、脚本、参考规则及必需资源。完整解压后，由目标电脑上的 Codex 按该技能说明检查依赖和使用方式。
- 白底透明安装器会为目标账号生成 `runtime.json`；仓库不复制本机运行环境或个人批准记录。
- 工作台程序源码在 [`workbenches/detail-workbench/`](workbenches/detail-workbench/)。含 **5 套母版**的完整 Windows 迁移包约 **1.24 GB**，请从 [Release 附件](https://github.com/ssjsjdjj/codex-image-skills/releases/tag/kkc-2026-11-11) 下载；[安装说明](packages/detail-workbench-安装说明.md)和 [SHA-256](packages/DetailWorkbench-v0.5.11-Windows-5-templates.zip.sha256) 保存在本目录。

## 版本与验证范围

- 白底透明采用 2.4.0 高清蒙版与 PS 三选项版；尺寸调整采用已交付的 3.4.1 两版迁移包。
- 视觉审稿采用 2026-11-02 已交付的本地记录精简版。
- 详情页 Skill 基于 kocotree 的原有技能继续更新；来源为 https://github.com/kocotree/kocotree-skills/tree/c973b4b29d29a31c084c775fdade83b5b0896b7c/skills/visual-detail-image-processor 。附带字体与母版为既有配套资源，权利归各自权利人。
- 工作台为 v0.5.11；既有迁移验收记录包含换目录解压、159 文件校验、Windows PowerShell 5 安装、启动与五母版预览。外置“自动解压安装.cmd”尚未完成，需完整解压后安装。
- 尺寸调整的 Photoshop COM 原生路径尚未完成实机验收；目标电脑需另行检查。不要把 Python 路径验收当作 PS 原生验收。
- 本次为集中整理与发布：核对版本、源码一致性、ZIP 完整性、Python 语法、JSON 和 SHA-256；不宣称重新完成所有商品图、安装或 Photoshop 功能测试。

未纳入可选辅助 Skill、SKC 草案、个人聊天导出、业务图片成品和本机运行缓存。

## 目录

```text
kkc/
├─ skills/          11 项 Skill，含尺寸调整的两个独立版本
├─ workbenches/     详情页工作台程序源码
├─ packages/        技能 ZIP、工作台下载信息与安装说明
└─ MANIFEST.json    版本与文件校验索引
```
