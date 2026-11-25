"""Group an offline Fluent orthogonality diagnosis by native topology and prism depth."""
from pathlib import Path

import h5py
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

from cut_fluent_cells import bounds, read_id_blocks, zones
from mesh_region_budget import native_flags


def cell_groups(path, quality, signed_volume, face_quality=None, neighbor_quality=None):
    """Arrays are 1-based. Each cell is counted once in every applicable grouping."""
    with h5py.File(path) as h:
        mesh = h["meshes/1"]
        n = len(quality) - 1
        nface = int(max(mesh["faces/zoneTopology/maxId"]))
        owner = read_id_blocks(mesh["faces/c0"], nface, np.int32)
        neighbor = read_id_blocks(mesh["faces/c1"], nface, np.int32)
        ctype = np.zeros(n + 1, dtype=np.int16)
        for block in mesh["cells/ctype"].values():
            lo, hi = bounds(block)
            ctype[lo:hi + 1] = (block["cell-types"][:]
                                 if "cell-types" in block else int(np.asarray(block.attrs["elementType"]).item()))
        wall_ranges = {k: v for k, v in zones(mesh["faces/zoneTopology"]).items() if k.startswith("wall_")}
        part_paths = []
        h.visit(lambda name: part_paths.append(name) if "partition" in name.lower() else None)
        # CFF exports may omit the MPI partition map after reassembling the mesh.
        partition = None
        partition_path = None
        for candidate in ("meshes/1/cells/partition", "meshes/1/cells/partitionId", "meshes/1/cells/partition-ids"):
            if candidate not in h:
                continue
            data = h[candidate]
            if isinstance(data, h5py.Dataset) and data.size == n and data.dtype.kind in "iu":
                partition = np.r_[-1, data[:].ravel()]
                partition_path = candidate
                break
        cell_flags = "special/boundary_layer_flags/cells"
        face_flags = "special/boundary_layer_flags/faces"
        prism = native_flags(h[cell_flags], n) if cell_flags in h else None
        caps = native_flags(h[face_flags], nface) if face_flags in h else None

    def counts(indices):
        ids = np.asarray(indices, dtype=np.int64)
        result = {"count": len(ids), "nonpositive_volume": int(np.sum(signed_volume[ids] <= 0)),
                  "proxy_below_005": int(np.sum(quality[ids] < .05)),
                  "proxy_below_010": int(np.sum(quality[ids] < .10))}
        if len(ids):
            result["proxy_minimum"] = float(quality[ids].min())
        if face_quality is not None and neighbor_quality is not None:
            qf, qn = face_quality[ids] < .05, neighbor_quality[ids] < .05
            result["below_005_face_only"] = int(np.sum(qf & ~qn))
            result["below_005_neighbor_only"] = int(np.sum(qn & ~qf))
            result["below_005_both"] = int(np.sum(qf & qn))
        return result

    active = np.arange(1, n + 1)
    native_names = {1:"triangle", 2:"tetrahedron", 3:"quadrilateral", 4:"hexahedron",
                    5:"pyramid", 6:"wedge", 7:"polyhedron"}
    results = {"native_shape": {native_names.get(int(i), f"type_{i}"): counts(active[ctype[1:] == i])
                                for i in np.unique(ctype[1:])},
               "partition_map": partition_path, "partition_candidates": part_paths}
    if partition is not None:
        results["by_native_partition"] = {str(i): counts(active[partition[1:] == i])
                                        for i in np.unique(partition[1:])}
    walladj = np.zeros(n + 1, dtype=bool)
    by_wall = {}
    seeds = []
    seed_wall = []
    for i, (name, (lo, hi)) in enumerate(wall_ranges.items()):
        faces = np.arange(lo, hi + 1)
        cells = np.maximum(owner[faces], neighbor[faces])
        cells = cells[cells > 0]
        walladj[cells] = True
        by_wall[name] = counts(np.unique(cells))
        if prism is not None and caps is not None:
            base = faces[caps[faces]]
            cells = np.maximum(owner[base], neighbor[base])
            cells = cells[prism[cells]]
            seeds.extend(cells)
            seed_wall.extend([i] * len(cells))
    results["touches_wall"] = by_wall
    results["beyond_first_wall_cell"] = counts(active[~walladj[1:]])
    if prism is None or caps is None:
        results["prism_depth_status"] = "CFF does not contain the native cell and face boundary-layer flags."
        return results

    pids = np.flatnonzero(prism)
    results["native_prism"] = counts(pids)
    results["core_hex"] = counts(active[(ctype[1:] == 4) & ~prism[1:]])
    results["nonprism_nonhex"] = counts(active[(ctype[1:] != 4) & ~prism[1:]])
    if not len(pids):
        return results
    loc = np.full(n + 1, -1, np.int32)
    loc[pids] = np.arange(len(pids))
    linked = caps & prism[owner] & prism[neighbor]
    left, right = loc[owner[linked]], loc[neighbor[linked]]
    graph = coo_matrix((np.ones(2 * len(left), np.uint8),
                        (np.r_[left, right], np.r_[right, left])),
                       shape=(len(pids), len(pids))).tocsr()
    nc, component = connected_components(graph, directed=False)
    seeds = np.asarray(seeds, dtype=np.int64)
    seed_wall = np.asarray(seed_wall, dtype=np.int16)
    seed_components = component[loc[seeds]]
    num_roots = np.bincount(seed_components, minlength=nc)
    degrees = np.diff(graph.indptr)
    branched = np.bincount(component[degrees > 2], minlength=nc) > 0
    good = (num_roots == 1) & ~branched
    usable = good[component]
    results["unassigned_or_branched_prisms"] = counts(pids[~usable])
    root_wall = np.full(nc, -1, np.int16)
    root_wall[seed_components] = seed_wall
    by_base = {}
    for i, name in enumerate(wall_ranges):
        by_base[name] = counts(pids[usable & (root_wall[component] == i)])
    results["by_connected_column_wall"] = by_base
    seedloc = loc[seeds[good[seed_components]]]
    if len(seedloc):
        distance = dijkstra(graph, directed=True, indices=seedloc, unweighted=True, min_only=True)
        local = np.flatnonzero(usable & np.isfinite(distance))
        depths = distance[local].astype(np.int32) + 1
        results["by_unambiguous_prism_depth"] = {str(k): counts(pids[local[depths == k]]) for k in np.unique(depths)}
    return results

