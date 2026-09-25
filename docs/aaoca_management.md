# AAOCA 实际治疗与手术整理（deterministic v1）

## 1. 任务边界

本阶段回答的是患者在现有病例中**实际发生了什么**，而不是未来应接受什么治疗，也不是手术适应证研究。

patient-level 主状态为：

| `observed_management` | 证据要求 |
|---|---|
| `surgery` | 至少一个可追溯的、已完成的 AAOCA 相关手术事件。正式手术记录优先；明确既往手术或术后叙述也可支持，但降低置信度并进入复核。 |
| `intended_surgery` | 有针对 AAOCA 的建议、考虑、计划、预约、知情同意、术前讨论、取消或拒绝证据，但没有足够证据证明手术已发生。 |
| `conservative` | 有明确不处理、暂无手术指征、保守治疗、观察或随访证据。没有找到手术记录本身不能产生此状态。 |
| `unknown` | 现有证据不能可靠支持前三种状态。只有冠脉造影/心导管检查、无关手术或文书缺失时仍可为 `unknown`。 |

另有独立字段 `actual_aaoca_surgery=yes/no/unknown`：

- `yes` 只来自已完成 AAOCA 手术事件；
- `no` 只来自强度为 high 的明确未处理/不手术证据；
- 随访、观察、未找到手术记录、手术计划或取消均不能单独证明 `no`，因此保留 `unknown`。

这里的 `conservative` 表示病例支持非手术管理阶段；它不等于终身未手术。若只有较弱的随访/历史观察证据，`observed_management=conservative` 与 `actual_aaoca_surgery=unknown` 会同时保留。

## 2. cohort 的解析方式

输入为：

- `data/derived/v0.1_full/`；
- `data/review/aaoca_exception_review_v1/exception_cases.csv` 及同目录 metadata。

程序要求基础 snapshot 已完成，并核对 review metadata 记录的 `run_metadata.json`、`patient_manifest.csv` 和 `section_index.csv` SHA256。AAOCA 相关性结果采用以下顺序：

1. `review_status=reviewed` 时，`final_aaoca_judgment` 覆盖自动结果；
2. 未完成复核的例外患者使用 `automatic_aaoca_judgment`，空的人工作业字段绝不视为标签；
3. 依据 exception-only contract，未出现在 `exception_cases.csv` 的患者为自动 `yes`；
4. 仅 `AAOCA=yes` 进入 management 输出，`no/uncertain` 保留在 `cohort_selection.csv` 并注明排除原因。

当前输入的 62 例 exception 尚无已完成的人工标签，因此本次 230 个纳入结果全部建立在自动 AAOCA 相关性判断上，不应写成 clinician-confirmed cohort。

## 3. 运行与验证

在项目根目录执行：

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

输出含病例原文片段，只能保存在本地受限、Git-ignored 目录，不得上传到远程 LLM/API 或提交到仓库。

## 4. 输出 contract

### `management_summary.csv`

一位纳入患者一行。主要字段包括：

- cohort：`patient_id`、`aaoca_judgment`、`aaoca_judgment_source`；
- 总状态：`observed_management`、`actual_aaoca_surgery`、`management_confidence`、`management_rule`；
- 手术事件：`n_surgery_events`、`surgery_event_count_status`、首次/末次/全部日期、日期精度、事件 ID；
- 手术归一化：`procedure_types` 与保留原文的 `procedure_names`；
- 证据存在性：完成、意向、取消/拒绝、保守、诊断性操作、无关手术六类布尔字段；
- 主证据定位：`document_id`、`section_id`、页码、section JSON 路径和 JSON pointer；
- 复核：`review_required` 与 `review_reasons`。

### `management_evidence.csv`

每条规则命中一行，保留 assertion 与原始定位。核心 assertion 为：

- `completed`：已完成 AAOCA 相关手术；
- `intended`：建议/考虑/计划/同意，但未证明发生；
- `cancelled_or_declined`：取消、暂缓、拒绝或放弃；
- `conservative`：明确不处理、无手术指征、保守或随访观察；
- `diagnostic_completed`：冠脉造影/心导管等已完成诊断操作，明确不计 AAOCA 手术；
- `unrelated_completed`：真实完成的其他手术，但 AAOCA 关系未建立，明确不计 AAOCA 手术。

`char_start/char_end` 是 section 正文的 0-based、右端不含区间；`evidence_text` 必须等于该区间原文。验证器会重新打开 section JSON 核对这一点。`source_pdf`、页码、`text_path` 和 `text_reference` 提供回到原始病例的路径。

### `surgery_events.csv`

每个去重后的 AAOCA 手术事件一行。正式 `surgery_record` 是事件锚点；术后首次病程、日常病程、出院小结与既往史中的重复描述作为 supporting evidence 附着到最近兼容事件。只有距离所有正式锚点足够远且有明确不同日期的完成证据才形成另一次手术。

手术名保留原文，同时归一到可多选的类型，包括去顶、开口成形、再植/转位、异常起源纠治、修补、重建/松解、搭桥和伴随肺动脉成形。类型用于聚合，不覆盖原手术名。

日期精度为 additive 字段：

- `day`：`YYYY-MM-DD`；
- `month`：`YYYY-MM`，`date_status=partial`；
- `unknown`：不能可靠定位；
- 文书内出现互相冲突的手术日期时保留选中值并标记 `date_status=conflict`，不能当作无冲突日期使用。

### 其他文件

- `cohort_selection.csv`：232 位源患者的 AAOCA 标签来源、是否纳入及排除原因；
- `qc/review_queue.csv`：真正的复核队列；每位 `review_required=True` 患者至少一行；
- `run_metadata.json`：规则/schema 版本、输入路径与 SHA256、计数、`network_processing=false`、`llm_invoked=false`；
- `README.md`：受限输出目录内的简要安全与语义说明。

## 5. 关键 deterministic 边界

- “建议/拟行/计划/考虑/预约/家属同意/术前讨论”只能产生 intent，不能产生完成手术。
- “冠脉造影、升主动脉造影、左右心造影、心导管检查”属于诊断操作，即使文书标题为“手术记录”也不计 AAOCA 手术。
- ASD/VSD/PDA、瓣膜、血管环、肺动脉瓣介入等手术会作为 `unrelated_completed` 保留，不能因同一 section 出现 AAOCA 诊断而自动变成 AAOCA 手术。
- 游离的“冠脉血运重建”等词必须有局部 AAOCA 语境，避免把电生理/抢救预案误判为 AAOCA 手术意向。
- “无手术禁忌症”不是“无手术指征”；前者不能产生保守治疗。
- 明确“AAOCA/异常冠脉未处理”可支持保守阶段；只有历史“未予特殊治疗”或随访叙述时仍保留 `actual_aaoca_surgery=unknown`。
- 同一次手术在多份文书中反复出现不会按文书日期生成多次事件；不同日期的正式手术记录会分别保留。
- 规则允许只有术后/既往叙述而缺少正式手术记录的手术，但置信度降为 medium，并保留日期精度与复核原因。

## 6. QC 和解释边界

复核原因包括：management 不明、只有意向而无完成证据、只有随访/观察、意向与保守阶段并存、多次手术、日期部分/冲突、OCR/date-review 来源以及无法唯一归并的完成证据。不同原因可在同一患者重叠。

这套结果证明的是规则执行、表间一致性、源 hash 和证据定位完整性，不是临床真值或抽取准确率。尚未冻结 management 人工 gold set，因此不能报告 sensitivity、specificity、PPV 或总体 accuracy。尤其要人工关注：

- OCR 对术名、否定词和日期的错误；
- 只有外院既往史、缺少正式手术记录；
- 复杂先心病同台手术中 AAOCA 是否实际被处理；
- 同一患者跨住院阶段的意向、取消、随访和手术时序；
- `unknown` 中只有诊断性造影、资料不完整或尚处诊疗过程的病例。

LLM 阶段必须作为独立 sidecar 工作流，引用本 contract 中已有的 section/evidence ID，并通过结构验证；不能静默覆盖 deterministic 结果，也不能在未经单独授权时把病例内容发送到外部服务。
