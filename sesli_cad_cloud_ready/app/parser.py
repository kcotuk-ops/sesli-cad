from __future__ import annotations
import re
from .cad_engine import CadState

NUM = r"(\d+(?:[\.,]\d+)?)"
UNIT = r"(?:mm|milim(?:etre)?|milimetre)?"

def n(s: str) -> float: return float(str(s).replace(",", "."))

def _normalize(text: str) -> str:
    t=text.lower().strip().replace("ø"," çap ").replace("⌀"," çap ").replace("×"," x ")
    reps={
        "milimetr":"milimetre","milim":"milimetre"," mm ":" milimetre ","flans":"flanş","cap":"çap",
        "kalanlığına":"kalınlığında","kalanligina":"kalınlığında","kalınlığına":"kalınlığında","kalinlik":"kalınlık",
        "sag":"sağ","sagdan":"sağdan","sola":"sola","ortasina":"ortasına","ust":"üst","alttan":"alttan",
        "dis":"diş","radyus":"radyüs","havsa":"havşa","konik havşa":"havşa","kanal ac":"kanal aç",
    }
    t=f" {t} "
    for a,b in reps.items(): t=t.replace(a,b)
    return re.sub(r"\s+"," ",t).strip()

def _fid(state):
    nums=[]
    for f in state.features:
        m=re.search(r"(\d+)$",str(f.get("id","")))
        if m: nums.append(int(m.group(1)))
    return f"feature_{(max(nums) if nums else 0)+1:03d}"

def _first(patterns,text,default=None):
    for p in patterns:
        m=re.search(p,text)
        if m:
            for g in m.groups():
                if g is not None and re.fullmatch(r"\d+(?:[\.,]\d+)?",g): return n(g)
    return default

def _upsert(state,typ,data,match=None):
    for f in state.features:
        if f.get("type")==typ and (match is None or match(f)):
            f.update(data); return f
    f={"id":_fid(state),"type":typ,**data}; state.features.append(f); return f

def _remove(state,typ,match=None):
    state.features=[f for f in state.features if not (f.get("type")==typ and (match is None or match(f)))]

def _has_word(t, word):
    return re.search(rf"(?<!\w){re.escape(word)}(?!\w)", t) is not None

def _new_part(t):
    action=any(_has_word(t,w) for w in ("yap","oluştur","çiz","hazırla","üret"))
    part=any(_has_word(t,w) for w in ("flanş","mil","silindir","şaft","blok","plaka","boru"))
    return action and part

def _face(t):
    if any(w in t for w in ("alt yüz","alt yüzey","alttaki yüz")): return "bottom"
    if any(w in t for w in ("sağ yüz","sağ yüzey")): return "right"
    if any(w in t for w in ("sol yüz","sol yüzey")): return "left"
    if any(w in t for w in ("ön yüz","ön yüzey")): return "front"
    if any(w in t for w in ("arka yüz","arka yüzey")): return "back"
    return "top"

def _dims_for_face(base,face):
    typ=base.get("type")
    if typ=="block":
        if face in ("top","bottom"): return float(base.get("x",0)),float(base.get("y",0))
        if face in ("front","back"): return float(base.get("x",0)),float(base.get("z",0))
        if face in ("left","right"): return float(base.get("y",0)),float(base.get("z",0))
    if typ in ("cylinder","flange"):
        d=float(base.get("diameter",0)); return d,d
    if typ=="tube":
        d=float(base.get("outer_diameter",0)); return d,d
    return 0,0

def _xy_from_text(t,base,face):
    # Explicit local coordinates. When a base is described as "blok x 100 y 60 z 20",
    # those dimensions must not be mistaken for feature coordinates. Prefer the portion
    # of the sentence after a face/location phrase, otherwise only accept x=/y= syntax.
    coord_text=t
    marks=list(re.finditer(r"(?:üst|alt|sağ|sol|ön|arka)\s*yüz(?:ey)?(?:de|ünde|üne|e)?",t))
    if marks: coord_text=t[marks[-1].end():]
    mxs=re.findall(r"\bx\s*[=:]?\s*(-?\d+(?:[\.,]\d+)?)",coord_text)
    mys=re.findall(r"\by\s*[=:]?\s*(-?\d+(?:[\.,]\d+)?)",coord_text)
    if not marks:
        mxs=re.findall(r"\bx\s*=\s*(-?\d+(?:[\.,]\d+)?)",coord_text)
        mys=re.findall(r"\by\s*=\s*(-?\d+(?:[\.,]\d+)?)",coord_text)
    x=n(mxs[-1]) if mxs else 0.0; y=n(mys[-1]) if mys else 0.0
    w,h=_dims_for_face(base,face)
    # Edge offsets on selected face: sağ kenardan 20, sol kenardan 20, üst kenardan 10, alt kenardan 10
    m=re.search(rf"sağ\s*kenardan\s*{NUM}\s*{UNIT}",t)
    if m and w: x=w/2-n(m.group(1))
    m=re.search(rf"sol\s*kenardan\s*{NUM}\s*{UNIT}",t)
    if m and w: x=-w/2+n(m.group(1))
    m=re.search(rf"üst\s*kenardan\s*{NUM}\s*{UNIT}",t)
    if m and h: y=h/2-n(m.group(1))
    m=re.search(rf"alt\s*kenardan\s*{NUM}\s*{UNIT}",t)
    if m and h: y=-h/2+n(m.group(1))
    # Relative-to-center speech
    m=re.search(rf"merkezden\s*{NUM}\s*{UNIT}\s*sağa",t)
    if m: x=n(m.group(1))
    m=re.search(rf"merkezden\s*{NUM}\s*{UNIT}\s*sola",t)
    if m: x=-n(m.group(1))
    m=re.search(rf"merkezden\s*{NUM}\s*{UNIT}\s*(?:yukarı|üste)",t)
    if m: y=n(m.group(1))
    m=re.search(rf"merkezden\s*{NUM}\s*{UNIT}\s*(?:aşağı|alta)",t)
    if m: y=-n(m.group(1))
    return float(x),float(y)

def parse_turkish_command(text: str, current: CadState | None=None) -> CadState:
    t=_normalize(text)
    state=CadState(**(current.__dict__ if current else CadState().__dict__)); state.base=dict(state.base); state.features=[dict(f) for f in state.features]
    if _new_part(t): state.features=[]

    # base geometry
    if "flanş" in t:
        d=_first([rf"{NUM}\s*{UNIT}\s*(?:çapında|çaplı|çap)",rf"(?:dış\s*)?çap(?:ı)?\s*{NUM}"],t,state.base.get("diameter",100))
        th=_first([rf"{NUM}\s*{UNIT}\s*(?:kalınlığında|kalınlık)",rf"kalınlık(?:ı)?\s*{NUM}"],t,state.base.get("thickness",20))
        state.part_name="flans"; state.base={"type":"flange","diameter":float(d),"thickness":float(th)}
    elif "boru" in t:
        od=_first([rf"(?:dış\s*)?çap(?:ı)?\s*{NUM}",rf"{NUM}\s*{UNIT}\s*dış\s*çap"],t,state.base.get("outer_diameter",60))
        id_=_first([rf"(?:iç\s*)?çap(?:ı)?\s*{NUM}",rf"{NUM}\s*{UNIT}\s*iç\s*çap"],t,state.base.get("inner_diameter",40))
        l=_first([rf"{NUM}\s*{UNIT}\s*(?:uzunluğunda|boyunda|uzunluk)",rf"uzunluk(?:u)?\s*{NUM}"],t,state.base.get("length",100))
        state.part_name="boru"; state.base={"type":"tube","outer_diameter":float(od),"inner_diameter":float(id_),"length":float(l)}
    elif "blok" in t or "plaka" in t:
        x=_first([rf"x\s*{NUM}"],t,None); y=_first([rf"y\s*{NUM}"],t,None); z=_first([rf"z\s*{NUM}"],t,None)
        if None in (x,y,z):
            vals=[n(v) for v in re.findall(NUM,t)[:3]]; vals=(vals+[100,60,20])[:3]
            x=x if x is not None else vals[0]; y=y if y is not None else vals[1]; z=z if z is not None else vals[2]
        state.part_name="blok"; state.base={"type":"block","x":float(x),"y":float(y),"z":float(z)}
    elif any(_has_word(t,w) for w in ("mil","silindir","şaft")):
        d=_first([rf"{NUM}\s*{UNIT}\s*(?:çapında|çaplı|çap)",rf"çap(?:ı)?\s*{NUM}"],t,state.base.get("diameter",50))
        l=_first([rf"{NUM}\s*{UNIT}\s*(?:uzunluğunda|boyunda|uzunluk)",rf"(?:uzunluk|boy)(?:u)?\s*{NUM}"],t,state.base.get("length",100))
        state.part_name="mil"; state.base={"type":"cylinder","diameter":float(d),"length":float(l)}

    face=_face(t); x,y=_xy_from_text(t,state.base,face)

    # deletion / edits
    if re.search(r"(?:merkez|orta).*?delik.*?(?:sil|kaldır)|(?:sil|kaldır).*?(?:merkez|orta).*?delik",t):
        _remove(state,"through_hole",lambda f: abs(float(f.get("x",0)))<1e-9 and abs(float(f.get("y",0)))<1e-9)
    if re.search(r"(?:tüm\s*)?delikleri\s*(?:sil|kaldır)",t):
        state.features=[f for f in state.features if "hole" not in f.get("type","")]
    if re.search(r"pah.*?(?:sil|kaldır)|(?:sil|kaldır).*?pah",t): _remove(state,"chamfer")
    if re.search(r"(?:radyüs|fillet).*?(?:sil|kaldır)|(?:sil|kaldır).*?(?:radyüs|fillet)",t): _remove(state,"fillet")

    # hole types
    center_d=_first([rf"(?:tam\s*)?(?:ortasına|ortada|merkeze|merkezine)\s*(?:çapı?\s*)?{NUM}\s*{UNIT}(?:\s*(?:lik|lık|luk|lük|çapında|delik))?",rf"(?:merkez|orta)\s*(?:deliğini|deliği|delik)\s*(?:çapı?\s*)?{NUM}"],t,None)
    if center_d is not None and "sil" not in t and "kaldır" not in t:
        _upsert(state,"through_hole",{"diameter":float(center_d),"x":0.0,"y":0.0,"face":face},lambda f: abs(float(f.get("x",0)))<1e-9 and abs(float(f.get("y",0)))<1e-9)

    # Generic positioned hole: "üst yüzeyde sağ kenardan 20 mm ... 8 mm delik"
    generic_hole=_first([rf"(?:çapı|çapında|çap)\s*{NUM}\s*{UNIT}\s*(?:delik|deliği)",rf"{NUM}\s*{UNIT}\s*(?:çapında|lik|lık|luk|lük)?\s*delik"],t,None)
    if generic_hole is not None and center_d is None and "pcd" not in t and "hatve" not in t and "havşa" not in t and "kör" not in t and "doğrusal" not in t and "lineer" not in t:
        _upsert(state,"through_hole",{"diameter":float(generic_hole),"x":x,"y":y,"face":face},lambda f: f.get("face","top")==face and abs(float(f.get("x",0))-x)<1e-9 and abs(float(f.get("y",0))-y)<1e-9)

    blind_d=_first([rf"{NUM}\s*{UNIT}\s*(?:çapında|lik|lık)?\s*kör\s*delik",rf"kör\s*delik.*?(?:çapı|çap)\s*{NUM}"],t,None)
    if blind_d is not None:
        depth=_first([rf"(?:derinliği|derinlik|derinlikte)\s*{NUM}",rf"{NUM}\s*{UNIT}\s*derinliğinde"],t,10)
        _upsert(state,"blind_hole",{"diameter":float(blind_d),"depth":float(depth),"x":x,"y":y,"face":face},lambda f:f.get("face","top")==face and abs(float(f.get("x",0))-x)<1e-9 and abs(float(f.get("y",0))-y)<1e-9)

    # Countersink / counterbore
    if "silindirik havşa" in t or "counterbore" in t:
        hd=_first([rf"(?:delik|delik çapı|çap)\s*{NUM}"],t,8); cbd=_first([rf"havşa çapı\s*{NUM}"],t,14); dep=_first([rf"havşa derinliği\s*{NUM}"],t,5)
        _upsert(state,"counterbore_hole",{"diameter":float(hd),"counterbore_diameter":float(cbd),"counterbore_depth":float(dep),"x":x,"y":y,"face":face})
    elif "havşa" in t:
        hd=_first([rf"(?:delik|delik çapı|çap)\s*{NUM}",rf"{NUM}\s*{UNIT}\s*delik"],t,8)
        csd=_first([rf"{NUM}\s*{UNIT}\s*havşa",rf"havşa(?:\s*çapı)?\s*{NUM}"],t,max(float(hd)*2,12))
        ang=_first([rf"{NUM}\s*(?:derece|°)"],t,90)
        _upsert(state,"countersink_hole",{"diameter":float(hd),"countersink_diameter":float(csd),"angle":float(ang),"x":x,"y":y,"face":face})

    # patterns
    pcd=_first([rf"{NUM}\s*{UNIT}\s*(?:pcd|hatve(?:\s*çapı)?)",rf"(?:pcd|hatve(?:\s*çapı)?)\s*{NUM}"],t,None); qtym=re.search(r"(\d+)\s*(?:tane|adet)\b",t)
    if pcd is not None and qtym:
        qty=int(qtym.group(1)); hd=_first([rf"{qty}\s*(?:tane|adet).*?{NUM}\s*{UNIT}\s*(?:lik|lık|çapında)?\s*(?:delik|deliği)",rf"{qty}\s*(?:tane|adet).*?(?:çapı|çap)\s*{NUM}"],t,10)
        _upsert(state,"circular_hole_pattern",{"quantity":qty,"pcd":float(pcd),"hole_diameter":float(hd),"face":face})
    if "doğrusal" in t or "lineer" in t:
        qtym=re.search(r"(\d+)\s*(?:tane|adet)",t); spacing=_first([rf"{NUM}\s*{UNIT}\s*(?:aralık|aralıklı|adım)"],t,None); hd=generic_hole
        if qtym and spacing and hd:
            axis="y" if any(w in t for w in ("dikey","y yön")) else "x"
            _upsert(state,"linear_hole_pattern",{"quantity":int(qtym.group(1)),"spacing":float(spacing),"hole_diameter":float(hd),"x":x,"y":y,"axis":axis,"face":face})

    # pocket and slot
    if "cep" in t:
        w=_first([rf"(?:genişlik|eni)\s*{NUM}",rf"{NUM}\s*{UNIT}\s*genişliğinde"],t,20); h=_first([rf"(?:yükseklik|boy)\s*{NUM}",rf"{NUM}\s*{UNIT}\s*(?:yüksekliğinde|boyunda)"],t,20); dep=_first([rf"(?:derinlik|derinliği)\s*{NUM}",rf"{NUM}\s*{UNIT}\s*derinliğinde"],t,5)
        _upsert(state,"pocket",{"width":float(w),"height":float(h),"depth":float(dep),"x":x,"y":y,"face":face})
    if "slot" in t or "oval kanal" in t or "uzun delik" in t:
        length=_first([rf"(?:uzunluk|boy)\s*{NUM}",rf"{NUM}\s*{UNIT}\s*(?:uzunluğunda|boyunda)"],t,30); width=_first([rf"(?:genişlik|en)\s*{NUM}",rf"{NUM}\s*{UNIT}\s*genişliğinde"],t,10); dep=_first([rf"(?:derinlik|derinliği)\s*{NUM}",rf"{NUM}\s*{UNIT}\s*derinliğinde"],t,5); ang=_first([rf"{NUM}\s*(?:derece|°)"],t,0)
        _upsert(state,"slot",{"length":float(length),"width":float(width),"depth":float(dep),"angle":float(ang),"x":x,"y":y,"face":face})

    cham=_first([rf"{NUM}\s*{UNIT}\s*(?:pah|pahlı|pahlama)",rf"pah(?:ı)?\s*{NUM}"],t,None)
    if cham is not None and "sil" not in t and "kaldır" not in t: _upsert(state,"chamfer",{"distance":float(cham),"selector":"%Circle"})
    fil=_first([rf"(?:radyüs|radius|fillet)\s*(?:r)?\s*{NUM}",rf"{NUM}\s*{UNIT}\s*(?:radyüs|radius|fillet)",rf"r\s*{NUM}"],t,None)
    if fil is not None and "sil" not in t and "kaldır" not in t: _upsert(state,"fillet",{"radius":float(fil),"selector":"|Z"})
    sm=re.search(rf"(?:sağdan|sağ\s*uçtan|sağ\s*taraftan).*?{NUM}\s*{UNIT}\s*(?:boyunca|uzunluğunda|boy).*?(?:çapı|çap)\s*{NUM}",t)
    if sm: _upsert(state,"shaft_step",{"length":n(sm.group(1)),"diameter":n(sm.group(2)),"position":"right"})
    sm2=re.search(rf"(?:soldan|sol\s*uçtan|sol\s*taraftan).*?{NUM}\s*{UNIT}\s*(?:boyunca|uzunluğunda|boy).*?(?:çapı|çap)\s*{NUM}",t)
    if sm2: _upsert(state,"shaft_step",{"length":n(sm2.group(1)),"diameter":n(sm2.group(2)),"position":"left"})
    keyw=_first([rf"{NUM}\s*{UNIT}\s*(?:genişliğinde|genişlikte|lik|lık)?\s*(?:kama\s*)?(?:kanalı|kama)"],t,None)
    if keyw is not None:
        dep=_first([rf"(?:derinliği|derinlik)\s*{NUM}",rf"{NUM}\s*{UNIT}\s*derinliğinde"],t,max(1,float(keyw)/3)); length=_first([rf"(?:uzunluk|boy)\s*{NUM}"],t,state.base.get("length",50))
        _upsert(state,"keyway",{"width":float(keyw),"depth":float(dep),"length":float(length),"x":x,"y":y,"face":face})
    tm=re.search(r"m\s*(\d+(?:[\.,]\d+)?)(?:\s*x\s*([\d\.,]+))?\s*(?:diş|vida)?",t)
    if tm and ("diş" in t or "vida" in t):
        size=f"M{tm.group(1).replace(',','.')}"; pitch=n(tm.group(2)) if tm.group(2) else None; typ="external_thread" if "dış diş" in t else "internal_thread"
        _upsert(state,typ,{"size":size,"pitch":pitch,"x":x,"y":y,"face":face})
    return state
