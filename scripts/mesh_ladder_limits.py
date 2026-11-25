"""Three-level CFD count planning and volume-based mesh-spacing ratios."""
import json
import math
from pathlib import Path

WINDOWS = {"coarse": (280000, 380000), "medium": (560000, 680000), "fine": (940000, 1044000)}
LEVELS = tuple(WINDOWS)
MIN_R32, MIN_R21 = 1.18, 1.15


def ratio_pass(r32, r21):
    return bool(r32 >= MIN_R32 and r21 >= MIN_R21)


def count_plan(volumes, counts=None):
    """Closed integer intervals consistent with both ratio floors and every fixed count."""
    counts = counts or {}
    if set(volumes) != set(LEVELS) or set(counts) - set(LEVELS):
        raise ValueError("Expected coarse, medium and fine domain volumes and known count keys")
    if any(not math.isfinite(v) or v <= 0 for v in volumes.values()):
        raise ValueError("All three fluid volumes must be finite and positive")
    limits = {k: list(WINDOWS[k]) for k in LEVELS}
    for level, n in counts.items():
        if not isinstance(n, int) or n <= 0:
            raise ValueError("Fixed native counts must be positive integers")
        limits[level][0] = max(limits[level][0], n)
        limits[level][1] = min(limits[level][1], n)
    pairs = list(zip(LEVELS[:-1], LEVELS[1:], (MIN_R32, MIN_R21), strict=True))
    for prev, nxt, ratio in pairs:
        floor = limits[prev][0] * volumes[nxt] / volumes[prev] * ratio**3
        limits[nxt][0] = max(limits[nxt][0], math.ceil(math.nextafter(floor, -math.inf)))
    for prev, nxt, ratio in reversed(pairs):
        cap = limits[nxt][1] * volumes[prev] / volumes[nxt] / ratio**3
        limits[prev][1] = min(limits[prev][1], math.floor(math.nextafter(cap, math.inf)))
    return dict(count_windows=limits, fixed_cells=counts, fluid_volume_m3=volumes,
                minimum_r32=MIN_R32, minimum_r21=MIN_R21,
                feasible=all(lo <= hi for lo, hi in limits.values()))


def geometric_domain_volume(folder):
    """Oriented closed native meshing-input surface integral, for planning unsolved levels."""
    import numpy as np
    from p2_geometry_io import TYPES, stl_triangles
    total, area_sum = 0., 0.
    closure = np.zeros(3)
    for wall in TYPES:
        tri = stl_triangles(folder / (wall + ".stl")).astype(float)
        area = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]) / 2
        closure += area.sum(axis=0)
        area_sum += np.linalg.norm(area, axis=1).sum()
        total += np.einsum("ij,ij->", tri.mean(axis=1), area) / 3
    if total <= 0 or np.linalg.norm(closure) > 1e-8 * area_sum:
        raise ValueError(f"Inconsistent oriented domain surface for planning: {folder}")
    return float(total)


def production_plan(root, candidate=None):
    """Keep accepted predecessors fixed; predict only missing levels from their oriented shell."""
    volumes, counts, sources = {}, {}, {}
    root = Path(root)
    for level in LEVELS:
        path = root / "02_mesh" / level / "mesh_qa.json"
        if candidate and candidate[0] == level:
            counts[level], volumes[level] = candidate[1], candidate[2]
            sources[level] = "Current native CFF volume mesh"
        elif path.is_file():
            row = json.loads(path.read_text(encoding="utf-8-sig"))
            if row.get("passed") is True and row.get("level") == level:
                counts[level] = int(row["cells"])
                volumes[level] = float(row["five_region_evidence"]["fluid_volume_m3"])
                sources[level] = str(path)
        if level not in volumes:
            folder = root / "01_geometry" / ("p2_" + level + "_prism_base_patches")
            volumes[level] = geometric_domain_volume(folder)
            sources[level] = "Pre-mesh oriented surface estimate: " + str(folder)
    result = count_plan(volumes, counts)
    result["volume_sources"] = sources
    result["all_volume_meshes_measured"] = len(counts) == len(LEVELS)
    measured_h={k:(volumes[k]/n)**(1/3) for k,n in counts.items()}
    pairs=[("coarse","medium",MIN_R32),("medium","fine",MIN_R21)]
    measured_ratios={f"{p}_to_{n}":measured_h[p]/measured_h[n]
                     for p,n,_ in pairs if p in measured_h and n in measured_h}
    result["measured_ratios"]=measured_ratios
    result["measured_constraints_pass"]=all(WINDOWS[k][0]<=n<=WINDOWS[k][1] for k,n in counts.items()) and all(
        measured_h[p]/measured_h[n]>=floor for p,n,floor in pairs if p in measured_h and n in measured_h)
    return result

def raw_domain_volume(path):
    """Sum the signed volumes of boundary face fans; internal faces cancel exactly."""
    import h5py
    import numpy as np
    from cut_fluent_cells import bounds, read_id_blocks
    total=0.
    with h5py.File(path) as handle:
        mesh=handle["meshes/1"]
        nf=int(max(mesh["faces/zoneTopology/maxId"]))
        nn=int(max(mesh["nodes/zoneTopology/maxId"]))
        primary=read_id_blocks(mesh["faces/c0"],nf,np.int64)
        secondary=read_id_blocks(mesh["faces/c1"],nf,np.int64)
        xyz=read_id_blocks(mesh["nodes/coords"],nn,float,3)
        for block in mesh["faces/nodes"].values():
            first,last=bounds(block)
            boundary=(primary[first:last+1]>0)^(secondary[first:last+1]>0)
            if not boundary.any():
                continue
            counts=block["nnodes"][:].astype(np.int64)
            offsets=np.r_[0,counts.cumsum()]
            for start in range(0,len(counts),20000):
                end=min(len(counts),start+20000)
                keep=boundary[start:end]
                if not keep.any():
                    continue
                n=counts[start:end]
                nodes=block["nodes"][offsets[start]:offsets[end]]
                starts=offsets[start:end]-offsets[start]
                for m in np.unique(n[keep]):
                    indices=np.flatnonzero(keep & (n==m))
                    ring=xyz[nodes[starts[indices,None]+np.arange(m)]]
                    center=ring.mean(axis=1)
                    q=ring-center[:,None,:]
                    normals=np.cross(q,np.roll(q,-1,axis=1)).sum(axis=1)
                    sign=np.where(primary[first+start+indices]>0,-1.,1.)
                    total+=np.einsum("ij,ij,i->",center,normals,sign)/6
    if not math.isfinite(total) or total<=0:
        raise ValueError(f"Invalid signed volume from native mesh boundary: {path}")
    return float(total)
