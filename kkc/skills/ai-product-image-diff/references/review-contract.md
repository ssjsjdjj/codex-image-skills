# 记录、版本与选择契约

这些记录只验证身份、范围和可追溯性，不能代替面料/商品的目视检查。先有真实观察和最终文件证据，再填写复核结果；不得为了通过校验编造观察或用户采用。

## 单一事实源与命令

修复与迭代维护 schema 2 JSON；报告和页面从同一次规范化记录生成，不分别手写相互矛盾的状态。

```bash
python scripts/build_bulk_review.py --manifest 检查清单.json --output review.html --report-json current-review.json --report-md repair_record.md
python scripts/build_bulk_review.py --manifest 检查清单.json --output review.html --status-record 更新记录.json --report-json current-review.json --report-md repair_record.md
python scripts/review_contract.py --manifest 检查清单.json --status-record 更新记录.json --validate-selection 选择清单.json
```

接收复制内容和 JSON 后使用相同校验入口，重新读取当前源文件、状态及图片指纹。校验成功只返回核实后的范围，不直接修改图像，也不产生新的视觉通过结论。

## schema 2 检查清单

顶层字段：`schema_version:2`、稳定且非空的 `dataset_id`、`files`、`people`、`issues`。批次标识与修订分开；`revision` 由生成器按当前数据、状态和实际文件内容计算，不按文件名或修改时间猜测。

```json
{
  "schema_version": 2,
  "dataset_id": "product-review-unique-batch",
  "title": "面料质感与商品差异",
  "scope": "本轮明确的商品和检查范围",
  "files": [
    {"id":"S01","name":"AI场景.png","role":"ai_input","path":"AI场景.png"},
    {"id":"REF01","name":"同款实拍.jpg","role":"reference","path":"实拍.jpg"}
  ],
  "people": [
    {"id":"P01","scene":"S01","position":"左位","color":"已核实颜色","conclusions":{}}
  ],
  "issues": [
    {
      "id":"Q01","scene":"S01","person":"P01","group":"Q","feature":"mesh",
      "title":"具体部位与观察到的质感问题",
      "diagnosis":{"status":"confirmed"},
      "repair":{"status":"pending"},
      "review":{"status":"not_reviewed"},
      "adoption":{"status":"not_adopted"},
      "reference_ids":["REF01"],"dependencies":[],"sequence":0
    }
  ]
}
```

示例中的文字必须替换成实际观察，不复制为默认结论。路径相对清单目录；文件角色为 `ai_input/reference/evidence/output`。生成器流式计算实际文件 SHA256，包含声明的输入、参考、证据和输出。不要把生成候选登记成 reference。

问题必须有非空 `id/scene/person/group/feature/title`；组为 D/Q/F/R；引用真实图片及 `(scene,person)`。v2 声明的文件必须实际存在；confirmed 项须有非空 `reference_ids`（其他诊断可显式为空）。同批问题编号唯一，人物键用图片+人物，因此不同图可都有 P01，但同图重复人物键会报错。缺失定位不默认猜成某个人。

推荐另存 `visibility`、`material_checks`、`evidence`、`description`、`limitation`、`suggested_method`、`comparison_image`、`native_ai/native_ref`。质感项的 `material_checks` 写实际孔型/尺度/密度/方向/对比/光泽/清晰度及所属布片；没有证据不补齐为“通过”。裁片记录源文件身份、原尺寸、坐标及显示倍率。

`dependencies` 为本批其他问题编号。未知引用、自依赖和循环不允许。未有当前有效技术复核通过的依赖会阻止该项进入默认批选；它不等于用户取消授权。已授权结构与质感可按依赖顺序完成，结构完成后继续已授权质感，不重复要求用户批准。

## 四种状态分开

|字段|允许状态|含义|
|---|---|---|
|diagnosis|confirmed / uncertain / withdrawn / no_difference|问题确认、待证、撤销判断或无需修改|
|repair|pending / in_progress / executed / failed / not_executed|本项执行阶段；executed 不等于复核通过|
|review|not_reviewed / needs_review / passed / failed / insufficient / revoked|针对具体输出的技术复核|
|adoption|not_adopted / adopted / withdrawn|用户明确采用当前文件的事实，不由助手自行推定|

不得在 v2 用自由文本 `status/repair_status` 替代上述字段。诊断撤销只关闭误判问题；复核撤销使相关输出失去通过，原问题仍在；用户撤销采用不删除历史记录。新版本不继承旧文件的通过或采用，旧文件历史采用事实也不能因出新文件而篡改。

## 当前输出与真实视觉复核

每项 `current_output` 为 `{path,sha256,version}`，指实际最终导出文件。只有源文件身份、输出和证据都有效时才可能保留 `review.status:passed`。passed 还需要：

- `output_sha256`、`output_version` 与当前输出匹配；填写 `output_path` 时也必须对应。
- `input_sha256` 为该 scene 原 AI 的当时内容指纹。
- `reference_ids` 与 `reference_sha256:{参考ID:当时SHA256}`，使换参考也能使旧 QA 失效。
- `method:visual` 或 `human_visual`、`reviewer`、`checked_at`，如实区分模型与人工。
- `evidence:[{path,sha256}]` 为实际最终文件的对比证据，保留裁片与缩放溯源。
- `checks` 含 `structure/color/texture/protection`，各项为 `{result:passed或not_applicable,notes:具体观察或不适用理由}`。所有图像修复的 color/protection 必须 passed，Q 还必须 texture passed，D 还必须 structure passed；其余维度才可写有依据的不适用。不能把四项全写不适用绕过面料验收。

字段齐全只能证明记录完整，不能证明 notes 正确。原图/参考/输出/证据换版或绑定缺失时，旧 passed 降为 needs_review 并保留原声明于 history，不能继续当通过。用户采用另需明确采用记录、`explicit_user_acceptance:true` 和当前已复核输出的 hash/version；无此依据只保留历史，不能宣称用户采用。生成后的 current_output 额外含 binding_valid；复制/下载载荷完整保留该对象，不自行删改。

## 更新记录与冲突

状态更新顶层绑定 `schema_version:2/dataset_id/source_manifest_sha256`；`updates`（兼容容器 records/repairs/issues）每行带完整问题定位与正整数 `sequence`，只写要更新的四种状态或 `current_output`。

- 跨批、源清单不匹配或对象定位改变则拒绝该更新，不能按 D01 等裸编号覆盖。
- 缺少状态字段表示没有更新，不覆盖原值；显式空值、未知状态或同序号冲突报告错误，阻止受影响记录执行，不能静默变待修或完成。
- 顺序按显式序号，不按 repairs/records/issues 容器遍历顺序决定当前状态。撤回需写明确枚举更新及原因，历史描述不触发当前通过。
- 更新后同时重建机器报告、Markdown 和页面；旧预览中的通过标签不是当前结论。

## 选择与旧数据

复制和下载同一 schema 2 载荷，含 `dataset_id/review_revision/source_manifest_sha256/allow_redo/selected_issues/summary/instruction`；每项包含完整定位、四种状态与当前输出绑定。执行前再次校验实际文件与范围；不信任旧页面、裸编号、被修改的摘要或仅凭可复制指令认定对象。推荐 title 放在源清单；若生成时使用 --title 覆盖，校验时也传同一个 --title，否则修订不匹配会被拒绝。

旧 schema 1 清单只读展示、明确诊断，不自动继承完成。旧无身份状态记录不能按裸编号导入；只有能唯一证明批次、图片、人物和输出对应时，才重建 v2 定位和真实复核记录。模糊/复合状态文字保留历史并需复核。不能因迁移或校验失败自动启动修复。

业务素材、机器状态、预览和历史修复文件在任务目录；技能包只保存通用规范、脚本与测试，不携带真实业务图片。
