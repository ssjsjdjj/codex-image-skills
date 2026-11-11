# 真实案例工作流与数据格式

按日期生成的Codex使用报告见[writing.md](writing.md)。这些是基于真实证据的写作模式，沿用本文件的责任区分、状态和确认口径，不改变既有案例数据格式。reporting.py的编稿输入与扫描索引不是已完成稿件，也不触发confirm-submission。

实际退回、修正与复验按[correction.md](correction.md)整理同素材六步链及正文中的四类证据导航。案例稿与报告的飞书正文和“某章材料多时统一放入该章的一份证据文档”见[feishu-layout.md](feishu-layout.md)。继续使用既有证据角色与case.json格式；待本人复验的修订输出先登记为other等适合角色，确认对应版本后才登记final。本人质量复验不自动变成业务acceptance。

只处理明确的真实工作。未知数据留null，不把未测量写成0。以用户授权范围内的源文件、过程、确认和产物取证。

## 命令

```text
init --out ABS_NEW --mode real --title TITLE
set --case ABS_CASE --field what|ai_step|human_judgment|application|evidence|reuse --text TEXT --kind observed|user_report --source SOURCE
timing --case ABS_CASE --file ABS_JSON
add --case ABS_CASE --role original|ai_first|issue|final|application|acceptance|other --path ABS_FILE --kind observed|user_report --note NOTE
closeout --case ABS_CASE --file ABS_JSON
confirm-submission --case ABS_CASE --evidence 本人对当前案例内容的明确确认原话
submission-status --case ABS_CASE
review-report --case ABS_CASE --review-id REVIEW_ID --seconds SECONDS --evidence 本人实际报告原话 [--all-checks-accounted]
render --case ABS_CASE --out ABS_NEW_WORK --evidence-id E003 --evidence-id E012
render --case ABS_CASE --out ABS_NEW_AUDIT --profile audit
```

记录必须有实际来源。登记文件只证明复制与哈希一致，不自动证明其业务内容。final只用于本人已确认的版本；技术检查、预览确认、页面采用、业务验收分开记录。

真实耗时数据格式（缺值保留）：

```json
{
  "baseline_minutes": null,
  "ai_minutes": null,
  "check_minutes": null,
  "rework_minutes": null,
  "rework_count": null,
  "rework_count_kind": "unknown",
  "rework_count_basis": "",
  "sample_count": null,
  "same_scope": null,
  "measurement_kind": "unknown",
  "basis": "待采集本次真实记录"
}
```

measurement_kind取measured/estimate/unknown，baseline是本人估算时保持estimate。范围包括数量、步骤、质量要求、检查和最终导出，不能用AI初稿与人工终版比较。净节省=人工基线-AI运行-人工检查-返工-未计入前述项目的额外人工；已包含或重叠时间不重复扣除。

rework_count_kind取unknown/human_return/revision_round，分别表示口径未知、本人实际退回次数、实际修订轮数，已知时同时填rework_count_basis说明真实依据。次数不参与时间减法，次数未知不阻塞已齐的分钟计算。旧数据中的无口径数字保留作历史记录，不自动宣称是人工返工次数。技术日志顶层返工步骤数另存在`timing_journal.technical_rework_step_count`，同步不能覆盖实际次数。

## 主张与收尾确认

多快好省只选证据最强的一项。收尾时核对已有事实和产物。仅使用已有计时与本人主动提供的用时，历史 collect_timing 和 deferred_fields 字段仍兼容读取，不触发询时。

submission-status 分别返回产物状态、本人质量结论、缺失案例事实和案例提交状态。五项事实齐备后为“待本人核对”，本人核对当前内容与证据限制后为“可提交”。缺时长不阻塞这些状态。只有时间改善主张才返回计时覆盖和相关限制；已有数字无覆盖依据时，仍保留无法证明净节省的限制。

本人已提供的信息通过`timing`和`closeout`登记，不重复询问。`closeout`示例（仅填实际回答，未知为null）：

```json
{
  "claim_focus": "speed",
  "net_savings_requested": true,
  "baseline_basis": "本人提供的同批工作估算或实测依据",
  "unlogged_human_minutes": null,
  "unlogged_human_kind": "unknown",
  "production_status": "unknown",
  "quality_status": "unknown",
  "source": "本聊天本人原话或实际记录位置"
}
```

claim_focus取speed/quality/volume/cost/unspecified。只有本人明确说无计时外人工时才填0；额外人工必须未计入AI、检查或返工，避免重复。若大于0，注明measured或estimate；净节省还须扣除该项，并按基线或额外人工中的估算性质披露。`timing`的measurement_kind与same_scope仍分别记录基线性质和范围。未知信息不写0，也不从会话时长猜测。缺项时仍可编稿，但不能声称已证明净节省。

production_status取unknown/in_progress/completed，仅根据真实业务产物状态填写；quality_status取unknown/needs_revision/usable，仅根据对应版本的实际质量结论填写。每项声明需有source，原始记录由AI查得还是本人陈述应在来源中说清楚。不要从“检查完成”推断usable，也不从workflow-finish推断本人质量确认或案例确认。未明确采用或验收时，在实际应用字段中如实说明未知或未发生，不虚构业务状态。

### 当前稿件的本人确认

先展示当前提交稿及实际主张。只有本人明确确认案例事实与主张无误时，才运行`confirm-submission`，evidence保留确认原话；不能拿“修后可用，确认生成”等图像效果授权代替案例内容确认。已有授权和未变化的已答事实不重复询问。

确认与当前实质内容版本绑定。工作范围、五项事实、计时比较或相关证据内容发生实质变化后，状态退回待补或待本人核对；只读状态、同步相同计时数据和新增role=other的无关技术附档不使确认失效。未明确核对时仍可交付标明状态的草稿，不能记录为本人已确认可提交。

## 精简提交与审计导出

默认`render`只写一份`案例提交内容草稿.txt`，含五项事实、相关价值/计时对照、按ID指定的关键证据来源和关键事实缺项或证据限制，不复制全部文件、哈希清单或计时目录，也不会因导出成功就改成可提交。该文件是work中的编稿数据；AI按飞书布局组织最终正文，必要时先制作DOCX并核对版面作为导入格式，移除编稿中的本地路径说明。图片已内嵌就不重复交附件；某章材料多时集中到该章的一份飞书证据文档，主文档从对应章节链接过去。不固定要求两页或若干张图，不自动选满所有角色，不把技术日志当业务验收。未真实写入并核验前，状态保持飞书链接待生成。

完整本地档案始终在case目录中保留。只有明确需要审计包时使用`--profile audit`，旧版1.1默认全包的调用须改成这个显式选项；程序调用对应`render(case, out, profile='audit')`。默认调用现在返回单份编稿路径和提交状态。未指定关键证据ID时只提示选择，不自动挑选可能不属于同一样本的图片。

## 本人直接报告检查时间

`review-report`保存本人报告秒数、稳定`review_id`与来源，按轮次去重；重复相同报告不累加，冲突报告不覆盖原值。`--all-checks-accounted`表示已有来源足以核对所有检查含最终复核，写入`check_time_complete=true`，不是质量或业务验收。若仍有最终检查未记录，保留false，待有真实记录时更新。

旧的`human_check_reports`中`revision_reviewed`继续兼容。自动会话和本人报告关联时用`--timer-session-id`，该报告不另加一遍；确为独立未计时轮次时使用`--independent-of-timer`。关联不明先由AI回查，不自动相加。只有分钟数但无可核来源的旧值保留并标待核，不被timer-sync抹掉，也不升级成实测。

## 自动计时

详细操作见[timing.md](timing.md)。新增review-start/pause/resume/finish/cancel/status、workflow-start/finish、timer-sync/status；这些命令都接收--case，首次用--journal-root设置同一任务计时目录，后续自动沿用。

render沿用已有计时；默认精简编稿，audit才导出五句话案例卡、耗时基线CSV、证据索引、缺项、复用记录和完整计时目录。任务未结束或人工检查未完成时保留缺失，不伪造完整耗时。草稿和阶段快照放work，outputs只保留当前提交文档与用户实际要求的业务成品。

原图只读，已有输出不覆盖；修订后导出到新目录。证据索引保留原路径和包内副本哈希。没有实际应用/验收就保留尚未应用/验收，缺项不按文件数设置门槛。后续批次另建案例，不能把同批复跑当作不同真实批次。
