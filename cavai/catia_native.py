"""CATIA V5 native reader for the ORIGINAL CAVAI upload flow.

Read-only extraction using the installed CATIA application via Windows COM.
A temporary STEP/IGES export is attempted automatically for Open CASCADE.
No user-side manual conversion is needed. No original model is saved/edited.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

_COM_LOCK = threading.RLock()
MAX_BODIES = 80
MAX_FEATURES_PER_BODY = 80
MAX_PARAMETERS = 120
MAX_GEOMETRICAL_SETS = 60


class NativeCatiaError(RuntimeError):
    """CATIA was not accessible or could not open the supplied part."""


def _property(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _safe_error(exc: Exception) -> str:
    """Keep a short useful COM diagnostic without temporary filesystem paths."""
    code = getattr(exc, "hresult", None)
    if code is not None:
        return f"{type(exc).__name__} (COM HRESULT {hex(code & 0xffffffff)})"
    return type(exc).__name__


def _read_bodies(part: Any) -> dict:
    collection = part.Bodies
    count = int(collection.Count)
    items = []
    for i in range(1, min(count, MAX_BODIES) + 1):
        row = {"name": str(_property(collection.Item(i), "Name", f"Body {i}"))}
        try:
            shapes = collection.Item(i).Shapes
            n = int(shapes.Count)
            row["feature_count"] = n
            row["features"] = [
                str(_property(shapes.Item(j), "Name", f"Feature {j}"))
                for j in range(1, min(n, MAX_FEATURES_PER_BODY) + 1)
            ]
            row["features_truncated"] = n > MAX_FEATURES_PER_BODY
        except Exception as exc:
            row["features_error"] = _safe_error(exc)
        items.append(row)
    return {"count": count, "items": items, "truncated": count > MAX_BODIES}


def _read_parameters(part: Any) -> dict:
    collection = part.Parameters
    count = int(collection.Count)
    items = []
    for i in range(1, min(count, MAX_PARAMETERS) + 1):
        param = collection.Item(i)
        value = _property(param, "ValueAsString")
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
        items.append({
            "name": str(_property(param, "Name", f"Parameter {i}")),
            "value_as_string": str(value)[:200] if value is not None else None,
        })
    return {"count": count, "items": items, "truncated": count > MAX_PARAMETERS}


def _read_geometrical_sets(part: Any) -> dict:
    collection = part.HybridBodies
    count = int(collection.Count)
    items = []
    for i in range(1, min(count, MAX_GEOMETRICAL_SETS) + 1):
        item = collection.Item(i)
        items.append({
            "name": str(_property(item, "Name", f"Geometrical Set {i}")),
            "direct_hybrid_shape_count": _property(
                _property(item, "HybridShapes"), "Count"
            ),
        })
    return {"count": count, "items": items, "truncated": count > MAX_GEOMETRICAL_SETS}


def _try_export(document: Any, work_dir: Path) -> tuple[Path | None, str | None, dict]:
    attempts = []
    for fmt, suffix in (("STEP", ".stp"), ("IGES", ".igs")):
        out = work_dir / ("cavai_auto_geometry" + suffix)
        try:
            document.ExportData(str(out), suffix[1:])
            # No artificial geometry is generated if CATIA did not export.
            candidates = [out] + [
                p for p in work_dir.iterdir()
                if p.suffix.lower() == suffix and p != out
            ]
            exported = next((p for p in candidates
                             if p.is_file() and p.stat().st_size > 0), None)
            if exported is None:
                raise NativeCatiaError(f"CATIA {fmt} export produced no file")
            attempts.append({"format": fmt, "status": "success"})
            return exported, fmt, {"status": "success", "format": fmt,
                                    "attempts": attempts}
        except Exception as exc:
            attempts.append({"format": fmt, "status": "unavailable",
                             "reason": _safe_error(exc)})
    return None, None, {
        "status": "unavailable",
        "attempts": attempts,
        "explanation": "CATIA 原生结构已读取，但自动 STEP/IGES 导出不可用；"
                       "无法从导出文件建立几何预览或执行 B-Rep 验证。",
    }


def extract_catpart(path: Path, work_dir: Path) -> tuple[dict, Path | None, str | None]:
    """Returns (real COM evidence, exported temporary file or None, export format).

    The input must be an uploaded temporary .CATPart file. CATIA COM calls are
    serialized and initialized inside the calling thread.
    """
    if os.name != "nt":
        raise NativeCatiaError("CATPart 原生解析需要 Windows + CATIA V5 COM")
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise NativeCatiaError("缺少 pywin32：在当前 venv 安装 pywin32") from exc

    with _COM_LOCK:
        pythoncom.CoInitialize()
        document = None
        try:
            try:
                # The user's environment has verified Dispatch() rather than
                # GetActiveObject(); do not switch to the latter.
                catia = win32com.client.Dispatch("CATIA.Application")
                document = catia.Documents.Open(str(path.resolve()))
            except Exception as exc:
                raise NativeCatiaError(
                    "CATIA COM 连接或打开 CATPart 失败。请先启动 CATIA V5，"
                    "确认文件可在 CATIA 内正常打开。错误类型：" + _safe_error(exc)
                ) from exc

            try:
                part = document.Part
                native = {
                    "source": "CATIA V5 Windows COM",
                    "part_name": str(_property(part, "Name", "")),
                    "bodies": _read_bodies(part),
                    "parameters": _read_parameters(part),
                    "hybrid_bodies": _read_geometrical_sets(part),
                    "read_only": True,
                    "scope": "原生 Body、一级特征名称、参数值和几何集；"
                             "不等于已检查草图约束、特征依赖更新或工程功能",
                }
            except Exception as exc:
                raise NativeCatiaError(
                    "CATPart 已打开，但读取原生 Body/参数失败：" + _safe_error(exc)
                ) from exc

            exported, export_fmt, export_info = _try_export(document, work_dir)
            native["geometry_export"] = export_info
            return native, exported, export_fmt
        finally:
            if document is not None:
                try:
                    document.Close()  # Close only the temporary uploaded copy; do not save.
                except Exception:
                    pass
            pythoncom.CoUninitialize()
