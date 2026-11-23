# kkc · 电商视觉 Skill 与详情页工作台

同步日期：2026-11-23。核心业务按 16 类功能组合并；独立版本与辅助引入工具分别保留，共 22 个源码目录。

[本次新增与更新](CHANGELOG-2026-11-23.md)

| 工具 | 版本／状态 | 源码与下载 |
|---|---|---|
| AI案例取证 | 1.5.0 | [源码](skills/ai-case-evidence/) · [ZIP](packages/ai-case-evidence.zip) |
| AI商品差异检测 | 本机当前快照 | [源码](skills/ai-product-image-diff/) · [ZIP](packages/ai-product-image-diff.zip) |
| 白底透明图基础版 | 本机当前快照 | [源码](skills/chutu-baidi-touming/) · [ZIP](packages/chutu-baidi-touming.zip) |
| 白底透明图V2 | 2.4.0 | [源码](skills/chutu-baidi-touming-v2/) · [ZIP](packages/chutu-baidi-touming-v2.zip) |
| 尺寸调整 | 本机当前快照 | [源码](skills/chutu-chicun-tiaozheng/) · [ZIP](packages/chutu-chicun-tiaozheng.zip) |
| 尺寸调整逐张版（保留） | 本机当前快照 | [源码](skills/chutu-chicun-tiaozheng-single/) · [ZIP](packages/chutu-chicun-tiaozheng-single.zip) |
| Codex聊天迁移（引入） | 本机当前快照 | [源码](skills/codex-chat-windows-to-mac-migration/) · [ZIP](packages/codex-chat-windows-to-mac-migration.zip) |
| SKU同款不同色套版 | 本机当前快照 | [源码](skills/ecom-color-scene-swap/) · [ZIP](packages/ecom-color-scene-swap.zip) |
| 指定模特换笑脸 | 本机当前快照 | [源码](skills/ecom-face-smile-edit/) · [ZIP](packages/ecom-face-smile-edit.zip) |
| 防晒帽减风精修 | 本机当前快照 | [源码](skills/ecom-hat-wind-retouch/) · [ZIP](packages/ecom-hat-wind-retouch.zip) |
| 通用电商出图 | 本机当前快照 | [源码](skills/ecom-image-pipeline/) · [ZIP](packages/ecom-image-pipeline.zip) |
| 电商视频提示词V1 | 本机当前快照 | [源码](skills/ecom-video-prompt/) · [ZIP](packages/ecom-video-prompt.zip) |
| 电商视频提示词V2 | 本机当前快照 | [源码](skills/ecom-video-prompt-v2/) · [ZIP](packages/ecom-video-prompt-v2.zip) |
| 面料质感修复 | 本机当前快照 | [源码](skills/fabric-texture-repair/) · [ZIP](packages/fabric-texture-repair.zip) |
| 商品视觉审稿 | 本机当前快照 | [源码](skills/kocotree-visual-review/) · [ZIP](packages/kocotree-visual-review.zip) |
| Lovart服装场景提示词 | 本机当前快照 | [源码](skills/lovart-apparel-prompt/) · [ZIP](packages/lovart-apparel-prompt.zip) |
| 指定商品选区PSD | 本机当前快照 | [源码](skills/product-selection-psd/) · [ZIP](packages/product-selection-psd.zip) |
| 小图找大图 | 本机当前快照 | [源码](skills/replace-images-by-name/) · [ZIP](packages/replace-images-by-name.zip) |
| 服装空模 SKC 与清晰度处理（逐图验收） | 本机当前快照 | [源码](skills/skc-ghost-mannequin/) · [ZIP](packages/skc-ghost-mannequin.zip) |
| 上下文交接与恢复（引入） | 本机当前快照 | [源码](skills/super-token-saver/) · [ZIP](packages/super-token-saver.zip) |
| Token节约规则（引入） | 本机当前快照 | [源码](skills/token-saver/) · [ZIP](packages/token-saver.zip) |
| 详情页套版 | 本机当前快照 | [源码](skills/visual-detail-image-processor/) · [ZIP](packages/visual-detail-image-processor.zip) |

## 详情页套版工作台 v0.5.14

完整 Windows 包含五套精简母版。**迁移验收未完成**，已有部分通过证据；继续按 M01–M06 补验收。

- [程序源码](workbenches/detail-workbench/)
- [完整五母版 Windows 安装包](https://github.com/ssjsjdjj/codex-image-skills/releases/tag/kkc-2026-11-23)
- [安装与验收说明](packages/detail-workbench-安装说明.md)
- [下载信息与 SHA-256](packages/detail-workbench-v0.5.14.json)

## 使用与版本边界

完整解压后交给 Codex 按各自 SKILL.md 检查依赖并安装。SKC 的运行文件、模型与原许可随包保留，许可边界见其第三方说明；每张图仍需实际视觉验收。辅助引入工具保留来源和许可。

详情页 Skill 基于 kocotree 原技能二次开发，来源：https://github.com/kocotree/kocotree-skills/tree/c973b4b29d29a31c084c775fdade83b5b0896b7c/skills/visual-detail-image-processor 。随附资源权利归原权利人。

[历史 v0.5.13 完整包](https://github.com/ssjsjdjj/codex-image-skills/releases/tag/kkc-2026-11-19) 及其他历史版本继续保留。
