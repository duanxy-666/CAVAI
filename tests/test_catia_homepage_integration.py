"""CATPart homepage integration tests.

COM responses are *mocked*: these tests do NOT assert a real CATIA installation.
Where 3D geometry is tested, it comes from the repository's real STEP sample.
The real CATPart acceptance test must be run on the user's Windows/CATIA host.
"""
from __future__ import annotations

import importlib
import json
import shutil
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from cavai.cad import parse_cad
from cavai.checks import run_tool
from cavai.llm import LLMClient

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_STEP = ROOT / "samples" / "bracket_4hole.step"


def native_meta(status="success"):
    return {
        "source": "CATIA V5 Windows COM",
        "part_name": "MockFixturePart",
        "bodies": {
            "count": 1,
            "items": [{"name": "PartBody", "feature_count": 2,
                       "features": ["Pad.1", "Hole.1"]}],
            "truncated": False,
        },
        "parameters": {
            "count": 1,
            "items": [{"name": "Part1\\Length.1", "value_as_string": "80mm"}],
            "truncated": False,
        },
        "hybrid_bodies": {"count": 0, "items": [], "truncated": False},
        "geometry_export": {"status": status},
        "read_only": True,
    }


def test_uploaded_catpart_hits_original_endpoint_and_real_occt_step(monkeypatch):
    native_mod = importlib.import_module("cavai.catia_native")

    def fake_com_extract(path, work_dir):
        out = work_dir / "exported.stp"
        shutil.copy2(SAMPLE_STEP, out)
        return native_meta(), out, "STEP"

    monkeypatch.setattr(native_mod, "extract_catpart", fake_com_extract)
    app_mod = importlib.import_module("cavai.app")
    client = TestClient(app_mod.app)
    response = client.post(
        "/api/upload",
        data={"description": "电池夹具"},
        files={"file": ("Part2.CATPart", b"COM-IS-MOCKED-NOT-A-CATIA-FILE")},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["summary"]["format"] == "CATPart"
    assert data["summary"]["valid_brep"] is True
    assert data["summary"]["bounds_mm"] == [80.0, 50.0, 6.0]
    assert data["summary"]["catia_native"]["bodies"]["count"] == 1
    preview = client.get("/api/models/" + data["model_id"] + "/preview")
    assert preview.status_code == 200
    assert preview.json()["display_triangles"] > 0
    offline = client.post("/api/offline-checks/" + data["model_id"])
    assert any(x["tool"] == "inspect_feature_tree"
               and x["status"] == "info" for x in offline.json()["checks"])

    calls = [0]

    def response_to_llm(request):
        calls[0] += 1
        if calls[0] == 1:
            message = {
                "role": "assistant",
                "content": "候选用途：电池夹具，须复核真实夹紧条件。",
                "tool_calls": [
                    {"id": "tool_a", "type": "function", "function": {
                        "name": "check_topology", "arguments": "{}"}},
                    {"id": "tool_b", "type": "function", "function": {
                        "name": "inspect_feature_tree", "arguments": "{}"}},
                ],
            }
        else:
            message = {
                "role": "assistant",
                "content": "已取得 B-Rep 和 Body/参数证据，但不能证明可直接量产。"
            }
        return httpx.Response(200, json={
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 80, "completion_tokens": 30, "total_tokens": 110}
        })

    monkeypatch.setattr(
        app_mod, "LLMClient",
        lambda cfg: LLMClient(cfg, transport=httpx.MockTransport(response_to_llm))
    )
    inspection = client.post("/api/inspect/stream", json={
        "model_id": data["model_id"],
        "llm": {"api_key": "test-only", "base_url": "https://example.test/v1",
                "model": "mock-function-caller", "retries": 0}
    })
    assert inspection.status_code == 200
    events = [json.loads(s) for s in inspection.text.splitlines() if s.strip()]
    assert events[-1]["kind"] == "report", events
    assert events[-1]["report"]["dynamic_tool_call_count"] == 2
    assert calls[0] == 2


def test_native_only_when_export_unavailable_does_not_invent_geometry(monkeypatch):
    native_mod = importlib.import_module("cavai.catia_native")

    def fake_no_export(path, work_dir):
        return native_meta("unavailable"), None, None

    monkeypatch.setattr(native_mod, "extract_catpart", fake_no_export)
    app_mod = importlib.import_module("cavai.app")
    client = TestClient(app_mod.app)
    response = client.post(
        "/api/upload", files={"file": ("Part2.CATPart", b"COM-MOCK-ONLY")}
    )
    assert response.status_code == 200, response.text
    summary = response.json()["summary"]
    assert summary["geometry_type"] == "native_only"
    assert summary["volume_mm3"] is None
    assert summary["bounds_mm"] is None
    assert summary["valid_brep"] is None
    cad = app_mod._get(response.json()["model_id"]).cad
    assert cad.preview["faces"] == []
    assert run_tool("check_topology", cad, {})["status"] == "unverified"
    assert run_tool("check_component_count", cad, {})["status"] == "unverified"
    assert run_tool("inspect_feature_tree", cad, {})["status"] == "info"
    assert run_tool("check_envelope", cad, {"max_envelope_mm": [100, 80, 20]})["status"] == "unverified"
