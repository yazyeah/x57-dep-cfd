"""Report-only image assets derived from the native Fluent / MAPDL renders (no pixel of the field data is changed).

* render02 (wing inflation close-up): the lower ~35 % of the native frame is the solid wing interior (no cells),
  so the frame is cropped to the mesh above the wall; the axis triad is moved into the cropped corner.
* MAPDL renders 19-22 are two-panel composites (2 x 2400 px); they are split into single panels so the report
  can arrange them in a 2 x 2 grid.
The DELIVERABLES originals stay untouched (they are hashed by the deliverables manifest).
"""
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "DELIVERABLES" / "fluent_renders"
OUT = HERE / "assets"


def crop_render02():
    im = Image.open(SRC / "render02_mesh_wing_inflation_closeup.png").convert("RGB")
    w, h = im.size
    keep = int(0.64 * h)                      # wall prism stack ends at ~0.54 h; keep a margin of solid below it
    triad = im.crop((w - 200, int(0.875 * h), w - 40, int(0.955 * h)))
    out = im.crop((0, 0, w, keep))
    out.paste(triad, (w - 200, keep - triad.size[1] - 12))
    out.save(OUT / "render02_wing_inflation_cropped.png", optimize=True)


def collapse_blank_rows(name, keep=36, out_name=None):
    """Collapse runs of fully white rows (across the whole frame) to `keep` px; content rows are untouched."""
    im = Image.open(SRC / f"{name}.png").convert("RGB")
    a = np.asarray(im)
    blank = (a.min(axis=2) >= 250).all(axis=1)
    rows, run = [], 0
    for i, b in enumerate(blank):
        run = run + 1 if b else 0
        if not b or run <= keep:
            rows.append(i)
    Image.fromarray(a[rows]).save(OUT / (out_name or f"{name}_trimmed.png"), optimize=True)


def teaser_von_mises():
    """render17 without its title lines and footnote text (the figure caption carries both)."""
    im = Image.open(SRC / "render17_fsi_von_mises_global_top_3d.png").convert("RGB")
    a = np.asarray(im)
    ink = a.min(axis=2) < 200
    rows = np.flatnonzero(ink.any(axis=1))
    # the title occupies the first text block; the aircraft starts after the first blank gap > 40 px
    gaps = np.flatnonzero(np.diff(rows) > 40)
    top = rows[gaps[0] + 1] - 30 if len(gaps) else rows[0]
    # keep down to the colour-bar label (the last ink block before the two footnote lines)
    bottom = rows[gaps[-2]] + 25 if len(gaps) >= 2 else rows[-1]
    im.crop((0, max(top, 0), im.size[0], min(bottom, im.size[1]))).save(OUT / "render17_teaser.png", optimize=True)


def split_pairs():
    for name in ("render19_fsi_von_mises_root_pylon_zoom_3d", "render20_fsi_principal_stress_s1_s3_3d",
                 "render21_fsi_shear_stress_tresca_3d", "render22_fsi_deformation_and_safety_factor_3d"):
        im = Image.open(SRC / f"{name}.png").convert("RGB")
        w, h = im.size
        for side, box in (("L", (0, 0, w // 2, h)), ("R", (w // 2, 0, w, h))):
            im.crop(box).save(OUT / f"{name}_{side}.png", optimize=True)


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    crop_render02()
    split_pairs()
    collapse_blank_rows("render11_ige_vs_oge_wake_3d")
    collapse_blank_rows("render12_opt_highlift_flow_comparison")
    teaser_von_mises()
    print("assets written to", OUT)
