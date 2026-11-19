# v0.5.13 工作台：新电脑完整安装与迁移

请从[2026-11-19 Release](https://github.com/ssjsjdjj/codex-image-skills/releases/tag/kkc-2026-11-19)下载 **DetailWorkbench-v0.5.13-Windows-5-templates.zip** 及其 SHA-256 文件。该包包含五套精简母版和字体；GitHub仓库的“Code → Download ZIP”只包含源码，不包含这份完整工作台迁移包。

当前完整包适用于Windows。Mac需要另行适配安装脚本和Photoshop调用，尚未完成同等迁移验收。

## 给 Codex 的完整包安装指令

请安装这个 **v0.5.13 · 含 5 套精简母版** Windows 工作台迁移包，并打开工作台。完整保留模板 ID、目录结构和相对资源路径。

1. 先确认已将整个 ZIP「全部解压」到可写的本地文件夹，建议短路径。不要在压缩包临时目录运行脚本，不要沿用其他电脑的 `.venv`。
2. 进入解压目录，执行：

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\detail-workbench\install.ps1"
   ```

   安装脚本会检测／安装可用的 Python，创建本地 `.venv`，安装 Pillow 和随包字体。程序所需的基础字体、母版补充字体都应安装；首次安装需要联网。
3. 安装后执行以下命令，确认检查通过：

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\detail-workbench\install.ps1" -CheckOnly
   ```

4. 运行根目录的 `启动工作台.cmd`。确认窗口标题为 v0.5.13，母版下拉列表含「KQ26201_产品信息T_字体统一」「产品信息T」「小山行风感洞洞裤 · 工作台母版 V1」「小糯云冰奶皮防晒t详情」「萌鱼泡泡渔夫帽-终」。逐个查看「母版版式」，确认只显示必要页面。
5. 这 5 个母版已精简并解析，正常使用不需要重新上传，也不依赖旧电脑的原始 PSB 路径。`profile.json` 应含 `compact_version: 1`，模块不含 `brand`／`footer`；母版示例预览为 `working.jpg`。`迁移清单.json` 记录随包文件 SHA-256，可按清单核对资源完整性。不要将旧版 profile 或完整原稿快照覆盖进新版目录。
6. 检查新电脑是否已有可正常打开并可通过 COM 调用的桌面 Photoshop。字体安装后，若 Photoshop 原先已打开，请用户保存文档再重开，随后再测生成 PSB。不要关闭用户未保存文档。

旧商品资料另存的 ZIP 可通过「导入资料包 / JSON」导入。安装出错先读 `detail-workbench\install.log`，保留模板、商品资料和用户原稿。


## 只有程序包时

标为“无母版”的程序包不带五套母版。它适用于已有母版、只升级程序的用户；新电脑完整恢复应优先使用上方Release附件。

## 业务资料与账号

原商品资料、工作中新增的母版和未提交源码仓库的素材须另行复制。新电脑需重新登录有权限的GitHub、飞书等账号；软件依赖、工具连接和模型环境按说明重建。
