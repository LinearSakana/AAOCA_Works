# AAOCA management LLM middleware prototype

## 1. 当前状态

这一层已经可以准备、执行、验证和对账结构化 LLM 请求，但工程中**没有内置 endpoint、provider SDK、模型名、密钥或网络调用**。当前真实数据只执行了 `prepare` 与本地验证：

- `llm_invoked=false`；
- `network_processing=false`；
- `endpoint_configured=false`；
- 没有真实 response，也没有 LLM-derived patient label。

deterministic 包仍可独立使用。LLM 是可替换 sidecar，不改变 `data/derived/aaoca_management_rules_v1/` 的任何文件。

## 2. 四层 contract

### Request preparation

`prepare_llm_request_package` 从已验证的 management 包和 source section JSON 生成一位患者一个 JSON object：

- deterministic patient summary；
- 已去重手术事件；
- 规则证据行；
- 有原始 section 定位的 bounded passages；
- 明确的上下文纳入/省略收据；
- prompt/interface/schema 版本。

每个 passage 都有稳定 `passage_id`、`document_id`、`section_id`、页码、section JSON 路径与 pointer、`section_char_start/end` 和原文。请求包验证器会回到 source section，要求 `text == section_text[start:end]`。

### Provider adapter

`StructuredManagementLLMClient` 只有一个方法：

```python
def complete(request, response_schema) -> Mapping[str, object]:
    ...
```

以后接入经过审批的本地模型或 API 时，adapter 负责把：

- `request["instructions"]`；
- `request["case"]`；
- `response_schema`

映射到具体 SDK，再返回解析后的 JSON object。其余准备、引用验证和对账代码不需要更换。adapter 的 provider/model/run receipt 由 response 自己携带。

### Response validation

返回值必须符合 `response_schema.json`，包括：

- `observed_management` 与 `actual_aaoca_surgery`；
- confidence、简短 rationale、不确定点与是否需要人工复核；
- 被引用的 deterministic `evidence_id`；
- exact passage citations；
- 可多次出现的手术/意向/取消事件、AAOCA 关系、术名、类型和日期精度。

机械验证不信任模型输出。它会拒绝：

- 未在该 request 中出现的 evidence 或 passage ID；
- quote 与 passage 指定区间逐字不一致；
- patient/request ID 错配或重复 response；
- `surgery` 与 `actual_aaoca_surgery=yes` 不一致；
- surgery 缺少 completed + AAOCA-related event；
- intent/conservative 缺少对应支持；
- 非法日期/日期精度组合；
- 与 deterministic 结果不同却未设置 `requires_human_review=true` 的结果。

如果模型从 source passage 中发现规则漏掉的手术、意向或保守证据，可以作为新 candidate 返回，但必须要求人工复核。只有引用到已验证的 `completed` deterministic evidence，才被视为已有 completion basis；引用一句计划或诊断性造影不能绕过这一约束。

### Sidecar reconciliation

`reconcile_llm_responses` 输出新的 `hybrid_management_summary.csv` 和完整 `llm_assessments.jsonl`，不修改 deterministic CSV。

v1 策略刻意保守：

- agreement 记录为 corroboration；
- disagreement 记录 LLM candidate 与 `llm_deterministic_disagreement`；
- `recommended_management` 和 surgery status 在人工解决冲突前保持 deterministic 值；
- 没有 response 的患者保持原结果。

后续如果要增加“何种 agreement 可以提升 confidence”或“经过人工确认后采用 LLM candidate”的 policy，只需增加新的 reconciliation policy/version，不需要改 request/provider 接口。

## 3. 本地 prepare

默认命令：

```powershell
python -X utf8 scripts/aaoca_management_llm.py prepare `
  --management data/derived/aaoca_management_rules_v1 `
  --run data/derived/v0.1_full `
  --aaoca-review data/review/aaoca_exception_review_v1 `
  --output data/derived/aaoca_management_llm_requests_v1

python -X utf8 scripts/aaoca_management_llm.py validate-requests `
  --requests data/derived/aaoca_management_llm_requests_v1 `
  --management data/derived/aaoca_management_rules_v1 `
  --run data/derived/v0.1_full
```

默认 `selection_policy=ambiguous` 包括：所有非 `surgery` 状态，以及低置信/日期不完整/多事件的 surgery。其他可选值为：

| policy | 用途 |
|---|---|
| `unknown` | 只处理 deterministic unknown。 |
| `ambiguous` | 默认；unknown/intended/conservative 加上低置信或多事件 surgery。 |
| `review_required` | 使用 deterministic QC 的全部复核患者。 |
| `all` | 全部纳入的 AAOCA=yes 患者。 |

上下文限额均可在 CLI 改动：section 数、evidence 行数、每个 section 的 passage 字符数、每位患者 passage 总字符数。`request_manifest.csv` 明确记录 available/included/omitted 数量与 `context_truncated`，不会假装给模型看过未纳入的文书。

prompt 也不是写死的 provider 假设。可用 UTF-8 文件替换，并显式给版本：

```powershell
python -X utf8 scripts/aaoca_management_llm.py prepare `
  --management data/derived/aaoca_management_rules_v1 `
  --run data/derived/v0.1_full `
  --aaoca-review data/review/aaoca_exception_review_v1 `
  --output data/derived/aaoca_management_llm_requests_experiment `
  --instructions-file config/my_management_prompt.md `
  --prompt-version my_management_prompt_v2
```

request ID 同时绑定 prompt version、prompt SHA256、management metadata hash 和 selection policy，避免不同实验静默混用。

## 4. 接入已批准 adapter 后

下列代码展示接口形状，不代表已配置或批准任何 endpoint：

```python
from pathlib import Path
from aaoca_pipeline.management_llm import execute_llm_requests


class ApprovedClient:
    def complete(self, request, response_schema):
        # 在这里把 provider-neutral payload 映射到经过批准的 SDK。
        # 返回值必须是已解析、符合 response_schema 的 dict。
        raise NotImplementedError


result = execute_llm_requests(
    Path("data/derived/aaoca_management_llm_requests_v1"),
    Path("data/derived/aaoca_management_llm_responses_v1/responses.jsonl"),
    ApprovedClient(),
)
```

执行函数逐 request 调用 adapter、原子写入 JSONL，并立即运行 response validator。provider 可在 adapter 内实现批处理、重试、速率控制和鉴权；它们不进入临床抽取 contract。

外部生成 response 后也可单独执行：

```powershell
python -X utf8 scripts/aaoca_management_llm.py validate-responses `
  --requests data/derived/aaoca_management_llm_requests_v1 `
  --responses data/derived/aaoca_management_llm_responses_v1/responses.jsonl `
  --require-complete

python -X utf8 scripts/aaoca_management_llm.py reconcile `
  --management data/derived/aaoca_management_rules_v1 `
  --requests data/derived/aaoca_management_llm_requests_v1 `
  --responses data/derived/aaoca_management_llm_responses_v1/responses.jsonl `
  --output data/derived/aaoca_management_hybrid_v1
```

## 5. 当前真实 request package

默认 prepare 从 230 位 deterministic 患者中选出 124 位：5 surgery、11 intended surgery、20 conservative、88 unknown。436 条可用 deterministic evidence 全部进入请求，没有 evidence row 因限额省略。上下文形成 2,734 个 passages，共 2,778,830 个字符。

122/124 个请求的 `context_truncated=true`，原因主要是患者可用 section 多于默认 24 个；这不表示已有 436 条 management evidence 被删除。每个请求仍保留实际 included/omitted receipt。最小/中位/最大 passage 字符量约为 7,422 / 21,820 / 39,750，均低于 80,000 的 patient 上限。

此目录包含临床原文，只能本地保存。当前没有 response 文件，也没有运行 reconciliation 得到真实 hybrid label；测试中的 response 只来自合成病例和 fake client。

## 6. 仍需用户决定的内容

接入前仍应显式决定：

- 使用本地还是其他经过批准的 endpoint，以及隐私/网络边界；
- 具体模型、sampling、重试和成本策略；
- prompt 版本和需要纳入的 section/context 限额；
- 选择 `unknown`、`ambiguous`、`review_required` 还是其他路由；
- 对 agreement、disagreement 和新发现 completion evidence 的人工确认流程；
- 是否建立并冻结 management gold set，用于报告真实抽取准确率。

在这些决定完成前，prototype 只提供可执行、可审计的接口，不对真实患者产生 LLM 结论。
