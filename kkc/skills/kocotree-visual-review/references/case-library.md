# 案例库：自动整理与引用

本文件规定如何从真实审核记录生成案例，以及如何把案例当作参考。实际案例由脚本生成在项目目录的`case-library/case-reference.md`和`case-library/case-index.json`；本技能包不预置虚构的业务案例。

## 项目目录与触发时机

把每个审核版本保存为`reviews/*.json`，原稿与返稿保留可访问位置。记录`reviewed_at`（含时区的ISO 8601时间）、`product_category`和`product_name`，以便排序和检索。取得主管决定、补齐问题关闭证据或修正旧记录后执行：

```text
python scripts/build_case_library.py path/to/project/reviews --out-dir path/to/project/case-library
python scripts/search_cases.py path/to/project/case-library/case-index.json --category 上衣 --dimension product_visibility --query 主体遮挡
```

首次审核前，若已有团队案例库，可先检索其中同品类、同维度、相似场景。脚本每次从原始JSON重建索引，重复运行结果一致；旧记录更正或撤销批准后，重新运行会更新或移除相应案例。案例文件是派生视图，审核JSON和原始视觉文件才是事实来源。不要直接编辑生成的案例文件；先改源记录再重建。

## 自动入库条件

脚本只提取“问题被解决”的案例。同一`project_id`和稳定问题ID必须在较早的有效记录中为`open`、`partial`或`pending`，较晚记录为`closed`，且后者有`closure_evidence_ids`。较晚记录必须有主管已记录的`direction_approved`或`final_approved`；两版均有可用的`reviewed_at`与`product_category`。更晚版本若将同一问题重开，旧解决案例暂不展示，直到再次关闭并获批准。记录结构校验失败时不生成任何新索引；缺时间、品类或主管批准的候选会列入跳过统计。

案例ID由`project_id`与问题ID稳定生成；同一问题多次解决只保留最新一次已批准且目前仍关闭的解决案例。索引保留前后`review_id`、版本、原文件位置、问题描述、修改动作、验收条件、前后证据及主管决定，不复制图片和个人资料。项目路径和图像的访问权限沿用原文件，不因进入索引而扩大。

## 审核时怎样引用

按品类、评分维度、关键词检索，并打开索引指向的前后审核记录和原视觉文件。引用时写案例ID、可比点与差异点、前后画面位置，说明本稿为何仍需相同或不同的修改。过时的品牌/平台规则须以当前已确认规则为准；不能把历史案例当作新品的商品事实或自动扣分依据。找不到可核验原稿时，仅把案例作为待核查线索，不作为正式证据。

`case-reference.md`供模型按需阅读和`rg`检索；`case-index.json`供脚本检索。两者不自动同步飞书；若需要在已授权飞书表记录案例，应另核对目标表、字段和权限，并执行写后回读。
