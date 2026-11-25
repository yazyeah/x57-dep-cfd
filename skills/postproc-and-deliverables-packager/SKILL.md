---
name: postproc-and-deliverables-packager
description: Publication-grade matplotlib & Fluent 3D visualization standards (matching LaTeX academic report style with solid-masked slices) and strict final deliverables packaging contract for downstream report generation.
---

# Post-Processing, Publication-Grade Figures & Deliverables Packaging

## 1. Visual Design Language (Match Target Report Quality!)

All generated matplotlib plots MUST follow this exact publication-grade academic report aesthetic:
- **Typography**: Times New Roman text and mathematical typography:
  ```python
  from publication_fonts import configure_matplotlib
  configure_matplotlib()
  plt.rcParams.update({
      "axes.labelsize": 10,
      "axes.titlesize": 10.5,
      "xtick.labelsize": 8.5,
      "ytick.labelsize": 8.5,
      "legend.fontsize": 8.5,
      "figure.dpi": 400,
      "savefig.dpi": 400,
      "axes.linewidth": 0.8,
      "grid.alpha": 0.25,
      "grid.linestyle": "--",
  })
  ```
- **Dual Export**: Save EVERY matplotlib figure in BOTH high-res PNG (`400 DPI`) AND vector PDF (`*.png` + `*.pdf`) in `DELIVERABLES\figures\`.
- **CRITICAL — Solid-Body Masking on Flow Slices**:
  - Extract real fluid cell/node values directly from Fluent (e.g., ASCII/CSV/CGNS/EnSight/XY-slice exports on real fluid zones — NEVER interpolate smeared colors through solid aircraft interiors!).
  - Mask triangles/grid cells that fall inside solid geometry (using the real CAD/surface cross-section polygon at each slice plane), fill masked solid interiors with clean light gray (`#d9d9d9`) + crisp black outline (`#111111`, linewidth `1.0–1.2`), and add `[Solid bodies masked]` in the colorbar/figure footer!
- **Colormaps**:
  - Velocity magnitude `|V|` (`m/s`): `turbo` colormap (`0` to max jet velocity, e.g. `48 m/s`), overlaid with crisp **white streamlines** (`color='white'`, `linewidth=0.6–0.8`, `alpha=0.85`).
  - Static gauge pressure `p_gauge` (`Pa`) and `C_p`: diverging **`RdBu_r`** centered symmetrically around `0 Pa` (`TwoSlopeNorm(vcenter=0)` or symmetric `[-p_lim, +p_lim]`).
  - Transverse swirl / axial vorticity `omega_x`: diverging **`RdBu_r`** centered at `0` with secondary-flow `(v, w)` streamlines, dashed circles marking each propeller disk footprint, and a hatched brown/gray bar marking the runway plane at `y = -1.70 m`!
- **Mirrored Full-Aircraft Plans**:
  - For horizontal planform planes (e.g., HLP thrust-axis plane `y ≈ +0.003 m` beneath wing lower surface, and above-wing plane `y ≈ +0.225 m` just above wing upper surface), mirror `z >= 0` symmetrically to `[-z_max, +z_max]` and explicitly tag `[fine_rpm100, Solid Bodies Masked, Mirrored Full Aircraft]`.

---

## 2. Mandatory Figure Suite (`DELIVERABLES\figures\` & `DELIVERABLES\fluent_renders\`)

### A. Python / Matplotlib Publication Figures (`DELIVERABLES\figures\`, PNG + PDF each)
1. **`fig01_geometry_and_domain.png/.pdf`**: Clean 3-view schematic of restored level metric X-57 geometry (dimensions in m, 6 HLP + 1 wingtip disk positions/radii, `z = 0` symmetry, `y = -1.70 m` runway, computational domain box & BCs).
2. **`fig02_mesh_convergence_and_yplus.png/.pdf`**: Multi-panel (a) `L_air`, `L_wing`, `D_air` and `C_L`, `C_D` vs. mesh cell count / effective spacing `h` with Richardson extrapolation & GCI error bars; (b) `wall_wing` and full-aircraft `y+` distribution histogram/CDF across Coarse/Medium/Fine showing `y+ ≈ 1`.
3. **`fig03_convergence_histories.png/.pdf`**: Multi-panel (a) Scaled residuals history for `fine_rpm100`; (b) Force monitor histories (`L_air`, `L_wing`, `D_air`) demonstrating steady converged tail.
4. **`fig04_spanwise_slices_vel_press.png/.pdf`** *(Matches reference Figure 9!)*: 2×3 solid-masked spanwise slices from `fine_rpm100`:
   - Top row (a–c): Velocity magnitude `|V|` (`turbo`) + white streamlines at:
     - (a) `z = z_HLP1` (~`0.86–0.90 m`, showing HLP-1 & open sponson clearance annotated with exact CAD vs. wrapped fine mesh clearance!)
     - (b) `z = z_HLP3` (~`2.04 m`, mid-span underslung jet & upper entrainment)
     - (c) `z = z_WT` (~`4.82 m`, wingtip cruise propeller large annular slipstream)
   - Bottom row (d–f): Matched static gauge pressure `p_gauge` (`RdBu_r`) at the exact same 3 spanwise stations, solid bodies masked!
5. **`fig05_horizontal_planes_blown_wing.png/.pdf`** *(Matches reference bottom panel!)*: 1×2 solid-masked mirrored full-aircraft horizontal slices from `fine_rpm100`:
   - (a) HLP thrust-axis plane (`y ≈ +0.003 m`, beneath wing lower surface): all 12 HLP jets + 2 wingtip jets contracting and merging beneath the wing.
   - (b) Above-wing plane (`y ≈ +0.225 m`, just above wing upper surface): outboard wingtip slipstream vs. weaker upper flow over inboard wing.
6. **`fig06_wing_cp_and_suction.png/.pdf`**: Multi-panel:
   - (a) Upper & lower surface wing `C_p` (and `p_gauge`) chordwise distributions at 4–5 key spanwise stations (`HLP-1`, `HLP-3`, mid-gap between HLPs, `HLP-6`, inboard of wingtip prop) clearly annotating the **peak suction (lowest pressure) location**!
   - (b) 2D planform map of wing upper-surface and lower-surface `C_p` (mirrored or starboard wing) with star marker showing global minimum `C_p` (highest suction).
7. **`fig07_rpm_sweep_scaling.png/.pdf`** *(Matches reference Figure 13 top!)*: 1×2 matched medium-grid RPM sweep (`s = 0, 50%, 75%, 100%`) + `100% no-swirl` marker:
   - (a) Full-aircraft vertical force `L_air`, wing vertical force `L_wing`, and airframe drag `D_air` vs. speed fraction `s`, with quadratic `s^2` curve fits (`R^2` annotated) + diamond marker for `100% RPM no-swirl`.
   - (b) Gross static thrust `T_gross (kN)` and net forward force `T_net = T_gross - D_air (kN)` vs. `s`, with inset bar chart confirming collapse of `D_air / s^2` and `|L_air| / s^2` across `50%, 75%, 100%`!
8. **`fig08_swirl_comparison_and_load_shift.png/.pdf`** *(Matches reference Figure 13 bottom!)*: 1×3 matched medium-grid swirl comparison:
   - (a) Transverse plane downstream of wing (`x ≈ 1.20 m`) for **Swirl ON** (`medium_rpm100`): axial vorticity / swirl contours + cross-flow streamlines + dashed disk circles + runway plane.
   - (b) Same transverse plane (`x ≈ 1.20 m`) for **Swirl OFF** (`medium_rpm100_noswirl`).
   - (c) Wing spanwise load shift `Delta(dL_wing/dz) = Swirl ON - Swirl OFF` vs. `z (m)`, shading positive swirl gain vs. negative loss and annotating inboard vs. outboard split!
9. **`fig09_wake_evolution_crossplanes.png/.pdf`**: 2×2 or 1×4 streamwise cross-plane evolution (`x = -0.30, +0.35, +1.20, +3.00 m`) showing slipstream contraction, inter-jet merging, ground-effect spreading near `y = -1.70 m`, and wingtip vortex development.
10. **`fig10_component_force_and_upper_lower_budget.png/.pdf`**: Stacked/waterfall pressure vs. viscous vertical force & drag breakdown by airframe component (`wing_upper`, `wing_lower`, `nacelles`, `fuselage`, `sponson`, `empennage`).
11. **`fig11_wall_yplus_and_shear_map.png/.pdf`**: 2D wing planform map of wall `y+` and skin-friction coefficient `C_f` / wall shear stress proving viscous-sublayer resolution and locating stagnation/separation regions.
12. **`fig12_actuator_disk_verification_and_design_concept.png/.pdf`**: Radial disk loading (`w_T`, `w_Q`) + discrete Fluent thrust/torque verification error across all 7 rotors + quantitative blown-wing high-lift modification analysis referencing NASA X-57 Mod IV literature!

### B. Native Fluent 3D High-Res Renders (`DELIVERABLES\fluent_renders\`, `>= 1920x1080` PNG via visible RTX 4060 GUI)
Render directly from Fluent (`fine_rpm100`, mirrored across `z = 0` where appropriate):
1. **`render01_mesh_farfield_hexcore.png`**: Symmetry plane / cut-plane showing Cartesian hex elements in farfield + BOI wake refinement.
2. **`render02_mesh_wing_inflation_closeup.png`**: Close-up cross-section around wing leading edge & nacelle showing 15–18 smooth prism inflation layers (`y+ ≈ 1`).
3. **`render03_mesh_sponson_and_disks_closeup.png`**: Close-up cut plane showing open sponson clearance + dense actuator-disk BOI mesh.
4. **`render04_pathlines_slipstreams_3d.png`**: Full-aircraft (mirrored) 3D **Pathlines** released from all 14 propeller disks colored by Velocity Magnitude!
5. **`render05_pathlines_wingtip_vortex_3d.png`**: Close-up 3D **Pathlines** around wingtip & wingtip propeller showing wingtip vortex formation and swirl interaction!
6. **`render06_surface_pressure_contour_top_3d.png`**: Full-aircraft 3D top-isometric static gauge pressure / `C_p` contours.
7. **`render07_surface_pressure_contour_bottom_3d.png`**: Full-aircraft 3D bottom-isometric static gauge pressure / `C_p` contours (revealing underslung jet suction footprint beneath wing!).
8. **`render08_velocity_streamlines_3d.png`**: Global 3D velocity streamlines around the full aircraft.
9. **`render09_qcriterion_vortices_3d.png`**: 3D **Q-criterion iso-surface** colored by Velocity Magnitude showing coherent propeller slipstream tubes & wingtip vortex cores.
10. **`render10_surface_yplus_and_oilflow_3d.png`**: 3D aircraft surface `y+` contour or wall-shear limiting streamlines (numerical oil-flow).

---

## 3. Strict Deliverables Packaging Contract (`DELIVERABLES\`)

When Stage S7 finishes, the `F:\FEA Coursework\Workspace\DELIVERABLES\` folder MUST be 100% self-contained so the downstream report-writing agent can read it directly and build the final LaTeX/PDF report with zero missing facts:

1. **`DELIVERABLES\DELIVERABLES_MANIFEST.json`**: Complete machine-readable index listing all file paths, SHA256 or byte sizes, simulation matrix summary, key headline numbers, and verification pass/fail status.
2. **`DELIVERABLES\data\`**:
   - `environment_and_license.json` (Ansys Student v252 exact version, cell cap, core count, CPU/RAM)
   - `geometry_audit.json` (original STL/GLB bounds, unit conversion, unrotation quaternion, exact disk centers/radii, wing `S_ref`, `MAC`, `b`, CAD vs. wrapped sponson clearance)
   - `actuator_disk_model.json` (BEMT derivation, parameters, spin directions, nominal/50%/75% thrust & torque targets vs. Fluent discrete integrated values)
   - `summary_metrics.json` (all headline forces, thrusts, coefficients, `q_ref`, `V_ref`, peak suction coordinates & `C_p_min`, GCI values, quadratic `R^2` fits, swirl shift split)
   - `mesh_convergence.csv` (Coarse/Medium/Fine cell counts, min ortho quality, max aspect ratio, `y+` stats, `L_air`, `L_wing`, `D_air`, `C_L`, `C_D`, `T_gross`, `T_net`, GCI)
   - `rpm_sweep.csv` (`s = 0.00, 0.50, 0.75, 1.00`, Swirl ON + `1.00` Swirl OFF: full forces, `T_gross`, `T_net`, `D_air/s^2`, `|L_air|/s^2`)
   - `yplus_stats.csv` (component-by-component `y+` mean, median, p95, max across grids)
   - `wing_cp_sections.csv` (chordwise `x/c`, `C_p`, `p_gauge` upper & lower at key spanwise stations)
   - `spanwise_loading.csv` (`z`, `dL/dz` for Swirl ON, Swirl OFF, and `Delta(dL/dz)`, plus `fine_rpm100`)
   - `convergence_qa.csv` (per-case final residuals, mass flux error, last-200-iter force mean & std dev)
3. **`DELIVERABLES\ansys_submission\`** *(Direct coursework submission attachments!)*:
   - `X57_DEP_fine_rpm100.msh.h5` (verified mesh file)
   - `X57_DEP_fine_rpm100.cas.h5` (verified converged case file)
   - `X57_DEP_fine_rpm100.dat.h5` (verified converged data file)
   - *(Optional if space permits: `X57_DEP_medium_rpm100.cas.h5` & `.dat.h5`)*
4. **`DELIVERABLES\figures\`**: All 8 publication matplotlib figures (both `.png` and `.pdf`).
5. **`DELIVERABLES\fluent_renders\`**: All 6 native Fluent high-res 3D PNG renders.
6. **`DELIVERABLES\handoff_notes.md`**: Detailed technical narrative written by GPT Astra covering: exact software/solver versions, every engineering assumption & modeling choice, exact Fluent TUI/expression commands used, any troubleshooting encountered, honest physical interpretation of static lift/thrust/swirl/peak-suction results, and data-backed design modification suggestions (flaps, slats, camber, HLP vertical alignment).

### Final Mandatory Gate Before Finishing
Run:
```powershell
& $env:X57_PYTHON "F:\FEA Coursework\Workspace\scripts\verify_deliverables.py"
```
Do **NOT** declare completion until `verify_deliverables.py` exits with code `0` (`ALL CHECKS PASSED`)!

所有绘图脚本统一使用 Times New Roman，覆盖标题、坐标与刻度、图例、色标、标注和数学符号（含粗体与斜体）。Matplotlib 使用 scripts/publication_fonts.py 中的 configure_matplotlib()；PNG 按 400 DPI 导出，矢量 PDF 嵌入实际 Times New Roman 字体。PyVista/VTK 出图前调用 configure_pyvista(plotter) 绑定相应 TTF。Fluent 原生视图调用 configure_fluent_font()，记录运行时实际支持及选用的字体，核验时如实列出任何不支持的原生文字元素。
