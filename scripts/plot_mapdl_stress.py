"""Figures 17 and 21 from native nodal loads, two-face SHELL181 fields and Fluent wall tractions."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
from matplotlib.lines import Line2D
from scipy.stats import gaussian_kde
from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset

from compare_x57_cases import ROOT, accepted
from extract_fluent_fields import extract_walls
from fsi_provenance import commit
from run_x57_converged import control
from p2_geometry_io import section_segments, heights
from plot_style import apply_publication_style, save_dual_figure, ACADEMIC_PALETTE
from render_mapdl_fields import physical_shell, STRUCT

FIG=ROOT/"DELIVERABLES"/"figures"
RENDERS=ROOT/"DELIVERABLES"/"fluent_renders"
NAMES=("Wing","Fuselage","Nacelles","Sponson","Empennage")
WALLS=("wall_wing","wall_fuselage","wall_nacelles","wall_sponson","wall_empennage")
CASES=("fine_rpm100","medium_rpm100_takeoff_v10","medium_opt_hlp_vector10")
CONDITIONS=("Static","Roll, 10 m/s","Vectored HLP")
COLORS=(ACADEMIC_PALETTE[0],ACADEMIC_PALETTE[1],ACADEMIC_PALETTE[2])


def span_resultants(mesh,fields):
    nodes=mesh["xyz"]
    elem=mesh["elements"]
    wing=(mesh["element_section"]==0)
    involved=wing|(mesh["element_section"]==2)|mesh["wingbox"]
    wing_ids=np.unique(elem[wing])
    ids=np.unique(elem[involved])
    force=np.load(STRUCT/"fine_struct__fine_rpm100"/"nodal_loads.npy")
    if force.shape!=(len(nodes),6):
        raise ValueError("Mapped forces and moments are incompatible with the Fine shell model")
    tags=json.loads((ROOT/"01_geometry/cad_component_regions.json").read_text())
    with np.load(ROOT/"01_geometry/cad_components.npz") as c:
        cad=np.concatenate([c[k] for k,v in tags.items() if v=="wall_wing"])
    halfspan=json.loads((ROOT/"01_geometry/geometry_audit.json").read_text())["wing_reference"]["full_span_m"]*.5
    zvals=np.linspace(.62,min(halfspan-.12,nodes[wing_ids,2].max()-.04),47)
    output=[]
    for z in zvals:
        segments=section_segments(cad,z)
        x=segments[:,:,0].min()+.30*np.ptp(segments[:,:,0])
        ycross=heights(segments,x)
        if not len(ycross):raise ValueError("No CAD intersection at the reference spar")
        origin=np.asarray((x,.5*(ycross.min()+ycross.max()),z))
        out=ids[nodes[ids,2]>=z]
        moment=-np.sum(np.cross(nodes[out]-origin,force[out,:3])+force[out,3:],axis=0)
        near=wing_ids[np.abs(nodes[wing_ids,2]-z)<.035]
        # Vertical deflection averaged on native wing-skin nodes nearest the spar station.
        if not len(near):raise ValueError("Wing skin sampling band misses the structural mesh")
        close=near[np.argsort(np.linalg.norm(nodes[near]-origin,axis=1))[:min(8,len(near))]]
        dy=fields["displacement_vector_m"][close,1].mean()
        output.append((z/halfspan,moment[0],moment[2],dy*1000))
    return np.asarray(output)


def unframed(ax,data,title):
    ax.imshow(data)
    ax.set_axis_off()
    ax.set_title(title,loc="left")


def figure17():
    study=json.loads((ROOT/"DELIVERABLES/data/fsi_structural_stress.json").read_text())
    if not study.get("stress_mesh_study_complete",study.get("stress_mesh_QA_passed")):raise ValueError("Stress mesh study incomplete")
    cases=study["shell_GCI"]
    mesh,fields,_=physical_shell()
    distribution=span_resultants(mesh,fields)
    # 2026-11-26: panels d/e (render17/render19) dropped, the report shows those native MAPDL renders in full
    # size; one row of the three plotted panels, plain-number log ticks (the minor-tick labels overlapped).
    fig=plt.figure(figsize=(7.2,2.6),layout="constrained")
    grid=fig.add_gridspec(1,3,width_ratios=(1.15,1,1))
    ax=fig.add_subplot(grid[0,0])
    spacing=[]
    labels=(("peak_element_average_top_or_bottom_von_mises_Pa","Peak stress"),
            ("area_weighted_p99_von_mises_Pa","Area P99 stress"),
            ("wingtip_patch_mean_displacement_magnitude_m","Tip displacement"))
    for (key,label),color in zip(labels,COLORS):
        for domain,series,style in [("Shell",cases,"o-"),("CFD load",study["CFD_load_grid_GCI_fixed_structure"],"s--")]:
            row=series[key];h=np.asarray(row["h_m"])*1000;spacing.extend(h)
            normal=np.asarray(row["values"])/row["values"][-1]
            ax.plot(h,normal,style,ms=3,color=color,label=label if domain=="Shell" else None)
            ax.errorbar(h[-1],normal[-1],abs(normal[-1])*row["reported_fine_percent_uncertainty"]/100,fmt="none",ecolor=color,capsize=3)
    ax.set_xscale("log")
    lo,hi=min(spacing)/1.15,max(spacing)*1.15
    ticks=[t for t in (5,10,20,30,50,100,200,300,500,1000,2000) if lo<=t<=hi]
    ax.set_xlim(lo,hi);ax.xaxis.set_major_locator(matplotlib.ticker.FixedLocator(ticks))
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v,_:f"{v:g}"))
    ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    ax.axhline(1,color=".5",lw=.6)
    ax.set(xlabel="Effective spacing (mm)",ylabel="Value / fine-grid value",title="a   Structural and CFD-load convergence")
    handles,legend_labels=ax.get_legend_handles_labels()
    handles.extend([Line2D([],[],marker="o",color=".3",lw=.7,ms=3),Line2D([],[],marker="s",ls="--",color=".3",lw=.7,ms=3)])
    ax.legend(handles,legend_labels+["Shell refinement","CFD-load refinement"],fontsize=5.5,frameon=False,ncol=1,labelspacing=0.25,
              loc="lower right",handlelength=1.6,borderaxespad=0.3)
    ax=fig.add_subplot(grid[0,1]);z,mx,mz,dy=distribution.T
    ax.plot(z,mx,label="Bending",color=COLORS[0]);ax.plot(z,mz,label="Torsion",color=COLORS[1])
    ax.set(xlabel="Span station, 2z/b",ylabel="Cut moment (N m)",title="b   Wing assembly resultants");ax.legend(fontsize=7,frameon=False)
    ax=fig.add_subplot(grid[0,2])
    ax.plot(z,dy,color=COLORS[0]);ax.set(xlabel="Span station, 2z/b",ylabel="Vertical deflection (mm)",title="c   Spar-line displacement")
    ax.axhline(0,color=".5",lw=.6)
    save_dual_figure(fig,FIG/"fig17_stress_convergence_and_fsi_structural");plt.close(fig)


def weighted_quantile(values,weights,levels):
    order=np.argsort(values);v=values[order];w=weights[order]
    return np.interp(levels,(np.cumsum(w)-.5*w)/np.sum(w),v,left=v[0],right=v[-1])


def collect(case):
    control()
    _, cas, dat = accepted(case)
    _, data, metrics = physical_shell(case)
    source = metrics["source_provenance"]
    work = STRUCT / ("fine_struct__" + case)
    result = (work / (source["job"] + ".rst")).resolve()
    # Re-read native Fluent face values at the same accepted checkpoint that drove SHELL181.
    wall = extract_walls(cas, dat)
    area = data["area_m2"]
    vm = np.max(data["top_bottom_vm_Pa"], axis=1) * 1.e-6
    s1 = np.max(data["top_bottom_S1_Pa"], axis=1) * 1.e-6
    tresca = np.max(data["top_bottom_tresca_max_shear_Pa"], axis=1) * 1.e-6
    tau = np.linalg.norm(wall["wall_shear_storage"], axis=1) / wall["area_m2"]
    if not np.isfinite(area).all() or np.any(area <= 0) or not all(
            np.isfinite(field).all() for field in (vm, s1, tresca, tau)):
        raise ValueError(f"Invalid stress samples or shell element area in {case}")
    component = wall["component"].astype(str)
    fields = ("von_Mises_MPa", "maximum_principal_MPa", "maximum_shear_MPa", "wall_shear_Pa")
    stats, components = [], {}
    for i, name in enumerate(WALLS):
        st = data["section"] == i
        fl = np.char.startswith(component, name)
        if not st.any() or not fl.any():
            raise ValueError(f"Missing structural or fluid samples in {case}/{name}")
        safety = data["safety_factor"][st]
        if np.isnan(safety).any() or np.any(safety <= 0):
            raise ValueError(f"Invalid yield safety factor in {case}/{name}")
        minimum = float(safety.min())
        samples = [(field[st], area[st]) for field in (vm, s1, tresca)] + [(tau[fl], wall["area_m2"][fl])]
        stats.append((samples, minimum))
        components[name] = dict(shell_elements=int(st.sum()), wall_faces=int(fl.sum()),
            shell_area_m2=float(area[st].sum()), wall_area_m2=float(wall["area_m2"][fl].sum()),
            min_yield_FoS=minimum if np.isfinite(minimum) else None,
            all_elements_stress_free=bool(np.isposinf(minimum)),
            native_ranges={key: [float(v.min()), float(v.max())] for key, (v, _) in zip(fields, samples)})
    evidence = dict(native_case=str(cas), native_data=str(dat),
        native_MAPDL_manifest=str(work/"native_result_provenance.json"),
        load_signature=source["load_signature"], result_file=str(result),
        result_sha256=source["sha256"][str(result)], components=components)
    control()
    return stats, evidence


def figure21():
    control()
    study = ROOT / "DELIVERABLES/data/fsi_structural_stress.json"
    if not (lambda s: s.get("stress_mesh_study_complete", s.get("stress_mesh_QA_passed")))(json.loads(study.read_text(encoding="utf8"))):
        raise ValueError("Figure 21 requires passing structural mesh convergence")
    collected = {case: collect(case) for case in CASES}
    data = [collected[case][0] for case in CASES]
    control()
    fig=plt.figure(figsize=(7.2,7.25),layout="constrained")
    grid=fig.add_gridspec(3,2,height_ratios=(1,1,.68))
    fields=("von Mises stress (MPa)","Maximum principal stress (MPa)","Maximum shear (MPa)","Wall shear stress (Pa)")
    for j,title in enumerate(fields):
        ax=fig.add_subplot(grid[j//2,j%2])
        for ci,run in enumerate(data):
            for component,(record,_) in enumerate(run):
                value,area=record[j]
                x=weighted_quantile(value,area,np.linspace(.001,.999,190))
                y=component+(ci-1)*.09
                # Equal-area quantiles bound KDE cost and leave the native extremes available for margins.
                cloud=weighted_quantile(value,area,np.linspace(.0005,.9995,512))
                if np.ptp(cloud)>max(1.e-14,np.max(np.abs(cloud))*1.e-12):
                    kde=gaussian_kde(cloud,bw_method="scott")(x)
                    height=kde/kde.max()*.37
                    ax.fill_between(x,y,y+height,color=COLORS[ci],alpha=.24,lw=0)
                    ax.plot(x,y+height,color=COLORS[ci],lw=.75)
                rain=weighted_quantile(value,area,np.linspace(.015,.985,15))
                offsets=np.resize([.046,.063,.081,.054,.072],len(rain))
                ax.scatter(rain,y-offsets,s=2,color=COLORS[ci],alpha=.44,edgecolors="none")
                lo,median,hi=weighted_quantile(value,area,[.25,.50,.75])
                ax.plot([lo,hi],[y,y],color=COLORS[ci],lw=1.3,solid_capstyle="round")
                ax.scatter([median],[y],s=6,color=COLORS[ci],edgecolors="none")
        ax.set_yticks(range(5),NAMES if j%2==0 else [""]*5)
        ax.set_xlabel(title);ax.set_ylim(-.35,4.63)
        ax.set_title(f"{'abcd'[j]}   {title.split(' (')[0]}",loc="left")
    ax=fig.add_subplot(grid[2,:])
    for ci,run in enumerate(data):
        minima=np.array([s[1] for s in run])
        finite=np.isfinite(minima)
        positions=np.arange(5)+(ci-1)*.13
        ax.scatter(positions[finite],minima[finite],color=COLORS[ci],label=CONDITIONS[ci],s=26)
        for pos in positions[~finite]:
            ax.text(pos,.97,"∞",color=COLORS[ci],ha="center",va="top",transform=ax.get_xaxis_transform())
    ax.set_yscale("log");ax.set_xticks(np.arange(5),NAMES)
    ax.set(ylabel="Minimum yield FoS",title="e   Safety margins under operating loads")
    ax.legend(ncols=3,loc="best",frameon=False,fontsize=8)
    stem="fig21_stress_envelope_and_ridge_distributions"
    fig.align_ylabels()
    control()
    save_dual_figure(fig,FIG/stem)
    plt.close(fig)
    commit(ROOT/"04_postproc/native_render_evidence"/(stem+".json"), dict(
        structural_QA=str(study), cases={case: collected[case][1] for case in CASES},
        envelope="Largest of the two element face values, with full native ranges preserved for each component.",
        distributions="Shell-element and CFD-face areas weighted independently; ridge width normalized per group. "
            "KDE sampled on 512 equal-area quantiles using Scott bandwidth; displayed from P0.1 to P99.9. "
            "Rain marks show 15 area quantiles; center marks show area median and interquartile range.",
        safety_measure="Minimum element yield safety factor. Infinity denotes zero stress throughout the component."))
    control()


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figures",type=int,nargs="+",choices=(17,21),default=(17,21))
    apply_publication_style()
    for n in parser.parse_args().figures:
        (figure17 if n==17 else figure21)()
