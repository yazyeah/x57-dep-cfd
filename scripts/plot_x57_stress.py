"""Figures 18 and 20 from matched native wall and volume data on the accepted fine grid."""
import argparse
from pathlib import Path
import json
import h5py
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection,PatchCollection
from matplotlib.colors import Normalize,TwoSlopeNorm
from matplotlib.patches import Rectangle
from mpl_toolkits.axes_grid1.inset_locator import mark_inset
from cmcrameri import cm
from plot_style import apply_publication_style,save_dual_figure,ACADEMIC_PALETTE
from plot_fluent_sections import panel as fluid_panel
from cut_fluent_cells import bounds,read_id_blocks,zones
from x57_stress_profiles import native_volume,plane_records,wall_profiles,intersect,STATIONS,WAKE,OUT
from x57_baseline_data import ROOT,FINE,DATA,read_json,wall_data

STEMS={18:"fig18_wall_shear_and_reynolds_stress_fields",20:"fig20_flow_topology_and_vortex_dynamics"}


def prepare():
    vol,case,data=native_volume()
    rotors=read_json(DATA/"actuator_disk_model.json")["rotors"]
    planes=[];records=[]
    for j,x in enumerate(STATIONS):
        name=f"stress_station_{j+1}"
        path=OUT/(name+"_slice.npz")
        if not path.is_file() or path.stat().st_mtime_ns<vol.stat().st_mtime_ns:
            path=intersect(FINE,0,x,name)
        field,rows=plane_records(x,path,rotors);planes.append(field);records.extend(rows)
    cp,_,w,_,_,_=wall_data(FINE)
    with w:
        records+=wall_profiles(case,data,vol,cp,w)
        parts=w["component"];tau=np.linalg.norm(w["wall_shear_storage"],axis=1)/w["area_m2"]
        walls=pd.DataFrame(dict(record_type="wall_face",component=parts,native_face_id=w["face_id"],
                                x_m=w["xyz"][:,0],y_m=w["xyz"][:,1],z_m=w["xyz"][:,2],half_domain_area_m2=w["area_m2"],
                                wall_shear_Pa=tau,pressure_gauge_Pa=w["p_gauge_Pa"],y_plus=w["yplus"],
                                method="native wall pressure and y+; magnitude of native integrated wall shear divided by face area"))
    frame=pd.concat([pd.DataFrame(records),walls],ignore_index=True)
    frame["case"]=FINE;frame["native_case"]=case.name;frame["native_data"]=data.name
    temp=OUT/"stress_and_bl_fluid.pending.csv";frame.to_csv(temp,index=False)
    temp.replace(OUT/"stress_and_bl_fluid.csv")
    return planes,frame,case


def wall_polygons(case,wall):
    polygons=[];heights=[];values=[]
    table=wall.set_index("native_face_id")
    with h5py.File(case) as f:
        mesh=f["meshes/1"];nodes=read_id_blocks(mesh["nodes/coords"],int(max(mesh["nodes/zoneTopology/maxId"])),float,3)
        for zone,(low,high) in zones(mesh["faces/zoneTopology"]).items():
            if not zone.startswith("wall_"):continue
            for g in mesh["faces/nodes"].values():
                lo,hi=bounds(g);a=max(low,lo);b=min(high,hi)
                if a>b:continue
                nn=g["nnodes"][:].astype(np.int64);sp=np.r_[0,np.cumsum(nn)]
                conn=g["nodes"][sp[a-lo]:sp[b-lo+1]]
                for n in np.unique(nn[a-lo:b-lo+1]):
                    off=np.flatnonzero(nn[a-lo:b-lo+1]==n);ids=a+off
                    p=nodes[conn[(sp[ids-lo]-sp[a-lo])[:,None]+np.arange(n)]]
                    origin=p.mean(axis=1);dp=p-origin[:,None,:]
                    normal=np.cross(dp,np.roll(dp,-1,axis=1)).sum(axis=1)
                    pick=np.flatnonzero(normal[:,1]>0)
                    shear=table.loc[ids[pick],"wall_shear_Pa"].to_numpy()
                    for shape,y,tau in zip(p[pick][:,:,[2,0]],origin[pick,1],shear):
                        polygons.extend([shape,shape*np.array([-1.,1.])]);heights.extend([y,y]);values.extend([tau,tau])
    order=np.argsort(heights,kind="stable")
    return [polygons[i] for i in order],np.asarray(values)[order]


def fig18(planes,frame,case):
    fig=plt.figure(figsize=(8.3,7.8),layout="constrained");gs=fig.add_gridspec(3,2,height_ratios=[.95,1,1])
    wall=frame[frame.record_type=="wall_face"];polys,tau=wall_polygons(case,wall)
    ax=fig.add_subplot(gs[0,:]); vmax=max(np.max(tau),1.e-12)
    # Main panel 0 to the 99th percentile (the junction peak is shown in the inset at its own full range).
    col=PolyCollection(polys,array=tau,cmap=cm.lajolla,norm=Normalize(0,max(float(np.percentile(tau,99)),1.e-12)),
                       edgecolors="face",linewidths=.08)
    ax.add_collection(col);ax.autoscale_view();ax.set_aspect("equal");ax.set(xlabel="Spanwise z (m)",ylabel="Axial x (m)",title="a   Projected upper airframe; wall shear")
    fig.colorbar(col,ax=ax,label="Wall shear (Pa)",shrink=.72,extend="max")
    z,x=polys[int(np.argmax(tau))].mean(axis=0);win=(z-.5,z+.5,x-.34,x+.34)
    select=[i for i,p in enumerate(polys) if p[:,0].max()>win[0] and p[:,0].min()<win[1] and p[:,1].max()>win[2] and p[:,1].min()<win[3]]
    inset=ax.inset_axes([.74,.62,.24,.39]); zoom=PolyCollection([polys[i] for i in select],array=tau[select],cmap=cm.lajolla,norm=Normalize(min(tau[select]),vmax),edgecolors="face",linewidths=.08)
    inset.add_collection(zoom);inset.set(xlim=win[:2],ylim=win[2:],aspect="equal");inset.tick_params(labelsize=5);inset.set_title("Peak-shear region",fontsize=6)
    mark_inset(ax,inset,loc1=2,loc2=4,fc="none",ec=".4",lw=.5)
    idx=2
    for j,(key,label,cmap) in enumerate([("k_m2_s2","Turbulent kinetic energy (m²/s²)",cm.batlow),("reynolds_shear_xy_Pa",r"Modeled $-\rho\,\overline{u'v'}$ (Pa)",cm.vik)]):
        a=fig.add_subplot(gs[1,j]);f=planes[idx];v=f[1][key];lim=max(np.percentile(abs(v),99),1.e-12)
        norm=Normalize(0,lim) if j==0 else TwoSlopeNorm(0,-lim,lim)
        col=fluid_panel(a,f,key,WAKE,cmap,norm,("b" if j==0 else "c")+f"   x = {STATIONS[idx]:+.2f} m",("Starboard z (m)","Vertical y (m)"))
        fig.colorbar(col,ax=a,label=label,shrink=.68,extend="max" if j==0 else "both")
    a=fig.add_subplot(gs[2,0]);d=frame[(frame.record_type=="wake_area_mean")&(frame.quantity=="Cp0")].sort_values("x_m")
    cp=d.value.to_numpy();a.plot(d.x_m,cp,"o-",label="Mean Cp0");a.plot(d.x_m,cp[0]-cp,"s--",label="Decrease from first plane")
    a.axhline(0,color=".5",lw=.5);a.set(xlabel="Axial station x (m)",ylabel="Dimensionless",title="d   Area-weighted total pressure");a.legend(fontsize=7)
    a=fig.add_subplot(gs[2,1]);bins=np.linspace(min(wall.wall_shear_Pa),max(wall.wall_shear_Pa)+1e-12,50)
    for part,g in wall.groupby("component"):
        hist,_=np.histogram(g.wall_shear_Pa,bins=bins,weights=g.half_domain_area_m2)
        a.step(bins[1:],np.cumsum(hist)/hist.sum(),where="post",label=part[5:])
    a.set(xlabel="Wall shear (Pa)",ylabel="Fraction of wetted area",title="e   Component shear distributions");a.legend(fontsize=6)
    save_dual_figure(fig,ROOT/"DELIVERABLES/figures"/STEMS[18]);plt.close(fig)


def raincloud(ax,groups,col):
    allvalues=np.concatenate([g[col].to_numpy() for _,g in groups]);low,high=allvalues.min(),allvalues.max()
    bins=np.linspace(low,high+max(1e-12,(high-low)*1e-10),28);cx=(bins[1:]+bins[:-1])*.5
    for i,(name,g) in enumerate(groups):
        val=g[col].to_numpy();weight=g.half_domain_area_m2.to_numpy();order=np.argsort(val)
        cdf=np.cumsum(weight[order])/weight.sum();q=val[order][np.searchsorted(cdf,np.linspace(.025,.975,20))]
        count,_=np.histogram(val,bins,weights=weight)
        ax.fill_between(cx,i,i+.42*count/max(count.max(),1e-20),color=ACADEMIC_PALETTE[i],alpha=.65)
        ax.scatter(q,np.full(len(q),i-.09),s=2,color=ACADEMIC_PALETTE[i],alpha=.7)
        ax.plot(q[len(q)//2],i-.09,"|",color="k",ms=5)
    ax.set_yticks(range(len(groups)),[n[5:] for n,_ in groups],fontsize=6)


def fig20(frame):
    fig=plt.figure(figsize=(8.8,7.7),layout="constrained");gs=fig.add_gridspec(2,2,height_ratios=[1,1.25])
    a=fig.add_subplot(gs[0,0]);circ=frame[frame.record_type=="circulation"].sort_values("x_m")
    a.plot(circ.x_m,circ.value,"o-",color=ACADEMIC_PALETTE[0]);a.axhline(0,color=".5",lw=.5)
    a.set(xlabel="Axial station x (m)",ylabel="Signed Γ (m²/s)",title="a   Fixed wingtip wake window, width 2R")
    a=fig.add_subplot(gs[0,1]);bl=frame[frame.record_type=="boundary_layer"]
    for (station,face_id),g in bl.groupby(["station","face_id"]):
        g=g.sort_values("y_plus");a.semilogx(g.y_plus,g.value,".-",ms=2,lw=.8,label=f"{station}, x/c={g.x_over_c.iloc[0]:.2f}")
    lin=np.geomspace(.2,5,30);log=np.geomspace(30,max(45.,bl.y_plus.max()),60)
    a.plot(lin,lin,"k:",label="Viscous sublayer");a.plot(log,np.log(log)/.41+5.2,"k--",label="Log law (κ=0.41, B=5.2)")
    a.set(xlabel="y+",ylabel="Signed u+",title="b   Crossed cells on upper-wall normals");a.legend(fontsize=5.7,ncol=2)
    sub=gs[1,0].subgridspec(3,1);ww=frame[frame.record_type=="wall_face"];groups=list(ww.groupby("component"))
    for n,(key,label) in enumerate([("pressure_gauge_Pa","Gauge pressure (Pa)"),("wall_shear_Pa","Wall shear (Pa)"),("y_plus","Wall y+")]):
        a=fig.add_subplot(sub[n,0]);raincloud(a,groups,key);a.set_xlabel(label,fontsize=7);a.tick_params(axis="x",labelsize=6)
        if n==0:a.set_title("c   Area-weighted wall distributions",fontsize=9)
    a=fig.add_subplot(gs[1,1]);ff=frame[frame.record_type=="induced_angle"]
    for i,(name,g) in enumerate(ff.groupby("component",sort=False)):
        g=g.sort_values("z_lo_m");xx=np.column_stack([g.z_lo_m,g.z_hi_m,np.full(len(g),np.nan)]).ravel()
        yy=np.column_stack([g.value,g.value,np.full(len(g),np.nan)]).ravel()
        a.plot(xx,yy,color=ACADEMIC_PALETTE[i],label=name,lw=1.15)
    a.axhline(0,color=".5",lw=.5);a.set(xlabel="Starboard z (m)",ylabel="atan2(v, u) (degrees)",title="d   Induced angle at x = −0.30 m");a.legend(fontsize=6,ncol=2)
    save_dual_figure(fig,ROOT/"DELIVERABLES/figures"/STEMS[20]);plt.close(fig)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--figures",nargs="*",type=int,choices=[18,20],default=[18,20]);args=p.parse_args()
    apply_publication_style();planes,frame,case=prepare()
    if 18 in args.figures:fig18(planes,frame,case)
    if 20 in args.figures:fig20(frame)
