from __future__ import annotations
import os, json, base64, re, urllib.request, urllib.error, io
from typing import Any
from PIL import Image, ImageOps

SYSTEM_PROMPT = r'''
You are a senior mechanical design engineer converting manufacturing technical drawings into a constrained parametric CAD schema.
Your job is NOT OCR-only. Reconstruct the manufacturable solid by interpreting orthographic views, section views, centerlines, dimensions, diameter/radius/thread symbols, hole patterns, repeated/symmetric features and geometric relationships.

Before returning JSON, silently perform this engineering checklist:
1) identify the single manufactured part and its manufacturing family (turned/prismatic/sheet/assembly);
2) identify front/top/side/section/detail views and do not count the same feature twice;
3) read overall dimensions first, then segment/feature dimensions;
4) reconcile repeated dimensions and symmetry/centerline information;
5) distinguish Ø diameter, R radius, M thread, PCD/bolt circle, depth, quantity, chamfer and tolerance callouts;
6) verify that every CAD feature is supported by an explicit printed dimension or an exact mathematical derivation from printed dimensions;
7) ensure the proposed CAD state can describe the same solid from every view.

ABSOLUTE RULES:
- Never invent a dimension. If a required dimension is missing, unreadable, contradictory, or only inferable by scale from the image, put it in blocking_ambiguities.
- Do not estimate dimensions from pixels or visual proportions.
- Distinguish dimensions from tolerances, surface finish, drawing numbers and notes.
- Use millimetres unless the drawing explicitly states another unit. If not mm, convert numeric geometry to mm and report original unit.
- The resulting CAD state must only use supported schema below.
- A STEP model is allowed only if all geometry-defining dimensions needed by the chosen schema are explicit and mutually consistent.
- If the drawing has multiple parts, set can_build=false and explain which item needs selection.
- If a photo is skewed/blurred/cropped so a dimension cannot be trusted, mark it ambiguous.
- If there are duplicate dimensions that disagree, mark them blocking.
- When a geometry-defining value is missing but the rest of that feature is known, KEEP that feature in state with the missing numeric value as null.
- For each such missing value, create a missing_inputs entry. If one entered value applies to multiple identical features, use "paths" with all JSON paths.
- JSON paths must start with state. Example: state.features.0.diameter
- You may mathematically derive centered X/Y coordinates ONLY from explicitly printed overall dimensions and explicitly printed edge/center distances. Never derive from image scale.

SUPPORTED CAD STATE:
{
  "part_name": "string",
  "base": one of:
    {"type":"cylinder","diameter":number,"length":number},
    {"type":"flange","diameter":number,"thickness":number},
    {"type":"tube","outer_diameter":number,"inner_diameter":number,"length":number},
    {"type":"block","x":number,"y":number,"z":number},
    {"type":"revolved_profile","stations":[{"z":number,"diameter":number}, ...]},
  "features": [
    {"type":"through_hole","diameter":number|null,"face":"top", "placement":{"mode":"semantic","position":"center|left|right|top|bottom|top_left|top_right|bottom_left|bottom_right"} OR {"mode":"point","x":number,"y":number}},
    {"type":"blind_hole","diameter":number,"depth":number,"face":"top", "placement":...},
    {"type":"countersink_hole","diameter":number,"countersink_diameter":number,"angle":number,"face":"top","placement":...},
    {"type":"counterbore_hole","diameter":number,"counterbore_diameter":number,"counterbore_depth":number,"face":"top","placement":...},
    {"type":"circular_hole_pattern","hole_diameter":number,"quantity":integer,"pcd":number,"face":"top"},
    {"type":"linear_hole_pattern","hole_diameter":number,"quantity":integer,"spacing":number,"axis":"x|y","face":"top","placement":...},
    {"type":"pocket","width":number,"height":number,"depth":number,"face":"top","placement":...},
    {"type":"slot","length":number,"width":number,"depth":number,"angle":number,"face":"top","placement":...},
    {"type":"keyway","width":number,"depth":number,"length":number,"face":"top","placement":...},
    {"type":"chamfer","distance":number,"target":"top_outer|bottom_outer|both_outer"},
    {"type":"fillet","radius":number,"target":"vertical|top"},
    {"type":"shaft_step","diameter":number,"length":number,"position":"right|left"},
    {"type":"internal_thread","size":"M8","pitch":number},
    {"type":"external_thread","size":"M8","pitch":number}
  ]
}

For axisymmetric turned parts prefer revolved_profile. Its stations define the OUTER diameter at axial z locations. Repeat z values when a vertical shoulder is required, e.g. [{z:0,diameter:50},{z:40,diameter:50},{z:40,diameter:30},{z:70,diameter:30}]. z must start at 0 and end at total length.

RETURN ONLY valid JSON with exactly this top-level structure:
{
  "can_build": true|false,
  "confidence": 0.0-1.0,  // visual-reading confidence only; application will independently compute geometry completeness
  "drawing_type": "turned|prismatic|sheet|assembly|unknown",
  "part_name": "...",
  "units": "mm",
  "state": {...} or null,
  "dimensions": [
    {"label":"...", "value":number|null, "unit":"mm", "kind":"diameter|length|radius|angle|thread|pcd|other", "source_view":"front|top|side|section|note|unknown", "confidence":0.0-1.0}
  ],
  "blocking_ambiguities": ["..."],
  "missing_inputs": [
    {
      "id":"short_unique_id",
      "label":"Kullanıcıya Türkçe soru/etiket",
      "unit":"mm",
      "kind":"number",
      "paths":["state.features.0.diameter"],
      "reason":"blocking_ambiguities içinde AYNI metin"
    }
  ],
  "warnings": ["..."],
  "interpretation": ["short Turkish explanation of geometry inferred from explicit dimensions"]
}
'''


def _strip_json(text: str) -> str:
    text=text.strip()
    if text.startswith('```'):
        text=re.sub(r'^```(?:json)?\s*','',text)
        text=re.sub(r'\s*```$','',text)
    a=text.find('{'); b=text.rfind('}')
    return text[a:b+1] if a>=0 and b>a else text


def _prepare_image_for_ai(data: bytes, media_type: str) -> tuple[bytes, str]:
    """Teknik resmi ana analiz için yüksek okunabilirlikte normalize eder."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            max_side = max(im.size)
            if max_side > 2600:
                scale = 2600.0 / max_side
                im = im.resize(
                    (max(1, int(im.width * scale)), max(1, int(im.height * scale))),
                    Image.Resampling.LANCZOS,
                )
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=91, optimize=True, progressive=True)
            return out.getvalue(), "image/jpeg"
    except Exception:
        return data, media_type


def _prepare_image_variants(data: bytes, media_type: str) -> list[tuple[bytes, str, str]]:
    """
    Tam sayfa + okunabilir yakın planlar üretir.
    Teknik resimlerde küçük ölçü rakamlarının tek küçültülmüş görüntüde kaybolmasını azaltır.
    """
    try:
        with Image.open(io.BytesIO(data)) as source:
            im = ImageOps.exif_transpose(source).convert("RGB")

            # Tam sayfa
            full = im.copy()
            max_side = max(full.size)
            if max_side > 2400:
                scale = 2400.0 / max_side
                full = full.resize(
                    (max(1, int(full.width * scale)), max(1, int(full.height * scale))),
                    Image.Resampling.LANCZOS,
                )

            variants = [("tam teknik resim", full)]

            # 4 bindirmeli bölge. Ölçü yazıları için kırpılmış görüntüler daha yüksek efektif çözünürlük sağlar.
            w, h = im.size
            if w >= 1200 or h >= 1200:
                overlap = 0.10
                boxes = [
                    ("sol üst yakın plan", (0, 0, int(w*(0.55+overlap)), int(h*(0.55+overlap)))),
                    ("sağ üst yakın plan", (int(w*(0.45-overlap)), 0, w, int(h*(0.55+overlap)))),
                    ("sol alt yakın plan", (0, int(h*(0.45-overlap)), int(w*(0.55+overlap)), h)),
                    ("sağ alt yakın plan", (int(w*(0.45-overlap)), int(h*(0.45-overlap)), w, h)),
                ]
                for label, box in boxes:
                    crop = im.crop(box)
                    cmax = max(crop.size)
                    if cmax > 1800:
                        scale = 1800.0 / cmax
                        crop = crop.resize(
                            (max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
                            Image.Resampling.LANCZOS,
                        )
                    variants.append((label, crop))

            encoded=[]
            for label, img in variants:
                out=io.BytesIO()
                img.save(out, format="JPEG", quality=90, optimize=True)
                encoded.append((out.getvalue(), "image/jpeg", label))
            return encoded
    except Exception:
        return [(data, media_type, "teknik resim")]


def _image_sources(data: bytes, media_type: str, filename: str) -> list[dict[str, Any]]:
    if media_type == "application/pdf" or filename.lower().endswith(".pdf"):
        b64=base64.standard_b64encode(data).decode("ascii")
        return [{"type":"document","source":{"type":"base64","media_type":"application/pdf","data":b64}}]

    sources=[]
    for blob, mt, label in _prepare_image_variants(data, media_type):
        sources.append({"type":"text","text":f"Görüntü: {label}"})
        sources.append({
            "type":"image",
            "source":{"type":"base64","media_type":mt if mt in ("image/jpeg","image/png","image/webp","image/gif") else "image/jpeg","data":base64.standard_b64encode(blob).decode("ascii")}
        })
    return sources


def _geometry_completeness(result: dict[str, Any]) -> float:
    """STEP'i tanımlamak için gereken alanların ne kadarının mevcut olduğunu deterministik hesaplar."""
    state=result.get("state")
    if not state:
        return 0.0
    required=[]
    base=state.get("base") or {}
    base_req={
        "cylinder":["diameter","length"],
        "flange":["diameter","thickness"],
        "tube":["outer_diameter","inner_diameter","length"],
        "block":["x","y","z"],
        "revolved_profile":["stations"],
    }
    for k in base_req.get(base.get("type"), []):
        required.append(base.get(k) not in (None,"",[]))

    feature_req={
        "through_hole":["diameter"],
        "blind_hole":["diameter","depth"],
        "countersink_hole":["diameter","countersink_diameter","angle"],
        "counterbore_hole":["diameter","counterbore_diameter","counterbore_depth"],
        "circular_hole_pattern":["hole_diameter","quantity","pcd"],
        "linear_hole_pattern":["hole_diameter","quantity","spacing"],
        "pocket":["width","height","depth"],
        "slot":["length","width","depth"],
        "keyway":["width","depth","length"],
        "chamfer":["distance"],
        "fillet":["radius"],
        "shaft_step":["diameter","length"],
    }
    for f in state.get("features") or []:
        for k in feature_req.get(f.get("type"), []):
            required.append(f.get(k) not in (None,"",[]))

    if not required:
        return 1.0 if state else 0.0
    return sum(1 for x in required if x) / len(required)


def _dimension_reading_confidence(result: dict[str, Any]) -> float:
    dims=[d for d in (result.get("dimensions") or []) if d.get("value") is not None]
    if not dims:
        return float(result.get("confidence",0) or 0)
    vals=[]
    for d in dims:
        try: vals.append(max(0.0,min(1.0,float(d.get("confidence",0.85) or 0.85))))
        except Exception: vals.append(0.85)
    return sum(vals)/len(vals)


def rescore_analysis(result: dict[str, Any], cad_validated: bool=False, verification_passed: bool=False) -> dict[str, Any]:
    """
    AI'nin tek bir keyfi yüzdesine güvenmez.
    - geometry_completeness: CAD şemasındaki zorunlu ölçülerin tamamlanması
    - reading_confidence: tek tek okunan ölçülerin ortalama görsel güveni
    - confidence: uygulamanın kalibre edilmiş birleşik güveni
    """
    completeness=_geometry_completeness(result)
    reading=_dimension_reading_confidence(result)

    # Bloklayıcı belirsizlik/missing input varsa tamamlık buna göre sınırlandırılır.
    if result.get("blocking_ambiguities") or result.get("missing_inputs"):
        completeness=min(completeness, 0.99)

    cad_score=1.0 if cad_validated else (0.92 if completeness >= 0.999 else 0.75)
    review_score=1.0 if verification_passed else 0.94

    # Net, tamamlanmış ve CAD doğrulanmış resimlerde "model tamamlığı" %100 olabilir.
    # Görsel okuma güveni yine ayrı kalır.
    calibrated = 0.45*reading + 0.30*completeness + 0.15*cad_score + 0.10*review_score
    if result.get("blocking_ambiguities"):
        calibrated=min(calibrated,0.70)
    if result.get("missing_inputs"):
        calibrated=min(calibrated,0.75)

    result["geometry_completeness"]=round(max(0,min(1,completeness)),4)
    result["reading_confidence"]=round(max(0,min(1,reading)),4)
    result["confidence"]=round(max(0,min(1,calibrated)),4)
    result["cad_validated"]=bool(cad_validated)
    return result


def test_anthropic_connection() -> dict[str, Any]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY tanımlı değil.")
    model = os.getenv("ANTHROPIC_FAST_MODEL", "claude-haiku-4-5-20251001").strip()
    payload = {
        "model": model,
        "max_tokens": 20,
        "messages": [{"role": "user", "content": "Reply only with OK"}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return {"ok": True, "model": model, "response": "".join(
            c.get("text", "") for c in body.get("content", []) if c.get("type") == "text"
        )}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Anthropic API hatası ({e.code}): {detail[:800]}") from e
    except Exception as e:
        raise RuntimeError(f"Anthropic bağlantı testi başarısız: {e}") from e


def _anthropic_message(api_key:str, model:str, source, text:str, max_tokens:int=9000) -> str:
    sources = source if isinstance(source, list) else [source]
    payload={
        "model":model,"max_tokens":max_tokens,"system":SYSTEM_PROMPT,
        "messages":[{"role":"user","content":sources+[{"type":"text","text":text}]}]
    }
    req=urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),method="POST",
        headers={"content-type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"}
    )
    try:
        with urllib.request.urlopen(req,timeout=int(os.getenv('ANTHROPIC_HTTP_TIMEOUT','120'))) as resp:
            body=json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail=e.read().decode("utf-8",errors="replace")
        raise RuntimeError(f"Anthropic API hatası ({e.code}): {detail[:1000]}") from e
    except Exception as e:
        raise RuntimeError(f"AI servisine bağlanılamadı: {e}") from e
    return "".join(c.get("text","") for c in body.get("content",[]) if c.get("type")=="text")


def analyze_drawing_bytes(data: bytes, media_type: str, filename: str, verify: bool=False) -> dict[str, Any]:
    api_key=os.getenv('ANTHROPIC_API_KEY','').strip()
    if not api_key:
        raise RuntimeError('ANTHROPIC_API_KEY tanımlı değil. Render Environment bölümüne API anahtarını ekleyin.')

    # Teknik resimde doğruluk öncelikli. Küçük model yerine Sonnet varsayılan.
    model=os.getenv('ANTHROPIC_DRAWING_MODEL', os.getenv('ANTHROPIC_REVIEW_MODEL','claude-sonnet-5')).strip()
    sources=_image_sources(data, media_type, filename)

    user_text=(
        'Bu dosya bir üretim teknik resmidir. Hızdan önce doğruluğa öncelik ver. '
        'Tam sayfa görüntüsü ve varsa yakın planlar AYNI teknik resmin farklı görünümleridir; bunları farklı parçalar sanma. '
        'Tüm ortografik/kesit/detay görünüşlerini birlikte incele. '
        'Önce parçanın üretilebilir ana katısını tanımla, sonra tüm delik/cep/kanal/pah/radyüs/diş özelliklerini ekle. '
        'Her ölçü için çizimde gerçekten basılı olan değeri kullan; ölçekten tahmin etme. '
        'Aynı ölçüyü birden fazla yakın planda görürsen tutarlılık kontrolü yap. '
        'Çizim açık ve tüm geometri-defining ölçüler mevcutsa bunları eksiksiz CAD state içine yerleştir. '
        'Eksik/geçersiz ölçü varsa kesinlikle tahmin etme ve missing_inputs üret. '
        'JSON döndürmeden önce tüm görünüşlerin aynı 3D parçayı tarif ettiğini tekrar kontrol et. '
        f'Dosya adı: {filename}'
    )
    raw=_anthropic_message(api_key,model,sources,user_text,3600)
    first=json.loads(_strip_json(raw))
    first=rescore_analysis(first, cad_validated=False, verification_passed=False)
    if verify:
        return review_drawing_bytes(data, media_type, filename, first)
    return first

def review_drawing_bytes(data: bytes, media_type: str, filename: str, first: dict[str, Any]) -> dict[str, Any]:
    api_key=os.getenv('ANTHROPIC_API_KEY','').strip()
    if not api_key:
        raise RuntimeError('ANTHROPIC_API_KEY tanımlı değil.')
    model=os.getenv('ANTHROPIC_REVIEW_MODEL','claude-sonnet-5').strip()
    source=_image_sources(data, media_type, filename)
    reviewer = '''You are the independent checking engineer. Re-read the SAME drawing from scratch and audit the proposed extraction below.
Look specifically for: missed dimensions, diameter vs radius confusion, overall vs segment length confusion, section-view mistakes, wrong hole counts/PCD, thread callouts, tolerance values accidentally used as nominal dimensions, and dimensions inferred from scale rather than printed values.
Never preserve a questionable value just because the first engineer proposed it. If any geometry-defining value cannot be explicitly verified from the drawing, add a blocking ambiguity and set can_build=false.
Return the COMPLETE corrected JSON in exactly the same schema as the first extraction, and nothing else.'''
    review_text=_anthropic_message(api_key,model,source,reviewer+'\n\nFIRST ENGINEER JSON:\n'+json.dumps(first,ensure_ascii=False),4200)
    try:
        reviewed=json.loads(_strip_json(review_text))
        reviewed.setdefault('warnings',[])
        reviewed['warnings'].append('Bağımsız ikinci AI mühendislik kontrolü tamamlandı.')
        reviewed['verification_status']='passed'
        return rescore_analysis(reviewed, cad_validated=False, verification_passed=True)
    except Exception:
        fallback=json.loads(json.dumps(first))
        fallback.setdefault('warnings',[])
        fallback['warnings'].append('İkinci AI kontrolü geçerli JSON üretemedi. İlk analiz korundu; ölçüleri kullanıcı onayıyla tamamlayabilirsiniz.')
        fallback['verification_status']='failed'
        return rescore_analysis(fallback, cad_validated=False, verification_passed=False)


def validate_analysis(result: dict[str,Any]) -> dict[str,Any]:
    result.setdefault('blocking_ambiguities',[]); result.setdefault('warnings',[]); result.setdefault('dimensions',[]); result.setdefault('interpretation',[]); result.setdefault('missing_inputs',[])
    c=float(result.get('confidence',0) or 0); result['confidence']=max(0,min(1,c))
    state=result.get('state')
    if not state:
        result['can_build']=False
        return result
    base=state.get('base') or {}; typ=base.get('type')
    required={
      'cylinder':['diameter','length'],'flange':['diameter','thickness'],'tube':['outer_diameter','inner_diameter','length'],'block':['x','y','z'],'revolved_profile':['stations']
    }
    if typ not in required:
        result['blocking_ambiguities'].append(f'Desteklenmeyen taban geometrisi: {typ}')
    else:
        for k in required[typ]:
            if k not in base or base[k] in (None,'',[]): result['blocking_ambiguities'].append(f'Eksik temel ölçü: {k}')
    # Feature seviyesinde zorunlu geometrik alanları doğrula.
    feature_required={
      'through_hole':['diameter'],
      'blind_hole':['diameter','depth'],
      'countersink_hole':['diameter','countersink_diameter','angle'],
      'counterbore_hole':['diameter','counterbore_diameter','counterbore_depth'],
      'circular_hole_pattern':['hole_diameter','quantity','pcd'],
      'linear_hole_pattern':['hole_diameter','quantity','spacing'],
      'pocket':['width','height','depth'],
      'slot':['length','width','depth'],
      'keyway':['width','depth','length'],
      'chamfer':['distance'],
      'fillet':['radius'],
      'shaft_step':['diameter','length'],
    }
    for i,f in enumerate((state.get('features') or [])):
        ft=f.get('type')
        for k in feature_required.get(ft,[]):
            if k not in f or f.get(k) in (None,'',[]):
                msg=f"Eksik feature ölçüsü: {ft}.{k}"
                # AI daha açıklayıcı bir blocking ambiguity verdiyse bunu ayrıca çoğaltma.
                if not result.get('missing_inputs') and msg not in result['blocking_ambiguities']:
                    result['blocking_ambiguities'].append(msg)

    if typ=='revolved_profile' and base.get('stations'):
        sts=base['stations']
        try:
            if len(sts)<2: raise ValueError()
            zs=[float(s['z']) for s in sts]; ds=[float(s['diameter']) for s in sts]
            if abs(zs[0])>1e-6: result['blocking_ambiguities'].append('Revolved profile z=0 ile başlamıyor.')
            if any(zs[i]>zs[i+1] for i in range(len(zs)-1)): result['blocking_ambiguities'].append('Revolved profile z istasyonları sıralı değil.')
            if any(d<=0 for d in ds): result['blocking_ambiguities'].append('Revolved profile çaplarından biri geçersiz.')
        except Exception: result['blocking_ambiguities'].append('Revolved profile istasyonları geçersiz.')
    # can_build değerini eski AI cevabından miras alma; mevcut, çözülmüş geometriye göre yeniden hesapla.
    geometry_complete = not result['blocking_ambiguities'] and not result.get('missing_inputs')
    # STEP kilidi artık modelin keyfi tek güven yüzdesine değil, geometrik tamamlığa bağlı.
    result['can_build'] = bool(geometry_complete)
    result['state']=state
    result=rescore_analysis(
        result,
        cad_validated=bool(result.get('cad_validated')),
        verification_passed=result.get('verification_status')=='passed'
    )
    return result
