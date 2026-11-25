"""Run one accepted one-way FSI case in its isolated MAPDL batch directory."""
import argparse,json,subprocess,sys,time
from pathlib import Path
from control_gate import ControlGate,append_history
from run_fluent_managed import build_f_only_env,attach_kill_on_close_job,close_job_handle
from map_cfd_shell_loads import produce
from mapdl_static_results import write,check
from prepare_mapdl_shell import OUT
from mapdl_shell_fields import source_hash
from fsi_provenance import verify_transfer,commit,accepted_model,accepted_result,hashes

EXE=Path(r'D:\Ansys\ANSYS Inc\ANSYS Student\v252\ansys\bin\winx64\MAPDL.exe')
def gatecheck(gate):
    rc=int(gate.check()['exit_code'])
    if rc:raise SystemExit(rc)
def run(level,source):
    gate=ControlGate();gatecheck(gate)
    case=source.resolve().parent.name
    if (OUT/(level+'_struct__'+case)/'native_result_provenance.json').is_file():
        try:
            report,native=accepted_result(level,case)
            print('Verified existing MAPDL result',case,level,native['load_signature'],flush=True)
            return
        except (KeyError,FileNotFoundError,ValueError):
            pass
    work=produce(level,source);gatecheck(gate)
    write(level,work);gatecheck(gate)
    case=source.resolve().parent.name;transfer=verify_transfer(level,case)
    token=transfer['load_identity']['load_signature']
    model_file=(OUT/'models'/level/'model.inp').resolve()
    if source_hash(work/'model.inp')!=accepted_model(level)['model_files_sha256'][str(model_file)]:
        raise ValueError('MAPDL model input differs from the signed structural mesh')

    # Use a fresh actual MAPDL job name so old result files cannot pass the checks.
    job='x57fsi'+str(time.time_ns())[-11:]
    cmd=[str(EXE),'-b','-smp','-np','2','-dir',str(work),'-j',job,'-i',str(work/'solve.inp'),'-o',str(work/(job+'.out'))]
    started=time.time_ns()
    proc=subprocess.Popen(cmd,cwd=work,env=build_f_only_env())
    handle=attach_kill_on_close_job(proc)
    interrupted=0;grace=None
    gate.register_pid(proc.pid,'mapdl_structural',str(work),work.name)
    import os as _os
    limit_s=60.*float(_os.environ.get('X57_MAPDL_MAX_WALL_MIN','40'));t_start=time.monotonic()
    timed_out=False
    try:
        while proc.poll() is None:
            if time.monotonic()-t_start>limit_s and not timed_out:
                # Fast-track guard: a linear SHELL181 static solve takes minutes; never wait forever.
                timed_out=True
                subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,check=False)
            code=int(gate.check()['exit_code'])
            if code and not interrupted:
                interrupted=code;grace=time.monotonic()
                (work/(job+'.abt')).write_text('nonlinear\n',encoding='ascii')
            if interrupted and (interrupted==30 or time.monotonic()-grace>45):
                subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,check=False)
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:continue
    finally:
        close_job_handle(handle);gate.unregister_pid(proc.pid)
    if interrupted:
        state={'control_exit_code':interrupted,'case':str(source),'mesh_level':level,'state':'paused',
               'restart':'model.inp + mapped_loads.inp + solve.inp; the interrupted static step is rerun from saved input.',
               'job':job}
        (work/'mapdl_checkpoint.json').write_text(json.dumps(state,indent=2))
        append_history('MAPDL_CONTROL_EXIT',json.dumps(state))
        raise SystemExit(interrupted)
    gatecheck(gate)
    if timed_out:
        raise RuntimeError(f'MAPDL exceeded the fast-track wall limit ({limit_s/60:.0f} min): {job}.out')
    log=(work/(job+'.out')).read_text(errors='replace')
    exports=[work/n for n in ('node_displacement.csv','element_stress.csv','element_top_principal_local.csv','element_bot_principal_local.csv','support_reactions.csv',job+'.rst')]
    if proc.returncode or 'X57_MAPDL_EXPORT_COMPLETE' not in log or '*** ERROR ***' in log or any(not p.exists() or p.stat().st_mtime_ns<started for p in exports):
        raise RuntimeError('MAPDL failed or output was incomplete: '+job+'.out')
    current=verify_transfer(level,case)
    if current['load_identity']['load_signature']!=token:
        raise ValueError('Accepted CFD or structural state changed while MAPDL was running')
    report=check(level,work);gatecheck(gate)
    model=OUT/'models'/level
    sources=[work/(job+'.rst'),work/(job+'.out'),work/'solve.inp',work/'model.inp',
             work/'load_transfer.json',work/'shell_fields.npz',work/'mapped_loads.inp',
             work/'nodal_loads.npy',work/'component_stress_metrics.json',work/'structural_metrics.json',model/'shell_mesh.npz',model/'model.json']
    provenance={'solver':'Mechanical APDL 2025 R2 SHELL181','job':job,'grid':level,
                'case':case,'geometry_signature':current['load_identity']['geometry_signature'],
                'model_signature':current['load_identity']['model_signature'],'load_signature':token,
                'sha256':{str(p.resolve()):source_hash(p) for p in sources}}
    provenance['structural_solver_and_export_sha256']=hashes([Path(__file__).with_name(n) for n in ['mapdl_static_results.py','mapdl_shell_fields.py','run_mapdl_structural.py']])
    manifest=work/'native_result_provenance.json'
    commit(manifest,provenance)
    print(json.dumps(report,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('level',choices=['coarse','medium','fine'])
    p.add_argument('accepted_cfd_case',type=Path);args=p.parse_args();run(args.level,args.accepted_cfd_case)
