import json
from pathlib import Path
import importlib
import httpx
from fastapi.testclient import TestClient
from cavai.llm import LLMClient

app_module=importlib.import_module("cavai.app")
SAMPLE=Path(__file__).resolve().parents[1]/"samples/bracket_4hole.step"

def test_ndjson_progress_has_real_tool_and_report(monkeypatch):
    counter=[0]
    def respond(request):
        counter[0]+=1
        if counter[0]==1:
            msg={"role":"assistant","content":"可能用于安装",
                 "tool_calls":[{"id":"stream-tool","type":"function",
                                "function":{"name":"check_topology","arguments":"{}"}}]}
        else:
            msg={"role":"assistant","content":"引用 EV-0001，仅确认基础结构有效，功能未确认。"}
        return httpx.Response(200,json={"choices":[{"message":msg}],
                                        "usage":{"total_tokens":25,"prompt_tokens":15,"completion_tokens":10}})
    transport=httpx.MockTransport(respond)
    monkeypatch.setattr(app_module,"LLMClient",lambda cfg: LLMClient(cfg,transport=transport))
    client=TestClient(app_module.app)
    with SAMPLE.open("rb") as f:
        uploaded=client.post("/api/upload",files={"file":("sample.step",f)})
    model_id=uploaded.json()["model_id"]
    req={"model_id":model_id,"llm":{"api_key":"fake",
         "base_url":"https://mock.example.com","model":"fake","retries":0}}
    r=client.post("/api/inspect/stream",json=req)
    assert r.status_code==200
    events=[json.loads(line) for line in r.text.splitlines() if line.strip()]
    assert any(e["kind"]=="phase" for e in events)
    assert any(e["kind"]=="tool" and e["tool"]["origin"]=="llm_tool_call" for e in events)
    assert events[-1]["kind"]=="report"
    assert events[-1]["report"]["dynamic_tool_call_count"]==1
