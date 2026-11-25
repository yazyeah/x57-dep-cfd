"""Render X-57 matched-condition comparisons from accepted native case data."""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.collections import PolyCollection
from plot_style import apply_publication_style, save_dual_figure
from compare_x57_cases import (ROOT,BASE,ZERO,HLP,WT,ALT,OGE,ROLL,RKE,VECTOR,CASES3,STEMS,LABEL,
                               accepted,read_json,comparisons3,table13,table14,reference)
from read_x57_section import case_names,load_section
from cfd_verification import weighted_distribution
from extract_fluent_fields import extract_walls,extract_slice
from plot_fluent_sections import sample_on_grid

apply_publication_style()
plt.rcParams.update({"font.size":8.2,"axes.titlesize":9.5,"axes.labelsize":8.4,"xtick.labelsize":7.6,
                     "ytick.labelsize":7.6,"legend.fontsize":7.2,"lines.linewidth":1.2,
                     "figure.facecolor":"white","axes.facecolor":"white","pdf.fonttype":42})
COLORS=["#245C85","#B5492C","#287B64","#926200","#714C88"]
MARKS=["o","s","^","D","v"]
OUT=ROOT/"DELIVERABLES"; POST=ROOT/"04_postproc"

def panel(ax,letter,title):
    ax.set_title(f"{letter}   {title}",loc="left",fontweight="bold",pad=5)
    if ax.name!="polar":
        ax.spines[["top","right"]].set_visible(False)
        ax.grid(axis="y",alpha=.18,zorder=0)
    return ax

def finish(fig,num,output,desc):
    output.mkdir(parents=True,exist_ok=True)
    stem=STEMS[num]
    save_dual_figure(fig,output/stem,dpi=400)
    plt.close(fig)

def compared_bars(ax,labels,series,ylabel):
    x=np.arange(len(labels));width=.76/len(series)
    for i,(title,values) in enumerate(series):
        ax.bar(x+(i-(len(series)-1)/2)*width,values,width,label=title,color=COLORS[i],edgecolor="#292929",lw=.35,zorder=2)
    ax.set(xticks=x,xticklabels=labels,ylabel=ylabel)
    ax.axhline(0,color=".38",lw=.55)
    low,high=ax.get_ylim()
    ax.set_ylim(low,high+.19*(high-low))
    ax.legend(frameon=False,loc="upper left",ncol=len(series))

def fig13(t,out):
    fig,axs=plt.subplots(2,2,figsize=(7.08,5.75),layout="constrained")
    z=t.set_index("case"); ii=[HLP,WT,BASE,ALT]; labels=["HLP","Wingtip","All","Alternating"]
    a=panel(axs[0,0],"a","Installed lift and wetted lift")
    compared_bars(a,labels,[("Wetted",z.loc[ii,"L_wall_N"]),("Installed",z.loc[ii,"L_installed_N"])],"Full-aircraft lift (N)")
    a=panel(axs[0,1],"b","Pressure and viscous contributions")
    compared_bars(a,labels,[("Pressure",z.loc[ii,"L_pressure_N"]),("Viscous",z.loc[ii,"L_viscous_N"])],"Wetted lift (N)")
    a=panel(axs[1,0],"c","Factorial interaction")
    keys=["L_wall_N","L_wing_N","D_wall_N"]
    d=z.loc["full_minus_hlp_minus_wingtip_plus_unpowered",keys].to_numpy(float)
    a.barh(["Airframe lift","Wing lift","Wetted drag"],d,color=COLORS[:3],edgecolor=".25",lw=.4)
    a.axvline(0,lw=.6,color=".35");a.set_xlabel("Full − HLP − wingtip + unpowered (N)")
    a=panel(axs[1,1],"d","Effect of adjacent rotor handedness")
    d=(z.loc[ALT,keys]-z.loc[BASE,keys]).to_numpy(float)
    a.barh(["Airframe lift","Wing lift","Wetted drag"],d,color=COLORS[:3],edgecolor=".25",lw=.4)
    a.axvline(0,lw=.6,color=".35");a.set_xlabel("Alternating − nominal (N)")
    finish(fig,13,out,"Matched medium grid; additive contrast uses the zero-source static equilibrium. Installed lift includes the direct propulsor reaction.")

def fig14(t,out):
    fig,axs=plt.subplots(1,2,figsize=(7.08,3.05),layout="constrained")
    z=t.set_index("case"); ids=[BASE,OGE,ROLL]
    a=panel(axs[0],"a","Aircraft and wing response")
    compared_bars(a,["Static IGE","Open lower","10 m/s"],[("Airframe",z.loc[ids,"L_wall_N"]),("Wing",z.loc[ids,"L_wing_N"])],"Wetted lift (N)")
    a=panel(axs[1],"b","Change from static runway")
    ids=[OGE,ROLL]
    compared_bars(a,["Open lower","10 m/s"],[("Δ lift",z.loc[ids,"delta_L_wall_N"]),("Δ drag",z.loc[ids,"delta_D_wall_N"])],"Full-aircraft force increment (N)")
    finish(fig,14,out,"Lower-boundary replacement and prescribed 10 m/s freestream/ground motion are separate matched sensitivities. Rotor loading stays fixed.")

def sections3(name):
    qa,cas,dat=accepted(name)
    out=POST/name/("comparison_"+cas.name[:-7]); marker=out/"source_checkpoint.json"
    signature={"span_partition":"WT-inboard-tip-v1","case":str(cas),"data":str(dat),"case_size":cas.stat().st_size,"dat_size":dat.stat().st_size,"data_mtime_ns":dat.stat().st_mtime_ns}
    if not marker.is_file() or read_json(marker)!=signature or not (out/"wing_sections.csv").is_file():
        from wing_surface_metrics import examine
        examine(cas,dat,out);marker.write_text(json.dumps(signature),encoding="utf8")
    return pd.read_csv(out/"wing_sections.csv"),pd.read_csv(out/"loading.csv"),out,cas,dat

def hlp3_probe(name):
    cp,load,out,cas,dat=sections3(name);p=cp.loc[cp.station=="HLP-3"]
    if p.empty:raise ValueError(f"Missing HLP-3 Cp trace for {name}.")
    file=out/"hlp3_slice.npz";z=p.z_m.iloc[0]
    if not file.exists():np.savez_compressed(file,**extract_slice(cas,dat,2,float(z)))
    with np.load(file) as cut:
        xy=cut["xy"];off=cut["offsets"]; x=.35
        polys=[xy[a:b] for a,b in zip(off[:-1],off[1:])]
        loc=[];vel=[]
        for j,poly in enumerate(polys):
            if poly[:,0].min()>x or poly[:,0].max()<=x:continue
            nxt=np.roll(poly,-1,axis=0);cross=(poly[:,0]>x)!=(nxt[:,0]>x)
            qv=poly[cross];ev=nxt[cross]
            y=qv[:,1]+(x-qv[:,0])/(ev[:,0]-qv[:,0])*(ev[:,1]-qv[:,1]);y=np.sort(y)
            for lo,hi in zip(y[::2],y[1::2]):
                if hi>=-1.0 and lo<=.95:
                    loc.extend([max(lo,-1.),min(hi,.95),np.nan]);vel.extend([cut["u_m_s"][j],cut["u_m_s"][j],np.nan])
    return p,np.asarray(loc),np.asarray(vel),load

def fig15(cases,out):
    fig,axs=plt.subplots(2,2,figsize=(7.08,5.85),layout="constrained")
    a=panel(axs[0,0],"a","HLP-3 wing pressure")
    b=panel(axs[0,1],"b","HLP-3 wake at x = 0.35 m")
    c=panel(axs[1,0],"c","Spanwise wing loading")
    for i,name in enumerate([BASE,RKE]):
        label=["SST","Realizable k–ε"][i];cp,y,u,load=hlp3_probe(name)
        for side,ls in [("upper","-"),("lower","--")]:
            tab=cp[cp.side==side].sort_values("x_over_c")
            a.plot(tab.x_over_c,tab.Cp,ls=ls,color=COLORS[i],label=label+" "+side)
        for k in range(0,len(y),3):
            b.plot(u[k:k+2],y[k:k+2],color=COLORS[i],lw=1.3,label=label if k==0 else None)
        c.plot(load.z_m,load.dL_dz_N_per_m,ls=["-","--"][i],color=COLORS[i],label=label)
    a.set(xlabel="Baseline chord fraction",ylabel="Pressure coefficient");a.invert_yaxis();a.legend(frameon=False,ncol=2,fontsize=6.5)
    b.set(xlabel="Axial velocity (m/s)",ylabel="Vertical position (m)");b.legend(frameon=False)
    c.set(xlabel="Starboard span (m)",ylabel="Wing lift per span (N/m)");c.legend(frameon=False)
    d=panel(axs[1,1],"d","Wetted force coefficients")
    compared_bars(d,["SST","Realizable k–ε"],[("Lift",[cases[n]["C_L"] for n in [BASE,RKE]]),("Drag",[cases[n]["C_D"] for n in [BASE,RKE]])],"Coefficient")
    finish(fig,15,out,"Two matched medium-grid models. Upper and lower wall pressure traces use a common nominal dynamic pressure; wake values are native cell-constant interval samples.")

def pareto(drag,lift):
    x=np.asarray(drag);y=np.asarray(lift)
    return np.array([not np.any((x<=a)&(y>=b)&((x<a)|(y>b))) for a,b in zip(x,y)])

def opt_table(rows,sections):
    table=pd.DataFrame([rows[BASE],rows[VECTOR]]+[s[0] for s in sections])
    for dimension,group in table.groupby("dimension",sort=False):
        base=group.iloc[0]
        for k in ["C_L","C_D","L_wall_N","D_wall_N"]:
            table.loc[group.index,"delta_"+k]=group[k]-base[k]
        table.loc[group.index,"matched_baseline"]=base["case"]
        table.loc[group.index,"pareto_within_dimension"]=pareto(group.C_D,group.C_L)
    return table

def fig16(cases,table,sections,out):
    t=table.loc[table.dimension=="2D"].reset_index(drop=True)
    best=int(t.C_L.idxmax());selected=t.iloc[best]
    row,wall,(polys,vals)=load_section(selected["case"],flow=True)
    fig=plt.figure(figsize=(7.08,6.95),layout="constrained")
    gs=fig.add_gridspec(3,2,height_ratios=[1.0,1.05,1.05]);a=panel(fig.add_subplot(gs[0,:]),"a",f"Native velocity and streamlines · {selected.label}")
    x0=wall.x_m.min();x1=wall.x_m.max();cc=row["c_ref_m"];ym=.5*(wall.y_m.min()+wall.y_m.max())
    box=(x0-.16*cc,x1+.28*cc,ym-.28*cc,ym+.28*cc)
    keep=[i for i,v in enumerate(polys) if v[:,0].max()>=box[0] and v[:,0].min()<=box[1] and v[:,1].max()>=box[2] and v[:,1].min()<=box[3]]
    shapes=[polys[i] for i in keep];vel={k:v[keep] for k,v in vals.items()}
    speed=np.hypot(vel["u_m_s"],vel["v_m_s"]);field=PolyCollection(shapes,array=speed,cmap="viridis",lw=0,rasterized=True)
    a.set_facecolor("#DADADA");a.grid(False);a.add_collection(field);a.set(xlim=box[:2],ylim=box[2:],aspect="equal",xlabel="x (m)",ylabel="y (m)")
    x,y,grid=sample_on_grid(shapes,vel,box,cc/170)
    a.streamplot(x,y,np.ma.masked_invalid(grid["u_m_s"]),np.ma.masked_invalid(grid["v_m_s"]),density=.8,color="white",linewidth=.45,arrowsize=.55)
    fig.colorbar(field,ax=a,label="Speed (m/s)",shrink=.78)
    b=panel(fig.add_subplot(gs[1:,0]),"b","Section pressure")
    for i,(r,w,_) in enumerate(sections):
        for (zone,side),q in w.groupby(["zone","side"]):
            q=q.sort_values("x_over_c")
            b.plot(q.x_over_c,q.Cp,color=COLORS[i],ls="-" if side=="upper" else "--",label=r["label"] if zone=="wall_main" and side=="upper" else None)
    b.invert_yaxis();b.set(xlabel="Baseline chord fraction",ylabel="Pressure coefficient");b.legend(frameon=False,fontsize=6.9)
    c=panel(fig.add_subplot(gs[1,1]),"c","Section design increments")
    for i,r in t.iterrows():c.scatter(r.delta_C_D,r.delta_C_L,color=COLORS[i],marker=MARKS[i],label=r.label,s=26)
    c.axhline(0,lw=.55,color=".5");c.axvline(0,lw=.55,color=".5");c.set(xlabel="Change in drag coefficient",ylabel="Change in lift coefficient")
    d=panel(fig.add_subplot(gs[2,1]),"d","3D thrust vectoring")
    ii=[BASE,VECTOR]
    compared_bars(d,["Nominal","Vector −10°"],[("Wetted",[cases[n]["L_wall_N"] for n in ii]),("Direct reaction",[cases[n]["L_actuator_reaction_N"] for n in ii])],"Full-aircraft lift (N)")
    finish(fig,16,out,"Flow is shown for the accepted 2D design with the greatest measured lift coefficient; bodies are masked by native cell topology. Both dimensions use the nominal dynamic pressure, with distinct reference areas.")

KPI=["C_L","C_D","C_M","L_over_D","CL_pressure","CL_viscous","Cp_min","tau95_Pa","yplus95","mass_imbalance_percent"]
KTICK=["Lift","Drag","Pitch","L/D","Press. lift","Visc. lift","Min. Cp","Shear","Wall y+","Flux err."]

def enrich3(row):
    _,cas,dat=accepted(row["case"]); w=extract_walls(cas,dat)
    wing=np.char.startswith(w["component"],"wall_wing");a=w["area_m2"][wing]; q=row["q_ref_Pa"]
    tau=np.linalg.norm(w["wall_shear_storage"][wing],axis=1)/a
    return dict(row,Cp_min=float(np.min(w["p_gauge_Pa"][wing])/q),tau95_Pa=weighted_distribution(tau,a)["p95"],
                yplus95=weighted_distribution(w["yplus"][wing],a)["p95"])

def mass_imbalance(row):
    qa=read_json(ROOT/row["qa_file"])
    if "mass_balance" in qa and "imbalance_fraction" in qa["mass_balance"]:
        return 100*float(qa["mass_balance"]["imbalance_fraction"])
    raise ValueError(f"{row['case']} requires a native signed open-boundary mass balance in QA.")

def matrix19(rows,sections):
    items=[enrich3(rows[n]) for n in CASES3]+[q[0] for q in sections]
    t=pd.DataFrame(items);t["mass_imbalance_percent"]=[mass_imbalance(r) for r in items]
    for dimension,g in t.groupby("dimension"):
        for k in KPI:
            raw=g[k].to_numpy(dtype=float)
            finite=np.isfinite(raw)
            if not finite.any():raise ValueError(f"No measured value for {k} in {dimension}.")
            lo,hi=float(np.nanmin(raw)),float(np.nanmax(raw))
            t.loc[g.index,k+"_scaled"]=(g[k]-lo)/(hi-lo) if hi>lo else np.where(finite,.5,np.nan)
            t.loc[g.index,k+"_group_min"]=lo;t.loc[g.index,k+"_group_max"]=hi
    return t

def fig19(t,out):
    fig=plt.figure(figsize=(7.08,8.3),layout="constrained")
    gs=fig.add_gridspec(2,2,height_ratios=[2.5,1.15])
    ax=panel(fig.add_subplot(gs[0,:]),"a","Eighteen verified cases")
    A=t[[k+"_scaled" for k in KPI]].to_numpy(float)
    masked=np.ma.masked_invalid(A); cmap=plt.get_cmap("viridis").copy();cmap.set_bad("#EEEEEE")
    im=ax.imshow(masked,aspect="auto",cmap=cmap,vmin=0,vmax=1);ax.grid(False)
    ax.set(yticks=np.arange(len(t)),yticklabels=t.label,xticks=np.arange(len(KPI)),xticklabels=KTICK)
    ax.tick_params(axis="x",labelrotation=32,labelsize=7)
    ax.axhline(len(CASES3)-.5,color="white",lw=2.2)
    for (r,c),v in np.ndenumerate(A):
        ax.text(c,r,"—" if not np.isfinite(v) else f"{v:.2f}",color="white" if np.isfinite(v) and v<.52 else "#151515",ha="center",va="center",fontsize=6.1)
    fig.colorbar(im,ax=ax,fraction=.035,pad=.02,label="Within-dimension range")
    b=panel(fig.add_subplot(gs[1,0],projection="polar"),"b","Matched 3D sensitivities")
    cols=["C_L","C_D","C_M","Cp_min","yplus95"];angles=np.linspace(0,2*np.pi,len(cols),endpoint=False);end=np.r_[angles,angles[0]]
    selected=[BASE,OGE,ROLL,VECTOR]; lab=["Nominal","Open lower","Roll","Vector"]
    for i,(n,short) in enumerate(zip(selected,lab)):
        vals=t.loc[t.case==n,[k+"_scaled" for k in cols]].iloc[0].to_numpy(float)
        b.plot(end,np.r_[vals,vals[0]],color=COLORS[i],ls=["-","--","-.",":"][i],label=short,marker=MARKS[i],ms=2.4)
    b.set(xticks=angles,xticklabels=["Lift","Drag","Pitch","Min. Cp","Wall y+"],ylim=(0,1),yticks=[.5,1],yticklabels=["0.5","1"])
    b.set_title("b   Matched 3D sensitivities",loc="left",fontweight="bold",y=1.16,pad=2)
    b.tick_params(labelsize=6.8);b.legend(loc="lower center",bbox_to_anchor=(.5,-.31),ncol=2,frameon=False,fontsize=6)
    c=panel(fig.add_subplot(gs[1,1]),"c","Two-dimensional design frontier")
    opt=t[t.dimension=="2D"].copy();dx=opt.C_D-opt.C_D.iloc[0];dy=opt.C_L-opt.C_L.iloc[0]
    best=pareto(dx,dy); order=np.argsort(dx[best].to_numpy())
    if sum(best)>1:c.plot(dx[best].iloc[order],dy[best].iloc[order],ls="--",color=".4",lw=.8)
    for i,(x,y,r) in enumerate(zip(dx,dy,opt.itertuples())):
        c.scatter(x,y,color=COLORS[i],marker=MARKS[i],s=30,label=r.label)
    c.set(xlabel="Δ drag coefficient",ylabel="Δ lift coefficient");c.legend(frameon=False,fontsize=6.0)
    finish(fig,19,out,"Each KPI is min–max scaled separately within the 3D and 2D cohorts. Values denote magnitude and need not denote design benefit. Constant KPIs map to 0.5; unavailable ratios remain blank. The frontier maximizes lift and minimizes drag.")

def write_expanded_summary(cases, sections, destination):
    """Report the 18 accepted CFD endpoints and explicitly matched comparisons."""
    from control_gate import atomic_write_json
    from prepare_airfoil_sections import CASES as design_names
    designs = [s[0] for s in sections]
    if [d["case"] for d in designs] != list(design_names):
        raise ValueError("Need all five independently accepted planar designs")
    quantities = ("C_L", "C_D", "C_M", "L_wall_N", "D_wall_N", "Mz_wall_Nm")
    def endpoint(row):
        keys = ("case","dimension","native_case","native_data","qa_file",*quantities)
        result = {k:row[k] for k in keys}
        result["force_basis"] = "full symmetric airframe, N" if row["dimension"]=="3D" else "per unit span, N/m"
        return result
    def contrast(row, base):
        return {"case":row["case"],"baseline":base["case"], "dimension":row["dimension"],
                "change":{k:float(row[k]-base[k]) for k in quantities}}
    medium = cases[BASE]
    configurations = (HLP,WT,ALT,OGE,ROLL,RKE,VECTOR,BASE+"_noswirl")
    effects = [contrast(cases[n],medium) for n in configurations]
    effects.extend(contrast(row,designs[0]) for row in designs[1:])
    interaction = table13(cases).iloc[-1]
    outputs = {key:float(interaction[key]) for key in
               ("L_wall_N","L_wing_N","D_wall_N","Mz_wall_Nm","L_installed_N","C_L","C_D")}
    frontier = pareto([row["C_D"] for row in designs],[row["C_L"] for row in designs])
    result = dict(accepted_3d_cases=len(CASES3),accepted_2d_cases=len(designs),
                  cases=[endpoint(cases[n]) for n in CASES3]+[endpoint(row) for row in designs],
                  two_dimensional_pareto_front=[r["case"] for r,keep in zip(designs,frontier) if keep],
                  matched_effects=effects,augmented_unpowered_control=endpoint(cases[ZERO]),
                  propulsion_interaction_full_minus_hlp_minus_wingtip_plus_unpowered=outputs,
                  reference="All coefficients use nominal disk-induced dynamic pressure. Dimensional 2D coefficients use the baseline section chord and a unit span. Deltas use the same dimensional cohort and reference across both endpoints.")
    if len({r["case"] for r in result["cases"]})!=18:
        raise ValueError("Expected 18 distinct accepted study cases")
    json.dumps(result,allow_nan=False)
    atomic_write_json(destination,result)


def run(numbers,tables_only=False):
    numbers=set(numbers)
    # Sensitivity table always includes both matched boundary changes and the RKE model.
    # A single-figure preview does not publish the four-case table until it is complete.
    cases=comparisons3(numbers)
    sections=[load_section(n) for n in case_names()] if numbers & {16,19} else []
    datadir=OUT/"data";figdir=OUT/"figures"
    def save(frame,name):
        datadir.mkdir(parents=True,exist_ok=True)
        dest=datadir/name;tmp=dest.with_name(dest.name+".pending")
        frame.to_csv(tmp,index=False);tmp.replace(dest)
    if 13 in numbers:
        t=table13(cases);save(t,"propulsion_decomposition.csv")
        if not tables_only:fig13(t,figdir)
    if numbers & {14,15}:
        t=table14(cases)
        if {BASE,OGE,ROLL,RKE}.issubset(cases):save(t,"sensitivity_ige_roll_turb.csv")
        if 14 in numbers and not tables_only:fig14(t,figdir)
        if 15 in numbers and not tables_only:fig15(cases,figdir)
    if 16 in numbers:
        t=opt_table(cases,sections);save(t,"design_optimization_results.csv")
        if not tables_only:fig16(cases,t,sections,figdir)
    if {13,14,15,16,19}.issubset(numbers):
        write_expanded_summary(cases,sections,datadir/"expanded_experiments_summary.json")
    if 19 in numbers:
        t=matrix19(cases,sections);save(t,"ablation_kpi_matrix.csv")
        if not tables_only:fig19(t,figdir)

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--figures",nargs="+",type=int,choices=sorted(STEMS),default=sorted(STEMS))
    p.add_argument("--tables-only",action="store_true")
    args=p.parse_args()
    run(args.figures,args.tables_only)
