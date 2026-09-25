# AAOCA 相关性例外病例复核

## 1. 复核问题

这里判断的不是患者最终是否确诊 AAOCA，而是：

> AAOCA 或相应冠状动脉异常是否曾在患者诊疗过程中成为实际被考虑、怀疑、检查、讨论、鉴别或排除的方向。

因此，先怀疑并做了针对性检查、后来确认冠脉起源正常的患者仍应标记为 `yes`。普通检查报告偶然写到正常冠脉，或手术知情同意模板列出冠脉造影并发症，并不足以单独构成 `yes`。

## 2. 为什么只复核例外

医院已经筛查过该队列。对 `data/derived/v0.1_full` 的实际逐患者扫描显示，绝大多数患者在诊断、具体冠脉来源、CTA/造影、会诊或手术记录中都有多处明确证据。让人工重复审阅全部患者既增加工作量，也会稀释真正需要判断的病例。

规则因此采用以下流程：

1. 从 section JSON 中抽取带 `document_id`、`section_id`、页码、原文路径和 JSON pointer 的证据；
2. 在患者层聚合，而不是按单个关键词直接分类；
3. 普通高证据病例不进入人工交付物；
4. 只输出资料不足、证据稀疏、始终为疑似、解剖描述冲突或范围边界不清的患者。

## 3. 当前例外条件

| reason code | 需要人工确认的情况 |
|---|---|
| `missing_source_documentation` | 患者在当前输入范围内没有 PDF 或没有 section。 |
| `evidence_only_in_nonclinical_or_laboratory_content` | 相关表述只存在于网页页眉、导航或检验包，缺少临床文书语境。 |
| `single_evidence_section` | 只有一个弱、疑似或非临床证据 section。 |
| `tentative_evidence_only` | 所有正向证据均为“可能、待排、不能除外、显示不清”等状态。注意：若这确实触发了诊疗尝试，最终标签仍应为 `yes`。 |
| `conflicting_coronary_origin_descriptions` | 同一冠脉在不同证据中出现不一致的来源；可能是真实前后变化、术后状态、转录/OCR 错误或文书冲突。 |
| `normal_and_abnormal_origin_same_vessel` | 同一冠脉既有明确异常描述，也有明确正常描述。 |
| `pulmonary_origin_scope_boundary` | 出现 ALCAPA、ARCAPA 或冠脉起源于肺动脉；它与严格 AAOCA 定义不同，但可能作为鉴别诊断或相关冠脉异常进入诊疗。 |
| `single_coronary_or_complex_chd_scope_boundary` | 单支冠脉、冠脉起自另一冠脉，或复杂先心病手术中的冠脉解剖，需要确认是否属于本项目的“相应冠状动脉异常”范围。 |
| `high_origin_without_more_specific_anatomy` | 只有冠脉高位起源/高位开口，缺少更具体的异常解剖。 |
| `normal_origin_and_nonspecific_positive_label` | 正常来源描述与笼统“冠脉异常”标签并存，但没有可解析的具体异常来源。 |
| `sparse_nonspecific_label` | 只有少量笼统诊断名称，没有解剖、针对性检查或处置证据。 |
| `sparse_ocr_only_evidence` | 少量证据全部来自未经人工核验的 OCR。 |
| `no_meaningful_aaoca_evidence_in_adequate_record` | 临床文书覆盖较充分，但没有发现 AAOCA 进入诊疗过程的证据。 |
| `insufficient_evidence_for_reliable_judgment` | 资料不足且不满足更具体原因。 |

规则不会因为“后来排除”而自动给 `no`。`explicit_exclusion` 本身说明该方向曾被实际考虑。

## 4. 运行和文件

```powershell
python -X utf8 scripts/aaoca_exception_review.py build `
  --run data/derived/v0.1_full `
  --output data/review/aaoca_exception_review_v1

python -X utf8 scripts/aaoca_exception_review.py validate `
  --output data/review/aaoca_exception_review_v1
```

人工 CSV 只含例外病例：

- `exception_cases.csv`：一位例外患者一行，保留自动判断、原因、证据摘要和人工字段；
- `exception_evidence.csv`：只保留例外患者的少量、语义不同的证据行；
- `run_metadata.json`：规则版本、源 snapshot 表的 SHA256、聚合计数和人工字段约束；
- `README.md`：本地复核简要说明。

人工只编辑以下列：

- `review_status`: `not_reviewed` / `in_review` / `reviewed`；
- `final_aaoca_judgment`: `yes` / `no` / `uncertain`；
- `reviewer_notes`。

填写最终标签后，`review_status` 必须为 `reviewed`。需要在后续流程使用最终标签前，运行：

```powershell
python -X utf8 scripts/aaoca_exception_review.py validate `
  --output data/review/aaoca_exception_review_v1 `
  --require-complete
```

## 5. 数据兼容和扩展

- 此阶段只读现有 pipeline snapshot，不修改 `patient_manifest.csv`、`section_index.csv`、section JSON 或时间线。
- 输入必须有 `status=complete` 且 source hash verification 已通过。
- 同时兼容旧 section type `surgery_related` 和当前 `procedure`。
- 输出字段顺序由代码常量固定；`ruleset_version=aaoca_exception_rules_v1`，每次输出记录源 `run_metadata.json`、`patient_manifest.csv` 和 `section_index.csv` 的 SHA256。
- 直接标识符仅从 snapshot 的 `private/patient_linkage.csv` 复制到受限的本地 review 目录，便于人工定位；这些文件不能提交或外传。
- `AaocaEvidenceExtractor` 是明确的 middleware contract。未来经单独授权的本地 LLM 可以输出同一证据结构；患者层聚合、例外队列、人工字段和验证约束无需改写。当前版本完全使用 deterministic rules，不调用 LLM 或外部病例处理服务。

## 6. 质量边界

自动结果是复核分流，不是临床金标准。规则可以证明某些可追溯文本被识别并按一致逻辑聚合，不能证明 OCR、文书归属或临床解剖一定正确。对冲突、肺动脉来源、复杂先心病和仅 OCR 证据，必须回看 `exception_evidence.csv` 指向的 section，必要时打开原 PDF 页面。
