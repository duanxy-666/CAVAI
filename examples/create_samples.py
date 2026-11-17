"""Recreate real CAD example solids and genuine STEP/IGES/STL files."""
from pathlib import Path
import cadquery as cq
from OCP.IGESControl import IGESControl_Writer
OUT=Path(__file__).resolve().parents[1]/"samples"
OUT.mkdir(exist_ok=True)
shape=(cq.Workplane("XY").box(80,50,6,centered=(True,True,False))
       .faces(">Z").workplane()
       .pushPoints([(-27,-15),(-27,15),(27,-15),(27,15)]).hole(6))
cq.exporters.export(shape,str(OUT/"bracket_4hole.step"))
cq.exporters.export(shape,str(OUT/"bracket_4hole.stl"))
writer=IGESControl_Writer()
assert writer.AddShape(shape.val().wrapped)
assert writer.Write(str(OUT/"bracket_4hole.igs"))
print("Generated actual STEP, IGES and STL models in:",OUT)
