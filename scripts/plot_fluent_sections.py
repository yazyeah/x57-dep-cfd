"""Flow-field figures from polygons cut out of verified Fluent fluid cells."""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.colors import Normalize, TwoSlopeNorm
from matplotlib.path import Path as MplPath
from matplotlib.patches import Circle
from scipy.ndimage import binary_erosion

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"04_postproc"
OUT=ROOT/"DELIVERABLES"/"figures"
GEO=json.loads((ROOT/"01_geometry"/"geometry_audit.json").read_text(encoding="utf-8"))
PROP=GEO["starboard_propellers_detected"]
from cmcrameri import cm
from plot_style import apply_publication_style, save_dual_figure
apply_publication_style()


def clipped_field(path, box, flip=False):
    with np.load(path) as d:
        xy=d["xy"]
        idx=d["offsets"]
        counts=np.diff(idx)
        use=np.ones(len(counts),dtype=bool)
        for i in range(2):
            low,high=box[2*i:2*i+2]
            use &= ((np.maximum.reduceat(xy[:,i],idx[:-1])>=low)&
                    (np.minimum.reduceat(xy[:,i],idx[:-1])<=high))
        indices=np.flatnonzero(use)
        polys=[xy[idx[k]:idx[k+1]] for k in indices]
        values={s:d[s][indices] for s in ["p_gauge_Pa","u_m_s","v_m_s","w_m_s"]}
        if "axial_vorticity_s_inv" in d:
            values["axial_vorticity_s_inv"]=d["axial_vorticity_s_inv"][indices]
        values["speed"]=np.sqrt(sum(values[key]**2 for key in ("u_m_s","v_m_s","w_m_s")))
        if flip:
            polys=polys+[p*np.array([1,-1]) for p in polys]
            values={key:np.r_[v,-v if key in ("w_m_s","axial_vorticity_s_inv") else v] for key,v in values.items()}
        return polys,values


def sample_on_grid(polys,values,box,spacing):
    """Sample only inside actual cell polygons. NaNs retain solid-body interiors."""
    xmin,xmax,ymin,ymax=box
    x=np.linspace(xmin,xmax,max(12,int(np.ceil((xmax-xmin)/spacing))+1))
    y=np.linspace(ymin,ymax,max(12,int(np.ceil((ymax-ymin)/spacing))+1))
    cells=np.full((len(y),len(x)),-1,dtype=int)
    for j,p in enumerate(polys):
        low=p.min(axis=0)
        high=p.max(axis=0)
        ix,jx=np.searchsorted(x,low[0]),np.searchsorted(x,high[0],side="right")
        iy,jy=np.searchsorted(y,low[1]),np.searchsorted(y,high[1],side="right")
        if ix>=jx or iy>=jy:
            continue
        xx,yy=np.meshgrid(x[ix:jx],y[iy:jy])
        inside=MplPath(p).contains_points(np.c_[xx.ravel(),yy.ravel()],radius=1e-11)
        cells[iy:jy,ix:jx][inside.reshape(xx.shape)]=j
    return x,y,{k:np.where(cells>=0,v[np.maximum(cells,0)],np.nan) for k,v in values.items()}


def panel(ax,field,scalar,box,cmap,norm,title,labels):
    polys,vals=field
    collection=PolyCollection(polys,array=vals[scalar],cmap=cmap,norm=norm,
                              edgecolors="face",linewidths=0.1,antialiaseds=False)
    ax.add_collection(collection)
    ax.set(xlim=box[:2],ylim=box[2:],xlabel=labels[0],ylabel=labels[1],title=title,aspect="equal")
    ax.set_facecolor("#d9d9d9")
    return collection


def stream(ax,field,box,q,r,spacing,density):
    x,y,grid=sample_on_grid(*field,box,spacing)
    # Solid contours use only unfilled interior regions inside the mesh viewport.
    valid=np.isfinite(grid[q])
    if valid.any() and not valid.all():
        ax.contour(x,y,valid.astype(float),levels=[.5],colors="#202020",linewidths=.55)
    ax.streamplot(x,y,np.ma.masked_invalid(grid[q]),np.ma.masked_invalid(grid[r]),
                  color="white",density=density,linewidth=.48,arrowsize=.55)


def finish(fig,stem,note):
    fig.supxlabel(note,fontsize=8,ha="center")
    save_dual_figure(fig,OUT/stem)
    plt.close(fig)


def span_slices():
    box=(-1.55,1.95,-1.15,.99)
    stations=[PROP[i] for i in (0,2,6)]
    fields=[clipped_field(DATA/"fine_rpm100"/(p["name"]+"_slice.npz"),box) for p in stations]
    umax=max(np.max(f[1]["speed"]) for f in fields)
    plim=max(np.max(np.abs(f[1]["p_gauge_Pa"])) for f in fields)
    fig,ax=plt.subplots(2,3,figsize=(7.2,4.65),layout="constrained")
    for k,(p,f) in enumerate(zip(stations,fields)):
        t=f"{p['name']}   $z={p['z_axis_m']:.3f}$ m"
        v=panel(ax[0,k],f,"speed",box,cm.batlow,Normalize(0,umax),t,("$x$ (m)","$y$ (m)"))
        stream(ax[0,k],f,box,"u_m_s","v_m_s",.012,1.05)
        pc=panel(ax[1,k],f,"p_gauge_Pa",box,cm.vik,TwoSlopeNorm(0,-plim,plim),"",("$x$ (m)","$y$ (m)"))
    fig.colorbar(v,ax=ax[0].tolist(),label="Speed (m/s)",shrink=.86)
    fig.colorbar(pc,ax=ax[1].tolist(),label="Gauge pressure (Pa)",shrink=.86)
    finish(fig,"fig04_spanwise_slices_vel_press","fine_rpm100   [Solid bodies masked]   Clearance is measured at the adjacent $z=0.860$ m station.")


def horizontal_slices():
    # Domain axes on horizontal slices are x and z. Flip z and the spanwise velocity.
    box=(-2.15,3.2,-6.1,6.1)
    fields=[clipped_field(DATA/"fine_rpm100"/(name+"_slice.npz"),box,True) for name in ["hlp_axis","above_wing"]]
    top=max(float(np.max(f[1]["speed"])) for f in fields)
    fig,ax=plt.subplots(1,2,figsize=(7.2,6.4),layout="constrained")
    for a,f,t in zip(ax,fields,[f"HLP axis   $y={PROP[0]['y_axis_m']:.4f}$ m","Above wing   $y=0.225$ m"]):
        c=panel(a,f,"speed",box,cm.batlow,Normalize(0,top),t,("$x$ (m)","$z$ (m)"))
        stream(a,f,box,"u_m_s","w_m_s",.027,1.26)
    fig.colorbar(c,ax=ax.tolist(),shrink=.73,label="Speed (m/s)")
    finish(fig,"fig05_horizontal_planes_blown_wing","fine_rpm100   [Solid bodies masked]   [Mirrored Full Aircraft]")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("figure",choices=["04","05"])
    args=parser.parse_args()
    (span_slices if args.figure=="04" else horizontal_slices)()
