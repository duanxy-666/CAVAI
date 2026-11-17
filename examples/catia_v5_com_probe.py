"""EXPERIMENTAL Windows-only CATIA V5 inspection probe; NOT wired to CAVAI MVP.

Requires installed/licensed CATIA V5 and pywin32 on Windows.
This code is not tested here and must never be presented as verified CATIA support.
"""
from __future__ import annotations
import os
from pathlib import Path

def inspect_catpart_probe(path: str) -> dict:
    if os.name != "nt":
        raise RuntimeError("CATIA V5 COM requires Windows + licensed CATIA V5")
    try:
        import win32com.client
    except ImportError as exc:
        raise RuntimeError("Install pywin32 and CATIA V5 on this Windows host") from exc
    file = Path(path).resolve(strict=True)
    if file.suffix.lower() != ".catpart":
        raise ValueError("Only CATPart files are accepted by this experimental probe")
    catia = win32com.client.Dispatch("CATIA.Application")
    doc = catia.Documents.Open(str(file))
    try:
        part = doc.Part
        bodies = []
        for i in range(1, part.Bodies.Count+1):
            body = part.Bodies.Item(i)
            shapes=[]
            for j in range(1, body.Shapes.Count+1):
                feat=body.Shapes.Item(j)
                shapes.append({"name":str(feat.Name)})
            bodies.append({"name":str(body.Name),"features":shapes})
        parameters=[]
        for i in range(1, min(part.Parameters.Count,2000)+1):
            param=part.Parameters.Item(i)
            try:
                value=str(param.ValueAsString())
            except Exception:
                value=None
            parameters.append({"name":str(param.Name),"value_string":value})
        return {
            "adapter":"EXPERIMENTAL_UNTESTED_CATIA_COM_PROBE",
            "file":file.name,
            "bodies":bodies,"parameters":parameters,
            "limitations":[
                "No verified update/rebuild or feature dependency traversal",
                "No geometric edge/face identity mapping from this prototype",
                "Windows CATIA licensing and COM behavior must be tested locally"
            ]
        }
    finally:
        # Probe deliberately does NOT call Part.Update() or Save().
        doc.Close()
