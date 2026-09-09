
from __future__ import annotations
from typing import Any
import io, re, math
import numpy as np
import cv2
import pytesseract
from PIL import Image, ImageOps
import fitz  # PyMuPDF

NUM = r"[-+]?\d+(?:[.,]\d+)?"

def _f(s):
    try: return float(str(s).replace(",", "."))
    except Exception: return None

def _render_pdf(data: bytes) -> np.ndarray:
    doc = fitz.open(stream=data, filetype="pdf")
    if doc.page_count < 1:
        raise ValueError("PDF içinde sayfa bulunamadı.")
    page = doc[0]
    pix = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2RGB)
    return arr

def _load_image(data: bytes, media_type: str, filename: str) -> np.ndarray:
    if media_type == "application/pdf" or filename.lower().endswith(".pdf"):
        return _render_pdf(data)
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im).convert("RGB")
    return np.array(im)

def _largest_quad(gray: np.ndarray):
    blur = cv2.GaussianBlur(gray, (5,5), 0)
    edge = cv2.Canny(blur, 50, 150)
    cnts,_ = cv2.findContours(edge, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    h,w = gray.shape[:2]
    target = h*w*0.30
    best = None
    best_area = 0
    for c in cnts:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02*peri, True)
        area = abs(cv2.contourArea(approx))
        if len(approx)==4 and area>target and area>best_area:
            best=approx.reshape(4,2).astype(np.float32); best_area=area
    return best

def _order_points(pts):
    rect=np.zeros((4,2),dtype=np.float32)
    s=pts.sum(axis=1); d=np.diff(pts,axis=1).reshape(-1)
    rect[0]=pts[np.argmin(s)]
    rect[2]=pts[np.argmax(s)]
    rect[1]=pts[np.argmin(d)]
    rect[3]=pts[np.argmax(d)]
    return rect

def _deskew_perspective(rgb: np.ndarray) -> np.ndarray:
    gray=cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    quad=_largest_quad(gray)
    if quad is None:
        return rgb
    q=_order_points(quad)
    (tl,tr,br,bl)=q
    width=int(max(np.linalg.norm(br-bl),np.linalg.norm(tr-tl)))
    height=int(max(np.linalg.norm(tr-br),np.linalg.norm(tl-bl)))
    if width<500 or height<500: return rgb
    dst=np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],dtype=np.float32)
    M=cv2.getPerspectiveTransform(q,dst)
    return cv2.warpPerspective(rgb,M,(width,height),borderValue=(255,255,255))

def _prep(rgb: np.ndarray):
    rgb=_deskew_perspective(rgb)
    h,w=rgb.shape[:2]
    max_side=max(h,w)
    if max_side>3200:
        scale=3200/max_side
        rgb=cv2.resize(rgb,(int(w*scale),int(h*scale)),interpolation=cv2.INTER_AREA)
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    clahe=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8))
    gray=clahe.apply(gray)
    th=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,35,12)
    return rgb,gray,th

def _ocr(gray: np.ndarray):
    config="--oem 3 --psm 11 -c preserve_interword_spaces=1"
    data=pytesseract.image_to_data(gray,lang="eng+tur",config=config,output_type=pytesseract.Output.DICT)
    toks=[]
    n=len(data["text"])
    for i in range(n):
        t=(data["text"][i] or "").strip()
        try: conf=float(data["conf"][i])
        except Exception: conf=-1
        if not t or conf<20: continue
        toks.append({
            "text":t,"conf":max(0,min(100,conf))/100,
            "x":int(data["left"][i]),"y":int(data["top"][i]),
            "w":int(data["width"][i]),"h":int(data["height"][i]),
        })
    text=" ".join(t["text"] for t in toks)
    return toks,text

def _norm(s: str)->str:
    s=s.replace("⌀","Ø").replace("ø","Ø").replace("Φ","Ø")
    s=s.replace("×","x").replace("X","x")
    s=re.sub(r"\s+"," ",s)
    return s

def _extract_dimensions(tokens, fulltext):
    s=_norm(fulltext)
    dims=[]
    # Explicit engineering symbols.
    pats=[
        ("diameter", rf"(?:Ø|DIA\.?|DIAM\.?)\s*({NUM})"),
        ("radius", rf"\bR\s*({NUM})"),
        ("thread", rf"\bM\s*({NUM})(?:\s*[xX]\s*({NUM}))?"),
        ("pcd", rf"(?:PCD|P\.C\.D\.?|BCD)\s*(?:Ø\s*)?({NUM})"),
        ("chamfer", rf"({NUM})\s*[xX]\s*45\s*°"),
    ]
    for kind,pat in pats:
        for m in re.finditer(pat,s,re.I):
            vals=[_f(v) for v in m.groups() if v is not None]
            dims.append({"kind":kind,"values":vals,"raw":m.group(0),"confidence":0.94})
    # Quantity x diameter, e.g. 6xØ10 or 6 x 10 THRU
    for m in re.finditer(rf"\b(\d+)\s*[xX]\s*(?:Ø\s*)?({NUM})\b",s,re.I):
        q=int(m.group(1)); d=_f(m.group(2))
        if q<=100 and d and d>0:
            dims.append({"kind":"qty_diameter","values":[q,d],"raw":m.group(0),"confidence":0.90})
    # Plain numeric OCR tokens are candidates for overall/linear dims.
    plain=[]
    for t in tokens:
        m=re.fullmatch(NUM,t["text"].replace(" ",""))
        if m:
            v=_f(m.group(0))
            if v and 0<v<100000:
                plain.append({"value":v,"confidence":t["conf"],"x":t["x"],"y":t["y"],"w":t["w"],"h":t["h"]})
    return dims,plain

def _detect_geometry(gray: np.ndarray):
    edges=cv2.Canny(gray,50,150,apertureSize=3)
    lines=cv2.HoughLinesP(edges,1,np.pi/180,threshold=80,minLineLength=50,maxLineGap=8)
    horiz=[];vert=[]
    if lines is not None:
        for l in lines[:,0,:]:
            x1,y1,x2,y2=map(int,l)
            ang=abs(math.degrees(math.atan2(y2-y1,x2-x1)))
            length=math.hypot(x2-x1,y2-y1)
            if ang<8 or ang>172: horiz.append((x1,y1,x2,y2,length))
            elif 82<ang<98: vert.append((x1,y1,x2,y2,length))
    blur=cv2.medianBlur(gray,5)
    circles=cv2.HoughCircles(blur,cv2.HOUGH_GRADIENT,dp=1.2,minDist=25,param1=100,param2=32,minRadius=5,maxRadius=0)
    circ=[]
    if circles is not None:
        for c in np.round(circles[0]).astype(int):
            circ.append({"x":int(c[0]),"y":int(c[1]),"r":int(c[2])})
    return {"horizontal_lines":len(horiz),"vertical_lines":len(vert),"circles":circ}

def _unique(vals, rel=0.02):
    out=[]
    for v in vals:
        if v is None: continue
        if not any(abs(v-x)<=max(0.1,abs(x)*rel) for x in out):
            out.append(v)
    return out

def _infer_state(dims, plain, geom, text):
    """
    Deterministic, conservative reconstruction.
    Broad families supported; missing data is surfaced instead of fabricated.
    """
    textn=_norm(text)
    diameters=_unique([d["values"][0] for d in dims if d["kind"]=="diameter" and d["values"]])
    radii=_unique([d["values"][0] for d in dims if d["kind"]=="radius" and d["values"]])
    pcds=_unique([d["values"][0] for d in dims if d["kind"]=="pcd" and d["values"]])
    qtydia=[d for d in dims if d["kind"]=="qty_diameter"]
    threads=[d for d in dims if d["kind"]=="thread"]
    chamfers=[d for d in dims if d["kind"]=="chamfer"]
    linear=_unique([p["value"] for p in plain if p["confidence"]>=0.45])
    linear_sorted=sorted(linear,reverse=True)

    # Exclude values already clearly used as diameters/radii/pcd from overall candidates.
    used=set(round(v,4) for v in diameters+radii+pcds)
    overall=[v for v in linear_sorted if round(v,4) not in used and v>1]

    features=[]
    missing=[]
    blocking=[]
    interpretation=[]
    name="teknik_resim_parcasi"

    # Classification.
    circular_evidence=len(geom["circles"])>=2 or len(diameters)>=2
    turned_evidence=len(diameters)>=2 and any(k in textn.lower() for k in ["shaft","mil","burç","bushing","spacer","ring","flan","flange"])
    plate_evidence=len(geom["horizontal_lines"])>=4 and len(geom["vertical_lines"])>=4

    if turned_evidence and len(overall)>=1:
        total=overall[0]
        # Conservative revolved profile: only create if axial segment lengths can be determined.
        # If multiple diameters exist but segment lengths are unclear, ask instead of inventing.
        if len(diameters)==1:
            base={"type":"cylinder","diameter":diameters[0],"length":total}
            interpretation.append(f"Dönel parça: Ø{diameters[0]} x {total} mm ana gövde.")
        else:
            missing.append({
                "id":"turned_profile_segments","label":"Kademeli dönel parçanın eksen boyunca kademe boyları",
                "unit":"mm","kind":"text","paths":[],
                "reason":"Birden fazla çap okundu ancak kademe boyları güvenilir biçimde eşleştirilemedi."
            })
            blocking.append("Birden fazla çap var; kademe boyları görünüşlerle eşleştirilmeli.")
            # Use envelope only as preview, not buildable final.
            base={"type":"cylinder","diameter":max(diameters),"length":total}
            interpretation.append("Dönel parça zarfı oluşturuldu; kademe boyları tamamlanmalı.")
    elif circular_evidence and diameters:
        od=max(diameters)
        thickness=overall[0] if overall else None
        if thickness is None:
            base={"type":"flange","diameter":od,"thickness":10}
            missing.append({"id":"thickness","label":"Parça kalınlığı","unit":"mm","kind":"number","paths":["state.base.thickness"],"reason":"Kalınlık okunamadı."})
            blocking.append("Kalınlık okunamadı.")
        else:
            base={"type":"flange","diameter":od,"thickness":thickness}
        interpretation.append(f"Dairesel/flanş tipi ana geometri Ø{od} mm olarak algılandı.")
        # Smaller explicit diameter may be center hole.
        smaller=[d for d in diameters if d<od*0.9]
        if smaller:
            features.append({"type":"through_hole","diameter":min(smaller),"face":"top","placement":{"mode":"semantic","position":"center"}})
        if pcds and qtydia:
            q,d=qtydia[0]["values"]
            features.append({"type":"circular_hole_pattern","hole_diameter":d,"quantity":int(q),"pcd":pcds[0],"face":"top"})
    else:
        # Prismatic family. Pick top 3 distinct largest plausible overall dimensions.
        # This is conservative: if only 2 are clear, ask for the third.
        vals=overall[:]
        # If no symbol dimensions, plain dimensions are all we have.
        if len(vals)<3:
            vals=linear_sorted[:]
        vals=_unique(vals)
        chosen=vals[:3]
        while len(chosen)<3:
            chosen.append(None)
        x,y,z=chosen[0],chosen[1],chosen[2]
        base={"type":"block","x":x or 100,"y":y or 60,"z":z or 10}
        labels=[("x","Toplam uzunluk",x),("y","Toplam genişlik",y),("z","Kalınlık/Yükseklik",z)]
        for key,label,val in labels:
            if val is None:
                reason=f"{label} net okunamadı."
                missing.append({"id":f"base_{key}","label":label,"unit":"mm","kind":"number","paths":[f"state.base.{key}"],"reason":reason})
                blocking.append(reason)
        interpretation.append("Prizmatik/plaka/blok tipi ana geometri algılandı.")

        # Explicit qty x diameter => repeated holes. Without reliable placement, ask for pattern.
        if qtydia:
            q,d=qtydia[0]["values"]
            if pcds:
                features.append({"type":"circular_hole_pattern","hole_diameter":d,"quantity":int(q),"pcd":pcds[0],"face":"top"})
            elif int(q)==1:
                features.append({"type":"through_hole","diameter":d,"face":"top","placement":{"mode":"semantic","position":"center"}})
            else:
                # If image geometry sees exactly q circular holes, use semantic symmetric placeholder only when q==2.
                if int(q)==2 and len(geom["circles"])>=2:
                    features += [
                        {"type":"through_hole","diameter":d,"face":"top","placement":{"mode":"semantic","position":"left"}},
                        {"type":"through_hole","diameter":d,"face":"top","placement":{"mode":"semantic","position":"right"}},
                    ]
                    blocking.append("İki deliğin gerçek merkez mesafesi/kenar mesafeleri ayrıca doğrulanmalı.")
                else:
                    reason=f"{int(q)} adet Ø{d} deliğin yerleşimi/merkez ölçüleri net eşleştirilemedi."
                    missing.append({"id":"hole_pattern_position","label":"Delik yerleşimi/merkez ölçüleri","unit":"mm","kind":"text","paths":[],"reason":reason})
                    blocking.append(reason)

    # Threads and finishing metadata as non-geometric features for drawing/export notes.
    for th in threads:
        size=th["values"][0]; pitch=th["values"][1] if len(th["values"])>1 else None
        features.append({"type":"internal_thread","size":f"M{size:g}","pitch":pitch or 0})
    for ch in chamfers[:2]:
        dist=ch["values"][0]
        if dist:
            features.append({"type":"chamfer","distance":dist,"target":"top_outer"})

    state={"part_name":name,"base":base,"features":features}
    return state,missing,blocking,interpretation

def _dimension_rows(dims, plain):
    out=[]
    for d in dims:
        if d["kind"]=="diameter":
            out.append({"label":"Çap","value":d["values"][0],"unit":"mm","confidence":d["confidence"]})
        elif d["kind"]=="radius":
            out.append({"label":"Radyüs","value":d["values"][0],"unit":"mm","confidence":d["confidence"]})
        elif d["kind"]=="pcd":
            out.append({"label":"PCD","value":d["values"][0],"unit":"mm","confidence":d["confidence"]})
        elif d["kind"]=="qty_diameter":
            out.append({"label":f"{int(d['values'][0])} adet delik çapı","value":d["values"][1],"unit":"mm","confidence":d["confidence"]})
        elif d["kind"]=="chamfer":
            out.append({"label":"Pah","value":d["values"][0],"unit":"mm","confidence":d["confidence"]})
    # Show strongest plain dimension candidates too.
    for p in sorted(plain,key=lambda x:x["confidence"],reverse=True)[:20]:
        out.append({"label":"Lineer ölçü","value":p["value"],"unit":"mm","confidence":round(p["confidence"],3)})
    return out

def validate_local_analysis(result: dict[str,Any]) -> dict[str,Any]:
    result.setdefault("blocking_ambiguities",[])
    result.setdefault("missing_inputs",[])
    result.setdefault("warnings",[])
    result.setdefault("dimensions",[])
    result.setdefault("interpretation",[])
    state=result.get("state")
    if not state:
        result["geometry_completeness"]=0.0
        result["reading_confidence"]=0.0
        result["can_build"]=False
        return result
    total=0; present=0
    base=state.get("base") or {}
    req={
      "cylinder":["diameter","length"],"flange":["diameter","thickness"],
      "tube":["outer_diameter","inner_diameter","length"],"block":["x","y","z"],
      "revolved_profile":["stations"]
    }.get(base.get("type"),[])
    for k in req:
        total+=1
        if base.get(k) not in (None,"",[]): present+=1
    feature_req={
      "through_hole":["diameter"],"blind_hole":["diameter","depth"],
      "circular_hole_pattern":["hole_diameter","quantity","pcd"],
      "linear_hole_pattern":["hole_diameter","quantity","spacing"],
      "pocket":["width","height","depth"],"slot":["length","width","depth"],
      "chamfer":["distance"],"fillet":["radius"],"shaft_step":["diameter","length"]
    }
    for f in state.get("features") or []:
        for k in feature_req.get(f.get("type"),[]):
            total+=1
            if f.get(k) not in (None,"",[]):present+=1
    comp=1.0 if total==0 else present/total
    if result["blocking_ambiguities"] or result["missing_inputs"]:
        comp=min(comp,0.99)
    ds=[float(d.get("confidence",0.7)) for d in result["dimensions"] if d.get("value") is not None]
    reading=sum(ds)/len(ds) if ds else 0.55
    result["geometry_completeness"]=round(comp,4)
    result["reading_confidence"]=round(reading,4)
    result["confidence"]=round(0.55*reading+0.45*comp,4)
    result["can_build"]=bool(comp>=0.999 and not result["blocking_ambiguities"] and not result["missing_inputs"])
    result["engine"]="VoiceCAD Local Vision Engine"
    return result

def analyze_drawing_bytes(data: bytes, media_type: str, filename: str) -> dict[str,Any]:
    rgb=_load_image(data,media_type,filename)
    rgb,gray,th=_prep(rgb)
    tokens,text=_ocr(gray)
    dims,plain=_extract_dimensions(tokens,text)
    geom=_detect_geometry(gray)
    state,missing,blocking,interp=_infer_state(dims,plain,geom,text)
    result={
      "drawing_type": state["base"].get("type","unknown"),
      "units":"mm",
      "part_name":state.get("part_name","parca"),
      "state":state,
      "dimensions":_dimension_rows(dims,plain),
      "blocking_ambiguities":blocking,
      "missing_inputs":missing,
      "warnings":[
        "Analiz tamamen yerel OCR + görüntü işleme ile yapıldı; harici AI servisine dosya gönderilmedi."
      ],
      "interpretation":interp,
      "ocr_text":text[:5000],
      "detected_geometry":{"circles":len(geom["circles"]),"horizontal_lines":geom["horizontal_lines"],"vertical_lines":geom["vertical_lines"]},
    }
    return validate_local_analysis(result)

def review_drawing_bytes(data: bytes, media_type: str, filename: str, first: dict[str,Any]) -> dict[str,Any]:
    # Independent deterministic pass: alternate threshold + consistency checks.
    rgb=_load_image(data,media_type,filename)
    _,gray,_=_prep(rgb)
    tokens,text=_ocr(cv2.GaussianBlur(gray,(3,3),0))
    dims,plain=_extract_dimensions(tokens,text)
    second_values=set(round(float(d["value"]),3) for d in _dimension_rows(dims,plain) if d.get("value") is not None)
    first_values=set(round(float(d["value"]),3) for d in first.get("dimensions",[]) if d.get("value") is not None)
    overlap=len(first_values & second_values)/max(1,len(first_values))
    out=json_clone(first)
    out.setdefault("warnings",[])
    out["verification_status"]="passed" if overlap>=0.65 else "needs_review"
    if overlap>=0.65:
        out["warnings"].append(f"Yerel ikinci okuma kontrolü geçti (ölçü eşleşmesi %{round(overlap*100)}).")
    else:
        out["warnings"].append(f"Yerel ikinci okuma ölçü eşleşmesi düşük (%{round(overlap*100)}); fotoğrafı daha düz/net yükleyin.")
        out.setdefault("blocking_ambiguities",[]).append("İki bağımsız OCR geçişi yeterince uyuşmadı.")
    return validate_local_analysis(out)

def json_clone(x):
    import json
    return json.loads(json.dumps(x))
