# AAOCA 管理方式待明确病例的后续规则化分类

## 目标

该流程只处理已验证 Management 包中 `observed_management=unknown` 的病例。原始病历、原有 Management 标签和证据表均保持不变。新输出把以下三个问题分开：

1. 是否合并会主导治疗决策、使 AAOCA 处置无法独立归因的其他复杂心脏疾病。
2. 医疗团队是否明确认为存在或不存在 AAOCA 手术指征。
3. 现有文书实际记录了什么处置结局。

因此，“医生建议手术、家属拒绝或延期、最终未手术”会保留为 `surgery_indication=yes` 与 `observed_aaoca_treatment_outcome=no_aaoca_surgery_documented`，不会被压成单一的保守治疗。

## 运行

```powershell
python -X utf8 scripts/aaoca_management_followup.py build `
  --run data/derived/v0.1_full `
  --management data/derived/aaoca_management_rules_v1 `
  --output data/derived/aaoca_management_followup_v1

python -X utf8 scripts/aaoca_management_followup.py validate `
  --run data/derived/v0.1_full `
  --management data/derived/aaoca_management_rules_v1 `
  --output data/derived/aaoca_management_followup_v1
```

如需在其他数据集增加病种或替换措辞，可用 `--rules rules.json` 传入 JSON。配置会与内置默认值递归合并；`complex_conditions` 列表可整体替换，`phrases` 中的单个规则组可单独替换。每次运行会把完整生效配置写入 `effective_rules.json`，便于复现。

## 输出字段

- `complex_heart_disease_status`: `confirmed`、`suspected` 或 `none`。只有诊断语境中的明确病名可以成为 `confirmed`；“待查”“疑似”“可能”“鉴别诊断”“可排除”均不会自动排除。
- `study_disposition`: 确诊复杂合并病暂时排除，疑似病例进入复核，其余保留在管理方式重分类队列。
- `surgery_indication`: `yes`、`no` 或 `unclear`，描述医生判断，不描述是否执行。
- `observed_aaoca_treatment_outcome`: 已完成 AAOCA 手术、保守随访、文书明确未实施，或未知。
- `decision_path`: 便于研究分层的互斥路径。
- `primary_*` 和 `supporting_evidence_ids`: 可回到原始 section、页码和精确字符范围。
- `review_required` / `review_reasons`: 仍需医生复核、查询后续住院或手术资料的原因。

`no_aaoca_surgery_documented` 只表示现有文书所覆盖的就诊或住院终局，不等同于患者一生从未接受 AAOCA 手术。

## 证据优先级

流程首先区分实际手术记录、出院结论、科内或病例讨论、会诊/查房、入院计划及同意书。时间可比较时，后出的明确决定覆盖较早计划；实际实施证据高于计划、知情同意和“拟行手术”。若日期无法比较或手术建议可能针对其他合并病变，保留冲突并进入复核，不强行决定。

同一次就诊中，`待检查/待内外科讨论/结果回报后再评估` 比模板式的“出院随访心内科”更具体，因此保持为 `continued_evaluation_or_pending`。跨就诊时，日期更晚的明确科内结论、手术记录、出院结论或 AAOCA 专病门诊记录可以覆盖较早计划。放射科报告中的“结合 ECHO，建议随访”、非心脏专科随访和通用知情同意书不构成 AAOCA 终局。

## 互斥路径与保留信息

分类按以下顺序执行，且始终保留三个独立轴：

1. 明确合并复杂心脏疾病时，进入 `combined_other_complex_heart_disease`，研究处置为暂时排除；不再把危重瓣膜病、复杂先心病或心肌病的拒签误写成 AAOCA 手术拒绝。
2. 有实际 AAOCA 手术完成证据时记录完成；“拟行”“同意”“具备诊断性造影指征”均不算实施。
3. 明确写明 AAOCA 无手术指征时，进入 `clinician_no_indication_conservative`。
4. 明确存在 AAOCA 手术指征，并有家属拒绝、延期、自动出院或其他未实施原因时，保留 `surgery_indication=yes`，结局记录为 `no_aaoca_surgery_documented`。
5. 未写明指征、但有 AAOCA 专病随访或明确缺血评估后的门诊观察时，进入 `clinician_conservative_other`；该类仍保留“指征不明确”的复核提示。
6. 检查/讨论未完成、仅转诊、自动出院、完成其他心脏手术但 AAOCA 处理不明、或仅完成诊断性检查时，分别进入可过滤的未决路径，不与完全缺少终局证据混在一起。

复杂病规则目前覆盖肥厚型/扩张型/限制型及致心律失常性右室心肌病、长 QT 综合征、右室双出口、器质性右室流出道梗阻/双腔右室、大动脉转位、法洛四联症、肺动脉闭锁、永存动脉干、单心室生理、完全性肺静脉异位引流、左心发育不良、重度肺动脉高压/艾森曼格生理、危重或重度主动脉瓣狭窄，以及主动脉缩窄/主动脉弓中断。疑似、待查、鉴别诊断及局部否定（例如“无主动脉缩窄”“流出道未见狭窄”）不会触发自动排除。

## 文献边界

规则词表参考了 [2025 ACC/AHA/HRS/ISACHD/SCAI 成人先天性心脏病指南](https://www.ahajournals.org/doi/abs/10.1161/CIR.0000000000001402)、[2017 AATS 异常主动脉起源冠状动脉专家共识](https://www.jtcvs.org/article/S0022522317301344/pdf)、[2018 AHA/ACC 成人先天性心脏病指南](https://www.ahajournals.org/doi/10.1161/CIR.0000000000000603)和 [2020 ESC 成人先天性心脏病指南](https://www.escardio.org/guidelines/clinical-practice-guidelines/all-esc-practice-guidelines/adult-congenital-heart-disease/)。这些文献只用于界定“解剖、缺血/功能评估、专家讨论和纵向随访均可能影响处置”的证据边界；脚本不根据解剖类型、症状或检查结果自行推断手术指征，只抽取病历中医生已经明确记录的判断。

## 验收不变量

- 输出患者必须与输入 Management 包的 `observed_management=unknown` 集合完全一致，且每例一行。
- 只有 `confirmed` 复杂合并病可进入暂时排除层。
- 计划、同意书和诊断性导管/造影不得生成“已完成 AAOCA 手术”。
- `clinician_no_indication_conservative` 必须同时满足 `surgery_indication=no` 与保守随访结局。
- “有指征但未实施”的路径必须保留 `surgery_indication=yes`，且结局不是已完成手术。
- 每个主证据 ID 必须存在，页码/section 可解析，证据文本必须与原文字符范围逐字一致。
- 输入 CSV、section 索引和运行元数据哈希写入 `run_metadata.json`；验证时重新比对。
