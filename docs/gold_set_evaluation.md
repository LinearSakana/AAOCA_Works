# Gold Set 设计、评分与版本规则

## 抽样单位与可复现性

抽样单位是**一份唯一内容的 PDF 的一个 1-based 页码**，键为 PDF 内容 SHA256 + 页码；完全相同的 PDF 副本只算一次。默认 48 页：`native_record`、`native_lab`、`ocr_record`、`ocr_lab` 各 12 页。每层 6 页按固定种子随机打散后优先取相对常规页，另 6 页用递减收益的贪心覆盖困难标签与少见 section type。同一患者和同一 PDF 最多各贡献 2 页。固定种子为 `20260925`。这是有意覆盖 failure modes 的**分层评估样本**，不能当作全队列无偏总体准确率；报告总量时也应同时列出各层结果。

困难标签由当前输出的页级/section 级可审计特征得到：多起点、跨页、日期未知/冲突/OCR 待审、低置信 OCR、空文字、密集文字、页外文字、可能含结局信息，以及各 section type。抽样代码不读取医学内容进行语义挑选。Manifest 记录采样算法、种子、baseline 运行收据哈希、PDF 哈希、页码、层与标签。`sample_id` 是 manifest 的摘要。已有目录不允许被采样命令覆盖。

```powershell
python -X utf8 scripts/gold_set.py sample --run data/derived/v0.1_full --gold-dir data/gold_sets/aao_pdf_pages_v1 --pages-per-stratum 12 --seed 20260925
```

原始 PDF 和已核验的 `data/gold_sets/` 均属受限临床数据，不进 Git。要在另一台机器长期复现，需通过受控存储备份**原始 PDF、manifest、annotations 和 revisions**；Git 只保存生成与评分程序。新 pipeline 可重排 document/section ID，评估器仍按 PDF 内容 SHA256 找同一页。如果缺失任何样本 PDF 或页，评估直接失败，避免只算“容易找到”的子集。

## 标注 schema

每页一个 JSON。`text.gold_text` 是人工按 PDF 核对的整页正文，按行分开；`text.status` 为 `ok`、`corrected`、`uncertain`。`sections` 中每段的 `start_line/end_line` 指向**人工文字**，不是任何 parser 的行号；完整页的非空行须无漏无重。每段分别记录 `type`、`subtype`、`date` 的判断状态，日期还记录 value、role、证据与易混淆的 `other_dates`。各字段可标 `uncertain` 或 `schema_gap`；event date 另有 `absent`，表示核验者确认本段没有合适的事件日期。`impact` 是人工判断该段错误可能影响临床抽取的程度。`reviewer/reviewed_at/notes` 留下审阅轨迹。

`status=draft` 不进入评估；`status=unreviewable` 整页排除并报告数量；`status=complete` 才能冻结。冻结修订包含标注 JSON 的摘要和 schema 版本。人工文字状态若为 `uncertain`，该页只计“已审阅、文字不可可靠核对”，文字与结构指标均排除。某个 type/subtype/date 字段的 `uncertain` 或 `schema_gap` 只排除**该字段**，其他可判定字段仍参与对应评分；排除数量单独列出。`unknown` 作为人工确认的真实 type 可以参与评分。

## 评分定义（`page_line_alignment_v1`）

先按 PDF 哈希和页码读取待评估运行的 normalized page text 与 section spans。对人工文字和预测文字做 NFKC，并**仅为 CER 忽略空白**；保留汉字、数字、符号、单位和标点。逐页 exact Levenshtein 编辑距离之和 / 人工参考字符数之和为 `text_cer`，可大于 1；另报 `text_exact_page_rate`。`numeric_token_recall` 用 `\d+(?:[./:-]\d+)*` 抽取数字/日期样式 token，计数多重集交集除以人工 token 总数；它是辅助信号，不证明检验表格的数值列关系正确。

结构比较先对两版页内文字行做保持顺序的一对一相似度对齐。去空白后的行文本相似度至少 0.45 才对齐；未能对齐的预测起点算多余边界，未命中的人工起点算漏边界。只统计**页内** section 起点；页首页尾因为选取的是 PDF 切片而截断，不算边界。`boundary_exact_f1` 要求对齐到完全同一人工行；`boundary_tolerant_f1` 允许相差 1 行。两者均为 `2TP/(2TP+FP+FN)`，无边界时为 null，不把“没有边界”当完美成绩。

将预测 section 覆盖的行映射到人工行号，与人工 section 的非空行集合算 IoU。IoU ≥ 0.5 时按 IoU 从高到低做一对一匹配；未匹配人工/预测段分别是 `missed_section/extra_section`。报告 section 匹配 precision、recall、已匹配平均 IoU。只有已匹配段才计算 `type_accuracy_matched` 与 `subtype_accuracy_matched`（精确字符串相等）；未匹配段通过 section recall 和 failure rows 表现，不能只看匹配后的分类准确率。

`date_value_accuracy_matched` 的分母为已匹配且人工日期是 `known` 或 `absent` 的段；`known` 要求 `YYYY-MM-DD` 完全相同，`absent` 要求预测值为空。另报 `date_value_accuracy_known`，避免大量无日期段提高表面准确率。`date_assertion_rate_known` 是人工已知日期中 pipeline 输出非空且未标 `date_uncertain` 的比例。`date_value_and_role_accuracy_known` 要求日期值与语义都正确；目前仅能从 `date_source` 区分 `test_timestamp_column → test` 与标题/显式文书字段 → `document`，其余角色返回 `unknown`，所以此项也暴露当前 schema 的限制。时间精度（小时分钟）目前**未评分**，仅评分日。

每个比率都在报告的 `counts` 中保留分子/分母；分母为零输出 null。`by_baseline_text_source` 按**固定样本采样时**的 native/OCR 层分开统计，适合跨版本公平比较；`by_evaluated_text_source` 按当前运行实际使用的文字来源统计，便于发现 OCR 路由变化，但两版的组成人群可能不同。`by_gold_type` 保留每种人工 type 的样本数、匹配率、分类与日期正确率以及错误模式计数。逐例 `failures` 用匿名页代号、页码、人工 type、指标、错误模式、影响级别和预测值定位错误；不写原文。日期预测等仍属受限临床信息，评估 JSON 保存在 `data/`。`date_confused_with_print/historical/planned_procedure/...` 只有在人工明确标注的其他日期与错误预测值相同时才赋予，不能凭程序猜原因。

`failure_modes` 按错误实例计数：type/date/subtype/section 错误每段计一次，文字差异每页计一次，漏/多 boundary 按边界数计。逐例 `failures` 中 boundary 行的 `count` 给出该页的边界错误数。用 `unit_id` 在 review 顶栏跳转回 PDF，逐条核对后再决定 parser 修改方向。

## 公平比较与限制

```powershell
python -X utf8 scripts/gold_set.py evaluate --run data/derived/v0.1_full --gold-dir data/gold_sets/aao_pdf_pages_v1 --revision r1 --report data/gold_sets/aao_pdf_pages_v1/evaluations/v01_r1.json
python -X utf8 scripts/gold_set.py evaluate --run data/derived/next_parser --gold-dir data/gold_sets/aao_pdf_pages_v1 --revision r1 --report data/gold_sets/aao_pdf_pages_v1/evaluations/next_r1.json
python -X utf8 scripts/gold_set.py compare --left data/gold_sets/aao_pdf_pages_v1/evaluations/v01_r1.json --right data/gold_sets/aao_pdf_pages_v1/evaluations/next_r1.json --report data/gold_sets/aao_pdf_pages_v1/evaluations/compare.json
```

评估报告记录 sample ID、annotation revision + 摘要、schema/scorer 版本、pipeline 版本、运行 ID、代码文件哈希和运行收据哈希。`compare` 要求这些 Gold Set 与 scorer 标识完全一致、两次评分的页集合一致；不满足则拒绝。报告给出 `right - left` 各指标变化，以及按“页代号 + 指标 + 错误模式”汇总的新旧错误。此比较键不会把同页同类错误的不同具体位置精确配对；需打开 review desk 查看逐例证据。

抽样是页切片，跨页边界只在样本页内可见部分评分；行对齐在严重 OCR 丢失时可能无法可靠映射，报告中的对齐率与 text CER 应一起阅读。类型/日期正确率只在 IoU≥0.5 的段上定义；如果 section 匹配率下降，单独升高的分类准确率不能解释为整体改进。Clinical impact 是人工判断的潜在影响，不等于已经证实的建模损害。本工具不能给出未完成人工标注前的真实 parser 准确率。
