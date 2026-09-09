from __future__ import annotations
import os, json, base64, re, urllib.request, urllib.error
from typing import Any

SYSTEM_PROMPT = r'''
You are a senior mechanical design engineer converting manufacturing technical drawings into a constrained parametric CAD schema.
Your job is NOT OCR-only. Interpret orthographic views, section views, centerlines, dimensions, diameter/radius/thread symbols, hole patterns and geometric relationships.

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
    {"type":"through_hole","diameter":number,"face":"top", "placement":{"mode":"semantic","position":"center|left|right|top|bottom|top_left|top_right|bottom_left|bottom_right"}},
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
  "confidence": 0.0-1.0,
  "drawing_type": "turned|prismatic|sheet|assembly|unknown",
  "part_name": "...",
  "units": "mm",
  "state": {...} or null,
  "dimensions": [
    {"label":"...", "value":number|null, "unit":"mm", "kind":"diameter|length|radius|angle|thread|pcd|other", "source_view":"front|top|side|section|note|unknown", "confidence":0.0-1.0}
  ],
  "blocking_ambiguities": ["..."],
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


def _anthropic_message(api_key:str, model:str, source:dict, text:str, max_tokens:int=9000) -> str:
    payload={
        "model":model,"max_tokens":max_tokens,"system":SYSTEM_PROMPT,
        "messages":[{"role":"user","content":[source,{"type":"text","text":text}]}]
    }
    req=urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),method="POST",
        headers={"content-type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"}
    )
    try:
        with urllib.request.urlopen(req,timeout=75) as resp:
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
    model=os.getenv('ANTHROPIC_MODEL','claude-sonnet-5').strip()
    b64=base64.standard_b64encode(data).decode('ascii')
    if media_type == 'application/pdf' or filename.lower().endswith('.pdf'):
        source={"type":"document","source":{"type":"base64","media_type":"application/pdf","data":b64}}
    else:
        mt=media_type if media_type in ('image/jpeg','image/png','image/webp','image/gif') else 'image/jpeg'
        source={"type":"image","source":{"type":"base64","media_type":mt,"data":b64}}
    user_text=(
        'Bu dosya bir üretim teknik resmi veya teknik resim fotoğrafıdır. '
        'Tüm görünüşleri birlikte incele. Ölçüleri ve geometrik ilişkileri çıkar. '
        'Eksik/geçersiz ölçü varsa kesinlikle tahmin etme. Desteklenen CAD şemasına dönüştür. '
        f'Dosya adı: {filename}'
    )
    text=_anthropic_message(api_key,model,source,user_text,9000)
    first=json.loads(_strip_json(text))

    if verify:
        return review_drawing_bytes(data, media_type, filename, first)
    return first


def review_drawing_bytes(data: bytes, media_type: str, filename: str, first: dict[str, Any]) -> dict[str, Any]:
    api_key=os.getenv('ANTHROPIC_API_KEY','').strip()
    if not api_key:
        raise RuntimeError('ANTHROPIC_API_KEY tanımlı değil.')
    model=os.getenv('ANTHROPIC_MODEL','claude-sonnet-5').strip()
    b64=base64.standard_b64encode(data).decode('ascii')
    if media_type == 'application/pdf' or filename.lower().endswith('.pdf'):
        source={"type":"document","source":{"type":"base64","media_type":"application/pdf","data":b64}}
    else:
        mt=media_type if media_type in ('image/jpeg','image/png','image/webp','image/gif') else 'image/jpeg'
        source={"type":"image","source":{"type":"base64","media_type":mt,"data":b64}}
    reviewer = '''You are the independent checking engineer. Re-read the SAME drawing from scratch and audit the proposed extraction below.
Look specifically for: missed dimensions, diameter vs radius confusion, overall vs segment length confusion, section-view mistakes, wrong hole counts/PCD, thread callouts, tolerance values accidentally used as nominal dimensions, and dimensions inferred from scale rather than printed values.
Never preserve a questionable value just because the first engineer proposed it. If any geometry-defining value cannot be explicitly verified from the drawing, add a blocking ambiguity and set can_build=false.
Return the COMPLETE corrected JSON in exactly the same schema as the first extraction, and nothing else.'''
    review_text=_anthropic_message(api_key,model,source,reviewer+'\n\nFIRST ENGINEER JSON:\n'+json.dumps(first,ensure_ascii=False),6000)
    reviewed=json.loads(_strip_json(review_text))
    reviewed.setdefault('warnings',[])
    reviewed['warnings'].append('Bağımsız ikinci AI mühendislik kontrolü tamamlandı.')
    return reviewed


def validate_analysis(result: dict[str,Any]) -> dict[str,Any]:
    result.setdefault('blocking_ambiguities',[]); result.setdefault('warnings',[]); result.setdefault('dimensions',[]); result.setdefault('interpretation',[])
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
    if typ=='revolved_profile' and base.get('stations'):
        sts=base['stations']
        try:
            if len(sts)<2: raise ValueError()
            zs=[float(s['z']) for s in sts]; ds=[float(s['diameter']) for s in sts]
            if abs(zs[0])>1e-6: result['blocking_ambiguities'].append('Revolved profile z=0 ile başlamıyor.')
            if any(zs[i]>zs[i+1] for i in range(len(zs)-1)): result['blocking_ambiguities'].append('Revolved profile z istasyonları sıralı değil.')
            if any(d<=0 for d in ds): result['blocking_ambiguities'].append('Revolved profile çaplarından biri geçersiz.')
        except Exception: result['blocking_ambiguities'].append('Revolved profile istasyonları geçersiz.')
    if result['blocking_ambiguities'] or result['confidence'] < 0.72:
        result['can_build']=False
        if result['confidence']<0.72: result['warnings'].append('Güven skoru STEP üretme eşiğinin altında (0.72).')
    result['state']=state
    return result
