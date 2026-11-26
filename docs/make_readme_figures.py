"""Web-sized README figures (docs/readme/) from the published renders and plots. Pixels are only resized/tiled."""
from pathlib import Path

from PIL import Image

WS = Path(__file__).resolve().parents[1]
REN = WS / "DELIVERABLES" / "fluent_renders"
FIG = WS / "DELIVERABLES" / "figures"
ASSETS = WS / "REPORT" / "assets"
OUT = Path(__file__).resolve().parent / "readme"


def load(path, width):
    im = Image.open(path).convert("RGB")
    return im.resize((width, round(im.size[1] * width / im.size[0])), Image.LANCZOS)


def tile(paths, name, cols=2, width=900, gap=12):
    ims = [load(p, width) for p in paths]
    h = max(i.size[1] for i in ims)
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * width + (cols - 1) * gap, rows * h + (rows - 1) * gap), "white")
    for k, im in enumerate(ims):
        sheet.paste(im, ((k % cols) * (width + gap), (k // cols) * (h + gap) + (h - im.size[1]) // 2))
    sheet.save(OUT / name, quality=88, optimize=True)


def single(path, name, width=1600):
    im = load(path, width)
    im.save(OUT / name, **({"quality": 88} if name.endswith(".jpg") else {}), optimize=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    tile([REN / "render04_pathlines_slipstreams_3d.png", REN / "render08_velocity_streamlines_3d.png",
          REN / "render13_fluent_wall_shear_stress_top_3d.png", ASSETS / "render17_teaser.png"], "overview.jpg")
    tile([REN / "render06_surface_pressure_contour_top_3d.png", REN / "render07_surface_pressure_contour_bottom_3d.png"],
         "surface_pressure.jpg")
    tile([REN / "render05_pathlines_wingtip_vortex_3d.png", REN / "render09_qcriterion_vortices_3d.png"], "vortices.jpg")
    tile([REN / "render01_mesh_farfield_hexcore.png", REN / "render03_mesh_sponson_and_disks_closeup.png"], "mesh.jpg")
    single(REN / "render22_fsi_deformation_and_safety_factor_3d.png", "fsi_deformation_safety_factor.jpg")
    single(ASSETS / "render12_opt_highlift_flow_comparison_trimmed.png", "design_highlift.jpg")
    single(FIG / "fig06_wing_cp_and_suction.png", "wing_cp.png", 1400)
    single(FIG / "fig07_rpm_sweep_scaling.png", "rpm_scaling.png", 1400)
    single(FIG / "fig02_mesh_convergence_and_yplus.png", "mesh_convergence.png", 1400)
    for p in sorted(OUT.iterdir()):
        print(f"{p.name:40s} {p.stat().st_size / 1024:7.0f} KB")
