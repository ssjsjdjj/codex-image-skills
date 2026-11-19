# 审核记录结构

每个被审核的视觉版本单独保存一个UTF-8 JSON。复制`assets/review-template.json`后填入真实项目资料；模板中的`EXAMPLE`只是结构示例，不能作为审核结果或同步到业务表。脚本只做结构和逻辑校验，不能核实图片结论、业务事实或主管身份。

## 核心字段

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 本文件结构版本，目前`1.0` |
| `project_id`, `review_id` | 项目ID及本次审核的唯一ID；新版本不得覆盖旧审核ID |
| `product_category`, `product_name`, `reviewed_at` | 商品品类、商品名与带时区的审核时间；自动案例整理需要这些字段 |
| `stage`, `version` | `initial`、`revision`、`final`之一及逻辑设计版本 |
| `artifact` | 实际文件名、可访问位置；能读取文件时记录SHA-256 |
| `rubric_version` | 本次评分规则版本`kocotree-visual-1.0` |
| `evidence[]` | 稳定的本版证据ID、文件/页面/区域定位、可观察内容、资料来源 |
| `scores[]` | 九项维度、状态、整数分或`null`、证据ID及评分原因 |
| `gates[]` | 四项核心门槛和五项辅助检查、状态、当前阶段是否阻断、证据及理由 |
| `findings[]` | 稳定问题ID、类型、状态、相关评分项、证据、修改动作和复核条件 |
| `decision` | Codex本版建议、主管是否已记录决定及其依据 |
| `package_status` | 数据包独立状态；通过时须有另行验收的依据 |
| `sync` | 飞书是否请求、待同步、已回读或失败；已回读时须存远端记录ID和时间 |

`evidence[].source`为`visual`、`business`、`platform`或`supervisor`。视觉证据的`source_ref`可以是原文件名；后面三类须写明可回查的资料、规则或确认记录，避免把推测写成事实。`locator`应足够让另一位审核者找到画面，例如“详情长图第2模块，左下袖口”或“主图3第1屏，商品右侧”。证据ID在本次记录内唯一。

`scores[].status`为`assessed`或`insufficient`。前者要求整数分、原因和至少一项证据；后者要求分数为`null`及未评原因。全部九项均为`assessed`才有正式100分制总分。

门槛状态为`passed`、`blocked`、`pending`或`na`。四个核心门槛的`blocking`必须为`true`；辅助检查的`blocking`按阶段和已确认要求设定。`blocked`必须关联一条未关闭的必改问题；`pending`需说明补充何种资料。`na`仅用于确实不适用的辅助检查。

问题`kind`为`required`或`suggestion`。问题`status`为`open`、`partial`、`closed`、`dismissed`或`pending`。必改项的`action`与`acceptance`不可为空；建议应说明预期收益。`dismissed`仅用于主管确认问题不成立，保留原始发现。跨版本沿用同一问题ID，旧问题`open`、`partial`或`pending`在新版本要继续出现。已关闭问题再度出现时写`reopen_reason`。同一版本多个截图不能生成同一问题的重复记录。

`decision.ai_recommendation`仅可为`needs_revision`、`direction_ready`、`final_ready`或`insufficient_evidence`。它由本版评分和门槛决定，不等于主管批准。`decision.supervisor`初始为`{"status":"pending","decision":null,"reason":null,"calibrated_score":null}`；主管确定后用`recorded`及`direction_approved`、`final_approved`或`revision_requested`之一，保留解释及原AI意见。主管若调整总分，将0至100的整数写入`calibrated_score`并说明依据；不改动AI九项原始分。

## 校验与版本衔接

在技能目录执行：

```text
python scripts/validate_review.py path/to/review.json
python scripts/validate_review.py path/to/revision.json --previous path/to/initial.json
```

脚本成功时返回0并输出正式总分或“资料不足”；失败时返回1并列出结构或逻辑错误。`--previous`要求同项目、不同审核ID，并检查上一版未关闭问题是否承接及关闭问题重开的理由。脚本不替用户决定是否接受某个发现。

推荐项目目录保留原稿、每轮返稿和审核JSON；外部表同步记录与本地审核记录使用同一`review_id`。只有文件重新导出时记录导出批次；设计内容修改时递增逻辑版本。若无法可靠辨别，标版本待确认，不凭文件时间推断。

案例整理详见[案例库规则](case-library.md)。`reviewed_at`采用例如`2026-10-20T10:00:00+08:00`，不要用文件修改时间代替审核时间。旧记录缺少这些元数据仍可继续校验和追踪，但不会自动晋升为案例。
