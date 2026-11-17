from pathlib import Path
import pytest
from cavai.cad import parse_cad, CadParseError
from cavai.checks import run_tool, validate_requirements

ROOT=Path(__file__).resolve().parents[1]
SAMPLES=ROOT/"samples"

def test_real_step_geometry():
    p=SAMPLES/"bracket_4hole.step"
    cad=parse_cad(p,p.name)
    s=cad.summary
    assert s["format"]=="STEP"
    assert s["valid_brep"] is True
    assert s["bounds_mm"]==[80.0,50.0,6.0]
    assert s["solid_count"]==1
    assert s["cylinder_face_count"]==4
    assert all(abs(c["diameter_mm"]-6.0)<0.001 for c in s["cylindrical_faces"])
    assert abs(s["volume_mm3"]-23321.416)<0.1
    assert cad.preview["display_triangles"] > 100

def test_iges_actually_imports_surface_not_claiming_solid():
    p=SAMPLES/"bracket_4hole.igs"
    cad=parse_cad(p,p.name)
    assert cad.summary["format"]=="IGES"
    assert cad.summary["face_count"] > 0
    assert cad.summary["bounds_mm"]==[80.0,50.0,6.0]
    assert cad.summary["volume_mm3"] is None  # IGES has surfaces but no recognized solid
    result=run_tool("check_topology",cad,{})
    assert result["evidence"]["solid_count"]==cad.summary["solid_count"]
    assert result["status"] in {"pass","review","fail"}

def test_user_confirmed_envelope_and_cylinder():
    p=SAMPLES/"bracket_4hole.step"
    cad=parse_cad(p,p.name)
    good=run_tool("check_envelope",cad,{"max_envelope_mm":[81,51,7]})
    bad=run_tool("check_envelope",cad,{"max_envelope_mm":[70,51,7]})
    assert good["status"]=="pass"
    assert bad["status"]=="fail"
    assert bad["evidence"]["excess_mm"][0]==10.0
    cyl=run_tool("check_target_cylinder",cad,{"target_cylinder_diameter_mm":6})
    assert cyl["status"]=="pass"
    assert len(cyl["evidence"]["matches"])==4

def test_stl_mesh_unit_boundary():
    p=SAMPLES/"bracket_4hole.stl"
    native=parse_cad(p,p.name)
    metric=parse_cad(p,p.name,stl_units="mm")
    assert native.summary["bounds_mm"] is None
    assert native.summary["mesh_watertight"] is True
    assert run_tool("check_envelope",native,{"max_envelope_mm":[81,51,7]})["status"]=="unverified"
    assert metric.summary["bounds_mm"]==[80.0,50.0,6.0]
    assert run_tool("check_mesh_integrity",metric,{})["status"]=="pass"

def test_reject_untrusted_constraints_and_catpart():
    with pytest.raises(ValueError):
        validate_requirements({"fake_pass":True})
    with pytest.raises(ValueError):
        validate_requirements({"max_envelope_mm":[float("nan"),40,10]})
    with pytest.raises(CadParseError,match="CATPart"):
        parse_cad(SAMPLES/"bracket_4hole.step","dummy.CATPart")
