"""Evidence-backed, allowlisted CAD tools: an LLM selects tools, but never supplies measurements."""
from __future__ import annotations
import math
from typing import Any
from OCP.BRepCheck import BRepCheck_Analyzer
from .cad import CadModel

def validate_requirements(obj: Any) -> dict:
    if obj in (None, ""):
        return {}
    if not isinstance(obj, dict):
        raise ValueError("Requirements must be a JSON object")
    allowed = {"max_envelope_mm", "expected_solid_count",
               "target_cylinder_diameter_mm", "cylinder_tolerance_mm"}
    if set(obj) - allowed:
        raise ValueError(f"Unsupported requirement keys: {sorted(set(obj)-allowed)}")
    validated = {}
    if "max_envelope_mm" in obj:
        v = obj["max_envelope_mm"]
        if not isinstance(v, list) or len(v) != 3 or any(
            not isinstance(x, (int,float)) or isinstance(x,bool)
            or not math.isfinite(x) or x <= 0 or x > 1e7 for x in v
        ):
            raise ValueError("max_envelope_mm must be [positive X,Y,Z]")
        validated["max_envelope_mm"] = [float(x) for x in v]
    if "expected_solid_count" in obj:
        v = obj["expected_solid_count"]
        if not isinstance(v, int) or isinstance(v, bool) or not (1 <= v <= 1000):
            raise ValueError("expected_solid_count must be integer 1..1000")
        validated["expected_solid_count"] = v
    for k in ("target_cylinder_diameter_mm","cylinder_tolerance_mm"):
        if k in obj:
            v = obj[k]
            if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or v <= 0 or v > 1e7:
                raise ValueError(k + " must be positive finite number")
            validated[k] = float(v)
    return validated

TOOL_GUIDES = {
    "check_topology": "Run OCCT BRepCheck_Analyzer for STEP/IGES; real geometry integrity, not functional compliance",
    "inspect_dimensions": "Read measured shape extents and volume from CAD backend; report coordinate system and units",
    "inspect_cylindrical_faces": "Inspect analytic cylindrical faces and their measured diameters; they are NOT proven holes",
    "check_component_count": "Read CAD solid count or connected STL mesh-body count, note multi-part ambiguity",
    "check_envelope": "Compare measured AABB against user's explicit max_envelope_mm, if supplied",
    "check_target_cylinder": "Compare analytical cylindrical face diameters against user's explicit target diameter, if supplied",
    "check_mesh_integrity": "Check STL mesh watertightness and consistent winding via Trimesh",
    "inspect_feature_tree": "Read actual CATIA Body / feature names / parameter values when COM data exists; never infer update stability",
    "check_function_context": "Identify missing load/material/mating/fit data and limit functional claims",
}

TOOL_SCHEMAS = [
    {"type":"function",
     "function":{"name": name,"description": desc,
                 "parameters":{"type":"object","properties":{},"additionalProperties":False}}}
    for name,desc in TOOL_GUIDES.items()
]

def _item(tool: str, status: str, scope: str, title: str, evidence: dict,
          explanation: str, recommendation: str = "") -> dict:
    return {"tool":tool,"status":status,"scope":scope,"title":title,
            "evidence":evidence,"explanation":explanation,"recommendation":recommendation}

def run_tool(name: str, model: CadModel, req: dict) -> dict:
    if name not in TOOL_GUIDES:
        raise ValueError("Tool not in allowlist")
    s = model.summary
    brep = model.shape is not None
    mesh = model.mesh is not None
    if name == "check_topology":
        if not brep:
            return _item(name,"unverified","structural","B-Rep 拓扑检查不可用",
                         {"format":model.format},
                         "当前模型未取得 B-Rep 几何；CATPart 可能是自动 STEP/IGES 导出不可用，"
                         "STL 则不包含原生 B-Rep")
        valid = bool(BRepCheck_Analyzer(model.shape).IsValid())
        solids = s["solid_count"]
        status = "fail" if not valid else "pass" if solids > 0 else "review"
        return _item(name,status,"structural",
                     "B-Rep 基础拓扑有效" if status == "pass" else "B-Rep 拓扑需进一步处理",
                     {"occt_brep_valid":valid,"solid_count":solids,
                      "shell_count":s["shell_count"],"face_count":s["face_count"]},
                     "OCCT 实际重新执行 BRepCheck_Analyzer；非零实体且拓扑有效时仅确认基础结构有效",
                     "若无闭合实体，核对设计目标是否本来就是开放曲面" if solids == 0 else
                     "定位无效面、边、壳并在 CAD 中修复" if not valid else "")
    if name == "inspect_dimensions":
        return _item(name,"info","structural","CAD 测量结果",
                     {"bounding_box":s["bounding_box"],
                      "volume_mm3":s.get("volume_mm3"),
                      "volume_native":s.get("volume_native")},
                     "尺寸来自 CAD/网格解析器；包围盒沿导入模型坐标轴，体积不等于承载能力")
    if name == "inspect_cylindrical_faces":
        if not brep:
            return _item(name,"unverified","structural","无法识别解析圆柱面",
                         {"format":model.format},
                         "未取得可解析的 B-Rep 曲面，不能检测真实圆柱面直径")
        candidates = s["cylindrical_faces"]
        return _item(name,"info","structural","解析圆柱面测量",
                     {"candidate_count":s["cylinder_face_count"],"samples":candidates[:30]},
                     "OCCT 精确解析几何曲面；圆柱面可能是孔内壁、轴面或局部曲面，不能直接证明孔为通孔")
    if name == "check_component_count":
        if brep:
            n, noun = s["solid_count"], "B-Rep solids"
        elif mesh:
            n, noun = len(model.mesh.split(only_watertight=False)), "mesh bodies"
        else:
            return _item(name, "unverified", "structural", "实体数量尚不可测量",
                         {"format": model.format,
                          "native_body_count": s.get("catia_native", {}).get("bodies", {}).get("count")},
                         "CATIA Body 数不等于最终实体数；几何自动导出失败时不能推断实体数量")
        expected = req.get("expected_solid_count")
        if expected is not None:
            status = "pass" if n == expected else "fail"
            scope = "functional"
            title = "实体数量符合明确要求" if status == "pass" else "实体数量不符合明确要求"
            recommendation = "检查是否意外拆分/合并零件或未导入全部对象" if status == "fail" else ""
        else:
            status = "review" if n != 1 else "info"
            scope = "structural"
            title = "多实体模型：需确定设计意图" if n != 1 else "实体数量记录"
            recommendation = "提供期望零件数量；多实体不必然代表错误" if n != 1 else ""
        return _item(name,status,scope,title,
                     {"detected_count":n,"representation":noun,"expected_count":expected},
                     "由真实拓扑/网格连通性得到数量；装配层级未被恢复",recommendation)
    if name == "check_envelope":
        limits = req.get("max_envelope_mm")
        if limits is None:
            return _item(name,"unverified","functional","缺少外形包络要求",
                         {"measured_bounds_mm":s.get("bounds_mm")},
                         "未指定 max_envelope_mm，不能推断允许外形尺寸",
                         "如有外形约束，在高级要求中填写 [X,Y,Z] 毫米")
        measures = s.get("bounds_mm")
        if measures is None:
            return _item(name,"unverified","functional","无法进行毫米尺寸对比",
                         {"required_mm":limits,"units":s["units"]},
                         "STL 未声明物理单位，不能将裸坐标值冒充 mm")
        over = [round(a-b,4) for a,b in zip(measures,limits)]
        ok = all(x <= 0.001 for x in over)
        return _item(name,"pass" if ok else "fail","functional",
                     "导入坐标系下的包络尺寸符合要求" if ok else "包络尺寸超出用户给定上限",
                     {"measured_mm":measures,"max_allowed_mm":limits,"excess_mm":over},
                     "比较 CAD 实际坐标轴对齐包围盒与用户明确给定的 XYZ 限制；不包括装配空间干涉",
                     "核对坐标方向、基准面及设计尺寸，必要时编辑相关参数并重新测量" if not ok else "")
    if name == "check_target_cylinder":
        target = req.get("target_cylinder_diameter_mm")
        if target is None or not brep:
            return _item(name,"unverified","functional","圆柱直径目标尚不可验证",
                         {"target_mm":target,"geometry_type":s["geometry_type"]},
                         "要求提供目标直径且格式包含可解析圆柱曲面")
        tol = req.get("cylinder_tolerance_mm",0.1)
        matched = [c for c in s["cylindrical_faces"]
                   if abs(c["diameter_mm"]-target) <= tol]
        return _item(name,"pass" if matched else "review","functional",
                     "发现尺寸相符的候选圆柱面" if matched else "未发现目标直径的解析圆柱面",
                     {"target_mm":target,"tolerance_mm":tol,
                      "matches":matched[:15],"candidate_face_count":s["cylinder_face_count"]},
                     "仅证明存在/不存在匹配的解析圆柱曲面，不证明它是安装孔或其孔距、通孔状态、配合公差正确",
                     "若期望安装孔，请补充配合模型或工程图以确认孔的拓扑和位置")
    if name == "check_mesh_integrity":
        if not mesh:
            return _item(name,"unverified","structural","STL 网格检查不适用",
                         {"format":model.format},"请使用 check_topology")
        watertight = s["mesh_watertight"]
        winding = s["mesh_winding_consistent"]
        volume = s["mesh_is_volume"]
        status = "pass" if all([watertight,winding,volume]) else "review"
        return _item(name,status,"structural",
                     "网格封闭且方向一致" if status=="pass" else "网格可能存在开边或法线问题",
                     {"watertight":watertight,"winding_consistent":winding,
                      "is_volume":volume,"triangles":s["mesh_face_count"]},
                     "Trimesh 真实网格检查；不保证 STL 具有可加工的几何精度",
                     "检查洞、非流形边、重复面或反向面并重新导出网格" if status=="review" else "")
    if name == "inspect_feature_tree":
        native = s.get("catia_native")
        if not native:
            return _item(name,"unverified","structural","CATIA 原生特征树不可用",
                         {"format":model.format,"parameter_tree_available":False},
                         "当前格式无法恢复 CATIA 原生参数和建模历史")
        bodies = native.get("bodies", {})
        params = native.get("parameters", {})
        sets = native.get("hybrid_bodies", {})
        return _item(
            name, "info", "structural", "已读取 CATIA 原生 Body、特征和参数",
            {
                "source": "CATIA V5 Windows COM",
                "part_name": native.get("part_name"),
                "body_count": bodies.get("count"),
                "body_samples": bodies.get("items", [])[:30],
                "parameter_count": params.get("count"),
                "parameter_samples": params.get("items", [])[:50],
                "geometrical_set_count": sets.get("count"),
                "geometrical_set_samples": sets.get("items", [])[:15],
                "body_list_truncated": bodies.get("truncated", False),
                "parameter_list_truncated": params.get("truncated", False),
            },
            "以上是从 CATIA COM 实际读取的一级结构和参数值；尚未验证完整依赖图、"
            "草图约束、参数修改后 Update 的稳定性或设计功能，不能标记为结构验证通过",
            "可进一步接入 CATIA 原生引用关系与非破坏性参数更新检查"
        )
    if name == "check_function_context":
        missing = ["配合件几何及装配基准","载荷与工况","材料及许用强度",
                   "制造工艺与公差","实际功能验收标准"]
        return _item(name,"unverified","functional","完整功能适用性证据不足",
                     {"missing_context":missing,"provided_explicit_constraints":req},
                     "当前 MVP 只能对可取得的真实几何和已明确的条件做部分比对；CATIA 原生参数可供查阅，仍不能给出强度/配合/疲劳结论",
                     "上传配合零件、工程图并补充明确设计条件，扩展相应的 CAD/CAE 检查工具")
    raise RuntimeError("unreachable")
