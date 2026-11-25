---
name: aero-structural-fsi-stress
description: 1-Way Fluid-Structure Interaction (FSI) structural stress convergence analysis using installed ANSYS Mechanical APDL v252 (MAPDL.exe) coupled with converged Fluent aerodynamic pressure and wall shear loads, plus Fluent fluid wall-shear and Reynolds stress diagnostics.
---

# Aero-Structural 1-Way FSI & Fluid Stress Analysis Skill

## 1. Installed Structural Solver & Strict F-Drive Isolation

- **ANSYS Mechanical APDL v252**: `D:\Ansys\ANSYS Inc\ANSYS Student\v252\ansys\bin\winx64\MAPDL.exe` (verified installed!).
- **ANSYS Mechanical Student Limit**: Typically `128,000` nodes/elements for structural analysis (keep structural shell meshes cleanly in `15k / 35k / 75k` nodes for 3-level stress mesh convergence!).
- **F-Drive Isolation**: Always run MAPDL with working directory inside `F:\FEA Coursework\Workspace\03_cases\fsi_structural\` and `-dir "F:\FEA Coursework\Workspace\03_cases\fsi_structural"` + `TEMP`/`TMP` redirected via `env_f_only.ps1` (zero C:/D: writes!).

---

## 2. Two Complementary Stress Domains (Zero Fabrication, 100% Physical Honesty!)

### A. Fluid-Side Aerodynamic Stresses (Directly from Converged Fluent `fine_rpm100`)
1. **Wall Shear Stress ($\tau_w$, Pa) & Skin-Friction Coefficient ($C_f = \tau_w / q_{\text{ref}}$)**:
   - Exported on all 5 airframe wall zones (`wall_wing`, `wall_fuselage`, `wall_nacelles`, `wall_sponson`, `wall_empennage`).
   - Physically very low across unblown fuselage/empennage (`~0.1–2 Pa`, naturally cool blue) and moderately elevated along the blown-wing leading edge & nacelle slipstream (`~3–15 Pa`).
2. **Wake Turbulent Kinetic Energy ($k$) & Reynolds Shear Stresses ($\tau'_{ij} = -\rho\overline{u'_i u'_j}$)**:
   - Extracted on spanwise and cross-stream wake slices to quantify turbulent shear layer dissipation in the HLP & wingtip slipstreams.

### B. Structural 1-Way FSI Equivalent Stress ($\sigma_{\text{vM}}$, MPa) & Elastic Deflection ($\delta$, mm)
Map the **real converged Fluent aerodynamic surface loads** ($p_{\text{gauge}}$ normal pressure + $\tau_w$ traction from `coarse_rpm100`, `medium_rpm100`, `fine_rpm100`, PLUS exact BEMT propeller thrust/torque reaction loads at the 7 motor nacelle mounts!) onto a realistic 3D **X-57 Airframe Thin-Shell + Wing-Box Structural Model (`SHELL181` in ANSYS MAPDL)**:
- **Realistic Aerospace Material Properties (Documented Transparently)**:
  - Primary baseline: Aerospace Aluminum Alloy **Al-7075-T6** (`E = 71.7 GPa`, `nu = 0.33`, `rho = 2810 kg/m³`, yield strength `sigma_y = 503 MPa`) — or quasi-isotropic CFRP aerospace laminate (`E_eff = 60 GPa`, `sigma_allow = 450 MPa`) for comparison!
  - Realistic structural gauges: outer skin thickness `t_skin = 2.0 mm` (wing skin `2.5 mm`, fuselage/empennage `1.8 mm`, nacelle/pylon mounts `3.5 mm`, internal wing main-spar web/flange equivalent stiffening at `25%–35%` chord).
- **Boundary Conditions**:
  - Symmetry boundary condition on `z = 0` fuselage centerline (`UZ = 0, ROTX = 0, ROTY = 0`);
  - Static landing-gear support constraints at the fuselage/sponson main-gear & nose-gear attachment stations (`UX = UY = 0` at taxiing wheel-gear roots).
- **Mandatory Full Ansys Stress Contour & Convergence Deliverables**:
  1. **3-Level Stress Mesh Convergence**: Run Coarse (~15k) / Medium (~35k) / Fine (~75k) `SHELL181` meshes AND compare Coarse vs. Medium vs. Fine mapped Fluent CFD loads -> report ASME V&V 20 stress `GCI < 3%`!
  2. **Complete 3D Stress Field Exports (ALL 6 Structural Metrics on Fine Shell Mesh + Baseline vs. Take-Off Roll `V=10 m/s` vs. Optimized Blown Wing Comparison)**:
     - Equivalent von Mises Stress ($\sigma_{\text{vM}}$, MPa) — **Global Engineering Safety Scale** (`0–100 MPa` / `0–0.2·σ_y` showing globally converged cool-blue airframe, Top + Bottom views: `render17`, `render18`)
     - Equivalent von Mises Stress ($\sigma_{\text{vM}}$, MPa) — **Auto-Ranged Wing-Root & HLP Pylon-Mount Close-Up** (`render19`)
     - Maximum Principal Stress ($\sigma_1$, tension) & Minimum Principal Stress ($\sigma_3$, compression) (`render20`)
     - Tresca Maximum Shear / In-Plane Shear Stress ($\tau_{\max}$, MPa) on wing torsion box & pylons (`render21`)
     - Total Elastic Deformation ($U_{\text{sum}}$, mm, magnified overlay) & Structural Safety Factor ($\text{FoS} = \sigma_y / \sigma_{\text{vM}}$) (`render22`)
  3. **NEVER artificially tamper with or fake stress values!** Report exact converged values in `DELIVERABLES\data\fsi_structural_stress.json` & `stress_and_bl_profiles.csv`, and plot component-wise stress distributions via Raincloud/Ridge plots in `fig21_stress_envelope_and_ridge_distributions`!

---

## 3. Fallback Contingency (If MAPDL Has Unexpected Geometry-Mapping Issue Overnight)

If ANSYS MAPDL encounters an unrecoverable STL-to-shell import error overnight after 2 attempts + web-search troubleshooting:
- Build a verified high-fidelity **3D Thin-Walled Shell / Multi-Cell Wing-Box Finite-Element Solver** directly on the actual `mesher_input\*.stl` surface mesh (`scipy.sparse.linalg` / 3D CST+DKT shell FEA or coupled Euler-Bernoulli/Bredt-Batho wing-box torsion-bending stress integrator verified on a cantilever benchmark against analytical Timoshenko beam theory to `< 0.5%` error!) using the EXACT Fluent `fine_rpm100` surface pressure & thrust loads, and document transparently in `fsi_structural_stress.json` & `handoff_notes.md`. **Prefer real ANSYS MAPDL `SHELL181` first!**
