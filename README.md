# AAOCA text pipeline v0.1

本工程将患者 CSV 与医院网页导出的 PDF 整理为可追溯的患者索引、文档分段、时间线和 QC。使用本地 Python、PyMuPDF、规则及可选 RapidOCR；**不调用第三方处理 API，不使用 LLM，不修改原始数据。** 项目背景见 `CONTEXT.md`，本次真实结果见 `reports/pipeline_v0.1_summary.md`。

## 运行

在 PowerShell 中进入本目录：

```powershell
Set-Location E:\AAOCA_Works
python -X utf8 -m pip install -e .
python -X utf8 -m aaoca_pipeline --config config/pipeline.sample.json
```

不做 editable 安装时，依赖已安装的环境也可直接用 `python -X utf8 -m src.aaoca_pipeline`。Python 要求 3.11+；本轮实际使用 Python 3.14。

仅提取全部 PDF 原生文字并产生异常页队列：

```powershell
python -X utf8 -m aaoca_pipeline --config config/pipeline.full.json
```

包含异常页本地 OCR 的完整流程：

```powershell
python -X utf8 -m pip install -r requirements-ocr.txt
# 只下载公开模型，不读任何患者文件；本工作目录已经准备好模型。
python -X utf8 -m aaoca_pipeline.local_ocr download-models --model-dir models/rapidocr
python -X utf8 -m aaoca_pipeline --config config/pipeline.ocr.json
```

模型准备和患者处理分开执行。处理阶段要求全部 ONNX 文件已在本地，缺失时直接报错，不在推理过程中下载。全量 OCR 使用 4 个独立进程，每个进程 2 个 ONNX CPU 线程；可通过配置调整。OCR 只处理 `ocr_recommended` 页面，不对正常文本层页面默认识别。空白页无需 OCR。没有使用 LayoutLM、Donut 或任何 LLM。

小批量核验 OCR 集成时可限制**每份 PDF**的识别页数：

```powershell
python -X utf8 -m aaoca_pipeline --config config/pipeline.sample.json --output data/derived/ocr_probe --ocr missing --ocr-model-dir models/rapidocr --ocr-max-pages 2
```

未处理页面会显式留在 QC 队列。`--ocr-max-pages 0` 表示处理全部推荐页面。正常运行是可重入的：原生提取及 OCR 结果分别按文件 SHA256、提取器/模型版本缓存；患者匹配、标准化、分段、日期、索引和 QC 每次重新生成。中断后重新运行同一命令，会复用已经完成的文档 OCR。不要同时向同一个输出目录运行两个 pipeline。

## 路径与配置

JSON 配置中的相对路径以**配置文件目录**为基准；CLI 覆盖路径以当前工作目录为基准。代码不含实际原始数据路径。`pipeline.full.json` 和 `pipeline.ocr.json` 使用 `${AAOCA_PDF_ROOT}` 指向额外的 PDF 根目录，保留全部来源，但精确重复文件只对分段和时间线贡献一次。

Windows 和 Linux 都可以使用同一份配置。运行 `pipeline.full.json` 或 `pipeline.ocr.json` 前，先把环境变量设为实际 PDF 目录；`pipeline.sample.json` 只使用仓库内的 `data/sample_raw`，不需要设置该变量：

```powershell
$env:AAOCA_PDF_ROOT = 'E:\Kenkyu-Shiryou\AAOCA Cases'
python -X utf8 -m aaoca_pipeline --config config/pipeline.full.json
```

```bash
export AAOCA_PDF_ROOT=/data/AAOCA\ Cases
python3 -X utf8 -m aaoca_pipeline --config config/pipeline.full.json
```

也可以不设置环境变量，直接用重复的 `--pdf-root` 覆盖配置中的 PDF 根目录。相对路径、`~` 和环境变量由程序在读取配置时展开；输入、输出和缓存路径的隔离规则不变。

可完全通过参数使用其他数据：

```powershell
python -X utf8 -m aaoca_pipeline --csv D:/research/cohort.csv --pdf-root D:/research/pdfs --pdf-root D:/research/extra --output D:/research/derived --cache D:/research/cache
```

CSV 默认字段为 `住院号、门诊号、姓名、病历、检验`；自定义字段可在配置的 `columns` 中设置 `inpatient_id/outpatient_id/name/expected_record/expected_lab`。默认尝试 UTF-8 BOM，然后 GB18030；标识符始终按字符串读取，保留前导零。

输出/cache 与任一原始目录或 CSV 所在目录不能重叠。开始和结束都对选中 CSV、PDF 校验 SHA256。ZIP、影像和原始 XLSX 不属于本轮 CSV+PDF 处理范围。原始文件始终只读。

## 输出与语义

完整 OCR 配置输出到 `data/derived/v0.1_full/`；纯文本层配置输出到 `data/derived/v0.1_text_layer/`。

| 文件 | 粒度及用途 |
|---|---|
| `patient_manifest.csv` | 保留 CSV 每一行；PDF/解析/section 数与可靠时间范围。`n_pdf` 计唯一内容，`n_source_pdf` 计所有来源。 |
| `document_index.csv` | 每个来源 PDF 一行，包括重复、未匹配和失败来源；重复行的 `duplicate_of` 指向 canonical 文档。 |
| `section_index.csv` | 每个 canonical 文档分段一行；类型、日期、日期来源、页/行/字符定位、质量标记和正文引用。 |
| `patient_timeline.csv` | 患者匹配明确且日期有模板依据的 section，按患者、时间排序。不是医学事件金标准。 |
| `page_index.csv` | 每页原始字符数、处理状态、OCR 状态和置信度汇总。 |
| `date_mentions.csv` | 正文所有可识别日期与证据，分开存放；这些日期不会自动进入时间线。 |
| `extracted/<document_id>.json` | 原生 PDF 原文、页边界、文字坐标、页级质量诊断，不被 OCR 覆盖。 |
| `normalized/<document_id>.json` | raw、OCR、normalized 三种表示及映射；删除行与原因可查。 |
| `normalized/<document_id>.txt` | 可阅读文本，带显式页面标记和换页符。 |
| `sections/<document_id>.json` | 完整分段正文、逐页 span、日期 evidence 与 mention。 |
| `qc/` | 缺失患者/未匹配文件/身份问题、解析问题、重复来源、日期不确定、OCR 队列、行覆盖账本与 cohort 汇总。 |
| `source_inventory.csv` | 输入路径、SHA256、结束时不变性核验。 |
| `run_metadata.json`、`logs/pipeline.log` | 配置、软件/模型版本、运行状态、计数与过程日志。 |
| `private/` | 本地患者链接表、身份核验原始标识符证据，含直接身份信息。 |

`text_path` 相对于该次运行输出根目录；`text_reference` 是对应 JSON 的指针，例如 `/sections/3/text`。页码、行号是 1-based；`page_spans` 的字符 offset 是 normalized page text 的 0-based、右端不含区间。`normalized_line_map` 按 `normalized_text_source` 指向原生提取文本或 OCR 行。

Section 处理依次为 **boundary detection → `section_type` classification → `section_subtype` classification → `section_title` extraction/normalization**。`section_type` 是粗粒度文书类；原 `surgery_related` 已改名为 `procedure`，覆盖手术、操作及床旁超声等记录。`section_subtype` 是新增的细分角色字段，不参与切分；不能可靠细分时为空字符串。`nonclinical` 用于明确的网页导航、检验导出首页、空白页和仅剩机构/身份抬头的片段；`unknown` 留给仍无法判断的内容。仅含 `nonclinical` section 的 PDF，其 `document_type` 也为 `nonclinical`。`nonclinical` 不提供文书日期，也不进入临床时间线。

检验报告仍以每个 `申请项目:`（包括前有少量 bullet/图标的形式）为边界。`section_title` 优先保留明确的申请项目名称；项目名空缺时，只在项目组合足够明确时恢复“血气分析”或单项检查名，如 `NT-proBNP`、`HS-CTNI`、`血浆肝素含量`。`blood_gas`、`cardiac_biomarker`、`anticoagulation_monitoring`、`mixed_panel` 等属于 `section_subtype`，不代替具体标题。门诊文书也可由就诊日期、科室、主诉、现病史及治疗计划的完整字段组合识别；同一门诊段内再次出现不同的就诊时间和完整的门诊抬头、主诉及现病史时，也视为新就诊，不要求独立标题。新增边界会使后续 section 的序号及 `section_id` 重新编号，使用旧版导出时应重新运行分段。

| `section_type` | 当前可判定的 `section_subtype` 示例 |
|---|---|
| `progress` | `initial_progress`、`daily_progress`、`round`、`first_round`、`critical_round`、`transfer`、`case_discussion`、`postop_progress`、`procedure_imaging_progress`、`antibiotic_adjustment` |
| `administrative` | `treatment_procedure_consent`、`condition_communication`、`admission_notice`、`research_consent`、`leave_commitment`、`infection_control_commitment` |
| `procedure` | `procedure`、`invasive_procedure`、`bedside_ultrasound`、`surgery_record`、`preoperative_discussion` |
| `laboratory` | `blood_gas`、`cardiac_biomarker`、`anticoagulation_monitoring`、`mixed_panel` |

`section_subtype` 同时出现在 `section_index.csv` 与 section JSON；时间线以 `event_subtype` 携带同一角色。已知的 `nonclinical` 段不进入待判文书和日期复核队列；损坏页警告仍保留在 section flags 和页级 QC 中。

PDF 容器往往包含多个不同日期文书。此时 `document_index.document_date` 留空，使用 section 日期及 `earliest/latest_section_date`。出生、导航就诊、打印日期、送样日期与正文提及日期不直接冒充文书时间。检验 `date_source=test_timestamp_column` 是列中的检验时间，并不等于报告审核完成时间。

## 质量界限

`ok` 表示通过当前文本层质量规则，不表示临床结论正确。`partial` 表示部分信息或 OCR 未核验；`text_layer_unusable` 表示原生文字不足以重建中文病例；`empty` 与 `failed` 分开。OCR 恢复结果保留 `raw_parse_status`，不会被改报成原生文本提取成功。OCR 置信度不是经校准的准确率，检验数值和单位仍需人工/几何复核，v0.1 不输出自动配对的检验指标表。

同名或不同 identifier 证据冲突的文件禁止自动归入患者时间线。稳定 URL 的患者编号优先于文书内部可能属于历史就诊的编号，但内部编号若明确指向另一已知患者则隔离。文件名的姓名差异只能由精确编号恢复，不做模糊自动合并。

`unknown` 与 QC 不意味着删除患者。所有 CSV 患者及全部来源文件都保留。SHA256 患者代号是伪名化，不能代替隐私保护；PDF 路径、原文、OCR 与链接表仍含真实患者数据，不能上传或公开发布。

## 时间截点与未来扩展

```powershell
python -X utf8 -m aaoca_pipeline --config config/pipeline.ocr.json --before 2024-01-01
```

此命令不重跑解析，只从完整运行导出严格早于给定日期的记录；排除同日、未知/不确定日期和未经复核的 OCR 日期，可加 `--patient-id`。它是数据选择接口，**不保证消除 leakage**：目前 `available_at` 未知，事后补写文书与正文包含结局仍需检查；保留的 `clinical_stage/leakage_flags/cutoff_review_required` 是后续判定线索。

未来 enrichment 可实现 `enrichment.LocalEnrichmentAdapter`，返回单独的候选字段、方法版本、assertion 状态和证据引用，不改写原始记录。v0.1 未接入任何 LLM，也未把“建议/拟行手术”自动标成实际 surgery。基础分段的 `procedure` 不是治疗已实施标签。

## 验证与重现

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 scripts/validate_outputs.py data/derived/v0.1_full --report reports/validation_v0.1_full.json
```

测试使用合成患者/临时 PDF，覆盖匹配冲突、重复、异常提取、原文保留、打印日期污染、跨页覆盖和时间语义。真实样本与全量迭代及剩余限制记录在 `reports/` 与 `SESSION_LOG.md`。开发中间运行位于 `data/derived/iteration_*`，不可将其计数当作最终结果。

## Gold Set 人工核验与独立评估

用 `scripts/gold_set.py` 从已完成且输入 SHA256 验证通过的运行中固定抽样，浏览原始 PDF 页并校正文字、section、type/subtype 与事件日期，冻结人工答案，再对任意完整 parser 运行评分。同一 PDF 以内容 SHA256 + 页码定位，所以重新分段后 section ID 的变化不会破坏比较。

当前本地已抽取 `data/gold_sets/aao_pdf_pages_v1/` 的 48 页固定样本（4 个 native/OCR × 病历/检验层各 12 页）；样本、文字和人工答案因隐私留在 Git 忽略的 `data/`。**这 48 页目前还没有真正完成的人工 annotation，因此没有可宣称的真实 parser accuracy。** 现阶段可验证的是抽样、标注结构、冻结摘要及合成样本上的评估逻辑。

开始核验：

```powershell
python -X utf8 scripts/gold_set.py review --run data/derived/v0.1_full --gold-dir data/gold_sets/aao_pdf_pages_v1
python -X utf8 scripts/gold_set.py validate --gold-dir data/gold_sets/aao_pdf_pages_v1
```

操作步骤、日期角色和不确定标记见 [人工核验指南](docs/gold_set_review.md)；抽样方法、评分定义、冻结/版本比较命令见 [评估规范](docs/gold_set_evaluation.md)。实际抽样覆盖与局限见 [抽样报告](reports/gold_set_sampling_2026-09-25.md)。

## AAOCA 相关性例外病例复核

当前队列已经由医院筛查，真实文本扫描显示绝大多数患者都有多处 AAOCA/冠状动脉起源异常诊疗证据。因此本阶段不要求人工重复标注全队列，只输出资料缺失、证据稀疏、始终为疑似、解剖描述冲突，或 ALCAPA/ARCAPA、单支冠脉、复杂先心病等范围边界病例：

```powershell
python -X utf8 scripts/aaoca_exception_review.py build `
  --run data/derived/v0.1_full `
  --output data/review/aaoca_exception_review_v1

python -X utf8 scripts/aaoca_exception_review.py validate `
  --output data/review/aaoca_exception_review_v1
```

`data/review/aaoca_exception_review_v1/exception_cases.csv` 和 `exception_evidence.csv` **只包含例外患者**；普通高证据病例不会混入人工交付物。人工只编辑 `review_status`、`final_aaoca_judgment` 和 `reviewer_notes`。若先怀疑并做过针对性检查、后来排除 AAOCA，仍应标记为 `yes`。完整判定定义、reason code、兼容约定和最终完整性验证见 [AAOCA 例外病例复核说明](docs/aaoca_exception_review.md)。该目录包含姓名和院内编号，仅限受限本地使用并由 `.gitignore` 排除。

面向人工的 `AAOCA_exception_review.xlsx` 同样只列出例外病例。复核者在“例外病例”表的黄色三列保存结果后，运行以下命令把三个人工字段安全回写到 CSV；命令会核对完整患者集合，且不会从 Excel 覆盖自动判断或证据列：

```powershell
python -X utf8 scripts/aaoca_exception_review.py import-workbook `
  --output data/review/aaoca_exception_review_v1

python -X utf8 scripts/aaoca_exception_review.py validate `
  --output data/review/aaoca_exception_review_v1 `
  --require-complete
```
