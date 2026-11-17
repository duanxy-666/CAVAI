from pathlib import Path
from fastapi.testclient import TestClient
from cavai.app import app

SAMPLE=Path(__file__).resolve().parents[1]/"samples/bracket_4hole.step"

def test_upload_preview_and_offline_not_agent():
    client=TestClient(app)
    with SAMPLE.open("rb") as f:
        res=client.post("/api/upload",
               data={"description":"电机固定","requirements_json":
                     '{"max_envelope_mm":[81,51,7]}'},
               files={"file":("bracket_4hole.step",f,"application/octet-stream")})
    assert res.status_code==200,res.text
    payload=res.json()
    mid=payload["model_id"]
    assert payload["summary"]["bounds_mm"]==[80.0,50.0,6.0]
    preview=client.get(f"/api/models/{mid}/preview")
    assert preview.status_code==200
    assert preview.json()["display_triangles"]>100
    offline=client.post(f"/api/offline-checks/{mid}")
    assert offline.status_code==200
    assert offline.json()["mode"]=="OFFLINE_RULES_NOT_AN_AGENT"
    assert any(x["tool"]=="check_envelope" and x["status"]=="pass" for x in offline.json()["checks"])
    assert client.get(f"/api/reports/{mid}.json").status_code==404

def test_native_catpart_is_explicitly_unsupported():
    client=TestClient(app)
    res=client.post("/api/upload",
            files={"file":("model.CATPart",b"NOT-A-CATIA-FILE","application/octet-stream")})
    assert res.status_code==422
    assert "CATPart" in res.text

def test_index_and_capabilities():
    client=TestClient(app)
    assert client.get("/").status_code==200
    capabilities=client.get("/api/capabilities").json()
    assert ".step" in capabilities["supported_real_formats"]
    assert ".catpart" in capabilities["supported_real_formats"]
    assert ".catproduct" in capabilities["unsupported_native_formats"]
