# AAOCA 相关性例外病例复核

## 1. 复核问题

这里判断的不是患者最终是否确诊 AAOCA，而是：

> AAOCA 或相应冠状动脉异常是否曾在患者诊疗过程中成为实际被考虑、怀疑、检查、讨论、鉴别或排除的方向。

因此，先怀疑并做了针对性检查、后来确认冠脉起源正常的患者仍应标记为 `yes`。普通检查报告偶然写到正常冠脉，或手术知情同意模板列出冠脉造影并发症，并不足以单独构成 `yes`。

## 2. 为什么只复核例外

医院已经筛查过该队列。逐患者扫描显示，绝大多数患者在诊断、冠脉来源、CTA/造影、会诊或手术记录中都有多处明确证据。让人工重复审阅全部患者会增加工作量，也会稀释真正需要判断的病例。

当前流程先在患者层聚合带来源定位的证据，然后只把资料不足、证据稀疏、始终为疑似、解剖描述冲突或研究范围边界不清的患者送入人工队列。普通高证据病例不会出现在工作簿中。

## 3. 当前进度

基于当前 232 位患者的正式快照：

| 项目 | 数量 |
|---|---:|
| 自动判为相关 | 230 |
| 自动判为不相关 | 0 |
| 自动无法判断 | 2 |
| 进入例外人工队列 | 62 |
| 未进入人工交付物的普通病例 | 170 |
| 例外证据行 | 654 |
| 已完成人工复核 | 0 |

62 位例外病例包含 60 位暂列自动 `yes` 和 2 位自动 `uncertain`；其余 170 位是没有进入人工交付物的普通高证据病例。因此，当前下游 Management 纳入的 230 位患者由 170 位普通病例和 60 位尚待人工复核的例外病例组成，排除的正是 2 位 `uncertain`。如果后续人工复核推翻部分自动判断，Management 分母与汇总结果需要随之重建。

两个自动无法判断病例分别是：一位在当前范围内没有 PDF；另一位只有空病历 PDF 和检验包中的非临床诊断页头，缺少能说明诊疗过程的临床文书。当前 230 个 `yes` 是证据分流结果，不是临床金标准。

## 4. 哪些情况进入例外队列

| 类型 | 需要人工确认的情况 |
|---|---|
| 来源不足 | 没有 PDF、没有可用 section，或相关表述只存在于网页页眉/检验包。 |
| 证据过少 | 只有一个弱、疑似、非临床或未经核验的 OCR 证据。 |
| 始终疑似 | 所有证据都是“可能、待排、不能除外、显示不清”等状态。若它确实触发了检查或讨论，最终仍可能是 `yes`。 |
| 解剖冲突 | 同一冠脉在不同文书中出现不一致来源，或同时有明确正常与异常描述。 |
| 范围边界 | 肺动脉来源、单支冠脉、冠脉起自另一冠脉、复杂先心病中的冠脉解剖、高位开口等是否属于本项目范围。 |
| 标签过于笼统 | 只有“冠脉异常”等名称，没有可解析的解剖、针对性检查或处置。 |
| 充分资料中无实质证据 | 临床文书覆盖较完整，但没有发现 AAOCA 真正进入诊疗过程。 |

规则不会因为“后来排除”而自动给 `no`。明确排除本身通常说明该方向曾被实际考虑。

## 5. 人工复核文件

本地目录 `data/review/aaoca_exception_review_v1/` 包含：

- `exception_cases.csv`：每位例外患者一行，包含自动判断、例外原因、证据摘要和人工字段；
- `exception_evidence.csv`：每位例外患者少量且语义不同的证据；
- `AAOCA_exception_review.xlsx`：面向人工的工作簿，黄色列为可编辑区；
- `README.md`：随本地工作包生成的简要说明。

工作簿只包含 62 位例外患者，不包含其余 170 位普通病例。直接标识只存在于受限的本地 review 目录，不能提交或外传。

人工只填写三列：

- `review_status`：`not_reviewed`、`in_review` 或 `reviewed`；
- `final_aaoca_judgment`：`yes`、`no` 或 `uncertain`；
- `reviewer_notes`：支持结论的简短说明。

如果填写了最终标签，状态必须是 `reviewed`。不要改动自动判断、原因、证据和定位列。

## 6. 运行方式

生成并检查例外包：

```powershell
python -X utf8 scripts/aaoca_exception_review.py build `
  --run data/derived/v0.1_full `
  --output data/review/aaoca_exception_review_v1

python -X utf8 scripts/aaoca_exception_review.py validate `
  --output data/review/aaoca_exception_review_v1
```

若在工作簿中完成复核，先把三个人工字段回写到 CSV，再要求全部完成：

```powershell
python -X utf8 scripts/aaoca_exception_review.py import-workbook `
  --output data/review/aaoca_exception_review_v1

python -X utf8 scripts/aaoca_exception_review.py validate `
  --output data/review/aaoca_exception_review_v1 `
  --require-complete
```

导入会要求工作簿与 CSV 的患者集合完全一致，并且只复制三个人工列。自动阶段和证据表不会被 Excel 覆盖。

## 7. 解释边界

自动结果只用于复核分流。规则能证明某些可追溯文字被识别并按一致逻辑聚合，不能证明 OCR、文书归属或冠脉解剖一定正确。对解剖冲突、肺动脉来源、复杂先心病和仅 OCR 证据，应回看证据指向的 section，必要时打开原 PDF 页面。

完成复核后，下游治疗状态需要按 [AAOCA 实际治疗与手术整理](aaoca_management.md) 重新构建。返回 [项目文档导航](README.md)。
