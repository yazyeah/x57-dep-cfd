"""Verify published renderer identity, byte identity and accepted Fluent inputs."""
from functools import lru_cache
from math import isclose, isfinite
from pathlib import Path
import re

from cfd_case_identity import digest
from compare_x57_cases import BASE, OGE, VECTOR, ROOT, accepted, read_json

ENGINE = "ANSYS Fluent 2025 R2"


@lru_cache(maxsize=None)
def endpoint(name):
    qa, case, data = accepted(name)
    return dict(case=str(case), data=str(data), case_sha256=qa["case_sha256"],
                data_sha256=qa["data_sha256"])


def require(condition, message):
    if not condition:
        raise ValueError(message)


def close_positive(actual, expected):
    return isfinite(actual) and actual > 0 and isclose(actual, expected, rel_tol=1e-9)


def audit_wake(number, plate, frames, cfg):
    from x57_stress_profiles import STATIONS, WAKE
    shell, planes = frames
    first, second = shell["metadata"], planes["metadata"]
    wake = cfg["wake_display"]
    stress = number == 15
    qref = float(read_json(Path(cfg["case_file"]).parent / "solver_physics.json")["q_ref_Pa"])
    require(close_positive(wake["q_ref_Pa"], qref) and close_positive(plate["q_ref_Pa"], qref),
            "Native total pressure coefficient uses a different reference pressure")
    require(plate["expression"] == ("X57ModeledShearXY" if stress else "X57TotalPressureCoeff"),
            "Unexpected native expression in wake scene")
    expected = ("TurbulenceViscosity*(dVelocitydy.x+dVelocitydx.y)" if stress
                else "TotalPressure/("+format(qref, ".17g")+" [Pa])")
    require(plate["definition"] == expected, "Native wake postprocessing expression changed")
    level = wake["k_isovalue_m2_s2" if stress else "Cp0_isovalue"]
    require(close_positive(plate["k_or_Cp0_isovalue"], level) and
            close_positive(first["iso_value"], level if stress else level*qref), "Wake level mismatch")
    require(first["iso_field"] in (["turb-kinetic-energy", "turbulent-kinetic-energy"] if stress else ["total-pressure"]),
            "Unexpected Fluent field used to create the energy shell")
    lo,hi = first["native_field_range"]
    require(all(isfinite(v) for v in (lo,hi)) and lo < first["iso_value"] < hi and
            isfinite(first["surface_area_m2"]) and first["surface_area_m2"]>0, "Empty native Fluent isosurface")
    require(tuple(second["sections_x_m"]) == STATIONS and tuple(second["sections_zy_bounds_m"]) == WAKE and
            len(second["sections_area_m2"]) == len(STATIONS) and
            all(isfinite(v) and v > 0 for v in second["sections_area_m2"]), "Missing native fluid cut")
    color_fields = [panel["legend_records"][0]["field"].casefold() for panel in (shell, planes)]
    var = plate["expression"].casefold()
    aliases = {prefix+var for prefix in ("","expr:","expr-","expression-","named-expression-")}
    require(color_fields[1] in aliases and (color_fields[0] in aliases if stress else color_fields[0]=="velocity-magnitude"),
            "Native wake legend does not correspond to the physical field")


def audit(number, published):
    """Check one final PNG against its producing renderer and actual solved case(s)."""
    receipt = read_json(ROOT/"04_postproc/native_render_evidence"/(published.stem+".json"))
    require(digest(published) == receipt["published_sha256"], "Published PNG has changed")
    if number in (11, 12):
        from read_x57_section import case_names
        names = (BASE, OGE) if number == 11 else (VECTOR, case_names()[3])
        expected = [endpoint(name) for name in names]
        require(receipt["engine"] == "PyVista" and receipt["accepted_sources"] == expected,
                "Incorrect native inputs to the 3D comparison")
        paths = [[row["case"],row["data"]] for row in expected]
        used = (receipt["native_files"] if number == 11 else
                [[receipt["vector_case"],receipt["vector_data"]],[receipt["section_case"],receipt["section_data"]]])
        used = [[str((ROOT/Path(p)).resolve()) for p in pair] for pair in used]
        require(used == paths, "Comparison planes were generated from different native endpoints")
        return "PyVista, matched to both accepted Fluent case/data pairs"
    fine = endpoint("fine_rpm100")
    require(receipt["engine"] == ENGINE and all(receipt[k] == fine[k] for k in ("case_sha256","data_sha256"))
            and (receipt["source_case"],receipt["source_data"])==(fine["case"],fine["data"]),
            "Native viewport does not match accepted Fine case/data")
    run_id = receipt["run_id"]
    require(isinstance(run_id,str) and re.fullmatch(r"[0-9a-f]{32}",run_id), "Invalid native graphics run")
    folder = ROOT/"04_postproc/native_fine_rpm100"/run_id
    for basename,key in [("native_render_evidence.json","render_evidence_sha256"),
                         ("render_config.json","render_config_sha256")]:
        require(digest(folder/basename)==receipt[key], "Raw Fluent run metadata has changed")
    cfg = read_json(folder/"render_config.json")
    require(cfg["mode"]=="production" and cfg["run_id"]==run_id and number in cfg["numbers"] and
            (cfg["case_file"],cfg["data_file"]) == (fine["case"],fine["data"]),"Nonproduction Fluent input")
    ledger = read_json(folder/"native_render_evidence.json")
    stem = published.stem
    names = [stem+"_shell",stem+"_slices"] if number in (15,16) else [stem]
    require(receipt["panels"]==names, "Missing native component image")
    frames = [ledger[name] for name in names]
    raw = {}
    for name,frame in zip(names,frames):
        require(frame["engine"]==ENGINE and frame["run_id"]==run_id and
                (frame["source_case"],frame["source_data"])==(fine["case"],fine["data"]),
                "Unbound Fluent camera or field view")
        paths = [folder/(name+".png")]
        if frame.get("font_overlay_required"):
            paths.extend([folder/k/(name+".png") for k in ("original_native","clean_native")])
        for path in paths:
            raw[path.relative_to(folder).as_posix()] = digest(path)
    require(receipt["raw_sha256"] == raw, "Native Fluent viewport bytes have changed")
    if number in (15,16):
        require(ledger[stem]["panels"]==names,"Fluent wake panels differ")
        audit_wake(number,ledger[stem],frames,cfg)
    elif not frames[0].get("font_overlay_required"):
        require(digest(published)==raw[stem+".png"],"Native Fluent image differs from the published image")
    return f"{ENGINE}, {len(names)} native view(s), accepted Fine hashes verified"
