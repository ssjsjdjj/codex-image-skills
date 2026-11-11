# 自动计时与检查操作

使用计时记录的任务用独立的绝对路径`<计时目录>`；所有命令传相同--journal-root。只采集真实任务；历史非实战数据不能转入真实基线。

## 正常流程

```text
python evidence.py init --out <案例目录> --mode real --title <任务名称> --journal-root <计时目录>
python evidence.py workflow-start --case <案例目录> --evidence <本次实际任务范围>
```

关联路径会记入case.json，后续evidence.py命令自动沿用。白底V2的plan、preview、review、approve、batch等同样加--journal-root <计时目录>；当前参数和审批要求保留。

其他执行程序交由包装器自动记录，不要手工在成功后补秒数：

```text
python run_journal.py --journal-root <计时目录> run --label <步骤名称> -- <解释器或程序> <实际参数>
```

先写开始事件再调用子进程，成功写结束，非零退出/异常写错误和耗时后继续抛出异常。重试用新的步骤ID，不覆盖前次。子进程继承计时目录、模式和父步骤；嵌套不重复累加。额外返工可加--category rework，但已计入AI的修边不再重复扣除。命令参数不原样写入日志，避免带出凭据；程序错误文本仍按原错误记录，交付前按任务内容核对。

AI实际看图等非脚本工具步骤：在调用工具前运行mark-start --label <步骤>，保存返回的id；立即完成工具和分析后运行mark-finish --id <id> --evidence <实际观察或输出>，出错用mark-error。不能把对话间隔推定成AI运行，也不能打开步骤后等待人回复。

## 人工检查

仅在用户主动要求计时或明确发出计时开始指令后执行：

```text
python evidence.py review-start --case <案例目录> --evidence 用户说开始检查
python evidence.py review-pause --case <案例目录> --evidence 用户说暂停检查
python evidence.py review-resume --case <案例目录> --evidence 用户说继续检查
python evidence.py review-finish --case <案例目录> --evidence 用户说检查完成
```

开始/暂停/继续/完成严格按真实指令执行，可多轮检查。重复开始或完成消息不得重置已有计时、追加耗时或补造开始；没有开始记录不能推定劳动用时。上一轮已结束后，用户明确开始新的复核才创建新轮次。多次完整检查累加，暂停与等待不计；需要作废用review-cancel保留原因，未结束或取消的检查不能报完整人工用时。脚本用跨进程单调时钟核对墙钟，时钟异常时保留待核验状态。

“检查完成”只结束计时。用户明确“可用/需要修改”等结论另用`closeout`的quality_status及source登记；实际产物状态用production_status登记。质量确认不是业务验收，也不是对案例提交稿的事实确认。

## 直接报告检查用时

本人说“检查30秒”时可直接记录：

```text
python evidence.py review-report --case <案例目录> --review-id revision-2 --seconds 30 --evidence "本人说检查30秒，并要求人物左移"
```

本人主动报告的检查时长按原话保存。同期有自动检查计时会话时核实是否同轮，分别使用 --timer-session-id 或 --independent-of-timer。

需要核算净节省时，每次重输出需本人检查的新版本后，用`closeout`记录`check_time_complete=false`，来源指向该次预览，避免沿用上一版的检查完整标记。只有各轮和最终版本检查用时均已有实际来源时才能设true；不因单说“确认”就填出分钟。

## 收尾和基线

```text
python evidence.py workflow-finish --case <案例目录> --evidence <本次任务实际完成状态>
python evidence.py timer-sync --case <案例目录>
python evidence.py coverage --case <案例目录> --file <基于真实来源填写的覆盖核对.json>
python evidence.py submission-status --case <案例目录>
python evidence.py render --case <案例目录> --out <work中的编稿目录>
```

有计时的任务在实际结束时运行 workflow-finish，使用返回的 closeout_review 整理案例。没有人工用时照常成稿，不主动询问。本人确认当前案例内容后才记录为可提交。

计时汇总只计算已接入的步骤：顶层AI窗口取并集，子步骤可追溯，错误尝试计入，额外返工与AI已覆盖时间不重复。已登记AI用时需要任务结束边界和全部步骤终态；自动人工用时需要真实开始/完成且无未结轮次；本人直接报告另按原话采集及去重，不能升级为自动实测，二者需核实不重叠。这些条件不能证明全任务覆盖，另按[coverage.md](coverage.md)核对实际发生的处理、模型/工具调用、复查、修复重试及正式导出验证。未接入的环节保持partial/unknown，不能因ai_complete或已有数值就宣称完整。任务覆盖已核实且未发生额外返工时可确认返工分钟为0，不是把缺失写0。

日志中的技术返工步骤数只放`timing_journal.technical_rework_step_count`。实际rework_count按human_return或revision_round及真实依据填写，同步不自动覆盖；旧数据未说明口径时不对外宣称人工次数。次数未知仍可计算已经齐备的分钟，技术步骤数既不是本人退回次数，也不是需扣除的分钟。

每条事件独立文件，写入后flush+fsync，进程正常异常都留痕；断电、强制杀进程无法承诺写结束，已写开始会被识别为incomplete，不能补猜结束时间。记录损坏/漏结束会阻止生成完整AI用时。旧缺失与未接入操作继续留空。

人工基线、样本数、同口径说明仍按事实填写；baseline为估算时，净节省亦标为估算。未知不填0，不从文件时间、会话等待或新跑一遍反推历史用时。只呈现实际影响净节省结论的计时限制。
