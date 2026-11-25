"""Reload one production Fluent mesh, perform the level audit, and publish on success."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys

import h5py
from run_fluent_managed import file_state
from run_x57_converged import ROOT,control,managed_step
from verify_mesh_level import WINDOWS,prepare_solver_check,digest,source_geometry,fine_resolution_checks
from mesh_ladder_limits import raw_domain_volume,production_plan
from prepare_native_polyhex import quality_evidence_journal
from control_gate import atomic_write_json
from mesh_quality_guard import scheme_histogram_population

SCRIPTS=ROOT/"scripts"


def native(work,journal,mode,label):
    work.mkdir(parents=True,exist_ok=True)
    before={p for p in work.glob("fluent-*.trn")}
    managed_step([sys.executable,"-B",str(SCRIPTS/"run_fluent_managed.py"),"--mode",mode,"--gui",
                  "--dim","3ddp","--procs","4","--workdir",str(work),"--journal",str(journal),
                  "--stage","S2_MESH_STUDY","--case",label])
    logs=sorted(set(work.glob("fluent-*.trn"))-before,key=lambda p:p.stat().st_mtime_ns)
    if len(logs)!=1:raise ValueError(f"Expected one new native transcript at {work}")
    return logs[0]


def native_tail_count(log):
    """Read the bounded native histogram without counting console echoes."""
    text=log.read_text(errors="replace")
    sections = re.findall(r"(?ms)^\s*(X57-(?:(?:RAW|POST)-)?INVERSE-OQ-DISTRIBUTION)-BEGIN\s*$"
                          r"(.*?)^\s*\1-END\s*$", text)
    if not sections:
        return None
    section = sections[-1]
    lines=section[1].splitlines()
    # Fluent releases may print a per-zone histogram as well as the aggregate.
    # Only unambiguous single-bin counts can authorize an improvement.
    counts=[]
    totals=re.findall(r"number of interior cells\s*=\s*(\d+)",text)
    total=int(totals[-1]) if totals else None
    explicit_bin=any("tgapi-util-get-cell-mesh-distribution" in line and "Inverse Orthogonal Quality" in line and ".9500000000000001 1.0e20" in line for line in lines)
    for line in lines:
        if explicit_bin:
            count=scheme_histogram_population(line,total)
            if count is not None:
                counts.append(count)
                continue
        numbers=re.findall(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?",line)
        for index in range(len(numbers)-2):
            low,high=map(float,numbers[index:index+2])
            if abs(low-.95)<1e-6 and high>=1.e19 and re.fullmatch(r"\d+",numbers[index+2]):
                if not line.lstrip().startswith((">","(")):
                    counts.append(int(numbers[index+2]))
                break
    return counts[0] if len(counts)==1 else None


def check_improved_population(work, mesh, transcript, stamp):
    count = native_tail_count(transcript)
    if count is None:
        folder = work / "final_quality_report" / stamp
        folder.mkdir(parents=True, exist_ok=False)
        journal = folder / "improved_quality.jou"
        evidence = quality_evidence_journal().replace("X57-INVERSE-", "X57-POST-INVERSE-")
        journal.write_text(f'/file/read-mesh "{mesh.as_posix()}"\n' + evidence + '/exit yes\n', encoding="ascii")
        transcript = native(folder, journal, "meshing", f"{work.name}_improved_quality_{stamp}")
        count = native_tail_count(transcript)
    if count is None:
        raise ValueError(f"Incomplete post-improvement inverse-OQ histogram: {transcript}")
    atomic_write_json(work / "improved_inverse_oq_population.json",
                      dict(threshold=.95, count=count, transcript=str(transcript), mesh=str(mesh)))
    if count > 5000:
        raise ValueError(f"Improved mesh still has {count} cells above inverse OQ 0.95: {transcript}")


def published_level(level):
    """Reuse a signed production mesh without another native meshing session."""
    folder=ROOT/"02_mesh"/level
    canonical=folder/"mesh_qa.json"
    if not canonical.is_file():
        return None
    row=json.loads(canonical.read_text(encoding="utf-8-sig"))
    if not row.get("passed") or row.get("level")!=level or not all(row["checks"].values()):
        return None
    mesh=Path(row["source_mesh"]).resolve(strict=True)
    if (not mesh.is_relative_to(folder) or digest(mesh)!=row["mesh_sha256"]
            or source_geometry(row["source_geometry"]["meshing_config_path"])!=row["source_geometry"]):
        raise ValueError(f"Accepted {level} mesh or its source has changed: {canonical}")
    if not WINDOWS[level][0]<=row["cells"]<=WINDOWS[level][1]:
        return None
    if level=="fine" and not all(fine_resolution_checks(row["five_region_evidence"]).values()):
        return None
    return canonical


def complete(work,original_log):
    control()
    cfg=json.loads((work/"mesh_config.json").read_text(encoding="utf-8"))
    level=cfg["level"]
    previous=published_level(level)
    if previous:
        print(f"{level} already accepted at {previous}")
        control()
        return
    mesh=Path(cfg["mesh"]).resolve(strict=True)
    with h5py.File(mesh) as h:
        zones=h["meshes/1/cells/zoneTopology"]
        count=sum(int(b)-int(a)+1 for a,b in zip(zones["minId"][:],zones["maxId"][:],strict=True))
    stamp=dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_count = native_tail_count(original_log)
    atomic_write_json(work / "raw_inverse_oq_population.json",
                      dict(threshold=.95, count=raw_count, total_raw_cells=count,
                           cell_budget=WINDOWS[level], raw_count_in_budget=WINDOWS[level][0]<=count<=WINDOWS[level][1],
                           transcript=str(original_log),
                           note="Optional measurement before the explicit native quality improvement."))
    if not WINDOWS[level][0] <= count <= WINDOWS[level][1]:
        raise ValueError(f"Raw {level} mesh has {count:,} cells outside {WINDOWS[level]}; adjust sizing before improvement.")
    control()
    measured_volume=raw_domain_volume(mesh)
    plan=production_plan(ROOT,(level,count,measured_volume))
    atomic_write_json(work/"raw_mesh_ladder_plan.json",plan)
    if not plan["measured_constraints_pass"]:
        raise ValueError(f"Raw {level} count and measured V/N are incompatible with the accepted predecessor: {plan}")
    control()
    improved = Path(cfg["improved_mesh"]).resolve()
    if improved.parent != work or improved == mesh:
        raise ValueError("The raw mesh and improved checkpoint need distinct paths in the run directory.")
    previous_state = file_state(improved) if improved.is_file() else None
    transcript = native(work, work/"improve_raw.jou", "meshing", level+"_inverse_085_5passes_"+stamp)
    if not improved.is_file() or file_state(improved) == previous_state:
        raise ValueError(f"No fresh native improved mesh was saved: {improved}")
    written = re.findall(r'\bWriting\s+"([^"]+)"', transcript.read_text(errors="replace"), re.I)
    if not any((work / path).resolve() == improved for path in written):
        raise ValueError(f"The improvement transcript does not record a native write of {improved}: {transcript}")
    mesh = improved
    control()
    check_improved_population(work, mesh, transcript, stamp)
    control()
    check=prepare_solver_check(mesh)
    control()
    reload_log=native(work/"quality_reload"/stamp,check,"solver",level+"_production_mesh_reload_"+stamp)
    managed_step([sys.executable,"-B",str(SCRIPTS/"verify_mesh_level.py"),str(mesh),str(transcript),
                  "--level",level,"--solver-transcript",str(reload_log),"--config",str(work/"mesh_config.json"),"--publish"])
    control()


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("work",type=Path)
    p.add_argument("meshing_transcript",type=Path)
    a=p.parse_args();complete(a.work.resolve(strict=True),a.meshing_transcript.resolve(strict=True))

