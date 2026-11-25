"""Read wall-face fields and plane-cell values by Fluent's global HDF5 entity IDs."""
import argparse
from pathlib import Path
import h5py
import numpy as np
from cut_fluent_cells import read_id_blocks, zones, bounds, cut_mesh,robust_cut


def sample(group, name, ids):
    field = group[name]
    first = next(iter(field.values()))
    result = np.full((len(ids),) + first.shape[1:], np.nan)
    for ds in field.values():
        lo, hi = bounds(ds)
        mask = (ids >= lo) & (ids <= hi)
        if mask.any():
            result[mask] = ds[:][ids[mask] - lo]
    if not np.isfinite(result).all():
        raise ValueError(f"Missing {name} on {np.sum(~np.isfinite(result))} requested entries.")
    return result


def face_geometry(vertex_ids, coords, counts):
    offsets = np.r_[0, np.cumsum(counts, dtype=np.int64)]
    centers = np.empty((len(counts), 3))
    areas = np.empty_like(centers)
    for n in np.unique(counts):
        ids = np.flatnonzero(counts == n)
        verts = coords[vertex_ids[offsets[ids,None] + np.arange(n)]]
        base = verts[:,0,:]
        delta = verts[:,1:,:] - base[:,None,:]
        cross = np.cross(delta[:,:-1,:],delta[:,1:,:]) * .5
        vector = cross.sum(axis=1)
        normal = vector / np.linalg.norm(vector,axis=1)[:,None]
        signed = np.einsum("ijk,ik->ij", cross, normal)
        tri_centers = (delta[:,:-1,:] + delta[:,1:,:]) / 3.
        centers[ids] = base + np.einsum("ij,ijk->ik",signed,tri_centers)/signed.sum(axis=1)[:,None]
        areas[ids] = vector
    return centers, areas


def extract_walls(case, data):
    with h5py.File(case) as fc, h5py.File(data) as fd:
        mesh = fc["meshes/1"]
        xyz = read_id_blocks(mesh["nodes/coords"],int(max(mesh["nodes/zoneTopology/maxId"])),float,3)
        fields = fd["results/1/phase-1/faces"]
        parts = []
        for name,(lo,hi) in zones(mesh["faces/zoneTopology"]).items():
            if not name.startswith("wall_"):
                continue
            face_ids = np.arange(lo,hi+1)
            centers = np.full((len(face_ids),3),np.nan)
            area_vec = np.full_like(centers,np.nan)
            for block in mesh["faces/nodes"].values():
                start,end = bounds(block)
                a,b = max(lo,start),min(hi,end)
                if a>b:
                    continue
                counts = block["nnodes"][:].astype(np.int64)
                offsets = np.r_[0,np.cumsum(counts)]
                j,k = a-start,b-start+1
                ids = block["nodes"][offsets[j]:offsets[k]]
                centers[a-lo:b-lo+1],area_vec[a-lo:b-lo+1] = face_geometry(ids,xyz,counts[j:k])
            area = np.linalg.norm(area_vec,axis=1)
            if not np.isfinite(area).all() or not np.all(area>0):
                raise ValueError(f"Incomplete or degenerate wall {name}")
            parts.append(dict(component=np.repeat(name,len(area)),face_id=face_ids,xyz=centers,
                              inward_fluid_area_vector_m2=area_vec,area_m2=area,
                              p_gauge_Pa=sample(fields,"SV_P",face_ids),
                              yplus=sample(fields,"SV_WALL_YPLUS",face_ids),
                              yplus_utau=sample(fields,"SV_WALL_YPLUS_UTAU",face_ids),
                              wall_shear_storage=sample(fields,"SV_WALL_SHEAR",face_ids)))
        if not parts:
            raise ValueError("Aircraft wall zones missing.")
        return {name:np.concatenate([part[name] for part in parts]) for name in parts[0]}


def extract_slice(case, data, axis, value):
    result = robust_cut(case, axis, value)
    with h5py.File(data) as f:
        fields = f["results/1/phase-1/cells"]
        ids = result["cell_ids"]
        for label,var in [("p_gauge_Pa","SV_P"),("u_m_s","SV_U"),("v_m_s","SV_V"),("w_m_s","SV_W")]:
            result[label] = sample(fields,var,ids)
    return result


if __name__ == "__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case",type=Path)
    ap.add_argument("data",type=Path)
    ap.add_argument("output",type=Path)
    ap.add_argument("--slice",nargs=2,metavar=("AXIS","METRES"))
    args=ap.parse_args()
    result=(extract_slice(args.case,args.data,"xyz".index(args.slice[0]),float(args.slice[1]))
            if args.slice else extract_walls(args.case,args.data))
    np.savez_compressed(args.output,**result)
    print(args.output,sorted(result))
