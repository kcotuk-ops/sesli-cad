from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import math
import cadquery as cq
from cadquery import exporters

@dataclass
class CadState:
    part_name: str = "parca"
    base: dict[str, Any] = field(default_factory=lambda: {"type":"cylinder","diameter":50.0,"length":100.0})
    features: list[dict[str, Any]] = field(default_factory=list)


def _base_shape(base: dict[str, Any]):
    t = base.get("type", "cylinder")
    if t == "cylinder":
        d = float(base.get("diameter", 50))
        l = float(base.get("length", 100))
        return cq.Workplane("XY").circle(d/2).extrude(l)
    if t == "flange":
        d = float(base.get("diameter", 100))
        th = float(base.get("thickness", 20))
        return cq.Workplane("XY").circle(d/2).extrude(th)
    if t == "block":
        x = float(base.get("x", 100)); y = float(base.get("y", 60)); z = float(base.get("z", 20))
        return cq.Workplane("XY").box(x,y,z, centered=(True,True,False))
    if t == "tube":
        od = float(base.get("outer_diameter", 60)); id_ = float(base.get("inner_diameter", 40)); l=float(base.get("length",100))
        return cq.Workplane("XY").circle(od/2).circle(id_/2).extrude(l)
    raise ValueError(f"Desteklenmeyen taban tipi: {t}")


def build_model(state: CadState):
    part = _base_shape(state.base)
    for f in state.features:
        typ = f.get("type")
        try:
            if typ == "through_hole":
                d = float(f["diameter"])
                x = float(f.get("x",0)); y=float(f.get("y",0))
                part = part.faces(">Z").workplane(centerOption="CenterOfBoundBox").center(x,y).hole(d)
            elif typ == "blind_hole":
                d=float(f["diameter"]); depth=float(f["depth"]); x=float(f.get("x",0)); y=float(f.get("y",0))
                part = part.faces(">Z").workplane(centerOption="CenterOfBoundBox").center(x,y).hole(d, depth)
            elif typ == "circular_hole_pattern":
                hd=float(f["hole_diameter"]); qty=int(f["quantity"]); pcd=float(f["pcd"])
                pts=[]
                for i in range(qty):
                    a=2*math.pi*i/qty
                    pts.append((pcd/2*math.cos(a), pcd/2*math.sin(a)))
                part = part.faces(">Z").workplane(centerOption="CenterOfBoundBox").pushPoints(pts).hole(hd)
            elif typ == "chamfer":
                dist=float(f["distance"])
                selector=f.get("selector","%Circle")
                part = part.edges(selector).chamfer(dist)
            elif typ == "fillet":
                r=float(f["radius"])
                selector=f.get("selector","|Z")
                part = part.edges(selector).fillet(r)
            elif typ == "keyway":
                width=float(f["width"]); depth=float(f["depth"]); length=float(f.get("length", state.base.get("length",50)))
                # simple keyway from top surface, centered in X, along Y-style rectangle projected through Z depth
                # Use top face and cut rectangular slot into body.
                part = part.faces(">Z").workplane().rect(width, length).cutBlind(-depth)
            elif typ == "pocket":
                w=float(f["width"]); h=float(f["height"]); depth=float(f["depth"]); x=float(f.get("x",0)); y=float(f.get("y",0))
                part = part.faces(">Z").workplane().center(x,y).rect(w,h).cutBlind(-depth)
            elif typ == "shaft_step":
                # For a cylindrical base extruded on Z: reduce the top segment to a smaller diameter.
                if state.base.get("type") not in ("cylinder", "flange"):
                    raise ValueError("shaft_step yalnızca silindirik tabanda destekleniyor")
                new_d=float(f["diameter"]); seg=float(f["length"])
                total=float(state.base.get("length", state.base.get("thickness",0)))
                base_d=float(state.base.get("diameter",0))
                if seg<=0 or seg>=total: raise ValueError("Kademe uzunluğu toplam boydan küçük olmalı")
                # cut annulus from top segment
                outer=cq.Workplane("XY").workplane(offset=total-seg).circle(base_d/2).circle(new_d/2).extrude(seg)
                part=part.cut(outer)
            elif typ in ("internal_thread", "external_thread"):
                # V1: represent thread cosmetically/metadata only. Geometry preserved.
                continue
            else:
                raise ValueError(f"Desteklenmeyen feature: {typ}")
        except Exception as e:
            raise ValueError(f"Feature '{typ}' uygulanamadı: {e}") from e
    return part


def export_files(state: CadState, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    part = build_model(state)
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in state.part_name) or "parca"
    step_path = out_dir / f"{stem}.step"
    stl_path = out_dir / f"{stem}.stl"
    exporters.export(part, str(step_path))
    exporters.export(part, str(stl_path), tolerance=0.05, angularTolerance=0.1)
    return part, step_path, stl_path
