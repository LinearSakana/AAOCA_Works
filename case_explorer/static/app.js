const TYPE_LABELS = {
  admission: "入院记录",
  progress: "病程记录",
  consultation: "会诊记录",
  laboratory: "检验报告",
  procedure: "手术与操作",
  surgery_related: "手术相关",
  administrative: "管理与知情",
  discharge: "出院记录",
  outpatient: "门诊记录",
  follow_up: "随访记录",
  nonclinical: "非临床内容",
  surgery_record: "手术记录",
  outpatient_record: "门诊记录",
  discharge_summary: "出院小结",
  unknown: "未分类",
};

const SOURCE_LABELS = {
  pdf_text_layer: "原生文本层",
  native_text: "原生文本层",
  local_ocr: "本地 OCR",
  mixed: "混合来源",
  unknown: "来源未知",
};

const STATUS_LABELS = {
  ok: "原生可用",
  partial: "部分 / OCR",
  uncertain: "需复核",
  no_pdf_in_scope: "无 PDF",
  empty: "空文档",
  failed: "失败",
  unknown: "未知",
  surgery: "已实施手术",
  intended_surgery: "手术意向",
  conservative: "保守管理",
  routine: "常规",
  high: "高",
  medium: "中",
  low: "低",
  yes: "是",
  no: "否",
  none_documented: "未记录治疗性操作",
  completed_other_cardiac_procedure: "已实施其他心脏治疗",
  diagnostic_only_documented: "仅记录诊断性操作",
  completed: "已实施",
  intended: "计划 / 意向",
  diagnostic_completed: "诊断性操作",
  cancelled: "取消 / 拒绝",
  unrelated_completed: "其他手术",
  context_only: "背景信息",
  aaoca_surgery: "AAOCA 手术",
  diagnostic_procedure: "诊断性操作",
  surgical_intent: "手术意向",
  management_decision: "管理决策",
  other_surgery: "其他手术",
  operative_context: "术中背景",
  management_context: "管理背景",
  definite: "明确相关",
  probable: "可能相关",
  related_nontherapeutic: "相关但非治疗",
  unrelated_or_unresolved: "无关或未定",
  unresolved: "未定",
};

const DETAIL_LABELS = {
  not_applicable: "不适用",
  not_documented: "未记录",
  concomitant_aaoca_repair: "同期处理 AAOCA",
  multiple_contexts: "多种处置情境",
  explicitly_not_treated: "明确未处理 AAOCA",
  anatomy_documented_intervention_unclear: "记录解剖，干预未明",
  assessed_no_intervention: "评估后未干预",
  coronary_manipulated_target_unclear: "冠脉操作，目标未明",
  cardiac_surgery: "心脏外科",
  cardiac_catheter_intervention: "心导管介入",
  noncardiac_surgery: "非心脏手术",
  unclassified: "未分类",
  unclassified_operation: "未分类操作",
  septal_defect_repair: "间隔缺损修补",
  valve_procedure: "瓣膜操作",
  ductus_or_aortic_arch_procedure: "动脉导管 / 主动脉弓",
  outflow_or_pulmonary_artery_procedure: "流出道 / 肺动脉",
  electrophysiology_procedure: "电生理",
  pericardial_procedure: "心包操作",
  other_vascular_procedure: "其他血管操作",
  complex_congenital_repair: "复杂先心病手术",
  pulmonary_venous_repair: "肺静脉操作",
  noncardiac_procedure: "非心脏操作",
  other_coronary_procedure: "其他冠脉操作",
  vascular_stent_procedure: "血管支架",
  coronary_repair: "冠脉修复",
  coronary_unroofing: "去顶术",
  coronary_origin_correction: "开口 / 起源矫治",
  adjunct_pulmonary_artery_plasty: "同期肺动脉成形",
  coronary_ostial_reconstruction: "冠脉开口重建",
  coronary_reconstruction: "冠脉重建",
  coronary_reimplantation: "冠脉再植",
  coronary_anomaly_repair_unspecified: "冠脉异常修复（未分型）",
  completed_aaoca_surgery_evidence: "AAOCA 手术完成证据",
  completed_non_aaoca_surgery_evidence: "其他手术完成证据",
  explicit_nonoperative_management: "明确非手术管理",
  insufficient_management_evidence: "管理证据不足",
  surgical_intent_without_completion: "手术意向，完成未证实",
  completed_other_cardiac_procedure: "已实施其他心脏治疗",
  diagnostic_without_therapeutic: "诊断性操作，无治疗性操作",
  aaoca_handling_not_documented_during_other_procedure: "其他操作中未记录 AAOCA 处理",
  aaoca_management_unresolved_after_other_cardiac_procedure: "其他心脏操作后 AAOCA 处置未明",
  aaoca_not_treated_during_other_procedure: "其他操作中未处理 AAOCA",
  aaoca_surgery_date_uncertain: "AAOCA 手术日期待核",
  aaoca_surgical_intent_completion_unproven: "手术意向，完成未证实",
  completed_noncardiac_procedure: "已实施非心脏手术",
  completed_procedure_type_unclassified: "已实施操作，类型未分",
  complex_procedure_aaoca_relation_uncertain: "复杂操作与 AAOCA 关系未明",
  coronary_anatomy_seen_intervention_unresolved: "记录冠脉解剖，干预未明",
  diagnostic_procedure_without_therapeutic_operation: "诊断性操作，无治疗性操作",
  insufficient_management_documentation: "管理文书不足",
  management_decision_pending_documented: "记录待定管理决策",
  mixed_management_stages: "多阶段管理证据",
  multiple_aaoca_surgery_events: "多个 AAOCA 手术事件",
  nonoperation_reported_in_imaging_only: "仅影像记录未手术",
  surgery_cancelled_declined_or_deferred: "手术取消、拒绝或延期",
  complex_management_context: "处置情境复杂",
  no_completed_intent_or_conservative: "未见完成、意向或保守管理证据",
  ocr_completion_or_date: "完成状态或日期受 OCR 影响",
  cancelled_or_declined_surgery_documented: "记录手术取消或拒绝",
  completion_not_proven: "完成状态未证实",
  followup_or_observation_only: "仅随访或观察",
  mixed_intent_and_conservative_evidence: "同时存在手术意向与保守证据",
  no_completed_intent_or_conservative_evidence: "未见完成、意向或保守证据",
  ocr_derived_completion_or_date_evidence: "完成状态或日期来自 OCR",
  surgery_date_unknown_or_conflicting: "手术日期未知或冲突",
  unrelated_completed_operation_not_aaoca_management: "其他已完成手术不代表 AAOCA 处置",
};

const TYPE_COLORS = {
  progress: "#3f739f",
  laboratory: "#2d8a80",
  administrative: "#8a7aa7",
  procedure: "#bd6f2a",
  surgery_related: "#bd6f2a",
  consultation: "#547c6f",
  nonclinical: "#9aa5b2",
  admission: "#4b68a1",
  discharge: "#a65f67",
  outpatient: "#62875a",
  unknown: "#8b96a4",
};

const MANAGEMENT_COLORS = {
  surgery: "#248176",
  intended_surgery: "#c07a25",
  conservative: "#3c70a7",
  unknown: "#9aa4b1",
};

const PRIORITY_COLORS = {
  high: "#b45555",
  medium: "#c07a25",
  routine: "#4d7f75",
  unknown: "#9aa4b1",
};

const state = {
  bootstrap: null,
  activeView: "overview",
  filters: {
    query: "",
    section_type: "",
    parse_status: "",
    management: "",
    overall_treatment: "",
    other_procedure_status: "",
    review_priority: "",
    review_required: "",
    sort: "latest_desc",
  },
  patientRows: [],
  patientTotal: 0,
  patientOffset: 0,
  patientLimit: 40,
  selectedPatientId: "",
  patient: null,
  caseTab: "timeline",
  timelineType: "",
  sectionQuery: "",
  documentFilter: "",
  selectedSectionId: "",
  section: null,
  patientRequest: 0,
  sectionRequest: 0,
};

const dom = {};
let searchTimer = null;
let toastTimer = null;

function cacheDom() {
  [
    "app", "run-select", "run-status", "reload-banner", "overview-view", "cases-view",
    "overview-subtitle", "metric-grid", "section-composition", "section-composition-total",
    "source-donut", "source-legend", "quality-facts", "timeline-chart", "management-panel",
    "management-chart", "overall-treatment-chart", "other-procedure-chart", "review-priority-chart",
    "management-total", "cohort-preview-list",
    "open-cohort", "view-all-cases", "cohort-count", "patient-search", "section-type-filter",
    "parse-status-filter", "management-filter", "overall-treatment-filter", "other-procedure-filter",
    "review-priority-filter", "management-filter-wrap", "overall-treatment-filter-wrap",
    "other-procedure-filter-wrap", "review-priority-filter-wrap", "review-filter",
    "review-filter-wrap", "patient-sort", "management-tab-button",
    "patient-list", "load-more", "case-workspace", "case-empty", "case-content", "patient-header",
    "case-tabs", "case-tab-content", "section-inspector", "inspector-empty",
    "inspector-content", "inspector-backdrop", "toast",
  ].forEach((id) => { dom[id] = document.getElementById(id); });
  dom.navButtons = [...document.querySelectorAll("[data-view]")];
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function humanize(value) {
  if (!value) return "—";
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function typeLabel(value) { return TYPE_LABELS[value] || humanize(value); }
function sourceLabel(value) { return SOURCE_LABELS[value] || humanize(value); }
function statusLabel(value) { return STATUS_LABELS[value] || humanize(value); }
function detailLabel(value) { return DETAIL_LABELS[value] || statusLabel(value); }

function listFrom(value) {
  if (Array.isArray(value)) return value;
  if (!value) return [];
  try {
    const parsed = JSON.parse(String(value));
    return Array.isArray(parsed) ? parsed : [parsed];
  } catch {
    return String(value).split(";").map((item) => item.trim()).filter(Boolean);
  }
}

function colorFor(value, map = TYPE_COLORS) {
  if (map[value]) return map[value];
  let hash = 0;
  for (const char of String(value)) hash = ((hash << 5) - hash + char.charCodeAt(0)) | 0;
  return `hsl(${Math.abs(hash) % 330} 35% 47%)`;
}

function toneForManagement(value) {
  if (value === "surgery") return "positive";
  if (value === "intended_surgery") return "warning";
  if (value === "conservative") return "info";
  return "neutral";
}

function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("zh-CN").format(number) : "—";
}

function formatDate(value, includeTime = false) {
  if (!value) return "日期未知";
  const text = String(value);
  if (includeTime && text.includes("T")) return text.replace("T", " ").slice(0, 16);
  return text.slice(0, 10);
}

function formatRange(start, end) {
  if (!start && !end) return "无可靠时间范围";
  if (!start) return `截至 ${formatDate(end)}`;
  if (!end) return `始于 ${formatDate(start)}`;
  return `${formatDate(start)} — ${formatDate(end)}`;
}

function percent(value, total) {
  return total ? `${(Number(value) / Number(total) * 100).toFixed(1)}%` : "0.0%";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Accept": "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.error?.message || `请求失败 (${response.status})`);
  return payload;
}

function showToast(message) {
  clearTimeout(toastTimer);
  dom.toast.textContent = message;
  dom.toast.hidden = false;
  toastTimer = setTimeout(() => { dom.toast.hidden = true; }, 4500);
}

function loadingMarkup(lines = 4) {
  return `<div class="loading-block" aria-label="正在加载">${Array.from({ length: lines }, () => '<i class="loading-line"></i>').join("")}</div>`;
}

function fillSelect(select, values, labeler, firstLabel) {
  const current = select.value;
  select.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = firstLabel;
  select.append(all);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = labeler(value);
    select.append(option);
  }
  select.value = values.includes(current) ? current : "";
}

async function init() {
  cacheDom();
  bindEvents();
  try {
    const bootstrap = await api("/api/bootstrap");
    applyBootstrap(bootstrap);
    await loadPatients({ reset: true });
    dom.app.setAttribute("aria-busy", "false");
  } catch (error) {
    dom["run-status"].dataset.tone = "error";
    dom["run-status"].textContent = "连接失败";
    dom["overview-subtitle"].textContent = error.message;
    dom.app.setAttribute("aria-busy", "false");
  }
}

function bindEvents() {
  dom.navButtons.forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));
  dom["open-cohort"].addEventListener("click", () => switchView("cases"));
  dom["view-all-cases"].addEventListener("click", () => switchView("cases"));
  dom["run-select"].addEventListener("change", changeRun);
  dom["patient-search"].addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.filters.query = dom["patient-search"].value;
      loadPatients({ reset: true });
    }, 220);
  });
  for (const [id, key] of [
    ["section-type-filter", "section_type"],
    ["parse-status-filter", "parse_status"],
    ["management-filter", "management"],
    ["overall-treatment-filter", "overall_treatment"],
    ["other-procedure-filter", "other_procedure_status"],
    ["review-priority-filter", "review_priority"],
    ["patient-sort", "sort"],
  ]) {
    dom[id].addEventListener("change", () => {
      state.filters[key] = dom[id].value;
      loadPatients({ reset: true });
    });
  }
  dom["review-filter"].addEventListener("change", () => {
    state.filters.review_required = dom["review-filter"].checked ? "true" : "";
    loadPatients({ reset: true });
  });
  dom["load-more"].addEventListener("click", () => loadPatients({ reset: false }));
  dom["patient-list"].addEventListener("click", (event) => {
    const target = event.target.closest("[data-patient-id]");
    if (target) selectPatient(target.dataset.patientId);
  });
  dom["cohort-preview-list"].addEventListener("click", (event) => {
    const target = event.target.closest("[data-patient-id]");
    if (!target) return;
    switchView("cases");
    selectPatient(target.dataset.patientId);
  });
  dom["case-tabs"].addEventListener("click", (event) => {
    if (event.target.closest("[data-show-cohort]")) {
      dom["cases-view"].classList.remove("has-selection");
      dom["cases-view"].scrollIntoView({ behavior: "smooth", block: "start" });
      requestAnimationFrame(() => dom["patient-search"].focus({ preventScroll: true }));
      return;
    }
    const target = event.target.closest("[data-case-tab]");
    if (!target) return;
    state.caseTab = target.dataset.caseTab;
    state.documentFilter = "";
    renderCaseTab();
  });
  dom["case-tab-content"].addEventListener("click", (event) => {
    const sectionTarget = event.target.closest("[data-section-id]");
    if (sectionTarget) {
      openSection(sectionTarget.dataset.sectionId);
      return;
    }
    const typeTarget = event.target.closest("[data-timeline-type]");
    if (typeTarget) {
      state.timelineType = typeTarget.dataset.timelineType;
      renderCaseTab();
      return;
    }
    const documentTarget = event.target.closest("[data-document-filter]");
    if (documentTarget) {
      state.caseTab = "sections";
      state.documentFilter = documentTarget.dataset.documentFilter;
      renderCaseTab();
    }
  });
  dom["case-tab-content"].addEventListener("input", (event) => {
    if (event.target.id === "section-search-input") {
      state.sectionQuery = event.target.value;
      renderSectionRows();
    }
  });
  dom["patient-header"].addEventListener("click", (event) => {
    if (event.target.closest("[data-show-cohort]")) {
      dom["cases-view"].classList.remove("has-selection");
      dom["cases-view"].scrollIntoView({ behavior: "smooth", block: "start" });
      requestAnimationFrame(() => dom["patient-search"].focus({ preventScroll: true }));
      return;
    }
    const target = event.target.closest("[data-primary-section]");
    if (target) openSection(target.dataset.primarySection);
  });
  dom["inspector-content"].addEventListener("click", (event) => {
    if (event.target.closest("[data-close-inspector]")) closeInspector();
  });
  dom["inspector-backdrop"].addEventListener("click", closeInspector);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeInspector();
  });
}

function switchView(view) {
  state.activeView = view;
  const overview = view === "overview";
  dom["overview-view"].hidden = !overview;
  dom["cases-view"].hidden = overview;
  for (const button of dom.navButtons) {
    const active = button.dataset.view === view;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  if (!overview) dom["patient-search"].focus({ preventScroll: true });
}

function applyBootstrap(bootstrap) {
  state.bootstrap = bootstrap;
  const { snapshot, capabilities, schema } = bootstrap;
  dom["run-status"].dataset.tone = snapshot.reload_error ? "error" : "ready";
  dom["run-status"].textContent = snapshot.reload_error ? "使用上次可用数据" : "本地只读";
  dom["reload-banner"].hidden = !snapshot.reload_error;
  dom["reload-banner"].textContent = snapshot.reload_error || "";
  dom["overview-subtitle"].textContent = [
    snapshot.label,
    snapshot.finished_at ? formatDate(snapshot.finished_at, true) : "",
  ].filter(Boolean).join(" · ");

  dom["run-select"].replaceChildren();
  for (const run of bootstrap.runs) {
    const option = document.createElement("option");
    option.value = run.key;
    option.textContent = `${run.label}${run.finished_at ? ` · ${formatDate(run.finished_at)}` : ""}`;
    option.selected = run.active;
    dom["run-select"].append(option);
  }
  dom["run-select"].disabled = bootstrap.runs.length <= 1;

  fillSelect(dom["section-type-filter"], schema.section_types, typeLabel, "全部类型");
  fillSelect(dom["parse-status-filter"], schema.patient_parse_statuses, statusLabel, "全部状态");
  fillSelect(dom["management-filter"], schema.management_statuses, statusLabel, "全部状态");
  fillSelect(dom["overall-treatment-filter"], schema.overall_treatment_statuses || [], statusLabel, "全部状态");
  fillSelect(dom["other-procedure-filter"], schema.other_procedure_statuses || [], statusLabel, "全部状态");
  fillSelect(dom["review-priority-filter"], schema.review_priorities || [], statusLabel, "全部级别");
  dom["management-filter-wrap"].hidden = !capabilities.management_sidecar;
  dom["overall-treatment-filter-wrap"].hidden = !capabilities.management_sidecar;
  dom["other-procedure-filter-wrap"].hidden = !capabilities.management_sidecar;
  dom["review-priority-filter-wrap"].hidden = !capabilities.management_sidecar;
  dom["review-filter-wrap"].hidden = !capabilities.management_sidecar;
  dom["management-tab-button"].hidden = !capabilities.management_sidecar;
  dom["patient-search"].placeholder = capabilities.identifiers_loaded
    ? "搜索患者 ID、姓名或院内编号"
    : "搜索患者 ID";
  renderOverview();
}

async function changeRun() {
  const runKey = dom["run-select"].value;
  dom["run-select"].disabled = true;
  dom["run-status"].dataset.tone = "loading";
  dom["run-status"].textContent = "切换中";
  try {
    const bootstrap = await api("/api/runs/select", {
      method: "POST",
      body: JSON.stringify({ run_key: runKey }),
    });
    state.selectedPatientId = "";
    state.patient = null;
    state.section = null;
    state.filters = {
      query: "", section_type: "", parse_status: "", management: "", overall_treatment: "",
      other_procedure_status: "", review_priority: "", review_required: "", sort: "latest_desc",
    };
    dom["patient-search"].value = "";
    dom["review-filter"].checked = false;
    for (const id of [
      "section-type-filter", "parse-status-filter", "management-filter", "overall-treatment-filter",
      "other-procedure-filter", "review-priority-filter",
    ]) dom[id].value = "";
    dom["patient-sort"].value = "latest_desc";
    applyBootstrap(bootstrap);
    resetCaseWorkspace();
    await loadPatients({ reset: true });
    showToast(`已切换到 ${bootstrap.snapshot.label}`);
  } catch (error) {
    showToast(error.message);
    const current = state.bootstrap.runs.find((run) => run.active);
    if (current) dom["run-select"].value = current.key;
    dom["run-status"].dataset.tone = "error";
    dom["run-status"].textContent = "切换失败";
  } finally {
    dom["run-select"].disabled = state.bootstrap.runs.length <= 1;
  }
}

function renderOverview() {
  const { overview, capabilities } = state.bootstrap;
  const totals = overview.totals;
  const metrics = [
    ["队列患者", totals.patients, `${formatNumber(totals.patients_with_documents)} 有文档`],
    ["规范文档", totals.canonical_documents, `${formatNumber(totals.source_documents)} 来源`],
    ["文档页数", totals.pages, "原页定位"],
    ["结构化章节", totals.sections, "按需载入"],
    ["时间线事件", totals.timeline_events, "有日期"],
  ];
  dom["metric-grid"].innerHTML = metrics.map(([label, value, note]) => `
    <article class="metric-card"><span>${escapeHtml(label)}</span><strong>${formatNumber(value)}</strong><small>${escapeHtml(note)}</small></article>
  `).join("");

  dom["section-composition-total"].textContent = `${formatNumber(totals.sections)} 章节`;
  const maxSection = Math.max(1, ...overview.section_types.map((row) => row.count));
  dom["section-composition"].innerHTML = overview.section_types.map((row) => `
    <div class="bar-row">
      <div class="bar-label"><strong>${escapeHtml(typeLabel(row.key))}</strong></div>
      <div class="bar-track" aria-label="${escapeHtml(typeLabel(row.key))} ${formatNumber(row.count)}">
        <div class="bar-fill" style="--bar-width:${(row.count / maxSection * 100).toFixed(2)}%;--bar-color:${colorFor(row.key)}"></div>
      </div>
      <span class="bar-value">${formatNumber(row.count)}</span>
    </div>
  `).join("");

  renderSourceDonut(overview.text_sources, totals.sections);
  renderTimelineChart(overview.timeline_years);
  renderManagementOverview(overview, capabilities.management_sidecar);
}

function renderSourceDonut(rows, total) {
  const colors = ["#315f91", "#2d8a80", "#8a7aa7", "#9aa5b2", "#bd6f2a"];
  let cursor = 0;
  const segments = rows.map((row, index) => {
    const start = cursor;
    cursor += total ? row.count / total * 100 : 0;
    return `${colors[index % colors.length]} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`;
  });
  dom["source-donut"].style.setProperty("--donut-gradient", `conic-gradient(${segments.join(",")})`);
  dom["source-donut"].querySelector("strong").textContent = formatNumber(total);
  dom["source-donut"].setAttribute("aria-label", rows.map((row) => `${sourceLabel(row.key)} ${row.count}`).join("，"));
  dom["source-legend"].innerHTML = rows.map((row, index) => `
    <div class="legend-item" style="--legend-color:${colors[index % colors.length]}">
      <i class="legend-swatch"></i><span>${escapeHtml(sourceLabel(row.key))}</span>
      <strong>${formatNumber(row.count)} · ${percent(row.count, total)}</strong>
    </div>
  `).join("");
  const quality = state.bootstrap.overview.quality;
  dom["quality-facts"].innerHTML = [
    [quality.sections_without_reliable_date, "无可靠日期章节"],
    [quality.sections_requiring_date_review, "日期需人工复核"],
    [quality.patients_without_documents, "无来源文档患者"],
    [quality.source_hash_verification === "passed" ? "通过" : quality.source_hash_verification, "来源哈希核验"],
  ].map(([value, label]) => `<div class="quality-fact"><strong>${typeof value === "number" ? formatNumber(value) : escapeHtml(value ?? "未知")}</strong><span>${escapeHtml(label)}</span></div>`).join("");
}

function renderTimelineChart(rows) {
  if (!rows.length) {
    dom["timeline-chart"].innerHTML = '<div class="chart-empty">当前快照没有可绘制的时间线事件</div>';
    return;
  }
  const compact = window.innerWidth <= 600;
  const width = compact ? 520 : 720;
  const height = 214;
  const margin = { top: 24, right: 12, bottom: 32, left: 34 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const max = Math.max(...rows.map((row) => row.count), 1);
  const gap = Math.min(13, plotWidth / rows.length * .22);
  const barWidth = plotWidth / rows.length - gap;
  const ticks = [0, .5, 1];
  dom["timeline-chart"].innerHTML = `
    <svg class="${compact ? "is-compact" : ""}" viewBox="0 0 ${width} ${height}" role="img" aria-label="按年份统计的时间线事件">
      ${ticks.map((tick) => {
        const y = margin.top + plotHeight * (1 - tick);
        return `<line class="grid-line" x1="${margin.left}" x2="${width - margin.right}" y1="${y}" y2="${y}" /><text x="${margin.left - 7}" y="${y + 3}" text-anchor="end">${formatNumber(Math.round(max * tick))}</text>`;
      }).join("")}
      ${rows.map((row, index) => {
        const x = margin.left + index * (plotWidth / rows.length) + gap / 2;
        const barHeight = row.count / max * plotHeight;
        const y = margin.top + plotHeight - barHeight;
        const showLabel = !compact || index % 2 === 0 || index === rows.length - 1;
        return `<g><title>${escapeHtml(row.key)}：${formatNumber(row.count)} 条</title><rect class="year-bar" x="${x}" y="${y}" width="${Math.max(2, barWidth)}" height="${barHeight}" />${showLabel ? `<text class="value-label" x="${x + barWidth / 2}" y="${Math.max(13, y - 6)}" text-anchor="middle">${formatNumber(row.count)}</text><text x="${x + barWidth / 2}" y="${height - 9}" text-anchor="middle">${escapeHtml(row.key)}</text>` : ""}</g>`;
      }).join("")}
    </svg>`;
}

function distributionMarkup(rows, colors = MANAGEMENT_COLORS) {
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  if (!rows.length) return '<div class="chart-empty chart-empty--compact">暂无数据</div>';
  return `
    <div class="management-stack" aria-label="状态构成">
      ${rows.map((row) => `<span title="${escapeHtml(statusLabel(row.key))} ${formatNumber(row.count)}" style="--segment-width:${total ? row.count / total * 100 : 0}%;--segment-color:${colorFor(row.key, colors)}"></span>`).join("")}
    </div>
    <div class="management-list">
      ${rows.map((row) => `<div class="management-item" style="--segment-color:${colorFor(row.key, colors)}"><i></i><span>${escapeHtml(statusLabel(row.key))}</span><strong>${formatNumber(row.count)} · ${percent(row.count, total)}</strong></div>`).join("")}
    </div>`;
}

function renderManagementOverview(overview, available) {
  dom["management-panel"].hidden = !available;
  if (!available) return;
  dom["management-total"].textContent = `${formatNumber(overview.totals.surgery_events)} 手术事件 · ${formatNumber(overview.totals.management_evidence)} 证据`;
  dom["management-chart"].innerHTML = distributionMarkup(overview.management_statuses || []);
  dom["overall-treatment-chart"].innerHTML = distributionMarkup(overview.overall_treatment_statuses || []);
  dom["other-procedure-chart"].innerHTML = distributionMarkup(overview.other_procedure_statuses || []);
  dom["review-priority-chart"].innerHTML = distributionMarkup(overview.review_priorities || [], PRIORITY_COLORS);
}

async function loadPatients({ reset }) {
  if (reset) {
    state.patientOffset = 0;
    state.patientRows = [];
    dom["patient-list"].innerHTML = loadingMarkup(5);
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(state.filters)) if (value) params.set(key, value);
  params.set("offset", String(state.patientOffset));
  params.set("limit", String(state.patientLimit));
  try {
    const payload = await api(`/api/patients?${params}`);
    state.patientTotal = payload.total;
    state.patientRows = reset ? payload.rows : state.patientRows.concat(payload.rows);
    state.patientOffset = state.patientRows.length;
    renderPatientList();
    if (reset) renderCohortPreview(payload.rows.slice(0, 8));
  } catch (error) {
    dom["patient-list"].innerHTML = `<div class="patient-empty">${escapeHtml(error.message)}</div>`;
    showToast(error.message);
  }
}

function renderPatientList() {
  dom["cohort-count"].textContent = formatNumber(state.patientTotal);
  if (!state.patientRows.length) {
    dom["patient-list"].innerHTML = '<div class="patient-empty">没有符合当前条件的病例</div>';
    dom["load-more"].hidden = true;
    return;
  }
  dom["patient-list"].innerHTML = state.patientRows.map((row) => {
    const management = row.management ? `<span class="pill" data-tone="${toneForManagement(row.management)}" ${row.management === "intended_surgery" ? 'data-outline="true"' : ""}>AAOCA · ${escapeHtml(statusLabel(row.management))}</span>` : "";
    const priority = row.review_priority
      ? `<span class="pill" data-tone="${row.review_priority === "high" ? "danger" : row.review_priority === "medium" ? "warning" : "positive"}">${escapeHtml(statusLabel(row.review_priority))}优先</span>` : "";
    const source = row.text_sources.local_ocr ? "含 OCR" : "原生文本";
    const name = row.display_name ? `<small>${escapeHtml(row.display_name)}</small>` : "";
    return `<button class="patient-row ${row.patient_id === state.selectedPatientId ? "is-selected" : ""}" type="button" data-patient-id="${escapeHtml(row.patient_id)}">
      <span class="patient-row-top"><span class="patient-row-name">${escapeHtml(row.patient_id)}${name}</span><span class="patient-row-pills">${management}${priority}</span></span>
      <span class="patient-meta"><span>${formatNumber(row.n_documents)} 文档</span><span>${formatNumber(row.n_sections)} 章节</span><span>${formatNumber(row.n_timeline_events)} 事件</span><span>${escapeHtml(source)}</span>${row.overall_treatment_status ? `<span>总体 · ${escapeHtml(statusLabel(row.overall_treatment_status))}</span>` : ""}</span>
      <span class="patient-range">${escapeHtml(formatRange(row.earliest_date, row.latest_date))}</span>
    </button>`;
  }).join("");
  dom["load-more"].hidden = state.patientRows.length >= state.patientTotal;
}

function renderCohortPreview(rows) {
  dom["cohort-preview-list"].innerHTML = rows.slice(0, 8).map((row) => `
    <button class="preview-card" type="button" data-patient-id="${escapeHtml(row.patient_id)}">
      <strong>${escapeHtml(row.display_name || row.patient_id)}</strong>
      <p><span>${formatNumber(row.n_sections)} 章节</span><span>${escapeHtml(row.overall_treatment_status ? statusLabel(row.overall_treatment_status) : row.management ? statusLabel(row.management) : statusLabel(row.parse_status))}</span></p>
    </button>
  `).join("");
}

async function selectPatient(patientId) {
  if (!patientId) return;
  state.selectedPatientId = patientId;
  state.selectedSectionId = "";
  state.section = null;
  state.caseTab = state.bootstrap?.capabilities?.management_sidecar ? "management" : "timeline";
  state.timelineType = "";
  state.sectionQuery = "";
  state.documentFilter = "";
  renderPatientList();
  closeInspector();
  dom["case-empty"].hidden = true;
  dom["case-content"].hidden = false;
  dom["patient-header"].innerHTML = loadingMarkup(4);
  dom["case-tab-content"].innerHTML = loadingMarkup(7);
  const requestId = ++state.patientRequest;
  try {
    const patient = await api(`/api/patients/${encodeURIComponent(patientId)}`);
    if (requestId !== state.patientRequest) return;
    state.patient = patient;
    renderPatient();
    if (window.innerWidth <= 920) {
      dom["cases-view"].classList.add("has-selection");
      requestAnimationFrame(() => dom["case-workspace"].scrollIntoView({ behavior: "smooth", block: "start" }));
    }
  } catch (error) {
    if (requestId !== state.patientRequest) return;
    dom["patient-header"].innerHTML = `<div class="patient-empty">${escapeHtml(error.message)}</div>`;
    dom["case-tab-content"].replaceChildren();
    showToast(error.message);
  }
}

function resetCaseWorkspace() {
  dom["cases-view"].classList.remove("has-selection");
  dom["case-empty"].hidden = false;
  dom["case-content"].hidden = true;
  dom["patient-header"].replaceChildren();
  dom["case-tab-content"].replaceChildren();
  closeInspector();
}

function renderPatient() {
  const patient = state.patient;
  const manifest = patient.manifest;
  const management = patient.management || {};
  const displayName = patient.identity?.name || patient.patient_id;
  const idSuffix = patient.identity?.name ? `<small>${escapeHtml(patient.patient_id)}</small>` : "";
  const managementPill = management.observed_management
    ? `<span class="pill" data-tone="${toneForManagement(management.observed_management)}" ${management.observed_management === "intended_surgery" ? 'data-outline="true"' : ""}>AAOCA · ${escapeHtml(statusLabel(management.observed_management))}</span>`
    : "";
  const overallPill = management.overall_treatment_status
    ? `<span class="pill" data-tone="${toneForManagement(management.overall_treatment_status)}">总体 · ${escapeHtml(statusLabel(management.overall_treatment_status))}</span>` : "";
  const reviewPill = String(management.review_required).toLowerCase() === "true"
    ? '<span class="pill" data-tone="warning">研究复核</span>' : "";
  const priorityPill = management.complex_case_review_priority
    ? `<span class="pill" data-tone="${management.complex_case_review_priority === "high" ? "danger" : management.complex_case_review_priority === "medium" ? "warning" : "positive"}">${escapeHtml(statusLabel(management.complex_case_review_priority))}优先</span>` : "";
  const parsePill = `<span class="pill" data-tone="${manifest.parse_status === "ok" ? "positive" : manifest.parse_status === "no_pdf_in_scope" ? "danger" : "info"}">${escapeHtml(statusLabel(manifest.parse_status))}</span>`;
  const primarySection = management.primary_section_id || "";
  dom["patient-header"].innerHTML = `
    <button class="mobile-cohort-back" type="button" data-show-cohort>← 病例列表</button>
    <div class="patient-title-line">
      <div><h2>${escapeHtml(displayName)}${idSuffix}</h2></div>
      <div class="patient-badges">${managementPill}${overallPill}${priorityPill}${reviewPill}${parsePill}</div>
    </div>
    <dl class="patient-stats">
      <div class="patient-stat"><dt>来源文档</dt><dd>${formatNumber(patient.documents.filter((row) => !row.duplicate_of).length)}</dd></div>
      <div class="patient-stat"><dt>章节</dt><dd>${formatNumber(patient.sections.length)}</dd></div>
      <div class="patient-stat"><dt>时间线事件</dt><dd>${formatNumber(patient.timeline.length)}</dd></div>
      <div class="patient-stat"><dt>记录范围</dt><dd>${escapeHtml(formatRange(manifest.earliest_document_date, manifest.latest_document_date))}</dd></div>
    </dl>
    ${management.observed_management ? `<div class="management-note"><span class="method-chip">规则提取</span>${primarySection ? `<button class="evidence-action" type="button" data-primary-section="${escapeHtml(primarySection)}">查看章节</button>` : ""}</div>` : ""}
  `;
  renderCaseTab();
}

function renderCaseTab() {
  if (!state.patient) return;
  for (const button of dom["case-tabs"].querySelectorAll("[data-case-tab]")) {
    const active = button.dataset.caseTab === state.caseTab;
    button.classList.toggle("is-active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  if (state.caseTab === "management") renderManagementTab();
  else if (state.caseTab === "timeline") renderTimelineTab();
  else if (state.caseTab === "documents") renderDocumentsTab();
  else renderSectionsTab();
}

function tagListMarkup(values, emptyText = "—") {
  const items = listFrom(values).filter((value) => value !== "");
  if (!items.length) return `<span class="muted-value">${escapeHtml(emptyText)}</span>`;
  return `<div class="detail-tags">${items.map((value) => `<span>${escapeHtml(detailLabel(value))}</span>`).join("")}</div>`;
}

function trueValue(value) {
  return value === true || String(value).toLowerCase() === "true" || String(value) === "1";
}

function contextMarkup(value) {
  return listFrom(value).map((context) => {
    if (!context || typeof context !== "object") return "";
    const modes = context.procedure_modes?.length ? context.procedure_modes : [context.procedure_mode].filter(Boolean);
    return `<article class="context-card">
      <div class="context-card-head"><strong>${escapeHtml(formatDate(context.procedure_date))}</strong><span>${escapeHtml(detailLabel(context.aaoca_handling || "unknown"))}</span></div>
      ${tagListMarkup(modes)}
      ${tagListMarkup(context.procedure_categories || [])}
    </article>`;
  }).join("");
}

function surgeryEventMarkup(row) {
  const sectionId = row.primary_section_id || "";
  return `<article class="surgery-event-card">
    <div class="surgery-event-date"><span>手术日期</span><strong>${escapeHtml(formatDate(row.surgery_date))}</strong></div>
    <div class="surgery-event-main">
      ${tagListMarkup(row.procedure_types)}
      <p>${escapeHtml(listFrom(row.procedure_names).join("；") || "未记录术式名称")}</p>
      <div class="inline-meta"><span>${formatNumber(row.n_supporting_evidence)} 条证据</span><span>${escapeHtml(statusLabel(row.relation_confidence))}置信度</span>${trueValue(row.formal_surgery_record_present) ? "<span>手术记录</span>" : ""}${trueValue(row.postoperative_evidence_present) ? "<span>术后记录</span>" : ""}</div>
    </div>
    ${sectionId ? `<button type="button" class="evidence-action" data-section-id="${escapeHtml(sectionId)}">查看章节</button>` : ""}
  </article>`;
}

function evidenceMarkup(row, primaryEvidenceId) {
  const primary = row.evidence_id === primaryEvidenceId;
  const procedure = row.procedure_name_raw ? `<strong>${escapeHtml(row.procedure_name_raw)}</strong>` : "";
  const excerpt = String(row.evidence_text || "").replace(/\s+/g, " ").trim().slice(0, 260);
  const selected = row.section_id && row.section_id === state.selectedSectionId;
  return `<article class="evidence-card ${primary ? "is-primary" : ""} ${selected ? "is-selected" : ""}">
    <div class="evidence-card-head">
      <div><span class="pill" data-tone="${row.strength === "high" ? "positive" : "info"}">${escapeHtml(statusLabel(row.assertion))}</span>${primary ? '<span class="pill" data-tone="purple">主要证据</span>' : ""}</div>
      <time>${escapeHtml(formatDate(row.evidence_date || row.section_date))}</time>
    </div>
    <div class="evidence-card-title">${procedure}<span>${escapeHtml(statusLabel(row.event_kind))} · ${escapeHtml(statusLabel(row.aaoca_relation))}</span></div>
    ${excerpt ? `<p>${escapeHtml(excerpt)}${String(row.evidence_text || "").length > 260 ? "…" : ""}</p>` : ""}
    <div class="evidence-card-foot"><span>${escapeHtml(typeLabel(row.section_subtype || row.section_type))} · 第 ${formatNumber(row.page_start)}${row.page_end && row.page_end !== row.page_start ? `–${formatNumber(row.page_end)}` : ""} 页</span>${row.section_id ? `<button type="button" class="evidence-action" data-section-id="${escapeHtml(row.section_id)}">查看章节</button>` : ""}</div>
  </article>`;
}

function renderManagementTab() {
  const patient = state.patient;
  const row = patient.management || {};
  const surgeryEvents = patient.surgery_events || [];
  const evidence = patient.management_evidence || [];
  const evidenceFlags = [
    ["has_completed_surgery_evidence", "完成手术证据"],
    ["has_surgical_intent_evidence", "手术意向证据"],
    ["has_cancelled_or_declined_evidence", "取消 / 拒绝证据"],
    ["has_conservative_evidence", "保守管理证据"],
    ["has_diagnostic_procedure_evidence", "诊断操作证据"],
    ["has_unrelated_surgery_evidence", "其他手术证据"],
  ].filter(([key]) => trueValue(row[key]));
  const contexts = contextMarkup(row.other_procedure_contexts);
  dom["case-tab-content"].innerHTML = `
    <div class="tab-toolbar"><h3>处置概览</h3><span class="panel-note">${formatNumber(evidence.length)} 条证据 · ${formatNumber(surgeryEvents.length)} 个 AAOCA 手术事件</span></div>
    <section class="management-hero">
      <div class="management-stat"><span>AAOCA 管理</span><strong>${escapeHtml(statusLabel(row.observed_management))}</strong><small>${escapeHtml(statusLabel(row.management_confidence))}置信度</small></div>
      <div class="management-stat"><span>实际 AAOCA 手术</span><strong>${escapeHtml(statusLabel(row.actual_aaoca_surgery))}</strong><small>${formatNumber(row.n_surgery_events)} 个事件</small></div>
      <div class="management-stat"><span>总体治疗</span><strong>${escapeHtml(statusLabel(row.overall_treatment_status))}</strong><small>${escapeHtml(detailLabel(row.overall_treatment_rule))}</small></div>
      <div class="management-stat"><span>研究复核优先级</span><strong>${escapeHtml(statusLabel(row.complex_case_review_priority))}</strong><small>${trueValue(row.review_required) ? "已纳入复核" : "常规查看"}</small></div>
    </section>
    <div class="management-detail-grid">
      <section class="management-section">
        <div class="management-section-head"><h4>AAOCA 管理</h4><span>${escapeHtml(row.first_surgery_date ? formatRange(row.first_surgery_date, row.last_surgery_date) : "未记录手术日期")}</span></div>
        <dl class="compact-facts">
          <div><dt>标准术式</dt><dd>${tagListMarkup(row.procedure_types)}</dd></div>
          <div><dt>术式原文</dt><dd>${tagListMarkup(row.procedure_names)}</dd></div>
          <div><dt>证据构成</dt><dd>${evidenceFlags.length ? `<div class="detail-tags">${evidenceFlags.map(([, label]) => `<span>${escapeHtml(label)}</span>`).join("")}</div>` : '<span class="muted-value">—</span>'}</dd></div>
        </dl>
      </section>
      <section class="management-section">
        <div class="management-section-head"><h4>其他心脏操作</h4><span>${escapeHtml(statusLabel(row.other_cardiac_procedure_status))}</span></div>
        <dl class="compact-facts">
          <div><dt>操作模式</dt><dd>${tagListMarkup(row.other_procedure_modes)}</dd></div>
          <div><dt>操作类别</dt><dd>${tagListMarkup(row.other_procedure_categories)}</dd></div>
          <div><dt>AAOCA 同期处理</dt><dd>${escapeHtml(detailLabel(row.aaoca_handling_during_other_procedure))}</dd></div>
        </dl>
        ${contexts ? `<div class="context-list">${contexts}</div>` : ""}
      </section>
    </div>
    ${listFrom(row.management_complexity_flags).length || listFrom(row.complex_case_review_reasons).length || listFrom(row.review_reasons).length ? `<section class="management-section management-review-section"><div class="management-section-head"><h4>复核索引</h4></div><div class="review-index"><div><span>情境标签</span>${tagListMarkup(row.management_complexity_flags)}</div><div><span>优先级依据</span>${tagListMarkup(row.complex_case_review_reasons)}</div><div><span>复核原因</span>${tagListMarkup(row.review_reasons)}</div></div></section>` : ""}
    ${surgeryEvents.length ? `<section class="management-section"><div class="management-section-head"><h4>AAOCA 手术事件</h4><span>${formatNumber(surgeryEvents.length)}</span></div><div class="surgery-event-list">${surgeryEvents.map(surgeryEventMarkup).join("")}</div></section>` : ""}
    <section class="management-section"><div class="management-section-head"><h4>处置证据</h4><span>${formatNumber(evidence.length)}</span></div>${evidence.length ? `<div class="evidence-grid ${evidence.length === 1 ? "is-single" : ""}">${evidence.map((item) => evidenceMarkup(item, row.primary_evidence_id)).join("")}</div>` : '<div class="timeline-empty">当前 sidecar 未提供逐条证据</div>'}</section>
  `;
}

function renderTypeFilters(rows) {
  const counts = new Map();
  for (const row of rows) counts.set(row.section_type, (counts.get(row.section_type) || 0) + 1);
  return `<div class="type-filters"><button type="button" class="type-filter ${state.timelineType ? "" : "is-active"}" data-timeline-type="">全部 ${formatNumber(rows.length)}</button>${[...counts.entries()].sort((a, b) => b[1] - a[1]).map(([type, count]) => `<button type="button" class="type-filter ${state.timelineType === type ? "is-active" : ""}" data-timeline-type="${escapeHtml(type)}" style="--type-color:${colorFor(type)}">${escapeHtml(typeLabel(type))} ${formatNumber(count)}</button>`).join("")}</div>`;
}

function renderTimelineTab() {
  const all = state.patient.timeline;
  const rows = state.timelineType ? all.filter((row) => row.section_type === state.timelineType) : all;
  dom["case-tab-content"].innerHTML = `
    <div class="tab-toolbar"><h3>纵向诊疗时间线</h3>${renderTypeFilters(all)}</div>
    ${rows.length ? `<div class="timeline-list">${rows.map(timelineEventMarkup).join("")}</div>` : '<div class="timeline-empty">当前筛选下没有带可靠日期的事件</div>'}
  `;
}

function timelineEventMarkup(row) {
  const type = row.section_type || "unknown";
  const title = row.title || typeLabel(type);
  const review = row.date_requires_review === true;
  const selected = row.section_id === state.selectedSectionId;
  return `<article class="timeline-event" style="--type-color:${colorFor(type)}">
    <time class="timeline-date">${escapeHtml(formatDate(row.date, true))}</time>
    <i class="timeline-dot" data-review="${review}"></i>
    <button type="button" class="timeline-event-button ${selected ? "is-selected" : ""}" data-section-id="${escapeHtml(row.section_id)}">
      <span class="timeline-event-title"><strong>${escapeHtml(title)}</strong><span>第 ${formatNumber(row.page_start)}${row.page_end && row.page_end !== row.page_start ? `–${formatNumber(row.page_end)}` : ""} 页</span></span>
      <span class="timeline-event-meta"><span>${escapeHtml(typeLabel(type))}</span><span>${escapeHtml(sourceLabel(row.text_source))}</span>${review ? '<span class="pill" data-tone="warning">日期待核</span>' : ""}</span>
    </button>
  </article>`;
}

function renderDocumentsTab() {
  const documents = state.patient.documents;
  dom["case-tab-content"].innerHTML = `
    <div class="tab-toolbar"><h3>来源文档</h3><span class="panel-note">${formatNumber(documents.length)} 个来源记录</span></div>
    <div class="document-grid">${documents.map((row) => `
      <article class="document-card">
        <div><span class="pill" data-tone="${row.parse_status === "ok" ? "positive" : row.parse_status === "empty" ? "danger" : "info"}">${escapeHtml(statusLabel(row.parse_status))}</span><h4 title="${escapeHtml(row.label)}">${escapeHtml(row.label)}</h4></div>
        <div class="document-card-meta"><div><span>类型</span><strong>${escapeHtml(typeLabel(row.document_type))}</strong></div><div><span>页数</span><strong>${formatNumber(row.page_count)}</strong></div><div><span>章节</span><strong>${formatNumber(row.n_sections)}</strong></div><div><span>文本来源</span><strong>${escapeHtml(sourceLabel(row.text_source))}</strong></div><div><span>OCR 页</span><strong>${formatNumber(row.ocr_recovered_pages)}</strong></div><div><span>时间范围</span><strong>${escapeHtml(formatDate(row.earliest_section_date))}</strong></div></div>
        <div class="document-actions"><button type="button" data-document-filter="${escapeHtml(row.document_id)}">查看章节</button>${row.pdf_url ? `<a href="${escapeHtml(row.pdf_url)}" target="_blank" rel="noopener">打开原 PDF</a>` : ""}</div>
      </article>`).join("")}</div>`;
}

function renderSectionsTab() {
  dom["case-tab-content"].innerHTML = `
    <div class="tab-toolbar"><div><h3>${state.documentFilter ? "文档章节" : "全部章节"}</h3>${state.documentFilter ? `<button class="text-action" type="button" data-document-filter="">清除文档筛选</button>` : ""}</div><label class="section-search"><span class="sr-only">搜索章节标题</span><input id="section-search-input" type="search" placeholder="搜索标题或类型" value="${escapeHtml(state.sectionQuery)}" /></label></div>
    <div id="section-list-container" class="section-list"></div>`;
  renderSectionRows();
}

function renderSectionRows() {
  const container = document.getElementById("section-list-container");
  if (!container || !state.patient) return;
  const query = state.sectionQuery.trim().toLowerCase();
  const rows = state.patient.sections.filter((row) => {
    if (state.documentFilter && row.document_id !== state.documentFilter) return false;
    if (!query) return true;
    return [row.title, row.section_type, row.section_subtype, row.section_id].some((value) => String(value || "").toLowerCase().includes(query));
  });
  container.innerHTML = rows.length ? rows.map((row) => `
    <button class="section-row ${row.section_id === state.selectedSectionId ? "is-selected" : ""}" type="button" data-section-id="${escapeHtml(row.section_id)}" style="--type-color:${colorFor(row.section_type)}">
      <i class="section-type-mark"></i><span class="section-row-main"><strong>${escapeHtml(row.title || typeLabel(row.section_type))}</strong><span>${escapeHtml(typeLabel(row.section_type))} · 第 ${formatNumber(row.page_start)} 页 · ${escapeHtml(sourceLabel(row.text_source))}</span></span><time class="section-row-date">${escapeHtml(formatDate(row.date))}</time>
    </button>`).join("") : '<div class="timeline-empty">没有符合当前条件的章节</div>';
}

async function openSection(sectionId) {
  if (!sectionId) return;
  state.selectedSectionId = sectionId;
  if (state.caseTab === "management") renderManagementTab();
  if (state.caseTab === "timeline") renderTimelineTab();
  if (state.caseTab === "sections") renderSectionRows();
  dom["inspector-empty"].hidden = true;
  dom["inspector-content"].hidden = false;
  dom["inspector-content"].innerHTML = loadingMarkup(8);
  dom["section-inspector"].classList.add("is-open");
  document.body.classList.add("inspector-open");
  dom["inspector-backdrop"].hidden = window.innerWidth > 1500;
  const requestId = ++state.sectionRequest;
  try {
    const section = await api(`/api/sections/${encodeURIComponent(sectionId)}`);
    if (requestId !== state.sectionRequest) return;
    state.section = section;
    renderInspector();
  } catch (error) {
    if (requestId !== state.sectionRequest) return;
    dom["inspector-content"].innerHTML = `<div class="patient-empty">${escapeHtml(error.message)}</div>`;
    showToast(error.message);
  }
}

function renderSectionText(pre, value, evidenceRows) {
  const text = value || "（无正文）";
  const ranges = evidenceRows.map((item) => ({
    start: Number(item.assertion_char_start),
    end: Number(item.assertion_char_end),
  })).filter((range) => Number.isInteger(range.start) && Number.isInteger(range.end)
    && range.start >= 0 && range.end > range.start && range.end <= text.length)
    .sort((left, right) => left.start - right.start);
  if (!ranges.length) {
    pre.textContent = text;
    return null;
  }
  const fragment = document.createDocumentFragment();
  let cursor = 0;
  let firstMark = null;
  for (const range of ranges) {
    if (range.start < cursor) continue;
    fragment.append(document.createTextNode(text.slice(cursor, range.start)));
    const mark = document.createElement("mark");
    mark.className = "evidence-highlight";
    mark.textContent = text.slice(range.start, range.end);
    fragment.append(mark);
    if (!firstMark) firstMark = mark;
    cursor = range.end;
  }
  fragment.append(document.createTextNode(text.slice(cursor)));
  pre.replaceChildren(fragment);
  return firstMark;
}

function renderInspector() {
  const row = state.section;
  const linkedEvidence = (state.patient?.management_evidence || []).filter((item) => item.section_id === row.section_id);
  const pageLabel = row.page_end && row.page_end !== row.page_start
    ? `第 ${row.page_start}–${row.page_end} 页` : `第 ${row.page_start} 页`;
  const dateReview = row.date_requires_review === true
    ? '<span class="pill" data-tone="warning">日期需复核</span>' : "";
  const metadata = [
    ["章节标识", row.section_id],
    ["文档标识", row.document_id],
    ["日期来源", row.date_source],
    ["日期证据", row.date_evidence],
    ["日期置信度", row.date_evidence_confidence],
    ["页内行号", `${row.line_start ?? "—"} – ${row.line_end ?? "—"}`],
    ["临床阶段", row.clinical_stage],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");
  dom["inspector-content"].innerHTML = `
    <header class="inspector-header">
      <div class="inspector-header-top"><div><p class="eyebrow">${escapeHtml(typeLabel(row.section_type))}</p><h2>${escapeHtml(row.title || typeLabel(row.section_type))}</h2></div><button class="inspector-close" type="button" data-close-inspector aria-label="关闭证据查看器">×</button></div>
      <div class="inspector-badges"><span class="pill" data-tone="info">${escapeHtml(typeLabel(row.section_type))}</span><span class="pill">${escapeHtml(formatDate(row.date, true))}</span><span class="pill">${escapeHtml(pageLabel)}</span><span class="pill" data-tone="${row.text_source === "local_ocr" ? "warning" : "positive"}">${escapeHtml(sourceLabel(row.text_source))}</span>${dateReview}</div>
    </header>
    <div class="inspector-body">
      ${row.pdf_url ? `<a class="source-link" href="${escapeHtml(row.pdf_url)}" target="_blank" rel="noopener"><span>打开原始 PDF 对照</span><strong>${escapeHtml(pageLabel)} ↗</strong></a>` : ""}
      ${linkedEvidence.length ? `<section class="inspector-evidence"><strong>本章节处置断言</strong><div>${linkedEvidence.map((item) => `<span class="pill" data-tone="${item.strength === "high" ? "positive" : "info"}">${escapeHtml(statusLabel(item.assertion))} · ${escapeHtml(statusLabel(item.aaoca_relation))}</span>`).join("")}</div></section>` : ""}
      <pre class="section-text"></pre>
      <details class="provenance"><summary>查看来源与切分信息</summary><dl>${metadata.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl>${row.page_spans?.length ? `<pre>${escapeHtml(JSON.stringify(row.page_spans, null, 2))}</pre>` : ""}${row.extra_fields && Object.keys(row.extra_fields).length ? `<pre>${escapeHtml(JSON.stringify(row.extra_fields, null, 2))}</pre>` : ""}</details>
    </div>`;
  const firstMark = renderSectionText(
    dom["inspector-content"].querySelector(".section-text"),
    row.text,
    linkedEvidence,
  );
  requestAnimationFrame(() => {
    dom["inspector-content"].querySelector(".inspector-close")?.focus({ preventScroll: true });
    firstMark?.scrollIntoView({ block: "center" });
  });
}

function closeInspector() {
  const hadSelection = Boolean(state.selectedSectionId || state.section);
  dom["section-inspector"].classList.remove("is-open");
  document.body.classList.remove("inspector-open");
  dom["inspector-backdrop"].hidden = true;
  dom["inspector-content"].hidden = true;
  dom["inspector-empty"].hidden = false;
  state.selectedSectionId = "";
  state.section = null;
  if (hadSelection && state.patient) {
    if (state.caseTab === "management") renderManagementTab();
    if (state.caseTab === "timeline") renderTimelineTab();
    if (state.caseTab === "sections") renderSectionRows();
  }
}

init();
