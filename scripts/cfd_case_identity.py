"""Identify source meshes and compare Fluent grids independently of entity numbering and partitions."""
import hashlib,json,re
from collections import defaultdict
from pathlib import Path
import h5py,numpy as np
from cut_fluent_cells import bounds
from fluent_checkpoints import case_for_data

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def digest(path):
    with Path(path).open('rb') as fp:return hashlib.file_digest(fp,'sha256').hexdigest()

def canonical_mesh(path):
    """Hash nanometre-quantized nodes, complete face-node sets and volume cell count."""
    path=Path(path)
    if path.suffix.lower()=='.h5':
        with h5py.File(path) as fp:
            m=fp['meshes/1'];grp=m['nodes/coords'];maxid=max(bounds(v)[1] for v in grp.values())
            sample=next(iter(grp.values()));xyz=np.full((maxid,sample.shape[-1]),np.nan)
            for block in grp.values():
                lo,hi=bounds(block);xyz[lo-1:hi]=block[:]
            cells=m['cells/zoneTopology'];ncell=int(np.sum(cells['maxId'][:].astype('i8')-cells['minId'][:].astype('i8')+1))
            def blocks():
                for block in m['faces/nodes'].values():
                    counts=block['nnodes'];cursor=0
                    for j in range(0,len(counts),64000):
                        n=counts[j:j+64000].astype('i4');end=cursor+int(n.sum(dtype='i8'))
                        yield n,block['nodes'][cursor:end].astype('i4')
                        cursor=end
                    if cursor!=len(block['nodes']):raise ValueError('Incomplete face-node storage')
            return connectivity_digest(xyz,ncell,blocks())
    xyz=[];lines=defaultdict(list);ncell=None;mode=None;width=0
    with path.open(encoding='ascii') as fp:
        for raw in fp:
            row=raw.strip()
            if row.startswith('(12 (0 '):ncell=int(row.split()[3],16)
            if row.startswith('(') or row.startswith(')'):
                mode='nodes' if row.startswith('(10 (1 ') and row.endswith(')(') else None
                face=re.match(r'^\(13 \([0-9a-fA-F]+ [0-9a-fA-F]+ [0-9a-fA-F]+ [0-9a-fA-F]+ ([0-9a-fA-F]+)\)\($',row)
                if face:mode='faces';width=int(face[1],16)
                continue
            if mode=='nodes':xyz.append([float(x) for x in row.split()])
            elif mode=='faces':
                data=[int(x,16) for x in row.split()]
                count=width or data.pop(0)
                if len(data)!=count+2:raise ValueError('Invalid ASCII face payload')
                lines[count].append(data[:count])
    if ncell is None or not xyz or not lines:raise ValueError('Missing planar Fluent mesh coordinates or edges')
    blocks=((np.full(len(rows),k,'i4'),np.asarray(rows,'i4').ravel()) for k,rows in lines.items())
    return connectivity_digest(np.array(xyz),ncell,blocks)

def connectivity_digest(xyz,ncell,blocks):
    if ncell<1 or not np.all(np.isfinite(xyz)):raise ValueError('Missing mesh cells or node coordinates')
    if xyz.shape[1]==2:xyz=np.column_stack((xyz,np.zeros(len(xyz))))
    coords=np.rint(xyz*1.e9).astype('<i8');unique,keys,counts=np.unique(coords,axis=0,return_inverse=True,return_counts=True)
    h=hashlib.sha256()
    h.update(np.array([ncell,len(xyz)],'<i8').tobytes());h.update(unique.tobytes());h.update(counts.astype('<i8').tobytes())
    collected=defaultdict(list)
    for n,ids in blocks:
        if not len(n) or np.min(n)<2 or int(n.sum())!=len(ids) or np.min(ids)<1 or np.max(ids)>len(xyz):raise ValueError('Malformed mesh face')
        keys0=keys[ids-1].astype('<i4');offset=np.r_[0,np.cumsum(n[:-1],dtype='i8')]
        for size in np.unique(n):
            faces=keys0[offset[n==size,None]+np.arange(size)];faces.sort(axis=1);collected[int(size)].append(faces)
    for size in sorted(collected):
        ar=np.concatenate(collected[size])
        dtype=np.dtype([(f'n{j}','<i4') for j in range(size)])
        rows=np.ascontiguousarray(ar).view(dtype).reshape(-1);rows.sort(kind='quicksort')
        h.update(np.array([size,len(rows)],'<i8').tobytes());h.update(memoryview(rows).cast('B'))
    return h.hexdigest()

def reference(root,case,section):
    if section:
        folder=root/'02_mesh'/case;grid=(folder/'section.msh').resolve(strict=True)
        cfg=read(folder/'section_config.json')
        inlet=cfg['inlet_profile'];profile=Path(inlet['profile_file']).resolve(strict=True)
        c=Path(inlet['source_case']).resolve(strict=True);d=Path(inlet['source_data']).resolve(strict=True)
        if cfg['case']!=case or any(not p.is_relative_to(root) for p in (grid,c,d,profile)) or case_for_data(d)!=c:
            raise ValueError('2D inlet and section mesh must belong to the physical source pair')
        fine=read(c.parent/'iteration_qa.json')
        if (not fine['passed'] or c.name!=fine['accepted_stem']+'.cas.h5' or d.name!=(fine.get('accepted_data') or fine['accepted_stem']+'.dat.h5')
                or digest(c)!=fine['case_sha256'] or digest(d)!=fine['data_sha256']):
            raise ValueError('Section inlet is not the accepted Fine endpoint')
        drivers={'profile_sha256':digest(profile),'fine_case_sha256':fine['case_sha256'],'fine_data_sha256':fine['data_sha256']}
        sha=digest(grid)
    elif case.startswith('surfref_'):
        # Surface-refinement study grid (brief: refine the surface AND the volume mesh): the published Medium
        # volume size field and inflation on the refined surface tessellation. Not part of the volume ladder.
        from fasttrack_profile import LICENSE_CELL_CAP
        folder=root/'02_mesh'/'surfref';row=read(folder/'mesh_qa.json')
        grid=Path(row['source_mesh']).resolve(strict=True);sha=digest(grid);drivers={}
        if not (grid.is_relative_to(folder.resolve()) and row.get('level')=='surfref' and row.get('passed') is True
                and sha==row['mesh_sha256'] and row['cells']<=LICENSE_CELL_CAP):
            raise ValueError('The native volume mesh is not the admitted surface-refinement grid')
    else:
        level=case.split('_')[0];folder=root/'02_mesh'/level;row=read(folder/'mesh_qa.json');ladder=read(root/'02_mesh/grid_ladder_qa.json')
        grid=Path(row['source_mesh']).resolve(strict=True);sha=digest(grid);drivers={}
        from fasttrack_profile import in_hard_window
        if not in_hard_window(level,row["cells"]):
            raise ValueError("The production mesh is outside the admissible fast-track count range")
        if not (grid.is_relative_to(folder) and row['level']==level and row['passed']
                and ladder['passed'] and sha==row['mesh_sha256']==ladder['mesh_sha256'][level]):
            raise ValueError('The native volume mesh is not the admitted published grid for '+level)
    token=hashlib.sha256(json.dumps([case,sha,drivers],sort_keys=True).encode()).hexdigest()
    return dict(case=case,dimension='2D' if section else '3D',mesh_path=str(grid),volume_mesh_sha256=sha,
                boundary_input=drivers,case_input_signature=token)

def bind_pair(qa,cas,dat,reference):
    if case_for_data(dat).resolve()!=Path(cas).resolve():raise ValueError('Mismatched native CFF endpoint')
    return dict(volume_mesh_sha256=reference['volume_mesh_sha256'],case_input_signature=reference['case_input_signature'],
                case_sha256=digest(cas),data_sha256=digest(dat))

def verify_endpoint(root,case,qa,cas,dat,section):
    current=reference(root,case,section)
    if any(qa.get(k)!=v for k,v in bind_pair(qa,cas,dat,current).items()):
        raise ValueError(f'{case} endpoint uses stale grid, inlet, case, or data')
    return current

