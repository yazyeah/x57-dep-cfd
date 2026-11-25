"""Bind structural observations to the published volume grid, source geometry and exact CFD endpoint."""
import hashlib,json,os,tempfile
from pathlib import Path
from mapdl_shell_fields import source_hash
from p2_geometry_io import WALLS

ROOT=Path(__file__).resolve().parents[1]
MODELS=ROOT/'03_cases/fsi_structural/models'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def signature(value):
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')
    return hashlib.sha256(raw).hexdigest()

def commit(path,record):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent,suffix='.pending',delete=False,mode='w',encoding='utf8') as output:
        pending=Path(output.name);json.dump(record,output,indent=2,allow_nan=False)
    try:os.replace(pending,path)
    finally:pending.unlink(missing_ok=True)

def inside(path):
    path=Path(path).resolve(strict=True)
    if not path.is_relative_to(ROOT):raise ValueError(f'Expected a workspace source {path}')
    return path

def hashes(files):
    return {str(inside(p)):source_hash(inside(p)) for p in files}

def geometry():
    qa_path=inside(ROOT/'02_mesh/coarse/mesh_qa.json');qa=read(qa_path)
    if qa.get('passed') is not True or qa.get('level')!='coarse':raise ValueError('A passing published coarse volume grid is required')
    source=qa['source_geometry']
    cfg=inside(source['meshing_config_path']);settings=read(cfg);mesh=inside(qa['source_mesh'])
    directory=inside(source['source_surface_dir']);shell=inside(settings['shell'])
    if inside(settings.get('source_surface_dir') or shell.parent)!=directory or (source.get('source_surface_path') and inside(source['source_surface_path'])!=shell):
        raise ValueError('Volume-grid QA and meshing configuration identify different surface folders')
    if source_hash(mesh)!=qa['mesh_sha256'] or source_hash(cfg)!=source['meshing_config_sha256'] or source_hash(shell)!=source['source_surface_sha256']:
        raise ValueError('Coarse volume mesh, source mesh or mesher configuration changed after published QA')
    files=[directory/(name+'.stl') for name in WALLS]
    files.append(ROOT/'01_geometry/cad_patches/wall_wing.stl')
    evidence={'coarse_volume_mesh':str(mesh),'volume_mesh_sha256':qa['mesh_sha256'],
              'meshing_config_path':str(cfg),'meshing_config_sha256':source['meshing_config_sha256'],
              'source_surface_dir':str(directory),'source_surface_file':str(shell),'source_surface_sha256':source['source_surface_sha256'],
              'wall_and_spar_CAD_sha256':hashes(files)}
    evidence['signature']=signature(evidence)
    return evidence

def lock_geometry(record):
    path=MODELS/'geometry_locks'/(record['signature']+'.json')
    if path.exists():
        if read(path)!=record:raise ValueError('Existing geometry lock content changed')
    else:commit(path,record)
    return path

def accepted_model(grid,geom=None):
    geom=geom or geometry()
    work=MODELS/grid
    model=read(work/'model.json')
    if model['level']!=grid or model['geometry_signature']!=geom['signature']:
        raise ValueError(f'{grid} SHELL181 model uses a different accepted coarse surface')
    if read(inside(model['geometry_lock']))!=geom:raise ValueError('Immutable coarse-surface record mismatch')
    files=hashes([work/'model.inp',work/'shell_mesh.npz'])
    new=signature({'geometry':geom['signature'],'grid':grid,'model_files_sha256':files})
    generator=Path(__file__).with_name('prepare_mapdl_shell.py')
    if model.get('model_generator_sha256')!=source_hash(generator) or files!=model['model_files_sha256'] or new!=model['model_signature']:
        raise ValueError('Structural mesh or element/material/support definitions changed after generation')
    return model

def load_identity(grid,case,model=None):
    from compare_x57_cases import accepted
    qa,cas,dat=accepted(case)
    model=model or accepted_model(grid)
    qa_path=ROOT/'02_mesh'/case.split('_')[0]/'mesh_qa.json'
    meshqa=read(qa_path)
    if not meshqa['passed'] or qa['volume_mesh_sha256']!=meshqa['mesh_sha256']:raise ValueError('Mapped CFD grid lost its accepted status or changed')
    files=[cas,dat,cas.parent/'iteration_qa.json',cas.parent/'fluent_discrete_disk_integrals.json',
           ROOT/'01_geometry/geometry_audit.json',ROOT/'scripts/map_cfd_shell_loads.py',ROOT/'scripts/extract_fluent_fields.py']
    content=hashes(files)
    identity={'grid':grid,'case':case,'geometry_signature':model['geometry_signature'],'model_signature':model['model_signature'],
              'CFD_volume_mesh_sha256':meshqa['mesh_sha256'],'CFD_case':str(cas),'CFD_data':str(dat),'source_sha256':content}
    identity['load_signature']=signature(identity)
    return identity

def verify_transfer(grid,case):
    work=MODELS.parent/(grid+'_struct__'+case)
    report=read(work/'load_transfer.json')
    expected=load_identity(grid,case)
    if report['load_identity']!=expected or report['mapped_files_sha256']!=hashes([work/'mapped_loads.inp',work/'nodal_loads.npy']):
        raise ValueError(f'Mapped loads are stale or from another model/operating point: {grid} / {case}')
    return report

def accepted_result(grid,case):
    work=MODELS.parent/(grid+'_struct__'+case)
    transfer=verify_transfer(grid,case)
    native=read(work/'native_result_provenance.json')
    if native['case']!=case or native['grid']!=grid or native['load_signature']!=transfer['load_identity']['load_signature']:
        raise ValueError('MAPDL result and current CFD/structural signatures differ')
    job=native['job']
    if Path(job).name!=job or not job.startswith('x57fsi'):raise ValueError('Invalid native MAPDL result identifier')
    paths=[work/(job+'.rst'),work/(job+'.out'),work/'solve.inp',work/'model.inp',work/'load_transfer.json',work/'shell_fields.npz',
           work/'mapped_loads.inp',work/'nodal_loads.npy',work/'component_stress_metrics.json',work/'structural_metrics.json',
           MODELS/grid/'shell_mesh.npz',MODELS/grid/'model.json']
    if hashes(paths)!=native['sha256']:raise ValueError('One or more native MAPDL evidence files changed')
    tools=[Path(__file__).with_name(f) for f in ['mapdl_static_results.py','mapdl_shell_fields.py','run_mapdl_structural.py']]
    if native.get('structural_solver_and_export_sha256')!=hashes(tools):
        raise ValueError('Static solve or SHELL181 field extraction definition changed')
    metrics=read(work/'structural_metrics.json')
    if metrics['equilibrium']['passed'] is not True:raise ValueError('MAPDL static reaction equilibrium failed')
    return metrics,native

