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
    t=base.get("type","cylinder")
    if t=="cylinder": return cq.Workplane("XY").circle(float(base.get("diameter",50))/2).extrude(float(base.get("length",100)))
    if t=="flange": return cq.Workplane("XY").circle(float(base.get("diameter",100))/2).extrude(float(base.get("thickness",20)))
    if t=="block": return cq.Workplane("XY").box(float(base.get("x",100)),float(base.get("y",60)),float(base.get("z",20)),centered=(True,True,False))
    if t=="tube": return cq.Workplane("XY").circle(float(base.get("outer_diameter",60))/2).circle(float(base.get("inner_diameter",40))/2).extrude(float(base.get("length",100)))
    if t=="revolved_profile":
        sts=base.get("stations") or []
        if len(sts)<2: raise ValueError("Revolved profile için en az iki istasyon gerekli")
        pts=[]
        for st in sts:
            z=float(st["z"]); d=float(st["diameter"])
            if d<=0: raise ValueError("Profil çapı pozitif olmalı")
            pts.append((z,d/2))
        if abs(pts[0][0])>1e-6: raise ValueError("Profil z=0 ile başlamalı")
        if any(pts[i][0]>pts[i+1][0] for i in range(len(pts)-1)): raise ValueError("Profil istasyonları z yönünde sıralı olmalı")
        # XZ benzeri kesiti XZ düzleminde tanımlayıp Z ekseni etrafında döndür. Workplane XZ'de yerel x global X, yerel y global Z'dir.
        wp=cq.Workplane("XZ").moveTo(pts[0][1],pts[0][0])
        for z,r in pts[1:]: wp=wp.lineTo(r,z)
        wp=wp.lineTo(0,pts[-1][0]).lineTo(0,pts[0][0]).close()
        return wp.revolve(360,(0,0),(0,1))
    raise ValueError(f"Desteklenmeyen taban tipi: {t}")


def _face_selector(face:str)->str:
    return {"top":">Z","bottom":"<Z","right":">X","left":"<X","front":"<Y","back":">Y"}.get(face or "top",">Z")


def _face_dims(state:CadState, face:str):
    b=state.base;t=b.get("type")
    if t=="block":
        if face in ("top","bottom"): return float(b.get("x",100)),float(b.get("y",60))
        if face in ("front","back"): return float(b.get("x",100)),float(b.get("z",20))
        return float(b.get("y",60)),float(b.get("z",20))
    d=float(b.get("diameter",b.get("outer_diameter",50)));return d,d


def _resolve_xy(state:CadState,f:dict):
    placement=f.get("placement") or {}
    mode=placement.get("mode")
    if mode=="point": return float(placement.get("x",0)),float(placement.get("y",0))
    if mode=="semantic":
        pos=placement.get("position","center");face=f.get("face","top");w,h=_face_dims(state,face)
        # Delikleri güvenli biçimde yüzeyin içinde tut. Dairesel tabanda diyagonaller daha içeri alınır.
        circular=state.base.get("type") in ("cylinder","flange","tube") and face in ("top","bottom")
        fx=0.30 if circular else 0.32; fy=0.30 if circular else 0.32
        mp={"center":(0,0),"left":(-fx,0),"right":(fx,0),"top":(0,fy),"bottom":(0,-fy),
            "top_left":(-fx*.78,fy*.78),"top_right":(fx*.78,fy*.78),"bottom_left":(-fx*.78,-fy*.78),"bottom_right":(fx*.78,-fy*.78)}
        px,py=mp.get(pos,(0,0));return w*px,h*py
    return float(f.get("x",0)),float(f.get("y",0))


def _planar_wp(part,state:CadState,f:dict):
    face=f.get("face","top")
    if face in ("left","right","front","back") and state.base.get("type")!="block":
        raise ValueError("Silindirik parçalarda yan yüzey işlemi henüz desteklenmiyor; uç yüzeyi seçin.")
    x,y=_resolve_xy(state,f)
    return part.faces(_face_selector(face)).workplane(centerOption="CenterOfBoundBox").center(x,y)


def _outer_edge(part,state:CadState,face:str):
    """Pah için selector string yerine gerçek geometri içinden dış kenarı bul."""
    candidates=part.edges(_face_selector(face)).vals()
    if not candidates: raise ValueError("Pah uygulanacak kenar bulunamadı")
    if state.base.get("type") in ("cylinder","flange","tube"):
        return [max(candidates,key=lambda e:e.Length())]
    # Blok/plakada seçilen yüzün tüm sınır kenarları
    return candidates


def _apply_chamfer(part,state:CadState,f:dict):
    dist=float(f.get("distance",0)); target=f.get("target","top_outer")
    if dist<=0: raise ValueError("Pah ölçüsü 0'dan büyük olmalı")
    edges=[]
    if target in ("top_outer","top"): edges+=_outer_edge(part,state,"top")
    elif target in ("bottom_outer","bottom"): edges+=_outer_edge(part,state,"bottom")
    elif target in ("both_outer","both"):
        edges+=_outer_edge(part,state,"top");edges+=_outer_edge(part,state,"bottom")
    else: edges+=_outer_edge(part,state,"top")
    return part.newObject(edges).chamfer(dist)


def build_model(state:CadState):
    part=_base_shape(state.base)
    for f in state.features:
        typ=f.get("type")
        try:
            if typ=="through_hole": part=_planar_wp(part,state,f).hole(float(f["diameter"]))
            elif typ=="blind_hole": part=_planar_wp(part,state,f).hole(float(f["diameter"]),float(f["depth"]))
            elif typ=="counterbore_hole": part=_planar_wp(part,state,f).cboreHole(float(f["diameter"]),float(f["counterbore_diameter"]),float(f["counterbore_depth"]),None)
            elif typ=="countersink_hole": part=_planar_wp(part,state,f).cskHole(float(f["diameter"]),float(f["countersink_diameter"]),float(f.get("angle",90)),None)
            elif typ=="circular_hole_pattern":
                hd=float(f["hole_diameter"]);qty=int(f["quantity"]);pcd=float(f["pcd"])
                pts=[(pcd/2*math.cos(2*math.pi*i/qty),pcd/2*math.sin(2*math.pi*i/qty)) for i in range(qty)]
                part=part.faces(_face_selector(f.get("face","top"))).workplane(centerOption="CenterOfBoundBox").pushPoints(pts).hole(hd)
            elif typ=="linear_hole_pattern":
                hd=float(f["hole_diameter"]);qty=int(f["quantity"]);spacing=float(f["spacing"]);x0,y0=_resolve_xy(state,f);axis=f.get("axis","x")
                offs=[(i-(qty-1)/2)*spacing for i in range(qty)];pts=[(x0+o,y0) if axis=="x" else (x0,y0+o) for o in offs]
                part=part.faces(_face_selector(f.get("face","top"))).workplane(centerOption="CenterOfBoundBox").pushPoints(pts).hole(hd)
            elif typ=="chamfer": part=_apply_chamfer(part,state,f)
            elif typ=="fillet":
                r=float(f["radius"]);target=f.get("target","vertical")
                sel="|Z" if target=="vertical" else ">Z"
                part=part.edges(sel).fillet(r)
            elif typ=="keyway":
                w=float(f["width"]);dep=float(f["depth"]);length=float(f.get("length",40));part=_planar_wp(part,state,f).rect(w,length).cutBlind(-dep)
            elif typ=="pocket": part=_planar_wp(part,state,f).rect(float(f["width"]),float(f["height"])).cutBlind(-float(f["depth"]))
            elif typ=="slot": part=_planar_wp(part,state,f).transformed(rotate=(0,0,float(f.get("angle",0)))).slot2D(float(f["length"]),float(f["width"])).cutBlind(-float(f["depth"]))
            elif typ=="shaft_step":
                if state.base.get("type") not in ("cylinder","flange"): raise ValueError("Kademe silindirik tabanda destekleniyor")
                nd=float(f["diameter"]);seg=float(f["length"]);total=float(state.base.get("length",state.base.get("thickness",0)));bd=float(state.base.get("diameter",0))
                if seg<=0 or seg>=total: raise ValueError("Kademe boyu toplam boydan küçük olmalı")
                z0=total-seg if f.get("position","right")=="right" else 0
                cutter=cq.Workplane("XY").workplane(offset=z0).circle(bd/2).circle(nd/2).extrude(seg);part=part.cut(cutter)
            elif typ in ("internal_thread","external_thread"): continue
            else: raise ValueError(f"Desteklenmeyen feature: {typ}")
        except Exception as e:
            raise ValueError(f"Feature '{typ}' uygulanamadı: {e}") from e
    return part


def export_files(state:CadState,out_dir:Path):
    out_dir.mkdir(parents=True,exist_ok=True);part=build_model(state)
    stem="".join(c if c.isalnum() or c in "-_" else "_" for c in state.part_name) or "parca"
    step=out_dir/f"{stem}.step";stl=out_dir/f"{stem}.stl"
    exporters.export(part,str(step));exporters.export(part,str(stl),tolerance=.05,angularTolerance=.1)
    return part,step,stl
