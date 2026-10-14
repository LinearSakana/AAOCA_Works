# Gold Set 设计、评分与版本规则

## 1. 当前样本与进度

Gold Set 的抽样单位是“一份唯一 PDF 中的一个页面”。当前固定样本共 48 页，按文字来源与文书类型分为四层：

| 分层 | 页数 | 常规页 | 困难覆盖页 |
|---|---:|---:|---:|
| 原生文字病历 | 12 | 6 | 6 |
| 原生文字检验 | 12 | 6 | 6 |
| OCR 病历 | 12 | 6 | 6 |
| OCR 检验 | 12 | 6 | 6 |
| **合计** | **48** | **24** | **24** |

样本来自 42 份不同 PDF、41 位伪名化患者；每位患者和每份 PDF 最多贡献两页。困难页优先覆盖多 section、跨页、日期不确定、OCR 待复核、低置信文字、空文字、页外文字和少见 section type 等情况。

这是一组刻意覆盖失败模式的分层样本，不是从全部 13,485 页中得到的无偏随机样本。因此不能把样本中的错误比例直接解释为全队列错误率。

截至当前，48 页都已抽样，但没有完成并冻结的人工标注版本，所以还不能报告真实 parser 准确率。

## 2. 怎样抽样

抽样使用固定种子，保证同一正式快照上可以得到同一组页面。每层一半来自常规候选页，一半用于覆盖困难标签和少见文书类型。完全相同的 PDF 副本只计算一次。

```powershell
python -X utf8 scripts/gold_set.py sample `
  --run data/derived/v0.1_full `
  --gold-dir data/gold_sets/aao_pdf_pages_v1 `
  --pages-per-stratum 12 `
  --seed 20260925
```

已有 Gold Set 目录不会被抽样命令覆盖。原始 PDF、页面清单、人工标注和逐例错误都属于受限临床数据，应保存在受控存储中，不进入 Git 或公共报告。

## 3. 人工标注内容

每页需要人工确认：

- PDF 可见的整页文字；
- 页面上每个 section 的起止行；
- section 的 type 与 subtype；
- section 对应的事件日期、日期角色和其他容易混淆的日期；
- 错误可能带来的影响、歧义和复核备注。

程序预填内容只是待核对的预测，不是 Gold。人工无法可靠判断时，应使用 `uncertain` 或 `schema_gap`，不要猜测。

只有 `complete` 页面进入正式评分；`draft` 不评分，`unreviewable` 会排除并报告数量。文字无法可靠转录的页面不参与文字和结构指标；某一个字段无法判断时，只排除该字段，不影响同页其他可判定字段。

详细操作见 [Gold Set 人工核验指南](gold_set_review.md)。

## 4. 文字指标

### 字符错误率

对人工文字和预测文字做统一字符规范化，并在计算时忽略空白差异。所有页面的编辑距离相加后除以人工参考字符数，得到 `text_cer`。该值越低越好；严重插入错误时可能大于 1。

同时报告整页完全一致率，避免平均字符指标掩盖“少数页面完全错误”或“多数页面只有小差异”的不同情况。

### 数字 token 召回

单独检查数字、日期和类似数值的 token 是否被保留。它只能提示数字是否缺失，不能证明检验项目、结果、单位和参考范围已经正确配对。

## 5. 分段和分类指标

人工与预测文字先按顺序对齐。只有相似度达到基本阈值的行才视为可对应；对齐失败本身也是质量信号。

- `boundary_exact_f1`：section 起点必须落在完全相同的人工行；
- `boundary_tolerant_f1`：允许相差一行；
- section precision/recall：根据人工段与预测段覆盖行的重叠做一对一匹配；
- 平均 section overlap：反映已匹配段覆盖范围是否接近；
- type/subtype accuracy：只在成功匹配的 section 上计算。

分类准确率必须和 section recall 一起阅读。如果很多人工 section 根本没有匹配，剩余少数匹配段的高分类准确率不能解释为整体改进。

## 6. 日期指标

日期评分区分“日期值是否正确”和“日期角色是否正确”：

- 人工确认有日期时，要求预测到同一天；
- 人工确认没有事件日期时，要求预测为空；
- 另行报告已知日期中系统实际给出非不确定日期的比例；
- 日期值和角色同时正确时才计入更严格指标。

打印、历史、计划操作、采样、检验、文书和实际操作日期分别记录。只有人工明确标注某个其他日期、且预测恰好采用了它，才能归因为“把打印日期当事件日期”等具体错误，不能由程序猜原因。

当前只评分到日，不评分小时和分钟。

## 7. 分层报告与失败清单

总指标应同时按以下维度展开：

- 抽样时固定的原生/OCR × 病历/检验分层，用于公平比较不同版本；
- 被评估版本实际采用的文字来源，用于观察 OCR 路由变化；
- 人工 section type，用于发现某类文书特别薄弱。

逐例失败只使用匿名页面代号、页码、字段、错误模式、影响级别和预测值，不把临床原文写入公开报告。研究人员可在本地 review desk 中按匿名代号回到 PDF 核对。

## 8. 冻结和比较版本

人工完成后先冻结一个不可覆盖的修订版：

```powershell
python -X utf8 scripts/gold_set.py freeze `
  --gold-dir data/gold_sets/aao_pdf_pages_v1 `
  --revision r1
```

然后分别评估当前和新 parser，并比较同一 Gold Set 修订版：

```powershell
python -X utf8 scripts/gold_set.py evaluate `
  --run data/derived/v0.1_full `
  --gold-dir data/gold_sets/aao_pdf_pages_v1 `
  --revision r1 `
  --report data/gold_sets/aao_pdf_pages_v1/evaluations/v01_r1.json

python -X utf8 scripts/gold_set.py compare `
  --left data/gold_sets/aao_pdf_pages_v1/evaluations/v01_r1.json `
  --right data/gold_sets/aao_pdf_pages_v1/evaluations/next_r1.json `
  --report data/gold_sets/aao_pdf_pages_v1/evaluations/compare.json
```

比较只在样本、人工修订版、评分规则和页面集合一致时成立。正式更正人工标注时，应冻结为 `r2`，不要直接改写已冻结的 `r1`。

## 9. 解释限制

- 页面切片只能评分样本页内可见的跨页 section 部分；
- 严重 OCR 丢失时，人工行与预测行可能难以可靠对齐；
- type、subtype 和日期准确率只在成功匹配的 section 上定义；
- 人工填写的影响程度是潜在影响，不等于已证实的建模损害；
- 在真实人工修订版冻结前，所有软件检查都只能证明工具可运行，不能证明临床解析准确。
