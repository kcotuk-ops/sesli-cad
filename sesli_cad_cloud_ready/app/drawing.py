from __future__ import annotations
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from .cad_engine import CadState


def _mesh(shape):
    verts, tris = shape.val().tessellate(0.25)
    v=np.array([[p.x,p.y,p.z] for p in verts], dtype=float)
    t=np.array(tris, dtype=int)
    return v,t

def _render(shape, out: Path, elev: float, azim: float, title: str):
    v,t=_mesh(shape)
    fig=plt.figure(figsize=(5,3.2))
    ax=fig.add_subplot(111, projection='3d')
    poly=Poly3DCollection(v[t], linewidths=0.15, alpha=0.9)
    ax.add_collection3d(poly)
    mins=v.min(axis=0); maxs=v.max(axis=0); ctr=(mins+maxs)/2; rng=max(maxs-mins)
    ax.set_xlim(ctr[0]-rng/2, ctr[0]+rng/2); ax.set_ylim(ctr[1]-rng/2, ctr[1]+rng/2); ax.set_zlim(ctr[2]-rng/2, ctr[2]+rng/2)
    ax.view_init(elev=elev, azim=azim)
    ax.set_proj_type('ortho')
    ax.set_axis_off(); ax.set_title(title, fontsize=9)
    plt.tight_layout(pad=0)
    fig.savefig(out, dpi=160, bbox_inches='tight', transparent=False)
    plt.close(fig)

def create_pdf(state: CadState, shape, out_pdf: Path):
    tmp=out_pdf.parent / (out_pdf.stem+"_views")
    tmp.mkdir(exist_ok=True)
    views=[("Ön Görünüş",0,-90), ("Üst Görünüş",90,-90), ("Sağ Görünüş",0,0), ("İzometrik",30,-45)]
    imgs=[]
    for i,(name,e,a) in enumerate(views):
        p=tmp/f"v{i}.png"; _render(shape,p,e,a,name); imgs.append(p)
    c=canvas.Canvas(str(out_pdf), pagesize=landscape(A4))
    W,H=landscape(A4)
    c.setFont("Helvetica-Bold",14); c.drawString(15*mm,H-15*mm, state.part_name.upper()+" - TEKNİK RESİM")
    positions=[(15,105),(150,105),(15,25),(150,25)]
    for p,(x,y) in zip(imgs,positions):
        c.drawImage(str(p), x*mm,y*mm, width=125*mm,height=70*mm, preserveAspectRatio=True, anchor='c')
    # title block
    c.rect(215*mm,5*mm,75*mm,18*mm)
    c.setFont("Helvetica",7)
    c.drawString(218*mm,18*mm,f"Parça: {state.part_name}")
    c.drawString(218*mm,14*mm,"Birim: mm")
    c.drawString(218*mm,10*mm,"Ölçek: otomatik")
    c.drawString(255*mm,18*mm,"Rev: A")
    # dimension/feature summary
    c.setFont("Helvetica-Bold",8); c.drawString(15*mm,18*mm,"Ölçü / İşlem Özeti")
    c.setFont("Helvetica",7)
    y=14
    base=state.base
    c.drawString(15*mm,y*mm, "Taban: "+", ".join(f"{k}={v}" for k,v in base.items() if k!='type')); y-=4
    for f in state.features[:8]:
        txt=f"{f.get('type')}: "+", ".join(f"{k}={v}" for k,v in f.items() if k not in ('id','type'))
        c.drawString(15*mm,y*mm,txt[:110]); y-=4
    c.showPage(); c.save()
