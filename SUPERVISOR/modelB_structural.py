#!/usr/bin/env python3
"""Model B structural rerun (user decision 2026-11-26): wing box continued through the fuselage to the symmetry plane.

Detached runner (survives the chat session). Steps, each logged to logs/modelB_structural.log; stops at the first
failure and leaves everything for manual inspection:
  1. archive model A (results, renders, figures, model.json) and copy 03_cases/fsi_structural;
  2. install SUPERVISOR/prepare_mapdl_shell_modelB.py as scripts/prepare_mapdl_shell.py (model A copy kept);
  3. the P10 structural chain (run_x57_stage.py lines 99-114): shells x3, MAPDL 7 pairs, mesh-study verification,
     element table; then the P11 structural pictures: render_mapdl_fields, plot_mapdl_stress, plot_x57_synthesis.
MAPDL only (no Fluent), so it can run next to the surface-refinement study.
"""
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

WS = Path(r"D:\FEA Coursework\Workspace")
LOG = WS / "logs" / "modelB_structural.log"
PY = WS / ".venv" / "Scripts" / "python.exe"
sys.path.insert(0, str(WS / "scripts"))


def note(msg):
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}\n")


def archive():
    dst = WS / "04_postproc" / "fsi_modelA_no_carrythrough"
    dst.mkdir(parents=True, exist_ok=True)
    files = [WS / "DELIVERABLES/data/fsi_structural_stress.json", WS / "logs/early_stress_check.json",
             WS / "04_postproc/fsi_structural/stress_and_bl_structural_provenance.json"]
    files += sorted((WS / "DELIVERABLES/fluent_renders").glob("render1[7-9]_*.png"))
    files += sorted((WS / "DELIVERABLES/fluent_renders").glob("render2[0-2]_*.png"))
    for stem in ("fig17", "fig21", "fig22"):
        files += sorted((WS / "DELIVERABLES/figures").glob(stem + "_*"))
    for f in files:
        if f.is_file():
            shutil.copy2(f, dst / f.name)
    for level in ("coarse", "medium", "fine"):
        src = WS / "03_cases/fsi_structural/models" / level / "model.json"
        if src.is_file():
            shutil.copy2(src, dst / f"model_{level}.json")
    tree = WS / "03_cases" / "fsi_structural_modelA_no_carrythrough"
    if not tree.exists():
        shutil.copytree(WS / "03_cases" / "fsi_structural", tree)
    note(f"model A archived: {len(files)} result files -> {dst}; case tree -> {tree}")


def install_generator():
    live = WS / "scripts" / "prepare_mapdl_shell.py"
    keep = WS / "04_postproc" / "fsi_modelA_no_carrythrough" / "prepare_mapdl_shell_modelA.py"
    if "CARRY_THROUGH" not in live.read_text(encoding="utf-8"):
        shutil.copy2(live, keep)
    shutil.copy2(WS / "SUPERVISOR" / "prepare_mapdl_shell_modelB.py", live)
    note("model B generator installed (model A generator kept in the archive)")


def main():
    from run_x57_converged import workspace_environment
    from compare_x57_cases import BASE, ROLL, VECTOR, accepted
    from fluent_checkpoints import case_for_data
    note("start")
    archive()
    install_generator()
    env = workspace_environment()
    steps = [["prepare_mapdl_shell.py", g] for g in ("coarse", "medium", "fine")]
    pairs = [(g, "fine_rpm100") for g in ("coarse", "medium", "fine")]
    pairs += [("fine", n) for n in ("coarse_rpm100", BASE, ROLL, VECTOR)]
    for grid, name in pairs:
        _, case, data = accepted(name)
        if case_for_data(data) != case:
            note(f"STOP: unmatched source CFF for {name}")
            return 2
        steps.append(["run_mapdl_structural.py", grid, str(case)])
    steps += [["verify_fsi_mesh_study.py"], ["assemble_fsi_structural_table.py"], ["render_mapdl_fields.py"],
              ["plot_mapdl_stress.py"], ["plot_x57_synthesis.py"]]
    for args in steps:
        t0 = dt.datetime.now()
        with (WS / "logs" / "modelB_structural_console.log").open("a", encoding="utf-8") as out:
            out.write(f"\n===== {' '.join(args)} =====\n")
            out.flush()
            rc = subprocess.run([str(PY), "-B", str(WS / "scripts" / args[0]), *args[1:]], cwd=str(WS), env=env,
                                stdout=out, stderr=subprocess.STDOUT).returncode
        note(f"{' '.join(a if len(a) < 60 else Path(a).name for a in args)}: rc={rc} in "
             f"{(dt.datetime.now() - t0).total_seconds() / 60:.1f} min")
        if rc != 0:
            note("STOP: see logs/modelB_structural_console.log")
            return 1
    note("model B structural chain complete")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - record any unexpected failure for the morning review
        note(f"STOP: {type(exc).__name__}: {exc}")
        raise
