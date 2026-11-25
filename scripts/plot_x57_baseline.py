"""Draw the baseline X-57 figures using accepted Fluent endpoints and auditable native fields."""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.colors import Normalize,TwoSlopeNorm
from mpl_toolkits.axes_grid1.inset_locator import mark_inset
from cmcrameri import cm
from plot_style import apply_publication_style,save_dual_figure,ACADEMIC_PALETTE
from plot_fluent_sections import panel as field_panel,stream
from wing_surface_metrics import wing_faces
from x57_baseline_data import (BASE,FINE,OFF,CASES3,ROOT,DATA,accepted,reference,save_table,save_json,
                               grid_series,histories,convergence_rows,rpm_series,wall_data,wall_budgets,crossplanes,read_json,swirl_load_partition)

STEMS={2:"fig02_mesh_convergence_and_yplus",3:"fig03_convergence_histories",6:"fig06_wing_cp_and_suction",
       7:"fig07_rpm_sweep_scaling",8:"fig08_swirl_comparison_and_load_shift",9:"fig09_wake_evolution_crossplanes",
       10:"fig10_component_force_and_upper_lower_budget",11:"fig11_wall_yplus_and_shear_map",12:"fig12_actuator_disk_verification_and_design_concept"}
OUT=ROOT/"DELIVERABLES/figures"
FORCES={"Airframe lift":"airframe-lift-half","Wing lift":"wing-lift-half","Airframe drag":"airframe-drag-half"}
BOX=(0.,5.8,-1.7,1.25)


def layout(rows,cols,size=None):
    return plt.subplots(rows,cols,figsize=size or (7.5,3.1*rows),layout="constrained",squeeze=False)


def title(ax,letter,name):
    ax.set_title(letter+"   "+name,loc="left",fontsize=9.2)


def finish(fig,num):
    save_dual_figure(fig,OUT/STEMS[num])
    plt.close(fig)


def projected_faces(case,wall,side):
    ids=wall["face_id"]; lookup={int(i):k for k,i in enumerate(ids)}
    normal=wall["inward_fluid_area_vector_m2"][:,1]
    polys=[]; rows=[]
    for fid,p in wing_faces(case):
        k=lookup[fid]
        if normal[k]*side<=0:continue
        shape=p[:,[2,0]]
        polys.extend([shape,shape*np.array([-1.,1.])]); rows.extend([k,k])
    if not rows:raise ValueError("Missing projected wing side")
    return polys,np.array(rows,dtype=int)


def wing_panel(fig,ax,projected,values,cmap,norm,label):
    polygons,idx=projected;field=PolyCollection(polygons,array=values[idx],cmap=cmap,norm=norm,
                                                  edgecolors="face",linewidths=.1)
    ax.add_collection(field);ax.autoscale_view();ax.set_aspect("equal")
    ax.set(xlabel="Spanwise z (m)",ylabel="Axial x (m)")
    fig.colorbar(field,ax=ax,shrink=.77,label=label)


def yplus_table():
    stats=[]
    for level in ("coarse","medium","fine"):
        name=level+"_rpm100";_,_,wall,metric,_,_=wall_data(name);wall.close()
        for part,row in metric["yplus"].items():stats.append(dict(case=name,component=part,**row))
    return pd.DataFrame(stats)


def fig2():
    frame,gcis=grid_series();save_table(frame,"mesh_convergence.csv");save_json(gcis,"asme_vv20_gci.json")
    save_table(yplus_table(),"yplus_stats.csv")
    fig,axs=layout(2,2,(8.1,6.2))
    for ax,col,label in zip(axs[0],["C_L","C_D"],["a","b"]):
        g=gcis[col];ax.plot(frame.h_m,frame[col],"-o",color=ACADEMIC_PALETTE[0])
        for i,text in enumerate(frame.level):ax.annotate(text,(frame.h_m.iloc[i],frame[col].iloc[i]),xytext=(0,5),textcoords="offset points",ha="center",fontsize=7)
        if g.get("reported_fine_absolute_uncertainty") is not None:
            ax.errorbar(frame.h_m.iloc[1:],frame[col].iloc[1:],yerr=[g["reported_medium_absolute_uncertainty"],g["reported_fine_absolute_uncertainty"]],fmt="none",capsize=4,color="black")
            if g["extrapolated"] is not None:
                extrap_label="Richardson" if g["qualified_monotonic_order"] else "Raw extrapolation"
                ax.plot(0,g["extrapolated"],marker="*",color=ACADEMIC_PALETTE[1],label=f"{extrap_label}, p={g['observed_order']:.2g}")
            if g["fallback_activated"]:
                ax.plot([],[],color="k",marker="|",ls="none",label=g["convergence_type"]+"; range / p=2 envelope")
            ax.legend(fontsize=7)
        else:ax.text(.02,.03,g["status"],transform=ax.transAxes,fontsize=6,wrap=True)
        title(ax,label,{"C_L":"Lift convergence","C_D":"Drag convergence"}[col]);ax.set(xlabel="Mean grid spacing h (m)",ylabel=col)
    _,_,w,_,_,_=wall_data(FINE)
    with w:
        yp=w["yplus"];ar=w["area_m2"];labels=w["component"]
        a=axs[1,0]
        for part in np.unique(labels):
            idx=np.flatnonzero(labels==part);ix=idx[np.argsort(yp[idx])]
            a.plot(yp[ix],np.cumsum(ar[ix])/ar[ix].sum(),label=part[5:])
        a.axvline(1,ls=":",color="k");a.set(xlabel="Wall y+",ylabel="Fraction of wetted area",xscale="symlog");a.legend(fontsize=6)
        title(a,"c","Fine-grid wall resolution")
    a=axs[1,1];a.plot(frame.cells/1e6,frame.min_orthogonal_quality,"o-",color=ACADEMIC_PALETTE[2]);a.axhline(.1,ls=":",color="k");a.set(xlabel="Half-domain cells (million)",ylabel="Minimum standard orthogonal quality");title(a,"d","Solver-reloaded mesh quality")
    finish(fig,2)


def fig3():
    force,res=histories(FINE)
    fig,axs=layout(2,2,(8.05,6.15))
    a=axs[0,0]
    for eq in ["continuity","x-velocity","y-velocity","z-velocity","energy","k","omega"]:
        a.semilogy(res.index,res[eq].where(res[eq]>0),label=eq)
    a.legend(ncol=2,fontsize=6);a.set(xlabel="Iteration",ylabel="Scaled residual");title(a,"a","Fine-grid residuals")
    a=axs[0,1]
    for label,col in FORCES.items():a.plot(force.index,2*force[col],label=label)
    a.legend(fontsize=6);a.set(xlabel="Iteration",ylabel="Full-aircraft force (N)");title(a,"b","Force histories")
    tail=force.iloc[-300:];a=axs[1,0];mz=2*force["airframe-pitch-mz-half"]
    a.plot(force.index,mz,color=ACADEMIC_PALETTE[1]);a.set(xlabel="Iteration",ylabel="Pitching moment (N m)");title(a,"c","Moment about CAD origin")
    if len(force)>len(tail):
        axin=a.inset_axes([.5,.55,.45,.39]);axin.plot(tail.index,mz.loc[tail.index],lw=.65);axin.tick_params(labelsize=5)
        mark_inset(a,axin,loc1=2,loc2=4,fc="none",ec=".45",lw=.6)
    a=axs[1,1]
    for label,col in FORCES.items():
        y=2*tail[col];mu=y.mean();sd=y.std()
        line,=a.plot(y.index,y-mu,label=label,lw=.8)
        a.fill_between(y.index,-sd,sd,alpha=.10,color=line.get_color())
    a.axhline(0,color=".3",lw=.5);a.set(xlabel="Iteration",ylabel="Force minus window mean (N)");a.legend(fontsize=6);title(a,"d",f"Final {len(tail)} iterations; ±1 SD")
    finish(fig,3)


def fig6():
    cp,_,wall,met,case,_=wall_data(FINE)
    save_table(cp,"wing_cp_sections.csv")
    fig,axs=layout(2,2,(8.2,6.2)); top,low=axs[0]
    for j,(name,g) in enumerate(cp.groupby("station",sort=False)):
        for ax,side in [(top,"upper"),(low,"lower")]:
            ss=g[g.side==side].sort_values("x_over_c")
            ax.plot(ss.x_over_c,ss.Cp,label=name,color=ACADEMIC_PALETTE[j%7],lw=1)
    for a,k,t in [(top,"a","Upper-surface sections"),(low,"b","Lower-surface sections")]:
        a.invert_yaxis();a.set(xlabel="x/c",ylabel="Pressure coefficient");title(a,k,t)
    low.legend(fontsize=6,ncol=2)
    inset=top.inset_axes([.55,.50,.42,.42]);lead=cp[(cp.side=="upper")&(cp.x_over_c<.14)&(cp.x_over_c>=0)]
    for j,(name,g) in enumerate(lead.groupby("station",sort=False)):
        inset.plot(g.x_over_c,g.Cp,color=ACADEMIC_PALETTE[j%7],lw=.65)
    inset.set_xlim(0,.14);inset.invert_yaxis();inset.tick_params(labelsize=5);mark_inset(top,inset,loc1=2,loc2=4,fc="none",ec="0.45",lw=.5)
    with wall:
        peak=met["peak_suction"]; mask=wall["component"]=="wall_wing"; v=wall["Cp"]; norm=Normalize(float(v[mask].min()),float(v[mask].max()))
        for s,ax,letter in [(1,axs[1,0],"c"),(-1,axs[1,1],"d")]:
            proj=projected_faces(case,wall,s);wing_panel(fig,ax,proj,v,cm.vik,norm,"Cp")
            title(ax,letter,"Upper wing" if s==1 else "Lower wing")
            ids=wall["face_id"][proj[1]]
            if peak["face_id"] in ids:
                x,y,z=peak["face_centroid_m"];ax.plot([z,-z],[x,x],"w*",mec="k",ms=7)
                ax.set_title(f"{letter}   Min Cp={peak['Cp']:.2f} at ({x:.2f}, {y:.2f}, ±{z:.2f}) m",loc="left",fontsize=8)
    finish(fig,6)


def fig7():
    t,fits=rpm_series();save_table(t,"rpm_sweep.csv")
    fig,axs=layout(1,2,(8.3,3.7));a,b=axs[0];on=t[t.case!=OFF];off=t[t.case==OFF]
    for i,(key,label) in enumerate([("delta_L_static_N","Lift increment"),("L_wing_N","Wing lift"),("D_air_N","Airframe drag")]):
        color=ACADEMIC_PALETTE[i];fit=fits[key];u=np.linspace(0,1,100)
        a.plot(on.s,on[key],"o",color=color);a.plot(u,fit["squared_rpm_coefficient"]*u*u,color=color,label=f"{label}; R²={fit['r_squared_centered']:.3f}" if fit['r_squared_centered'] is not None else label)
        a.plot(off.s,off[key],marker="D",mfc="none",mec=color,ls="none")
    a.plot([],[],"kD",mfc="none",label="No swirl");a.legend(fontsize=6);title(a,"a","RPM scaling, fit to positive speeds");a.set(xlabel="RPM fraction s",ylabel="Full-aircraft load (N)")
    b.plot(on.s,on.T_gross_N,"o-",label="Gross thrust");b.plot(on.s,on.T_net_N,"s--",label="Net thrust");b.legend(fontsize=6,loc="upper left")
    b.set(xlabel="RPM fraction s",ylabel="Thrust (N)");title(b,"b","Installed thrust budget")
    inset=b.inset_axes([.54,.1,.42,.38]);positive=on[on.s>0];inset.plot(positive.s,positive.D_over_s2_N,"o-",ms=2,label="D/s²");inset.plot(positive.s,positive.abs_L_over_s2_N,"s--",ms=2,label="|L|/s²");inset.legend(fontsize=5);inset.tick_params(labelsize=5);inset.set_ylabel("N",fontsize=6)
    finish(fig,7)

def field_norm(fields,key,signed=False):
    data=np.concatenate([v[key] for _,v in fields])
    if not len(data) or not np.isfinite(data).all():raise ValueError(f"No finite native {key} values")
    # Every native value is retained; colorbar arrowheads identify percentile saturation.
    vmax=max(float(np.percentile(abs(data),99)),np.finfo(float).eps)
    return TwoSlopeNorm(vcenter=0.,vmin=-vmax,vmax=vmax) if signed else Normalize(0,vmax)


def fig8():
    fields=[crossplanes(n,[1.20])[0] for n in (BASE,OFF)]
    norm=field_norm(fields,"axial_vorticity_s_inv",True)
    fig,axs=layout(1,3,(11.3,3.2))
    for ax,f,caption in zip(axs[0,:2],fields,["a   Swirl on","b   Swirl off"]):
        bar=field_panel(ax,f,"axial_vorticity_s_inv",BOX,cm.vik,norm,caption,("Spanwise z (m)","Vertical y (m)"))
        stream(ax,f,BOX,"w_m_s","v_m_s",.04,1.)
    fig.colorbar(bar,ax=axs[0,:2].tolist(),label="Axial vorticity (1/s)",extend="both",shrink=.75)
    tables=[]
    for name in [BASE,OFF,FINE]:
        _,load,wall,_,_,_=wall_data(name);wall.close();tables.append(load.assign(case=name))
    delta_table,partition=swirl_load_partition()
    absolute=pd.concat(tables,ignore_index=True)
    # Put signed ON-minus-OFF values on the matched nominal rows; the Fine
    # curve is a separate grid and has no matched OFF solution.
    absolute=absolute.merge(delta_table.assign(case=BASE).drop(columns=["span_region","z_m"]),
                            on=["case","z_lo_m","z_hi_m"],how="left",validate="many_to_one")
    save_table(absolute,"spanwise_loading.csv")
    on,off=tables[:2]
    if not np.allclose(on[["z_lo_m","z_hi_m"]],off[["z_lo_m","z_hi_m"]],atol=1.e-10,rtol=0):
        raise ValueError("Swirl cases have different spanwise integration bins")
    ax=axs[0,2];delta=on.dL_dz_N_per_m-off.dL_dz_N_per_m;ax.plot(on.z_m,delta,color=ACADEMIC_PALETTE[0]);ax.axhline(0,color=".4",lw=.5)
    ax.axvline(partition["inboard_edge_of_wingtip_disk_m"],color=".3",ls=":",lw=.7)
    by=partition["full_symmetric_delta_by_region_N"]
    ax.text(.03,.97,f"Full-wing lift change\nInboard {by['inboard_HLP']:+.2f} N\nOutboard {by['outboard_wingtip']:+.2f} N",
            transform=ax.transAxes,va="top",fontsize=6)
    title(ax,"c","Swirl on minus off");ax.set(xlabel="Starboard z (m)",ylabel="Lift-density change (N/m)")
    finish(fig,8)


def fig9():
    xs=[-.30,.35,1.20,3.00];fields=crossplanes(FINE,xs)
    fig,axs=layout(4,2,(8.1,8.1))
    for j,(key,caption,cmap,signed) in enumerate([("speed","Speed (m/s)",cm.batlow,False),("axial_vorticity_s_inv","Axial vorticity (1/s)",cm.vik,True)]):
        norm=field_norm(fields,key,signed)
        for i,(x,field) in enumerate(zip(xs,fields)):
            ax=axs[i,j];bar=field_panel(ax,field,key,BOX,cmap,norm,f"{chr(97+i*2+j)}   x = {x:+.2f} m",("Spanwise z (m)","Vertical y (m)"))
            if j==1:stream(ax,field,BOX,"w_m_s","v_m_s",.045,.85)
        fig.colorbar(bar,ax=axs[:,j].tolist(),label=caption,extend="both" if signed else "max",shrink=.72)
    finish(fig,9)


def fig10():
    t=wall_budgets(FINE);save_table(t,"component_force_breakdown.csv")
    fig,axs=layout(1,3,(10.2,3.5))
    parts=t[t.part.str.startswith("wall_")]
    for ax,axis,letter in zip(axs[0,:2],["L","D"],"ab"):
        y=np.arange(len(parts));ax.barh(y-.17,parts[axis+"_pressure_N"],height=.32,label="Pressure")
        ax.barh(y+.17,parts[axis+"_viscous_N"],height=.32,label="Viscous")
        ax.set_yticks(y,parts.part.str.removeprefix("wall_"));ax.set_xlabel("Full-aircraft force (N)");ax.axvline(0,color=".3",lw=.5)
        title(ax,letter,"Component lift" if axis=="L" else "Component drag");ax.legend(fontsize=7)
    ax=axs[0,2];w=t[t.part.str.startswith("wing_")]
    ax.bar(["Upper","Lower","Edge"],w.set_index("part").loc[["wing_upper","wing_lower","wing_edge"],"L_pressure_N"],color=ACADEMIC_PALETTE[:3])
    ax.axhline(0,color=".3",lw=.5);ax.set_ylabel("Full-wing vertical pressure force (N)");title(ax,"c","Vertical pressure contributions")
    finish(fig,10)


def fig11():
    _,_,w,_,case,_=wall_data(FINE);fig,axs=layout(2,2,(8.1,4.4))
    with w:
        mask=w["component"]=="wall_wing";tau=np.linalg.norm(w["wall_shear_storage"],axis=1)/w["area_m2"]
        for i,side in enumerate([1,-1]):
            proj=projected_faces(case,w,side)
            for j,(v,label,cmap) in enumerate([(w["yplus"],"Wall y+",cm.batlow),(tau,"Wall shear (Pa)",cm.lajolla)]):
                cap=max(float(np.max(v[mask])),np.finfo(float).eps)
                wing_panel(fig,axs[i,j],proj,v,cmap,Normalize(0,cap),label)
                title(axs[i,j],chr(97+i*2+j),("Upper" if side==1 else "Lower")+" surface")
    finish(fig,11)


def fig12():
    qa,case,_=accepted(FINE);disks=pd.DataFrame(qa["disk_integrals"]).set_index("name")
    model=read_json(DATA/"actuator_disk_model.json");rotors=model["rotors"]
    names=[p["name"] for p in rotors];disks=disks.loc[names]
    fig,axs=layout(2,2,(8.2,6.05));ax=axs[0,0]
    h=np.linspace(0,1,180)
    for i,p in enumerate(rotors):
        radius=p["r_hub_m"]+h*(p["r_tip_m"]-p["r_hub_m"])
        ax.plot(radius,h*np.sqrt(1-h),color=ACADEMIC_PALETTE[i],alpha=.88,lw=1.0,label=p["name"])
        ax.plot(radius,np.sqrt(h*(1-h)),ls="--",color=ACADEMIC_PALETTE[i],alpha=.8,lw=1)
    ax.legend(fontsize=5.5,ncol=2);title(ax,"a","Prescribed weights: thrust (solid), torque (dashed)")
    ax.set(xlabel="Blade radius r (m)",ylabel="Dimensionless radial weight")
    a=axs[0,1];y=np.arange(len(names));et=100*(disks.discrete_thrust_N/disks.thrust_target_N-1)
    eq=100*(disks.discrete_torque_Nm/disks.torque_target_Nm-1)
    a.barh(y-.16,et,height=.30,label="Thrust");a.barh(y+.16,eq,height=.30,label="Torque")
    a.axvline(0,color="k",lw=.6);a.set(yticks=y,yticklabels=names,xlabel="Native integral / target − 1 (%)");a.legend(fontsize=7);title(a,"b","Discrete normalization on the fine mesh")
    c=axs[1,0];cal=model["hlp_calibration"];forces=np.array(cal["table_16_thrust_lbf_5_10_KEAS"])*4.4482216152605
    c.plot([5,10],forces,"o",label="NASA TM, Table 16");c.plot([0,5,10],[2*forces[0]-forces[1],*forces],"--",label="Linear extrapolation")
    c.set(xlabel="Equivalent airspeed (kn)",ylabel="HLP thrust (N)");title(c,"c",f"NASA map at {cal['fixed_mode_rpm']} rpm");c.legend(fontsize=7)
    a=axs[1,1];labels=["HLP-1","Wingtip"];picks=[rotors[0],rotors[-1]]
    calculated=[disks.loc[p["name"],"discrete_torque_Nm"] for p in picks]
    intended=[p["targets"][-1]["torque_magnitude_Nm"] for p in picks]
    x=np.arange(2);a.bar(x-.18,intended,width=.35,label="Calibrated input");a.bar(x+.18,calculated,width=.35,label="Native integral")
    a.set(xticks=x,xticklabels=labels,ylabel="Torque (N m)");a.legend(fontsize=7);title(a,"d","Torque at prescribed nominal speeds")
    finish(fig,12)


def summary():
    frame,gcis=grid_series();rpm,fits=rpm_series();qa,case,dat=accepted(FINE)
    _,loads,w,met,_,_=wall_data(FINE);w.close()
    q,geom=reference();m=read_json(DATA/"actuator_disk_model.json")
    row=frame.iloc[-1];disk=qa["disk_integrals"]
    force={label:qa["forces_full_aircraft"][label]["mean_N"] for label in ("L_air","L_wing","D_air")}
    gross=2*sum(float(d["discrete_thrust_N"]) for d in disk);force.update(T_gross=gross,T_net=gross-force["D_air"])
    on=rpm[rpm.case==BASE].iloc[0];off=rpm[rpm.case==OFF].iloc[0]
    report=dict(accepted_case=case.name,accepted_data=dat.name,coordinate_convention="x downstream; y upward; z starboard; thrust magnitudes reported positive forward.",
                full_aircraft_forces_N=force,half_domain_forces_N={k:v/2 for k,v in force.items()},
                C_L=row.C_L,C_D=row.C_D,q_ref_Pa=q,V_ref_m_s=float(np.sqrt(2*q/m["rho_kg_m3"])),
                S_ref_m2=geom["full_planform_area_m2"],peak_suction=met["peak_suction"],
                gci=gcis,rpm_fits=fits,matched_medium_static_lift_increment_N=float(on["delta_L_static_N"]),swirl_span_partition=swirl_load_partition()[1],swirl_on_minus_off_full_N={k:float(on[k]-off[k]) for k in ("L_air_N","L_wing_N","D_air_N","T_net_N")},
                rpm_zero_source_baseline="Native same-medium static equilibrium",signed_pressure_forces="Gauge pressure integrated over aircraft surfaces.",
                sources=dict(pressure_shear="native face fields",thrust="native seven-disk volume integrals",coefficients="derived from area and fixed induced-velocity reference"))
    save_json(report,"summary_metrics.json")
    from prepare_airfoil_sections import CASES as planar_cases
    save_table(convergence_rows([*CASES3,*planar_cases]),"convergence_qa.csv")


def run(numbers,with_summary):
    apply_publication_style()
    for number in numbers:
        globals()["fig"+str(number)]()
    if with_summary:summary()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figures",type=int,nargs="*",choices=list(STEMS),default=list(STEMS))
    parser.add_argument("--summary",action="store_true",help="Publish the cross-case quantitative CSV and aggregate baseline metrics after all 13 3D endpoints pass")
    args=parser.parse_args()
    run(args.figures,args.summary)
