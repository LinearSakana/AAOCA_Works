# AAOCA management 与 LLM 包兼容修正验收（2026-10-14）

本批修正 management 的重复断言、混合操作方式及 LLM 请求/响应/sidecar 的来源绑定。Case explorer 不在本批范围。基础 PDF/OCR snapshot 与 relevance 包内容没有改动，management 和 request 包在原正式目录重建；LLM 为可重置的测试接口，没有调用真实模型。

## 修正及版本

- 规则升为 `aaoca_management_rules_v1.3`，management schema 为 `aaoca_management_v1.2`。重叠的 conservative 规则合并为一条断言，以 `matched_rule_ids` 保留全部来源；不同位置的同日决定独立保留。
- 操作方式按分开的术名组成部分判定。逐条上下文新增 `procedure_modes`；原标量在多种方式时记为 `mixed`，患者级方式列表保留所有方式。诊断性造影的入路不会污染另一个修补操作的方式。
- request identity 为 `aaoca_management_request_payload_v2`，绑定完整 payload、response schema、source hashes 及上下文限额。Provider/response schema 和 prompt v1.1 接口继续可用；旧 request 包须重新 prepare。
- 执行在 adapter 调用前验证 management/run；reconcile 必须核对 request 与传入 management 的 hashes。新增 `validate-hybrid`，重新检查来源、逐行结果、assessment 副本、完成状态及验证收据。
- LLM 输出路径与上游包或 response 输入重叠时会在写入前拒绝。

旧 response 不通过替换 ID 或 hash 迁移。还原包中的 11 个旧 ID 均被当前 validator 拒绝；旧 hybrid 的 management-summary/request-metadata/requests 三项 hashes 不匹配，且缺少新来源验证收据。三个旧 LLM response/hybrid/audit 实验目录已移出正式输出，9 月试跑汇总另存为 [历史报告](aaoca_management_llm_trial_2026-09-29.md)，周报引用该报告。递归及逐文件删除命令均被执行环境以 `blocked by policy` 拒绝，文件没有删除；原目录完整移至 `scratch/management_compatibility_20261014/obsolete_llm/`，由用户自行删除该文件夹。

## 正式输出

| 指标 | 当前值 |
|---|---:|
| 纳入患者 | 230 |
| 扫描 sections | 13,869 |
| management evidence assertions | 1,693 |
| AAOCA 手术事件 | 112 |
| QC 行 | 340 |
| LLM requests | 126 |
| 纳入请求的 evidence rows | 522 |
| 省略的 evidence rows | 0 |
| 原文 passages | 2,783 |
| passage 字符 | 2,830,080 |
| 额外 section 上下文截断的 requests | 124 |

AAOCA 状态为 111 surgery / 11 intended surgery / 31 conservative / 77 unknown；整体治疗为 158 / 9 / 17 / 46；actual AAOCA surgery 为 111 yes / 14 no / 105 unknown。全部患者状态及原有 112 个 AAOCA 事件的患者/日期/类型/精度/日期状态 tuple 与修正前一致。证据总行数由 1,695 净减至 1,693，三个断言保留多个命中规则。

基础 snapshot 仍为 232 患者、365 PDF paths、342 唯一内容、13,485 页、13,931 sections、10,341 timeline records。9 月 25 日首次运行摘要保留其历史数字，不用它作为当前 snapshot 的分母。

## 验收

- `tests/` 下 102 项测试全部通过，覆盖混合方式、断言去重、独立同日决定、旧 source、变更上下文限额、payload 篡改、hybrid 行/收据篡改、缺失 source、输入输出重叠和 CLI 退出码。
- 正式 management 与测试候选的五个 CSV 逐字节一致；正式 `requests.jsonl` 与候选逐字节一致。
- management 与 request source-bound validation 均为 0 errors / 0 warnings；基础 snapshot 与 relevance 校验通过。
- management 对上游 snapshot/relevance 的 source hashes 与重建前完全一致。当前包使用更新后的代码 hash；患者级材料与详细 hash/差异收据留在 Git-ignored 本地目录。
- 周报的全部来源链接继续指向存在的白名单文件；原始 response/hybrid/audit 目录不再是报告来源或当前结果。

真实患者未生成新的 LLM response 或 hybrid。合成 fake-client 测试证明接口行为，不构成临床准确率。复现命令及字段定义见 [management contract](../docs/aaoca_management.md) 与 [LLM contract](../docs/aaoca_management_llm.md)。
