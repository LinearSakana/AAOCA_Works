# AAOCA Management LLM 复核

当前推荐使用 `scripts/aaoca_management_llm.py` 的 v2 工具复核流程：先在本地筛选有实际语义问题的病例，准备中文时间线与少量原文窗口，再按需调用 DeepSeek。每批最多三例，结果保存为独立复核 sidecar；确定性规则包和原始病历不被回写。

## 哪些病例进入模型

分流依据是当前 management summary、证据和完整 section 集合。`needs_llm` 是待选候选，不表示全部会发送；一次 `prepare-agent` 只从中选一至三例，也可以用重复的 `--patient-id` 明确选人。

- `rules_sufficient`：规则已解决的手术和明确管理路径。常见 OCR、日期精度或一般复核标记不会单独触发模型。
- `insufficient_documentation`：当前来源没有可供进一步解释的处置线索。保留未知，补充资料比调用模型更有价值。
- `needs_llm`：冠脉操作的治疗目标未明、规则未解决的明确处置措辞、与规则“未完成”结论冲突的术后追记，或确有日期不确定的意向/观察冲突。

筛选同时检查普通病程、手术记录、门诊和有关治疗的同意/沟通文书。不会因它们被分为 administrative 就丢掉自填决策，也不会把影像模板的常规随访当作手术管理问题。`AAOCA/AOOCA` 异写只用于发现候选，不能直接建立手术事实。

## 模型看到什么

系统提示词约 1,400 字符，包含三种管理字段的边界、工具使用规则和小型 JSON 示例。病例输入单独提供：规则初判、按日期排列的关键 section 导航、最多八个去重原文窗口。短摘录优先保留手术、末次门诊、同意书自填决策及出院证据，并明确省略范围。显示结构放在引文外，原文字符不改写。

只有两个工具，作用域固定为当前患者：

| 工具 | 行为 |
|---|---|
| `get_section(section_id, offset=0)` | 返回标题、日期、页码和 section 全文；每页最多 10,000 字符，明确返回剩余内容的 offset。 |
| `search_sections(query, mode="keyword", offset=0)` | 遍历患者全部 sections；支持原文关键词或正则，返回命中 section 的标题、日期与上下文。每页最多十处；标记截断、超时和下一页。 |

搜索正则有长度、运行时间和匹配数量限制。搜索别名需要显式写入查询，工具不会悄悄改写模型的关键词。文书日期不能自动当作手术日期；模型也不能把导航标题当作完成证据。

## 运行

安装可选依赖：

```powershell
python -m pip install -e ".[llm]"
```

先看本地候选，再准备请求；这两步都不调用模型：

```powershell
python -X utf8 scripts/aaoca_management_llm.py triage `
  --management data/derived/aaoca_management_rules_v1 `
  --run data/derived/v0.1_full `
  --aaoca-review data/review/aaoca_exception_review_v1

python -X utf8 scripts/aaoca_management_llm.py prepare-agent `
  --management data/derived/aaoca_management_rules_v1 `
  --run data/derived/v0.1_full `
  --aaoca-review data/review/aaoca_exception_review_v1 `
  --output scratch/management_review_requests
```

准备包中的 `previews/*.md` 是实际病例输入，`prompt.md` 和 `tools.json` 是实际系统提示与工具定义，`routing_manifest.csv` 保留全部患者的路由理由。可在调用前直接审阅这些文件。

密钥只从当前进程的 `DEEPSEEK_API_KEY` 读取，不写进代码、请求包或报告。设置好环境变量后执行：

```powershell
python -X utf8 scripts/aaoca_management_llm.py run-agent `
  --requests scratch/management_review_requests `
  --output scratch/management_review_results

python -X utf8 scripts/aaoca_management_llm.py validate-agent `
  --requests scratch/management_review_requests `
  --output scratch/management_review_results
```

`validate-agent` 不带 `--output` 时只检查准备包。每次准备与执行均须使用新的输出目录，避免覆盖历史结果或意外重跑。

## 调用和检查边界

通过 `langchain_deepseek.ChatDeepSeek` 使用官方地址和 `model="deepseek-flash"`，关闭 thinking 以控制本轮试测开销。默认每例最多两次模型请求：可以首轮直接作答，也可以首轮并行调用最多四个工具、第二轮结束。每批最多六次 HTTP 请求；工具往返的模型请求同样计入次数。可调低 `--max-model-calls-per-case` 和 `--max-total-calls`，不能突破上述上限。API 出错时停止整批；不自动重试，也不通过额外模型请求修复输出。

不发送 `response_format`，不用 `with_structured_output`。先从回复末尾识别完整 JSON 对象，再交给 `JsonOutputParser`，随后进行本地字段与引用检查。截断 JSON 不会被自动补齐成成功结果。官方接口说明见 [DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/) 与 [ChatDeepSeek 文档](https://docs.langchain.com/oss/python/integrations/chat/deepseek)。

模型只提交 `section_id` 与短连续引文，宿主在模型实际读到的原文窗口中定位字符偏移。未展示内容、其他患者的 section 和改写引文不能通过校验；只有空白差异且能唯一定位时允许回到精确源文字，同时保存模型引文、源引文与匹配方式。字词和标点差异不做模糊修复。准备包绑定当前规则、全部 section 来源、提示词和工具；来源变化后必须重新准备，旧结果不能换编号复用。

结果包括 `responses.jsonl`、`transcripts/*.json`、`review_summary.csv` 和调用/token 回执。每例结果都保留 `requires_human_review=true`；检查通过只表示工程结构、来源与引用一致，不表示临床结论正确。运行时禁用 LangSmith tracing，患者文本及 AGY 原始报告保留在 Git 忽略目录。

`actual_aaoca_surgery=no` 在本流程中需要直接否定既往手术史的引文。某一次操作“未处理”由 `aaoca_handling=explicitly_not_treated` 表达，不能单独推断患者整个已记录时间线从未手术；“未见完成记录”也不能证明明确未处理。宿主设置最低限度的直接引文门槛，不能代替临床语义复核。历史“术后”追记、肺动脉移位是否针对 AAOCA，以及其他处置目标，仍需要人工核实。这些候选不能直接改写正式手术事件。

## 本次诊断试测（2026-10-17）

当前队列的旧 `ambiguous` 路由为 126 例；v2 分为 141 例规则已解决、34 例缺少进一步可解释资料、55 例语义复核候选。实际仅选三例，覆盖同意书自填决策、复杂同台操作目标归属和后续门诊术后异写。

首轮暴露出单次未处理被扩大为全局 `no`、原文换行造成引文失败的问题。收紧提示词和直接否定证据门槛，并加入唯一空白映射后，同三例第二轮均通过结构/引用/来源回放校验。模型找回了同意书保守决定，对冲突的术后追记保留未知；复杂肺动脉移位病例仍存在管理归属分歧，不能直接采用其预测。三例通过工程校验不表示三例临床正确。

两轮共 12 次模型 HTTP 请求，输入 67,931、输出 2,956 tokens；工具往返包含在内，无开发期真实病例调用和自动重试。临床内容与逐例分析保存在 Git 忽略的本地诊断目录，正式规则状态未改动。

## 历史 v1 接口

原 `prepare`、`validate-requests`、`validate-responses`、`reconcile`、`validate-hybrid` 命令及 provider-neutral Python 接口保留，用于历史包和已有测试。它们的 schema 与 v2 不互换；v2 复核结果不能直接送入旧 `reconcile`。历史试跑和本次小样本诊断均不构成 management Gold Set，不据此报告准确率。
