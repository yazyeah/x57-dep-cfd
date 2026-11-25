"""Fast-track P2 mesh audit, tiered quality grading and canonical publication.

Writes 02_mesh/<level>/mesh_qa.json and 02_mesh/grid_ladder_qa.json in the schema
the solver/FSI/plot pipeline already consumes. Hard gates (never relaxed):
  * licence cap and admissible cell window, positive cell volumes in the solver,
  * exactly one fluid zone and the 11 named physical boundaries,
  * solver-reloadable native mesh with a measured orthogonal-quality report,
  * grid-spacing ratios r32, r21 >= 1.10 on measured V/N (Celik 2008 minimum).
Quality tiers (recorded, best one published):
  target       solver min OQ >= 0.10 and <=1 % cells with OQ < 0.05
  accept       solver min OQ >= 0.01 (Ansys minimum) and <=1 % cells with OQ < 0.05
  last_resort  solver min OQ > 0, positive volumes and <=2 % cells with OQ < 0.05
               (run with Fluent poor-mesh numerics, see fluent_solver_worker.py)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import h5py
import numpy as np

from control_gate import atomic_write_json
from fasttrack_profile import (CAD_GAP_TOL_M, HARD_WINDOWS, LICENSE_CELL_CAP, MESH_OQ_ACCEPT, MESH_OQ_TARGET,
                               MESH_POOR_FRACTION_LASTRESORT, MESH_POOR_FRACTION_MAX, RATIO_HARD, RATIO_TARGET,
                               ROOT, TARGET_WINDOWS, in_hard_window, snapshot)

LEVELS = ("coarse", "medium", "fine")
BOUNDARIES = {"symmetry", "runway_ground", "farfield_inlet", "farfield_top", "farfield_side", "farfield_outlet",
              "wall_wing", "wall_fuselage", "wall_nacelles", "wall_sponson", "wall_empennage"}
CTYPE = {1: "triangle", 2: "tetrahedron", 3: "quadrilateral", 4: "hexahedron", 5: "pyramid", 6: "wedge", 7: "polyhedron"}
TIERS = ("target", "accept", "last_resort")
NUM = r"([+\-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+\-]?\d+)?)"


def digest(path):
    import hashlib
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def _zone_names(topology):
    raw = topology["name"][0]
    raw = raw.decode() if isinstance(raw, bytes) else str(raw)
    return [n for n in raw.rstrip(";").split(";") if n]


def mesh_inventory(mesh):
    """Counts read directly from the native CFF file (mesh or solver case)."""
    with h5py.File(mesh, "r") as f:
        m = f["meshes/1"]
        cz = m["cells/zoneTopology"]
        cells = int(np.sum(cz["maxId"][:].astype("i8") - cz["minId"][:].astype("i8") + 1))
        nodes = int(sum(ds.shape[0] for ds in m["nodes/coords"].values()))
        types = {}
        for block in m["cells/ctype"].values():
            uniform = int(np.asarray(block.attrs["elementType"]).item())
            if uniform == 0:
                values, counts = np.unique(block["cell-types"][:], return_counts=True)
            else:
                values, counts = [uniform], [int((block.attrs["maxId"] - block.attrs["minId"] + 1).item())]
            for v, c in zip(values, counts):
                key = CTYPE.get(int(v), str(v))
                types[key] = types.get(key, 0) + int(c)
        faces = [n for n in _zone_names(m["faces/zoneTopology"]) if not n.startswith("interior")]
        cell_zones = _zone_names(cz) if "name" in cz else []
        bl = None
        if "special/boundary_layer_flags/cells" in f:
            group = f["special/boundary_layer_flags/cells"]
            bl = int(sum(int(np.count_nonzero(g["data"][:])) for k, g in group.items() if k != "topology"))
    return dict(cells=cells, nodes=nodes, cell_type_counts=types, boundary_zones=faces, cell_zones=cell_zones,
                boundary_layer_cells=bl)


def _sections(text, mark):
    return re.findall(r"(?ms)^\s*X57-" + mark + r"-BEGIN\s*$(.*?)^\s*X57-" + mark + r"-END\s*$", text)


def _last_float(pattern, text):
    found = re.findall(pattern, text, re.I)
    return float(found[-1]) if found else None


def solver_quality(transcript):
    """Parse the fast-track solver session: BEFORE/AFTER quality blocks and volume statistics."""
    text = Path(transcript).read_text(encoding="utf-8", errors="replace")
    out = {"transcript": str(transcript)}
    for key in ("BEFORE", "AFTER"):
        blocks = _sections(text, key + "-QUALITY")
        out[key.lower() + "_min_oq"] = _last_float(r"Minimum Orthogonal Quality\s*=\s*" + NUM, blocks[-1]) if blocks else None
    if out["before_min_oq"] is None:  # plain verify_mesh_level reload journal
        blocks = _sections(text, "STANDARD-QUALITY")
        out["before_min_oq"] = _last_float(r"Minimum Orthogonal Quality\s*=\s*" + NUM, blocks[-1]) if blocks else None
    out["min_volume_m3"] = _last_float(r"minimum volume(?:\s*\(m3\))?:\s*" + NUM, text)
    out["negative_volume_reported"] = bool(re.search(r"(?i)error[^\n]*negative volume", text))
    out["repair_ran"] = "X57-FASTTRACK-REPAIR" in text
    out["case_written"] = bool(re.search(r"Writing \".*?_solver_ready\.cas\.h5\"", text, re.I)) or "solver_ready.cas.h5" in text
    return out


def mesher_quality(transcript):
    from complete_production_mesh import native_tail_count
    text = Path(transcript).read_text(encoding="utf-8", errors="replace")
    return dict(transcript=str(transcript),
                min_oq=_last_float(r"Minimum Orthogonal Quality\s*=\s*" + NUM, text),
                max_aspect_ratio=_last_float(r"Maximum Aspect Ratio\s*=\s*" + NUM, text),
                min_volume_m3=_last_float(r"minimum volume(?:\s*\(m3\))?:\s*" + NUM, text),
                inverse_oq_above_0p95=native_tail_count(Path(transcript)))


def cad_gap_audit(mesh, level):
    """CAD sponson-clearance rays; informational unless the primary gap closes."""
    try:
        from check_mesh_clearance import measure_stations
        cad = json.loads((ROOT / "01_geometry/geometry_audit.json").read_text("utf-8-sig"))["cad_clearance_vertical_rays"]
        rays = measure_stations(Path(mesh), [(r["x_m"], r["z_m"]) for r in cad])
        errors, mismatched, primary_open = [], 0, None
        for station, ray in zip(cad, rays):
            if (station["clearance_m"] is None) != (ray["gap_m"] is None):
                mismatched += 1
            if station["clearance_m"] is not None and ray["gap_m"] is not None:
                errors.append(abs(ray["gap_m"] - station["clearance_m"]))
            if abs(station["z_m"] - .86) < 1e-9:
                primary_open = ray["gap_m"] is not None and ray["gap_m"] > 0
        worst = max(errors) if errors else None
        return dict(stations=len(cad), max_gap_error_m=worst, presence_mismatches=mismatched,
                    primary_sponson_gap_open=primary_open,
                    within_tolerance=bool(worst is not None and worst <= CAD_GAP_TOL_M[level]))
    except Exception as exc:  # never block on an informational geometry ray
        return dict(error=f"{exc.__class__.__name__}: {exc}")


def grade(level, inv, mq, sq, phase="after"):
    poor = mq.get("inverse_oq_above_0p95")
    poor_fraction = (poor / inv["cells"]) if (poor is not None and inv["cells"]) else None
    other = "before" if phase == "after" else "after"
    oq = sq.get(phase + "_min_oq")
    if oq is None:
        oq = sq.get(other + "_min_oq")
    vol = sq.get("min_volume_m3")
    if vol is None:
        vol = mq.get("min_volume_m3")
    positive = bool(vol is not None and vol > 0 and not sq.get("negative_volume_reported"))
    pf = poor_fraction if poor_fraction is not None else 1.0
    if oq is not None and positive and oq >= MESH_OQ_TARGET and pf <= MESH_POOR_FRACTION_MAX:
        tier = "target"
    elif oq is not None and positive and oq >= MESH_OQ_ACCEPT and pf <= MESH_POOR_FRACTION_MAX:
        tier = "accept"
    elif oq is not None and positive and oq > 0 and pf <= MESH_POOR_FRACTION_LASTRESORT:
        tier = "last_resort"
    else:
        tier = "reject"
    return tier, oq, poor_fraction, positive


def audit_candidate(level, mesh, mesh_transcript, solver_transcript, config_path, label="", phase="after"):
    from mesh_ladder_limits import raw_domain_volume
    mesh, config_path = Path(mesh).resolve(strict=True), Path(config_path).resolve(strict=True)
    inv = mesh_inventory(mesh)
    mq = mesher_quality(mesh_transcript) if mesh_transcript else {}
    sq = solver_quality(solver_transcript) if solver_transcript else {}
    sq["quality_phase_used"] = phase
    tier, oq, poor_fraction, positive = grade(level, inv, mq, sq, phase)
    volume = raw_domain_volume(mesh)
    cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
    hard = {
        "below_licence_cap": inv["cells"] <= LICENSE_CELL_CAP,
        "admissible_cell_window": in_hard_window(level, inv["cells"]),
        "positive_cell_volumes_in_solver": positive,
        "solver_quality_report_present": oq is not None,
        "single_fluid_zone": len(inv["cell_zones"]) <= 1,
        "eleven_physical_boundaries": set(inv["boundary_zones"]) == BOUNDARIES,
        "quality_tier_admissible": tier in TIERS,
        "mesh_inside_level_folder": mesh.is_relative_to((ROOT / "02_mesh" / level).resolve()),
    }
    report = dict(level=level, label=label, source_mesh=str(mesh), mesh_sha256=digest(mesh), quality_tier=tier,
                  solver_min_orthogonal_quality=oq, poor_cell_fraction_oq_below_0p05=poor_fraction,
                  fluid_volume_m3=volume, inventory=inv, mesher_quality=mq, solver_quality=sq,
                  cad_gap_audit=cad_gap_audit(mesh, level), hard_checks=hard, admissible=all(hard.values()),
                  target_window=list(TARGET_WINDOWS[level]), hard_window=list(HARD_WINDOWS[level]),
                  in_target_window=TARGET_WINDOWS[level][0] <= inv["cells"] <= TARGET_WINDOWS[level][1],
                  meshing_config_path=str(config_path),
                  prism_scopes=cfg.get("prism_scopes"), size_scale=cfg.get("fasttrack_size_scale"))
    return report


def tier_key(report):
    tier = report.get("quality_tier")
    rank = {"target": 0, "accept": 1, "last_resort": 2}.get(tier, 9)
    # Within a tier prefer the fuller boundary layer (0.1 buckets), then the better minimum OQ.
    coverage = min(1.0, float(report.get("bl_coverage") or 0.0))
    return (0 if report.get("admissible") else 1, rank, -round(coverage, 1),
            -(report.get("solver_min_orthogonal_quality") or -1.0), 0 if report.get("in_target_window") else 1)


def _source_geometry(config_path):
    cfg_path = Path(config_path).resolve(strict=True)
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    shell = Path(cfg["shell"]).resolve(strict=True)
    folder = Path(cfg.get("source_surface_dir") or shell.parent).resolve(strict=True)
    return dict(meshing_config_path=str(cfg_path), meshing_config_sha256=digest(cfg_path),
                source_surface_dir=str(folder), source_surface_path=str(shell), source_surface_sha256=digest(shell))


def published(level):
    path = ROOT / "02_mesh" / level / "mesh_qa.json"
    if not path.is_file():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8-sig"))
        mesh = Path(row["source_mesh"])
        if (row.get("passed") is True and row.get("level") == level and row.get("fasttrack") and mesh.is_file()
                and digest(mesh) == row["mesh_sha256"] and in_hard_window(level, row["cells"])):
            return row
    except (OSError, KeyError, ValueError):
        return None
    return None


def ratio_check(level, cells, volume):
    """Measured h=(V/N)^(1/3) ratios against already-published coarser levels."""
    h = {level: (volume / cells) ** (1 / 3)}
    for other in LEVELS:
        if other != level:
            row = published(other)
            if row:
                h[other] = (row["five_region_evidence"]["fluid_volume_m3"] / row["cells"]) ** (1 / 3)
    r32 = h["coarse"] / h["medium"] if {"coarse", "medium"} <= set(h) else None
    r21 = h["medium"] / h["fine"] if {"medium", "fine"} <= set(h) else None
    ok = (r32 is None or r32 >= RATIO_HARD["r32"]) and (r21 is None or r21 >= RATIO_HARD["r21"])
    return dict(h_m=h, r32=r32, r21=r21, hard_pass=bool(ok),
                target_pass=bool((r32 is None or r32 >= RATIO_TARGET["r32"]) and (r21 is None or r21 >= RATIO_TARGET["r21"])))


def publish(report):
    level = report["level"]
    if not report.get("admissible"):
        raise ValueError(f"Refusing to publish a non-admissible {level} mesh: {report['hard_checks']}")
    ratios = ratio_check(level, report["inventory"]["cells"], report["fluid_volume_m3"])
    if not ratios["hard_pass"]:
        raise ValueError(f"{level} spacing ratio below the hard floor: {ratios}")
    mesh = Path(report["source_mesh"])
    if digest(mesh) != report["mesh_sha256"]:
        raise ValueError("Mesh changed after audit")
    checks = dict(report["hard_checks"], spacing_ratio_hard_floor=ratios["hard_pass"])
    inv = report["inventory"]
    row = dict(level=level, fasttrack=True, passed=True, solver_admissible=True, checks=checks,
               quality_tier=report["quality_tier"], cells=inv["cells"], nodes=inv["nodes"],
               cell_type_counts=inv["cell_type_counts"], face_zones=inv["boundary_zones"], cell_zones=inv["cell_zones"],
               boundary_layer_cell_count=inv["boundary_layer_cells"], source_mesh=str(mesh), mesh_sha256=report["mesh_sha256"],
               source_geometry=_source_geometry(report["meshing_config_path"]),
               cell_target_window=report["target_window"], cell_hard_window=report["hard_window"],
               min_orthogonal_quality=report["solver_min_orthogonal_quality"],
               mesher_min_orthogonal_quality=report["mesher_quality"].get("min_oq"),
               max_aspect_ratio=report["mesher_quality"].get("max_aspect_ratio"),
               min_volume_m3=report["solver_quality"].get("min_volume_m3"),
               poor_cell_fraction_oq_below_0p05=report["poor_cell_fraction_oq_below_0p05"],
               recommended_solver_minimum_OQ=MESH_OQ_TARGET,
               solver_reaches_recommended_OQ=bool((report["solver_min_orthogonal_quality"] or 0) >= MESH_OQ_TARGET),
               independent_solver_quality=dict(standard=report["solver_min_orthogonal_quality"],
                                               before_repair=report["solver_quality"].get("before_min_oq"),
                                               managed_transcript=report["solver_quality"].get("transcript")),
               five_region_evidence=dict(fluid_volume_m3=report["fluid_volume_m3"], fasttrack=True),
               spacing_ratios=ratios, cad_gap_audit=report["cad_gap_audit"], in_target_window=report["in_target_window"],
               fasttrack_report=report, fasttrack_profile=snapshot())
    atomic_write_json(ROOT / "02_mesh" / level / "mesh_qa.json", row)
    return row


def publish_ladder():
    rows = {lv: published(lv) for lv in LEVELS}
    missing = [lv for lv, r in rows.items() if r is None]
    if missing:
        raise ValueError(f"Cannot publish the ladder; unpublished levels: {missing}")
    h = {lv: (r["five_region_evidence"]["fluid_volume_m3"] / r["cells"]) ** (1 / 3) for lv, r in rows.items()}
    r32, r21 = h["coarse"] / h["medium"], h["medium"] / h["fine"]
    checks = dict(each_grid_passed=all(r["passed"] for r in rows.values()),
                  admissible_windows=all(in_hard_window(lv, r["cells"]) for lv, r in rows.items()),
                  ratio_hard_floor=bool(r32 >= RATIO_HARD["r32"] and r21 >= RATIO_HARD["r21"]),
                  increasing_counts=rows["coarse"]["cells"] < rows["medium"]["cells"] < rows["fine"]["cells"],
                  fine_below_licence=rows["fine"]["cells"] <= LICENSE_CELL_CAP)
    result = dict(fasttrack=True, levels={lv: r["cells"] for lv, r in rows.items()},
                  fluid_volume_m3={lv: r["five_region_evidence"]["fluid_volume_m3"] for lv, r in rows.items()},
                  h_m=h, r32=r32, r21=r21, coarse_to_medium=r32, medium_to_fine=r21,
                  ratio_target_pass=bool(r32 >= RATIO_TARGET["r32"] and r21 >= RATIO_TARGET["r21"]),
                  quality_tiers={lv: r["quality_tier"] for lv, r in rows.items()},
                  min_orthogonal_quality={lv: r["min_orthogonal_quality"] for lv, r in rows.items()},
                  mesh_sha256={lv: r["mesh_sha256"] for lv, r in rows.items()}, checks=checks,
                  passed=all(checks.values()), solver_admissible=all(checks.values()))
    atomic_write_json(ROOT / "02_mesh" / "grid_ladder_qa.json", result)
    return result
