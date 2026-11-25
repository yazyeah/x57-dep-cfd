"""Prepare, run and independently audit the zero-RPM medium-mesh equilibrium reference."""
import argparse,hashlib,json,os,subprocess,sys
from control_gate import checked_command
from pathlib import Path
import h5py
import numpy as np
from compare_x57_cases import ROOT,BASE,ZERO,accepted,read_json
from assess_fluent_case import flux_value
from fluent_checkpoints import case_for_data
from cut_fluent_cells import bounds,zones

WORK=ROOT/"03_cases"/ZERO
TOL={"MaxVelocity":1.e-6,"MaxAbsGaugePressure":1.e-4,"MaxTemperatureDeparture":1.e-5}
ROLE="Auxiliary zero-source static-equilibrium reference, excluded from the 18 production cases and three-point RPM fit."


def gate():
    checked_command([sys.executable,str(ROOT/"scripts/control_gate.py"),"check"],cwd=ROOT)


def mesh_signature(case):
    h=hashlib.sha256()
    with h5py.File(case) as f:
        m=f["meshes/1"]
        for z in ("cells","faces","nodes"):
            top=m[z+"/zoneTopology"]
            label=sorted(zones(top).items()) if "name" in top else [(int(lo),int(hi)) for lo,hi in zip(top["minId"],top["maxId"],strict=True)]
            h.update(json.dumps(label).encode())
        for group,key,kind in [("nodes/coords",None,"<f8"),("faces/c0",None,"<i8"),("faces/c1",None,"<i8"),
                               ("faces/nodes","nnodes","<i8"),("faces/nodes","nodes","<i8")]:
            h.update((group+str(key)).encode())
            for part in sorted(m[group].values(),key=lambda g:bounds(g)[0]):
                arr=part[key] if key else part
                for j in range(0,len(arr),65536):h.update(np.asarray(arr[j:j+65536],dtype=kind).tobytes())
    return h.hexdigest()


def native_extrema(data):
    maxima=np.zeros(3)
    with h5py.File(data) as f:
        g=f["results/1/phase-1/cells"]
        vars=["SV_U","SV_V","SV_W","SV_P","SV_T"]
        blocks=[sorted(g[v].values(),key=lambda a:bounds(a)[0]) for v in vars]
        for ds in zip(*blocks,strict=True):
            if len({bounds(d) for d in ds})!=1:raise ValueError("Inconsistent zero-field native ID blocks")
            for i in range(0,len(ds[0]),65536):
                u,v,w,p,t=(d[i:i+65536].ravel() for d in ds)
                maxima=np.maximum(maxima,[np.sqrt(u*u+v*v+w*w).max(),abs(p).max(),abs(t-288.15).max()])
    if not np.isfinite(maxima).all():raise ValueError("Nonfinite zero-source native field")
    return dict(zip(TOL,map(float,maxima)))


def validate(baseline,folder,stem):
    case=folder/(stem+".cas.h5");data=folder/(stem+".dat.h5")
    if case_for_data(data)!=case:raise ValueError("Equilibrium CFF pairing failed")
    cfg=read_json(folder/"solver_config.json")
    if cfg["case_name"]!=ZERO or cfg["s"]!=0 or cfg["mode"]!="branch" or Path(cfg["input_file"])!=baseline:
        raise ValueError("Expected zero-source branch from the accepted nominal medium mesh")
    signed=read_json(folder/"static_equilibrium_native.json")
    if signed["accepted_stem"]!=stem:raise ValueError("Equilibrium reports belong to another endpoint")
    checks={}
    direct=native_extrema(data)
    for key,tol in TOL.items():
        checks[key]=bool(direct[key]<=tol and abs(signed[key])<=tol)
    mesh=mesh_signature(case);checks["matched_native_mesh"]=mesh==mesh_signature(baseline)
    disks=read_json(folder/"fluent_discrete_disk_integrals.json")
    checks["zero_actuator_fields"]=len(disks)==7 and len({d["name"] for d in disks})==7 and all(
        abs(d[k])<1.e-10 for d in disks for k in ("discrete_thrust_N","discrete_torque_Nm","thrust_target_N","torque_target_Nm"))
    end=read_json(folder/(stem+"_force_and_flux.json"))
    expected={"airframe","wing","nacelles","sponson","fuselage","empennage"}
    checks["reported_airframe_parts"]=set(end["half_model_force_N"])==expected and all(
        {"ForceX","ForceY","PressureForceX","PressureForceY","ViscousForceX","ViscousForceY"}<=set(load)
        for load in end["half_model_force_N"].values())
    checks["reported_open_boundaries"]=set(end["native_flux_reports"])=={"farfield_inlet","farfield_outlet","farfield_top","farfield_side"}
    checks["stationary_wall_forces"]=all(abs(float(value))<=1.e-4 for group in end["half_model_force_N"].values() for value in group.values())
    checks["zero_moment"]=abs(flux_value(end["half_model_pitch_moment_Nm"],"airframe-pitch-mz-half"))<=1.e-4
    checks["zero_surface_flux"]=all(abs(flux_value(v,"mass-"+k.replace("_","-")))<=1.e-5 for k,v in end["native_flux_reports"].items())
    checks["zero_source_reaction"]=all(abs(v)<1e-10 for v in end["half_model_actuator_reaction_N"].values())
    report=dict(accepted_stem=stem,accepted_data=data.name,passed=all(checks.values()),role=ROLE,baseline_case=str(baseline),
                auxiliary=True,count_in_18=False,included_in_nonzero_rpm_fit=False,checks=checks,thresholds=TOL,
                matched_mesh_sha256=mesh,native_cell_field_extrema=direct,native_report_extrema={k:signed[k] for k in TOL},
                half_wall_forces_N=end["half_model_force_N"],**direct)
    target=folder/"static_equilibrium_audit.json";tmp=target.with_suffix(".pending.json")
    tmp.write_text(json.dumps(report,allow_nan=False,indent=2),encoding="utf8");tmp.replace(target)
    if not report["passed"]:raise ValueError(f"Static-equilibrium physical checks failed: {checks}")
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group()
    m.add_argument("--prepare-only",action="store_true");m.add_argument("--verify-only",action="store_true")
    p.add_argument("--stage",default="P6");a=p.parse_args();gate()
    _,baseline,bd=accepted(BASE)
    from fluent_checkpoints import case_for_data
    if case_for_data(bd)!=baseline:raise ValueError("Invalid accepted baseline CFF")
    ready=WORK/"static_equilibrium_audit.json"
    if (ready.exists() and read_json(ready).get("passed")) or a.verify_only:
        stem=(read_json(WORK/"solver_config.json")["output_stem"])
        print(json.dumps(validate(baseline,WORK,stem),indent=2));gate();return
    WORK.mkdir(parents=True,exist_ok=True)
    index=1
    while any((WORK/f"equilibrium_{index:03d}{ext}").exists() for ext in (".cas.h5",".dat.h5","_iterations.trn")):index+=1
    stem=f"equilibrium_{index:03d}"
    checked_command([sys.executable,str(ROOT/"scripts/prepare_solver_case.py"),"--case",ZERO,"--branch",str(baseline),
                    "--branch-data",str(bd),"--iterations","2","--output-stem",stem],cwd=ROOT)
    gate()
    if a.prepare_only:
        print(WORK/"solve.jou");return
    checked_command([sys.executable,str(ROOT/"scripts/run_fluent_managed.py"),"--mode","solver","--dim","3ddp",
                    "--gui","--procs","4","--stage",a.stage,"--case",ZERO,"--workdir",str(WORK),"--journal",str(WORK/"solve.jou")],cwd=ROOT)
    gate();print(json.dumps(validate(baseline,WORK,stem),indent=2));gate()


if __name__=="__main__":main()
