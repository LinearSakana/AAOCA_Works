# AAOCA 实际治疗与手术整理

## 1. 任务边界

这一步只回答病历中已经有证据支持的管理事实：是否完成了 AAOCA 相关手术、是否形成了手术意向、是否明确选择观察/随访，以及是否完成过其他治疗性操作。

它不会根据疾病名称、风险印象或“应该如何治疗”推测真实处置，也不会把未找到手术记录解释为没有手术。当前结果来自可回溯的确定性规则，尚未经过完整的临床 Gold Set 评估。

## 2. 三个需要分开的结论

### AAOCA 专属管理状态

`observed_management` 有四种值：

| 状态 | 含义 |
|---|---|
| `surgery` | 有可靠证据表明完成了 AAOCA 相关手术。 |
| `intended_surgery` | 有明确建议、计划、术前准备、同意或拒绝/暂缓证据，但没有完成证据。 |
| `conservative` | 有明确的观察、随访或暂不干预决定。 |
| `unknown` | 当前资料不足以确定上述任一状态。 |

### AAOCA 手术是否实际发生

`actual_aaoca_surgery` 单独保留 `yes`、`no`、`unknown`。它不能简单从四分类反推：

- `surgery` 必须对应 `yes`；
- `intended_surgery` 不能证明已经完成；
- 一般观察或随访通常仍保留 `unknown`；
- 只有明确、高强度的未处理或不手术证据，才能支持 `no`。

### 总体治疗状态

`overall_treatment_status` 与 AAOCA 专属状态使用相同的四种取值，但范围覆盖患者记录中的全部治疗，而不只看 AAOCA。只要存在已完成的 AAOCA 手术或其他治疗性操作，它就是 `surgery`；若没有任何完成操作，则沿用 AAOCA 专属状态的 `intended_surgery`、`conservative` 或 `unknown`。其他操作包括 VSD/PFO/ASD 修补、瓣膜或血管介入、消融和非心脏手术，但这些事实不会被自动解释为 AAOCA 已治疗。

例如，一位患者确实做过 VSD 修补术，但记录没有说明 AAOCA 是否处理，可以是：

- `overall_treatment_status=surgery`；
- `observed_management=unknown`；
- `actual_aaoca_surgery=unknown`。

这个分离是当前规则中最重要的安全边界之一。

## 3. 当前正式结果

当前正式包位于 `data/derived/aaoca_management_rules_v1/`，纳入相关性规则判为 `yes` 的 230 位患者：170 位普通高证据病例，加上 [62 位例外队列](aaoca_exception_review.md) 中暂列自动 `yes` 的 60 位；另外 2 位 `uncertain` 未纳入。例外人工复核尚未开始，如果部分自动判断被推翻，Management 分母与分布需要联动重建。因此以下结果是研究分流结果，不是临床金标准。

| 状态 | AAOCA 专属管理 | 总体治疗状态 |
|---|---:|---:|
| `surgery` | 111 | 158 |
| `intended_surgery` | 11 | 9 |
| `conservative` | 31 | 17 |
| `unknown` | 77 | 46 |

`actual_aaoca_surgery` 为 111 `yes`、14 `no`、105 `unknown`。系统整理出 112 个去重后的 AAOCA 手术事件，来自 111 位患者；一位患者有两个不同日期的事件。111 个事件的日期精确到日，其中 108 个没有检测到来源冲突、3 个保留冲突标记；另有 1 个事件只能确定到月份。111 个事件有正式手术记录，1 个主要依赖多处一致的既往/术后记载。

归一化术式可以在同一事件中重叠：冠脉修补 76 次、去顶 42 次、起源矫正 34 次、冠脉开口重建 8 次、重建/松解 5 次、再植或转位 3 次、未进一步细分的异常修复 1 次；16 次同时记录肺动脉成形等辅助操作。这是文书术式构成，不是互斥治疗组。

这些结果保留 1,693 条证据断言和 340 条复核提示。数字用于说明当前数据包规模与人工复核负担，不能换算为抽取准确率、治疗率或疗效结论。

## 4. 什么能、什么不能证明手术完成

### 可以支持完成

- 正式手术记录或术后首次病程中明确记载已完成的 AAOCA 修复；
- 明确的术式、完成状态和相互一致的来源证据；
- 对院外既往手术，只有在多处历史/术后记录一致支持时才保留，并标明日期精度较低。

重复的术后病程、出院小结和既往史会附着到同一个事件，不会因为文书数量多而重复计数。

### 不能单独支持完成

- “拟行、建议、考虑、同意、术前讨论、手术指征”等意向文字；
- 家属拒绝、暂缓或出院后再议；
- 冠脉造影、心导管等诊断性操作；
- 同次住院完成了其他先心病手术，但没有说明 AAOCA 是否处理；
- 影像报告中复制的“未处理”或普通随访模板句；
- 没找到手术记录。

## 5. 纵向决策怎样处理

病历可能先出现手术意向，后出现拒绝、观察或实际手术。规则按可确定的文书日期、section 顺序和原文位置组织轨迹：

- 明确的后续手术可以覆盖早期意向；
- 明确的后续观察决定可以把当前 `observed_management` 改为 `conservative`，但不自动把终身手术事实改成 `no`；
- 同一 section 中的拒绝手术不能被附近普通“随访”措辞吞没；
- 同一天不能只凭日期判断先后，仍需使用文书内顺序；
- 条件句、“将讨论进一步方案”和影像模板随访不形成确定管理结论。

当出院诊断与末尾决定相距很远时，只有诊断字段明确指向 AAOCA、且不存在其他更可能的手术目标，才会把“暂无手术指征”等结论归给 AAOCA。复杂先心病或并列竞争诊断下保持谨慎。

## 6. 复杂操作与冠脉处置

为了审阅复杂病例，当前包额外记录：

- 已完成操作的名称、日期和操作方式；
- 是否存在其他心脏治疗性操作、诊断性操作或非心脏手术；
- 每次操作中冠脉是被修复、明确未处理、仅评估、记录不清，还是完全未说明；
- 多学科讨论、待定决策和复杂操作带来的研究复核优先级。

这些字段只用于研究筛选和解释证据，不是临床风险评分，也不表示共病导致了某种治疗。解剖性描述、术中探查和 Button 转位等复杂信息，只有在明确支持 AAOCA 靶向治疗时才可建立 AAOCA 手术事件。

混合操作会逐个术名判断。诊断性造影采用的导管入路不会把同一记录中的外科修补错误标成导管治疗；同一患者可以同时具有外科、导管和其他操作方式。

## 7. 输出文件

| 文件 | 用途 |
|---|---|
| `cohort_selection.csv` | 每位患者如何从相关性结果进入或排除出 Management 队列。 |
| `management_summary.csv` | 每位患者的 AAOCA 状态、总体治疗状态、主要证据和复核标记。 |
| `management_evidence.csv` | 每条完成、意向、保守、诊断或其他手术证据及其来源位置；复杂操作与冠脉处置也保存在这里和患者汇总字段中。 |
| `surgery_events.csv` | 去重后的 AAOCA 手术事件。 |
| `qc/review_queue.csv` | 需要人工优先回看的不确定、冲突、混合阶段、日期或复杂情况。 |

患者级输出和临床原文保留在 Git 忽略的本地目录。公开文档只使用聚合结果。

## 8. 运行与检查

```powershell
python -X utf8 scripts/aaoca_management.py build `
  --run data/derived/v0.1_full `
  --aaoca-review data/review/aaoca_exception_review_v1 `
  --output data/derived/aaoca_management_rules_v1

python -X utf8 scripts/aaoca_management.py validate `
  --run data/derived/v0.1_full `
  --aaoca-review data/review/aaoca_exception_review_v1 `
  --output data/derived/aaoca_management_rules_v1
```

如果来源快照、相关性复核或规则发生变化，应从来源重建整个包，而不是手工修改 CSV。LLM 如需参与，只能作为独立 sidecar 使用，不能静默覆盖这些确定性结果，详见 [Management LLM 中间件](aaoca_management_llm.md)。

## 9. 人工复核重点

- OCR 中的术名、否定词和日期；
- 只有院外既往史、缺少正式手术记录的事件；
- 复杂先心病同台手术中 AAOCA 是否实际处理；
- 同一患者跨住院阶段的计划、拒绝、观察与手术时序；
- 只有诊断性造影、其他手术或资料不全的 `unknown`；
- 明确 `no` 是否真的来自直接管理/手术证据，而不是复制的影像描述。

在单独的 management Gold Set 完成前，不报告 sensitivity、specificity、PPV 或总体 accuracy。页面级 Gold Set 的版本与评分原则见 [Gold Set 设计、评分与版本规则](gold_set_evaluation.md)，但它当前不替代 management 标注集。
