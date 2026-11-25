"""Continue one CFD case through native restart blocks until its scientific checks pass."""
import argparse
import csv
import datetime as dt
from contextlib import contextmanager
import msvcrt
import math
import json
import subprocess
import sys
import time
from pathlib import Path

from assess_fluent_case import assess
from assess_section_case import assess as assess_section
from compare_x57_cases import CASES3, ROOT, accepted
from control_gate import atomic_write_json, atomic_write_text, checked_command
from run_fluent_managed import build_f_only_env as workspace_environment
from fluent_checkpoints import case_for_data
from cfd_case_identity import reference,canonical_mesh,digest,bind_pair
from prepare_airfoil_sections import CASES as SECTIONS

SCRIPTS=ROOT/"scripts"


def control():
    rc=subprocess.run([sys.executable,"-B",str(SCRIPTS/"control_gate.py"),"check"],stdout=subprocess.DEVNULL).returncode
    if rc:raise SystemExit(rc)


def managed_step(command,stdout=None):
    control()
    checked_command(command,cwd=ROOT,env=workspace_environment(),stdout=stdout)
    control()


def read(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def grid_for(level):
    return Path(reference(ROOT,level+"_rpm100",False)["mesh_path"])


@contextmanager
def case_lock(case):
    folder=ROOT/"logs"/"case_locks";folder.mkdir(parents=True,exist_ok=True)
    with (folder/(case+".lock")).open("a+b") as fp:
        if fp.tell()==0:fp.write(b"0");fp.flush()
        fp.seek(0)
        try:msvcrt.locking(fp.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:raise RuntimeError("Another managed convergence process owns "+case) from exc
        try:yield
        finally:fp.seek(0);msvcrt.locking(fp.fileno(),msvcrt.LK_UNLCK,1)


def activate(work,identity):
    current=work/"grid_binding.json"
    prior=read(current) if current.exists() else {}
    formal=(work/"iteration_qa.json").exists() or any(work.glob("*.dat.h5")) or (work/"force_history.out").exists()
    mismatch=prior.get("case_input_signature")!=identity["case_input_signature"]
    final=work/"iteration_qa.json"
    if not mismatch and final.exists():
        qa=read(final)
        if qa.get("passed"):
            try:
                case=work/(qa["accepted_stem"]+".cas.h5");data=work/(qa.get("accepted_data") or qa["accepted_stem"]+".dat.h5")
                mismatch=any(qa.get(k)!=v for k,v in bind_pair(qa,case,data,identity).items())
            except (OSError,KeyError,ValueError,TypeError,IndexError):
                mismatch=True
    if formal and mismatch:
        old=work.resolve();root=(ROOT/"03_cases").resolve()
        archive=(ROOT/"logs"/"superseded_case_states"/work.name/dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")).resolve()
        if old.parent!=root or not archive.is_relative_to((ROOT/"logs"/"superseded_case_states").resolve()):
            raise ValueError("Unexpected case archive location")
        archive.parent.mkdir(parents=True,exist_ok=True)
        old.rename(archive)
        work.mkdir()
        print("Prior numerical state preserved in",archive,flush=True)
    atomic_write_json(current,identity)


def matching_restart(work,grid_signature):
    for data in sorted(work.glob("*.dat.h5"),key=lambda p:p.stat().st_mtime_ns,reverse=True):
        try:
            cas=case_for_data(data,deep=True)
            if canonical_mesh(cas)==grid_signature:return cas,data
        except (OSError,KeyError,ValueError,IndexError,TypeError):
            continue
    return None,None


def native_command(work,case,stage,section):
    return [sys.executable,"-B",str(SCRIPTS/"run_fluent_managed.py"),"--mode","solver","--gui",
            "--dim","2ddp" if section else "3ddp","--procs","4","--workdir",str(work),"--journal",
            str(work/("section.jou" if section else "solve.jou")),"--stage",stage,"--case",case]


def interpolation_receipt(work, qa):
    stem=qa["accepted_stem"]
    path=work/(stem+".ip")
    if not path.is_file() or not path.stat().st_size:
        return None
    return dict(source_case=stem+".cas.h5",source_data=qa.get("accepted_data") or stem+".dat.h5",
                case_sha256=qa["case_sha256"],data_sha256=qa["data_sha256"],
                interpolation_file=path.name,interpolation_sha256=digest(path))


def interpolation_valid(work, qa):
    saved=work/(qa["accepted_stem"]+"_interpolation.json")
    actual=interpolation_receipt(work,qa)
    return actual is not None and saved.is_file() and read(saved)==actual


def recover_timing_row(work,qa,previous):
    """Complete a formerly interrupted sign-off using only that native block's saved measurements."""
    stem=qa["accepted_stem"]
    if previous and previous[-1]["stem"]==stem:
        row=previous[-1]
        if not (row["passed"] and row["case_sha256"]==qa["case_sha256"] and row["data_sha256"]==qa["data_sha256"]):
            raise ValueError("Accepted timing and checkpoint hashes disagree")
        return
    stamp_qa=read(work/(stem+"_qa.json"))
    if stamp_qa!=qa:
        raise ValueError("Cannot recover timing for a different accepted endpoint")
    controls=read(work/(stem+"_block_controls.json"))
    scale=controls.get("effective_time_scale_factor",controls.get("pseudo_time_scale"))
    row=block_timing(work,stem,qa,scale,scale,None)
    append_block(work,previous,row)


def block_timing(work,stem,qa,scale,next_scale,wall):
    with (work/(stem+"_residuals.csv")).open() as f:
        iterations=sorted({int(row["iter"]) for row in csv.DictReader(f)})
    if (not iterations or any(b!=a+1 for a,b in zip(iterations,iterations[1:]))
            or iterations[-1]!=qa["final_iteration"]):
        raise ValueError("Timing requires contiguous native iterations through the assessed endpoint")
    timing=read(work/(stem+"_iteration_timing.json"))
    seconds=timing["solver_wall_seconds"]
    if not math.isfinite(seconds) or seconds<=0:
        raise ValueError("Missing or invalid measured Fluent iteration time")
    return dict(stem=stem,actual_iteration_samples=len(iterations),final_iteration=qa["final_iteration"],
                time_scale=scale,next_time_scale=next_scale,solver_wall_seconds=seconds,
                seconds_per_iteration=seconds/len(iterations),launch_through_save_seconds=wall,
                passed=qa["passed"],checks=qa["checks"],volume_mesh_sha256=qa["volume_mesh_sha256"],
                case_input_signature=qa["case_input_signature"],case_sha256=qa["case_sha256"],
                data_sha256=qa["data_sha256"],data_file=qa["data_file"])


def append_block(work,previous,row):
    atomic_write_text(work/"convergence_blocks.jsonl",
                      "".join(json.dumps(item,allow_nan=False)+"\n" for item in [*previous,row]))


def _quarantine(work,since_ns,stamp):
    """Hide native files written by a failed/diverged block so restarts use the last good pair."""
    moved=[]
    candidates=list(work.glob("*.dat.h5"))+list(work.glob("*.cas.h5"))+[work/(stamp+"_residuals.csv"),work/(stamp+"_qa.json")]
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_mtime_ns>=since_ns:
                target=path.with_name(path.name+".diverged")
                target.unlink(missing_ok=True)
                path.replace(target)
                moved.append(target.name)
        except OSError:
            continue
    return moved


def _oscillating(qa,limit):
    forces=qa.get("forces_full_aircraft") or qa.get("forces_per_span") or {}
    return any((st.get("relative_std") or 0.)>limit for st in forces.values())


def _log_event(work,payload):
    with (work/"fasttrack_events.jsonl").open("a",encoding="utf-8") as fp:
        fp.write(json.dumps({"at":dt.datetime.now().astimezone().isoformat(timespec="seconds"),**payload},default=str)+"\n")


def _residual_samples(work,stamp):
    with (work/(stamp+"_residuals.csv")).open() as f:
        return len({int(row["iter"]) for row in csv.DictReader(f)})


def solve(case,stage,block_size=None,initial_scale=None):
    """Bounded native continuation: iteration cap, per-case deadline, divergence recovery, tiered acceptance."""
    import os
    from fasttrack_profile import (case_plan,env_deadline,MAX_DIVERGENCE_RECOVERIES,FORCE_TIERS,
                                   INTERPOLATION_EXPORT_CASES)
    plan=case_plan(case)
    block_size=int(block_size or plan["block"])
    if block_size<50:raise ValueError("Residual acceptance uses the last 50 native iterations of the block")
    control()
    # Fast-track: the informational deep resume-scan re-read every case's HDF5 pair on each call
    # (GBs late in the run); restarts are resolved per case by matching_restart() below.
    work=ROOT/"03_cases"/case
    work.mkdir(parents=True,exist_ok=True)
    section=case in SECTIONS
    ident=reference(ROOT,case,section);activate(work,ident)
    grid=Path(ident["mesh_path"]);native_grid=canonical_mesh(grid)
    ident["canonical_native_mesh_sha256"]=native_grid
    atomic_write_json(work/"grid_binding.json",ident)
    final=work/"iteration_qa.json"
    record=work/"convergence_blocks.jsonl"
    previous=[json.loads(line) for line in record.read_text().splitlines() if line] if record.exists() else []
    if previous and previous[-1]["passed"]:
        # A pause between committing the timing and the summary leaves a complete native block.
        last=previous[-1]
        candidate=read(work/(last["stem"]+"_qa.json"))
        if (candidate["passed"] and candidate["final_iteration"]==last["final_iteration"]
                and candidate["case_sha256"]==last["case_sha256"] and candidate["data_sha256"]==last["data_sha256"]
                and candidate["case_input_signature"]==ident["case_input_signature"]):
            if not final.is_file() or read(final)!=candidate:
                c=work/(last["stem"]+".cas.h5");d=work/last["data_file"]
                if all(candidate.get(k)==v for k,v in bind_pair(candidate,c,d,ident).items()):
                    atomic_write_json(final,candidate)
    if final.is_file() and read(final).get("passed"):
        qa,_,_=accepted(case)
        recover_timing_row(work,qa,previous)
        print("Already accepted",case,qa["final_iteration"],qa.get("acceptance_tier"),flush=True)
        if not section:
            export_accepted(work,case,stage,qa)
        control()
        return
    deadline=env_deadline("X57_CASE_DEADLINE_EPOCH")
    allow_flagged=os.environ.get("X57_ALLOW_FLAGGED","1")!="0"
    scale=float(previous[-1]["next_time_scale"]) if previous else float(initial_scale or plan["initial_scale"])
    done_iters=sum(int(r.get("actual_iteration_samples",0)) for r in previous)
    warm_next=0 if previous or section else int(plan.get("warmup",0))
    recoveries=0
    try:  # grace blocks already spent survive a kill/resume, so the cap stays global
        grace_used=int((read(final).get("fasttrack") or {}).get("grace_blocks_used",0)) if final.is_file() else 0
    except (OSError,ValueError,TypeError):
        grace_used=0
    grace_cap=int(plan.get("grace_blocks",1))
    _log_event(work,dict(event="solve_start",case=case,plan=plan,deadline_epoch=deadline,done_iterations=done_iters,scale=scale))
    while True:
        control()
        stamp=dt.datetime.now().strftime("block_%Y%m%d_%H%M%S_%f")
        restart,data=matching_restart(work,native_grid)
        # A paused initial block can leave a header or only a few force samples.
        # Only a previously assessed endpoint certifies its 200-sample history.
        assessed_restart = (previous and restart and data and (work/"force_history.out").is_file()
                            and restart.name == previous[-1]["stem"]+".cas.h5"
                            and data.name == previous[-1].get("data_file",previous[-1]["stem"]+".dat.h5")
                            and previous[-1].get("case_input_signature")==ident["case_input_signature"])
        iterations=block_size if assessed_restart else max(200,block_size)
        warm=0 if section else max(0,min(int(warm_next),iterations-50))
        interp_used=None
        if section:
            prep=[sys.executable,"-B",str(SCRIPTS/"prepare_section_solver.py"),case,"--stem",stamp,
                  "--iterations",str(iterations),"--time-scale",str(min(1.,scale))]
            if restart:prep+=["--resume","--resume-case",str(restart),"--resume-data",str(data)]
        else:
            prep=[sys.executable,"-B",str(SCRIPTS/"prepare_solver_case.py"),"--case",case,
                  "--output-stem",stamp,"--iterations",str(iterations),"--pseudo-time-scale",str(scale),
                  "--first-order-iterations",str(warm)]
            if restart:
                prep+=["--resume",str(restart),"--resume-data",str(data)]
            elif case in ("coarse_rpm100","medium_rpm100","fine_rpm100"):
                prep+=["--mesh",str(grid)]
                if case=="fine_rpm100":
                    q,c,_=accepted("medium_rpm100")
                    if not interpolation_valid(c.parent,q):
                        export_accepted(c.parent,"medium_rpm100",stage,q)
                    if not interpolation_valid(c.parent,q):
                        raise ValueError("Medium interpolation fields are unbound to the accepted solution")
                    ip=c.parent/(q["accepted_stem"]+".ip")
                    prep+=["--interpolate",str(ip.resolve(strict=True))]
                    interp_used=(c,q)
                elif case=="medium_rpm100" and "coarse_rpm100" in INTERPOLATION_EXPORT_CASES:
                    # Optional coarse-grid initial field: shortens the medium transient only.
                    try:
                        q,c,_=accepted("coarse_rpm100")
                        if interpolation_valid(c.parent,q):
                            ip=c.parent/(q["accepted_stem"]+".ip")
                            prep+=["--interpolate",str(ip.resolve(strict=True))]
                            interp_used=(c,q)
                    except (OSError,ValueError,KeyError) as exc:
                        print("Coarse interpolation unavailable; hybrid initialization:",exc,flush=True)
            else:
                base,c,d=accepted("medium_rpm100")
                if base.get("volume_mesh_sha256")!=ident["volume_mesh_sha256"] or canonical_mesh(c)!=native_grid:
                    raise ValueError("Warm branch and destination have different physical medium grids")
                prep+=["--branch",str(c),"--branch-data",str(d)]
        managed_step(prep)
        journal=work/("section.jou" if section else "solve.jou")
        record_input={"block":stamp,**ident,"journal_sha256":digest(journal),
                      "restart_native_case":str(restart) if restart else None,"restart_native_data":str(data) if data else None,
                      "fasttrack":dict(iterations=iterations,first_order_iterations=warm,pseudo_time_scale=scale,
                                       total_iterations_before=done_iters,recoveries=recoveries)}
        if "--branch" in prep:
            record_input.update(branch_case=str(c),branch_data=str(d),branch_case_sha256=digest(c),branch_data_sha256=digest(d))
        if interp_used:
            ic,iq=interp_used
            record_input["interpolation"]=interpolation_receipt(ic.parent,iq)
            record_input["interpolation_sha256"]=record_input["interpolation"]["interpolation_sha256"]
        if restart:record_input.update(restart_case_sha256=digest(restart),restart_data_sha256=digest(data))
        atomic_write_json(work/(stamp+"_grid_input.json"),record_input)
        block_start=time.time_ns()
        t=time.perf_counter()
        try:
            managed_step(native_command(work,case,stage,section))
            wall=time.perf_counter()-t
            control()
            qa=assess_section(work,stamp) if section else assess(work,stamp)
            if qa.get("diverged"):
                raise RuntimeError("Non-finite or exploding scaled residuals in the block (divergence)")
            samples=_residual_samples(work,stamp)
        except SystemExit:
            raise
        except Exception as exc:
            # Divergence, NaN residuals, a guard-terminated session or an incomplete block.
            recoveries+=1
            moved=_quarantine(work,block_start,stamp)
            _log_event(work,dict(event="block_failed",stamp=stamp,error=f"{exc.__class__.__name__}: {exc}"[:3000],
                                 quarantined=moved,scale=scale,recovery=recoveries))
            print(f"[FastTrack] {case} block {stamp} failed ({exc.__class__.__name__}); recovery {recoveries}/{MAX_DIVERGENCE_RECOVERIES}",flush=True)
            if recoveries>MAX_DIVERGENCE_RECOVERIES:
                raise RuntimeError(f"{case}: {recoveries} consecutive failed native blocks; last error: {exc}") from exc
            scale=max(.1,scale*.5);warm_next=0 if section else 100
            continue
        recoveries=0
        out_case=work/(stamp+".cas.h5");out_data=work/(qa.get("accepted_data") or stamp+".dat.h5")
        current=reference(ROOT,case,section)
        if current["case_input_signature"]!=ident["case_input_signature"] or canonical_mesh(out_case)!=native_grid:
            raise ValueError("Published grid/inlet or native checkpoint geometry changed during "+stamp)
        qa.update(bind_pair(qa,out_case,out_data,ident))
        qa["canonical_native_mesh_sha256"]=native_grid
        qa["data_file"]=out_data.name
        checks=qa["checks"]
        invariant=[k for k in ("disk_integrals","force_consistency","mesh_budget") if k in checks and not checks[k]]
        if invariant:
            qa["passed"]=False
            atomic_write_json(work/(stamp+"_qa.json"),qa)
            raise RuntimeError(f"Case {case} needs corrective work (deterministic invariant failed): {invariant}")
        total=done_iters+samples
        window_ok=section or (iterations-warm)>=200
        # Required (coursework-brief) cases are never cut short by a stage deadline and never accept
        # the 'budget' tier; extension cases absorb time compression (fasttrack_profile.CASE_PLAN).
        deadline_hit=(deadline is not None and plan.get("deadline_binding",True) and time.time()+wall>deadline)
        exhausted=total>=plan["max_iter"] or deadline_hit
        acceptable=("strict","engineering","budget") if plan.get("allow_budget",True) else ("strict","engineering")
        tier=None
        if qa["passed"] and window_ok and total>=plan["min_iter"]:
            tier=qa["acceptance_tier"]
        elif exhausted and window_ok and qa.get("best_available_tier") in acceptable:
            tier=qa["best_available_tier"]
        elif exhausted and grace_used<grace_cap:
            grace_used+=1
            _log_event(work,dict(event="grace_block",stamp=stamp,grace=f"{grace_used}/{grace_cap}",
                                 total_iterations=total,best=qa.get("best_available_tier")))
        elif exhausted:
            if not allow_flagged:
                raise RuntimeError(f"{case}: budget exhausted without a plateau and X57_ALLOW_FLAGGED=0")
            tier="flagged"
        if tier:
            qa["passed"]=True
            qa["acceptance_tier"]=tier
            if tier=="flagged":
                qa["checks"]={k:bool(v) for k,v in checks.items() if k in ("disk_integrals","force_consistency","mesh_budget")}
                qa["checks"]["finite_native_endpoint"]=True
            else:
                qa["checks"]=dict(qa["tier_checks"][tier])
            if section:qa["accepted_stem"]=stamp
        else:
            qa["passed"]=False
            qa["acceptance_tier"]=None
            qa["deferred_reason"]=("minimum iterations" if total<plan["min_iter"] else
                                   "first-order warm-up inside the force window" if not window_ok else "criteria not met")
        qa["fasttrack"]=dict(plan=plan,total_iterations=total,block_iterations=iterations,first_order_iterations=warm,
                             budget_exhausted=bool(exhausted),grace_blocks_used=grace_used,grace_blocks_cap=grace_cap,
                             deadline_epoch=deadline,pseudo_time_scale=scale)
        atomic_write_json(work/(stamp+"_qa.json"),qa)
        oscillating=not qa.get("tier_checks",{}).get("engineering",{}).get("force_platform",True) and _oscillating(qa,FORCE_TIERS["engineering"][0])
        # Grace blocks always damp the pseudo-time step a little to help a slow plateau settle.
        next_scale=max(.2,scale*.7) if (oscillating or (exhausted and not qa["passed"])) else scale
        row=block_timing(work,stamp,qa,scale,next_scale,wall)
        append_block(work,previous,row)
        atomic_write_json(final,qa)
        print(json.dumps(row),flush=True)
        _log_event(work,dict(event="block_assessed",stamp=stamp,total_iterations=total,tier=qa.get("acceptance_tier"),
                             best=qa.get("best_available_tier"),passed=qa["passed"],wall_s=wall))
        control()
        if qa["passed"]:break
        previous.append(row);scale=next_scale;done_iters=total;warm_next=0
    if not section:
        export_accepted(work,case,stage,qa)
    control()


def export_accepted(work,case,stage,qa):
    """Native exports only for cases that downstream figures/initialisations actually read."""
    from fasttrack_profile import FIELD_EXPORT_CASES,INTERPOLATION_EXPORT_CASES
    stamp=qa["accepted_stem"]
    endpoint=work/(stamp+".cas.h5")
    data=work/(qa.get("accepted_data") or stamp+".dat.h5")
    wants_fields=case in FIELD_EXPORT_CASES
    wants_ip=case in INTERPOLATION_EXPORT_CASES
    if not wants_fields and not wants_ip:
        return
    manifest=work/(stamp+"_native_field_manifest.json")
    field_qa=work/(stamp+"_native_field_qa.json")
    fields_ok=True
    if wants_fields:
        fields_ok=False
        if manifest.is_file() and field_qa.is_file() and read(field_qa).get("passed"):
            meta=read(manifest)
            fields_ok=(meta["case"]==endpoint.name and meta["data"]==data.name and (work/meta["file"]).is_file())
    ip_ok=(not wants_ip) or interpolation_valid(work,qa)
    if fields_ok and ip_ok:
        return
    args=[sys.executable,"-B",str(SCRIPTS/"prepare_solver_case.py"),"--case",case,"--resume",str(endpoint),
          "--resume-data",str(data),"--extract-only","--output-stem",stamp]
    if wants_fields:args.append("--export-full-fields")
    if wants_ip:args.append("--export-interpolation")
    managed_step(args)
    managed_step(native_command(work,case,stage,False))
    if wants_fields:
        managed_step([sys.executable,"-B",str(SCRIPTS/"verify_native_cell_export.py"),str(manifest)])
    if wants_ip and not interpolation_valid(work,qa):
        raise ValueError(f"Native {case} interpolation export is not bound to the accepted case and data")



if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("case",choices=CASES3+list(SECTIONS))
    p.add_argument("--stage",required=True)
    p.add_argument("--block",type=int,default=None,help="Iterations per native launch (default: fasttrack_profile.CASE_PLAN)")
    p.add_argument("--initial-scale",type=float,default=None)
    a=p.parse_args()
    with case_lock(a.case):solve(a.case,a.stage,a.block,a.initial_scale)
