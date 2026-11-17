import json
from pathlib import Path
import httpx
from cavai.agent import AgentRunner
from cavai.cad import parse_cad
from cavai.llm import LLMClient,LLMConfig
from cavai.rl import InspectionState,ReviewedFeedback,TabularQPolicy,reward_from_review

SAMPLE=Path(__file__).resolve().parents[1]/"samples/bracket_4hole.step"

def test_real_function_call_round_trip_over_httpx_mock_transport():
    rounds=[]
    def handler(request):
        assert request.method == "POST"
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-only"
        payload=json.loads(request.content)
        assert payload["tools"][0]["type"]=="function"
        rounds.append(payload)
        if len(rounds)==1:
            msg={"role":"assistant","content":"推断：带安装面和圆柱面，可能是支架。",
                 "tool_calls":[
                    {"id":"call_a","type":"function","function":{"name":"check_topology","arguments":"{}"}},
                    {"id":"call_b","type":"function","function":{"name":"inspect_cylindrical_faces","arguments":"{}"}}
                 ]}
        elif len(rounds)==2:
            assert any(m.get("role")=="tool" for m in payload["messages"])
            msg={"role":"assistant","content":None,
                 "tool_calls":[{"id":"call_c","type":"function",
                                "function":{"name":"check_envelope","arguments":"{}"}}]}
        else:
            assert sum(m.get("role")=="tool" for m in payload["messages"])==3
            msg={"role":"assistant","content":
                 "候选用途：安装支架。EV-0001 基础拓扑有效；EV-0003 包络符合用户明确上限。"
                 "载荷/配合件缺失，不能判定完整适用性。"}
        return httpx.Response(200,json={"choices":[{"message":msg}],
                                        "usage":{"prompt_tokens":100,"completion_tokens":40,"total_tokens":140}})
    transport=httpx.MockTransport(handler)
    cad=parse_cad(SAMPLE,SAMPLE.name)
    cfg=LLMConfig(api_key="test-only",base_url="https://api.example.org/v1",
                  model="unit-test-model",max_rounds=5,retries=0)
    client=LLMClient(cfg,transport=transport)
    events=list(AgentRunner(client).run_events(cad, "电机安装支架", "",
                                         {"max_envelope_mm":[81,51,7]}))
    report=events[-1]["report"]
    assert len(rounds)==3
    assert report["dynamic_tool_call_count"]==3
    assert report["structural_status"]=="basic_checks_passed"
    assert report["functional_status"]=="partial_requirements_met"
    assert report["llm_status"]=="tool_calls_completed"
    assert [t["evidence_id"] for t in report["tool_trace"]]==["EV-0001","EV-0002","EV-0003"]
    assert report["usage_reported_by_provider"]["total_tokens"]==420
    assert "test-only" not in json.dumps(report)

def test_non_tool_calling_model_not_misrepresented_as_agent():
    def handler(request):
        return httpx.Response(200,json={"choices":[{"message":{"role":"assistant",
                          "content":"仅总结，未提供任何 function calls"}}],
                          "usage":{"prompt_tokens":20,"completion_tokens":20,"total_tokens":40}})
    cad=parse_cad(SAMPLE,SAMPLE.name)
    client=LLMClient(LLMConfig(api_key="fake",base_url="https://api.example.org",model="mock",
                               retries=0,max_rounds=3),transport=httpx.MockTransport(handler))
    report=list(AgentRunner(client).run_events(cad))[-1]["report"]
    assert report["dynamic_tool_call_count"]==0
    assert report["llm_status"]=="no_dynamic_tool_calls"
    assert report["tool_trace"][0]["origin"]=="mandatory_baseline"

def test_reward_requires_reviewed_ground_truth():
    start=InspectionState("STEP","medium",2,())
    end=InspectionState("STEP","medium",1,("check_topology",))
    policy=TabularQPolicy(alpha=.5,gamma=.9,epsilon=0)
    rv=ReviewedFeedback(label_source="reviewed_benchmark",truth_is_complete=True,
            true_defect_ids=frozenset({"D-1","D-2"}),
            correctly_detected_ids=frozenset({"D-1"}),
            false_alarm_ids=frozenset({"FP-1"}),check_cost_units=2)
    reward,counts=reward_from_review(rv)
    assert counts=={"TP":1,"FN":1,"FP":1,"cost":2}
    updated=policy.update(start,"check_topology",reward,end,[])
    assert updated==reward*.5
    assert policy.choose(start,["inspect_dimensions","check_topology"])=="inspect_dimensions"
    try:
        ReviewedFeedback(label_source="llm_self_score",truth_is_complete=True,
            true_defect_ids=frozenset(),correctly_detected_ids=frozenset(),
            false_alarm_ids=frozenset(),check_cost_units=0)
        assert False, "untrusted labels must be rejected"
    except ValueError:
        pass


def test_cad_tool_exception_cannot_become_pass(monkeypatch):
    import cavai.agent as module
    original=module.run_tool
    def broken_one(name,model,requirements):
        if name=="inspect_dimensions":
            raise RuntimeError("a simulated checker failure")
        return original(name,model,requirements)
    monkeypatch.setattr(module,"run_tool",broken_one)
    counter=[0]
    def handler(request):
        counter[0]+=1
        msg=({"role":"assistant","content":None,
              "tool_calls":[{"id":"fail_tool","type":"function",
                             "function":{"name":"inspect_dimensions","arguments":"{}"}}]}
              if counter[0]==1 else
              {"role":"assistant","content":"该测量项工具异常，不能声称成功。"})
        return httpx.Response(200,json={"choices":[{"message":msg}],
                "usage":{"total_tokens":30,"prompt_tokens":20,"completion_tokens":10}})
    cad=parse_cad(SAMPLE,SAMPLE.name)
    client=LLMClient(LLMConfig(api_key="fake",base_url="https://api.example.org",model="mock",
               retries=0),transport=httpx.MockTransport(handler))
    report=list(AgentRunner(client).run_events(cad))[-1]["report"]
    item=next(x for x in report["tool_trace"] if x["tool"]=="inspect_dimensions")
    assert item["status"]=="unverified"
    assert item["evidence"]["error_type"]=="RuntimeError"
    assert report["dynamic_tool_call_count"]==1
