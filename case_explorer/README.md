# AAOCA 病例浏览器

`case_explorer` 是独立于预处理 pipeline 的本地只读模块。它直接读取一个或多个已完成的 `data/derived` snapshot，在浏览器中提供数据总览、病例筛选、患者时间线、section 原文和原 PDF 页定位。它不修改 pipeline 输出，不复制临床文本到新的持久化数据库，也不需要第三方前端或 Python 依赖。

## 动态兼容约定

模块不会写死患者数、年份、section type/subtype、解析状态、文本来源或 management 标签。每次加载都会从 `run_metadata.json`、CSV 表头和真实记录动态发现这些维度；新记录、新类别和新增字段会自动进入 API 能力描述与聚合结果。

最低稳定关联契约只有：

- `patient_manifest.csv.patient_id`
- `document_index.csv.patient_id + document_id`
- `section_index.csv.patient_id + document_id + section_id + text_path`
- `run_metadata.json.status == "complete"`

`patient_timeline.csv` 缺失时会从有可靠日期的 section 动态派生时间线。新增字段会保留在记录的 `extra_fields` 中。若上述核心键被移除、ID 重复、section JSON 与索引断链，模块会明确报告 schema 兼容性错误，不会静默显示错误关联。

当 `--data-root` 下出现多个兼容 snapshot 时，API 会动态列出并支持运行期切换。活动 snapshot 的索引或 metadata 发生变化时，服务按间隔重新检查，在新数据完整可读后原子替换内存视图；若新文件暂时不完整，则保留上一份可用视图并暴露 `reload_error`。

可选 management sidecar 不是按目录名盲目接入：只有其 metadata 中的 `run_metadata`、`patient_manifest` 与 `section_index` SHA256 全部匹配当前 snapshot 时才会加载。

## 界面

- **数据总览**：当前规模、文书构成、文本来源、日期覆盖、管理方式与病例入口；年份、类别和计数均来自活动 snapshot。
- **病例浏览**：患者搜索、动态筛选与排序；单例页提供时间线、来源文档、全部章节、按需正文和原 PDF 页定位。
- **窄屏模式**：选择病例后进入专注阅读，并可一键返回病例列表；章节查看器独立滚动，关闭后回到原上下文。

界面不加载 CDN，不预取全部正文。概览和列表只使用索引字段，点击章节时才读取对应 JSON，点击 PDF 时才流式读取源文件。

## 启动

从工程根目录运行：

```powershell
python -X utf8 -m case_explorer `
  --data-root data/derived `
  --run data/derived/v0.1_full `
  --sidecar-root data/derived `
  --port 8765
```

打开 `http://127.0.0.1:8765/`。省略 `--run` 时自动选择 `--data-root` 下完成时间最新且满足核心契约的 snapshot，并可通过 API/UI 切换。所有服务只允许绑定 loopback 地址。

默认使用伪名化 `patient_id`。如确需本地显示和搜索姓名、住院号、门诊号，可显式加入：

```powershell
python -X utf8 -m case_explorer --run data/derived/v0.1_full --include-identifiers
```

此开关只控制 linkage 表的加载和显式身份标签；section 原文及原 PDF 本身仍可能含直接身份信息，因此整个应用始终属于受限临床数据界面，不能公开托管或把 URL 暴露到非本机网络。

## API

- `GET /api/health`：活动 snapshot 与热重载状态。
- `GET /api/bootstrap`：snapshot、动态 schema/capabilities、overview 聚合、可用 runs。
- `GET /api/patients`：支持搜索、section type、解析状态、management、复核状态、排序和分页。
- `GET /api/patients/{patient_id}`：患者 manifest、文档、全部 section 元数据、时间线及匹配 sidecar。
- `GET /api/sections/{section_id}`：按需读取 section JSON 原文与证据定位。
- `GET /api/documents/{document_id}/pdf`：只读流式返回原 PDF，支持浏览器 Range 请求。
- `POST /api/runs/select`：在已经发现并通过兼容性检查的 snapshot 间原子切换。

所有 API 响应均禁止缓存；静态资源无 CDN，服务设置同源 CSP，并拒绝跨源 POST。

## 验证

```powershell
python -X utf8 -m unittest discover -s case_explorer/tests -v
node --check case_explorer/static/app.js
python -X utf8 -m case_explorer --run data/derived/v0.1_full --port 8765
```

真实浏览器验收覆盖 1440×1000、768×900 与 390×844：总览、病例筛选、时间线、来源文档、章节搜索、正文查看器、PDF 链接、移动端返回路径、滚动/溢出和控制台错误。验收截图写入 Git 忽略的 `output/playwright/`。
