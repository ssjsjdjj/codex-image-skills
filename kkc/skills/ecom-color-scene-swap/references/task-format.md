# 批次记录格式

需要批量处理或保留多轮选图、裁切反馈时，使用此格式作为工作记录。不是要求用户事先填写的表单。可按实际工具补充字段，路径必须来自实际文件，不把本例路径直接投入执行。

## 示例

下面是相对于素材根目录的路径示例；执行前解析成绝对路径并验证存在。每项一个款号和颜色，不能依赖数组顺序与其他文件配对。

```json
{
  "template": {
    "path": "模板/主图.psd",
    "size": [800, 800],
    "card_position_locked": true,
    "layer_map": {
      "scene": "场景图",
      "product": "产品小图",
      "color_text": "颜色名称"
    }
  },
  "items": [
    {
      "sku": "泳镜01",
      "color": "碧波白青",
      "product": "产品/泳镜01_碧波白青.png",
      "scene_candidates": [
        "场景/泳镜01_碧波白青_01.jpg",
        "场景/泳镜01_碧波白青_02.jpg"
      ],
      "selected_scene": "场景/泳镜01_碧波白青_02.jpg",
      "selection_reason": "可见产品款式配色匹配，右侧卡片覆盖区不遮挡脸和泳镜",
      "identity_status": "verified",
      "layout": {
        "source_size": [1600, 2000],
        "scene_crop_xyxy": [0, 200, 1600, 1800],
        "scene_target_xywh": [0, 0, 800, 800],
        "product_box_xywh": [525, 320, 235, 140],
        "text": "碧波白青"
      },
      "preview_revision": 1,
      "approved_revision": null,
      "approval_status": "pending",
      "output": "泳镜01_碧波白青.jpg"
    }
  ]
}
```

## 字段约定

- `identity_status`：`verified` 已核对；`uncertain` 不能确定；`missing` 缺必需素材；`not_applicable` 场景没有可见产品。后者不是佩戴图核对通过。
- `selected_scene`：只有完成选择后填写；尚未选择时用 `null`，不要用列表第一项自动填充。
- `source_size`：所选场景的原始像素宽、高。
- `scene_crop_xyxy`：原图坐标下的左、上、右、下；右和下为不包含的边界。裁切框须在源图范围内，并与目标区域保持相同比例。示例是 1600×1600 裁切到 800×800。
- `scene_target_xywh`、`product_box_xywh`：输出画布坐标下的左、上、宽、高。产品框内按实际可见主体边界等比放置；不得强行拉伸至框的宽高。
- `layer_map`：检查实际模板后填写。重建普通图层模板时可省略，不能从示例猜测真实图层名。
- 文本字体、字号、锚点、卡片可移动区域及其他装饰参数按实际模板补充，不预设示例中的坐标适用于所有产品。
- `preview_revision`：任何影响成品的选图、素材、裁切或文字变更都递增。
- `approval_status`：`pending` 待确认、`approved` 用户已确认、`waived` 用户明确跳过预览。`approved_revision` 只记录用户实际确认的版本，不推断确认。
- 正式生成前，检查当前版本与已确认版本一致；用户明确跳过预览时记录其要求。对未确认或缺图的项目逐项列出状态，不把整个批次误记为完成。

## 交付对应清单

用户不需要阅读内部 JSON 时，交付一份简洁表格：成品文件、款号、颜色、场景源文件、产品源文件、确认版本/状态、未解决问题。内部记录保留完整绝对路径及构图参数，方便复做。
