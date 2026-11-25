"""Intersect actual Fluent wall polygons with vertical rays used by the CAD clearance audit."""
import h5py
import numpy as np
from cut_fluent_cells import bounds, read_id_blocks, zones


def names(topology):
    return list(zones(topology))


def intersections(polygons, x, z):
    """Use centroid fans, including polygons with more than three vertices."""
    if not len(polygons):
        return []
    center=polygons.mean(axis=1)
    a=polygons-center[:,None,:]
    b=np.roll(a,-1,axis=1)
    dx=x-center[:,0,None]
    dz=z-center[:,2,None]
    det=a[:,:,0]*b[:,:,2]-a[:,:,2]*b[:,:,0]
    usable=abs(det)>1.e-16
    u=np.divide(dx*b[:,:,2]-dz*b[:,:,0],det,out=np.zeros_like(det),where=usable)
    v=np.divide(a[:,:,0]*dz-a[:,:,2]*dx,det,out=np.zeros_like(det),where=usable)
    hit=usable&(u>=-1.e-9)&(v>=-1.e-9)&(u+v<=1.+1.e-9)
    return (center[:,None,1]+u*a[:,:,1]+v*b[:,:,1])[hit].tolist()


def measure_stations(mesh_path, stations):
    output=[dict(x_m=float(x),z_m=float(z),sponson=[],upper=[]) for x,z in stations]
    with h5py.File(mesh_path,'r') as f:
        mesh=f['meshes/1']
        total=int(max(mesh['nodes/zoneTopology/maxId']))
        xyz=read_id_blocks(mesh['nodes/coords'],total,np.float64,3)
        labels=zones(mesh['faces/zoneTopology'])
        for label,(first,last) in labels.items():
            if not label.startswith(('wall_sponson','wall_nacelles','wall_wing')):
                continue
            key='sponson' if label.startswith('wall_sponson') else 'upper'
            for part in mesh['faces/nodes'].values():
                lo,hi=bounds(part)
                if hi<first or lo>last:
                    continue
                sizes=part['nnodes'][:].astype(np.int64)
                spans=np.r_[0,np.cumsum(sizes)]
                for begin in range(max(0,first-lo),min(len(sizes),last-lo+1),12000):
                    end=min(begin+12000,last-lo+1,len(sizes))
                    nodeids=part['nodes'][spans[begin]:spans[end]]
                    for count in np.unique(sizes[begin:end]):
                        local=np.flatnonzero(sizes[begin:end]==count)+begin
                        poly=xyz[nodeids[(spans[local]-spans[begin])[:,None]+np.arange(count)]]
                        xlo=poly[:,:,0].min(axis=1); xhi=poly[:,:,0].max(axis=1)
                        zlo=poly[:,:,2].min(axis=1); zhi=poly[:,:,2].max(axis=1)
                        for row in output:
                            x,z=row['x_m'],row['z_m']
                            selected=(xlo<=x)&(xhi>=x)&(zlo<=z)&(zhi>=z)
                            row[key].extend(intersections(poly[selected],x,z))
    for row in output:
        sponson,upper=row.pop('sponson'),row.pop('upper')
        top=max(sponson,default=None); underside=min(upper,default=None)
        row.update(sponson_top_y_m=top,underside_y_m=underside,
                   gap_m=underside-top if underside is not None and top is not None else None)
    return output


def measure(mesh_path, x, z):
    return measure_stations(mesh_path,[(x,z)])[0]
