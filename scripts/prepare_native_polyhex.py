"""Prepare a new Fluent BOI field and a native object-based poly-hexcore journal."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "02_mesh/coarse/octree_field_budget"
WALLS = ["wall_wing", "wall_fuselage", "wall_nacelles", "wall_sponson", "wall_empennage"]
# HLP, wingtip, near wake, middle wake, far field (metres), first height, wing/body layers, growth.
LEVELS = {
    "coarse": (.020625, .02805, .17325, .33825, 2.4, 18e-6, 12, 12, 1.18),
    "medium": (.010, .014, .067, .145, 2.2, 15e-6, 15, 13, 1.18),
    "fine": (.008, .011, .040, .100, 2.2, 12e-6, 18, 15, 1.17),
}

PAUSE_AFTER_SAVE = '(if (or (file-exists? "exit-fluent.txt") (file-exists? "exit-fluent")) (ti-menu-load-string "/exit yes"))\n'


def quality_evidence_journal():
    """Report the high-inverse-OQ tail and the native worst cell's coordinates."""
    return ('(format #t "~%X57-INVERSE-OQ-DISTRIBUTION-BEGIN~%")\n'
            '(tgapi-util-get-cell-mesh-distribution "*" "Inverse Orthogonal Quality" 1 \'(.9500000000000001 1.0e20))\n'
            '(format #t "~%X57-INVERSE-OQ-DISTRIBUTION-END~%")\n'
            '(tgapi-util-print-worst-quality-cell "*" "Inverse Orthogonal Quality")\n')


def improvement_journal(mesh,improved):
    return (
        f'/file/confirm-overwrite no\n/file/read-mesh "{mesh.as_posix()}"\n'
        '/report/quality-method inverse-ortho-quality\n'
        '/mesh/modify/auto-node-move\n*\n()\n*\n()\n0.85\n5\n60\nyes\n1\n'
        + f'/file/write-mesh "{improved.as_posix()}"\n' + PAUSE_AFTER_SAVE
        + '/mesh/check-mesh\n/mesh/check-quality\n/report/mesh-size\n' + quality_evidence_journal() + '/exit yes\n'
    )


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def workspace_path(path):
    resolved = path.resolve(strict=True)
    resolved.relative_to(ROOT)
    return resolved

def prism_control(name, walls, first_height, layers, growth):
    return (f"/mesh/scoped-prisms/create\n{name}\nuniform\n{first_height:g}\n{layers}\n{growth:g}\n"
            f'x57fluid\nfluid-regions\nselected-face-zones\n"{walls}"\n')

def prepare(args):
    shell = workspace_path(args.shell)
    existing = workspace_path(args.field) if args.field else None
    targets = LEVELS[args.level]
    hlp, wt, near, mid, far, first, wing_layers, body_layers, growth = targets
    nacelle_first,nacelle_layers,low_first,low_layers={
        "coarse":(4.0e-5,9,8.0e-5,7),"medium":(3.5e-5,12,7.0e-5,11),"fine":(3.0e-5,15,6.0e-5,14)
    }[args.level]
    if args.wing_first_height is not None:
        first=args.wing_first_height
    if not 0<first<.001:raise ValueError("Invalid wing first layer height")
    scopes=[("wing_prisms","wall_wing",first,wing_layers,growth),("nacelle_prisms","wall_nacelles",nacelle_first,nacelle_layers,1.18),
            ("low_speed_prisms","wall_fuselage wall_sponson wall_empennage",low_first,low_layers,1.18)]
    if args.protect_tail_junction:
        scopes[-1]=("low_speed_prisms","wall_fuselage wall_sponson",low_first,low_layers,1.18)
        tail_layers={"coarse":6,"medium":10,"fine":14}[args.level]
        scopes.append(("tail_prisms","wall_empennage",6.0e-5,tail_layers,1.18))
    if args.normal_offset_correction and args.level=="coarse":
        if not args.protect_tail_junction:
            raise ValueError("Normal-offset correction requires an independent tail scope.")
        scopes[1]=("nacelle_prisms","wall_nacelles",4e-5,8,1.18)
        scopes[2]=("low_speed_prisms","wall_fuselage wall_sponson",1e-4,6,1.18)
        low_layers=6
    physical_scopes=scopes
    native_scopes=scopes
    if args.paired_layer_growth:
        if not args.protect_tail_junction:
            raise ValueError("Paired extrusion requires the independent empennage scope.")
        depths={"coarse":(12,10,8,6),"medium":(16,12,10,10),"fine":(18,16,14,14)}[args.level]
        physical_scopes=[(n,w,h,layers,1.18) for (n,w,h,_,_),layers in zip(scopes,depths,strict=True)]
        native_scopes=[(n,w,h*(1+g),layers//2,g*g) for n,w,h,layers,g in physical_scopes]
        wing_layers,low_layers=depths[0],depths[2]
        growth=1.18
    scopes=physical_scopes
    if min(args.disk_scale, args.wake_scale) <= 0 or not 1.05 <= args.boi_growth <= 1.35:
        raise ValueError("Local scale must be positive; BOI growth must be from 1.05 to 1.35.")
    if args.keep_prism_layers is not None and not 1 <= args.keep_prism_layers <= min(wing_layers,nacelle_layers,low_layers):
        raise ValueError("Retained poly-prism layers must fit both scoped prism stacks.")
    bg = args.boi_growth
    field_mesh = workspace_path(BASE / "field_geometry.msh")
    baseline = json.loads((BASE / "mesh_config.json").read_text(encoding="utf-8-sig"))
    if not args.attempt.replace("_", "").isalnum() or not .1 <= args.scale <= 10:
        raise ValueError("Invalid attempt name or size scale.")
    out = ROOT / "02_mesh" / args.level / args.attempt
    out.mkdir(parents=True, exist_ok=False)
    field = existing or out / "refinement.sf"
    sizes = {f"hlp_{k}_boi":hlp for k in range(1,7)}
    sizes.update(wt_1_boi=wt, near_wake_boi=near, mid_wake_boi=mid)
    sizes = {name:size*args.scale*(args.wake_scale if 'wake' in name else args.disk_scale) for name,size in sizes.items()}
    minimum = .375 * min(sizes.values())
    controls = [
        f'("{name}" "boi" {minimum:g} {size:g} {bg:g} 12. 1. 12 "Face Zone" "{name}" #t #t)'
        for name, size in sizes.items()
    ]
    controls.append(f'("outer" "soft" {far:g} {far:g} {bg:g} 12. 1. 12 "Face Zone" "farfield_*" #t #t)')
    if not existing:
        (out / "field.jou").write_text(
            f'/file/confirm-overwrite no\n/file/read-mesh "{field_mesh.as_posix()}"\n'
            + "/objects/create\nsizing_mesh\nfluid\n1\n*\n()\n()\nmesh\nyes\n/objects/list\n"
            + f"(tgsetvar! 'size-func/global-params '({minimum:g} {far:g} {bg:g} 2.))\n"
            + "(tgsetvar! 'size-controls '(" + " ".join(controls) + "))\n"
            + '/scoped-sizing/list\n/scoped-sizing/validate\n/scoped-sizing/compute\n'
            + f'/file/write-size-field "{field.as_posix()}"\n/exit yes\n', encoding="ascii")
    output = out / (args.level + ".msh.h5")
    raw_controls = ""
    if args.raw_first:
        raw_controls = ("(tgsetvar! 'poly/smooth-improve-iter 1)\n"
                        "(tgsetvar! 'poly/smooth-improve-tries 1)\n"
                        "(tgsetvar! 'poly/post-improve? #f)\n")
    improved = out / (args.level + "_improved.msh.h5")
    (out / "improve_raw.jou").write_text(improvement_journal(output,improved),encoding="ascii")

    retained_layers = ""
    if args.keep_prism_layers is not None:
        retained_layers = f"/mesh/scoped-prisms/poly-keep-nlayer-prism-characteristics {args.keep_prism_layers}\n"
    junction_controls = ""
    if args.protect_tail_junction:
        junction_controls = ("(tgsetvar! 'prism/corner-height-weight? #t)\n"
                             "(tgsetvar! 'prism/orthogonal-layers 1)\n"
                             "(tgsetvar! 'prism/left-hand-check1 2)\n"
                             "(tgsetvar! 'prism/stairstep-quality-method 14)\n")
    if args.normal_offset_correction:
        junction_controls += ("(tgsetvar! 'prism/normal-smooth-angle1 10.)\n"
                              "(tgsetvar! 'prism/normal-smooth-adjust-offsets? #t)\n"
                              "(tgsetvar! 'prism/offset-adjust? #t)\n"
                              "(tgsetvar! 'prism/offset-correct-smooth? #t)\n"
                              "(tgsetvar! 'prism/post-improve-iterations 2)\n"
                              "(tgsetvar! 'prism/stairstep-quality-method 11)\n")
    if args.paired_layer_growth:
        # A parent interval h*(1+g) with parent ratio g**2 conserves the final
        # requested physical stack height when Fluent divides each parent in two.
        junction_controls += ("(tgsetvar! 'prism/normal-smooth-angle1 10.)\n"
                              "(tgsetvar! 'prism/normal-smooth-adjust-offsets? #t)\n"
                              "(tgsetvar! 'prism/offset-adjust? #t)\n"
                              "(tgsetvar! 'prism/post-split? #t)\n"
                              "(tgsetvar! 'prism/post-split-layers 2)\n"
                              "(tgsetvar! 'prism/post-split-change-growth-rate? #t)\n"
                              "(tgsetvar! 'prism/post-split-growth-rate 1.18)\n"
                              "(tgsetvar! 'prism/post-improve-iterations 2)\n"
                              "(tgsetvar! 'prism/stairstep-quality-method 11)\n")
    journal = (
        f'/file/confirm-overwrite no\n/file/read-mesh "{shell.as_posix()}"\n/boundary/manage/list\n'
        '/objects/create\nx57fluid\nfluid\n1\n*\n()\n()\nmesh\nyes\n'
        '/material-point/create-material-point\nexternal_fluid\n-6\n4\n3\n'
        '/objects/volumetric-regions/compute\nx57fluid\nyes\nexternal_fluid\n()\n'
        '/objects/volumetric-regions/list x57fluid * ()\n'
        + "".join(prism_control(*scope) for scope in native_scopes)
        + f'/mesh/scoped-prisms/list\n/file/read-size-field "{field.as_posix()}"\n'
        + f'/mesh/hexcore/controls/maximum-cell-length {far:g}\n'
        + "(tgsetvar! 'octree/based-hexcore? #t)\n(tgsetvar! 'hexcore/hexcore-by-size-field? #t)\n"
        + "(tgsetvar! 'hexcore/sf-driven-octree? #t)\n"
        + "(tgsetvar! 'prism/allow-stairstepping? #t)\n(tgsetvar! 'prism/proximity-stairstep? #t)\n"
        + "(tgsetvar! 'prism/collision-gap-factor 0.35)\n(tgsetvar! 'prism/shrink-factor 0.5)\n"
        + "(tgsetvar! 'prism/collision-first-fix? #f)\n(tgsetvar! 'prism/check-quality? #t)\n"
        + "(tgsetvar! 'prism/stairstep-quality-threshold 0.95)\n(tgsetvar! 'prism/stairstep-max-warp 0.48)\n"
        + "(tgsetvar! 'prism/improve-warp? #t)\n(tgsetvar! 'prism/improve-left-handed-faces? #t)\n"
        + junction_controls + retained_layers + raw_controls + f'/file/write-mesh "{(out/"physical_surface_and_controls.msh.h5").as_posix()}"\n' + PAUSE_AFTER_SAVE
        + '/parallel/auto-partition? yes\n/mesh/auto-mesh\nx57fluid\nno\nscoped\npyramids\npoly-hexcore\nyes\nyes\n'
        + f'/file/write-mesh "{output.as_posix()}"\n' + PAUSE_AFTER_SAVE
        + '/mesh/check-mesh\n/mesh/check-quality\n/report/mesh-size\n' + quality_evidence_journal() + '/exit yes\n'
    )
    (out/"mesh.jou").write_text(journal, encoding="ascii")
    baseline.update(level=args.level, shell=str(shell), source_surface_dir=str(shell.parent), size_field_path=str(field),
                    mesh=str(output), first_height=first,layers=wing_layers,other_wall_layers=low_layers,
                    prism_scopes=[dict(name=n,walls=w.split(),first_height_m=h,layers=l,growth=g,
                    total_height_m=h*(g**l-1)/(g-1),last_height_m=h*g**(l-1)) for n,w,h,l,g in scopes],
                    scoped_transition="Explicit first height and bounded growth; last-ratio would independently prescribe final height and locally change the achieved growth.",
                    protected_tail_junction=args.protect_tail_junction,paired_layer_growth=args.paired_layer_growth,normal_offset_correction=args.normal_offset_correction,
                    native_input_stacks=[dict(name=n,walls=w.split(),first_height_m=h,layers=l,growth=g) for n,w,h,l,g in native_scopes],
                    native_gap_factor=.35,allow_layer_compression=True,native_shrink_factor=.5,
                    growth=growth, max_size=far, boi_file=str(BASE/"refinement_bodies.msh"),
                    boi_growth=bg, raw_first=args.raw_first, native_default_retained_prism_layers=2,
                    requested_retained_prism_layers=args.keep_prism_layers, improvement_target_orthogonal_quality=.15,
                    improvement_inverse_orthogonal_quality=.85, improvement_iterations=5,
                    improved_mesh=str(improved),
                    sizes=[dict(name=name, type="Body Of Influence", labels=[name], size=size) for name,size in sizes.items()])
    if existing:
        producer = json.loads((existing.parent/"mesh_config.json").read_text(encoding="utf-8-sig"))
        if Path(producer["size_field_path"]).resolve() != existing or producer["level"] != args.level:
            raise ValueError("Supplied size field does not match its actual grade and producer manifest.")
        if (args.scale, args.disk_scale, args.wake_scale, args.boi_growth) != (1., 1., 1., 1.22):
            raise ValueError("Choose a new field to change BOI settings. Reusing a field preserves its sizing.")
        for key in ("sizes", "boi_file", "near_wake_bounds", "mid_wake_bounds"):
            baseline[key] = producer[key]
        baseline["boi_growth"] = producer.get("boi_growth", 1.22)
        baseline["field_producer_manifest"] = str(existing.parent/"mesh_config.json")
    baseline["source_surface_sha256"] = sha256(shell)
    baseline["size_field_sha256"] = sha256(existing) if existing else None
    (out/"mesh_config.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    print(out)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("level", choices=LEVELS)
    parser.add_argument("shell", type=Path)
    parser.add_argument("attempt")
    parser.add_argument("--field", type=Path, help="Existing Fluent size field computed from this level's BOIs")
    parser.add_argument("--wing-first-height",type=float,help="First-layer height calibrated from the accepted powered wing y-plus")
    parser.add_argument("--normal-offset-correction",action="store_true",help="Constrain normal turning and correct height through smoothing on the actual physical layer stack")
    parser.add_argument("--paired-layer-growth",action="store_true",help="Generate half as many native parent layers and split each at the required physical growth rate")
    parser.add_argument("--protect-tail-junction",action="store_true",help="Use targeted tail inflation and checked normal extrusion at the tail/symmetry collision")
    parser.add_argument("--raw-first", action="store_true", help="Bound generation-phase smoothing; preserve base CFF before separate 0.20 OQ improvement")
    parser.add_argument("--keep-prism-layers", type=int, help="Explicit number of layers retaining poly-prism characteristics in Fluent")
    parser.add_argument("--disk-scale", type=float, default=1.0, help="Independent scale for the six HLP BOIs and wingtip BOI")
    parser.add_argument("--wake-scale", type=float, default=1.0, help="Independent scale for both wake boxes")
    parser.add_argument("--boi-growth", type=float, default=1.22, help="Native BOI field growth outside each closed refinement body")
    parser.add_argument("--scale", type=float, default=1.0, help="Multiplier for all local BOI sizes")
    prepare(parser.parse_args())

