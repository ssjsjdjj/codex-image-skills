# 计时覆盖核对

用于案例或使用报告提出时间改善时。仅依据已接入日志、真实反馈和本人主动提供的用时。核对任务范围、样本、处理、检查、重试和正式导出。ai_complete 只表示已登记步骤结束。无返工的 0 需要实际依据。未知保留缺失，无法核实的历史时间只作为结论限制，不影响编稿。

## 覆盖核对格式

任务实际结束并timer-sync后，由AI基于来源填写以下结构，通过`evidence.py coverage`绑定当前范围、样本数和计时数据。字段值是填写说明，必须替换为实际记录；不能仅为通过检查而填complete。

```json
{
  "scope": "本次真实任务的数量、步骤、质量要求及交付边界",
  "components": {
    "ai": {"status": "partial", "basis": "已核对的实际范围", "sources": ["实际日志或事件定位"], "gaps": ["尚未被记录的实际环节"]},
    "check": {"status": "unknown", "basis": "", "sources": [], "gaps": []},
    "rework": {"status": "unknown", "basis": "", "sources": [], "gaps": []}
  }
}
```

status为unknown/partial/complete；complete必须有依据、可回查来源、无未记录环节，partial必须指出缺口。程序只验证字段与一致性，AI仍须打开来源核实。`timing_coverage`独立于数值，旧案例没有该字段就按未知处理。任务、分钟、样本或已记录步骤变化使旧核对失效；只是读状态或新增记录整理事件不应使它失效。估算基线只支持估算结果，不是必须反复追问的缺项。

```text
python <技能目录>/scripts/evidence.py coverage --case <本次案例目录> --file <覆盖核对输入.json>
```

回顾历史时不要同步、改写旧案例或旧日志。用以下只读方式将核对结果写入当前编稿work；该命令不打开旧计时日志，若需计时用当前编稿的run_journal包装。

```text
python <技能目录>/scripts/evidence.py coverage --case <历史案例目录> --file <覆盖核对输入.json> --out <当前work>/coverage-review.json
```

历史人工回答若原case未登记但会话已有：在当前work中建立保留来源的编稿案例副本，补入原话对应事实，case_path指该副本，原case保持只读；不重新问已有答案，不覆盖旧证据。没有起止事件的历史耗时保留未知，不能用重新运行倒填。

## 使用报告预检

证据核验后将 evidence-register 的 review_status 设为 reviewed。给每项已核验任务登记唯一 id，并用 time_comparison 指明正文是否比较用时。比较用时且已有案例证据时填 case_path 绝对目录，可选 coverage_path 指向外置覆盖核对。没有同口径证据时，在正文写明结论限制，照常整理事实。没有核验任务时，填写 no_valid_work_evidence 说明实际检索范围与限制。

在编稿前和交付前分别运行 reporting.py preflight，交付检查加 --delivery。预检的 limitations 用于相关章节，limited_draft 表示可以展示带限制的待核稿。只有未核验、数据结构或证据定位等问题进入 blockers；没有计时、计时不全或无法比较本身不阻塞。预检不读取最终文档，也不代替本人核对。
