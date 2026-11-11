# 自动计时与检查操作

每个真实任务用独立的绝对路径`<计时目录>`；所有命令传相同--journal-root。只采集真实任务；历史非实战数据不能转入真实基线。

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

用户说“开始检查”后：

```text
python evidence.py review-start --case <案例目录> --evidence 用户说开始检查
python evidence.py review-pause --case <案例目录> --evidence 用户说暂停检查
python evidence.py review-resume --case <案例目录> --evidence 用户说继续检查
python evidence.py review-finish --case <案例目录> --evidence 用户说检查完成
```

开始/暂停/继续/完成严格按真实指令执行，可多轮检查。运行和暂停期间不能重复开始；没有开始不能完成。已开始后用户明确确认当前预览并要求生成，也可结束本轮检查，同时另记其质量确认。不会自动记录业务验收。多次完整检查累加，暂停等待不计。需要作废用review-cancel并保留原因，取消或未结束的检查不能报为完整人工用时。脚本用跨进程单调时钟并核对墙钟，检测重启或时钟异常时保留待核验状态。

## 收尾和基线

```text
python evidence.py workflow-finish --case <案例目录> --evidence <本次任务实际完成状态>
python evidence.py timer-sync --case <案例目录>
python evidence.py render --case <案例目录> --out <新的交付目录>
```

计时汇总只计算已接入的步骤：顶层AI执行窗口取并集，子步骤可逐个追溯，错误尝试包括在实际耗时里。额外返工与AI已覆盖时间不重复。完整AI用时需要任务结束边界和全部步骤终态；人工用时需要至少一轮真实开始/完成且没有未结轮次。没发生额外返工且任务完整时可确认返工为0；不是拿缺失当0。

每条事件独立文件，写入后flush+fsync，进程正常异常都留痕；断电、强制杀进程无法承诺写结束，已写开始会被识别为incomplete，不能补猜结束时间。记录损坏/漏结束会阻止生成完整AI用时。旧缺失与未接入操作继续留空。

人工基线、样本数、同口径说明仍按事实填写；baseline是估算时不能因运行计时是真实就变为已独立核实。未知项不填0，不从文件修改时间、会话等待或新跑一遍反推历史用时。缺项仅汇总3～5条。

白底入口还支持：

```text
python launch.py check-start --journal-root <计时目录> --evidence 用户说开始检查
python launch.py check-finish --journal-root <计时目录> --evidence 用户说检查完成
python launch.py workflow-start --journal-root <计时目录> --evidence <真实任务范围>
python launch.py workflow-finish --journal-root <计时目录> --evidence <完成状态>
python launch.py timing-status --journal-root <计时目录>
```

AI看图步骤仍用本目录run_journal.py的mark-start/finish，由AI在实际操作前后记录；不会自动读取未授权的系统活动或监控人。
