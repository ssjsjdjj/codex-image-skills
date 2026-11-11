# Photoshop 导出与验收

对于单张 8 位 RGB 平面源图和已确认的同尺寸 8 位灰度 PNG 蒙版，使用 `scripts/export-selection.jsx`。脚本可接收多个目标层。其他源格式保留原文件结构，在 Photoshop 中按同样规则组装并逐层验收。

把脚本内容与下面的调用合并，通过已连接的 Photoshop 执行。路径使用实际绝对路径，配置用 JSON 序列化。脚本读取蒙版需使用 Photoshop 剪贴板。

```javascript
exportProductSelection({
  source: "C:/素材/商品.jpg",
  output: "C:/交付/商品-选区.psd",
  layers: [
    {name: "指定商品", mask: "C:/预览/商品-确认蒙版.png", smartObject: false}
  ]
});
```

脚本使用 Photoshop 打开源图，复制原图层作为商品层，将灰度蒙版导入临时通道再生成图层蒙版。输出保存为新文件。保存后重开并逐层从蒙版载入选区验证边界。执行前检查 Photoshop 当前文档，避免使用用户正在编辑的同名源文件。脚本只关闭它打开的文档。

验收时核对尺寸、对位、图层类型和蒙版与确认预览的一致性。单击商品蒙版缩略图应进入蒙版编辑。Windows 按住 Ctrl 单击缩略图，macOS 按住 Command 单击缩略图，应能载入选区。关闭完整底图，核对商品边缘与孔洞。遇到透过镜片等透明商品看到的原图内容，说明此 PSD 的原位修图用途。出现导出或重开错误时，保留已确认的蒙版，修正错误后使用新输出路径重试。
