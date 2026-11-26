"""Surface-refined shell for the surface-refinement study (brief: refine the surface AND the volume mesh).

The volume ladder shares the coarse CAD tessellation (01_geometry/p2_coarse_prism_base_patches). The finer CAD
re-tessellations (p2_medium/p2_fine) cannot be inflated with the ladder's prism recipe: on 2026-11-25 both
gave "No cell zones (check for holes in boundary mesh)" after prism stair-stepping, and on 2026-11-24 every
medium-shell attempt had inverted cells at the outboard HLP nacelle junction. This script therefore refines the
SURFACE MESH on the identical faceted geometry: every wall edge longer than a threshold is split at its planar
midpoint (red/green/blue refinement, conformal across zones). Edges shared with the symmetry plane, the runway
ground or the far field are never split, so those zones stay byte-identical. Vertices never move: the wall
geometry is exactly the coarse facet geometry, only the wall face size (and so the prism-cap / near-wall cell
lateral size) is reduced. The threshold is chosen for a requested wall-face ratio; the result is validated by
the same P2 shell gate (verify_p2_cad_shell.verify: self intersections, open loops, multi-fan vertices,
zero-area facets, CAD wing/tail/gap sections) and written to 01_geometry/p2_<label>_prism_base_patches.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from p2_geometry_io import GEO, TYPES, WALLS, indices, save_patches, stl_triangles  # noqa: E402
from verify_p2_cad_shell import quality, verify  # noqa: E402

SRC = GEO / "p2_coarse_prism_base_patches"


def edge_table(f):
    e = np.sort(f[:, [[0, 1], [1, 2], [2, 0]]].reshape(-1, 2), axis=1)
    u, inv = np.unique(e, axis=0, return_inverse=True)
    return u, inv.reshape(-1, 3)


def split_faces(v, f, mid):
    """mid[i, k] = new vertex on edge k (0:ab, 1:bc, 2:ca) of face i, or -1. Keeps the face orientation."""
    out, parent = [], []
    for i, ((a, b, c), m) in enumerate(zip(f, mid)):
        n = int((m >= 0).sum())
        if n == 0:
            new = [(a, b, c)]
        elif n == 3:
            m0, m1, m2 = m
            new = [(a, m0, m2), (m0, b, m1), (m2, m1, c), (m0, m1, m2)]
        else:
            # rotate so that edge 0 is marked (n == 1) or edge 2 is the unmarked one (n == 2)
            p, q = [a, b, c], list(m)
            for _ in range(3):
                if (n == 1 and q[0] >= 0) or (n == 2 and q[2] < 0):
                    break
                p, q = p[1:] + p[:1], q[1:] + q[:1]
            a_, b_, c_ = p
            if n == 1:
                new = [(a_, q[0], c_), (q[0], b_, c_)]
            else:
                m0, m1 = q[0], q[1]
                first = [(m0, b_, m1), (a_, m0, m1), (a_, m1, c_)]
                second = [(m0, b_, m1), (a_, m0, c_), (m0, m1, c_)]
                shape = lambda tris: quality(v[np.array(tris)]).min()
                new = first if shape(first) >= shape(second) else second
        out.extend(new)
        parent.extend([i] * len(new))
    return np.array(out, dtype=np.int64), np.array(parent, dtype=np.int64)


FROZEN = []   # wall zones kept at the source tessellation (--frozen); their edges are protected like the far field


def refine(patches, threshold):
    names = list(patches)
    zone = np.concatenate([np.full(len(patches[k]), i) for i, k in enumerate(names)])
    v, f = indices(np.concatenate([patches[k] for k in names]))
    v = v.astype(np.float64)
    f = f.astype(np.int64)
    wall = np.isin(np.array(names)[zone], WALLS) & ~np.isin(np.array(names)[zone], FROZEN)
    u, inv = edge_table(f)
    touches_other = np.zeros(len(u), dtype=bool)
    touches_other[inv[~wall].ravel()] = True
    length = np.linalg.norm(v[u[:, 0]] - v[u[:, 1]], axis=1)
    mark = (length > threshold) & ~touches_other
    ids = np.full(len(u), -1, dtype=np.int64)
    ids[mark] = len(v) + np.arange(mark.sum())
    v = np.vstack([v, 0.5 * (v[u[mark, 0]] + v[u[mark, 1]])])
    nf, parent = split_faces(v, f, ids[inv])
    tri = v[nf].astype(np.float32)
    nz = zone[parent]
    return {k: tri[nz == i] for i, k in enumerate(names)}, dict(split_edges=int(mark.sum()),
                                                               wall_edges=int((~touches_other).sum()),
                                                               max_wall_edge_m_before=float(length[~touches_other].max()))


def predicted_faces(patches, threshold):
    names = list(patches)
    zone = np.concatenate([np.full(len(patches[k]), i) for i, k in enumerate(names)])
    v, f = indices(np.concatenate([patches[k] for k in names]))
    v = v.astype(np.float64)
    wall = np.isin(np.array(names)[zone], WALLS) & ~np.isin(np.array(names)[zone], FROZEN)
    u, inv = edge_table(f.astype(np.int64))
    other = np.zeros(len(u), dtype=bool)
    other[inv[~wall].ravel()] = True
    mark = (np.linalg.norm(v[u[:, 0]] - v[u[:, 1]], axis=1) > threshold) & ~other
    return int((1 + mark[inv].sum(1))[wall].sum())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("label", help="short level label without underscores, e.g. subdivA")
    ap.add_argument("--wall-face-ratio", type=float, default=2.0)
    # 2026-11-26: subdivA (2.0x) and subdivB (1.5x) volume meshes kept a zero-OQ cell even after boundary repair;
    # the known failure site is the HLP nacelle/wing junction, so the nacelles can be kept at the source facets.
    ap.add_argument("--frozen", nargs="*", default=[], help="wall zones not subdivided, e.g. wall_nacelles")
    args = ap.parse_args()
    FROZEN[:] = args.frozen
    if "_" in args.label:
        raise SystemExit("label must not contain '_' (surfref folder naming)")
    patches = {k: stl_triangles(SRC / (k + ".stl")) for k in TYPES}
    base = sum(len(patches[k]) for k in WALLS)
    target = args.wall_face_ratio * base
    lo, hi = 1e-4, 5.0           # threshold [m]; face count decreases with the threshold
    for _ in range(60):
        mid = np.sqrt(lo * hi)
        if predicted_faces(patches, mid) > target:
            lo = mid
        else:
            hi = mid
    threshold = hi
    refined, info = refine(patches, threshold)
    out = GEO / f"p2_{args.label}_prism_base_patches"
    for k in TYPES:
        if k not in WALLS and not np.array_equal(refined[k], patches[k]):
            raise ValueError(f"non-wall zone {k} changed")
    save_patches(out, refined)
    verify(out, require_gap=True)       # same P2 CAD/topology gate; writes assembled_shell_qa.json
    qa = json.loads((out / "assembled_shell_qa.json").read_text())
    walls_after = qa["wall_faces"]
    meta = dict(source_shell=str(SRC / "aircraft_domain.msh"), method="planar edge-midpoint red/green/blue "
                "subdivision of wall facets; vertices never move; symmetry/ground/far-field edges never split",
                split_threshold_edge_length_m=threshold, requested_wall_face_ratio=args.wall_face_ratio,
                wall_faces_before=base, wall_faces_after=walls_after, wall_face_ratio=walls_after / base,
                linear_surface_refinement_ratio=(walls_after / base) ** 0.5,
                min_shape_before={k: float(quality(patches[k]).min()) for k in WALLS},
                min_shape_after={k: float(quality(refined[k]).min()) for k in WALLS}, **info)
    (out / "surface_subdivision.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
