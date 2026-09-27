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
  high: "高",
  medium: "中",
  low: "低",
  yes: "是",
  no: "否",
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

const state = {
  bootstrap: null,
  activeView: "overview",
  filters: {
    query: "",
    section_type: "",
    parse_status: "",
    management: "",
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
    "management-chart", "cohort-preview-list", "open-cohort", "view-all-cases", "cohort-count",
    "patient-search", "section-type-filter", "parse-status-filter", "management-filter",
    "management-filter-wrap", "review-filter", "review-filter-wrap", "patient-sort",
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
  dom["management-filter-wrap"].hidden = !capabilities.management_sidecar;
  dom["review-filter-wrap"].hidden = !capabilities.management_sidecar;
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
    state.filters = { query: "", section_type: "", parse_status: "", management: "", review_required: "", sort: "latest_desc" };
    dom["patient-search"].value = "";
    dom["review-filter"].checked = false;
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
  renderManagement(overview.management_statuses, capabilities.management_sidecar);
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
  const width = 720;
  const height = 214;
  const margin = { top: 24, right: 12, bottom: 32, left: 34 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const max = Math.max(...rows.map((row) => row.count), 1);
  const gap = Math.min(13, plotWidth / rows.length * .22);
  const barWidth = plotWidth / rows.length - gap;
  const ticks = [0, .5, 1];
  dom["timeline-chart"].innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="按年份统计的时间线事件">
      ${ticks.map((tick) => {
        const y = margin.top + plotHeight * (1 - tick);
        return `<line class="grid-line" x1="${margin.left}" x2="${width - margin.right}" y1="${y}" y2="${y}" /><text x="${margin.left - 7}" y="${y + 3}" text-anchor="end">${formatNumber(Math.round(max * tick))}</text>`;
      }).join("")}
      ${rows.map((row, index) => {
        const x = margin.left + index * (plotWidth / rows.length) + gap / 2;
        const barHeight = row.count / max * plotHeight;
        const y = margin.top + plotHeight - barHeight;
        return `<g><title>${escapeHtml(row.key)}：${formatNumber(row.count)} 条</title><rect class="year-bar" x="${x}" y="${y}" width="${Math.max(2, barWidth)}" height="${barHeight}" /><text class="value-label" x="${x + barWidth / 2}" y="${Math.max(10, y - 6)}" text-anchor="middle">${formatNumber(row.count)}</text><text x="${x + barWidth / 2}" y="${height - 9}" text-anchor="middle">${escapeHtml(row.key)}</text></g>`;
      }).join("")}
    </svg>`;
}

function renderManagement(rows, available) {
  dom["management-panel"].hidden = !available;
  if (!available) return;
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  dom["management-chart"].innerHTML = `
    <div class="management-stack" aria-label="管理方式构成">
      ${rows.map((row) => `<span title="${escapeHtml(statusLabel(row.key))} ${formatNumber(row.count)}" style="--segment-width:${total ? row.count / total * 100 : 0}%;--segment-color:${colorFor(row.key, MANAGEMENT_COLORS)}"></span>`).join("")}
    </div>
    <div class="management-list">
      ${rows.map((row) => `<div class="management-item" style="--segment-color:${colorFor(row.key, MANAGEMENT_COLORS)}"><i></i><span>${escapeHtml(statusLabel(row.key))}</span><strong>${formatNumber(row.count)} · ${percent(row.count, total)}</strong></div>`).join("")}
    </div>
    `;
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
    const management = row.management ? `<span class="pill" data-tone="${toneForManagement(row.management)}" ${row.management === "intended_surgery" ? 'data-outline="true"' : ""}>${escapeHtml(statusLabel(row.management))}</span>` : "";
    const review = row.review_required === true ? '<span class="pill" data-tone="warning">需复核</span>' : "";
    const source = row.text_sources.local_ocr ? "含 OCR" : "原生文本";
    const name = row.display_name ? `<small>${escapeHtml(row.display_name)}</small>` : "";
    return `<button class="patient-row ${row.patient_id === state.selectedPatientId ? "is-selected" : ""}" type="button" data-patient-id="${escapeHtml(row.patient_id)}">
      <span class="patient-row-top"><span class="patient-row-name">${escapeHtml(row.patient_id)}${name}</span><span>${management}${review}</span></span>
      <span class="patient-meta"><span>${formatNumber(row.n_documents)} 文档</span><span>${formatNumber(row.n_sections)} 章节</span><span>${formatNumber(row.n_timeline_events)} 事件</span><span>${escapeHtml(source)}</span></span>
      <span class="patient-range">${escapeHtml(formatRange(row.earliest_date, row.latest_date))}</span>
    </button>`;
  }).join("");
  dom["load-more"].hidden = state.patientRows.length >= state.patientTotal;
}

function renderCohortPreview(rows) {
  dom["cohort-preview-list"].innerHTML = rows.slice(0, 8).map((row) => `
    <button class="preview-card" type="button" data-patient-id="${escapeHtml(row.patient_id)}">
      <strong>${escapeHtml(row.display_name || row.patient_id)}</strong>
      <p><span>${formatNumber(row.n_sections)} 章节</span><span>${escapeHtml(row.management ? statusLabel(row.management) : statusLabel(row.parse_status))}</span></p>
    </button>
  `).join("");
}

async function selectPatient(patientId) {
  if (!patientId) return;
  state.selectedPatientId = patientId;
  state.selectedSectionId = "";
  state.section = null;
  state.caseTab = "timeline";
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
    ? `<span class="pill" data-tone="${toneForManagement(management.observed_management)}" ${management.observed_management === "intended_surgery" ? 'data-outline="true"' : ""}>${escapeHtml(statusLabel(management.observed_management))}</span>`
    : "";
  const reviewPill = String(management.review_required).toLowerCase() === "true"
    ? '<span class="pill" data-tone="warning">需人工复核</span>' : "";
  const parsePill = `<span class="pill" data-tone="${manifest.parse_status === "ok" ? "positive" : manifest.parse_status === "no_pdf_in_scope" ? "danger" : "info"}">${escapeHtml(statusLabel(manifest.parse_status))}</span>`;
  const primarySection = management.primary_section_id || "";
  dom["patient-header"].innerHTML = `
    <button class="mobile-cohort-back" type="button" data-show-cohort>← 病例列表</button>
    <div class="patient-title-line">
      <div><h2>${escapeHtml(displayName)}${idSuffix}</h2></div>
      <div class="patient-badges">${managementPill}${reviewPill}${parsePill}</div>
    </div>
    <dl class="patient-stats">
      <div class="patient-stat"><dt>来源文档</dt><dd>${formatNumber(patient.documents.filter((row) => !row.duplicate_of).length)}</dd></div>
      <div class="patient-stat"><dt>章节</dt><dd>${formatNumber(patient.sections.length)}</dd></div>
      <div class="patient-stat"><dt>时间线事件</dt><dd>${formatNumber(patient.timeline.length)}</dd></div>
      <div class="patient-stat"><dt>记录范围</dt><dd>${escapeHtml(formatRange(manifest.earliest_document_date, manifest.latest_document_date))}</dd></div>
      ${management.actual_aaoca_surgery ? `<div class="patient-stat"><dt>实际 AAOCA 手术</dt><dd>${escapeHtml(statusLabel(management.actual_aaoca_surgery))}</dd></div>` : ""}
      ${management.management_confidence ? `<div class="patient-stat"><dt>规则置信度</dt><dd>${escapeHtml(statusLabel(management.management_confidence))}</dd></div>` : ""}
    </dl>
    ${management.observed_management ? `<div class="management-note"><span class="method-chip">规则提取</span>${primarySection ? `<button class="evidence-action" type="button" data-primary-section="${escapeHtml(primarySection)}">主要证据</button>` : ""}</div>` : ""}
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
  if (state.caseTab === "timeline") renderTimelineTab();
  else if (state.caseTab === "documents") renderDocumentsTab();
  else renderSectionsTab();
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
    </button>`).join("") : '<div class="timeline-empty">没有符合当前条件的 section</div>';
}

async function openSection(sectionId) {
  if (!sectionId) return;
  state.selectedSectionId = sectionId;
  if (state.caseTab === "timeline") renderTimelineTab();
  if (state.caseTab === "sections") renderSectionRows();
  dom["inspector-empty"].hidden = true;
  dom["inspector-content"].hidden = false;
  dom["inspector-content"].innerHTML = loadingMarkup(8);
  dom["section-inspector"].classList.add("is-open");
  document.body.classList.add("inspector-open");
  dom["inspector-backdrop"].hidden = window.innerWidth > 1240;
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

function renderInspector() {
  const row = state.section;
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
      <pre class="section-text"></pre>
      <details class="provenance"><summary>查看来源与切分信息</summary><dl>${metadata.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl>${row.page_spans?.length ? `<pre>${escapeHtml(JSON.stringify(row.page_spans, null, 2))}</pre>` : ""}${row.extra_fields && Object.keys(row.extra_fields).length ? `<pre>${escapeHtml(JSON.stringify(row.extra_fields, null, 2))}</pre>` : ""}</details>
    </div>`;
  dom["inspector-content"].querySelector(".section-text").textContent = row.text || "（无正文）";
  requestAnimationFrame(() => dom["inspector-content"].querySelector(".inspector-close")?.focus({ preventScroll: true }));
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
    if (state.caseTab === "timeline") renderTimelineTab();
    if (state.caseTab === "sections") renderSectionRows();
  }
}

init();
