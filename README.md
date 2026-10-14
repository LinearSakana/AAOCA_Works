# AAOCA text pipeline v0.1

本工程面向小儿先心病 **AAOCA（异常主动脉起源冠状动脉）** 亚组，将患者索引 CSV 与临床导出 PDF 转换为结构化、可追溯的患者文档 sections、时间线和质控索引，并在此基础上提取 AAOCA 相关性、临床管理分类及手术证据。

> 核心技术栈：基于 Python、PyMuPDF、机械规则及 RapidOCR 离线执行。
> 
> 另有一个测试性的 LLM Middleware，提供独立的结构化请求构建、Prompt 模板、响应校验 pipeline。

**相关参考**：

- 项目背景与临床任务边界：[CONTEXT.md](CONTEXT.md)

- 文档导航：[docs/README.md](docs/README.md)

- 基础流水线与当前快照：[docs/pipeline_overview.md](docs/pipeline_overview.md)

## 初始化

PowerShell 进入本目录：

```powershell
python -X utf8 -m pip install -e .
python -X utf8 -m aaoca_pipeline --config config/pipeline.sample.json
```

若依赖已经安装，也可直接执行 `python -X utf8 -m src.aaoca_pipeline`。运行环境要求 Python 3.11+。

仅提取全部 PDF 原生文字并产生异常页队列：

```powershell
python -X utf8 -m aaoca_pipeline --config config/pipeline.full.json
```

包含异常页本地 OCR 的完整流程：

```powershell
python -X utf8 -m pip install -r requirements-ocr.txt
# 下载模型权重（若已存在则自动复用）
python -X utf8 -m aaoca_pipeline.local_ocr download-models --model-dir models/rapidocr
python -X utf8 -m aaoca_pipeline --config config/pipeline.ocr.json
```

OCR 处理阶段依赖本地 ONNX 权重，只处理 `ocr_recommended` 页面；空白页与正常文本层页面直接跳过。小批量核验 OCR 时可限制**每份 PDF**的识别页数：

```powershell
python -X utf8 -m aaoca_pipeline --config config/pipeline.sample.json --output data/derived/ocr_probe --ocr missing --ocr-model-dir models/rapidocr --ocr-max-pages 2
```

未处理页面会显式留在 QC 队列。`--ocr-max-pages 0` 表示处理全部推荐页面。正常运行是可重入的：原生提取及 OCR 结果分别按文件 SHA256、提取器/模型版本缓存；患者匹配、标准化、分段、日期、索引和 QC 每次重新生成。中断后重新运行同一命令，会复用已经完成的文档 OCR。

不要同时向同一个输出目录运行两个 pipeline。

## 路径配置

JSON 配置中的相对路径以**配置文件目录**为基准；CLI 覆盖路径以当前工作目录为基准。

代码不含实际原始数据路径——`pipeline.full.json` 和 `pipeline.ocr.json` 使用 `${AAOCA_PDF_ROOT}` 指向额外的 PDF 根目录，保留全部来源，但精确重复文件只对分段和时间线贡献一次。

Windows 和 Linux 都可以使用同一份配置。运行 `pipeline.full.json` 或 `pipeline.ocr.json` 前，先把环境变量设为实际 PDF 目录；`pipeline.sample.json` 则使用仓库内的 `data/sample_raw`，不依赖该变量：

```powershell
$env:AAOCA_PDF_ROOT = 'E:\Kenkyu-Shiryou\AAOCA Cases'
python -X utf8 -m aaoca_pipeline --config config/pipeline.full.json
```

```bash
export AAOCA_PDF_ROOT=/data/AAOCA\ Cases
python3 -X utf8 -m aaoca_pipeline --config config/pipeline.full.json
```

也可以不设置环境变量，直接用重复的 `--pdf-root` 覆盖配置中的 PDF 根目录。

可通过参数使用其他数据：

```powershell
python -X utf8 -m aaoca_pipeline --csv D:/research/cohort.csv --pdf-root D:/research/pdfs --pdf-root D:/research/extra --output D:/research/derived --cache D:/research/cache
```

CSV 默认字段为 `住院号、门诊号、姓名、病历、检验`；自定义字段可在配置的 `columns` 中设置 `inpatient_id/outpatient_id/name/expected_record/expected_lab`。

```powershell
python -X utf8 -m aaoca_pipeline --config config/pipeline.ocr.json --before 2024-01-01
```

此命令从已有运行中直接导出早于指定日期的记录；配合 `--patient-id` 可按患者筛选。导出结果自动携带 `clinical_stage` 与 `leakage_flags` 标记，便于后续时序建模筛选。

下游扩展可通过实现 `enrichment.LocalEnrichmentAdapter` 接口接入，支持返回候选字段、抽取版本及证据索引。

## 输出语义

完整 OCR 配置输出到 `data/derived/v0.1_full/`；纯文本层配置输出到 `data/derived/v0.1_text_layer/`。

| 文件                                      | 粒度及用途                                                                  |
| --------------------------------------- | ---------------------------------------------------------------------- |
| `patient_manifest.csv`                  | 保留 CSV 每一行；PDF/解析/section 数与可靠时间范围。`n_pdf` 计唯一内容，`n_source_pdf` 计所有来源。 |
| `document_index.csv`                    | 每个来源 PDF 一行，包括重复、未匹配和失败来源；重复行的 `duplicate_of` 指向 canonical 文档。         |
| `section_index.csv`                     | 每个 canonical 文档分段一行；类型、日期、日期来源、页/行/字符定位、质量标记和正文引用。                     |
| `patient_timeline.csv`                  | 患者匹配明确且日期有模板依据的 section，按患者、时间排序的时间线汇总。                                |
| `page_index.csv`                        | 每页原始字符数、处理状态、OCR 状态和置信度汇总。                                             |
| `date_mentions.csv`                     | 正文所有可识别日期与证据，分开存放；这些日期不会自动进入时间线。                                       |
| `extracted/<document_id>.json`          | 原生 PDF 原文、页边界、文字坐标、页级质量诊断，不被 OCR 覆盖。                                   |
| `normalized/<document_id>.json`         | raw、OCR、normalized 三种表示及映射；删除行与原因可查。                                   |
| `normalized/<document_id>.txt`          | 可阅读文本，带显式页面标记和换页符。                                                     |
| `sections/<document_id>.json`           | 完整分段正文、逐页 span、日期 evidence 与 mention。                                  |
| `qc/`                                   | 缺失患者/未匹配文件/身份问题、解析问题、重复来源、日期不确定、OCR 队列、行覆盖账本与 cohort 汇总。               |
| `source_inventory.csv`                  | 输入路径、SHA256、结束时不变性核验。                                                  |
| `run_metadata.json`、`logs/pipeline.log` | 配置、软件/模型版本、运行状态、计数与过程日志。                                               |
| `private/`                              | 本地患者链接表及原始身份标识符映射证据。                                                   |

`text_path` 相对于该次运行输出根目录；`text_reference` 是对应 JSON 的指针，例如 `/sections/3/text`。页码、行号是 1-based；`page_spans` 的字符 offset 是 normalized page text 的 0-based、右端不含区间。`normalized_line_map` 按 `normalized_text_source` 指向原生提取文本或 OCR 行。

`sections/.json` 的生成遵循如下步骤：

- **粗分类与细分角色**：`section_type` 为粗粒度文书类型（如 `procedure` 涵盖手术、介入操作与床旁超声）；`section_subtype` 为细分角色字段，不参与物理切分，无法确定时为空字符串。

- **非临床过滤**：网页导航、空白页、纯抬头片段归为 `nonclinical`；仅含该类段落的 PDF 标记为 `nonclinical`，不提供文书日期，不进入临床时间线。

- **检验报告切分**：以 `申请项目:`（含前置项目符号/图标）为核心边界；`section_title` 优先采用明确的申请项目名称，若标题缺失则在项目组合足够明确时恢复（如“血气分析”、`NT-proBNP`、`HS-CTNI`、`血浆肝素含量` 等）；`blood_gas`、`cardiac_biomarker` 等属于 `section_subtype`，不代替具体标题。

- **门诊文书识别**：通过就诊日期、科室、主诉、现病史及治疗计划的完整字段组合识别就诊；同一门诊段内再次出现新就诊组合时自动视为新分段，无需依赖独立大标题。新增边界若改变编号需重新分段。

| `section_type`   | 当前可判定的 `section_subtype` 示例                                                                                                                                                    |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `progress`       | `initial_progress`、`daily_progress`、`round`、`first_round`、`critical_round`、`transfer`、`case_discussion`、`postop_progress`、`procedure_imaging_progress`、`antibiotic_adjustment` |
| `administrative` | `treatment_procedure_consent`、`condition_communication`、`admission_notice`、`research_consent`、`leave_commitment`、`infection_control_commitment`                                |
| `procedure`      | `procedure`、`invasive_procedure`、`bedside_ultrasound`、`surgery_record`、`preoperative_discussion`                                                                               |
| `laboratory`     | `blood_gas`、`cardiac_biomarker`、`anticoagulation_monitoring`、`mixed_panel`                                                                                                     |

## 病例浏览器

`case_explorer/` 是独立的本地只读浏览模块，可按 snapshot 动态呈现数据总览、病例队列、患者时间线、章节原文和原 PDF 页。它会发现 `data/derived/` 下兼容的完整运行；未来新增的年份、类别、状态与记录会从数据中自动识别。

从仓库根目录启动：

```powershell
python -X utf8 -m case_explorer `
  --data-root data/derived `
  --run data/derived/v0.1_full `
  --sidecar-root data/derived `
  --port 8765
```

省略 `--run` 时自动选择最新兼容快照。默认展示伪名化患者 ID。

详细 schema、API、热重载和验证方式见 [`case_explorer/README.md`](case_explorer/README.md)。

## 数据质量与状态定义

- **解析状态**：
  
  - `ok`：原生文本层完整可用；
  - `partial`：部分页面需 OCR 补充提取；
  - `text_layer_unusable`：原生文字为矢量轮廓字形，完全依赖 OCR 提取；
  - `empty` / `failed`：空页面或解析异常。

- **身份冲突隔离**：多来源证据出现编号冲突或多患者混杂时，自动进入隔离审查队列。

- **全量样本保留**：未匹配或解析不确定（`unknown`）的记录均完整保留于 QC 队列，支持全量回溯与审查。

## 验证与重现

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 scripts/validate_outputs.py data/derived/v0.1_full --report data/validation/validation_v0.1_full.json
```

测试套件覆盖匹配冲突、文档去重、异常提取、打印日期过滤、跨页合并及时间线时序。长期说明见 `docs/`，关键阶段决策见 `SESSION_LOG.md`；`reports/` 只保存周报展示材料。

## Gold Set 人工核验

用 `scripts/gold_set.py` 从已完成且来源一致性检查通过的运行中固定抽样，浏览原始 PDF 页并校正文字、section、type/subtype 与事件日期，冻结人工答案，再对任意完整 parser 运行评分。样本以稳定的 PDF 内容与页码定位，所以重新分段后 section ID 的变化不会破坏比较。

当前已抽取 `data/gold_sets/aao_pdf_pages_v1/` 的 48 页固定样本（原生/OCR × 病历/检验各 12 页）。支持逐页核验、版本冻结，并对解析器输出进行多维度评分与版本比较。当前完成人工标注 0 页；在人工版本冻结前，不提供也不应声明真实解析准确率。

开始核验：

```powershell
python -X utf8 scripts/gold_set.py review --run data/derived/v0.1_full --gold-dir data/gold_sets/aao_pdf_pages_v1
python -X utf8 scripts/gold_set.py validate --gold-dir data/gold_sets/aao_pdf_pages_v1
```

操作步骤、日期角色和不确定标记见 [人工核验指南](docs/gold_set_review.md)；当前抽样规模、评分定义、冻结与版本比较命令见 [评估规范](docs/gold_set_evaluation.md)。

## AAOCA 相关性例外病例复核

流水线自动筛选资料缺失、证据稀疏、持续疑似、解剖冲突或解剖边界等例外病例供人工复核：

```powershell
python -X utf8 scripts/aaoca_exception_review.py build `
  --run data/derived/v0.1_full `
  --output data/review/aaoca_exception_review_v1

python -X utf8 scripts/aaoca_exception_review.py validate `
  --output data/review/aaoca_exception_review_v1
```

`data/review/aaoca_exception_review_v1/exception_cases.csv` 和 `exception_evidence.csv` 收录需人工复核的例外患者。人工编辑字段包括 `review_status`、`final_aaoca_judgment` 和 `reviewer_notes`。若先怀疑并做过针对性检查、后来排除 AAOCA，按定义仍标记为 `yes`。完整判定准则与 reason code 见 [AAOCA 例外病例复核说明](docs/aaoca_exception_review.md)。

在 `AAOCA_exception_review.xlsx`（黄色列为人工编辑区）中完成复核后，运行以下命令把人工作业字段同步回写至 CSV：

```powershell
python -X utf8 scripts/aaoca_exception_review.py import-workbook `
  --output data/review/aaoca_exception_review_v1

python -X utf8 scripts/aaoca_exception_review.py validate `
  --output data/review/aaoca_exception_review_v1 `
  --require-complete
```

## AAOCA 实际管理、其他治疗及复杂病例

规则区分 AAOCA 专属管理状态（`observed_management`：`surgery/intended_surgery/conservative/unknown`）、总体治疗状态（`overall_treatment_status`）及实际手术判断（`actual_aaoca_surgery`），支持精细记录共病介入及术中冠脉处置。

在完成基础运行并确认 relevance package 绑定同一 snapshot 后执行：

```powershell
python -X utf8 scripts/aaoca_management.py build --run data/derived/v0.1_full --aaoca-review data/review/aaoca_exception_review_v1 --output data/derived/aaoca_management_rules_v1
python -X utf8 scripts/aaoca_management.py validate --run data/derived/v0.1_full --aaoca-review data/review/aaoca_exception_review_v1 --output data/derived/aaoca_management_rules_v1
python -X utf8 scripts/aaoca_management_llm.py prepare --management data/derived/aaoca_management_rules_v1 --run data/derived/v0.1_full --aaoca-review data/review/aaoca_exception_review_v1 --output data/derived/aaoca_management_llm_requests_v1
python -X utf8 scripts/aaoca_management_llm.py validate-requests --requests data/derived/aaoca_management_llm_requests_v1 --management data/derived/aaoca_management_rules_v1 --run data/derived/v0.1_full
```

字段定义见 [Management 规范](docs/aaoca_management.md)，适配器接口与测试见 [LLM 中间件说明](docs/aaoca_management_llm.md)。
