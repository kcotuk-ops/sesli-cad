from __future__ import annotations
import re
from typing import Any
from .cad_engine import CadState

NUM = r"(\d+(?:[\.,]\d+)?)"

def n(s: str) -> float:
    return float(s.replace(",", "."))

def parse_turkish_command(text: str, current: CadState | None = None) -> CadState:
    t = text.lower().replace("ø", " çap ").replace("mm", " milimetre ")
    state = current or CadState()

    # Part name
    if "flanş" in t or "flans" in t:
        state.part_name = "flans"
        d = _first([rf"{NUM}\s*(?:milimetre\s*)?(?:çap(?:ında|li|lı)?|cap)", rf"çap\s*{NUM}"], t, 100)
        th = _first([rf"{NUM}\s*(?:milimetre\s*)?(?:kalınlığında|kalinliginda|kalınlık|kalinlik)"], t, 20)
        state.base = {"type":"flange","diameter":d,"thickness":th}
    elif "blok" in t or "plaka" in t:
        vals = [n(x) for x in re.findall(NUM, t)[:3]]
        x,y,z = (vals+[100,60,20])[:3]
        state.part_name="blok"
        state.base={"type":"block","x":x,"y":y,"z":z}
    elif any(w in t for w in ["mil", "silindir", "şaft", "saft"]):
        d = _first([rf"{NUM}\s*(?:milimetre\s*)?(?:çap(?:ında|li|lı)?|cap)", rf"çap\s*{NUM}"], t, state.base.get("diameter",50))
        l = _first([rf"{NUM}\s*(?:milimetre\s*)?(?:uzunluğunda|uzunlugunda|boyunda|uzunluk)"], t, state.base.get("length",100))
        state.part_name="mil"
        state.base={"type":"cylinder","diameter":d,"length":l}

    # edits / features
    # central hole
    m = re.search(rf"(?:ortasına|ortasina|merkeze|merkezine).*?{NUM}\s*(?:milimetre\s*)?(?:çapında|capinda|lik|lık|delik)", t)
    if not m:
        m = re.search(rf"{NUM}\s*(?:milimetre\s*)?(?:çapında|capinda)?\s*(?:merkez\s*)?delik", t)
    if m:
        state.features.append({"id":_fid(state),"type":"through_hole","diameter":n(m.group(1)),"x":0,"y":0})

    # hole pattern: 6 tane 10'luk delik, 80 PCD
    qtym = re.search(r"(\d+)\s*(?:tane|adet).*?delik", t)
    pcdm = re.search(rf"{NUM}\s*(?:milimetre\s*)?(?:pcd|hatve)", t)
    hdm = re.search(rf"(?:tane|adet).*?{NUM}\s*(?:milimetre\s*)?(?:lik|lık|çapında|capinda)?\s*delik", t)
    if qtym and pcdm:
        hd = n(hdm.group(1)) if hdm else 10.0
        state.features.append({"id":_fid(state),"type":"circular_hole_pattern","quantity":int(qtym.group(1)),"pcd":n(pcdm.group(1)),"hole_diameter":hd})

    # chamfer
    cm = re.search(rf"{NUM}\s*(?:milimetre\s*)?pah", t)
    if cm:
        state.features.append({"id":_fid(state),"type":"chamfer","distance":n(cm.group(1)),"selector":"%Circle"})

    # fillet/radius
    fm = re.search(rf"(?:radyüs|radius|fillet).*?{NUM}|{NUM}\s*(?:milimetre\s*)?(?:radyüs|radius|fillet)", t)
    if fm:
        val = next((g for g in fm.groups() if g), None)
        if val:
            state.features.append({"id":_fid(state),"type":"fillet","radius":n(val),"selector":"|Z"})

    # keyway
    km = re.search(rf"{NUM}\s*(?:milimetre\s*)?(?:genişliğinde|genisliginde|lik|lık)?\s*kama", t)
    if km:
        state.features.append({"id":_fid(state),"type":"keyway","width":n(km.group(1)),"depth":max(1,n(km.group(1))/3)})

    # shaft step: sağdan 40 boyunca çapı 50
    sm = re.search(rf"(?:sağdan|sagdan|sağ taraftan|sag taraftan).*?{NUM}\s*(?:milimetre\s*)?(?:boyunca|uzun).*?(?:çapı|capi|çap)\s*{NUM}", t)
    if sm:
        state.features.append({"id":_fid(state),"type":"shaft_step","length":n(sm.group(1)),"diameter":n(sm.group(2)),"position":"right"})

    # thread metadata
    tm = re.search(r"m\s*(\d+)(?:\s*[x×]\s*([\d\.,]+))?\s*(?:diş|dis)", t)
    if tm:
        state.features.append({"id":_fid(state),"type":"internal_thread","size":f"M{tm.group(1)}","pitch": n(tm.group(2)) if tm.group(2) else None})

    return state

def _first(patterns, text, default):
    for p in patterns:
        m=re.search(p,text)
        if m: return n(m.group(1))
    return float(default)

def _fid(state):
    return f"feature_{len(state.features)+1:03d}"
