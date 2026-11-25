"""Measure a signed-off C21 prism-only CFF before selecting a domain for core meshing."""
import hashlib
import json
import re
from pathlib import Path

import h5py
import numpy as np

from control_gate import ControlGate
from cut_fluent_cells import bounds, read_id_blocks
from p2_geometry_io import TYPES

ROOT = Path(__file__).resolve().parents[1]
PRISMS = ROOT / "02_mesh/coarse/f_scoped_prisms_only_21"
ARTIFICIAL = re.compile(r"prism[-_](?:cap|side)(?:[-_.][A-Za-z0-9_-]+)*", re.I)


def check_control():
    rc = ControlGate().check()["exit_code"]
    if rc:
        raise SystemExit(rc)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def classify(name, zone_type, neighbors):
    """Return whether each face borders the unfilled core and any ambiguous topology."""
    reason = None
    physical = name if name in TYPES else None
    if not physical:
        match = re.fullmatch(r"(.+?)[-_]quad(?:[-_]\d+)?", name, re.I)
        if match and match[1] in TYPES:
            physical = match[1]
    if physical:
        use = neighbors == 0
        if TYPES[physical][1] != zone_type or np.any(neighbors > 1):
            reason = "physical zone has unexpected type or adjacency"
    elif ARTIFICIAL.fullmatch(name):
        use = neighbors == 1
        if np.any(neighbors == 0):
            reason = "unattached artificial faces cannot be assigned to the core"
    else:
        use = np.zeros(len(neighbors), dtype=bool)
        if np.any(neighbors < 2):
            reason = "unidentified exposed face zone"
    if reason is None and use.any() and not use.all():
        reason = "core includes only part of this zone; whole-zone selection is ambiguous"
    return use, reason


def reference_geometry(mesh):
    """Read the native, explicitly tagged CAD and wrapped diagnostic geometry objects."""
    if "settings/TGrid Variables" not in mesh:
        return {}
    objects = [line for line in mesh["settings/TGrid Variables"][0].decode().splitlines() if line.startswith("(objects ")]
    if len(objects) != 1:
        return {}
    groups = re.findall(r"\((origin-[^\s()]+|wrapped_diagnostic) (?:dead|fluid) \d+ \(([\d ]+)\) \([^()]*\) geom\b", objects[0])
    return {int(zid): name for name, zone_ids in groups for zid in zone_ids.split()}


def scan(path, registered=None):
    rows, issues, edges, chosen = [], [], [], []
    seed_reference = set()
    if registered is not None:
        with h5py.File(registered, "r") as seed:
            owners = reference_geometry(seed)
            top = seed["meshes/1/faces/zoneTopology"]
            original_names = top["name"][0].decode().rstrip(";").split(";")
            seed_reference = {(owners[int(zid)], n) for zid, n in zip(top["id"][:], original_names, strict=True)
                              if int(zid) in owners and n not in TYPES}
    with h5py.File(path, "r") as mesh:
        owners = reference_geometry(mesh)
        faces = mesh["meshes/1/faces"]
        top = faces["zoneTopology"]
        names = top["name"][0].decode().rstrip(";").split(";")
        missing = set(TYPES) - set(names)
        if missing:
            issues.append("missing physical boundaries: " + ", ".join(sorted(missing)))
        nf = int(max(top["maxId"]))
        neighbor_count = (read_id_blocks(faces["c0"], nf, np.int64) > 0).astype(np.int8)
        neighbor_count += (read_id_blocks(faces["c1"], nf, np.int64) > 0).astype(np.int8)
        mask = np.zeros(nf + 1, dtype=bool)
        nnodes = np.zeros(nf + 1, dtype=np.int64)
        for name, zid, typ, lo, hi in zip(names, top["id"][:], top["zoneType"][:], top["minId"][:], top["maxId"][:], strict=True):
            part = slice(int(lo), int(hi) + 1)
            adjacent = neighbor_count[part]
            geom = owners.get(int(zid))
            from_reference = (geom, name) in seed_reference and not np.any(adjacent)
            if from_reference:
                use, reason = np.zeros(len(adjacent), dtype=bool), None
            else:
                use, reason = classify(name, int(typ), adjacent)
            mask[part] = use
            rows.append(dict(name=name, id=int(zid), type=int(typ), total=len(use), core_faces=int(use.sum()),
                             reference_geometry_object=geom if from_reference else None,
                             no_cell=int(np.sum(adjacent == 0)), one_cell=int(np.sum(adjacent == 1)),
                             two_cells=int(np.sum(adjacent == 2))))
            if reason:
                issues.append(f"{name}: {reason}")
            elif use.any():
                chosen.append(name)
        for block in faces["nodes"].values():
            lo, hi = bounds(block)
            counts = block["nnodes"][:].astype(np.int64)
            nnodes[lo:hi+1] = counts
            selected = mask[lo:hi+1]
            if not selected.any():
                continue
            offsets = np.r_[0, np.cumsum(counts)]
            nodes = block["nodes"][:]
            for order in np.unique(counts[selected]):
                if order < 3:
                    raise ValueError("Invalid face with fewer than 3 nodes")
                at = offsets[:-1][selected & (counts == order)]
                cycle = nodes[at[:, None] + np.arange(order)]
                pairs = np.stack([cycle, np.roll(cycle, -1, axis=1)], axis=2).reshape(-1, 2)
                edges.append(np.sort(pairs, axis=1))
        for row, lo, hi in zip(rows, top["minId"][:], top["maxId"][:], strict=True):
            part = slice(int(lo), int(hi) + 1)
            orders = nnodes[part][mask[part]]
            count = int(np.sum(orders != 3))
            row["core_quads"] = int(np.sum(orders == 4))
            row["core_nontri_faces"] = count
            if count:
                issues.append(f"{row['name']}: {count} core faces require a conformal transition")
    if not edges:
        raise ValueError("No candidate core boundary")
    unique, incidences = np.unique(np.concatenate(edges), axis=0, return_counts=True)
    open_edges = int(np.sum(incidences == 1))
    nonmanifold = int(np.sum(incidences > 2))
    collapsed = int(np.sum(unique[:, 0] == unique[:, 1]))
    if open_edges or nonmanifold or collapsed:
        issues.append(f"core-boundary edges: {open_edges} open, {nonmanifold} nonmanifold, {collapsed} collapsed")
    return dict(zones=rows, candidate_whole_zone_names=chosen, core_faces=int(mask.sum()), open_edges=open_edges,
                nonmanifold_edges=nonmanifold, collapsed_edges=collapsed, blockers=issues,
                triangle_domain_candidate=not issues)


def main():
    check_control()
    try:
        checkpoint = PRISMS / "prism_checkpoint.json"
        if not checkpoint.is_file():
            raise ValueError("C21 native prism checkpoint report is not available")
        report = json.loads(checkpoint.read_text(encoding="utf-8"))
        path = PRISMS / "prisms_only.msh.h5"
        if report.get("ready_for_core_fill") is not True or Path(report["path"]).resolve() != path or report["sha256"] != sha(path):
            raise ValueError("C21 five-wall readiness, checkpoint identity or SHA-256 is unconfirmed")
        cfg = json.loads((PRISMS / "mesh_config.json").read_text(encoding="utf-8"))
        field = Path(cfg["size_field_path"]).resolve()
        if not field.is_relative_to(ROOT) or sha(field) != cfg["size_field_sha256"]:
            raise ValueError("Registered BOI size-field hash or location changed")
        registered = Path(cfg["region_registration_checkpoint"]).resolve()
        if not registered.is_relative_to(ROOT) or sha(registered) != cfg["region_registration_checkpoint_sha256"]:
            raise ValueError("Registration CFF hash or location changed")
        measured = scan(path, registered)
        measured.update(source=str(path), source_sha256=report["sha256"], size_field=str(field),
                        size_field_sha256=cfg["size_field_sha256"], production_signed_off=False)
        print(json.dumps(measured, indent=2))
        if not measured["triangle_domain_candidate"]:
            raise SystemExit(2)
    finally:
        check_control()


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit(str(error))
