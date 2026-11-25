"""Assemble figure 22 from accepted CFD fields, a verified SHELL181 image and matched design comparisons."""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image
from plot_style import apply_publication_style,save_dual_figure,ACADEMIC_PALETTE
from compare_x57_cases import ROOT,BASE,VECTOR,load3
from read_x57_section import load_section,case_names
from plot_x57_comparisons import opt_table,sections3
from x57_baseline_data import FINE
from fsi_provenance import accepted_result, commit
from mapdl_shell_fields import source_hash
from render_mapdl_fields import STRUCT
from run_x57_converged import control
import pandas as pd

STRUCTURAL_RENDER="render17_fsi_von_mises_global_top_3d.png"
STEM="fig22_3d_2d_hybrid_aeropropulsive_synthesis"


def pressure_trace(sections, chord_station=.25):
    """Interpolate along measured upper/lower section intersections only."""
    numeric = sections[["z_m","x_over_c","Cp"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or sections[["station","side"]].isna().any().any():
        raise ValueError("Invalid measured quarter-chord source samples")
    rows=[]
    for (station,z,side),part in sections.groupby(["station","z_m","side"]):
        samples=part.groupby("x_over_c").Cp.mean().sort_index()
        if len(samples)<2 or not samples.index[0]<=chord_station<=samples.index[-1]:
            continue
        rows.append(dict(station=station,z_m=z,side=side,Cp=np.interp(chord_station,samples.index,samples)))
    data=pd.DataFrame(rows)
    if data.empty or set(data.side)!={"upper","lower"} or (data.groupby("side").size()<2).any():
        raise ValueError("Insufficient quarter-chord pressure samples from actual wall sections")
    coverage = data.groupby(["station","z_m"]).size()
    if len(coverage) != sections.groupby(["station","z_m"]).ngroups or not coverage.eq(2).all():
        raise ValueError("An upper or lower section does not bracket the requested chord station")
    return data.sort_values("z_m")


def draw(images,cp,design,loads,q_isovalue):
    fig,ax=plt.subplots(2,3,figsize=(7.2,5.1),layout="constrained",
                        gridspec_kw={"height_ratios":[.84,1]})
    for a,image,title in zip(ax[0],images,["a   Slipstreams",f"b   Q = {q_isovalue:.2g} s⁻²","c   Shell stress"]):
        a.imshow(image,interpolation="lanczos");a.set_axis_off();a.set_title(title,loc="left")
    a=ax[1,0]
    for i,side in enumerate(("upper","lower")):
        v=cp[cp.side==side]
        a.plot(v.z_m,v.Cp,marker=["o","s"][i],ls=["-","--"][i],ms=3,
               color=ACADEMIC_PALETTE[i],label=side.capitalize())
    a.set(title="d   Quarter-chord pressure",xlabel="Starboard z (m)",ylabel="$C_p$ at $x/c=0.25$")
    a.invert_yaxis();a.legend(fontsize=8)
    a=ax[1,1]
    nominal=loads["Nominal"]
    for j,(name,label,sign) in enumerate([("Zero swirl","ON − OFF",-1.),("Vectored","Vector − ON",1.)]):
        table=loads[name]
        bounds = ["z_lo_m","z_hi_m"]
        if (len(nominal)!=len(table) or
                not np.allclose(nominal[bounds],table[bounds],atol=1.e-10,rtol=0)):
            raise ValueError("Comparison uses different spanwise integration intervals")
        a.plot(table.z_m,sign*(table.dL_dz_N_per_m-nominal.dL_dz_N_per_m),
               ls=["-","--"][j],label=label,color=ACADEMIC_PALETTE[j])
    a.axhline(0,color=".5",lw=.5);a.set(title="e   Wing-load change",xlabel="Starboard z (m)",
                                        ylabel="Δ(dL/dz) (N/m)");a.legend(fontsize=8)
    a=ax[1,2]
    a.axhline(0,color=".6",lw=.6);a.axvline(0,color=".6",lw=.6)
    for i,row in enumerate(design.loc[design.dimension=="2D"].itertuples()):
        a.scatter(row.delta_C_D,row.delta_C_L,s=24,marker=["o","s","^","D","v"][i],
                  color=ACADEMIC_PALETTE[i],label=row.label)
    vectored=design.loc[design.case==VECTOR].iloc[0]
    a.scatter(vectored.delta_C_D,vectored.delta_C_L,marker="*",s=55,ec="k",fc="white",label="3D vector")
    a.set(title="f   High-lift changes",xlabel="Δ drag coefficient",ylabel="Δ lift coefficient")
    a.legend(fontsize=7,loc="best",handlelength=1.0,borderpad=.2,labelspacing=.18)
    for loc in ax.flat:
        loc.title.set_fontsize(8.5)
    return fig


def studio_flow_panels():
    import pyvista as pv
    from cmcrameri import cm
    from render_x57_comparisons import RANGE,add_body,body,plotter,scalarbar,shot
    from x57_stress_profiles import native_volume
    from vtk_x57_native_cells import mapped_volume

    control()
    source,case,data=native_volume()
    grid,mapping=mapped_volume(case,data,source,["velocity_m_s","Q_s_inv2"])
    roi=grid.clip_box(RANGE,invert=False,crinkle=True)
    points=roi.cell_data_to_point_data(pass_cell_data=False)
    airframe=body(case)
    aircraft=airframe.merge(airframe.reflect((0,0,1),point=(0,0,0)))
    rotors=json.loads((ROOT/"DELIVERABLES/data/actuator_disk_model.json").read_text())["rotors"]
    paths=[];seeding={}
    control()
    for disk in rotors:
        control()
        center=np.array(disk["center_m"],dtype=float)
        # Place seeds just downstream of the finite disk, outside its hub.
        center[0]+=.5*disk["thickness_m"]+.005
        radius=disk["r_hub_m"]+(disk["r_tip_m"]-disk["r_hub_m"])*np.array([.30,.75])
        theta=np.arange(12)*2*np.pi/12
        seeds=np.array([center+[0.,r*np.sin(t),r*np.cos(t)] for r in radius for t in theta])
        inside=seeds[roi.find_containing_cell(seeds)>=0]
        if not len(inside):raise ValueError("No physical seed within the wake of "+disk["name"])
        lines=points.streamlines_from_source(pv.PolyData(inside),vectors="velocity_m_s",
                    integration_direction="forward",integrator_type=45,initial_step_length=.15,
                    max_steps=3500,max_length=7.,terminal_speed=1.e-5)
        if not lines.n_lines:raise ValueError("No resolved streamline from "+disk["name"])
        lines["speed_m_s"]=np.linalg.norm(lines.point_data["velocity_m_s"],axis=1)
        paths.append(lines)
        seeding[disk["name"]]=dict(candidate_seed_count=len(seeds),fluid_seed_count=len(inside),
                                   actual_line_count=lines.n_lines)
        control()
    Q=np.asarray(roi.cell_data["Q_s_inv2"])
    if not np.isfinite(Q).all() or not np.isfinite(roi.cell_data["velocity_m_s"]).all():
        raise ValueError("Nonfinite velocity or Q in the wake region")
    positive=Q[Q>0]
    if not len(positive):raise ValueError("No rotation-dominated native fluid cells in the displayed wake")
    iso_value=float(np.quantile(positive,.90))
    iso=points.contour([iso_value],scalars="Q_s_inv2")
    if iso.n_cells==0:raise ValueError("Empty native Q isosurface")
    iso["speed_m_s"]=np.linalg.norm(iso.point_data["velocity_m_s"],axis=1)
    vmax=float(np.quantile(np.linalg.norm(roi.cell_data["velocity_m_s"],axis=1),.99))
    if not np.isfinite(vmax) or vmax<=0:raise ValueError("No positive velocity scale in the selected powered wake")
    images=[]
    for scene in ("streamlines","Q"):
        control()
        view=plotter("");add_body(view,aircraft)
        objects=[line.tube(radius=.010,n_sides=8) for line in paths] if scene=="streamlines" else [iso]
        for j,item in enumerate(objects):
            full=item.merge(item.reflect((0,0,1),point=(0,0,0)))
            view.add_mesh(full,scalars="speed_m_s",cmap=cm.batlow,clim=(0,vmax),smooth_shading=True,
                          split_sharp_edges=True,show_scalar_bar=j==0,scalar_bar_args=scalarbar("Speed (m/s)"))
        camera=[(7.,9.,8.),(.25,-.1,0.),(0,1,0)]
        images.append(shot(view,cam=camera,scale=5.5))
        control()
    return images,dict(velocity_source=str(source),cell_mapping=mapping,covered_seeds=seeding,
                       Q_isovalue_per_second_squared=iso_value,speed_color_limits_m_s=[0,vmax],
                       geometry="Starboard native fluid with symmetry-plane reflection for the full-aircraft view",
                       pathline_assumption="For a stationary velocity field, pathlines coincide with streamlines.",
                       rendering="white background, SSAO, SSAA, smooth lighting and split sharp edges")


def structural_panel():
    _, native = accepted_result("fine", FINE)
    work = STRUCT / ("fine_struct__" + FINE)
    result = (work / (native["job"] + ".rst")).resolve()
    manifest = work / "render_sources.json"
    path = ROOT / "DELIVERABLES/fluent_renders" / STRUCTURAL_RENDER
    entry = json.loads(manifest.read_text(encoding="utf8"))[path.name]
    expected = dict(source_case=FINE, path=str(path), result_file=str(result),
                    image_sha256=source_hash(path), result_sha256=native["sha256"][str(result)],
                    load_signature=native["load_signature"])
    if any(entry.get(k) != value for k, value in expected.items()):
        raise ValueError("Structural panel differs from the accepted Fine MAPDL result or render")
    with Image.open(path) as image:
        if image.width < 1920 or image.height < 1080:
            raise ValueError(f"Insufficient structural panel resolution: {image.size}")
        rgb = np.asarray(image.convert("RGB")).copy()
    return rgb, dict(manifest=str(manifest), **entry)


def section_source(directory, cas, dat, filename):
    path = directory / filename
    return dict(native_case=str(cas), native_data=str(dat), table=str(path),
                table_sha256=source_hash(path), checkpoint=str(directory/"source_checkpoint.json"))


def main():
    control()
    apply_publication_style()
    structural=ROOT/"DELIVERABLES/data/fsi_structural_stress.json"
    study=json.loads(structural.read_text(encoding="utf8"))
    if not study.get("stress_mesh_study_complete",study.get("stress_mesh_QA_passed")):
        raise ValueError("Figure 22 requires passing structural stress-mesh QA")
    shell_image, shell_source = structural_panel()
    control()
    images,studio=studio_flow_panels()
    images.append(shell_image)
    control()
    native_cp,_,out,case,data=sections3(FINE)
    cp=pressure_trace(native_cp)
    cp_source=section_source(out,case,data,"wing_sections.csv")
    loads,load_sources={},{}
    for name,label in [(BASE,"Nominal"),(BASE+"_noswirl","Zero swirl"),(VECTOR,"Vectored")]:
        control()
        _,table,folder,cas,dat=sections3(name)
        if not np.isfinite(table[["z_lo_m","z_hi_m","z_m","dL_dz_N_per_m"]].to_numpy()).all():
            raise ValueError(f"Nonfinite native span loading in {name}")
        loads[label]=table
        load_sources[label]=section_source(folder,cas,dat,"loading.csv")
    control()
    sections=[]
    for name in case_names():
        control()
        sections.append(load_section(name))
    designs=opt_table({n:load3(n) for n in (BASE,VECTOR)}, sections)
    columns=["case","dimension","label","matched_baseline","delta_C_L","delta_C_D","native_case","native_data","qa_file"]
    if not np.isfinite(designs[["delta_C_L","delta_C_D"]].to_numpy()).all():
        raise ValueError("Missing measured high-lift coefficient changes")
    control()
    fig=draw(images,cp,designs,loads,studio["Q_isovalue_per_second_squared"])
    save_dual_figure(fig,ROOT/"DELIVERABLES/figures"/STEM)
    plt.close(fig)
    commit(ROOT/"04_postproc/native_render_evidence"/(STEM+".json"), dict(
        native_case=str(case),native_data=str(data),structural_QA=str(structural),structural_panel=shell_source,
        studio_flow=studio,loads=load_sources,pressure_source=cp_source,pressure_stations=cp.to_dict("records"),
        matched_designs=designs[columns].to_dict("records"),
        caption="Quarter-chord pressure is interpolated within each measured upper and lower section. "
            "Positive load changes denote increased vertical wing force. The 2D reference is the clean "
            "blown section; the 3D reference is nominal Medium."))
    control()


if __name__=="__main__":main()
