"""Prepare matched Medium/Fine FTM production inputs on the audited SI shells."""
import argparse
import hashlib
import math
import json
from pathlib import Path
import re
import shutil

import numpy as np

from mesh_region_budget import boi_bounds
from p2_geometry_io import TYPES, indices, stl_triangles
from prepare_native_polyhex import PAUSE_AFTER_SAVE, quality_evidence_journal, improvement_journal

ROOT = Path(__file__).resolve().parents[1]
C16 = ROOT / '02_mesh/coarse/f_registered_ftm_16'
BASE = ROOT / '02_mesh/coarse/octree_field_budget'
TARGETS = {
    'medium': dict(hlp=.013, wt=.017, core=.067, box=.095, mid=.145, far=2.2,
                   wing=(15e-6, 4, 4, 1.18), nac=(35e-6, 4, 3, 1.18),
                   low=(70e-6, 4, 3, 1.18), tail=(60e-6, 4, 3, 1.18)),
    'fine': dict(hlp=.008, wt=.010, core=.045, box=.065, mid=.1, far=2.2,
                 wing=(12e-6, 3, 6, 1.17), nac=(30e-6, 3, 5, 1.18),
                 low=(60e-6, 3, 5, 1.18), tail=(60e-6, 3, 5, 1.18)),
}
SCOPES = [('parent_low_airframe', ['wall_fuselage', 'wall_sponson'], 'low'),
          ('parent_wing', ['wall_wing'], 'wing'),
          ('parent_nacelles', ['wall_nacelles'], 'nac'),
          ('parent_tail', ['wall_empennage'], 'tail')]


def json_save(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def existing_bodies():
    contents = (BASE/'refinement_bodies.msh').read_text('ascii')
    block = re.search(r'\(10 \(1 1 [\da-f]+ 1 3\)\(\s*(.*?)\s*\)\)', contents, re.S)
    xyz = np.fromstring(block[1], sep=' ').reshape(-1, 3)
    patches = {}
    for face in re.finditer(r'\(13 \(([\da-f]+) [\da-f]+ [\da-f]+ 3 3\)\(\s*(.*?)\s*\)\)\s*\(45 \((\d+) wall ([\w-]+)\)\(\)\)', contents, re.S):
        if int(face[1], 16) != int(face[3]):
            raise ValueError('Malformed BOI index')
        ids = [[int(k, 16)-1 for k in row.split()[:3]] for row in face[2].splitlines()]
        patches[face[4]] = xyz[ids]
    if len(patches) != 9:
        raise ValueError('Missing calibrated disk/wake BOI')
    return patches


def jet_tube(rotor, end_x):
    # Use the full disk-radius envelope as the pre-solve sizing region. Flow
    # data, including the contracted streamtubes, are measured after convergence.
    cx, cy, cz = rotor['center_m']
    radius = rotor['r_tip_m']
    x0 = cx+rotor['thickness_m']/2
    if end_x <= x0:
        raise ValueError('Jet tube axis must point downstream')
    theta = np.arange(96)*(2*np.pi/96)
    y, z = cy+radius*np.cos(theta), cz+radius*np.sin(theta)
    a = np.column_stack((np.full(len(y), x0), y, z))
    b = a.copy()
    b[:, 0] = end_x
    a1, b1 = np.roll(a, -1, axis=0), np.roll(b, -1, axis=0)
    cap0 = np.broadcast_to([x0, cy, cz], a.shape)
    cap1 = np.broadcast_to([end_x, cy, cz], b.shape)
    return np.concatenate([np.stack(t, axis=1) for t in
                           [(a, a1, b1), (a, b1, b), (cap0, a1, a), (cap1, b, b1)]])


def write_sizing_mesh(path, patches):
    xyz, faces = indices(np.concatenate(list(patches.values())))
    with path.open('w', encoding='ascii') as stream:
        stream.write(f'(2 3)\n(10 (0 1 {len(xyz):x} 0 3))\n(10 (1 1 {len(xyz):x} 1 3)(\n')
        np.savetxt(stream, xyz, fmt='%.12g')
        stream.write(f'))\n(13 (0 1 {len(faces):x} 0))\n')
        off = 0
        for zid, (name, tri) in enumerate(patches.items(), 2):
            typ, code = TYPES[name] if name in TYPES else ('wall', 3)
            end = off+len(tri)
            stream.write(f'(13 ({zid:x} {off+1:x} {end:x} {code:x} 3)(\n')
            np.savetxt(stream, faces[off:end]+1, fmt='%x %x %x 0 0')
            stream.write(f'))\n(45 ({zid} {typ} {name})())\n')
            off = end


def write_field(work, source, cfg):
    rotor_data = json.loads((ROOT/'DELIVERABLES/data/actuator_disk_model.json').read_text('utf-8-sig'))
    patches = existing_bodies()
    bounds = boi_bounds(BASE/'refinement_bodies.msh')
    end_x = bounds['near_wake_boi'][1][0]
    size = {}
    for rotor in rotor_data['rotors']:
        key = rotor['name'].lower().replace('-', '_')
        patches[key+'_jet_core_boi'] = jet_tube(rotor, end_x)
        size[key+'_boi'] = cfg['wt' if key.startswith('wt') else 'hlp']
        size[key+'_jet_core_boi'] = cfg['core']
    size['near_wake_boi'] = cfg['box']
    size['mid_wake_boi'] = cfg['mid']
    if set(patches) != set(size):
        raise ValueError('Native size controls must cover each BOI')
    write_sizing_mesh(work/'refinement_bodies.msh', patches)
    shell = {n: stl_triangles(source/(n+'.stl')) for n in TYPES}
    write_sizing_mesh(work/'field_geometry.msh', {**shell, **patches})
    minimum = min(size.values())*.375
    far = cfg['far']
    sizing = [f'("{n}" "boi" {minimum:g} {width:g} 1.22 12. 1. 12 "Face Zone" "{n}" #t #t)'
              for n,width in size.items()]
    sizing.append(f'("outer" "soft" {far:g} {far:g} 1.22 12. 1. 12 "Face Zone" "farfield_*" #t #t)')
    geom = (work/'field_geometry.msh').as_posix()
    field = (work/'refinement.sf').as_posix()
    (work/'field.jou').write_text(
        f'/file/confirm-overwrite no\n/file/read-mesh "{geom}"\n/objects/create\nsizing_mesh\nfluid\n1\n*\n()\n()\nmesh\nyes\n/objects/list\n'
        f"(tgsetvar! 'size-func/global-params '({minimum:g} {far:g} 1.22 2.))\n"
        + "(tgsetvar! 'size-controls '("+ ' '.join(sizing) + "))\n"
        + f'/scoped-sizing/list\n/scoped-sizing/validate\n/scoped-sizing/compute\n/file/write-size-field "{field}"\n/exit yes\n',
        encoding='ascii')
    return size, bounds


def verify_split_plan(scopes, inputs):
    """Validate the v252 uniform-offset, split-prism controls for one fluid region."""
    by_scope={group["name"]:group for group in scopes}
    if not inputs or not scopes or len(by_scope)!=len(scopes):
        raise ValueError("Empty or duplicate prism layer controls")
    walls=[w for scope in scopes for w in scope["walls"]]
    expected={w for _,group,_ in SCOPES for w in group}
    if set(walls)!=expected or len(walls)!=len(expected):
        raise ValueError("All five walls must each be scoped once")
    if len(inputs)!=len(scopes) or {p["name"] for p in inputs}!=set(by_scope):
        raise ValueError("Physical and native prism groups differ")
    if len({p["parent_count"] for p in inputs})!=1:
        raise ValueError("Fluent requires the same NumberOfLayers for all prism controls in external_fluid")
    for p in inputs:
        s=by_scope[p["name"]]
        n,m=p["parent_count"],p["split_count"]
        r,h=s["growth"],s["first_height_m"]
        rate,first=p["parent_growth"],p["parent_height_m"]
        if (type(n) is not int or n<1 or type(m) is not int or not 2<=m<=100
                or not math.isfinite(first) or first<1e-12 or not .01<=rate<=3
                or not math.isfinite(r) or r<=0 or not math.isfinite(h) or h<=0
                or s["layers"]!=n*m or set(s["walls"])!=set(p["walls"])):
            raise ValueError("Invalid Fluent split control or physical target on "+p["name"])
        recovered_r=rate**(1/m)
        recovered_h=first/sum(recovered_r**j for j in range(m))
        firsts=[h*r**(i*m) for i in range(n)]
        parents=[first*rate**i for i in range(n)]
        physical=[start*sum(r**j for j in range(m)) for start in firsts]
        pairs=[(recovered_r,r),(recovered_h,h),(sum(parents),s["total_height_m"]),
               (h*r**(s["layers"]-1),s["last_height_m"]),*zip(parents,physical)]
        if not all(math.isclose(a,b,rel_tol=1e-11,abs_tol=0.) for a,b in pairs):
            raise ValueError("Native parent plan does not reconstruct requested child layers on "+p["name"])


def split_plan(cfg):
    scopes,inputs=[],[]
    for name,walls,key in SCOPES:
        height,parents,splits,rate=cfg[key]
        layers=parents*splits
        scopes.append(dict(name=name,walls=walls,first_height_m=height,layers=layers,growth=rate,
                           total_height_m=height*sum(rate**i for i in range(layers)),last_height_m=height*rate**(layers-1)))
        inputs.append(dict(name=name,walls=walls,parent_count=parents,split_count=splits,
                           parent_height_m=height*sum(rate**n for n in range(splits)),parent_growth=rate**splits))
    verify_split_plan(scopes,inputs)
    return scopes,inputs


def prepare(level, attempt, wing_first=None):
    if not re.fullmatch(r'[a-zA-Z0-9_]+',attempt):
        raise ValueError('Expected a simple attempt name')
    source = ROOT/'01_geometry'/f'p2_{level}_prism_base_patches'
    work = ROOT/'02_mesh'/level/attempt
    cfg = TARGETS[level].copy()
    if wing_first is not None:
        if not 0 < wing_first < .001:
            raise ValueError('Invalid first-layer height')
        cfg['wing'] = (wing_first, *cfg['wing'][1:])
    scopes,inputs=split_plan(cfg)
    work.mkdir(exist_ok=False)
    size, bounds = write_field(work, source, cfg)
    shell = source/'aircraft_domain.msh'
    shutil.copyfile(shell,work/'conformal_patch_input.msh')
    # These lines are the native, validated one-region assembly prompts.
    assembly = (C16/'assemble_local.jou').read_text().splitlines()
    assembly[1] = f'/file/read-mesh "{(work/"workflow_seed.msh.h5").as_posix()}"'
    assembly = [f'/file/write-mesh "{(work/"conformal_fluid.msh.h5").as_posix()}"' if line.startswith('/file/write-mesh ') else line for line in assembly]
    (work/'assemble.jou').write_text('\n'.join(assembly)+'\n', encoding='ascii')
    mesh = work/(level+'.msh.h5')
    improved = work/(level+'_improved.msh.h5')
    path = work/'mesh_config.json'
    config = dict(level=level,mesh=str(mesh),improved_mesh=str(improved),shell=str(shell),
                  source_surface_dir=str(source),source_surface_sha256=digest(shell),boi_file=str(work/'refinement_bodies.msh'),
                  near_wake_bounds=bounds['near_wake_boi'],mid_wake_bounds=bounds['mid_wake_boi'],
                  size_field_path=str(work/'refinement.sf'),max_size=cfg['far'],
                  sizes=[dict(name=n,labels=[n],type='Body Of Influence',size=v) for n,v in size.items()],
                  first_height=cfg['wing'][0],growth=cfg['wing'][3],layers=cfg['wing'][1]*cfg['wing'][2],
                  paired_layer_growth=True,native_continuous_split=False,native_post_improvement_method='Stair Step',
                  prism_scopes=scopes,continuous_parent_inputs=inputs,orthogonal_quality=0.05,
                  improvement_target_orthogonal_quality=0.15,improvement_inverse_orthogonal_quality=0.85,
                  improvement_iterations=5,generation_journal=str(work/'mesh.jou'),
                  field_producer_manifest=str(path),core_sizing_geometry='Pre-solve downstream cylindrical envelope of each calibrated actuator disk, through x=2.8 m.')
    json_save(path, config)
    module=(ROOT/'scripts/ftm_refined_native.py').as_posix()
    def entry(action):
        py=f"exec(open(r'{module}',encoding='utf-8').read()); {action}(workflow,meshing,r'{path.as_posix()}')"
        return f'(%py-exec "{py}")\n'
    field = (work/'refinement.sf').as_posix()
    fluid = (work/'conformal_fluid.msh.h5').as_posix()
    controls = (work/'registered_prism_controls.msh.h5').as_posix()
    (work/'register.jou').write_text(f'/file/confirm-overwrite no\n/file/read-mesh "{fluid}"\n'
        +PAUSE_AFTER_SAVE+f'/file/read-size-field "{field}"\n'+entry('install')
        +f'/file/write-mesh "{controls}"\n'+PAUSE_AFTER_SAVE+'/exit yes\n',encoding='ascii')
    (work/'mesh.jou').write_text(f'/file/confirm-overwrite no\n/file/read-mesh "{controls}"\n'
        +PAUSE_AFTER_SAVE+f'/file/read-size-field "{field}"\n'+entry('fill')
        +'yes\n'+f'/file/write-mesh "{mesh.as_posix()}"\n'+PAUSE_AFTER_SAVE
        +quality_evidence_journal()+'/exit yes\n',encoding='ascii')
    (work/'improve_raw.jou').write_text(improvement_journal(mesh,improved),encoding='ascii')
    print(work)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('level',choices=TARGETS)
    parser.add_argument('attempt')
    parser.add_argument('--wing-first',type=float)
    args=parser.parse_args()
    prepare(args.level,args.attempt,args.wing_first)
