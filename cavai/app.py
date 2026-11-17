"""CAVAI single-process MVP API and local web UI.

Security boundary: suitable for trusted local demonstration, NOT a public multi-tenant service.
"""
from __future__ import annotations
import html
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ValidationError
from .agent import AgentRunner
from .cad import CadModel, CadParseError, MAX_FILE_BYTES, NATIVE_UNAVAILABLE, SUPPORTED, parse_cad
from .checks import TOOL_GUIDES, run_tool, validate_requirements
from .llm import DEFAULT_URLS, LLMClient, LLMConfig, LLMError

STATIC = Path(__file__).parent / "static"
app = FastAPI(title="CAVAI - CATIA Intelligent Verification Agent", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

@dataclass
class Entry:
    cad: CadModel
    description: str
    source_prompt: str
    requirements: dict
    created: float = field(default_factory=time.monotonic)
    report: dict | None = None

DATA: dict[str, Entry] = {}
LOCK = threading.RLock()
MAX_MODELS = 15
TTL = 3600

def _get(key: str) -> Entry:
    with LOCK:
        item = DATA.get(key)
        if item is None:
            raise HTTPException(404, "Unknown or expired model ID")
        if time.monotonic() - item.created > TTL:
            DATA.pop(key, None)
            raise HTTPException(404, "Model expired, upload again")
        return item

def _evict():
    with LOCK:
        now = time.monotonic()
        for k,v in list(DATA.items()):
            if now-v.created > TTL:
                DATA.pop(k,None)
        if len(DATA) >= MAX_MODELS:
            oldest = min(DATA, key=lambda k: DATA[k].created)
            DATA.pop(oldest)

class InspectRequest(BaseModel):
    model_id: str
    llm: LLMConfig

class TestConnectionRequest(BaseModel):
    llm: LLMConfig

@app.get("/")
def index():
    return FileResponse(STATIC/"index.html")

@app.get("/api/health")
def health():
    return {"ok":True,"version":"0.2.0",
            "real_cad_backends":["CATIA V5 COM","OCCT B-Rep","Trimesh STL"],
            "api_chat_completions":True,
            "catia_host_windows":sys.platform=="win32"}

@app.get("/api/capabilities")
def capabilities():
    return {
        "supported_real_formats":list(SUPPORTED),
        "unsupported_native_formats":list(NATIVE_UNAVAILABLE),
        "llm_providers":DEFAULT_URLS,
        "tools":TOOL_GUIDES,
        "constraints":["max_envelope_mm","expected_solid_count",
                       "target_cylinder_diameter_mm","cylinder_tolerance_mm"],
        "preview_engine":"Native Canvas, data generated via OCCT/Trimesh (no external assets)",
        "limits":["CATPart needs Windows, CATIA V5 and working COM automation",
                  "CATPart geometry preview requires CATIA STEP/IGES translation",
                  "CATProduct native assembly parsing is not implemented",
                  "Native parameters are read-only; feature dependencies/updates are not verified",
                  "Functional engineering certification not implemented"],
    }

@app.post("/api/upload")
async def upload(file: UploadFile = File(...),
                 description: str = Form(""),
                 source_prompt: str = Form(""),
                 requirements_json: str = Form("{}"),
                 stl_units: str = Form("unknown")):
    filename = Path((file.filename or "").replace("\\","/")).name
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED and extension not in NATIVE_UNAVAILABLE:
        raise HTTPException(400,"Format not supported by MVP")
    try:
        requirements = validate_requirements(json.loads(requirements_json))
    except (json.JSONDecodeError,ValueError) as exc:
        raise HTTPException(400,"Invalid explicit requirements: "+str(exc)[:160]) from exc
    if len(description)>2500 or len(source_prompt)>8000:
        raise HTTPException(400,"Text description is too long")
    data = await file.read(MAX_FILE_BYTES+1)
    await file.close()
    if not data or len(data)>MAX_FILE_BYTES:
        raise HTTPException(413,"Empty model or model exceeds 25 MiB")
    # Temporary upload bytes are erased after parsing; parsed shape remains in-memory.
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=extension,delete=False) as temp:
            temp.write(data)
            temp_path=temp.name
        # Offload blocking Windows COM / CAD parsing from the HTTP event loop.
        cad = await run_in_threadpool(parse_cad,temp_path,filename,stl_units=stl_units)
        cad.filename = filename
    except CadParseError as exc:
        raise HTTPException(422,str(exc)[:450]) from exc
    except Exception as exc:
        # Do not fabricate geometry or expose parser internals.
        raise HTTPException(422,"CAD parser failed: "+type(exc).__name__) from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass  # CATIA may briefly retain an open handle after Close().
    key = uuid.uuid4().hex
    _evict()
    with LOCK:
        DATA[key] = Entry(cad,description,source_prompt,requirements)
    return {"model_id":key,"summary":cad.summary,"filename":filename,
            "sha256":cad.sha256,"preview_meta":{
                "triangles":cad.preview["display_triangles"],
                "decimated":cad.preview["decimated"]
            }}

@app.get("/api/models/{model_id}")
def model_info(model_id: str):
    entry = _get(model_id)
    return {"summary":entry.cad.summary, "description":entry.description,
            "requirements":entry.requirements}

@app.get("/api/models/{model_id}/preview")
def model_preview(model_id: str):
    return _get(model_id).cad.preview

@app.post("/api/llm/test")
def test_llm_connection(req: TestConnectionRequest):
    client = LLMClient(req.llm)
    try:
        response = client.chat([{"role":"user","content":"Reply with exactly the word OK."}])
    except LLMError as exc:
        raise HTTPException(502,str(exc)) from exc
    return {"ok":True,"answer":(response["choices"][0]["message"].get("content") or "")[:120],
            "usage":client.usage}

@app.post("/api/offline-checks/{model_id}")
def offline_checks(model_id: str):
    entry = _get(model_id)
    names = ["inspect_dimensions", "check_mesh_integrity" if entry.cad.mesh is not None
             else "check_topology", "check_component_count","inspect_cylindrical_faces",
             "check_envelope","check_target_cylinder","check_function_context"]
    if entry.cad.format == "CATPart":
        names.insert(2, "inspect_feature_tree")
    items = []
    for i,name in enumerate(names,1):
        item = run_tool(name,entry.cad,entry.requirements)
        item["evidence_id"] = f"OFF-{i:04}"
        item["origin"] = "offline_rule_only"
        items.append(item)
    return {"mode":"OFFLINE_RULES_NOT_AN_AGENT","checks":items,
            "warning":"Offline deterministic checks do not perform LLM intent planning or self-directed tool choice."}

@app.post("/api/inspect")
def inspect(req: InspectRequest):
    entry = _get(req.model_id)
    runner = AgentRunner(LLMClient(req.llm))
    report = None
    for event in runner.run_events(entry.cad,entry.description,entry.source_prompt,entry.requirements):
        if event["kind"] == "report":
            report = event["report"]
    if report is None:
        raise HTTPException(502,"Agent did not produce a report")
    with LOCK:
        entry.report = report
    return report

@app.post("/api/inspect/stream")
def inspect_stream(req: InspectRequest):
    entry = _get(req.model_id)
    def generate():
        try:
            runner = AgentRunner(LLMClient(req.llm))
            for event in runner.run_events(entry.cad,entry.description,entry.source_prompt,entry.requirements):
                if event.get("kind")=="report":
                    with LOCK:
                        entry.report = event["report"]
                yield json.dumps(event,ensure_ascii=False,default=str)+"\n"
        except Exception as exc:
            yield json.dumps({"kind":"error","message":"Server inspection error: "+type(exc).__name__},ensure_ascii=False)+"\n"
    return StreamingResponse(generate(),media_type="application/x-ndjson",
                             headers={"Cache-Control":"no-store","X-Accel-Buffering":"no"})

def _report_html(r: dict) -> str:
    e = lambda value: html.escape(str(value))
    status = {"pass":"通过","fail":"不满足","review":"需复核","unverified":"未验证","info":"测量信息"}
    rows = "\n".join(
        "<tr><td>"+e(t["evidence_id"])+"</td><td>"+e(t["tool"])+"</td><td>"
        +e(status.get(t["status"],t["status"]))+"</td><td>"+e(t["title"])
        +"</td><td><pre>"+e(json.dumps(t["evidence"],ensure_ascii=False,indent=2))
        +"</pre></td></tr>" for t in r["tool_trace"])
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>CAVAI 工程检查报告</title>
<style>body{{font:15px/1.6 system-ui, sans-serif;max-width:1100px;margin:36px auto;padding:0 20px;color:#143047}}
h1,h2{{color:#173d4e}} table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{padding:8px;border:1px solid #cbd5e1;vertical-align:top;text-align:left}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere}} .sub{{color:#5b7282}}
.note{{border-left:3px solid #bd8358;padding:10px 15px;background:#fcf8f0}}
@media print{{body{{margin:10mm}}}}</style></head><body>
<h1>CAVAI · CAD 智能验证报告</h1>
<p class="sub">文件：{e(r["filename"])} ｜ SHA256：{e(r["sha256"])}<br>
结构：{e(r["structural_status"])} ｜ 功能：{e(r["functional_status"])}
｜ 动态工具次数：{e(r["dynamic_tool_call_count"])}</p>
<h2>设计输入</h2><pre>{e(json.dumps(r["input"],ensure_ascii=False,indent=2))}</pre>
<h2>证据化工具检查</h2>
<table><tr><th>证据 ID</th><th>工具</th><th>状态</th><th>检查项</th><th>实测证据</th></tr>{rows}</table>
<h2>AI 分析与修复建议（须人工复核）</h2>
<pre>{e(r["ai_analysis_unverified_until_engineer_review"] or "未获得可用 AI 分析")}</pre>
<h2>边界与未验证项</h2><div class="note"><ul>{"".join("<li>"+e(x)+"</li>" for x in r["limitations"])}</ul></div>
<p class="sub">此报告不是设计放行证明，不包含材料强度、疲劳寿命或装配配合的自动认证。</p>
</body></html>"""

@app.get("/api/reports/{model_id}.{extension}")
def download_report(model_id: str,extension: str):
    entry = _get(model_id)
    if not entry.report:
        raise HTTPException(404,"No agent report available yet")
    if extension=="json":
        return JSONResponse(entry.report,
                            headers={"Content-Disposition":f'attachment; filename="cavai-{model_id[:8]}.json"'})
    if extension=="html":
        return HTMLResponse(_report_html(entry.report),
                            headers={"Content-Disposition":f'attachment; filename="cavai-{model_id[:8]}.html"'})
    raise HTTPException(404,"Only json and html are supported")
