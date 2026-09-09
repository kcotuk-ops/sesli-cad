from __future__ import annotations
from pathlib import Path
import json, uuid
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from .cad_engine import CadState, export_files
from .drawing import create_pdf
from .parser import parse_turkish_command

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/"output"; OUT.mkdir(exist_ok=True)
app=FastAPI(title="Sesli CAD")

@app.get('/health')
def health():
    return {'status':'ok'}

class CommandIn(BaseModel):
    text: str
    state: dict | None = None
class BuildIn(BaseModel):
    state: dict

@app.post('/api/parse')
def parse(inp: CommandIn):
    current = CadState(**inp.state) if inp.state else None
    try:
        state=parse_turkish_command(inp.text,current)
        return {"state":state.__dict__}
    except Exception as e:
        raise HTTPException(400,str(e))

@app.post('/api/build')
def build(inp: BuildIn):
    try:
        state=CadState(**inp.state)
        job=uuid.uuid4().hex[:10]
        d=OUT/job; d.mkdir(parents=True,exist_ok=True)
        shape,step,stl=export_files(state,d)
        pdf=d/f"{state.part_name}.pdf"; create_pdf(state,shape,pdf)
        (d/'state.json').write_text(json.dumps(state.__dict__,ensure_ascii=False,indent=2),encoding='utf-8')
        return {"job":job,"step":f"/files/{job}/{step.name}","stl":f"/files/{job}/{stl.name}","pdf":f"/files/{job}/{pdf.name}","state":state.__dict__}
    except Exception as e:
        raise HTTPException(400,str(e))

@app.get('/files/{job}/{name}')
def files(job:str,name:str):
    p=OUT/job/name
    if not p.exists(): raise HTTPException(404,'Dosya bulunamadı')
    return FileResponse(p)

app.mount('/', StaticFiles(directory=ROOT/'app'/'static', html=True), name='static')
