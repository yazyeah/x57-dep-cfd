"""Improve skinny prism bases inside named CAD patches with locked seams and feature edges."""
import argparse
import json
from pathlib import Path

import numpy as np
from meshlib import mrmeshpy as mr, mrmeshnumpy as mn
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from p2_geometry_io import TYPES, WALLS, indices, save_patches, stl_triangles
from verify_p2_cad_shell import geom, halo, quality, verify
from retessellate_prism_cap import improve as flip_diagonals
from repair_p2_native_cap_slivers import GEO, probes


def improve(tri):
    verts, face = indices(tri)
    original = mn.meshFromFacesVerts(face, verts)
    mesh = mn.meshFromFacesVerts(face, verts)
    for tolerance in (.000025, .00006, .0001):
        coords, faces = geom(mesh)
        q = quality(coords[faces])
        if not np.any(q < .14):
            break
        region = halo(faces, q < .14, 1)
        sharp = mr.findCreaseEdges(mesh.topology, mesh.points, np.deg2rad(25.))
        flips = mr.DeloneSettings()
        flips.region = region
        flips.notFlippable = sharp
        flips.maxAngleChange = .14
        flips.maxDeviationAfterFlip = tolerance
        mr.makeDeloneEdgeFlips(mesh, flips, 8)
        dec = mr.DecimateSettings()
        dec.region = region
        dec.notFlippable = sharp
        dec.touchBdVerts = False
        dec.touchNearBdEdges = False
        dec.collapseNearNotFlippable = False
        dec.optimizeVertexPos = False
        dec.preventNormalFlips = True
        dec.maxError = tolerance
        dec.maxEdgeLen = .003
        dec.tinyEdgeLength = tolerance
        dec.criticalTriAspectRatio = 14.
        dec.maxTriangleAspectRatio = 25.
        dec.maxAngleChange = .14
        dec.packMesh = False
        mr.decimateMesh(mesh, dec)
    coords, faces = geom(mesh)
    result = coords[faces]
    q0, q1 = quality(tri), quality(result)
    deviation = float(np.sqrt(mr.findMaxDistanceSq(original, mesh)))
    observed = dict(faces_before=len(tri), faces_after=len(result), below_010_before=int(sum(q0 < .10)),
                    below_010_after=int(sum(q1 < .10)), min_shape_before=float(q0.min()),
                    min_shape_after=float(q1.min()), deviation_m=deviation)
    if deviation > .0003 or sum(q1 < .10) >= sum(q0 < .10) or q1.min() < min(.009, q0.min()):
        observed["retained_original"] = True
        return tri, observed
    return result, observed


def boundary_segments(triangles):
    vertices, faces = indices(triangles)
    edge = np.sort(np.stack((faces, np.roll(faces, -1, axis=1)), axis=-1).reshape(-1, 2), axis=1)
    edges, counts = np.unique(edge, axis=0, return_counts=True)
    if np.any(counts > 2):
        raise ValueError('Nonmanifold edge in candidate patch')
    return {tuple(pair.ravel()) for pair in vertices[edges[counts == 1]]}


def condition_components(triangles):
    verts, faces = indices(triangles)
    oldq = quality(triangles)
    active = np.isin(faces, np.unique(faces[oldq < .14])).any(axis=1)
    if not active.any():
        return triangles, dict(components=0, accepted=0)
    cluster = faces[active]
    ids = np.repeat(np.arange(len(cluster)), 3)
    incidence = coo_matrix((np.ones(len(ids), dtype='i4'), (ids, cluster.ravel())),
                           shape=(len(cluster),len(verts))).tocsr()
    count, labels = connected_components(incidence @ incidence.T, directed=False)
    selected = np.flatnonzero(active)
    patches = [triangles[~active]]
    accepted = 0
    largest_deviation = 0.
    lows, highs = triangles.min(axis=1), triangles.max(axis=1)
    for n in range(count):
        group = selected[labels == n]
        old = triangles[group]
        new, evidence = improve(old)
        if (not evidence.get('retained_original') and quality(new).min() >= max(.010, quality(old).min() * .8)
                and boundary_segments(old) == boundary_segments(new)):
            nearby = np.all(lows < new.max(axis=(0, 1)) + .0003, axis=1) & np.all(highs > new.min(axis=(0, 1)) - .0003, axis=1)
            nearby[group] = False
            union_v, union_f = indices(np.concatenate((new, triangles[nearby])))
            union_mesh = mn.meshFromFacesVerts(union_f, union_v)
            if mr.findSelfCollidingTrianglesBS(union_mesh).count():
                patches.append(old)
                continue
            patches.append(new)
            accepted += 1
            largest_deviation = max(largest_deviation, evidence['deviation_m'])
        else:
            patches.append(old)
    return np.concatenate(patches), dict(components=count, accepted=accepted, max_deviation_m=largest_deviation)


def main(source, target, components):
    patches = {name: stl_triangles(source / (name + ".stl")) for name in TYPES}
    report = {}
    for name in WALLS:
        patches[name], report[name] = (condition_components if components else improve)(patches[name])
        old = patches[name]
        new = flip_diagonals(old, name, all_prism_bases=True)
        old_q, new_q = quality(old), quality(new)
        if new_q.min() >= old_q.min() - 1.e-8 and sum(new_q < .10) < sum(old_q < .10):
            patches[name] = new
        report[name]["final_below_010"] = int(sum(quality(patches[name]) < .10))
        report[name]["final_minimum_shape"] = float(quality(patches[name]).min())
        print(name, report[name], flush=True)
    save_patches(target, patches)
    verify(target, True)
    root = probes(patches["wall_wing"], GEO / "p2_stair_coarse_root33b/root_trailing_edge_qa.json", "rays_detail")
    tube = patches["wall_nacelles"]
    tube = tube[(tube[:, :, 1].min(1) < .11) & (abs(tube.mean(1)[:, 2] - 3.769) < .15)]
    nac = probes(tube, GEO / "p2_stair_coarse_hlp6cad2/hlp6_aft_qa.json", "samples")
    for name, test in [("wing_root", root), ("nacelle_6", nac)]:
        if test["missing_or_odd"] or test["max_cad_envelope_error_m"] > .001:
            raise ValueError((name, test))
        report[name] = test
    (target / "prism_base_shape_audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--components", action="store_true")
    args = parser.parse_args()
    main(args.source, args.target, args.components)

