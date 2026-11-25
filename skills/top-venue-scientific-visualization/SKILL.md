---
name: top-venue-scientific-visualization
description: 2025-2026 top-venue scientific plotting skill fusing AIAA Journal of Aircraft / Journal of Fluid Mechanics (JFM) / Nature physics rigor with CVPR / ICCV / NeurIPS multi-panel composite aesthetics, mandatory Times New Roman typography, cmcrameri/cmocean colormaps, Raincloud/Ridge/Inset/Radar/Pareto/Heatmap analytics, and white-background PyVista SSAO/SSAA 3D rendering.
---

# Top-Venue Scientific Visualization Skill (AIAA / JFM / Nature + CVPR / ICCV / NeurIPS Fusion)

## 1. Philosophy: Visually Sophisticated, Archival-Grade, and 100% Scientifically Exact

Every figure in `DELIVERABLES\figures\` (`fig01`–`fig22`, 400 DPI PNG + vector PDF) and `DELIVERABLES\fluent_renders\` (`render01`–`render22`, `>= 1920×1080` PNG) MUST meet **AIAA *Journal of Aircraft***, ***Journal of Fluid Mechanics (JFM)***, ***Nature***, and **CVPR / ICCV / NeurIPS (2025–2026)** archival standards:
- **High Information Density & Multi-Panel Storytelling**: Never produce sparse single-line default charts. Use Matplotlib `fig.subfigures` + `GridSpec` (2 to 6 coordinated panels per figure) combining global fields, CVPR-style `inset_axes + mark_inset` zoom callouts, GCI / `±σ` uncertainty bands, marginal distributions, Raincloud/Ridge statistical overlays, and clear quantitative annotations.
- **100% Truthful Analysis**: Complexity comes strictly from genuine physics & statistical diagnostics — NEVER decorative or fabricated curves.
- **Proactive Package & Web Lookup**: You may install lightweight plotting libraries (`cmcrameri`, `SciencePlots`, `tueplots`, `cmocean`, `seaborn`, `pyvista`) strictly inside `F:\FEA Coursework\Workspace\.venv` via `uv` (`UV_CACHE_DIR=F:\FEA Coursework\Workspace\_cache\uv`) and search latest official documentation when crafting advanced composite layouts.

---

## 2. Mandatory Typography & Vector Export (`Times New Roman` Everywhere!)

Always import and call `configure_matplotlib()` / `apply_publication_style()` from `F:\FEA Coursework\Workspace\scripts\publication_fonts.py` (or `plot_style.py`) at the top of EVERY plotting script:
```python
import sys
sys.path.insert(0, r"F:\FEA Coursework\Workspace\scripts")
from plot_style import apply_publication_style, save_dual_figure, ACADEMIC_PALETTE
apply_publication_style()
```
This guarantees:
- **Times New Roman** across ALL titles, axis labels, tick labels, legends, annotations, and mathematical symbols (`mathtext.fontset="stix"` matching Times New Roman regular & italic!).
- **`pdf.fonttype = 42`** & **`ps.fonttype = 42`** (TrueType Times New Roman embedded in every vector PDF — verified by `verify_deliverables.py`!).
- **Dual Export**: Every `fig01`–`fig22` saved as BOTH **400 DPI PNG** (`*.png`) and **Vector PDF** (`*.pdf`) on pure **white (`#ffffff`)** backgrounds, sized cleanly for LaTeX double-column/full-width (`6.8–7.2 in` wide; readable `8–10 pt` final text).

---

## 3. Perceptually Uniform Scientific Colormaps (Nature / CVPR / JFM Standard)

- **Categorical Comparisons (Okabe-Ito / Muted Academic Palette)**:
  `["#1f4e79", "#c0392b", "#2e7d32", "#d97706", "#6a1b9a", "#00838f", "#546e7a"]` paired with distinct line styles (`-`, `--`, `-.`, `:`) and markers (`o`, `s`, `^`, `D`, `v`) for grayscale/colorblind safety.
- **Velocity Magnitude `|V|` & TKE**: `turbo`, `viridis`, or `cmcrameri.cm.batlow` (with crisp white streamlines `lw=0.65, alpha=0.88`).
- **Diverging Fields (`p_gauge`, `C_p`, Axial Vorticity `omega_x`, Helicity, Principal Stress $\sigma_1/\sigma_3$)**: Zero-centered **`RdBu_r`**, **`cmocean.cm.balance`**, or **`cmcrameri.cm.vik` / `roma`** with `TwoSlopeNorm(vcenter=0)`.
- **Ansys Stress Contours ($\tau_w$, $\sigma_{\text{vM}}$, $\tau_{\max}$, $\text{FoS}$)**:
  - Use perceptually smooth blue-to-red engineering `turbo` (or Ansys-style clean scale where low stress = deep cool **blue**!).
  - **Dual-Scale Rule**: Pair (1) **Full-Aircraft Engineering Allowable Scale** (`0–100 MPa` / `0–0.2·σ_y`, showing the globally converged low-stress cool-blue airframe & Safety Factor $\gg 20$) with (2) **Auto-Ranged Local Detail Zoom** (wing root & HLP nacelle-pylon roots revealing real stress gradients!).

---

## 4. Signature 2025–2026 Complex Composite Archetypes (Code Patterns)

1. **CVPR/ICCV Zoom-In Callouts (`inset_axes` + `mark_inset`)**:
   ```python
   from mpl_toolkits.axes_grid1.inset_locator import inset_axes, mark_inset
   axins = inset_axes(ax, width="40%", height="38%", loc="upper right", borderpad=1.2)
   # plot zoomed wing LE suction peak / last-300-iter lift plateau / wing-root stress
   mark_inset(ax, axins, loc1=2, loc2=4, fc="none", ec="#444444", ls="--", lw=0.8)
   ```
2. **Nature/CVPR Raincloud & Overlapping KDE Ridge Plots (`fig20`, `fig21`)**:
   - Combine half-violin KDE density + slim embedded boxplot + jittered quantile markers (Raincloud), OR stacked overlapping `scipy.stats.gaussian_kde` curves (`hspace=-0.35`, minimal spines) to compare component-by-component pressure, $\tau_w$, $y^+$, and structural $\sigma_{\text{vM}}$ distributions across cases!
3. **CVPR/NeurIPS Multi-Metric Radar + Pareto Frontier + Annotated Ablation Heatmap (`fig19`)**:
   - Normalized polar radar chart + $\Delta C_L$ vs $\Delta C_D$ Pareto frontier + 18-case × 10-KPI heatmap with direct numeric cell labels and group dividers (3D Core / 3D Expanded / 2D Optimization).
4. **Solid-Masked Real-Fluid Slices (`fig04`, `fig05`, `fig08`, `fig09`, `fig18`)**:
   - Extract real fluid cell/node data from Fluent; mask interior solid bodies (`#d9d9d9` fill + `#111111` crisp CAD contour + `[Solid bodies masked]`); mirror `z >= 0` for full-aircraft planform views (`[Mirrored Full Aircraft]`).
5. **PyVista Publication Studio 3D Rendering (`render01`–`render22` & `fig22` hybrid)**:
   - Pure white background (`pl.set_background("white")`), super-sampling anti-aliasing (`pl.enable_anti_aliasing("ssaa")`), **Screen-Space Ambient Occlusion (`pl.enable_ssao()`)** for realistic contact shadows around nacelles/pylons/wing junctions, `smooth_shading=True`, `split_sharp_edges=True`, 3D shaded stream-tubes (`streamlines.tube(radius=...)`), semi-transparent Q-criterion iso-surfaces (`opacity=0.78`), crisp black scalar bars, and high-res export (`window_size=(1920, 1080)` or `scale=2`).
   - Can also stitch white-background PyVista/Fluent 3D panels directly beside 2D Matplotlib physics panels (`fig22`) using `fig.subfigures` + `mpimg.imread`!
