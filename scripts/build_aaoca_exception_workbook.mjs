import fs from "node:fs/promises";
import path from "node:path";

import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const FONT = "Microsoft YaHei";
const COLORS = {
  navy: "#17365D",
  blue: "#1F4E78",
  paleBlue: "#D9EAF7",
  border: "#D9E2F3",
  text: "#1F2937",
  muted: "#5B6573",
  input: "#FFF2CC",
  required: "#F4CCCC",
  high: "#FCE5CD",
  medium: "#FFF2CC",
  good: "#D9EAD3",
  neutral: "#E7E6E6",
};

const CASE_COLUMNS = [
  ["patient_id", "患者ID"],
  ["inpatient_id", "住院号"],
  ["outpatient_id", "门诊号"],
  ["name", "姓名"],
  ["automatic_aaoca_judgment", "自动判断"],
  ["exception_reasons", "例外原因"],
  ["review_priority", "复核优先级"],
  ["automatic_rationale", "自动判断说明"],
  ["relevant_evidence_summary", "相关证据摘要"],
  ["n_evidence_rows", "证据条数"],
  ["n_evidence_sections", "证据section数"],
  ["n_clinical_sections", "临床section数"],
  ["n_pdf", "PDF数"],
  ["patient_parse_status", "患者数据状态"],
  ["evidence_text_sources", "证据文本来源"],
  ["review_status", "复核状态（可编辑）"],
  ["final_aaoca_judgment", "人工最终判断（可编辑）"],
  ["reviewer_notes", "复核备注（可编辑）"],
];

const EVIDENCE_COLUMNS = [
  ["patient_id", "患者ID"],
  ["evidence_id", "证据ID"],
  ["category", "证据类别"],
  ["assertion", "语境判断"],
  ["strength", "规则强度"],
  ["target", "冠脉目标"],
  ["origin", "描述的起源"],
  ["document_id", "文档ID"],
  ["section_id", "Section ID"],
  ["section_type", "Section类型"],
  ["section_subtype", "Section子类型"],
  ["section_date", "Section日期"],
  ["page_start", "起始页"],
  ["page_end", "结束页"],
  ["text_source", "文本来源"],
  ["date_requires_review", "日期需复核"],
  ["parse_status", "解析状态"],
  ["evidence_text", "证据原文"],
  ["source_pdf", "来源PDF"],
  ["text_path", "文本路径"],
  ["text_reference", "文本定位"],
  ["rule_id", "规则ID"],
];

const REASON_LABELS = {
  missing_source_documentation: "缺少可用源文档，无法可靠判断",
  evidence_only_in_nonclinical_or_laboratory_content: "相关词仅见于非临床叙述或检验材料",
  single_evidence_section: "仅一个 section 提供相关证据",
  sparse_nonspecific_label: "证据稀疏且只有非特异标签",
  sparse_ocr_only_evidence: "证据稀疏且仅来自 OCR",
  conflicting_coronary_origin_descriptions: "不同文书存在冠脉起源描述冲突",
  normal_and_abnormal_origin_same_vessel: "同一血管同时出现正常与异常起源描述",
  single_coronary_or_complex_chd_scope_boundary: "单冠脉或复杂先心病的纳入边界需人工确认",
  pulmonary_origin_scope_boundary: "肺动脉起源异常的 AAOCA 范围边界需人工确认",
  high_origin_without_more_specific_anatomy: "仅描述高位起源，缺少更明确解剖信息",
  tentative_evidence_only: "现有证据均为怀疑、待排或鉴别语境",
  normal_origin_and_nonspecific_positive_label: "正常起源描述与非特异阳性标签并存",
};

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    const key = token.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`Missing value for --${key}`);
    result[key] = value;
    index += 1;
  }
  return result;
}

// Small RFC 4180 parser. The source files contain quoted JSON and may contain newlines.
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        field += character;
      }
      continue;
    }
    if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      row.push(field);
      field = "";
    } else if (character === "\n") {
      row.push(field.endsWith("\r") ? field.slice(0, -1) : field);
      rows.push(row);
      row = [];
      field = "";
    } else {
      field += character;
    }
  }
  if (field.length || row.length) {
    row.push(field.endsWith("\r") ? field.slice(0, -1) : field);
    rows.push(row);
  }
  const headers = rows.shift() ?? [];
  return rows
    .filter((values) => values.some((value) => value !== ""))
    .map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])));
}

function excelText(value) {
  if (value === null || value === undefined) return "";
  let text = "";
  for (const character of String(value)) {
    const codePoint = character.codePointAt(0);
    if (
      codePoint === 0x09 ||
      codePoint === 0x0a ||
      codePoint === 0x0d ||
      (codePoint >= 0x20 && codePoint <= 0xd7ff) ||
      (codePoint >= 0xe000 && codePoint <= 0xfffd) ||
      (codePoint >= 0x10000 && codePoint <= 0x10ffff)
    ) {
      text += character;
    } else {
      text += " ";
    }
  }
  return text.length > 32700 ? `${text.slice(0, 32680)}\n[内容过长，已截断]` : text;
}

function parseJsonList(value) {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(excelText) : [excelText(parsed)];
  } catch {
    return [excelText(value)];
  }
}

function numeric(value) {
  if (value === "" || value === null || value === undefined) return "";
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : excelText(value);
}

function caseValue(row, key) {
  if (key === "exception_reasons") return parseJsonList(row[key]).join("\n");
  if (key === "evidence_text_sources") return parseJsonList(row[key]).join("\n");
  if (["n_evidence_rows", "n_evidence_sections", "n_clinical_sections", "n_pdf"].includes(key)) {
    return numeric(row[key]);
  }
  return excelText(row[key]);
}

function evidenceValue(row, key) {
  if (["page_start", "page_end"].includes(key)) return numeric(row[key]);
  return excelText(row[key]);
}

function setBaseFont(sheet, range) {
  range.format.font = { name: FONT, size: 10, color: COLORS.text };
  range.format.verticalAlignment = "top";
}

function styleTitle(sheet, endColumn, title, subtitle) {
  sheet.mergeCells(`A1:${endColumn}1`);
  sheet.getRange("A1").values = [[title]];
  sheet.getRange(`A1:${endColumn}1`).format = {
    fill: COLORS.navy,
    font: { name: FONT, size: 16, bold: true, color: "#FFFFFF" },
    verticalAlignment: "center",
  };
  sheet.getRange(`A1:${endColumn}1`).format.rowHeight = 30;

  sheet.mergeCells(`A2:${endColumn}2`);
  sheet.getRange("A2").values = [[subtitle]];
  sheet.getRange(`A2:${endColumn}2`).format = {
    fill: COLORS.paleBlue,
    font: { name: FONT, size: 10, color: COLORS.muted },
    wrapText: true,
    verticalAlignment: "center",
  };
  sheet.getRange(`A2:${endColumn}2`).format.rowHeight = 35;
}

function addContainsTextFormat(range, text, fill, fontColor = COLORS.text) {
  range.conditionalFormats.add("containsText", {
    text,
    format: { fill, font: { bold: true, color: fontColor } },
  });
}

function buildCasesSheet(workbook, rows, metadata) {
  const sheet = workbook.worksheets.add("例外病例");
  sheet.showGridLines = false;
  sheet.tabColor = COLORS.blue;
  const endRow = 4 + rows.length;
  styleTitle(
    sheet,
    "R",
    "AAOCA 相关性例外病例人工复核",
    `仅列出 ${rows.length} 位例外患者；${metadata.nonexception_patients} 位普通高证据患者未列入本工作簿。黄色三列为人工编辑区。`,
  );

  const matrix = [
    CASE_COLUMNS.map(([, label]) => label),
    ...rows.map((row) => CASE_COLUMNS.map(([key]) => caseValue(row, key))),
  ];
  const tableRange = sheet.getRange(`A4:R${endRow}`);
  tableRange.values = matrix;
  setBaseFont(sheet, tableRange);
  tableRange.format.wrapText = true;
  tableRange.format.borders = { preset: "all", style: "thin", color: COLORS.border };
  sheet.getRange("A4:R4").format = {
    fill: COLORS.blue,
    font: { name: FONT, size: 10, bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
  };
  sheet.getRange("A4:R4").format.rowHeight = 38;
  sheet.getRange(`A5:R${endRow}`).format.rowHeight = 62;
  sheet.getRange(`P5:R${endRow}`).format.fill = COLORS.input;
  sheet.getRange(`P5:P${endRow}`).dataValidation = {
    rule: { type: "list", values: ["not_reviewed", "in_review", "reviewed"] },
  };
  sheet.getRange(`Q5:Q${endRow}`).dataValidation = {
    rule: { type: "list", values: ["yes", "no", "uncertain"] },
  };

  const table = sheet.tables.add(`A4:R${endRow}`, true, "AaocaExceptionCases");
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;
  table.showBandedColumns = false;

  addContainsTextFormat(sheet.getRange(`E5:E${endRow}`), "uncertain", COLORS.required, "#9C0006");
  addContainsTextFormat(sheet.getRange(`E5:E${endRow}`), "yes", COLORS.good, "#006100");
  addContainsTextFormat(sheet.getRange(`G5:G${endRow}`), "required", COLORS.required, "#9C0006");
  addContainsTextFormat(sheet.getRange(`G5:G${endRow}`), "high", COLORS.high, "#9C5700");
  addContainsTextFormat(sheet.getRange(`G5:G${endRow}`), "medium", COLORS.medium, "#7F6000");
  addContainsTextFormat(sheet.getRange(`Q5:Q${endRow}`), "yes", COLORS.good, "#006100");
  addContainsTextFormat(sheet.getRange(`Q5:Q${endRow}`), "no", COLORS.neutral, COLORS.text);
  addContainsTextFormat(sheet.getRange(`Q5:Q${endRow}`), "uncertain", COLORS.medium, "#7F6000");

  const widths = [24, 14, 14, 12, 11, 34, 12, 52, 72, 10, 12, 12, 8, 20, 22, 18, 22, 45];
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, endRow, 1).format.columnWidth = width;
  });
  sheet.getRange(`J5:M${endRow}`).format.horizontalAlignment = "center";
  sheet.freezePanes.freezeRows(4);
  sheet.freezePanes.freezeColumns(4);
  return { name: "例外病例", endRow };
}

function buildEvidenceSheet(workbook, rows, caseIds) {
  const sheet = workbook.worksheets.add("证据");
  sheet.showGridLines = false;
  sheet.tabColor = "#4472C4";
  const endRow = 4 + rows.length;
  styleTitle(
    sheet,
    "V",
    "例外病例相关证据与原始定位",
    `共 ${rows.length} 条证据；只包含“例外病例”工作表中的患者。可按患者ID、语境、文档或 section 筛选并回溯原始 PDF/结构化文本。`,
  );
  const matrix = [
    EVIDENCE_COLUMNS.map(([, label]) => label),
    ...rows.map((row) => EVIDENCE_COLUMNS.map(([key]) => evidenceValue(row, key))),
  ];
  const tableRange = sheet.getRange(`A4:V${endRow}`);
  tableRange.values = matrix;
  setBaseFont(sheet, tableRange);
  tableRange.format.wrapText = true;
  tableRange.format.borders = { preset: "all", style: "thin", color: COLORS.border };
  sheet.getRange("A4:V4").format = {
    fill: "#4472C4",
    font: { name: FONT, size: 10, bold: true, color: "#FFFFFF" },
    wrapText: true,
    verticalAlignment: "center",
  };
  sheet.getRange("A4:V4").format.rowHeight = 38;
  sheet.getRange(`A5:V${endRow}`).format.rowHeight = 58;
  const table = sheet.tables.add(`A4:V${endRow}`, true, "AaocaExceptionEvidence");
  table.style = "TableStyleMedium9";
  table.showFilterButton = true;

  addContainsTextFormat(sheet.getRange(`D5:D${endRow}`), "uncertain", COLORS.medium, "#7F6000");
  addContainsTextFormat(sheet.getRange(`D5:D${endRow}`), "negated", COLORS.neutral, COLORS.text);
  addContainsTextFormat(sheet.getRange(`D5:D${endRow}`), "affirmed", COLORS.good, "#006100");

  const widths = [24, 22, 18, 12, 12, 20, 18, 25, 31, 18, 18, 13, 9, 9, 14, 12, 15, 78, 58, 40, 18, 24];
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, endRow, 1).format.columnWidth = width;
  });
  sheet.getRange(`M5:N${endRow}`).format.horizontalAlignment = "center";
  sheet.freezePanes.freezeRows(4);
  sheet.freezePanes.freezeColumns(1);

  const evidenceCaseIds = new Set(rows.map((row) => row.patient_id));
  const unexpected = [...evidenceCaseIds].filter((patientId) => !caseIds.has(patientId));
  if (unexpected.length) throw new Error(`Evidence contains non-exception patients: ${unexpected.join(", ")}`);
  return { name: "证据", endRow };
}

function buildGuideSheet(workbook, metadata) {
  const sheet = workbook.worksheets.add("说明");
  sheet.showGridLines = false;
  sheet.tabColor = "#70AD47";
  setBaseFont(sheet, sheet.getRange("A1:F100"));
  styleTitle(
    sheet,
    "F",
    "AAOCA 例外病例复核说明",
    "复核问题：患者整个诊疗过程中，AAOCA 或相应冠状动脉异常是否曾成为实际被考虑、怀疑、检查、讨论、鉴别或排除的诊疗方向？",
  );
  sheet.getRange("A4:B11").values = [
    ["交付范围", "仅例外患者；普通高证据患者不会出现在病例表和证据表中"],
    ["源数据患者", metadata.patients_total],
    ["例外患者", metadata.exception_patients],
    ["普通患者（已省略）", metadata.nonexception_patients],
    ["自动判断 yes", metadata.automatic_judgments_all_patients?.yes ?? 0],
    ["自动判断 uncertain", metadata.automatic_judgments_all_patients?.uncertain ?? 0],
    ["例外证据条数", metadata.evidence_rows_for_exceptions],
    ["规则版本", metadata.ruleset_version],
  ];
  sheet.getRange("A4:A11").format = {
    fill: COLORS.paleBlue,
    font: { name: FONT, size: 10, bold: true, color: COLORS.navy },
  };
  sheet.getRange("A4:B11").format.borders = { preset: "all", style: "thin", color: COLORS.border };
  sheet.getRange("A4:B11").format.wrapText = true;

  sheet.mergeCells("D4:F4");
  sheet.getRange("D4").values = [["人工复核步骤"]];
  sheet.getRange("D4:F4").format = {
    fill: COLORS.blue,
    font: { name: FONT, size: 11, bold: true, color: "#FFFFFF" },
  };
  sheet.getRange("D5:F9").values = [
    ["1", "先看例外原因", "理解为什么该患者没有被自动直通。"],
    ["2", "再看证据摘要", "必要时按患者ID到“证据”表查看全部上下文与定位。"],
    ["3", "更新复核状态", "not_reviewed → in_review → reviewed。"],
    ["4", "填写最终判断", "仅在 review_status=reviewed 时填写 yes / no / uncertain。"],
    ["5", "记录理由", "冲突、范围边界或资料不足时，在复核备注中说明判断依据。"],
  ];
  sheet.getRange("D5:F9").format.wrapText = true;
  sheet.getRange("D5:F9").format.borders = { preset: "all", style: "thin", color: COLORS.border };
  sheet.getRange("D5:D9").format = {
    fill: COLORS.input,
    font: { name: FONT, size: 11, bold: true, color: COLORS.navy },
    horizontalAlignment: "center",
  };

  sheet.mergeCells("A13:F13");
  sheet.getRange("A13").values = [["例外原因代码"]];
  sheet.getRange("A13:F13").format = {
    fill: COLORS.blue,
    font: { name: FONT, size: 11, bold: true, color: "#FFFFFF" },
  };
  const reasonRows = Object.entries(REASON_LABELS).map(([code, label]) => [
    code,
    label,
    metadata.exception_reason_counts?.[code] ?? 0,
  ]);
  const reasonEnd = 14 + reasonRows.length;
  sheet.getRange(`A14:C${reasonEnd}`).values = [["代码", "人工解释", "病例数（可重叠）"], ...reasonRows];
  sheet.getRange("A14:C14").format = {
    fill: "#4472C4",
    font: { name: FONT, size: 10, bold: true, color: "#FFFFFF" },
  };
  sheet.getRange(`A14:C${reasonEnd}`).format.borders = { preset: "all", style: "thin", color: COLORS.border };
  sheet.getRange(`A14:C${reasonEnd}`).format.wrapText = true;

  const sourceStart = reasonEnd + 2;
  sheet.mergeCells(`A${sourceStart}:F${sourceStart}`);
  sheet.getRange(`A${sourceStart}`).values = [["口径依据与质量边界"]];
  sheet.getRange(`A${sourceStart}:F${sourceStart}`).format = {
    fill: COLORS.blue,
    font: { name: FONT, size: 11, bold: true, color: "#FFFFFF" },
  };
  const sourceRows = [
    ["判断口径", "“yes”表示 AAOCA/对应冠状动脉异常曾实际进入诊疗过程，不等于最终确诊。后续排除仍可判 yes。"],
    ["自动结果边界", "规则结果用于分流；冲突、资料缺失和范围边界病例必须由人工结合原文判断。"],
    ["隐私", "本工作簿含姓名、住院号、门诊号和原始路径，仅限获授权的本地临床复核。"],
    ["源数据", metadata.source_run],
    ["AATS 专家共识", "https://pubmed.ncbi.nlm.nih.gov/28274557/?dopt=Abstract"],
    ["ESC 成人先心病指南", "https://academic.oup.com/eurheartj/article/42/6/563/5898606"],
    ["ASE 多模态影像指南", "https://www.asecho.org/wp-content/uploads/2020/03/ConCoronary_March2020.pdf"],
    ["冠状动脉异常标准命名", "https://www.jacc.org/doi/10.1016/j.jcmg.2026.02.005"],
  ];
  const sourceEnd = sourceStart + sourceRows.length;
  sheet.getRange(`A${sourceStart + 1}:B${sourceEnd}`).values = sourceRows;
  sheet.getRange(`A${sourceStart + 1}:A${sourceEnd}`).format = {
    fill: COLORS.paleBlue,
    font: { name: FONT, size: 10, bold: true, color: COLORS.navy },
  };
  sheet.getRange(`A${sourceStart + 1}:B${sourceEnd}`).format.borders = {
    preset: "all",
    style: "thin",
    color: COLORS.border,
  };
  sheet.getRange(`A${sourceStart + 1}:B${sourceEnd}`).format.wrapText = true;

  const widths = [43, 76, 18, 8, 25, 55];
  widths.forEach((width, index) => {
    sheet.getRangeByIndexes(0, index, sourceEnd, 1).format.columnWidth = width;
  });
  sheet.getRange(`A4:F${sourceEnd}`).format.rowHeight = 31;
  sheet.getRange(`A15:C${reasonEnd}`).format.rowHeight = 38;
  sheet.getRange(`A${sourceStart + 1}:B${sourceEnd}`).format.rowHeight = 42;
  sheet.freezePanes.freezeRows(2);
  return { name: "说明", endRow: sourceEnd };
}

async function savePreview(workbook, sheetName, range, outputPath) {
  const preview = await workbook.render({ sheetName, range, scale: 1.2, format: "png" });
  await fs.writeFile(outputPath, new Uint8Array(await preview.arrayBuffer()));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const inputDir = path.resolve(args.input ?? "data/review/aaoca_exception_review_v1");
  const outputPath = path.resolve(args.output ?? path.join(inputDir, "AAOCA_exception_review.xlsx"));
  const previewDir = path.resolve(args["preview-dir"] ?? path.join("temp", "aaoca_exception_workbook_preview"));
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.mkdir(previewDir, { recursive: true });

  const [caseText, evidenceText, metadataText] = await Promise.all([
    fs.readFile(path.join(inputDir, "exception_cases.csv"), "utf8"),
    fs.readFile(path.join(inputDir, "exception_evidence.csv"), "utf8"),
    fs.readFile(path.join(inputDir, "run_metadata.json"), "utf8"),
  ]);
  const cases = parseCsv(caseText.replace(/^\uFEFF/, ""));
  const evidence = parseCsv(evidenceText.replace(/^\uFEFF/, ""));
  const metadata = JSON.parse(metadataText.replace(/^\uFEFF/, ""));
  if (metadata.human_deliverable_scope !== "exception_patients_only") {
    throw new Error("Refusing to build a workbook whose scope is not exception_patients_only");
  }
  if (cases.length !== metadata.exception_patients) {
    throw new Error(`Case count mismatch: CSV=${cases.length}, metadata=${metadata.exception_patients}`);
  }
  if (evidence.length !== metadata.evidence_rows_for_exceptions) {
    throw new Error(`Evidence count mismatch: CSV=${evidence.length}, metadata=${metadata.evidence_rows_for_exceptions}`);
  }
  const caseIds = new Set(cases.map((row) => row.patient_id));
  if (caseIds.size !== cases.length) throw new Error("Duplicate patient_id values in exception_cases.csv");

  const workbook = Workbook.create();
  const casesSheet = buildCasesSheet(workbook, cases, metadata);
  const evidenceSheet = buildEvidenceSheet(workbook, evidence, caseIds);
  const guideSheet = buildGuideSheet(workbook, metadata);

  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);

  const saved = await FileBlob.load(outputPath);
  const reopened = await SpreadsheetFile.importXlsx(saved);
  const inspections = {};
  for (const [sheetName, range] of [
    [casesSheet.name, "A1:R12"],
    [evidenceSheet.name, "A1:V10"],
    [guideSheet.name, `A1:F${Math.min(guideSheet.endRow, 45)}`],
  ]) {
    const inspected = await reopened.inspect({
      kind: "region",
      sheetId: sheetName,
      range,
      include: "values,formulas",
      tableMaxRows: 12,
      tableMaxCols: 22,
      maxChars: 8000,
    });
    inspections[sheetName] = inspected.ndjson;
  }
  const errors = await reopened.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
    options: { useRegex: true, maxResults: 300 },
    summary: "final formula error scan",
  });

  await savePreview(reopened, casesSheet.name, "A1:R18", path.join(previewDir, "cases.png"));
  await savePreview(reopened, evidenceSheet.name, "A1:V14", path.join(previewDir, "evidence.png"));
  await savePreview(
    reopened,
    guideSheet.name,
    `A1:F${guideSheet.endRow}`,
    path.join(previewDir, "guide.png"),
  );

  const verification = {
    output: outputPath,
    cases: cases.length,
    evidence_rows: evidence.length,
    omitted_nonexception_patients: metadata.nonexception_patients,
    sheets: [casesSheet.name, evidenceSheet.name, guideSheet.name],
    previews: ["cases.png", "evidence.png", "guide.png"].map((name) => path.join(previewDir, name)),
    formula_error_scan: errors.ndjson,
    inspected_ranges: Object.keys(inspections),
  };
  await fs.writeFile(
    path.join(previewDir, "verification.json"),
    JSON.stringify({ ...verification, inspections }, null, 2),
    "utf8",
  );
  // artifact-tool may spill large inspect results beside the workbook. Keep the
  // human review directory limited to the actual review deliverables.
  await fs.rm(`${outputPath}.inspect.ndjson`, { force: true });
  process.stdout.write(`${JSON.stringify(verification, null, 2)}\n`);
}

await main();
