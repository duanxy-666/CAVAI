"""LLM-led iterative CAD tool inspection with deterministic evidence and explicit limits."""
from __future__ import annotations
import json
import re
import time
from typing import Any, Iterable
from .cad import CadModel
from .checks import TOOL_GUIDES, TOOL_SCHEMAS, run_tool
from .knowledge import SYSTEM_PROMPT, KNOWLEDGE_VERSION, PART_FAMILIES
from .llm import LLMClient, LLMError

def _report(model: CadModel, description: str, source_prompt: str, requirements: dict,
            trace: list, usage: dict, proposed_intent: list, ai_text: str,
            llm_error: str = "") -> dict:
    failed = [x for x in trace if x["status"] == "fail"]
    review = [x for x in trace if x["status"] == "review"]
    structural = [x for x in trace if x["scope"] == "structural"]
    functional = [x for x in trace if x["scope"] == "functional"]
    structural_status = "fail" if any(x["status"]=="fail" for x in structural) else (
        "basic_checks_passed" if any(x["status"]=="pass" for x in structural) else "unknown")
    functional_status = "fail_specific_requirement" if any(x["status"]=="fail" for x in functional) else (
        "partial_requirements_met" if any(x["status"]=="pass" for x in functional) else "unknown")
    known_actions = sum(1 for x in trace if x["origin"] == "llm_tool_call")
    return {
        "format_version":"cavai-report-0.2",
        "filename":model.filename, "sha256":model.sha256, "cad_format":model.format,
        "input": {"user_declared_purpose":description,"original_prompt":source_prompt,
                  "explicit_requirements":requirements},
        "model_evidence":model.summary,
        "preliminary_llm_intent_hypotheses":proposed_intent,
        "tool_trace":trace,
        "confirmed_findings":failed,
        "review_items":review,
        "structural_status":structural_status,
        "functional_status":functional_status,
        "ai_analysis_unverified_until_engineer_review":ai_text,
        "llm_status": "incomplete" if llm_error else ("tool_calls_completed" if known_actions else "no_dynamic_tool_calls"),
        "llm_error":llm_error,
        "dynamic_tool_call_count":known_actions,
        "usage_reported_by_provider":usage,
        "knowledge_version":KNOWLEDGE_VERSION,
        "limitations": [
            "Measured tool values and explicit requirement comparisons are evidence; LLM narrative is a hypothesis/recommendation",
            "Functional fit, strength, fatigue, tolerances and CATIA parameter update robustness are not certified",
            "Without load/material/mating geometry, overall fitness remains unverified",
            "For STL without user-defined units, dimensions cannot be compared against mm requirements",
            "LLM token usage depends on the external provider response; independent engineering verification remains required",
        ]
    }

class AgentRunner:
    def __init__(self, llm: LLMClient):
        self.llm = llm

    def run_events(self, model: CadModel, description: str = "",
                   source_prompt: str = "", requirements: dict | None = None) -> Iterable[dict]:
        requirements = requirements or {}
        messages = [
            {"role":"system","content":SYSTEM_PROMPT},
            {"role":"user","content":json.dumps({
                "user_declared_purpose_untrusted":description,
                "original_modeling_prompt_untrusted":source_prompt[:4000],
                "user_explicit_requirements":requirements,
                "measured_cad_summary":model.summary,
                "design_knowledge":PART_FAMILIES,
                "instruction":"First propose potential design intent, then call several relevant tools. "
                              "Use explicit requirements only, do not infer a pass from your hypothesis."
            },ensure_ascii=False)},
        ]
        trace: list[dict] = []
        hypotheses: list[str] = []
        ai_text = ""
        error = ""
        called = set()
        tool_calls_count = 0

        def execute(name: str, origin: str) -> dict:
            nonlocal tool_calls_count
            try:
                item = dict(run_tool(name, model, requirements))
            except Exception as exc:
                # A CAD backend exception is an unverified check, never a pass/fail verdict.
                item = {"tool":name,"status":"unverified","scope":"structural",
                        "title":"CAD 检查工具执行失败",
                        "evidence":{"error_type":type(exc).__name__},
                        "explanation":"工具异常导致本项验证未完成，不得依据此项得出工程结论",
                        "recommendation":"检查 CAD 文件有效性或更换解析适配器，再重试"}
            item["evidence_id"] = f"EV-{len(trace)+1:04}"
            item["origin"] = origin
            item["state_before"] = {
                "format":model.format, "executed_tools":sorted(called),
                "detected_failures":sum(x["status"]=="fail" for x in trace),
                "remaining_tool_slots":self.llm.cfg.max_tools-tool_calls_count,
                "available_actions":list(TOOL_GUIDES)
            }
            trace.append(item)
            called.add(name)
            return item

        yield {"kind":"phase","message":"已读取真实 CAD 摘要，开始 LLM 设计意图分析与检查规划"}
        try:
            for round_index in range(self.llm.cfg.max_rounds):
                force_finish = round_index == self.llm.cfg.max_rounds-1
                choice = "none" if force_finish else "auto"
                response = self.llm.chat(messages, TOOL_SCHEMAS, tool_choice=choice)
                message = response["choices"][0]["message"]
                content = message.get("content") or ""
                tool_requests = message.get("tool_calls") or []
                if content and tool_requests:
                    hypotheses.append(content[:2400])
                if not tool_requests:
                    if not trace and not force_finish:
                        messages.append({"role":"assistant","content":content})
                        messages.append({"role":"user","content":
                            "请先真实调用至少两项 CAD 检查工具，再给结论；这是检查任务，不是仅做文字摘要。"})
                        yield {"kind":"phase","message":"要求 LLM 通过 Function Calling 实际调用 CAD 工具"}
                        continue
                    ai_text = content
                    break
                if force_finish:
                    ai_text = content
                    break
                # Preserve assistant's actual tool call message for the next LLM request.
                safe_calls = []
                for tc in tool_requests[:8]:
                    safe_calls.append({"id":tc.get("id",""),
                                       "type":"function","function":{
                                           "name":tc.get("function",{}).get("name",""),
                                           "arguments":tc.get("function",{}).get("arguments","{}")}})
                messages.append({"role":"assistant","content":content or None,
                                 "tool_calls":safe_calls})
                for call in safe_calls:
                    name = call["function"]["name"]
                    args = call["function"]["arguments"]
                    tool_calls_count += 1
                    if tool_calls_count > self.llm.cfg.max_tools:
                        result = {"error":"Tool budget exhausted"}
                    elif name not in TOOL_GUIDES:
                        result = {"error":"Unregistered tool name"}
                    else:
                        try:
                            parsed = json.loads(args)
                            if parsed not in ({}, None):
                                raise ValueError("Unexpected tool args (checks use trusted stored inputs only)")
                            result = execute(name,"llm_tool_call")
                            yield {"kind":"tool","tool":result}
                        except (ValueError,TypeError,json.JSONDecodeError) as exc:
                            result = {"error":f"Tool arguments invalid: {str(exc)[:100]}"}
                    messages.append({"role":"tool","tool_call_id":call["id"],
                                     "content":json.dumps(result,ensure_ascii=False,default=str)})
                yield {"kind":"phase","message":f"已执行 {len(trace)} 次证据化检查，LLM 继续决定下一步"}
            else:
                error = "Agent reached maximum LLM rounds before final explanation"
        except (LLMError,KeyError,IndexError,TypeError) as exc:
            error = str(exc)[:280]
            yield {"kind":"error","message":"LLM 调用中断：" + error}

        # Invariant safety checks: these are explicitly labeled as mandatory, not credited to agent autonomy.
        mandatory = ["check_mesh_integrity"] if model.mesh is not None else ["check_topology"]
        if model.format == "CATPart":
            mandatory.append("inspect_feature_tree")
        if "max_envelope_mm" in requirements:
            mandatory.append("check_envelope")
        if "expected_solid_count" in requirements:
            mandatory.append("check_component_count")
        for name in mandatory:
            if name not in called:
                item = execute(name,"mandatory_baseline")
                yield {"kind":"tool","tool":item}

        if not ai_text and not error:
            error = "Model gave no final analysis before round budget ended"
        report = _report(model,description,source_prompt,requirements,
                         trace,dict(self.llm.usage),hypotheses,ai_text,error)
        yield {"kind":"report","report":report}
