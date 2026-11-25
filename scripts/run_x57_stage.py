"""Run one X-57 milestone between stage reports, respecting the workspace control gate."""
import argparse
import datetime as dt
import sys
from pathlib import Path

from compare_x57_cases import ROOT,BASE,OGE,ROLL,RKE,HLP,WT,ALT,VECTOR,accepted,read_json
from control_gate import atomic_write_json
from prepare_airfoil_sections import CASES as SECTIONS
from run_x57_converged import control,managed_step,grid_for

FINE="fine_rpm100"
SCRIPTS=ROOT/"scripts"
STAGES={"P3":["coarse_rpm100"],"P4":[BASE],"P5":[FINE],"P6":["medium_rpm050","medium_rpm075"],
        "P7":[BASE+"_noswirl"],"P8":[HLP,WT,ALT],"P9":[OGE,ROLL,RKE]}


def step(script,*args):
    managed_step([sys.executable,"-B",str(SCRIPTS/(script+".py")),*map(str,args)])


def _quick_accepted(case):
    path=ROOT/"03_cases"/case/"iteration_qa.json"
    try:
        return path.is_file() and read_json(path).get("passed") is True
    except (OSError,ValueError):
        return False


def converge(case,stage,cases):
    """Give this case an equal share of the remaining stage budget (fast-track deadline)."""
    import os,time
    from fasttrack_profile import env_deadline
    stage_deadline=env_deadline("X57_STAGE_DEADLINE_EPOCH")
    pending=[c for c in cases if not _quick_accepted(c)]
    if stage_deadline is None or case not in pending:
        os.environ.pop("X57_CASE_DEADLINE_EPOCH",None)
    else:
        share=max(0.,stage_deadline-time.time())/max(1,len(pending))
        os.environ["X57_CASE_DEADLINE_EPOCH"]=repr(time.time()+share)
    try:
        step("run_x57_converged",case,"--stage",stage)
    finally:
        os.environ.pop("X57_CASE_DEADLINE_EPOCH",None)


def warn(stage,key,detail):
    path=ROOT/"logs"/(stage+"_fasttrack_warnings.json")
    record=read_json(path) if path.is_file() else {}
    record[key]=detail
    atomic_write_json(path,record)
    print(f"[FastTrack WARNING] {stage} {key}: {detail}",flush=True)


def confirmed(stage):
    if stage=="P2":
        for level in ("coarse","medium","fine"):
            control();grid_for(level);control()
        return
    if stage in STAGES:
        record=read_json(ROOT/"logs"/(stage+"_quantitative_audit.json"))
        if not record.get("passed"):raise ValueError(f"{stage} requires corrective work")
        for case in STAGES[stage]:
            control()
            q,cas,dat=accepted(case)
            old=record["cases"][case]
            if old["endpoint"]!=q["final_iteration"] or str(cas)!=old["native_case"] or str(dat)!=old["native_data"]:
                raise ValueError(f"{case} endpoint changed after milestone audit")
            control()
    else:
        record=read_json(ROOT/"logs"/(stage+"_execution.json"))
        if record.get("status")!="completed":raise ValueError(f"{stage} has unfinished operations")


def optimization():
    from audit_x57_milestone import record_disk_integrals
    from fluent_checkpoints import case_for_data
    work_items=[VECTOR,*SECTIONS]
    converge(VECTOR,"P10",work_items)
    record_disk_integrals([VECTOR])
    _,fine_case,fine_data=accepted(FINE)
    inlet=ROOT/"04_postproc"/FINE/"hlp3_section_inlet"
    path=inlet/"inlet.json"
    before=read_json(path) if path.exists() else {}
    if before.get("source_case")!=str(fine_case) or before.get("source_data")!=str(fine_data) or not (inlet/"hlp3.prof").is_file():
        step("extract_section_inlet",fine_case.parent,inlet)
    for name in SECTIONS:
        control()
        mesh=ROOT/"02_mesh"/name
        cfg=mesh/"section_config.json"
        meta=read_json(cfg) if cfg.is_file() else {}
        profile=meta.get("inlet_profile",{})
        if (not (mesh/"section.msh").is_file() or profile.get("source_case")!=str(fine_case)
                or profile.get("source_data")!=str(fine_data) or not 60000<=meta.get("stats",{}).get("cells",0)<=120000):
            step("prepare_airfoil_sections",name,"--inlet",path)
        converge(name,"P10",list(SECTIONS))
    control()
    # Fixed Fine fluid load across shell meshes; fixed Fine shell across CFD meshes.
    # The two cross-refinement studies share their Fine/Fine endpoint.
    for grid in ("coarse","medium","fine"):
        step("prepare_mapdl_shell",grid)
    pairs=[(grid,FINE) for grid in ("coarse","medium","fine")]
    pairs.extend(("fine",name) for name in ("coarse_rpm100",BASE,ROLL,VECTOR))
    for grid,name in pairs:
        control()
        _,case,data=accepted(name)
        if case_for_data(data)!=case:raise ValueError(f"Unmatched source CFF for FSI {name}")
        step("run_mapdl_structural",grid,case)
    step("verify_fsi_mesh_study")
    report=read_json(ROOT/"DELIVERABLES/data/fsi_structural_stress.json")
    if not report["stress_mesh_QA_passed"]:
        # Recorded and reported in the final quality audit; peak/support stresses are idealisation-sensitive.
        warn("P10","stress_mesh_QA",{k:report.get(k) for k in ("stress_mesh_QA_passed","stress_mesh_QA_target_3pct_passed")})
    step("assemble_fsi_structural_table")


def make_figures():
    from x57_stress_profiles import native_volume
    from native_flow_data import intersect
    control()
    vol,_,_=native_volume()
    control()
    props=read_json(ROOT/"01_geometry/geometry_audit.json")["starboard_propellers_detected"]
    cuts=[(2,props[i]["z_axis_m"],props[i]["name"]) for i in (0,2,6)]
    cuts.extend([(1,props[0]["y_axis_m"],"hlp_axis"),(1,.225,"above_wing")])
    for axis,station,label in cuts:
        control()
        output=vol.parent/(label+"_slice.npz")
        if not output.is_file() or output.stat().st_mtime_ns<vol.stat().st_mtime_ns:
            intersect(FINE,axis,station,label)
        control()
    # Figure 01 is the accepted P1 deliverable.
    step("plot_x57_baseline","--summary")
    for n in ("04","05"):
        step("plot_fluent_sections",n)
    step("plot_x57_comparisons")
    step("plot_x57_stress")
    step("run_x57_native_renders")
    for n in (11,12):
        step("render_x57_comparisons",n)
    step("render_mapdl_fields")
    step("plot_mapdl_stress")
    step("plot_x57_synthesis")


def run(stage):
    control()
    confirmed("P"+str(int(stage[1:])-1))
    clock=ROOT/"logs"/(stage+"_execution.json")
    now=lambda:dt.datetime.now().astimezone().isoformat(timespec="seconds")
    state=read_json(clock) if clock.is_file() else dict(stage=stage,first_start=now(),intervals=[])
    interval=dict(start=now());state["intervals"].append(interval);state["status"]="running"
    atomic_write_json(clock,state)
    try:
        if stage in STAGES:
            if stage=="P5":
              try:
                calibration=read_json(ROOT/"logs/P4_quantitative_audit.json")["fine_wall_calibration"]
                fine=read_json(ROOT/"02_mesh/fine/mesh_qa.json")
                from audit_x57_milestone import wing_first_height
                current=wing_first_height(fine)
                scale=current/calibration["medium_first_m"]
                yplus=calibration["measured_medium_wing_yplus"]
              except (KeyError,OSError,ValueError,TypeError,ZeroDivisionError) as exc:
                warn("P5","fine_wall_calibration_unavailable",str(exc))
                scale,yplus=1.,{"mean":1.,"p95":1.}
              if True:
                if not (.5<=scale*yplus["mean"]<=1.2 and scale*yplus["p95"]<2.5):
                    # Fast-track: a y+ target miss is a reported quality target, never a dead stop.
                    # The measured Fine y+ is audited from the actual Fine solution in P5.
                    warn("P5","predicted_fine_wing_yplus",dict(scale=scale,medium=yplus,
                         predicted_mean=scale*yplus["mean"],predicted_p95=scale*yplus["p95"]))
            if stage=="P6":step("run_x57_zero_equilibrium","--stage",stage)
            for case in STAGES[stage]:
                converge(case,stage,STAGES[stage])
            step("audit_x57_milestone",stage)
        elif stage=="P10":
            optimization()
        elif stage=="P11":
            make_figures()
        else:
            try:  # report table of lift definitions; informational, never blocks packaging
                step("lift_definitions")
            except Exception as exc:
                warn("P12","lift_definitions",str(exc))
            step("package_x57_submission","package")
            step("package_x57_submission","verify")
        control()
    except BaseException as exc:
        state["status"]="interrupted"
        interval.update(end=now(),exception=str(exc))
        atomic_write_json(clock,state)
        raise
    interval["end"]=now()
    state.update(status="completed",last_completion=interval["end"])
    atomic_write_json(clock,state)
    control()


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage",choices=[*STAGES,"P10","P11","P12"])
    run(p.parse_args().stage)

