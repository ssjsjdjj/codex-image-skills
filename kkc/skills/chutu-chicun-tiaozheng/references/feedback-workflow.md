# 3.4账号、反馈和审批命令

## 账号目录与首次启用

迁移环境支持Python3.12/3.13；依赖以requirements-lock.txt为准。使用本机已验证可用的专用解释器，不要假设 `py` 一定安装。依赖齐备后日常运行不需要联网。摄影图几何预览使用Pillow，汇总PSD使用psd-tools等锁定依赖。3.4默认Python支持平坦pixel层/位图蒙版，不支持已有group源（含本包分组结果再次输入）；复杂文字、智能对象、矢量、效果或组等提示用户选PS或兼容副本，不自动flatten/切PS。

PSD输入或含PSD交付的正式任务先按实际source_viewport计算scale；大于1时先提示倍率和可能模糊、细节变软，建议使用Photoshop（PS）放大，并取得本批真实PS或Python选择，未选前不生成目标尺寸预览或正式输出。已绑定当前输入、内容、裁切和尺寸的明确选择直接复用，任一依据变化即失效。不能用反馈累计、风格授权或Python默认替代人工放大选择，也不能把本批选择学习成永久自动放大。Photoshop不能保证找回缺失细节；本机PS COM路径尚未通过实机验收，但不阻断受支持的Python路径，选PS后失败也不自动换Python。

下文在技能目录运行，`python` 代表可用解释器；中文乱码先设置 `$env:PYTHONIOENCODING='utf-8'`。所有 JSON 用 UTF-8，路径优先用绝对路径。

```powershell
python scripts/user_profile.py status
python scripts/prepare_initial.py --out "D:/测试/初始草案" --spec "D:/测试/样例任务.json"
```

正式目录固定为当前 Windows 账号的 `%LOCALAPPDATA%/ChutuResize`。迁移版用 `USERPROFILE` 在Windows `ProfileList`匹配所属SID来检查归属，避免Codex沙箱进程SID造成误判；匹配失败或有歧义时停止。这是按账号隔离的工作流程，不额外改变 Windows ACL，也不是防止管理员读取其他账号文件的加密系统。账号切换即切换默认根目录。新账号需单独确认初始规则；不能拷贝他人 `owner.json`、反馈或版本库，也不自动迁移SID不一致的旧状态。模板里的规则是起点，当前账号的偏好经其确认才能启用。

首次草案生成在用户选定的测试目录，包含 `snapshot`、验证报告和预览，不产生正式配置。向用户展示初始规则及实际样例；确认后才执行：

```powershell
# 下列占位文字必须换成用户这次真实的批准原文。
python scripts/user_profile.py init --snapshot "D:/测试/初始草案/snapshot" --validation "D:/测试/初始草案/validation.json" --confirmation "<用户实际批准原文>"
```

若用户要求修改草案，编辑 snapshot 后重新调用 `validate_snapshot`（见文末）刷新验证；旧报告不会通过。已有账号不能重复 `init`，必须走待审提案。正常运行入口为 `scripts/resize_assets.py`，会加载 `current.json` 指向的三份个人文件。

这里的首次启用测试任务须已含每项明确size，可使用安装自带样例或已展开任务。它不授权跳过业务delivery、用途及本批明确所选尺寸。3.4默认同size图片1—N、PSD款号_尺寸，不再把两类人工命名设为必填。业务jobs可无size，先正式review-start按delivery.sizes展开。

目录结构：

```text
ChutuResize/
  owner.json                  Windows SID
  current.json                当前已批准版本及摘要
  versions/v-.../              配置、提示词、裁切脚本、版本记录
  batches/b-....json           实际参数、原图路径、输出路径、是否已询问
  feedback.jsonl              文字、参数、图片路径，不复制原图
  proposals/p-.../             候选副本、精确差异、测试报告及预览
  incidents.jsonl             异常；没有自动回退
  audit.jsonl                 生效和回退的确认记录
```

测试时才用 `--state "D:/测试/独立账号状态"`；其权限与归属检查仍然有效。不要用这个选项指向别人的账号目录。

## 一批结束，询问一次

默认整批分组预览队列经真实review-confirm-all后，通过`batch --review`完成才算一批，不论多少张只询问一次反馈。预览、调整、整批确认不注册正式出图批次；预览确认不等于满意反馈，也不表示人类逐张单独看过。失败时有pending/partial/failed批次清单，完成后才feedback_due。成功结果含 `feedback.batch_id`、`feedback_due`，批量时只在第一项返回。记录已捕获版本号，防止并行任务中途变更归属。旧单张仅用户明确要求时使用。

```powershell
python scripts/user_profile.py mark-asked --batch "<批次ID>"
```

仅在返回 `ask_now:true` 时向用户展示本批结果并问一次，例如“这批构图满意吗？可说明主体大小、白边、位置或要保留的部位，也可跳过。”不把继续下一批或沉默记成满意。用户回复后记录；不再循环催问。

## 解释和收集反馈

范围：`once` 仅此次；`general` 未明确长期的可复用反馈；`long_term` 用户明确说以后/默认/长期。若只说“这张往上些”，按 once。若不清楚是批次修改还是长期偏好，先询问。单纯满意但没有可提炼的修改时，可用 once 记录此次评价，不累计成修改建议。

同类需有相同、具体主题和相同结构化修改；不要把相反反馈都放进 `position` 这类宽泛主题。自然语言语义判断由 Codex完成，脚本只按 `topic` 和 `desired_patch` 计数，不使用词向量或训练模型。

```powershell
python scripts/user_profile.py feedback --batch "<批次ID>" --text "仅这张向上挪一点" --topic "single_image_move_up" --scope once
python scripts/user_profile.py feedback --batch "<批次ID>" --text "以后所有场景图不要新增白边" --topic "scene_no_added_border" --scope long_term --patch "D:/测试/规则修改.json"
```

`规则修改.json` 可为：

```json
{"defaults":{"fit":"cover","allow_padding":false,"on_conflict":"error"}}
```

补丁仅可表达用户明确反馈；不要将“自然美观”直接等价为固定焦点、统一放大倍数或裁切比例。无精确参数则省略 `--patch`，仅提提示词草案。普通反馈需来自 3 个不同批次，同批重复不累加；明确长期偏好立即提议。记录反馈不会更新正式版本。

脚本先生成保守的参数/提示词草案。Codex应检查其内容：合并重复规则，替换明确被取代的旧规则；范围有冲突先询问。修改 `candidate` 后必须重新验证，验证会重建精确差异和摘要。若相同规则已存在，先检查实际执行参数、旧入口或程序行为，不能靠反复追加提示词解决。

## 草案、验证、一次确认

能力不足或程序错误才考虑 `renderer.py`。在独立目录放被修改的文件，文件名仅限 `settings.json`、`personal_prompt.md`、`renderer.py`。程序修改前理解原有行为，加入针对此问题的实际回归样例；保留几何与原图保护检查。不得用反馈渠道修改控制器或验证器。

```powershell
python scripts/user_profile.py propose --changes "D:/测试/修改文件" --summary "修复保护区域冲突时的构图错误"
python scripts/user_profile.py validate --proposal "<草案ID>" --spec "D:/测试/已展开复现任务.json"
```

验证不把任务单中的 `out_dir` 当作正式交付位置。摄影图使用内存渲染和独立预览；受支持PSD默认使用Python副本，保留可支持的图层与蒙版并检查，不写回源文件。PSD输入或含PSD交付的验证若实际需要放大，仍先取得绑定当前依据的人工后端选择；只有实际选PS才调用原生后端并产生独立变体和缓存。无PSD交付的安装合成PNG或纯几何诊断不冒充业务决策。验证包含尺寸/比例/补边政策/保护区域/禁止覆盖原图检查；原层保留与像素、蒙版、merged预览必须按实际执行项目记录，未执行不写通过。必须选择能复现反馈的真实素材，并检查代表性不同构图；合成示意图只是基础检查，不能单独证明审美改善。

提案验证用已展开且每项含size的清单，例如该账号review队列的approved-spec.json，或等价的复现任务单；不要直接把尚未展开、jobs无size的原始delivery任务单当作低层几何验证清单。实际数据包的分组PSD、字节预算和说明文件仍须通过正式交付入口验收，不能凭几何预览通过就声称整包已完成。

验证后读取 `proposal.json` 最新摘要、`changes.diff`、`review.md`、`validation.json`，给用户看：具体改了什么、适用范围、硬性测试是否通过、原图与候选结果预览、已知影响。脚本更改还需说明回归验证。一次确认后：

```powershell
python scripts/user_profile.py approve --proposal "<草案ID>" --digest "<已展示且验证通过的最新摘要>" --confirmation "<用户本次实际批准原文>"
# 不同意则记录原因，正式版本不变
python scripts/user_profile.py reject --proposal "<草案ID>" --reason "用户希望调整适用范围"
```

不能为追求自动化捏造确认。脚本检查确认字符串非空，无法判断真实发言者；Codex负责核对人类消息与所审草案。测试程序里的“批准”只用于隔离测试，不能授权正式账号。

审批绑定候选三文件的 SHA256 组合摘要、当前基线版本、通过的测试、测试原图和预览摘要。任一发生变化或草案过时则拒绝，重新测试和展示。保留总共 3 个有效版本（含当前版）；已应用候选的完整副本会删除，完整历史只在 versions 中按此数量保留。待审/驳回草案和差异日志可能另有记录，但不作为可回退正式版本。

## 异常和手动回退

错误大小、非授权补边/拉伸和保护区域缺失会在写图前检查。出错后返回逐图完成清单并停止，不删除已完成文件；PSD缺失按部分交付报告。读取同一队列记录后可用batch --review加--resume续跑，哈希不一致时停止。部分输入/路径错误也会被记录，不能把所有异常都归咎于审美规则。查看原因、可回退版本和影响，让用户选择；未回复不回退。

```powershell
python scripts/user_profile.py versions
python scripts/user_profile.py rollback --revision "<用户选择的已保留版本>" --confirmation "<用户实际同意回退的原文>"
```

回退切换已批准的完整配置、提示词和脚本。旧版本超过保留数量则不可回退。路径被移动/图片删除时无法复现原反馈，应先重新定位源图；反馈存储不保留原图备份。

## 编辑初始草案后重新验证

在技能目录创建一次性 Python 驱动，调用固定验证器：

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "scripts"))
from user_profile import write_json
from task_spec import load_jobs
from validate_candidate import validate_snapshot
jobs = load_jobs("D:/测试/已展开样例任务.json")
report = validate_snapshot("D:/测试/初始草案/snapshot", "D:/测试/初始草案/previews", jobs)
write_json("D:/测试/初始草案/validation.json", report)
```


## 用途与经验提取
3.4先分main/scene并用对应预设、多选与自定义，只出所选；默认每size图片1—N，不把旧人工命名要求当默认。整批预览的真实确认来源和每size编号映射单独记录，presets/size_selections/naming_source只是spec配置来源，不代替真人预览确认。人工放大后端选择仍先于整轮目标预览，所有未选风险按size/范围聚合一次提示；整批确认不能批准未作出的后端选择。

主图和场景图分别记录用途、商品品类、尺寸、原图或PSD与认可结果路径，以及真实反馈。相同主题/结构化修改也不能把不同用途和品类混在同一次3批累计中。初始通用品类表是规划依据，不是从本批满意自动提取的主图规则。

提炼的是适用条件与判断，例如哪类画面需保全哪些商品细节、什么情况下允许非重点部位出画；不能因为几张案例都用了同一坐标就规定所有商品固定居中或80%。需要明确扩大到跨用途的长期偏好时先问清范围，在提案中整理适用条件，验证并展示差异后批准。
