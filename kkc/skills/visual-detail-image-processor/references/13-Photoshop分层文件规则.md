# Photoshop分层文件规则

## 触发场景

用户提到以下内容时，优先使用分层 PSD 流程：

- 分层文件、PSD、PS、Photoshop、源文件
- 设计师要二次调整、复修、返工后微调
- 先出图，后续有问题还要改图层

## 运行顺序

1. 先按常规规则确认 `input-root`、`output-root`、`template-dir`、`product_data.json` 和模特图坐标 JSON。
2. 使用 `scripts/create_layered_psd_package.py`，不要只运行 `scripts/main.py`。
3. 该脚本会生成 790px JPG、PSD manifest、JSX 文件和报告。
4. 再使用 `scripts/run_photoshop_jsx.ps1` 让 Photoshop 执行 JSX，生成真正的 PSD。
5. 完成后检查 `_psd/` 目录、JPG 成品、`scripts/output/report/layered_psd_report-*.json`。

## 命令

```powershell
cd scripts
uv run python create_layered_psd_package.py `
  --input-root "<input-root>" `
  --output-root "<output-root>" `
  --visual-model-selection "<visual_model_selection-json>"
```

```powershell
powershell -ExecutionPolicy Bypass -File run_photoshop_jsx.ps1 `
  -JsxPath "<output-root>/_photoshop_layered/build_layered_psd.jsx"
```

## 输出

```text
<output-root>/<商品文件夹名>/
  01产品信息.jpg
  02透明图.jpg
  03选尺码.jpg
  05尺码快选.jpg
  模特图1.jpg
  模特图2.jpg
  模特图3.jpg
  _psd/
    01产品信息.psd
    02透明图.psd
    03选尺码.psd
    05尺码快选.psd
    模特图1.psd
    模特图2.psd
    模特图3.psd
  _psd_layers/
    ...
```

`_psd_layers/` 是 Photoshop 自动组装 PSD 时使用的中间图层素材，不要删，除非 PSD 已确认可打开且不再需要重建。

## 分层规范

- 每个 PSD 保持 2000px 模板尺寸，方便设计师按母版尺寸调整。
- JPG 成品仍保持 790px 宽。
- 固定模板图作为 `00 模板背景`。
- 动态区域拆分为独立层，命名必须可读，如 `20 商品透明图-黑色`、`20 模特照片`。
- 隐藏层 `99 成品参考（隐藏）` 用于对照最终 JPG，不参与正常编辑。
- 表格、复杂文字混排、圆角裁切优先用像素图层保证视觉稳定；能安全表达的短文字可以生成 Photoshop 文本层。
- 不要在脚本里写死商品名、货号、路径或表格内容。

## 二次调整策略

- 文案或表格数据错：优先修正 `product_data.json` 后重跑分层流程。
- 模特图裁切不好：优先修正 `visual_model_selection` 的 `crop_box` 后重跑。
- 设计师只要微调位置、大小、遮挡：直接打开 `_psd/` 中对应 PSD 调整图层。
- Photoshop 脚本失败：先确认 Photoshop 已安装并能正常启动，再检查 JSX 报错里提示的缺失图片路径。

## 验收

- 每个已生成 JPG 的模块都应有对应 PSD，除非报告明确说明数据或素材缺失。
- PSD 打开后能看到模板背景、动态内容层、隐藏参考层。
- 模特图 PSD 中照片层不能拉伸变形。
- 表格 PSD 中不能出现白框、绿线残留、表格残影。
- 输出报告必须记录 `manifest_path`、`jsx_path`、`psd_documents`。
