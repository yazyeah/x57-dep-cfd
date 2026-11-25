"""Verify a structural PNG against the signed Fine solve and actual MAPDL POST1 pictures."""
import json
import re
from pathlib import Path
import numpy as np
from PIL import Image,ImageChops
from native_mapdl_deck import MARKER,plot_deck,verify_readback
from native_mapdl_layout import compose
from mapdl_shell_fields import source_hash

def audit(number:int,output:Path)->str:
    try:
        return _audit(number,Path(output))
    except (OSError,KeyError,TypeError,IndexError) as error:
        raise ValueError(f"Incomplete MAPDL provenance for render {number}: {error}") from error

def _audit(number:int,output:Path)->str:
    from render_mapdl_fields import STRUCT,physical_shell,build_panels
    from verify_deliverables import REQUIRED_FLUENT_RENDERS
    output=Path(output).resolve()
    if number not in range(17,23) or output.name!=REQUIRED_FLUENT_RENDERS[number-1]:
        raise ValueError("Incorrect MAPDL render number or output name")
    if not output.is_file():
        raise ValueError(f"Native MAPDL render is absent: {output}")
    case="fine_rpm100" if output.parent.name=="fluent_renders" else output.parent.parent.name
    work=STRUCT/("fine_struct__"+case)
    mesh,fields,metrics=physical_shell(case)
    native=metrics["source_provenance"]
    if not (work/"render_sources.json").is_file():
        raise ValueError("Native MAPDL render provenance is absent")
    manifest=json.loads((work/"render_sources.json").read_text())[output.name]
    rst=(work/(native["job"]+".rst")).resolve()
    if (manifest["renderer"]!="ANSYS Mechanical APDL POST1" or manifest["source_case"]!=case or
            manifest["result_file"]!=str(rst) or manifest["result_sha256"]!=native["sha256"][str(rst)] or
            manifest["path"]!=str(output) or manifest["image_sha256"]!=source_hash(output) or
            manifest["load_signature"]!=native["load_signature"] or
            Path(manifest["native_source_manifest"]).resolve()!=work/"native_result_provenance.json"):
        raise ValueError("Native render and signed structural solution identities differ")
    run=Path(manifest["batch_directory"]).resolve()
    if run.parent!=work or not run.name.startswith("post1_") or manifest["job"]!="post1":
        raise ValueError("Unexpected native MAPDL batch directory")
    log=run/"post1.out";deck=run/"render.inp"
    script_dir=Path(__file__).parent
    sources=[deck,log,run/"element_readback.csv",run/"node_readback.csv",
             run/"model.inp",work/"native_result_provenance.json"]
    sources.extend(script_dir/f for f in ("render_mapdl_fields.py","native_mapdl_deck.py","native_mapdl_layout.py"))
    transcript=log.read_text(errors="replace")
    if MARKER not in transcript or re.search(r"\*{3}\s*(ERROR|FATAL)\s*\*{3}",transcript,re.I):
        raise ValueError("Incomplete/failed MAPDL POST1 transcript")
    if source_hash(run/"source.rst")!=native["sha256"][str(rst)] or source_hash(run/"model.inp")!=native["sha256"][str(work/"model.inp")]:
        raise ValueError("Native batch source RST or shell model differs from accepted solve")
    contents=deck.read_text(encoding="ascii")
    ordered=[int(x) for x in re.findall(r"^! X57_PANEL\s+(\d+)\s+",contents,re.M)]
    if number not in ordered:
        raise ValueError("The requested panel does not occur in the native POST1 deck")
    panels,masks,extrema=build_panels(sorted(set(ordered)),mesh,fields)
    if contents!=plot_deck(panels,masks):
        raise ValueError("MAPDL batch deck differs from the verified field definitions and element selections")
    if [p["number"] for p in panels]!=ordered:
        raise ValueError("Native PNG and MAPDL plot command ordering differ")
    ids=[i for i,n in enumerate(ordered) if n==number]
    expect=[panels[i] for i in ids]
    images=[run/f"post1{i:03}.png" for i in ids]
    if manifest["panels"]!=expect or manifest["raw_pngs"]!=[str(p) for p in images]:
        raise ValueError("MAPDL plot view, field ranges or panel sequence changed")
    if not np.allclose(extrema,[manifest["peak_vm_MPa"],manifest["min_yield_safety_factor"],manifest["max_displacement_m"]],rtol=1e-12,atol=0):
        raise ValueError("Displayed extrema disagree with signed structural solution")
    if {str(p):source_hash(p) for p in sources+images}!=manifest["native_evidence_sha256"]:
        raise ValueError("Changed MAPDL native input, output, raw PNG, readback or renderer")
    verify_readback(run,fields)
    expected=compose(expect,images,manifest["title"],*extrema)
    with Image.open(output) as png:
        if png.format!="PNG" or png.size!=expected.size or ImageChops.difference(expected,png.convert("RGB")).getbbox():
            raise ValueError("Published data pixels or captions differ from the native POST1 composition")
    return f"MAPDL POST1; {len(images)} native view(s); {extrema[0]:.5g} MPa, minimum FoS {extrema[1]:.5g}"
