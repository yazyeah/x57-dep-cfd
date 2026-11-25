"""Cut the actual Fluent face connectivity and retain parent fluid cell IDs."""
from collections import defaultdict
from pathlib import Path
import argparse
import h5py
import numpy as np


def bounds(obj):
    return tuple(int(np.asarray(obj.attrs[k]).item()) for k in ("minId", "maxId"))


def read_id_blocks(group, total, dtype, width=None):
    result = np.zeros((total + 1,) if width is None else (total + 1, width), dtype=dtype)
    for obj in group.values():
        lo, hi = bounds(obj)
        result[lo:hi + 1] = obj[:].reshape(result[lo:hi + 1].shape)
    return result


def zones(topology):
    names = topology["name"][0].decode().rstrip(";").split(";")
    return {name: (int(lo), int(hi)) for name, lo, hi in
            zip(names, topology["minId"], topology["maxId"], strict=True)}


def polygon_loops(segments):
    """Undirected cell-face intersections must form closed cycles."""
    edges = defaultdict(set)
    for a, b in segments:
        if a != b:
            edges[a].add(b)
            edges[b].add(a)
    if any(len(v) != 2 for v in edges.values()):
        raise ValueError("Non-manifold cut. Choose a slightly displaced plane and record its coordinate.")
    while edges:
        first = min(edges)
        previous, current = None, first
        loop = []
        while True:
            loop.append(current)
            adjacent = edges[current]
            successor = next(v for v in sorted(adjacent) if v != previous)
            previous, current = current, successor
            if current == first:
                break
        for point in loop:
            del edges[point]
        yield loop


def cut_mesh(mesh_path, axis, value, max_open_cells=0):
    """max_open_cells > 0 drops at most that many cells whose cut is not a closed polygon (returned as
    open_cell_ids); the default keeps the strict closed-cycle requirement."""
    kept = [i for i in range(3) if i != axis]
    segments = defaultdict(list)
    with h5py.File(mesh_path) as file:
        mesh = file["meshes/1"]
        count = int(max(mesh["nodes/zoneTopology/maxId"]))
        xyz = read_id_blocks(mesh["nodes/coords"], count, np.float64, 3)
        nf = int(max(mesh["faces/zoneTopology/maxId"]))
        owners = read_id_blocks(mesh["faces/c0"], nf, np.int64)
        neighbors = read_id_blocks(mesh["faces/c1"], nf, np.int64)
        for group in mesh["faces/nodes"].values():
            lo, hi = bounds(group)
            sizes = group["nnodes"][:].astype(np.int64)
            offsets = np.r_[0, np.cumsum(sizes)]
            for start in range(0, len(sizes), 25000):
                end = min(len(sizes), start + 25000)
                ids = group["nodes"][offsets[start]:offsets[end]]
                idx = offsets[start:end] - offsets[start]
                vals = xyz[ids, axis]
                active = (np.minimum.reduceat(vals, idx) <= value) & (np.maximum.reduceat(vals, idx) > value)
                for local in np.flatnonzero(active):
                    face_id = lo + start + local
                    f = ids[idx[local]:idx[local] + sizes[start + local]]
                    q = xyz[f]
                    side = q[:,axis] > value
                    ia = np.flatnonzero(side != np.roll(side, -1))
                    ib = (ia + 1) % len(f)
                    # Use canonical global edge direction for identical shared endpoints.
                    swap = f[ia] > f[ib]
                    a = q[np.where(swap, ib, ia)]
                    b = q[np.where(swap, ia, ib)]
                    t = (value - a[:,axis]) / (b[:,axis] - a[:,axis])
                    points = (a[:,kept] + t[:,None] * (b[:,kept] - a[:,kept])).round(12)
                    if len(points) > 2:
                        points = points[np.argsort(points[:,np.argmax(np.ptp(points,axis=0))])]
                    pairs = [(tuple(p), tuple(q)) for p,q in points.reshape(-1,2,2) if np.any(p != q)]
                    for cell in (owners[face_id], neighbors[face_id]):
                        if cell:
                            segments[int(cell)].extend(pairs)
    coords, cell_ids, offsets = [], [], [0]
    area = 0.0
    open_cells = []
    for cell, pairs in segments.items():
        try:
            loops = list(polygon_loops(pairs))
        except ValueError:
            if len(open_cells) >= max_open_cells:
                raise
            open_cells.append(int(cell))
            continue
        for loop in loops:
            a = np.array(loop)
            # Shift origin for thin near-wall polygons.
            a -= a[0].copy()
            signed_area = 0.5 * np.sum(a[:,0] * np.roll(a[:,1],-1) - a[:,1] * np.roll(a[:,0],-1))
            if signed_area == 0:
                continue
            coords.extend(loop if signed_area > 0 else reversed(loop))
            offsets.append(len(coords))
            cell_ids.append(cell)
            area += abs(signed_area)
    if not cell_ids:
        raise ValueError("Plane did not cut a fluid cell.")
    return dict(xy=np.asarray(coords), offsets=np.asarray(offsets), cell_ids=np.asarray(cell_ids),
                axis=axis, coordinate_m=value, projected_axes=np.array(kept), fluid_area_m2=area,
                open_cell_ids=np.asarray(open_cells, dtype=np.int64))


def robust_cut(mesh_path, axis, value):
    """cut_mesh with the remedy its non-manifold error asks for: displace the plane slightly (up to 1 mm) and
    record the coordinate used; if a sliver/spinner cell stays open at every shift, drop at most 3 such cells
    at the requested plane and record them (open_cell_ids). Same policy as native_flow_data.intersect."""
    shifts = (0., 1.e-6, -1.e-6, 1.e-5, -1.e-5, 1.e-4, -1.e-4, 5.e-4, -5.e-4, 1.e-3, -1.e-3)
    for shift in shifts:
        try:
            result = cut_mesh(mesh_path, axis, value + shift)
            break
        except ValueError as exc:
            if "Non-manifold" not in str(exc):
                raise
    else:
        result = cut_mesh(mesh_path, axis, value, max_open_cells=3)
    result["requested_coordinate_m"] = value
    result["plane_displacement_m"] = result["coordinate_m"] - value
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("mesh",type=Path)
    ap.add_argument("axis",choices="xyz")
    ap.add_argument("coordinate",type=float)
    ap.add_argument("output",type=Path)
    args=ap.parse_args()
    dataset=cut_mesh(args.mesh,"xyz".index(args.axis),args.coordinate)
    np.savez_compressed(args.output, **dataset)
    print(f"{len(dataset['cell_ids'])} fluid polygons, area {dataset['fluid_area_m2']:.12g} m2")
