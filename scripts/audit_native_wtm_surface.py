"""Measure the actual Fluent surface against the CAD witnesses before volume generation."""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np

from cut_fluent_cells import bounds, read_id_blocks, zones
from repair_p2_native_cap_slivers import GEO, probes
from verify_p2_cad_shell import sections


def read_surfaces(filename):
    patches = {}
    with h5py.File(filename) as h5:
        mesh = h5["meshes/1"]
        coords = read_id_blocks(mesh["nodes/coords"], max(mesh["nodes/zoneTopology/maxId"]), float, 3)
        for zone, (first, last) in zones(mesh["faces/zoneTopology"]).items():
            if not zone.startswith("wall_"):
                continue
            blocks = []
            for group in mesh["faces/nodes"].values():
                lo, hi = bounds(group)
                begin, end = max(first, lo) - lo, min(last, hi) + 1 - lo
                if end <= begin:
                    continue
                sizes = group["nnodes"][:].astype(int)
                offsets = np.r_[0, sizes.cumsum()]
                if np.any(sizes[begin:end] != 3):
                    raise ValueError(f"Surface at {zone} contains non-triangle faces.")
                ids = group["nodes"][offsets[begin]:offsets[end]]
                blocks.append(coords[ids.reshape(-1, 3)])
            patches[zone] = np.concatenate(blocks)
    return patches


def measure(filename, level="coarse", wall_suffix=""):
    native = read_surfaces(filename)
    names = ("wall_wing", "wall_nacelles", "wall_fuselage", "wall_sponson", "wall_empennage")
    mapping = {name: name + wall_suffix for name in names}
    patches = {name: native[actual] for name, actual in mapping.items()}
    wing, tail, hinge, gaps = sections(patches)
    errors = [abs(row["cad_gap_m"] - row["surface_gap_m"]) for row in gaps
              if row["cad_gap_m"] is not None and row["surface_gap_m"] is not None]
    mismatch = sum((row["cad_gap_m"] is None) != (row["surface_gap_m"] is None) for row in gaps)
    nacelle = patches["wall_nacelles"]
    local = nacelle[(nacelle[:, :, 1].min(1) < .11) & (abs(nacelle.mean(1)[:, 2] - 3.769) < .15)]
    root = probes(patches["wall_wing"], GEO / "p2_stair_coarse_root33b/root_trailing_edge_qa.json", "rays_detail")
    hlp = probes(local, GEO / "p2_stair_coarse_hlp6cad2/hlp6_aft_qa.json", "samples")
    tail_tip = probes(patches["wall_empennage"], GEO / "p2_stair_coarse_tail5c/outer_tail_tip_qa.json", "probes")
    within_gap = max(errors) <= .005 if level == "fine" else max(errors) < .003
    wing_error = max(row["error_m"] for row in wing)
    tail_error = max(row["max_vertical_error_m"] for row in tail)
    passed = (mismatch == 0 and within_gap and wing_error <= .001 and tail_error <= .0008
              and not root["missing_or_odd"] and not hlp["missing_or_odd"]
              and not tail_tip["missing_or_odd"] and tail_tip["max_cad_envelope_error_m"] <= .001
              and root["max_cad_envelope_error_m"] <= .001 and hlp["max_cad_envelope_error_m"] <= .001)
    return dict(source=str(filename.resolve()), passed=bool(passed), wing54_m=wing_error,
                tail5_m=tail_error, hinge_stations=hinge, max_gap_error_81_m=max(errors),
                gap_mismatches=mismatch, wing_root_234=root, nacelle_294=hlp, outer_tail_tip_652=tail_tip, level=level,
                native_wall_names=mapping, face_counts={zone: len(tris) for zone, tris in patches.items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mesh", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--level", choices=["coarse", "medium", "fine"], default="coarse")
    parser.add_argument("--wall-suffix", default="", help="Exact suffix on the five audited native wall names.")
    args = parser.parse_args()
    report = measure(args.mesh, args.level, args.wall_suffix)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)
    raise SystemExit(0 if report["passed"] else 1)

