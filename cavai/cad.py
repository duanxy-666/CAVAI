"""Real CAD adapters: CATIA V5 COM + OCCT B-Rep + Trimesh mesh."""
from __future__ import annotations
import hashlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Cylinder
from OCP.IFSelect import IFSelect_RetDone
from OCP.IGESControl import IGESControl_Reader
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
import numpy as np
import trimesh

SUPPORTED = {".step": "STEP", ".stp": "STEP", ".iges": "IGES", ".igs": "IGES",
             ".stl": "STL", ".catpart": "CATPart"}
NATIVE_UNAVAILABLE = {".catproduct": "CATProduct"}
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_PREVIEW_TRIANGLES = 60000
MAX_STL_FACES = 250_000

class CadParseError(ValueError):
    pass

@dataclass
class CadModel:
    filename: str
    format: str
    sha256: str
    summary: dict[str, Any]
    preview: dict[str, Any]
    shape: Any = None
    mesh: Any = None

def _count(shape: Any, kind: Any) -> int:
    exp = TopExp_Explorer(shape, kind)
    n = 0
    while exp.More():
        n += 1
        exp.Next()
    return n

def _round(x: Any, ndigits: int = 4) -> float:
    return round(float(x), ndigits)

def _brep_preview(shape: Any) -> dict:
    # True tessellation of CAD B-Rep faces, independent from uploaded screenshots.
    BRepMesh_IncrementalMesh(shape, 0.9, False, 0.55, False)
    vertices, triangles = [], []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        location = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, location)
        if tri is not None:
            offset = len(vertices)
            tform = location.Transformation()
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(tform)
                vertices.append([_round(p.X(), 3), _round(p.Y(), 3), _round(p.Z(), 3)])
            reversed_orientation = face.Orientation() == TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                if reversed_orientation:
                    b, c = c, b
                triangles.append([offset + a - 1, offset + b - 1, offset + c - 1])
        exp.Next()
    return _limit_preview(vertices, triangles)

def _limit_preview(vertices: Any, triangles: Any) -> dict:
    """Keep the actual surface triangles intact.

    Old versions used triangles[::step], which *removed isolated faces*
    instead of properly simplifying a connected mesh. Complex CAD
    models therefore appeared as torn, crossing triangular shards.
    To avoid misleading users, never present such a broken preview.
    """
    n = len(triangles)
    if n > MAX_PREVIEW_TRIANGLES:
        return {
            "vertices": [],
            "faces": [],
            "source_triangles": n,
            "display_triangles": 0,
            "decimated": False,
            "preview_error": (
                f"模型包含 {n:,} 个预览三角面，超过当前浏览器绘制上限 "
                f"{MAX_PREVIEW_TRIANGLES:,}。为避免显示破碎的假图形，"
                "已暂停三维预览；真实 CAD 几何检查数据仍可使用。"
            ),
        }

    # Compact referenced vertices WITHOUT dropping any triangles.
    used = sorted({int(i) for f in triangles for i in f})
    ids = {original: idx for idx, original in enumerate(used)}
    compact_v = [list(map(float, vertices[i])) for i in used]
    compact_f = [[ids[int(i)] for i in f] for f in triangles]
    return {
        "vertices": compact_v,
        "faces": compact_f,
        "source_triangles": n,
        "display_triangles": len(compact_f),
        "decimated": False,
    }

def _brep(path: Path, fmt: str, digest: str) -> CadModel:
    if fmt == "STEP":
        reader = STEPControl_Reader()
    else:
        reader = IGESControl_Reader()
    status = reader.ReadFile(str(path))
    if status != IFSelect_RetDone:
        raise CadParseError(f"{fmt} reader returned non-success status")
    roots = reader.TransferRoots()
    if not roots:
        raise CadParseError(f"{fmt} contained no convertible roots")
    shape = reader.OneShape()
    if shape.IsNull():
        raise CadParseError(f"{fmt} shape is empty")
    bbox = Bnd_Box()
    BRepBndLib.Add_s(shape, bbox)
    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    bounds = [_round(v, 3) for v in (xmax - xmin, ymax - ymin, zmax - zmin)]
    # OCCT XDE/reader geometric units are normalized to mm in this import pipeline;
    # IGES origin unit metadata is not preserved in the MVP.
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    cyls = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    face_idx = 0
    while exp.More():
        face_idx += 1
        face = TopoDS.Face_s(exp.Current())
        surf = BRepAdaptor_Surface(face, True)
        if surf.GetType() == GeomAbs_Cylinder:
            cyl = surf.Cylinder()
            direction = cyl.Axis().Direction()
            cyls.append({
                "face_index": face_idx,
                "diameter_mm": _round(2 * cyl.Radius()),
                "axis_direction": [_round(direction.X()), _round(direction.Y()), _round(direction.Z())],
                "note": "cylindrical surface, NOT a proven through-hole"
            })
        exp.Next()
    solids = _count(shape, TopAbs_SOLID)
    summary = {
        "format": fmt,
        "geometry_type": "brep",
        "units": "mm",
        "unit_note": "OCCT converted length units to mm; confirm original IGES units where critical."
                     if fmt == "IGES" else "OCCT STEP length units normalized to mm",
        "bounds_mm": bounds,
        "bounding_box": {"size": bounds, "min": [_round(v,3) for v in (xmin,ymin,zmin)],
                         "max": [_round(v,3) for v in (xmax,ymax,zmax)], "unit":"mm"},
        "volume_mm3": _round(props.Mass(), 3) if solids > 0 else None,
        "volume_note": "Physical volume only reported for recognized solid B-Rep topology",
        "valid_brep": bool(BRepCheck_Analyzer(shape).IsValid()),
        "solid_count": solids,
        "shell_count": _count(shape, TopAbs_SHELL),
        "face_count": face_idx,
        "edge_count": _count(shape, TopAbs_EDGE),
        "vertex_count": _count(shape, TopAbs_VERTEX),
        "cylindrical_faces": cyls[:120],
        "cylinder_face_count": len(cyls),
        "parameter_tree_available": False,
        "assembly_hierarchy_available": False,
        "native_constraints_available": False,
        "limits": [
            "STEP/IGES import does not reconstruct a CATIA parametric feature tree",
            "B-Rep geometric validity does not prove strength, assembly fit, or manufacturability",
            "Cylinder faces are candidates, not certified hole features"
        ],
    }
    return CadModel(path.name, fmt, digest, summary, _brep_preview(shape), shape=shape)

def _stl(path: Path, digest: str, stl_units: str) -> CadModel:
    mesh = trimesh.load(str(path), file_type="stl", force="mesh", process=True)
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise CadParseError("STL has no valid triangle mesh")
    if len(mesh.faces) > MAX_STL_FACES:
        raise CadParseError(f"STL exceeds {MAX_STL_FACES:,} face limit")
    if not np.isfinite(mesh.vertices).all():
        raise CadParseError("STL contains non-finite coordinates")
    # STL stores no unit metadata. Conversion is only done with user declaration.
    scale = {"unknown": None, "mm": 1.0, "cm": 10.0, "in": 25.4}.get(stl_units)
    if stl_units not in {"unknown", "mm", "cm", "in"}:
        raise CadParseError("STL unit must be unknown/mm/cm/in")
    src_size = np.asarray(mesh.extents, dtype=float)
    length_mm = [_round(x * scale, 3) for x in src_size] if scale else None
    bounds = (np.asarray(mesh.bounds, dtype=float) * (scale or 1.0)).tolist()
    volume = float(mesh.volume)
    summary = {
        "format": "STL",
        "geometry_type": "mesh",
        "units": "mm" if scale else "unknown",
        "unit_note": "STL has no native unit metadata; unit assumed from user input"
                     if scale else "STL has no units; no mm-based engineering checks permitted",
        "bounds_mm": length_mm,
        "bounding_box": {"size": length_mm if scale else [_round(v,3) for v in src_size],
                         "min": [_round(v,3) for v in bounds[0]],
                         "max": [_round(v,3) for v in bounds[1]],
                         "unit": "mm" if scale else "STL coordinate units"},
        "volume_mm3": _round(volume * scale**3, 3) if scale and bool(mesh.is_volume) else None,
        "volume_native": _round(volume, 3) if bool(mesh.is_volume) else None,
        "volume_note": "Only report volume when mesh is a coherent closed volume",
        "mesh_face_count": int(len(mesh.faces)),
        "mesh_vertex_count": int(len(mesh.vertices)),
        "mesh_watertight": bool(mesh.is_watertight),
        "mesh_winding_consistent": bool(mesh.is_winding_consistent),
        "mesh_is_volume": bool(mesh.is_volume),
        "brep_available": False,
        "parameter_tree_available": False,
        "assembly_hierarchy_available": False,
        "native_constraints_available": False,
        "limits": [
            "STL is a triangle mesh; original analytic circles, design features and parameters are unavailable",
            "STL dimensions have no physical units without explicit user declaration",
            "Mesh watertightness does not prove engineering suitability"
        ],
    }
    vv = mesh.vertices * (scale or 1.0)
    preview = _limit_preview(vv.tolist(), mesh.faces.tolist())
    return CadModel(path.name, "STL", digest, summary, preview, mesh=mesh)

def _catpart(path: Path, digest: str) -> CadModel:
    """Read actual CATIA features; autoconvert temporary geometry if available.

    No manual STEP conversion, no fabricated measurements. If CATIA cannot
    export B-Rep, native parameters still remain available to the Agent.
    """
    from .catia_native import NativeCatiaError, extract_catpart

    try:
        with tempfile.TemporaryDirectory(prefix="cavai_geom_") as work:
            native, exported_path, export_fmt = extract_catpart(path, Path(work))
            geometry = None
            if exported_path is not None:
                try:
                    geometry = _brep(exported_path, export_fmt, digest)
                    native["geometry_export"]["occt_read"] = "success"
                except Exception as exc:
                    native["geometry_export"]["occt_read"] = "unavailable"
                    native["geometry_export"]["occt_error"] = type(exc).__name__
    except NativeCatiaError as exc:
        raise CadParseError("CATPart 原生解析失败：" + str(exc)) from exc

    extra_limits = [
        "CATIA Body / Shapes / Parameters 为原生 COM 读取结果，但未检查草图约束和更新稳定性",
        "B-Rep 尺寸若可用，来自 CATIA 自动导出后的 OCCT 解析，不是直接 COM 精密测量",
        "制造可行性、强度、装配匹配与公差仍须独立工程验证",
    ]
    if geometry is not None:
        geometry.format = "CATPart"
        geometry.filename = path.name
        geometry.summary.update({
            "format": "CATPart",
            "geometry_source": f"CATIA COM -> auto {export_fmt} -> Open CASCADE",
            "catia_native": native,
            "parameter_tree_available": True,
            "feature_tree_scope": "Body / direct Shapes only (not full dependency graph)",
            "native_constraints_available": False,
            "limits": geometry.summary.get("limits", []) + extra_limits,
        })
        return geometry

    empty_preview = {
        "vertices": [], "faces": [], "source_triangles": 0,
        "display_triangles": 0, "decimated": False,
    }
    summary = {
        "format": "CATPart",
        "geometry_type": "native_only",
        "geometry_source": "CATIA COM; no usable STEP/IGES geometry export",
        "units": "unknown",
        "unit_note": "原生特征读取成功；未获得可供尺寸测量的 B-Rep",
        "bounds_mm": None,
        "bounding_box": {"size": None, "min": None, "max": None,
                         "unit": "unknown"},
        "volume_mm3": None,
        "valid_brep": None,
        "solid_count": None,
        "face_count": None,
        "shell_count": None,
        "edge_count": None,
        "cylindrical_faces": [],
        "cylinder_face_count": 0,
        "parameter_tree_available": True,
        "feature_tree_scope": "Body / direct Shapes only (not full dependency graph)",
        "assembly_hierarchy_available": False,
        "native_constraints_available": False,
        "catia_native": native,
        "limits": extra_limits + [
            "CATIA STEP/IGES 几何自动导出不可用；无法执行真实几何尺寸、实体数或拓扑检查",
        ],
    }
    return CadModel(path.name, "CATPart", digest, summary, empty_preview)


def parse_cad(path: str | Path, filename: str, stl_units: str = "unknown") -> CadModel:
    path = Path(path)
    extension = Path(filename).suffix.lower()
    if extension in NATIVE_UNAVAILABLE:
        raise CadParseError(
            f"{NATIVE_UNAVAILABLE[extension]} native extraction is unavailable in this environment. "
            "Install CATIA V5 + Windows COM adapter; do not rename CATPart as STEP."
        )
    if extension not in SUPPORTED:
        raise CadParseError("Unsupported format: only STEP/STP, IGES/IGS and STL can be parsed in MVP")
    if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
        raise CadParseError("Missing file or file exceeds 25 MiB upload limit")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if extension == ".catpart":
        return _catpart(path, digest)
    if extension == ".stl":
        return _stl(path, digest, stl_units)
    return _brep(path, SUPPORTED[extension], digest)
