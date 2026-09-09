from __future__ import annotations
from pathlib import Path
import json,uuid,copy,asyncio
from fastapi import FastAPI,HTTPException,UploadFile,File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from cadquery import exporters
from .cad_engine import CadState,export_files,build_model
from .drawing import create_pdf
from .parser import parse_turkish_command
from .drawing_ai import analyze_drawing_bytes,review_drawing_bytes,validate_analysis

ROOT=Path(__file__).resolve().parent.parent;OUT=ROOT/'output';OUT.mkdir(exist_ok=True)
app=FastAPI(title='VoiceCAD Studio')
class CommandIn(BaseModel): text:str; state:dict|None=None
class BuildIn(BaseModel): state:dict
@app.get('/health')
def health():return {'status':'ok'}

def _stl(state:CadState):
    job=uuid.uuid4().hex[:10];d=OUT/job;d.mkdir(parents=True,exist_ok=True);shape=build_model(state);p=d/'preview.stl';exporters.export(shape,str(p),tolerance=.05,angularTolerance=.1);return job,p

def _describe_diff(before:CadState,after:CadState,text:str):
    notes=[];ass=[];added=after.features[len(before.features):] if len(after.features)>=len(before.features) else []
    if before.base!=after.base: notes.append('Taban geometrisi güncellenecek.')
    for f in added:
        typ=f.get('type'); labels={'through_hole':'delik','blind_hole':'kör delik','chamfer':'pah','fillet':'radyüs','pocket':'cep','slot':'slot','countersink_hole':'havşa','counterbore_hole':'silindirik havşa','circular_hole_pattern':'dairesel delik dizisi','linear_hole_pattern':'doğrusal delik dizisi','shaft_step':'kademe'}
        place=f.get('placement',{}).get('position')
        pnames={'center':'merkez','left':'sol','right':'sağ','top':'üst','bottom':'alt','top_left':'sol üst','top_right':'sağ üst','bottom_left':'sol alt','bottom_right':'sağ alt'}
        notes.append(f"{labels.get(typ,typ)} eklenecek"+(f" · konum: {pnames.get(place,place)}" if place else '')+'.')
    low=text.lower()
    if added and any(f.get('type') in ('through_hole','blind_hole','pocket','slot') for f in added):
        if not any(w in low for w in ('merkez','orta','sağ','sol','üst','alt','buraya','seçili','dokun')):
            ass.append('Konum belirtilmediği için merkez önerildi. İstersen aşağıdaki konum düğmelerinden değiştirebilirsin.')
    if any(f.get('type')=='chamfer' for f in added): ass.append('Pah için varsayılan olarak üst dış kenar seçildi; istersen alt veya iki dış kenar olarak değiştirebilirsin.')
    return notes or ['Modeldeki mevcut özellikler güncellenecek.'],ass


@app.post('/api/drawing/analyze')
async def analyze_drawing(file:UploadFile=File(...)):
    try:
        data=await file.read()
        if not data: raise ValueError('Dosya boş.')
        if len(data)>20*1024*1024: raise ValueError('Dosya 20 MB sınırını aşıyor.')
        media=file.content_type or 'application/octet-stream'
        allowed=('image/jpeg','image/png','image/webp','image/gif','application/pdf')
        if media not in allowed and not (file.filename or '').lower().endswith(('.jpg','.jpeg','.png','.webp','.gif','.pdf')):
            raise ValueError('JPG, PNG, WEBP veya PDF yükleyin.')
        result=validate_analysis(await asyncio.to_thread(analyze_drawing_bytes,data,media,file.filename or 'teknik_resim',False))
        if result.get('state'):
            try:
                st=CadState(**result['state']); job,p=_stl(st); result['stl']=f'/files/{job}/{p.name}'
            except Exception as ge:
                result['can_build']=False; result.setdefault('blocking_ambiguities',[]).append('Çıkarılan geometri CAD motorunda oluşturulamadı: '+str(ge))
        return result
    except Exception as e: raise HTTPException(400,str(e))


@app.post('/api/drawing/verify')
async def verify_drawing(file:UploadFile=File(...), analysis:str=File(...)):
    try:
        data=await file.read()
        if not data: raise ValueError('Dosya boş.')
        first=json.loads(analysis)
        media=file.content_type or 'application/octet-stream'
        result=validate_analysis(await asyncio.to_thread(review_drawing_bytes,data,media,file.filename or 'teknik_resim',first))
        if result.get('state'):
            try:
                st=CadState(**result['state']); job,p=_stl(st); result['stl']=f'/files/{job}/{p.name}'
            except Exception as ge:
                result['can_build']=False; result.setdefault('blocking_ambiguities',[]).append('Doğrulanan geometri CAD motorunda oluşturulamadı: '+str(ge))
        return result
    except Exception as e: raise HTTPException(400,str(e))

@app.post('/api/parse')
def parse(inp:CommandIn):
    try:return {'state':parse_turkish_command(inp.text,CadState(**inp.state) if inp.state else None).__dict__}
    except Exception as e:raise HTTPException(400,str(e))

@app.post('/api/propose')
def propose(inp:CommandIn):
    try:
        before=CadState(**inp.state) if inp.state else CadState();after=parse_turkish_command(inp.text,before)
        # Yeni konumsal feature'lar için parser explicit koordinat üretmiş ama kullanıcı koordinat vermemişse semantic merkeze dönüştür.
        low=inp.text.lower();locwords=('merkez','orta','sağ','sol','üst','alt','buraya','seçili','dokun','x=','y=')
        def sempos(t):
            if 'sağ üst' in t or 'üst sağ' in t:return 'top_right'
            if 'sol üst' in t or 'üst sol' in t:return 'top_left'
            if 'sağ alt' in t or 'alt sağ' in t:return 'bottom_right'
            if 'sol alt' in t or 'alt sol' in t:return 'bottom_left'
            if 'sağ' in t:return 'right'
            if 'sol' in t:return 'left'
            if 'üst' in t:return 'top'
            if 'alt' in t:return 'bottom'
            return 'center'
        for f in after.features[len(before.features):]:
            if f.get('type') in ('through_hole','blind_hole','pocket','slot','countersink_hole','counterbore_hole'):
                # Eğer kullanıcı gerçek model üzerinde bir nokta seçmediyse koordinat yerine semantik konum sakla.
                if not any(w in low for w in ('buraya','seçili','dokun','x=','y=')):
                    f['placement']={'mode':'semantic','position':sempos(low)};f.pop('x',None);f.pop('y',None)
            elif f.get('type')=='chamfer': f['target']=f.get('target','top_outer');f.pop('selector',None)
        job,p=_stl(after);notes,ass=_describe_diff(before,after,inp.text)
        return {'state':after.__dict__,'stl':f'/files/{job}/{p.name}','summary':notes,'assumptions':ass}
    except Exception as e:raise HTTPException(400,str(e))

@app.post('/api/preview')
def preview(inp:BuildIn):
    try:
        s=CadState(**inp.state);job,p=_stl(s);return {'state':s.__dict__,'stl':f'/files/{job}/{p.name}'}
    except Exception as e:raise HTTPException(400,str(e))

@app.post('/api/build')
def build(inp:BuildIn):
    try:
        s=CadState(**inp.state);job=uuid.uuid4().hex[:10];d=OUT/job;d.mkdir(parents=True,exist_ok=True);shape,step,stl=export_files(s,d);pdf=d/f'{s.part_name}.pdf';create_pdf(s,shape,pdf);(d/'state.json').write_text(json.dumps(s.__dict__,ensure_ascii=False,indent=2),encoding='utf-8');return {'state':s.__dict__,'step':f'/files/{job}/{step.name}','stl':f'/files/{job}/{stl.name}','pdf':f'/files/{job}/{pdf.name}'}
    except Exception as e:raise HTTPException(400,str(e))
@app.get('/files/{job}/{name}')
def files(job:str,name:str):
    p=OUT/job/name
    if not p.exists():raise HTTPException(404,'Dosya bulunamadı')
    return FileResponse(p)
app.mount('/',StaticFiles(directory=ROOT/'app'/'static',html=True),name='static')
