import json
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
import importlib
from cavai.llm import LLMClient, LLMConfig

app_module=importlib.import_module("cavai.app")
SAMPLE=Path(__file__).resolve().parents[1]/"samples/bracket_4hole.step"

def test_fastapi_agent_full_report_and_exports_using_mock_provider(monkeypatch):
    requests=[]
    def handler(request):
        payload=json.loads(request.content)
        requests.append(payload)
        if len(requests)==1:
            msg={"role":"assistant","content":"可能是电机固定板",
                "tool_calls":[{"id":"tool_1","type":"function",
                               "function":{"name":"check_topology","arguments":"{}"}},
                              {"id":"tool_2","type":"function",
                               "function":{"name":"check_envelope","arguments":"{}"}}]}
        else:
            msg={"role":"assistant","content":"引用 EV-0001/EV-0002：有限检查通过。没有载荷数据，不能认证整体功能。"}
        return httpx.Response(200,json={"choices":[{"message":msg}],
                                        "usage":{"total_tokens":35,"prompt_tokens":20,"completion_tokens":15}})
    transport=httpx.MockTransport(handler)
    monkeypatch.setattr(app_module,"LLMClient",lambda cfg: LLMClient(cfg,transport=transport))
    client=TestClient(app_module.app)
    with SAMPLE.open("rb") as f:
        uploaded=client.post("/api/upload",
            data={"requirements_json":'{"max_envelope_mm":[81,51,7]}'},
            files={"file":("bracket_4hole.step",f,"application/octet-stream")})
    assert uploaded.status_code==200
    model_id=uploaded.json()["model_id"]
    body={"model_id":model_id,"llm":{"api_key":"not-really-a-key","base_url":"https://api.mock.test/v1",
                                    "model":"test-model","retries":0,"max_rounds":4}}
    analyzed=client.post("/api/inspect",json=body)
    assert analyzed.status_code==200,analyzed.text
    report=analyzed.json()
    assert report["dynamic_tool_call_count"]==2
    assert report["llm_status"]=="tool_calls_completed"
    assert report["functional_status"]=="partial_requirements_met"
    assert client.get(f"/api/reports/{model_id}.json").status_code==200
    html=client.get(f"/api/reports/{model_id}.html")
    assert html.status_code==200
    assert "EV-0001" in html.text
    assert "not-really-a-key" not in html.text
    assert len(requests)==2

def test_local_network_urls_are_rejected_without_opt_in(monkeypatch):
    monkeypatch.delenv("CAVAI_ALLOW_LOCAL_API",raising=False)
    with pytest.raises(ValueError):
        LLMConfig(api_key="a-key",model="mock",base_url="http://127.0.0.1:9000")
    with pytest.raises(ValueError):
        LLMConfig(api_key="a-key",model="mock",base_url="http://localhost:1234")
    cfg=LLMConfig(api_key="private",model="mock",base_url="https://api.example.org")
    assert "private" not in repr(cfg)
