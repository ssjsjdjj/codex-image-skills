# 第三方来源与许可

本包对第三方二进制、模型未做修改。文件 SHA-256 记录在包根目录 `SHA256SUMS.json`，用于锁定本次实际使用的版本，不跟随上游 main 自动更新。

## 本机放大引擎

- 项目：Real-ESRGAN ncnn Vulkan，Xintao Wang；基于 nihui 的 realsr-ncnn-vulkan 与 Tencent ncnn。
- 官方发行包：<https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip>
- 源代码：<https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan>
- 保留原 README、MIT 许可及 ncnn 许可，见 `licenses/`。
- `vcomp140.dll` 为该官方 Windows 发行包附带的 Microsoft Visual C++ OpenMP 运行时组件，其权利归 Microsoft 所有，不能将其视为本 skill 的自有代码。迁移包未包含发行包中未使用的 debug DLL。

## UltraSharp 4× 模型

- 作者：Kim2091；名称：4x-UltraSharp；模型作者页：<https://huggingface.co/Kim2091/UltraSharp>。
- 作者列出许可：CC BY-NC-SA 4.0。原模型卡和许可全文随包保留。许可页：<https://creativecommons.org/licenses/by-nc-sa/4.0/>。
- 本次使用文件来自 Upscayl 的公开 NCNN 模型分发，下载后未改动：
  - <https://raw.githubusercontent.com/upscayl/upscayl/main/resources/models/ultrasharp-4x.bin>
  - <https://raw.githubusercontent.com/upscayl/upscayl/main/resources/models/ultrasharp-4x.param>
- 署名：4x-UltraSharp © Kim2091；NCNN 文件来源为 Upscayl。此包不是作者或 Upscayl 的官方产品。重新分发模型时保留署名、来源和原模型许可。
- 本包不附带额外商用授权，不能因为模型可下载就宣称其可无条件用于商业商品图。商品商用前应确认相应授权。

许可文件于 2026-11-19 从以上官方项目、作者与 Creative Commons 来源取得。本 skill 的说明和辅助脚本独立于模型；没有改动模型训练权重或移除其原有许可。
