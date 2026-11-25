"""Exercise native v252 iteration/checkpoint/reload on a retained 12-cell CFF inside F."""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import h5py
import numpy as np
from control_gate import ControlGate, atomic_write_json
from fluent_checkpoints import case_for_data
from verify_mesh_level import digest

ROOT=Path(__file__).resolve().parents[1]
AUDIT=ROOT/"00_env_audit"/"native_pause_probe"
FIXTURE=ROOT/"00_env_audit/solver_discovery"/"synthetic_postproc_fixture.cas.h5"
FIELD_NAMES=("SV_P","SV_U","SV_V","SV_W","SV_DENSITY","SV_T","SV_K","SV_O","SV_MU_T")
WORKER="""import os,sys
from pathlib import Path
p=Path.cwd()
sys.path.insert(0,str(Path(os.environ['FLUENT_PROD_DIR'])/'cortex/pylib'))
import flsetup
flsetup.insert_pyfluent_module_path()
from flapi.flproxy import Proxy
from flapi.generated.solver.settings_252 import root
s=root()
s.set_flproxy(Proxy)
for key in s.solution.monitor.report_files.get_object_names():
    obj=s.solution.monitor.report_files[key]
    obj.file_name=str(p/(key+'.out'))
for key in s.solution.monitor.report_plots.get_object_names():
    s.solution.monitor.report_plots[key].active=False
for key in s.solution.monitor.residual.equations.get_object_names():
    s.solution.monitor.residual.equations[key].check_convergence=False
a=s.file.auto_save
a.root_name=str(p/'autosave')
a.data_frequency=50
a.case_frequency='each-time'
a.retain_most_recent_files=True
a.max_files=2
"""
STOP=WORKER+"""s.solution.run_calculation.iterate(iter_count=2)
s.file.write_case_data(file_name=str(p/'before_pause.cas.h5'))
s.file.start_transcript(file_name=str(p/'native_pause_iterations.trn'))
# Only this session's isolated test control directory is modified.
(p/'CONTROL'/'STATE.txt').write_text('PAUSE',encoding='ascii')
s.solution.run_calculation.iterate(iter_count=400)
(p/'unexpected_iteration_return').touch()
s.file.stop_transcript()
"""
RELOAD=WORKER+"""s.file.write_case_data(file_name=str(p/'reread.cas.h5'))
s.file.start_transcript(file_name=str(p/'one_more_iteration.trn'))
s.solution.run_calculation.iterate(iter_count=1)
s.file.stop_transcript()
s.file.write_case_data(file_name=str(p/'continued.cas.h5'))
"""

def gate():
    state=ControlGate().check()
    if state["exit_code"]:
        raise SystemExit(state["exit_code"])

def journal(work,case,data,code):
    work.mkdir(parents=True,exist_ok=False)
    local=work/"CONTROL"
    local.mkdir()
    (local/"STATE.txt").write_text("RUN",encoding="ascii")
    worker=work/"native_worker.py"
    worker.write_text(code,encoding="utf-8")
    p=work/"native.jou"
    p.write_text('/file/confirm-overwrite no\n'
        +f'/file/read-case "{case.as_posix()}"\n/file/read-data "{data.as_posix()}"\n'
        +'(set! checkpoint/exit-filename "exit-fluent.txt")\n(set! checkpoint/check-filename "check-fluent.txt")\n'
        +f'(%py-exec "exec(open(\'{worker.as_posix()}\', encoding=\'utf-8\').read())")\n/exit ok\n')
    return p

def managed(work):
    gate()
    return subprocess.run([sys.executable,"-B",str(ROOT/"scripts/run_fluent_managed.py"),"--mode","solver","--gui",
        "--dim","3ddp","--procs","1","--stage","P2_CONTROL_CHECK","--case","s0_native_pause_"+work.name,"--workdir",str(work),
        "--journal",str(work/"native.jou"),"--audit-local-pause","--poll-seconds",".10","--grace-seconds","50"]).returncode

def fields(data):
    values={}
    with h5py.File(data) as file:
        for name in FIELD_NAMES:
            group=file["results/1/phase-1/cells/"+name]
            blocks=sorted(group.values(),key=lambda v:int(v.attrs["minId"].item()))
            ids=np.concatenate([np.arange(int(v.attrs["minId"].item()),int(v.attrs["maxId"].item())+1) for v in blocks])
            if not np.array_equal(ids,np.arange(1,13)):raise ValueError(f"{name} cell IDs: {ids}")
            values[name]=np.concatenate([v[:] for v in blocks])
            if not np.isfinite(values[name]).all():raise ValueError(name)
    return values

def native_iterations(path):
    text=path.read_text(encoding="utf-8",errors="replace")
    return [int(k) for k in re.findall(r"(?m)^\s*(\d+)\s+[0-9.eE+-]+\s+[0-9.eE+-]+",text)]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run",action="store_true",help="Use the managed Student seat for a short visible native test.")
    args=parser.parse_args()
    gate()
    case=FIXTURE
    data=case.with_name(case.name[:-7]+".dat.h5")
    if case_for_data(data,True)!=case:raise ValueError("Fixture pair mismatch")
    start={str(p):digest(p) for p in [case,data]}
    if not args.run:
        fields(data)
        compile(STOP,"native_stop","exec")
        compile(RELOAD,"native_reload","exec")
        print("READY: verified 12-cell fixture, nine native cell arrays, journal workers; seat not opened.")
        return
    root=AUDIT/datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    try:
        exercise(root,case,data,start)
    except Exception as exc:
        if root.is_dir():
            atomic_write_json(root/"native_pause_qa.json",dict(passed=False,production_case=False,
                              error_type=type(exc).__name__,reason=str(exc),fixture_sha256=start))
        raise


def exercise(root,case,data,start):
    work=root/"stop"
    journal(work,case,data,STOP)
    rc=managed(work)
    gate()
    if rc!=10:raise RuntimeError(f"Expected local PAUSE=10, got {rc}. See {work}")
    result=json.loads((work/"managed_stop.json").read_text())
    if result["forced"] or result["provenance"]!="written_during_launch" or result["checkpoint"].get("kind")!="case_data":
        raise RuntimeError(result)
    if (work/"unexpected_iteration_return").exists() or (work/"exit-fluent.txt").exists():
        raise RuntimeError("Fluent did not consume the trigger and exit inside its native iteration loop")
    paused=Path(result["checkpoint"]["path"])
    if paused.name=="before_pause.dat.h5":raise RuntimeError("No new iteration checkpoint was saved")
    saved_case=case_for_data(paused,True)
    read_work=root/"readback"
    journal(read_work,saved_case,paused,RELOAD)
    rc=managed(read_work)
    gate()
    if rc:raise RuntimeError(f"Native restart/reload failed: {rc}, {read_work}")
    reread=read_work/"reread.dat.h5"
    onward=read_work/"continued.dat.h5"
    for x in (reread,onward):case_for_data(x,True)
    before,after=fields(paused),fields(reread)
    errors={k:float(np.max(np.abs(before[k]-after[k]))) for k in before}
    if not all(np.array_equal(before[k], after[k]) for k in before):
        raise ValueError(f"Changed primary native fields after reread: {errors}")
    resumed_iters=native_iterations(read_work/"one_more_iteration.trn")
    saved_iters=native_iterations(work/"native_pause_iterations.trn")
    if not saved_iters or not resumed_iters or resumed_iters[-1]!=saved_iters[-1]+1:
        raise ValueError(f"Iteration continuity: pause={saved_iters[-4:]}, reload={resumed_iters[-4:]}")
    if any(digest(Path(k))!=v for k,v in start.items()):raise ValueError("Original fixture changed")
    report=dict(passed=True,production_case=False,fixture_sha256=start,control_outcome=result,
        pause_iteration=saved_iters[-1],continued_iteration=resumed_iters[-1],force_terminated=result["forced"],
        paused_case_sha256=digest(saved_case),paused_data_sha256=digest(paused),native_cell_ids=12,
        max_abs_field_differences_after_reload=errors,continued_data_sha256=digest(onward))
    atomic_write_json(root/"native_pause_qa.json",report)
    print(root/"native_pause_qa.json")
    gate()

if __name__=="__main__":main()
