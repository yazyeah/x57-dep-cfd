"""Run a prepared Medium or Fine FTM level through native independent publication."""
import argparse
import json
from pathlib import Path
import re

import h5py

from audit_native_wtm_surface import measure
from complete_production_mesh import complete, native, published_level
from control_gate import atomic_write_json
from p2_geometry_io import TYPES
from prepare_refined_ftm import ROOT, C16, digest, verify_split_plan
from relocate_ftm_checkpoint import copy_checkpoint, copy_sidecars
from run_x57_converged import control
from mesh_ladder_limits import production_plan

STEPS=('field','seed','sidecars','assemble','surface','register','mesh','publish')


def physical_surface(mesh_path,level,source):
    with h5py.File(mesh_path) as h:
        raw=h['settings/TGrid Variables'][0]
        matches=re.findall(rb'\(external_fluid fluid \d+ \(([\d ]+)\) \(\) mesh \(',raw)
        if len(matches)!=1:
            raise ValueError('Expected one named external fluid mesh object')
        ids={int(x) for x in matches[0].split()}
        top=h['meshes/1/faces/zoneTopology']
        names=top['name'][0].decode().rstrip(';').split(';')
        actual=[n for i,n in zip(top['id'][:],names,strict=True) if i in ids]
        if len(actual)!=len(TYPES) or set(actual)!=set(TYPES):
            raise ValueError(f'Fluid mesh object has unexpected boundaries: {actual}')
    qa=measure(mesh_path,level)
    qa['mesh_object_faces']=actual
    expected=json.loads((source/'assembled_shell_qa.json').read_text('utf-8-sig'))['faces_by_zone']
    qa['confirmed_source_wall_counts']=all(expected[n]==c for n,c in qa['face_counts'].items())
    qa['passed']=qa['passed'] and qa['confirmed_source_wall_counts']
    return qa


def run(work, first):
    cfg=json.loads((work/'mesh_config.json').read_text(encoding='utf-8-sig'))
    level=cfg['level']
    verify_split_plan(cfg['prism_scopes'],cfg['continuous_parent_inputs'])
    if level not in ('fine','medium') or not work.is_relative_to(ROOT/'02_mesh'/level):
        raise ValueError('Expected level-specific workspace production inputs')
    control()
    canonical=published_level(level)
    if canonical:
        print(f'{level} already accepted at {canonical}')
        control()
        return
    plan=production_plan(ROOT)
    if not plan['measured_constraints_pass']:
        raise ValueError(f"Measured predecessor mesh counts or refinement ratios failed: {plan}")
    print(f"{level} planned count interval: {plan['count_windows'][level]}",flush=True)
    previous='coarse' if level=='medium' else 'medium'
    prev=json.loads((ROOT/'02_mesh'/previous/'mesh_qa.json').read_text('utf-8-sig'))
    if not prev['passed'] or not all(prev['checks'].values()) or digest(Path(prev['source_mesh']))!=prev['mesh_sha256']:
        raise ValueError(f'Missing verified predecessor mesh: {previous}')
    source=Path(cfg['source_surface_dir'])
    if cfg['source_surface_sha256']!=digest(source/'aircraft_domain.msh') or digest(work/'conformal_patch_input.msh')!=cfg['source_surface_sha256']:
        raise ValueError('Prepared shell does not match the source')
    seed=C16/'extracted_si_surface.msh.h5'
    rebound=work/'workflow_seed.msh.h5'
    field=work/'refinement.sf'
    fluid=work/'conformal_fluid.msh.h5'
    logbook=work/'volume_generation_transcript.json'
    for step in STEPS[STEPS.index(first):]:
        control()
        try:
            if step=='field':
                native(work,work/'field.jou','meshing',f'{level}_{work.name}_field')
            elif step=='seed':
                copy_checkpoint(seed,rebound,field)
            elif step=='sidecars':
                copy_sidecars(seed,rebound,field)
            elif step=='assemble':
                native(work,work/'assemble.jou','meshing',f'{level}_{work.name}_fluid')
            elif step=='surface':
                qa=physical_surface(fluid,level,source)
                qa['surface_sha256']=digest(fluid)
                atomic_write_json(work/'conformal_region_cad_audit.json',qa)
                if not qa['passed']:
                    raise ValueError('CAD and fluid-object checks failed')
            elif step=='register':
                qa=json.loads((work/'conformal_region_cad_audit.json').read_text('utf-8-sig'))
                if not qa['passed'] or qa['surface_sha256']!=digest(fluid):
                    raise ValueError('The surface does not match its audited checkpoint')
                native(work,work/'register.jou','meshing',f'{level}_{work.name}_controls')
            elif step=='mesh':
                transcript=native(work,work/'mesh.jou','meshing',f'{level}_{work.name}_volume')
                atomic_write_json(logbook,dict(transcript=str(transcript),raw_mesh_sha256=digest(Path(cfg['mesh']))))
            elif step=='publish':
                result=json.loads(logbook.read_text('utf-8-sig'))
                if result['raw_mesh_sha256']!=digest(Path(cfg['mesh'])):
                    raise ValueError('Raw volume does not match the generation transcript receipt')
                complete(work,Path(result['transcript']))
        finally:
            control()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('work',type=Path)
    parser.add_argument('--from-step',choices=STEPS,default='field')
    args=parser.parse_args()
    control()
    try:
        run(args.work.resolve(strict=True),args.from_step)
    finally:
        control()
