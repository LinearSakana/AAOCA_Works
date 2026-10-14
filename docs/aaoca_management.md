# AAOCA 实际治疗与手术整理（deterministic v1.3）

## 1. 任务边界

本阶段回答的是患者在现有病例中**实际发生了什么**，而不是未来应接受什么治疗，也不是手术适应证研究。`observed_management` 专门表示 AAOCA 的管理状态；为避免把“AAOCA 去向不明”和“患者什么手术都没做”混为一谈，另以 `overall_treatment_status` 表示病例中已观察到的总体治疗路径。

patient-level 主状态为：

| `observed_management` | 证据要求 |
|---|---|
| `surgery` | 至少一个可追溯的、已完成的 AAOCA 相关手术事件。正式手术记录优先；明确既往手术或术后叙述也可支持，但降低置信度并进入复核。 |
| `intended_surgery` | 有针对 AAOCA 的建议、考虑、计划、预约、知情同意、术前讨论、取消或拒绝证据，但没有足够证据证明手术已发生。 |
| `conservative` | 有明确不处理、暂无手术指征、保守治疗、观察或随访证据。没有找到手术记录本身不能产生此状态。 |
| `unknown` | 现有证据不能可靠支持前三种状态。只有冠脉造影/心导管检查、无关手术或文书缺失时仍可为 `unknown`。 |

`overall_treatment_status` 使用同一组值，任何已完成的、可追溯的治疗性操作（包括治疗性导管介入及非心脏手术）都会记为 `surgery`；纯诊断性造影不在其中。具体操作范围由新增的 `other_procedure_modes/categories` 区分。因此，一位完成 VSD/PFO 修补而没有 AAOCA 处理信息的患者会同时保留：

- `observed_management=unknown`：AAOCA 的实际处理无法确定；
- `overall_treatment_status=surgery`、`overall_treatment_rule=completed_non_aaoca_surgery_evidence`：患者确实接受过其他手术；
- `actual_aaoca_surgery=unknown`：不能把其他手术推断为 AAOCA 已处理或明确未处理。

另有独立字段 `actual_aaoca_surgery=yes/no/unknown`：

- `yes` 只来自已完成 AAOCA 手术事件；
- `no` 只来自现有病例窗口内强度为 high 的明确未处理/不手术证据；
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
- 状态：AAOCA-specific 的 `observed_management`，总体实际治疗的 `overall_treatment_status/overall_treatment_rule`，以及 `actual_aaoca_surgery`、`management_confidence`、`management_rule`；
- 手术事件：`n_surgery_events`、`surgery_event_count_status`、首次/末次/全部日期、日期精度、事件 ID；
- 手术归一化：`procedure_types` 与保留原文的 `procedure_names`；
- 证据存在性：完成、意向、取消/拒绝、保守、诊断性操作、无关手术六类布尔字段；另保留无关手术证据行数及原始术名；
- 共病/复杂操作：`other_cardiac_procedure_status`、`other_procedure_modes/categories`、`aaoca_handling_during_other_procedure` 与逐条关联的 `other_procedure_contexts`；
- 疑难研究分层：`management_complexity_flags`、`management_context_evidence_ids`、`complex_case_review_priority/reasons`；
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
- `context_only`：复杂矫治中的冠脉操作、等待进一步讨论等背景事实；本身不改变 AAOCA management，也不能建立 AAOCA surgery。

`char_start/char_end` 是带上下文的 evidence excerpt 在 section 正文中的 0-based、右端不含区间；`assertion_char_start/assertion_char_end` 是触发断言本身的位置。重叠的非手术规则合并为一条证据，`rule_id` 保留代表规则，`matched_rule_ids` 记录全部命中规则；同日但不重叠的决定保留独立位置。验证器会重新打开 section JSON，核对 excerpt 原文以及 assertion span 必须落在 excerpt 内。`source_pdf`、页码、`text_path` 和 `text_reference` 提供回到原始病例的路径。

### `surgery_events.csv`

每个去重后的 AAOCA 手术事件一行。正式 `surgery_record` 是事件锚点；术后首次病程、日常病程、出院小结与既往史中的重复描述作为 supporting evidence 附着到最近兼容事件。只有距离所有正式锚点足够远且有明确不同日期的完成证据才形成另一次手术。

手术名保留原文，同时归一到可多选的类型，包括去顶、开口成形、再植/转位、异常起源纠治、修补、重建/松解、搭桥和伴随肺动脉成形。类型用于聚合，不覆盖原手术名。

日期精度为 additive 字段：

- `day`：`YYYY-MM-DD`；
- `month`：`YYYY-MM`，`date_status=partial`；
- `unknown`：不能可靠定位；
- 文书内出现互相冲突的手术日期时保留选中值并标记 `date_status=conflict`，不能当作无冲突日期使用。

### 共病和复杂处置的研究字段（v1.2 新增）

这些是记录支持的研究筛选层，不表示共病导致某种处置的因果关系，也不是手术指征或疾病严重度评分。当前 schema 为 `aaoca_management_v1.2`，ruleset 为 `aaoca_management_rules_v1.3`。旧 CSV 列保留，新增 `matched_rule_ids` 及操作上下文内的 `procedure_modes`；旧 schema 的生成包须从 source 重建，验证器会明确返回版本不匹配。

| 字段 | 语义与允许值 |
|---|---|
| `other_cardiac_procedure_status` | `completed_other_cardiac_procedure`：有其他心脏治疗性操作；`diagnostic_only_documented`：只发现诊断性操作而未发现其他心脏治疗操作；`none_documented`：未检出上述其他心脏操作。三者均不否认独立 AAOCA 手术。 |
| `other_procedure_modes` | JSON 多选：`cardiac_surgery`、`cardiac_catheter_intervention`、`noncardiac_surgery`、`unclassified_operation`。 |
| `other_procedure_categories` | 依据实际术名细分为间隔缺损修补、瓣膜操作、流出道/肺动脉操作、PDA/主动脉弓操作、肺静脉纠治、复杂先心矫治、其他血管/冠脉操作、血管支架、电生理、心包及非心脏操作等；可能多选。 |
| `aaoca_handling_during_other_procedure` | `concomitant_aaoca_repair`、`explicitly_not_treated`、`assessed_no_intervention`、`anatomy_documented_intervention_unclear`、`coronary_manipulated_target_unclear`、`not_documented`、`conflicting_documentation`、`multiple_contexts`、`not_applicable`。 |
| `other_procedure_contexts` | JSON 对象列表；每项保留 `procedure_evidence_id`、操作日期、`procedure_modes` 多选方式、类别、AAOCA 处理状态及 `handling_evidence_ids`。原标量 `procedure_mode` 在单一方式时维持原值，多种方式时为 `mixed`；多选字段不会包含 `mixed`。这是证据层列表，不能以列表长度当作手术次数。 |
| `management_complexity_flags` | 可并存的事实/疑难标签，例如其他心脏操作后 AAOCA 去向不明、复杂矫治目标不明、仅影像记载未处理、混合管理阶段、拒绝/暂缓、等待讨论、多次 AAOCA 手术及日期不确定。 |
| `management_context_evidence_ids` | 上述分层的原始证据集合，可 join 到 `management_evidence.csv`。单纯证据缺失标签允许空列表，并明确表示缺失而非阳性结论。 |
| `complex_case_review_priority/reasons` | `high/medium/routine` 及原因；优先级服务人工研究抽查，不表示医疗紧急程度。高优先级包括其他心脏操作后 AAOCA management 不明、复杂矫治目标不明、直接处理记录冲突或操作类型无法确定。 |

处理状态只关联同一 section，或同文档、明确同日的正式手术/术后记录；以前的 AAOCA 修复不能填入另一次无关手术。多个操作背景不一致时保留 `multiple_contexts` 并逐项列出。出院记录转录影像中的“未处理”保留 `nonoperation_reported_in_imaging_only`，不会冒充术中直接记录。

ASO 等复杂先心矫治中明确存在冠脉 Button 移植时，保留实际操作证据，但若目的未明确归属于 AAOCA，使用 `coronary_manipulated_target_unclear`。纯 VSD/PFO 修补且未说明冠脉处理时，使用 `not_documented`；其 AAOCA management 继续为 `unknown`，同时可筛选出已完成间隔修补及高优先级复核。

只有伴随肺动脉成形的 AAOCA 术名不会自动产生“共病操作”，因为肺动脉成形本身可能是 AAOCA 的辅助处理。其他操作名称中同时出现封堵/球囊成形与造影时，保留治疗性操作，不能将整份手术记录降为纯诊断操作。

正式手术经过中的冠脉探查/解剖记录可产生 `anatomy_documented_intervention_unclear`：这表示“确有记录，但不能确定是否干预”，不同于完全没有说明的 `not_documented`。既不能把探查等同于修复，也不能根据肺动脉干移位自行推定 AAOCA 治疗目的。

术名分类先隔离编号并去除括号内的解剖型别，避免将“VSD修补(肺动脉瓣下型)2.PFO修补”跨词误判为瓣膜修补。治疗性识别覆盖消融、植入、支架、心包引流/剥脱等；单独“心导管置入”仍是诊断操作。既往其他心脏介入与后续 AAOCA 观察决定可以同时成立，不能让后者抹掉已经完成的治疗。

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

### v1.1 的出院决策与跨阶段规则

2026-10-13 对原 `unknown` 做分层抽查后，补入了以下高精度路径；输出目录与 schema 不变，`ruleset_version` 更新为 `aaoca_management_rules_v1.1`：

- 同一出院/病程 section 已有明确 AAOCA 诊断，且记录内外科讨论、手术风险评估和家属拒绝/放弃手术时，产生 `cancelled_or_declined`，patient-level 为 `intended_surgery`；仍然不能证明手术发生。
- 冠脉评估后，心内外科/心外科明确形成出院观察、随访观察或定期门诊随访决定时，产生 medium-strength `conservative`；`actual_aaoca_surgery` 保留 `unknown`。
- 内外科明确建议手术而家属表示考虑、暂缓或先出院时，产生 `intended`；“将讨论进一步方案”本身不产生 intent 或 conservative。
- 正式手术记录/术后首次病程若明确记录冠脉探查后“未处理/未予处理”，可产生 high-strength `conservative`；同一文书只有 VSD/PFO/ASD 等无关手术而没有这种明确语句时仍为 `unknown`。
- 同一纵向记录中，后续明确的多学科观察决定可以覆盖更早的条件性手术意向；它只改变当前 `observed_management`，不会把终身手术事实推断为 `no`。
- 若只有已完成的 VSD/PFO/ASD 等非 AAOCA 手术，patient-level 仍保留 `unknown`；summary 的主证据会指向该排除性手术证据，QC 另列 `unrelated_operation_without_aaoca_management`，明确提示“做过手术”不等于“AAOCA 已处理或明确保守”。

独立复核后进一步收紧了覆盖规则：相同日期不再自动视为“后发生”，而是继续比较文档内 section 序号和精确 assertion offset；同一 section 中的拒绝手术不能被随附的普通出院随访吞没；影像报告中“请结合 CT/临床，建议随访”的模板句不产生保守管理；出院小结转抄超声“未处理”标签只作为 medium-strength 阶段证据，不能单独把 `actual_aaoca_surgery` 置为 `no`。

负向保护仍然优先：诊断性“手术造影检查”、其他结构性心脏病的手术/拒绝、普通专科随访、“胸外科会诊或门诊随访”这种尚未形成决定的二选一表述，以及无 AAOCA 局部语境的出院随访均不能触发上述规则。PDF/OCR 行内换行可以出现在“观察/随访”等词中，但字符 offset 仍指向原 section 文本。

### v1.2 的独立抽查修正

出院小结的诊断与末尾决策可能相距数页。仅当入/出院诊断字段明确包含 AAOCA、且没有其他可能的手术目标时，远处明确的“暂无（后续/外科）手术指征”才可归属于 AAOCA；合并间隔缺损、梗阻性肥厚型心肌病等时不使用这条补充路径。多行编号诊断必须整体检查，不能只读取第一项。该决定使用文书日期，并可覆盖更早的手术意向；条件句与“无手术禁忌症”不触发。

取消/暂缓规则允许 PDF 行内换行；因个人原因等出院的拟手术记录保留 `cancelled_or_declined`。所有未证实完成的 AAOCA 手术意向至少列为 `medium` 研究复核优先级。复核不等于临床风险评分，也不能强制把 `conservative` 同步为 `actual_aaoca_surgery=no`。

### v1.3 的去重与操作方式修正

同一处“无需手术干预”等断言可以被具体规则和通用规则同时识别。现在只输出一条代表证据，并用 `matched_rule_ids` 保留全部规则来源；不会把同日不同位置的独立决定合并。选代表规则时保留高强度支持及较具体的决定位置，多学科决定的跨阶段判定仍会检查全部命中规则。

编号、加号或标点分开的术名组成部分分别判定操作方式，避免“经皮冠脉造影 + VSD 修补”的造影入路把修补归为导管治疗。混合心脏手术、导管治疗、非心脏手术可以同时出现在 `procedure_modes` 中；患者级 `other_procedure_modes` 汇总所有方式。

## 6. QC 和解释边界

复核原因包括：management 不明、只有意向而无完成证据、只有随访/观察、已完成其他手术但 AAOCA management 仍无证据、意向与保守阶段并存、多次手术、日期部分/冲突、OCR/date-review 来源以及无法唯一归并的完成证据。不同原因可在同一患者重叠。

这套结果证明的是规则执行、表间一致性、源 hash 和证据定位完整性，不是临床真值或抽取准确率。尚未冻结 management 人工 gold set，因此不能报告 sensitivity、specificity、PPV 或总体 accuracy。尤其要人工关注：

- OCR 对术名、否定词和日期的错误；
- 只有外院既往史、缺少正式手术记录；
- 复杂先心病同台手术中 AAOCA 是否实际被处理；
- 同一患者跨住院阶段的意向、取消、随访和手术时序；
- `unknown` 中只有诊断性造影、资料不完整或尚处诊疗过程的病例。

LLM 阶段必须作为独立 sidecar 工作流，引用本 contract 中已有的 section/evidence ID，并通过结构验证；不能静默覆盖 deterministic 结果，也不能在未经单独授权时把病例内容发送到外部服务。已实现的 provider-neutral 原型、运行命令和接入约束见 `docs/aaoca_management_llm.md`。
