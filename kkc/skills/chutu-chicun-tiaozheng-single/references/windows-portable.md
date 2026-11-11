# 3.4 Windows安装、升级与恢复

支持Windows x64及Python3.12/3.13，实际版本以验收记录为准。用Pillow、psd-tools等锁定依赖，Python默认处理普通图片及受支持平坦pixel/位图mask PSD，不支持已有group源（含本包分组结果再次输入）。复杂特征提示人工选PS或兼容副本，不自动flatten/切PS。依赖齐备后Python日常处理无需联网，不需要GPU/抠图模型。

本机PS COM原生路径尚未实机验收，不阻断受支持Python路径；人工选PS后才尝试并核验，失败如实停止，不自动退Python。PS不保证恢复缺失细节。迁移材料本身不授权自动安装。

运行环境在当前账号LOCALAPPDATA/ChutuResizeSingleRuntime，个人状态LOCALAPPDATA/ChutuResizeSingle，技能HOME/.agents/skills/chutu-chicun-tiaozheng-single。动态定位，USERPROFILE按ProfileList识别所属SID，不接管/复制其他账号owner、反馈、批准和历史。

## 准备与批准

~~~powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<包目录>/install.ps1" -Mode Prepare -PythonExe "<可用Python绝对路径>"
~~~

Prepare建独立venv、跑回归、准备候选，不发布。缺Python时优先当前用户级winget，失败按官方来源诊断；不改系统包或永久执行策略。新账号准备初始规则，已有账号保留settings/personal_prompt并展示升级差异，renderer定制须审阅，不重新init覆盖。

展示完整规则、renderer摘要、真实changes.diff、本版变更.diff、测试、实际看过的预览及digest，再取得本账号真实批准。测试确认不授权正式账号。Python、放大闸门、整批预览及PS实机验收分别报告；跳过/模拟PS不算PS实机通过。安装合成PNG不等于真实业务预览或放大批准。

~~~powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<包目录>/install.ps1" -Mode Refresh -PlanPath "<计划>"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<包目录>/install.ps1" -Mode Activate -PlanPath "<计划>" -Digest "<已审阅摘要>" -ConfirmationFile "<真实批准UTF-8文件>"
~~~

草案变更先Refresh验证/审阅；中断凭同计划、摘要、真实批准续跑，不重复init、不自动回退。候选/源/预览改变须重新审阅。旧技能保留backup及.previous目录；未知暂存先诊断，不自动删。

## 业务入口

读取runtime.json专用解释器或使用run_resize.ps1/run_profile.ps1。先main/scene：main预设800x800、1440x1440、750x1000；scene预设750x1000、800x800、800x1200；均多选及自定义，只出所选。默认每size图片1—N，PSD款号_尺寸且内部1—N，不再问固定图片命名。明确自定义再覆盖。

review-start后review-next，先预检整批风险再只预览当前张。PSD输入或含PSD交付的业务，全部候选实际source_viewport推导scale>1的未选项先聚合提示，按size/范围人工选Python/PS；未选不出该轮目标预览。真实已绑定选择复用，源/内容/crop/size变化失效，不学成永久偏好。

每次仅生成当前候选对照预览，标明尺寸和编号。review-adjust修改后重新review-next展示当前张，review-confirm绑定当前digest和真实原文；确认后才review-next下一张。全部候选逐张确认后batch --review。禁止review-preview-all、review-confirm-all和批量风格授权。

PNG默认保留格式/alpha；PSD未设format默认JPG并告知，需要透明可选PNG。图片实际≤500000B，PSD/TXT不受限；每款每size一PSD，附两份说明并记actual backend/scale/risk/basis及真实分组确认来源，未执行不写通过。详细见framing.md、delivery.md。

新聊天检查技能发现，不擅自退出应用或宣称热加载。现有已批准个人提示词升级需审阅差异，不能因为脚本已有新默认就假称个人规则也已批准；固定控制模块不能借图片反馈改写。

