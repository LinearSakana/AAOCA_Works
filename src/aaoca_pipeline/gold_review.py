"""Loopback-only review desk for page-anchored gold annotations."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlparse

import fitz

from .gold_common import (SCHEMA, complete_run, load_annotations, read_json,
                          source_documents, validate_annotation, write_json)


HTML = """<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AAOCA Gold Review</title><link rel="stylesheet" href="/style.css"></head><body>
<header><h1>Gold Set 人工核验</h1><span id="progress"></span><button id="previous">上一页</button><button id="next">下一页</button></header>
<div id="message" role="status"></div><main><aside><h2>原始 PDF 切片</h2><p id="source"></p>
<div class="pdf-navigation"><button id="pdf-previous">PDF 前一页</button><span id="pdf-page-label"></span><button id="pdf-next">PDF 后一页</button><button id="pdf-current">回样本页</button></div>
<img id="pdf" alt="原始 PDF 当前页"></aside>
<article><h2 id="unit"></h2><p>先核对 PDF，再修改文字与分段。下方字段预填的是 parser 预测，只有您核对后保存为“完成”才会进入金标准。</p>
<details><summary>原生提取文字 / OCR 原文 / 标准化文字</summary><h3>原生文字层</h3><pre id="raw"></pre><h3>OCR 原文</h3><pre id="ocr"></pre><h3>当前 normalized text</h3><pre id="normalized"></pre></details>
<h3>当前 parser 预测</h3><div id="predictions"></div>
<h3>人工校正后的整页文字</h3><p>按 PDF 阅读顺序逐行记录可见临床内容；保留标题、日期和数值。浏览器导航与打印页眉可略去。编辑后请检查下方行号与 section 范围。</p>
<label>文字核验状态 <select id="text-status"><option value="ok">与 PDF 一致</option><option value="corrected">已修正</option><option value="uncertain">无法可靠转录</option></select></label>
<label>文字错误的临床影响 <select id="text-impact"><option value="unknown">无法判断</option><option value="low">低</option><option value="moderate">中</option><option value="high">高</option></select></label>
<textarea id="gold-text" spellcheck="false"></textarea><details open><summary>带行号的人工文字</summary><pre id="line-preview"></pre></details>
<h3>人工 section</h3><p>同一页的所有非空文字行必须恰好属于一个 section。跨页 section 在本页只标本页范围；页边界不计入 boundary 指标。</p>
<div id="sections"></div><button id="add-section">增加 section</button>
<h3>整页备注</h3><textarea id="notes" placeholder="无法判断、PDF 模糊、现有 schema 无法表达等"></textarea>
<label>核验人姓名或代号 <input id="reviewer" placeholder="例如 reviewer_01"></label>
<p><label><input type="checkbox" id="confirmed"> 我已对照原始 PDF 核查文字、所有 section 边界、type/subtype、日期及可能混淆的其他日期</label></p>
<div class="actions"><button id="save-draft">保存草稿</button><button id="save-complete">完成本页</button><button id="unreviewable">标记无法核验</button></div></article></main>
<script src="/app.js"></script></body></html>"""

CSS = """body{font:15px system-ui,sans-serif;margin:0;color:#182238;background:#f4f6f8}header{display:flex;align-items:center;gap:1rem;background:#152943;color:white;padding:.65rem 1rem;position:sticky;top:0;z-index:3}h1{font-size:1.15rem;margin:0}button{padding:.5rem .8rem;cursor:pointer;border:1px solid #8295a4;border-radius:4px;background:#fff}button:hover{background:#e5f2fc}#message{padding:.4rem 1rem;min-height:1.3rem;color:#8b2100}main{display:grid;grid-template-columns:minmax(380px,50%) 1fr;gap:1rem;padding:1rem}aside,article{background:white;padding:1rem;border-radius:6px;min-width:0}aside{position:sticky;top:4.3rem;height:calc(100vh - 6rem);overflow:auto}#pdf{width:100%;height:auto;border:1px solid #aaa}#source{overflow-wrap:anywhere;font-size:.85rem}.pdf-navigation{display:flex;flex-wrap:wrap;gap:.3rem;align-items:center;margin:.5rem 0}.pdf-navigation button{padding:.3rem}.pdf-navigation span{font-weight:600}textarea{box-sizing:border-box;width:100%;min-height:5rem;font:13px ui-monospace,monospace;padding:.55rem}#gold-text{height:20rem}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f5f8;padding:.55rem;max-height:18rem;overflow:auto}#line-preview{max-height:14rem}.section{border:1px solid #b6c6d1;border-radius:5px;padding:.7rem;margin:.7rem 0;background:#fbfdfe}.section-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.6rem}.section label{display:flex;flex-direction:column;gap:.2rem}.section input,.section select{padding:.35rem;min-width:0}.section textarea{min-height:3rem}.prediction{padding:.4rem;border-bottom:1px solid #ddd}.actions{display:flex;gap:.7rem;margin:1rem 0}details{margin:.7rem 0}summary{cursor:pointer}@media(max-width:1000px){main{display:block}aside{position:static;height:auto;margin-bottom:1rem}}"""

JS = r"""'use strict';
const token=new URLSearchParams(location.search).get('token');
let data, unitIndex=0, sectionRows=[], shownPdfPage=1;
const $=id=>document.getElementById(id);
function el(tag,attrs={},txt=''){const x=document.createElement(tag);for(const [k,v] of Object.entries(attrs))x.setAttribute(k,v);if(txt)x.textContent=txt;return x;}
function optionSelect(values,value){const x=el('select');for(const [key,label] of values){const y=el('option',{value:key},label);x.append(y);}x.value=value||values[0][0];return x;}
const statuses=[['known','已确定'],['uncertain','无法判断'],['schema_gap','schema 无法表达']];
const dateStatuses=[['known','已确定'],['absent','确认没有 event date'],['uncertain','无法判断'],['schema_gap','schema 无法表达']];
const types=['admission','administrative','consultation','discharge','laboratory','nonclinical','outpatient','procedure','progress','unknown'].map(x=>[x,x]);
const roles=['document','test','specimen','performed_procedure','other'].map(x=>[x,x]);
const impacts=['unknown','low','moderate','high'].map(x=>[x,x]);
function field(parent,label,node){const w=el('label');w.append(el('span',{},label),node);parent.append(w);return node;}
function sectionForm(section={}){
 const root=el('div',{class:'section'}), grid=el('div',{class:'section-grid'});root.append(grid);
 const a=section.type||{status:'known',value:'unknown'},b=section.subtype||{status:'uncertain',value:''},d=section.date||{status:'uncertain',value:'',role:'document',other_dates:[]};
 const start=field(grid,'起始行',el('input',{type:'number',min:'1',value:section.start_line||1}));
 const end=field(grid,'结束行',el('input',{type:'number',min:'1',value:section.end_line||1}));
 const typeStatus=field(grid,'Type 判断',optionSelect(statuses,a.status));
 const typeValue=field(grid,'Type',optionSelect(types,a.value));
 const subStatus=field(grid,'Subtype 判断',optionSelect(statuses,b.status));
 const subValue=field(grid,'Subtype',el('input',{value:b.value||'',placeholder:'可为空字符串'}));
 const dateStatus=field(grid,'Event date 判断',optionSelect(dateStatuses,d.status));
 const dateValue=field(grid,'Event date YYYY-MM-DD',el('input',{type:'date',value:d.value||''}));
 const dateRole=field(grid,'Event date 的语义',optionSelect(roles,d.role));
 const impact=field(grid,'错误若存在的临床影响',optionSelect(impacts,section.impact));
 const evidence=field(root,'日期证据（PDF 中的原文）',el('input',{value:d.evidence||''}));
 const other=field(root,'其他日期：每行 YYYY-MM-DD | role | 证据；role 可为 print, historical, planned_procedure, specimen 等',el('textarea'));
 other.value=(d.other_dates||[]).map(x=>`${x.value} | ${x.role} | ${x.evidence||''}`).join('\n');
 const note=field(root,'Section 备注',el('textarea'));note.value=section.notes||'';
 const remove=el('button',{type:'button'},'删除此 section');remove.onclick=()=>{sectionRows=sectionRows.filter(x=>x.root!==root);root.remove();};root.append(remove);
 return {root,read(){const other_dates=other.value.split('\n').filter(x=>x.trim()).map(line=>{const parts=line.split('|').map(x=>x.trim());return {value:parts[0]||'',role:parts[1]||'',evidence:parts.slice(2).join(' | ')}});return {start_line:Number(start.value),end_line:Number(end.value),type:{status:typeStatus.value,value:typeValue.value},subtype:{status:subStatus.value,value:subValue.value},date:{status:dateStatus.value,value:dateStatus.value==='known'?dateValue.value:'',role:dateRole.value,evidence:evidence.value,other_dates},impact:impact.value,notes:note.value}}};}
function addSection(section){const row=sectionForm(section);sectionRows.push(row);$('sections').append(row.root);}
function updateLines(){$('line-preview').textContent=$('gold-text').value.split('\n').map((x,i)=>`${String(i+1).padStart(3)}  ${x}`).join('\n');}
function showPdfPage(number){if(!data)return;shownPdfPage=Math.max(1,Math.min(data.page_count,number));$('pdf-page-label').textContent=`第 ${shownPdfPage}/${data.page_count} 页${shownPdfPage===data.unit.page?'（样本页）':'（上下文）'}`;$('pdf').src=`/pdf/${unitIndex}?page=${shownPdfPage}&token=${encodeURIComponent(token)}`;$('pdf-previous').disabled=shownPdfPage<=1;$('pdf-next').disabled=shownPdfPage>=data.page_count;}
async function api(path,options={}){const url=path+(path.includes('?')?'&':'?')+'token='+encodeURIComponent(token);const r=await fetch(url,{cache:'no-store',...options});const v=await r.json();if(!r.ok)throw Error(v.error||r.statusText);return v;}
async function load(index){try{const info=await api('/api/unit/'+index);data=info;unitIndex=index;$('message').textContent='';$('unit').textContent=`${index+1}/${info.total} · ${info.unit.unit_id} · ${info.unit.stratum} · PDF 第 ${info.unit.page} 页`;$('progress').textContent=`已完成 ${info.completed}/${info.total} 页`;
 $('source').textContent=`原始 PDF: ${info.source_pdf}；SHA256: ${info.unit.source_sha256}`;
 showPdfPage(info.unit.page);
 $('raw').textContent=info.raw_text;$('ocr').textContent=info.ocr_text;$('normalized').textContent=info.normalized_text;
 const pred=$('predictions');pred.replaceChildren();for(const p of info.predictions){pred.append(el('div',{class:'prediction'},`行 ${p.start_line}–${p.end_line} · ${p.section_type}/${p.section_subtype||'∅'} · ${p.section_date||'无日期'} · ${p.date_source||'无来源'} · ${p.section_id}`));}
 const a=info.annotation;$('text-status').value=a.text.status;$('text-impact').value=a.text.impact||'unknown';$('gold-text').value=a.text.gold_text;$('notes').value=a.notes||'';$('reviewer').value=a.reviewer||'';$('confirmed').checked=false;
 sectionRows=[];$('sections').replaceChildren();for(const s of a.sections)addSection(s);updateLines();
 }catch(e){$('message').textContent=String(e);}}
async function save(status){if(status==='complete'&&!$('confirmed').checked){$('message').textContent='请先勾选核查确认。';return;}
 const annotation={...data.annotation,status,schema_version:data.annotation.schema_version,reviewer:$('reviewer').value.trim(),text:{status:$('text-status').value,impact:$('text-impact').value,gold_text:$('gold-text').value},sections:sectionRows.map(x=>x.read()),notes:$('notes').value,reviewed_at:new Date().toISOString()};
 try{const r=await api('/api/save/'+unitIndex,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(annotation)});$('message').textContent=`已保存 ${status}。${r.completed}/${r.total} 页完成。`;data.annotation=annotation;$('progress').textContent=`已完成 ${r.completed}/${r.total} 页`;}catch(e){$('message').textContent=String(e);}}
document.addEventListener('DOMContentLoaded',()=>{$('gold-text').oninput=updateLines;$('add-section').onclick=()=>addSection({start_line:1,end_line:1});$('previous').onclick=()=>load(Math.max(0,unitIndex-1));$('next').onclick=()=>load(Math.min(data.total-1,unitIndex+1));$('pdf-previous').onclick=()=>showPdfPage(shownPdfPage-1);$('pdf-next').onclick=()=>showPdfPage(shownPdfPage+1);$('pdf-current').onclick=()=>showPdfPage(data.unit.page);$('save-draft').onclick=()=>save('draft');$('save-complete').onclick=()=>save('complete');$('unreviewable').onclick=()=>save('unreviewable');load(0);});
"""


def _seed(unit: dict, normalized_page: dict, predictions: list[dict], sample_id: str) -> dict:
    sections = []
    for pred in predictions:
        start, end = pred["start_line"], pred["end_line"]
        if not any(line.strip() for line in normalized_page.get("normalized_text", "").splitlines()[start - 1:end]):
            continue
        date_value = pred.get("section_date") or ""
        date_source = pred.get("date_source", "")
        role = "test" if "test_timestamp" in date_source else "document"
        sections.append({"start_line": start, "end_line": end,
                         "type": {"status": "known", "value": pred.get("section_type", "unknown")},
                         "subtype": {"status": "known", "value": pred.get("section_subtype", "")},
                         "date": {"status": "known" if date_value else "uncertain", "value": date_value,
                                  "role": role, "evidence": pred.get("date_evidence", ""), "other_dates": []},
                         "impact": "unknown", "notes": ""})
    return {"schema_version": SCHEMA, "sample_id": sample_id, "unit_id": unit["unit_id"],
            "source_sha256": unit["source_sha256"], "page": unit["page"],
            "status": "draft", "reviewer": "", "reviewed_at": "", "notes": "",
            "text": {"status": "ok", "impact": "unknown", "gold_text": normalized_page.get("normalized_text", "")},
            "sections": sections}


def serve(gold_dir: Path, output: Path, port: int = 8765) -> None:
    metadata = complete_run(output)
    manifest, annotations = load_annotations(gold_dir)
    if metadata["run_id"] != manifest["source_run"]["run_id"]:
        raise ValueError("Review desk must use the same baseline run used for sampling")
    if hashlib.sha256((output / "run_metadata.json").read_bytes()).hexdigest() != manifest["source_run"]["run_metadata_sha256"]:
        raise ValueError("Baseline run receipt changed since sampling")
    docs = source_documents(output)
    units = manifest["units"]
    if any(u["source_sha256"] not in docs for u in units):
        raise ValueError("Baseline output is missing a sampled PDF")
    token = secrets.token_urlsafe(28)
    checked_sources = set()

    def material(index: int):
        unit = units[index]
        doc = docs[unit["source_sha256"]]
        source = Path(doc["source_pdf"])
        if unit["source_sha256"] not in checked_sources:
            if hashlib.sha256(source.read_bytes()).hexdigest() != unit["source_sha256"]:
                raise ValueError("Original PDF hash changed")
            checked_sources.add(unit["source_sha256"])
        normalized = read_json(output / doc["text_path"].replace(".txt", ".json"))
        page = next(p for p in normalized["pages"] if p["page"] == unit["page"])
        section_payload = read_json(output / doc["sections_path"])
        predictions = []
        for section in section_payload["sections"]:
            span = next((s for s in section["page_spans"] if s["page"] == unit["page"]), None)
            if span:
                predictions.append({"start_line": span["start_line"], "end_line": span["end_line"],
                                    **{key: section.get(key, "") for key in
                                       ("section_id", "section_type", "section_subtype", "section_date", "date_source", "date_evidence")}})
        return unit, doc, source, page, predictions

    class Handler(BaseHTTPRequestHandler):
        def send(self, body: bytes, content_type: str, status: int = 200):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; script-src 'self'; style-src 'self'")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, value: dict, status: int = 200):
            self.send(json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def route(self, post: bool = False):
            parsed = urlparse(self.path)
            if not post and parsed.path == "/favicon.ico":
                return self.send(b"", "image/x-icon")
            if parse_qs(parsed.query).get("token") != [token] or self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                return self.send_json({"error": "Unauthorized"}, 403)
            path = parsed.path
            try:
                if not post and path in {"/", "/app.js", "/style.css"}:
                    body, kind = {"/": (HTML, "text/html"), "/app.js": (JS, "application/javascript"),
                                  "/style.css": (CSS, "text/css")}[path]
                    if path == "/":
                        body = body.replace('/style.css"', f'/style.css?token={token}"').replace(
                            '/app.js"', f'/app.js?token={token}"')
                    return self.send(body.encode("utf-8"), kind + "; charset=utf-8")
                prefix = "/api/save/" if post else "/api/unit/" if path.startswith("/api/unit/") else "/pdf/"
                if not path.startswith(prefix) or not path[len(prefix):].isdigit():
                    return self.send_json({"error": "Unknown route"}, 404)
                index = int(path[len(prefix):])
                if index < 0 or index >= len(units):
                    return self.send_json({"error": "Unknown page"}, 404)
                unit, doc, source, page, predictions = material(index)
                if post:
                    if self.headers.get("Origin") != f"http://127.0.0.1:{port}" or int(self.headers.get("Content-Length", 0)) > 2_000_000:
                        return self.send_json({"error": "Invalid request origin or size"}, 403)
                    annotation = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    errors = validate_annotation(annotation, unit, manifest["sample_id"])
                    if errors:
                        return self.send_json({"error": "; ".join(errors)}, 400)
                    write_json(gold_dir / "annotations" / f"{unit['unit_id']}.json", annotation)
                    annotations[unit["unit_id"]] = annotation
                    return self.send_json({"completed": sum(a["status"] in {"complete", "unreviewable"} for a in annotations.values()),
                                           "total": len(units)})
                if prefix == "/pdf/":
                    with fitz.open(source) as pdf:
                        if unit["page"] > len(pdf):
                            raise ValueError("Sample page is outside the PDF")
                        requested = parse_qs(parsed.query).get("page", [str(unit["page"])])[0]
                        if not requested.isdigit() or not 1 <= int(requested) <= len(pdf):
                            raise ValueError("PDF context page is outside the source")
                        pix = pdf[int(requested) - 1].get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False)
                        return self.send(pix.tobytes("png"), "image/png")
                annotation = annotations.get(unit["unit_id"]) or _seed(unit, page, predictions, manifest["sample_id"])
                return self.send_json({"unit": unit, "page_count": int(doc["page_count"]),
                                       "total": len(units), "completed": sum(a["status"] in {"complete", "unreviewable"} for a in annotations.values()),
                                       "source_pdf": str(source), "raw_text": page.get("text", ""),
                                       "ocr_text": page.get("analysis_text", "") if page.get("analysis_text_source") == "local_ocr" else "",
                                       "normalized_text": page.get("normalized_text", ""), "predictions": predictions,
                                       "annotation": annotation})
            except (ValueError, KeyError, OSError, json.JSONDecodeError) as exc:
                return self.send_json({"error": str(exc)}, 400)

        def do_GET(self):
            self.route()

        def do_POST(self):
            self.route(post=True)

        def log_message(self, format, *args):
            # Request paths contain only opaque unit indices and a random token.
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Open http://127.0.0.1:{port}/?token={token}")
    print("Only this computer can access the review desk. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    finally:
        server.server_close()
