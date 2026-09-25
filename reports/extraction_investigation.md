# PDF extraction and local OCR investigation — v0.1

This report contains aggregate measurements and anonymous document/page indices only. Patient text, names, identifiers and filenames are restricted to local derived artifacts. All inference ran locally. No patient content was sent to an API, and no LLM was used.

## What the PDFs actually contain

The source has two sharply different export families. Across the 342 unique PDF contents, all **198 PDFs with unusable Chinese text layers** report `Chrome Helper` as creator and macOS Quartz as producer. All **142 clean text-layer PDFs** report Safari as creator and macOS Quartz as producer. There is also one empty/zero-page PDF and one partial PDF.

The failing files are not ordinary broken font maps. On representative clinical and laboratory pages:

- PyMuPDF, pypdf and pdfplumber all returned zero Chinese characters while retaining Latin text and numbers.
- The visible Chinese glyphs are `fill-path` vector outlines. Fonts with valid `ToUnicode` maps still cover only the remaining text; they do not contain the visible Chinese prose.
- The PDF has no `ActualText`, marked-content IDs, accessibility structure tree or hidden Chinese layer that could restore the semantics.
- A representative Chrome/Quartz page exposed only embedded Arial and FontAwesome fonts, with the Chinese content represented by anonymous paths. A corresponding Safari export uses embedded PingFang fonts and extractable Chinese text.

This rules out recovering the prose by changing text-extraction libraries or repairing a `ToUnicode` CMap. Re-exporting the original hospital webpage through Safari would likely give a true text layer, but the current dataset contains only the PDFs. Vector-shape glyph classification was briefly tested as a possible custom decoder: repeated outlines are highly reusable inside a document, but a complete Unicode mapping is absent and uncommon clinical glyphs would still require a labeled recognizer. The project therefore uses targeted local OCR, as selected for v0.1.

## Direct text extraction

`extract_pdf()` uses PyMuPDF and keeps one record per original page. It disables MediaBox clipping because real exports contain text spans outside the nominal printed page. A normal sample page increased from 621 to 686 recoverable Chinese characters when full-page coordinates were retained, matching the other two extractors. Off-page recovery is flagged rather than silently treated as ordinary visible text.

Each page retains:

- raw extracted text and line/span coordinates;
- raw character and Chinese-character counts;
- page dimensions and paint-operation diagnostics;
- image-area and character-sized-vector-path evidence;
- extraction status and flags;
- `ocr_recommended`, without running OCR in the extraction function.

The document status distinguishes `ok`, `partial`, `text_layer_unusable`, `empty` and `failed`. Nonempty digits cannot make an outlined-Chinese page pass. A pypdf fallback is used only if the primary parser raises on a page; repeatedly applying other text parsers cannot reconstruct path outlines.

On the 23-PDF sample, the implemented extractor processed **805 pages**, with **10 PDFs / 495 pages** requiring OCR and **13 PDFs / 306 pages** passing the direct-text rules. Two pages were blank and two were partial. Raw text totaled 523,191 characters; conservative normalization produced 489,117 characters while retaining the raw representation.

## Normalization

Normalization is page-preserving and reversible. It applies Unicode NFKC, horizontal-space cleanup and blank-line compression, then removes only allowlisted browser title/URL/page-number/private-use icon lines in their observed margin positions. It does not frequency-delete repeated clinical titles. Every removed line records its original number, exact local text and reason. OCR text, when present, becomes a separate `analysis_text`/`normalized_text` source; it never overwrites `page.text` from the PDF.

## Local OCR choice

RapidOCR 3.9.2 with ONNX Runtime CPU was tested with PP-OCR v4, v5 and v6 models at 2× rendering. The benchmark used 12 fixed pages spanning native-text controls, outlined clinical prose and outlined laboratory tables, plus a separate progress-note control. Network calls were blocked during inference. All model files are pinned by SHA256 and loaded from `models/` before any patient PDF is opened.

| Model | 12-page median seconds/page | Total seconds | Native-control CJK bag recall | Geometry-aligned CJK CER proxy |
|---|---:|---:|---:|---:|
| PP-OCR v6 | 4.052 | 45.623 | 0.9970 | 0.1202 |
| PP-OCR v5 | 4.813 | 61.108 | 0.9909 | 0.1237 |
| PP-OCR v4 | 7.556 | 95.612 | 0.9931 | 0.1259 |

These are engineering proxies against six pages that already had extractable text, not a clinical accuracy estimate. OCR can read labels or image content absent from the native text reference, and text-line geometry differs between representations; this inflates an edit-distance proxy even when characters are recognizable. The six outlined pages have no independent gold transcription. PP-OCR v6 was selected because it was fastest and had the best aggregate proxy results in this small comparison.

An initial unloaded four-page probe took 1.21–2.39 seconds per page. Two outlined clinical pages recovered 244 and 880 Chinese characters; one normal-text control recovered 647. The outlined laboratory page had 19 of 120 detected lines below 0.8 model confidence, demonstrating that table cell relationships require separate validation. Model confidence is not calibrated clinical accuracy.

## Full OCR execution

The first complete local OCR pass scheduled **8,216 pages from 199 PDFs**, used four worker processes with two ONNX CPU threads each, and wrote an atomic per-document cache. It recovered nonempty text on **8,202 pages**; **14 pages** remained empty. Wall time was **8,796.803 seconds** including PDF rasterization, inference and initial downstream output construction. Subsequent matching/date/segmentation/QC iterations reuse the OCR cache.

OCR output preserves line polygons, bounding boxes, model confidence, low-confidence flags, raster size, method and model hashes. Its status remains `partial` and `local_ocr_unverified`; it is never promoted to native-text `ok`. Laboratory rows are retained as geometry-bearing text lines, but v0.1 does not claim analyte/value/unit cell reconstruction.

## Failure modes retained for QC

1. Vector-outlined Chinese with meaningful numbers/Latin text still present.
2. Blank or visually nonblank pages with no recoverable OCR line.
3. Numeric laboratory tables with little Chinese, which must not fail only on CJK ratio.
4. OCR low-confidence lines, especially dense tables, superscripts and small units.
5. OCR line-order or whitespace changes, including joined date and time tokens.
6. Text outside the PDF MediaBox that ordinary extraction clips.
7. Image labels read by OCR but absent from a native-text control, complicating automatic comparison.
8. A successful OCR pass that is still not a validated clinical transcription.

The benchmark and private per-page OCR payloads remain under ignored `scratch/` and `data/derived/` paths. The reusable public pipeline contains only local processing code, model manifests, aggregate reports and synthetic tests.
