from __future__ import annotations
import re
import unicodedata
from .cad_engine import CadState

NUM = r"(\d+(?:[\.,]\d+)?)"
UNIT = r"(?:mm|milim(?:etre)?|milimetre)?"


def n(s: str) -> float:
    return float(str(s).replace(",", "."))


def _normalize(text: str) -> str:
    t = text.lower().strip()
    t = t.replace("ø", " çap ").replace("⌀", " çap ").replace("×", " x ")
    # Common Turkish speech-to-text variants / misspellings.
    replacements = {
        "milimetr": "milimetre", "milimetreler": "milimetre",
        "milim": "milimetre", " mm ": " milimetre ",
        "flans": "flanş", "cap": "çap", "capi": "çapı", "capinda": "çapında",
        "kalinlik": "kalınlık", "kalinliginda": "kalınlığında", "kalanlığına": "kalınlığında", "kalanligina": "kalınlığında", "kalınlığına": "kalınlığında",
        "uzunlugunda": "uzunluğunda", "sag": "sağ", "sagdan": "sağdan",
        "ortasina": "ortasına", "merkezine": "merkezine",
        "dis": "diş", "radyus": "radyüs", "havsa": "havşa",
    }
    # Pad to avoid replacing parts of unrelated words too aggressively.
    t = f" {t} "
    for a,b in replacements.items():
        t = t.replace(a,b)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _fid(state: CadState) -> str:
    nums=[]
    for f in state.features:
        m=re.search(r"(\d+)$", str(f.get("id", "")))
        if m: nums.append(int(m.group(1)))
    return f"feature_{(max(nums) if nums else 0)+1:03d}"


def _first(patterns, text, default=None):
    for p in patterns:
        m = re.search(p, text)
        if m:
            for g in m.groups():
                if g is not None and re.fullmatch(r"\d+(?:[\.,]\d+)?", g):
                    return n(g)
    return default


def _remove_types(state: CadState, *types: str):
    state.features = [f for f in state.features if f.get("type") not in types]


def _upsert_single(state: CadState, typ: str, data: dict):
    for f in state.features:
        if f.get("type") == typ:
            f.update(data)
            return
    state.features.append({"id": _fid(state), "type": typ, **data})


def _is_new_part_command(t: str) -> bool:
    create_words = ("yap", "oluştur", "çiz", "hazırla", "üret")
    part_words = ("flanş", "mil", "silindir", "şaft", "saft", "blok", "plaka", "boru")
    return any(w in t for w in create_words) and any(w in t for w in part_words)


def parse_turkish_command(text: str, current: CadState | None = None) -> CadState:
    t = _normalize(text)
    state = CadState(**(current.__dict__ if current else CadState().__dict__))
    # Deep-copy feature/base containers because API state may be reused.
    state.base = dict(state.base)
    state.features = [dict(f) for f in state.features]

    # A command that clearly creates/draws a NEW base part must never inherit old holes/features.
    if _is_new_part_command(t):
        state.features = []

    # ---------- BASE GEOMETRY ----------
    if "flanş" in t:
        d = _first([
            rf"{NUM}\s*{UNIT}\s*(?:çapında|çaplı|çap)",
            rf"(?:dış\s*)?çap(?:ı)?\s*{NUM}",
        ], t, state.base.get("diameter", 100))
        th = _first([
            rf"{NUM}\s*{UNIT}\s*(?:kalınlığında|kalınlık|kalınlığında bir)",
            rf"kalınlık(?:ı)?\s*{NUM}",
        ], t, state.base.get("thickness", 20))
        state.part_name = "flans"
        state.base = {"type": "flange", "diameter": float(d), "thickness": float(th)}

    elif "boru" in t:
        od = _first([rf"(?:dış\s*)?çap(?:ı)?\s*{NUM}", rf"{NUM}\s*{UNIT}\s*dış\s*çap"], t, state.base.get("outer_diameter",60))
        id_ = _first([rf"(?:iç\s*)?çap(?:ı)?\s*{NUM}", rf"{NUM}\s*{UNIT}\s*iç\s*çap"], t, state.base.get("inner_diameter",40))
        l = _first([rf"{NUM}\s*{UNIT}\s*(?:uzunluğunda|boyunda|uzunluk)", rf"uzunluk(?:u)?\s*{NUM}"], t, state.base.get("length",100))
        state.part_name="boru"; state.base={"type":"tube","outer_diameter":float(od),"inner_diameter":float(id_),"length":float(l)}

    elif "blok" in t or "plaka" in t:
        # Prefer X/Y/Z labels; otherwise first 3 dimensions.
        x=_first([rf"x\s*{NUM}"],t,None); y=_first([rf"y\s*{NUM}"],t,None); z=_first([rf"z\s*{NUM}"],t,None)
        if None in (x,y,z):
            vals=[n(v) for v in re.findall(NUM,t)[:3]]
            defaults=[100,60,20]
            vals=(vals+defaults)[:3]
            x=x if x is not None else vals[0]; y=y if y is not None else vals[1]; z=z if z is not None else vals[2]
        state.part_name="blok"; state.base={"type":"block","x":float(x),"y":float(y),"z":float(z)}

    elif any(w in t for w in ["mil", "silindir", "şaft", "saft"]):
        d = _first([
            rf"{NUM}\s*{UNIT}\s*(?:çapında|çaplı|çap)",
            rf"çap(?:ı)?\s*{NUM}",
        ], t, state.base.get("diameter",50))
        l = _first([
            rf"{NUM}\s*{UNIT}\s*(?:uzunluğunda|boyunda|uzunluk)",
            rf"(?:uzunluk|boy)(?:u)?\s*{NUM}",
        ], t, state.base.get("length",100))
        state.part_name="mil"; state.base={"type":"cylinder","diameter":float(d),"length":float(l)}

    # ---------- DELETIONS ----------
    if re.search(r"(?:merkez|orta).*?(?:deliği|delik).*?(?:sil|kaldır)", t) or re.search(r"(?:sil|kaldır).*?(?:merkez|orta).*?delik",t):
        _remove_types(state,"through_hole")
    if re.search(r"pah.*?(?:sil|kaldır)|(?:sil|kaldır).*?pah",t):
        _remove_types(state,"chamfer")
    if re.search(r"(?:radyüs|fillet).*?(?:sil|kaldır)|(?:sil|kaldır).*?(?:radyüs|fillet)",t):
        _remove_types(state,"fillet")
    if re.search(r"pcd.*?(?:sil|kaldır)|(?:sil|kaldır).*?pcd",t):
        _remove_types(state,"circular_hole_pattern")

    # ---------- CENTRAL HOLE ----------
    # Handles: "ortasına 40 mm", "tam ortasına 40'lık delik", "merkez deliğini 50 yap".
    center_d = _first([
        rf"(?:tam\s*)?(?:ortasına|ortada|merkeze|merkezine)\s*(?:çapı?\s*)?{NUM}\s*{UNIT}(?:\s*(?:lik|lık|luk|lük|çapında|delik))?",
        rf"(?:merkez|orta)\s*(?:deliğini|deliği|delik)\s*(?:çapı?\s*)?{NUM}",
        rf"(?:merkez|orta)\s*(?:deliğini|deliği|delik).*?{NUM}\s*{UNIT}",
    ], t, None)
    # avoid creating after explicit deletion command
    if center_d is not None and not re.search(r"(?:merkez|orta).*?delik.*?(?:sil|kaldır)",t):
        _upsert_single(state,"through_hole",{"diameter":float(center_d),"x":0.0,"y":0.0})

    # ---------- HOLE PATTERN ----------
    # Both orders: "80 PCD üzerinde 6 tane 10'luk delik" / "6 adet 10 delik PCD 80".
    pcd = _first([rf"{NUM}\s*{UNIT}\s*(?:pcd|hatve(?:\s*çapı)?)", rf"(?:pcd|hatve(?:\s*çapı)?)\s*{NUM}"],t,None)
    qtym = re.search(r"(\d+)\s*(?:tane|adet)\b",t)
    if pcd is not None and qtym:
        qty=int(qtym.group(1))
        # Search a hole diameter near the quantity, but do not accidentally use PCD or center-hole diameter.
        hd = _first([
            rf"{qty}\s*(?:tane|adet).*?{NUM}\s*{UNIT}\s*(?:lik|lık|luk|lük|çapında|çaplı)?\s*(?:delik|deliği)",
            rf"{qty}\s*(?:tane|adet).*?(?:çapı|çap)\s*{NUM}",
            rf"{NUM}\s*{UNIT}\s*(?:lik|lık|luk|lük|çapında)?\s*{qty}\s*(?:tane|adet).*?delik",
        ],t,10.0)
        _upsert_single(state,"circular_hole_pattern",{"quantity":qty,"pcd":float(pcd),"hole_diameter":float(hd)})

    # ---------- CHAMFER ----------
    cham = _first([
        rf"{NUM}\s*{UNIT}\s*(?:pah|pahlı|pahlama)",
        rf"pah(?:ı)?\s*{NUM}",
    ],t,None)
    if cham is not None and not re.search(r"pah.*?(?:sil|kaldır)|(?:sil|kaldır).*?pah",t):
        _upsert_single(state,"chamfer",{"distance":float(cham),"selector":"%Circle"})

    # ---------- FILLET ----------
    fillet = _first([
        rf"(?:radyüs|radius|fillet)\s*(?:r)?\s*{NUM}",
        rf"{NUM}\s*{UNIT}\s*(?:radyüs|radius|fillet)",
        rf"r\s*{NUM}",
    ],t,None)
    if fillet is not None and not re.search(r"(?:radyüs|fillet).*?(?:sil|kaldır)|(?:sil|kaldır).*?(?:radyüs|fillet)",t):
        _upsert_single(state,"fillet",{"radius":float(fillet),"selector":"|Z"})

    # ---------- SHAFT STEP ----------
    sm = re.search(rf"(?:sağdan|sağ\s*uçtan|sağ\s*taraftan).*?{NUM}\s*{UNIT}\s*(?:boyunca|uzunluğunda|boy).*?(?:çapı|çap)\s*{NUM}",t)
    if sm:
        _upsert_single(state,"shaft_step",{"length":n(sm.group(1)),"diameter":n(sm.group(2)),"position":"right"})

    # ---------- KEYWAY ----------
    keyw = _first([rf"{NUM}\s*{UNIT}\s*(?:genişliğinde|genişlikte|lik|lık)?\s*(?:kama\s*)?(?:kanalı|kama)"],t,None)
    if keyw is not None:
        depth=_first([rf"(?:derinliği|derinlik)\s*{NUM}",rf"{NUM}\s*{UNIT}\s*derinliğinde"],t,max(1.0,float(keyw)/3))
        _upsert_single(state,"keyway",{"width":float(keyw),"depth":float(depth)})

    # ---------- THREAD ----------
    tm = re.search(r"m\s*(\d+(?:[\.,]\d+)?)(?:\s*x\s*([\d\.,]+))?\s*(?:diş|vida)?",t)
    if tm and ("diş" in t or "vida" in t or "m" in t):
        size=f"M{tm.group(1).replace(',', '.')}"
        pitch=n(tm.group(2)) if tm.group(2) else None
        typ="external_thread" if any(w in t for w in ["dış diş","dış vida"]) else "internal_thread"
        _upsert_single(state,typ,{"size":size,"pitch":pitch})

    return state
