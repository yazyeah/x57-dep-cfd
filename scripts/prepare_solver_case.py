"""Prepare a managed solver journal for a mesh, matching-grid branch, or checkpoint."""
import argparse,json,math,os
from fluent_checkpoints import case_for_data
from pathlib import Path

ROOT=Path(os.environ['X57_WORKSPACE']).resolve()
MATRIX={'coarse_rpm100':(1,True),'medium_rpm100':(1,True),'fine_rpm100':(1,True),
        'medium_rpm100_hlp_only':(1,True),'medium_rpm100_wt_only':(1,True),
        'medium_rpm100_alt_swirl':(1,True),'medium_rpm100_takeoff_v10':(1,True),
        'medium_rpm100_oge':(1,True),'medium_rpm100_rke':(1,True),
        'medium_opt_hlp_vector10':(1,True),'medium_rpm000':(0,False),'medium_rpm050':(.5,True),'medium_rpm075':(.75,True),'medium_rpm100_noswirl':(1,False)}
p=argparse.ArgumentParser()
p.add_argument('--case',choices=list(MATRIX)+['synthetic_solver'],required=True)
g=p.add_mutually_exclusive_group(required=True)
g.add_argument('--mesh',type=Path)
g.add_argument('--branch',type=Path,help='Converged medium_rpm100 case with adjacent data file')
g.add_argument('--resume',type=Path,help='Checkpoint case with adjacent data file')
p.add_argument('--branch-data',type=Path,help='Explicit native data file paired with --branch')
p.add_argument('--resume-data',type=Path,help='Use the explicitly paired native autosave data file with --resume')
p.add_argument('--pseudo-time-scale',type=float,help='Positive multiplier on Fluent automatic global pseudo-time step; omission retains current setting')
p.add_argument('--export-full-fields',action='store_true',help='Export native cell-center velocity gradients and flow fields from the endpoint')
p.add_argument('--interpolate',type=Path,help='Medium-grid Fluent interpolation file for fine-grid initialization')
p.add_argument('--export-interpolation',action='store_true',help='Write a mesh-independent restart field file')
p.add_argument('--extract-only',action='store_true',help='Read a matching same-directory checkpoint, refresh endpoint reports and export publication fields without advancing iterations or rewriting the checkpoint')
p.add_argument('--iterations',type=int,default=500)
p.add_argument('--first-order-iterations',type=int,default=0,help='Fast-track first-order warm-up span at the start of this block (0 = none)')
p.add_argument('--output-stem',required=True)
a=p.parse_args()
source=(a.mesh or a.branch or a.resume).resolve(strict=True)
if not source.is_relative_to(ROOT) or a.iterations<1 or Path(a.output_stem).name!=a.output_stem:
    p.error('Invalid input, iteration count or output stem')
if a.branch_data and not a.branch:
    p.error('--branch-data requires --branch')
if a.resume_data and not a.resume:
    p.error('--resume-data requires --resume')
if a.pseudo_time_scale is not None and (not math.isfinite(a.pseudo_time_scale) or a.pseudo_time_scale<=0 or a.extract_only):
    p.error('--pseudo-time-scale requires a positive finite multiplier on an iteration block')
fixture=a.case=='synthetic_solver'
work=ROOT/('00_env_audit/solver_discovery' if fixture else '03_cases/'+a.case)
work.mkdir(parents=True,exist_ok=True)
if a.extract_only and (a.resume is None or source!=work/(a.output_stem+'.cas.h5')):
    p.error('--extract-only requires --resume of the same case directory and output stem')
for suffix in [] if a.extract_only else ['.cas.h5','.dat.h5']:
    if (work/(a.output_stem+suffix)).exists():
        p.error('Output already exists; use a distinct --output-stem')
mode='mesh' if a.mesh else ('branch' if a.branch else 'resume')
input_data=None
if mode!='mesh':
    if not source.name.endswith('.cas.h5'):
        p.error('Expected native .cas.h5 input')
    input_data=(a.resume_data or a.branch_data or source.with_name(source.name[:-7]+'.dat.h5')).resolve(strict=True)
    if input_data.parent!=source.parent or not input_data.name.endswith('.dat.h5'):
        p.error('Expected adjacent native .dat.h5 input')
    try:
        matched=case_for_data(input_data)
    except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
        p.error(f'Invalid native checkpoint {input_data.name}: {exc}')
    if matched.resolve()!=source:
        p.error(f'{input_data.name} references {matched.name}, not {source.name}')
    if not fixture and mode=='branch' and (source.parent!=ROOT/'03_cases/medium_rpm100' or not a.case.startswith('medium_')):
        p.error('RPM/swirl branches use the converged matched-medium source case')
    if mode=='resume' and source.parent!=work:
        p.error('Resume requires the case directory being continued')
ip=a.interpolate.resolve(strict=True) if a.interpolate else None
if ip and (not ip.is_relative_to(ROOT) or mode!='mesh'):
    p.error('Interpolation must be applied to an initial mesh solve')
if a.case=='fine_rpm100' and mode=='mesh' and (not ip or ip.parent!=ROOT/'03_cases/medium_rpm100'):
    p.error('The fine mesh requires --interpolate from the converged medium grid')
if a.case=='fine_rpm100' and mode=='mesh':
    from compare_x57_cases import accepted
    from run_x57_converged import interpolation_valid
    medium_qa,medium_case,_=accepted('medium_rpm100')
    if ip!=medium_case.with_suffix('').with_suffix('.ip') or not interpolation_valid(medium_case.parent,medium_qa):
        p.error('Fine initialization requires the native interpolation export of the accepted Medium endpoint')
if not fixture and a.case.startswith('medium_') and a.case!='medium_rpm100' and mode=='mesh':
    p.error('The matched sweep requires --branch from the converged medium baseline')
s,swirl=MATRIX.get(a.case,(1,True))
cfg=dict(case_name=a.case,s=s,swirl=swirl,mode=mode,output_stem=a.output_stem,iterations=a.iterations,input_file=str(source),input_data=str(input_data) if input_data else None,pseudo_time_scale=a.pseudo_time_scale,export_full_fields=a.export_full_fields,interpolation=str(ip) if ip else None,export_interpolation=a.export_interpolation,extract_only=a.extract_only,
         first_order_iterations=0 if a.extract_only else max(0,min(a.first_order_iterations,a.iterations-50)))
(work/'solver_config.json').write_text(json.dumps(cfg,indent=2),encoding='utf-8')
read_cmd=f'/file/read-case "{source.as_posix()}"'
if input_data:
    read_cmd+=f'\n/file/read-data "{input_data.as_posix()}"'
worker=(ROOT/'scripts/fluent_solver_worker.py').as_posix()
journal=f'''/file/confirm-overwrite no
{read_cmd}
(set! checkpoint/exit-filename "exit-fluent.txt")
(set! checkpoint/check-filename "check-fluent.txt")
/mesh/check
/file/auto-save/data-frequency 50
/file/auto-save/case-frequency each-time
/file/auto-save/retain-most-recent-files yes
/file/auto-save/max-files 2
(%py-exec "exec(open('{worker}', encoding='utf-8-sig').read())")
/exit ok
'''
(work/'solve.jou').write_text(journal,encoding='utf-8')
print(work/'solve.jou')
