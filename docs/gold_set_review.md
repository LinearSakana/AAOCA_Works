# Gold Set 人工核验指南

这份指南面向核验原始临床 PDF 的同学。Gold Set 是**人工对照 PDF 得出的答案**。程序在页面里预填的文字、section 和日期都只是待检查的预测，不能直接当作正确答案。整个流程在本机运行；病例内容、标注和逐例错误保存在 Git 忽略的 `data/` 下。

## 1. 样本与准备

当前固定样本在 `data/gold_sets/aao_pdf_pages_v1/`，共 48 个 PDF 页，来自 42 份不同 PDF。每页有一个不随 parser section 编号改变的代号 `pg_...`。一个 PDF 页可能有多个 section，也可能没有可见临床文字。请核验**整页**，包括页首、页尾以及一个页面上的多个检验项目。

在工程目录运行：

```powershell
python -X utf8 scripts/gold_set.py review --run data/derived/v0.1_full --gold-dir data/gold_sets/aao_pdf_pages_v1
```

终端会打印一个只供本机访问的网址。用本机浏览器打开。左侧是从原始 PDF 渲染的样本页；“PDF 前一页/后一页”可临时看同一 PDF 的上下文，“回样本页”返回要标注的页。页面上方给出 PDF 文件路径和 SHA256，便于必要时用本机 PDF 阅读器打开原件。右侧依次是**样本页**的原生提取、OCR、normalized 文字、parser 预测和人工编辑区；切换左侧上下文页不会改变标注目标。顶栏“上一页/下一页”才切换 Gold Set 样本。草稿可以反复保存。关闭终端或按 `Ctrl+C` 停止服务，已保存内容仍在 `annotations/`。

评估报告的 `failures` 含有 `unit_id`（例如 `pg_...`）。将它粘贴到顶栏“跳到样本”可直接回看错误，也可输入 1–48 的样本序号；如果 review 服务正在运行，可以在它打印的网址后加 `&unit=pg_...` 直接打开该页。不要把含访问令牌的网址分享给他人。

如果原始 PDF 路径失效、SHA256 改变，review 工具会报错；先恢复原件，不要用同名替代文件继续标注。

## 2. 每页怎样核验

1. **对照 PDF 看文字。** “人工校正后的整页文字”起初复制 parser 的 normalized 结果。按 PDF 可见顺序修正漏字、错字、数字、单位、阴性/阳性、否定、日期及被误删或误加的行。保留临床标题和表内有意义的文字。浏览器导航、打印 URL、纯页码可略去；不要补写 PDF 上没有的医学信息。
2. **检查分段。** 下方每个 section 用人工文字的起始/结束行号表示。先看带行号的预览，再修改行号，必要时增加/删除 section。一页上所有**非空行恰好归入一个 section**；空行可以夹在区间里。跨页 section 在本页只标本页可见部分。若 OCR 把一行误分成两行，先改文字，再核对所有区间。
3. **核对 type 与 subtype。** 页面预填 parser 的结果。请看 PDF 上这段材料实际是什么，再选择 type。Subtype 用当前工程中的细分名称；如果明确不存在进一步细分，可以留空。当前 type 包含 `admission`、`progress`、`discharge`、`procedure`、`consultation`、`outpatient`、`laboratory`、`administrative`、`nonclinical`、`unknown`。`procedure` 包括手术/操作相关文书，不代表已经完成手术。无法可靠判断时选“无法判断”；现有类别无法表达时选“schema 无法表达”，并在备注中说明。
4. **核对 event date。** 这是**本 section 所属临床事件/文书的日期**，不是 PDF 打印时间。明确有值时选“已确定”，填写 `YYYY-MM-DD` 并选语义：`document`（文书或就诊日期）、`test`（检验时间）、`specimen`（采样时间）、`performed_procedure`（实际操作日期）或 `other`。明确没有 event date 才选“确认没有 event date”。看不清或几种日期都可能成立时选“无法判断”；schema 表达不了则选“schema 无法表达”。不要从相邻 section 借日期。
5. **记录易混淆的其他日期。** 如果一段同时出现打印、历史、计划操作、采样等日期，在“其他日期”中逐行填写 `YYYY-MM-DD | role | PDF 上的证据`。可用角色有 `print`、`historical`、`planned_procedure`、`specimen`、`test`、`document`、`performed_procedure`、`other`。这使 evaluator 能指出“把打印日期误当事件日期”等具体错误。
6. **记录影响和歧义。** 如果这一处被解析错，选择对后续临床变量抽取可能造成的影响：低、中、高或无法判断。严重 OCR 数字错误、手术是否实际完成、术前/术后混淆通常值得写具体备注；影响程度由核验者判断，不由程序自动推定。整页无法可靠转录时将文字状态改为“无法可靠转录”，并写原因。原始 PDF 本身无法阅读时可“标记无法核验”，必须填写原因。
7. **完成。** 填写核验人姓名或代号，勾选已对照 PDF 核查的确认框，再点“完成本页”。未完成时点“保存草稿”。完成页仍可回头修改；正式冻结后会复制成一个独立版本。

例子：检验 section 同时出现 `检验时间 2024-01-02` 与 `打印时间 2024-01-03`。如果前者是所需事件日期，就把 event date 设为 `2024-01-02`、role 设为 `test`，在“其他日期”填 `2024-01-03 | print | 打印时间...`。如果不能从 PDF 判断“检验时间”究竟是采样还是结果时间，就选“无法判断”并说明原因，不要猜。

## 3. 检查和冻结

随时检查进度与格式：

```powershell
python -X utf8 scripts/gold_set.py validate --gold-dir data/gold_sets/aao_pdf_pages_v1
```

所有 48 页都完成或明确标记无法核验后，创建一个不可覆盖的修订版：

```powershell
python -X utf8 scripts/gold_set.py freeze --gold-dir data/gold_sets/aao_pdf_pages_v1 --revision r1
```

冻结会计算所有人工标注的摘要，并把它们复制到 `revisions/r1/`。后续继续改工作区的 `annotations/` 不会修改 `r1`。要正式更正错误，请重新核验、冻结成 `r2`，并且只拿同一个 revision 的评估报告互相比。不要手工修改已冻结文件；评估器会检测摘要不一致。

## 4. 数据保护和核验边界

原始 PDF、逐页文字、标注和逐例错误都留在本地 `data/`；不要把它们贴进 Git、issue、公共报告或在线工具。工程报告只可使用聚合数与不含身份信息的样本代号。自动验证会检查文件结构、覆盖和摘要，**不会替代人工判断 PDF 的临床含义**。如果同一页有争议，应在备注里写清楚并请第二位核验者复核；无法达成可靠判断的字段保留 uncertain/schema_gap。
