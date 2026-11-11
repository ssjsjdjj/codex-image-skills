---
name: visual-detail-image-processor
description: 电商详情页套版技能，从 PSD/PSB 母版为每款生成独立可编辑长图，保留可替换的嵌入式智能对象及可编辑文案和表格。按需输出 790px JPG 模块。
---

# 视觉详情页模板生成

## 默认交付逐款可编辑长图

- 详情页套版默认使用 [可编辑长图规则](references/13-可编辑长图PSD规则.md)。输入范围内每个款式各输出一份已替换为该款内容的独立长图，按款归档。
- 当前默认版式暂用 `小山行风感洞洞裤-终.psb`（790 × 40000 px），保留完整画布时交付 PSB。可在任务中显式指定旧母版。货号、材质、尺码范围及表格沿用原逐字符字体规则。
- 商品图和模特/场景图使用分别可替换的嵌入式智能对象。商品文案、颜色名和表格单元格使用 Photoshop 原生文字图层。新母版的 S3 选尺码、S4 尺码快选、S5 试穿报告按实际行列数调整网格，保留母版各区标题、配色、模块位置和固定设计。
- 用户明确要 JPG 模块时使用下方 JPG 流程。用户同时要 JPG 时，按需求附加导出。

## 逐款套版

1. 盘点输入根目录内全部款式，核对 PSD/PSB 母版和实际图层。区分固定设计和随款替换内容。
2. 每款准备一份任务 JSON 和独立输出路径。绑定商品文案、尺码表、尺码快选、已有的试穿报告、商品图、模特/场景图及其他随款变化的模块。现有商品 JSON 可复用为数据来源。
3. 使用 `scripts/build_editable_long_psd.py` 逐款生成 JSX，再通过 Photoshop 执行。母版槽位无法匹配或该款素材缺失时，列出款号、模块及缺项。旧款动态内容、合并 JPG 或未完成的母版副本不得作为该款成品交付。
4. 重开每个输出 PSD，核对款号、可见内容、文字和表格可编辑性，检查商品图和场景图能分别打开智能对象内容且不依赖外部链接。列出逐款成品路径及未完成项。

## 环境准备

首次使用前需在skill的 `scripts/` 目录下初始化 Python 环境：

```bash
cd scripts
uv sync
```

如未安装 uv，先执行：

- macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

初始化完成后，务必使用 `.venv` 中的 Python 执行工具脚本。


## 输入结构

商品素材结构通常为：

```text
<input-root>/
  <product-folder>/
    product_data.json
    产品信息.jpg|png
    选尺码.png|jpg|jpeg
    尺码快选.png|jpg|jpeg
    透明图/
      <颜色名>.png
    模特图/
      1.jpg
      2.jpg
      3.jpg
```

内置模板目录为：

```text
template/
```

模板结构通常为：

```text
template/
  01产品信息.jpg
  02透明图.jpg
  03选尺码.jpg
  04推荐尺码.jpg
  05尺码快选.jpg
  模特图1.jpg
  模特图2.jpg
  模特图2覆盖.png
  模特图3.jpg
```

## 执行流程

1. 先确认输入根目录和输出根目录；默认使用 skill 内置 `template/` 和 `assets/`。
2. 若商品还没有结构化数据，先使用 GPT 本身的图像识别能力读取 `产品信息`、`选尺码`、`尺码快选` 三张图，按商品合并生成 JSON，并保存到 `scripts/output/product_data/<商品文件夹名>-product_data-<时间戳>.json`。
3. 读取 [图片表格转数据规则](references/04-图片表格转数据规则.md)，校验商品 JSON，不确定内容写入 `warnings`，不能编造。
4. 在运行渲染脚本前，先扫描商品是否存在模特图素材；只要存在可读取的模特图，就必须先使用 AI 审美选图/选框，为每张可用模特图输出源图原始像素坐标，并保存到 `scripts/output/visual_model_selection/visual_model_selection-<时间戳>.json`。
5. 运行通用批处理脚本，不允许写死商品名或商品数据；如果本轮生成了 AI 坐标 JSON，必须显式传入 `--visual-model-selection "<坐标json路径>"`，不能依赖脚本自动回退或自动等待数据。
6. 对每个商品分别生成输出子文件夹，子文件夹名保留原商品文件夹名。
7. 成品图片只输出到 `--output-root/<商品文件夹名>/`；批处理报告统一输出到 `scripts/output/report/render_report-<时间戳>.json`。
8. 如果用户要“分层文件”“PSD”“Photoshop 二次调整”或设计师复修交付，改用 `scripts/create_layered_psd_package.py`；它会同步生成 JPG、PSD 清单和 Photoshop JSX 组装脚本。
9. 输出后做视觉与尺寸检查，尤其检查白框、绿线残留、表格残影、文字错位、透明图大小跳动和模特图裁切。
10. 读取报告确认所有有坐标的模特图 `mode` 为 `visual_model_selection`；若回退 `cover_crop`，必须逐条说明是坐标缺失、坐标无效、源文件不存在，还是当前环境无法可靠视觉判断。

## Photoshop 分层文件流程

当用户需要设计师可二次调整的文件时，使用 Photoshop 分层流程：

```powershell
cd scripts
uv run python create_layered_psd_package.py `
  --input-root "<input-root>" `
  --output-root "<output-root>"
```

脚本会在 `<output-root>/_photoshop_layered/` 生成：

```text
layered_psd_manifest.json
build_layered_psd.jsx
```

再调用 Photoshop 生成 PSD：

```powershell
powershell -ExecutionPolicy Bypass -File run_photoshop_jsx.ps1 `
  -JsxPath "<output-root>/_photoshop_layered/build_layered_psd.jsx"
```

PSD 输出到：

```text
<output-root>/<商品文件夹名>/_psd/
```

分层约定：

- 模板背景独立为 `00 模板背景`。
- 动态替换内容独立成可开关图层，如商品透明图、模特照片、表格图层、数据区底色。
- 每个 PSD 默认包含隐藏的 `99 成品参考（隐藏）`，用于设计师对照检查。
- 表格和复杂混排文字会以像素图层保留视觉一致性；产品信息与颜色名会尽量生成 Photoshop 文本层，方便二次微调。
- 如果只想基于已有 JPG/素材重建 PSD，不重新渲染 JPG，可加 `--skip-jpg-render`。

## 必读细则

根据任务读取对应 reference：

- 处理任意批量任务前，读取 [批量执行规则](references/01-批量执行规则.md)。
- 需要了解固定字体资源时，读取 [内置资源规则](references/02-内置资源规则.md)。
- 需要了解或替换模板资源时，读取 [内置模板资源规则](references/03-内置模板资源规则.md)。
- 需要从图片/表格素材得到数据时，读取 [图片表格转数据规则](references/04-图片表格转数据规则.md)。
- 绘制文字或遇到字体问题时，读取 [字体与文字规则](references/05-字体与文字规则.md)。
- 处理 `01产品信息.jpg` 时，读取 [产品信息规则](references/06-产品信息规则.md)。
- 处理 `02透明图.jpg` 时，读取 [透明图规则](references/07-透明图规则.md)。
- 处理 `03选尺码.jpg` 或 `05尺码快选.jpg` 时，读取 [表格规则](references/08-表格规则.md)。
- 处理 `模特图1.jpg`、`模特图2.jpg`、`模特图3.jpg` 时，读取 [模特图规则](references/09-模特图规则.md)。
- 需要使用 AI 主观审美裁切坐标时，读取 [智能模特图选框规则](references/10-智能模特图选框规则.md)。
- 使用或维护脚本时，读取 [脚本说明](references/11-脚本说明.md)。
- 需要输出 PSD 分层文件或控制 Photoshop 时，读取 [Photoshop分层文件规则](references/13-Photoshop分层文件规则.md)。

## 当前脚本

```text
scripts/detail_template_replacer_2000.py
scripts/main.py
scripts/create_layered_psd_package.py
scripts/run_photoshop_jsx.ps1
scripts/create_product_data_template.py
scripts/validate_product_data.py
```

## 运行

示例命令：

```powershell
cd scripts
uv run python main.py `
  --input-root "<input-root>" `
  --output-root "<output-root>"
```

如果本轮存在模特图素材，先生成 `visual_model_selection-<时间戳>.json`，再显式传入坐标文件：

```powershell
cd scripts
uv run python main.py `
  --input-root "<input-root>" `
  --output-root "<output-root>" `
  --visual-model-selection "output/visual_model_selection/visual_model_selection-<时间戳>.json"
```

如果使用外部数据目录或外部模板目录：

```powershell
cd scripts
uv run python main.py `
  --input-root "<input-root>" `
  --output-root "<output-root>" `
  --data-dir "<data-dir>" `
  --template-dir "<custom-template-dir>" `
  --visual-model-selection "<visual_model_selection-json>"
```

## 验收底线

- 每个输入商品文件夹都必须被处理或被报告原因。
- 所有输出图片宽度必须为 790px。
- 模板固定文字、背景、绿色块、logo、装饰线、覆盖层不能被动态绘制破坏。
- 商品数据必须来自 `product_data.json` 或等价结构化文件，不能写死在 Python 里。
- 空值留空，不补默认值，不推算。
- 不能出现白框、绿线残留、表格残影、绿色表头白竖线。
- 同类文字字号和粗细一致，混排数字不能上下乱跳。
- 透明图同页商品视觉大小一致，颜色名贴近商品且同一基线。
- 模特图主体不变形，优先保证头部完整和主体完整。
- 含模特图素材的批处理必须先产出 AI 坐标 JSON 再运行脚本；报告中对应模特图应显示 `visual_model_selection`，除非已明确说明无法使用 AI 坐标的原因。
