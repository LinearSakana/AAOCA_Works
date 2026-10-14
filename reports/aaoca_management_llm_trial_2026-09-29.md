# AAOCA management LLM 诊断试跑汇总（2026-09-29）

本报告于 2026-10-14 从还原的本地 `audit_summary.json`、`validation_result.json` 和旧 hybrid metadata 整理，只保留汇总与文件 hashes。原 trial 使用旧 request 和 management snapshot，不能用于当前规则包或当作模型准确率结果。旧测试目录按用户要求重置后，周报引用本报告。

| 指标 | 历史值 |
|---|---:|
| 准备的 requests | 124 |
| 收到的 responses | 11 |
| 原样通过当时 validator | 1 |
| 被当时 validator 拦截 | 10 |
| 校验错误总数 | 52 |
| 完整响应队列 | 否 |

原始输出状态为 unknown 4、conservative 4、surgery 3。错误可以在同一 response 中重叠，不能把错误次数当作患者数。

| 当时的错误代码 | 次数 |
|---|---:|
| `response_evidence_id_not_allowed` | 15 |
| `citation_passage_not_allowed` | 3 |
| `citation_quote_mismatch` | 15 |
| `new_actual_no_claim_requires_human_review` | 3 |
| `llm_disagreement_requires_human_review` | 4 |
| `new_conservative_claim_requires_human_review` | 1 |
| `response_management_actual_mismatch` | 1 |
| `response_surgery_without_completed_related_event` | 2 |
| `response_actual_no_without_conservative_state` | 1 |
| `new_surgery_claim_requires_human_review` | 2 |
| `response_evidence_ids_duplicate` | 1 |
| `response_event_evidence_id_not_allowed` | 4 |

还原的原始 response 文件 SHA256 与当时 audit summary 的记录一致：

`4a1eee5ffe0ece2635bf1d157c7791667a9e1547b3c1391e3dfd68fc73c7dbe1`

旧 hybrid 的 source hashes 为：

| 来源 | SHA256 |
|---|---|
| management summary | `9d2f3c749988ef8cd5f3712f1d7047732792e69db941afd27ea5c161f19d7d85` |
| request metadata | `b9bb45fc1865f49bdd424dddf004ed96c2a93f220006bc12a65aef4e96fc31b5` |
| requests | `0599d7a1238137fa0e5d4c20a48ef1107fc540c6bfaf7f6ce26608066a756bae` |
| 通过当时校验的 response 子集 | `f4fba8b180aa99731444742edd0b245cac951377087f4250224aa47c3eeddb68` |

2026-10-14 兼容检查确认前三项与当前源包不匹配，11 个旧 response ID 也不在当前 request 集合内。本报告保留诊断试跑的工程记录；当前交付见 [兼容修正验收](aaoca_management_compatibility_2026-10-14.md)。
