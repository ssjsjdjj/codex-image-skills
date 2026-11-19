# kkc · 电商视觉Skill与详情页工作台

同步日期：2026-11-19。按本机当前文件与上次GitHub快照逐文件比较，只更新有变化的内容。核心业务按14类功能组归并；V1/V2、基础版与逐张版分别保存，辅助引入工具保留来源和许可说明。

| 产出 | 版本／状态 | 源码与下载 |
|---|---|---|
| AI案例取证 | 1.5.0 | [源码](skills/ai-case-evidence/) · [ZIP](packages/ai-case-evidence.zip) |
| AI商品差异检测 | 本机当前快照 | [源码](skills/ai-product-image-diff/) · [ZIP](packages/ai-product-image-diff.zip) |
| 白底透明图基础版 | 本机当前快照 | [源码](skills/chutu-baidi-touming/) · [ZIP](packages/chutu-baidi-touming.zip) |
| 白底透明图V2 | 2.4.0 | [源码](skills/chutu-baidi-touming-v2/) · [ZIP](packages/chutu-baidi-touming-v2.zip) |
| 尺寸调整 | 本机当前快照 | [源码](skills/chutu-chicun-tiaozheng/) · [ZIP](packages/chutu-chicun-tiaozheng.zip) |
| 尺寸调整逐张版（保留） | 本机当前快照 | [源码](skills/chutu-chicun-tiaozheng-single/) · [ZIP](packages/chutu-chicun-tiaozheng-single.zip) |
| Codex聊天迁移（引入） | 本机当前快照 | [源码](skills/codex-chat-windows-to-mac-migration/) · [ZIP](packages/codex-chat-windows-to-mac-migration.zip) |
| SKU同款不同色套版 | 本机当前快照 | [源码](skills/ecom-color-scene-swap/) · [ZIP](packages/ecom-color-scene-swap.zip) |
| 通用电商出图 | 本机当前快照 | [源码](skills/ecom-image-pipeline/) · [ZIP](packages/ecom-image-pipeline.zip) |
| 电商视频提示词V1 | 本机当前快照 | [源码](skills/ecom-video-prompt/) · [ZIP](packages/ecom-video-prompt.zip) |
| 电商视频提示词V2 | 本机当前快照 | [源码](skills/ecom-video-prompt-v2/) · [ZIP](packages/ecom-video-prompt-v2.zip) |
| 面料质感修复 | 本机当前快照 | [源码](skills/fabric-texture-repair/) · [ZIP](packages/fabric-texture-repair.zip) |
| 商品视觉审稿 | 本机当前快照 | [源码](skills/kocotree-visual-review/) · [ZIP](packages/kocotree-visual-review.zip) |
| Lovart服装场景提示词 | 本机当前快照 | [源码](skills/lovart-apparel-prompt/) · [ZIP](packages/lovart-apparel-prompt.zip) |
| 指定商品选区PSD | 本机当前快照 | [源码](skills/product-selection-psd/) · [ZIP](packages/product-selection-psd.zip) |
| 小图找大图 | 本机当前快照 | [源码](skills/replace-images-by-name/) · [ZIP](packages/replace-images-by-name.zip) |
| 服装空模SKC（草案） | 本机当前快照 | [源码](skills/skc-ghost-mannequin/) · [ZIP](packages/skc-ghost-mannequin.zip) |
| 上下文交接与恢复（引入） | 本机当前快照 | [源码](skills/super-token-saver/) · [ZIP](packages/super-token-saver.zip) |
| Token节约规则（引入） | 本机当前快照 | [源码](skills/token-saver/) · [ZIP](packages/token-saver.zip) |
| 详情页套版 | 本机当前快照 | [源码](skills/visual-detail-image-processor/) · [ZIP](packages/visual-detail-image-processor.zip) |

## 详情页套版工作台

当前程序为v0.5.13，支持五套精简母版；本地已有五套母版共10份PSB生成、重开与视觉对照记录。此处同步源码和交付包，不将技术验证代替设计师业务验收。

- [程序源码](workbenches/detail-workbench/)
- [五套母版完整Windows迁移包](https://github.com/ssjsjdjj/codex-image-skills/releases/tag/kkc-2026-11-19)
- [安装说明](packages/detail-workbench-安装说明.md)
- [下载信息与SHA-256](packages/detail-workbench-v0.5.13.json)

## 使用和版本边界

源码包完整解压后交给Codex按SKILL.md检查依赖并安装。白底V2和尺寸调整包保留原Windows安装器；本机环境、个人设置、密钥、聊天和业务图片成品不在本次源码同步中。SKC为已有草案与试用流程；Token和聊天迁移工具属于引入资产，保留其说明与许可。其他历史版本和v0.5.11工作台仍可从Git历史或旧Release查阅。

详情页Skill基于kocotree原技能二次开发，来源：https://github.com/kocotree/kocotree-skills/tree/c973b4b29d29a31c084c775fdade83b5b0896b7c/skills/visual-detail-image-processor 。随附资源权利归原权利人。

## 本次变化

新增或更新的Skill：ai-product-image-diff、codex-chat-windows-to-mac-migration、ecom-video-prompt-v2、fabric-texture-repair、kocotree-visual-review、super-token-saver、token-saver、chutu-baidi-touming、chutu-chicun-tiaozheng、ecom-image-pipeline、skc-ghost-mannequin。
未变化的本机Skill：ai-case-evidence、chutu-baidi-touming-v2、ecom-color-scene-swap、ecom-video-prompt、lovart-apparel-prompt、product-selection-psd、replace-images-by-name、visual-detail-image-processor。

本次检查包括本地源码对应、ZIP完整性、Python语法、JSON及文件哈希；没有重新执行所有图像业务或Photoshop功能测试。
