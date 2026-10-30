# 项目文档导航

`docs/` 只保存面向研究人员和协作者的长期说明。这里不保存机器验证回执、原始 JSON、文件摘要、逐次测试输出或临时排错记录。

## 从哪里开始

- [基础流水线与当前快照](pipeline_overview.md)：PDF 匹配、文字提取、OCR、分段、时间线、主要输出与当前限制。
- [Gold Set 人工核验指南](gold_set_review.md)：如何逐页核对 PDF、修正文稿并冻结人工版本。
- [Gold Set 设计与评分](gold_set_evaluation.md)：抽样原则、评分口径和版本比较规则。
- [AAOCA 相关性例外复核](aaoca_exception_review.md)：哪些病例进入人工队列，以及怎样回写复核结论。
- [AAOCA 实际治疗与手术整理](aaoca_management.md)：治疗状态、手术证据、复杂操作与当前汇总结果。
- [AAOCA 管理方式待明确病例后续分类](aaoca_management_followup.md)：77 例未知管理病例的复杂合并病筛查、手术指征/实际结局分轴和医生复核规则。
- [Management LLM 中间件](aaoca_management_llm.md)：当前仅准备请求、尚未接入真实模型的边界，以及未来接入流程。

配套资料：

- [项目背景与临床任务边界](../CONTEXT.md)；
- [本地病例浏览器](../case_explorer/README.md)。

需要了解阶段性决策和版本演变时，再看仓库根目录的 [`SESSION_LOG.md`](../SESSION_LOG.md)。周报展示页、口播稿和本地演示启动器统一放在 [`reports/`](../reports/)；该目录不再承担技术文档或机器回执的存档职能。
