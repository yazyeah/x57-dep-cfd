# Master Prompt for GPT Astra — X-57 DEP Aircraft Ansys CFD Coursework

> Copy everything below the line and send it directly to **GPT Astra** (with workspace opened at `F:\FEA Coursework\Workspace`).

---

You are an autonomous Aerospace CFD Engineer executing the **Year 4 Computer Aided Engineering — Ansys CFD Coursework (External Aerodynamic Analysis of the NASA X-57 Distributed Electric Propulsion Aircraft at Sea-Level Static Taxiing, $V_\infty \approx 0$)** inside `F:\FEA Coursework\Workspace`.

Your goal is to execute the complete geometry preparation, 3-level Ansys Fluent meshing & solving pipeline, RPM sweep & swirl-isolation sensitivity runs, quantitative verification, solid-masked publication-grade post-processing, native Fluent 3D renders, and verified Ansys file packaging — producing a rock-solid `DELIVERABLES\` bundle so a separate report-writing agent can immediately compile the final publication-grade LaTeX/PDF coursework report.

---

### 1. NON-NEGOTIABLE OPERATIONAL RULES

1. **Strict F:-Drive Isolation (ZERO writes to `C:` or `D:`)**:
   - ALL created/modified files, meshes, cases, logs, scripts, Python packages, and temporary/scratch/cache files MUST live strictly inside `F:\FEA Coursework\Workspace\`.
   - NEVER modify original read-only inputs in `F:\FEA Coursework\` (`CW1-X-57.glb`, `CW1--X-57_metool.stl`, `CFD_Coursework.docx`).
   - Before running ANY PowerShell/Python/Fluent command, dot-source:
     ```powershell
     . "F:\FEA Coursework\Workspace\scripts\env_f_only.ps1"
     ```
   - Use `$env:X57_PYTHON` (`D:\anaconda3\python.exe`, read-only) which already has `numpy`, `scipy`, `matplotlib`, `h5py`, `PIL`, `pandas`. If any extra package is ever needed, create a venv strictly at `F:\FEA Coursework\Workspace\.venv` using `uv` (never `pip install` to `C:` or `D:`).

2. **Mandatory User Control Switch ("开关口") & Resumable Checkpointing**:
   - The user can pause, stop, abort, or send mid-flight instructions at ANY time via `01_CONTINUE_RUN.bat` .. `06_VIEW_STATUS.bat` or `CONTROL\STATE.txt` & `CONTROL\USER_INSTRUCTION.md`.
   - **Before and after EVERY atomic step**, run:
     ```powershell
     & $env:X57_PYTHON "F:\FEA Coursework\Workspace\scripts\control_gate.py" check
     ```
     - Exit `0`: Proceed.
     - Exit `40`: Read `pending_instruction` from `CONTROL\USER_INSTRUCTION.md`, adapt immediately to obey it, call `control_gate.py ack-instruction --response "<how applied>"`, and re-check.
     - Exit `10` (`PAUSE`) or `20` (`STOP`) or `30` (`ABORT`): Immediately update `CONTROL\CHECKPOINT.json` (`--status paused`), verify zero orphan processes remain, give the user a concise status + resume summary, and **STOP cleanly**.
   - **NEVER launch `fluent.exe` directly.** Launch EVERY Fluent Meshing and Fluent Solver run through:
     ```powershell
     & $env:X57_PYTHON "F:\FEA Coursework\Workspace\scripts\run_fluent_managed.py" ...
     ```
     Include Fluent's native checkpoint exit hooks (`(set! checkpoint/exit-filename "exit-fluent")` and periodic `/file/auto-save/`) in EVERY solver journal so a user pause saves `.cas.h5`/`.dat.h5` cleanly with zero wasted compute.
   - Start by checking `control_gate.py status` and `CONTROL\CHECKPOINT.json`. Update `CONTROL\CHECKPOINT.json` as every stage (`S0_ENV_AUDIT` through `S7_DELIVERABLES_PACK`) transitions `in_progress` -> `paused` / `done`.

3. **Zero Fabrication & Complete Physical Honesty**:
   - NEVER invent, smooth over, or hardcode CFD numbers. Every reported value must come directly from converged Ansys Fluent runs and real exported fluid cell/surface data.

---

### 2. MANDATORY WORKSPACE SKILLS & TOOLS (READ FIRST!)

Before starting each phase, read `F:\FEA Coursework\Workspace\AGENTS.md` and ALL 5 pre-authored skills in `F:\FEA Coursework\Workspace\skills\`:
1. `skills\e-drive-isolation-and-control-gate\SKILL.md`
2. `skills\x57-geometry-prep\SKILL.md` *(contains pre-verified ground-truth findings: raw CAD is in **inches** (`× 0.0254 m`), `CW1--X-57_metool.stl` has a baked ~5.41° tilt quaternion that MUST be removed via `R^T` to restore exact `z = 0` symmetry, plus already-verified coordinates for HLP-1..6 & Wingtip WT-1 in `01_geometry\geometry_audit.json`!)*
3. `skills\ansys-fluent-dep-cfd\SKILL.md`
4. `skills\cfd-verification-and-physics-qa\SKILL.md`
5. `skills\postproc-and-deliverables-packager\SKILL.md`

---

### 3. EXECUTION PLAN (STAGES `S0` TO `S7`)

- **Stage `S0_ENV_AUDIT`**: Probe installed **ANSYS Student v252** (`D:\Ansys\ANSYS Inc\ANSYS Student\v252\fluent\ntbin\win64\fluent.exe`) via `run_fluent_managed.py` to confirm exact license cell/node limit (typically `1,048,576` cells/nodes) and max parallel cores (typically `-t4`), verify F:-Drive Isolation, and write `DELIVERABLES\data\environment_and_license.json`.
- **Stage `S1_GEOMETRY`**: Run `scripts\inspect_x57_geometry.py --export-level-stl`, inspect blade pitch/spin sense on the starboard (`+z`) wing, cleanly remove frozen solid propeller blades (keeping spinners, nacelles, pylons, wing, fuselage, sponson, empennage intact), verify open sponson-to-wing clearance at `x = 0, z ≈ 0.86–0.89 m`, create clean named surface regions (`wall_wing`, `wall_fuselage`, `wall_nacelles`, `wall_sponson`, `wall_empennage`), define the `z >= 0` half-aircraft domain (`x ∈ [-18, +30] m`, runway `y = -1.70 m` to `+18 m`, `z ∈ [0, +20] m`), and place the 7 actuator-disk regions (6 HLPs + 1 WT-1). Save a multi-view visual check PNG in `01_geometry\`.
- **Stage `S2_MESH_STUDY`**: Generate **3 systematically refined Poly-Hexcore meshes** (`coarse`, `medium`, `fine`) strictly inside the ANSYS Student cell limit (e.g., ~280k / ~560k / ~920k half-aircraft cells if cap is 1.048M; scale proportionally if cap differs):
  - Cartesian **hex elements in the far field** & wake BOIs.
  - **Prism inflation layers** on all aircraft surfaces targeting **`y+ ≈ 1`** on the blown wing.
  - Verify orthogonal quality (`> 0.10`, target `> 0.15`), prism coverage, and **open sponson clearance** (never bridged by wrapping!).
- **Stage `S3_SOLVER_MESH_CONVERGENCE`**: Solve `coarse_rpm100`, `medium_rpm100`, and `fine_rpm100` (all **Swirl ON**, 5400 RPM HLPs / 2700 RPM wingtip prop, ideal gas air `rho_ref = 1.225 kg/m³`, `mu = 1.789e-5 kg/(m·s)`, `P_op = 101325 Pa`, `k-omega SST`, Coupled pseudo-transient, 2nd-order upwind, BEMT-calibrated Actuator-Disk axial + tangential swirl via Fluent Named Expressions). Verify discrete disk thrust/torque integrals, residual & last-200-iter force stability, global mass flux balance, `y+` statistics, and 3-grid Roache **GCI / Richardson extrapolation**!
- **Stage `S4_RPM_AND_SWIRL_SWEEP`**: On the matched `medium` grid (initialized from converged `medium_rpm100`), solve:
  1. `medium_rpm050` (50% RPM: 2700 HLP / 1350 wingtip, Swirl ON)
  2. `medium_rpm075` (75% RPM: 4050 HLP / 2025 wingtip, Swirl ON)
  3. `medium_rpm100_noswirl` (100% RPM, Swirl OFF — axial thrust only)
  Verify `s^2` quadratic scaling (`R^2`, collapse of `D_air/s^2` and `|L_air|/s^2`) and extract spanwise wing load shift `Delta(dL/dz) = Swirl ON - Swirl OFF`.
- **Stage `S5_POSTPROC_EXTRACTION`**: Extract real fluid cell/node data from Fluent (NEVER interpolating blindly through solid bodies!) for spanwise slices (`z = z_HLP1`, `z_HLP3`, `z_WT`), horizontal planes (`y ≈ +0.003 m` HLP thrust axis & `y ≈ +0.225 m` above wing), transverse swirl wake plane (`x ≈ 1.20 m`), wing surface `Cp` & pressure distributions (identifying exact global peak suction coordinates & `C_p,min`), spanwise sectional loading `dL/dz`, and render all **6 native Fluent 3D high-resolution PNG views** (farfield hexcore mesh, wing prism inflation close-up, 3D **Pathlines** of propeller slipstreams, 3D **Pathlines** of wingtip vortices, 3D aircraft pressure contours, 3D velocity streamlines).
- **Stage `S6_FIGURES_AND_QA`**: Generate all **8 publication-grade Times New Roman matplotlib figures** (dual `.png` @ 400 DPI + vector `.pdf`) strictly following `skills\postproc-and-deliverables-packager\SKILL.md`, with clean **solid-body masking** (`[Solid bodies masked]`), mirrored full-aircraft planform views (`[Mirrored Full Aircraft]`), and complete physics QA verification.
- **Stage `S7_DELIVERABLES_PACK`**: Populate `F:\FEA Coursework\Workspace\DELIVERABLES\` completely, verify that the Ansys submission attachments reload cleanly in Fluent, write `DELIVERABLES_MANIFEST.json` and `handoff_notes.md`, and run `verify_deliverables.py` until it exits with code `0`.

---

### 4. EXPLICIT FINAL DELIVERABLES CONTRACT (DEFINITION OF DONE)

Everything below MUST exist under `F:\FEA Coursework\Workspace\DELIVERABLES\` and pass `scripts\verify_deliverables.py` with exit code `0`:

1. **Master Index & Technical Handoff**:
   - `DELIVERABLES\DELIVERABLES_MANIFEST.json` — machine-readable index of all files, case matrix, headline aerodynamic/propulsive metrics, and QA pass flags.
   - `DELIVERABLES\handoff_notes.md` — comprehensive technical log (Ansys Student v252 exact version/caps, coordinate & unit restoration details, BEMT actuator-disk equations & verification, BC/solver/mesh details, convergence & GCI interpretation, honest physical explanation of static lift/suction/swirl behavior, and quantitative engineering recommendations for high-lift modifications: flaps, slats, camber, HLP vertical alignment).

2. **Verified Quantitative Data (`DELIVERABLES\data\`)**:
   - `environment_and_license.json`
   - `geometry_audit.json`
   - `actuator_disk_model.json`
   - `summary_metrics.json` *(full-aircraft & half-domain `L_air`, `L_wing`, `D_air`, `T_gross`, `T_net`, `C_L`, `C_D`, `q_ref`, `V_ref`, `S_ref`, peak suction `(x,y,z)` & `C_p,min`, GCI metrics, RPM quadratic `R^2`, Swirl ON vs OFF delta)*
   - `mesh_convergence.csv` *(Coarse / Medium / Fine cells, ortho quality, `y+`, forces, coefficients, GCI)*
   - `rpm_sweep.csv` *(0%, 50%, 75%, 100% Swirl ON + 100% Swirl OFF)*
   - `yplus_stats.csv` *(mean, median, p95, max `y+` per component & grid)*
   - `wing_cp_sections.csv` *(upper & lower surface `x/c`, `C_p`, `p_gauge` at >= 5 spanwise stations)*
   - `spanwise_loading.csv` *(`z`, `dL/dz` for `fine_rpm100`, `medium_rpm100`, `medium_rpm100_noswirl`, and `Delta(dL/dz)`)*
   - `convergence_qa.csv` *(final residuals, mass imbalance %, last-200-iter force means & std devs for all 6 cases)*

3. **Publication-Grade Matplotlib Figures (`DELIVERABLES\figures\`, BOTH `.png` and `.pdf` for every figure)**:
   - `fig01_geometry_and_domain.png/.pdf`
   - `fig02_mesh_convergence_and_yplus.png/.pdf`
   - `fig03_convergence_histories.png/.pdf`
   - `fig04_spanwise_slices_vel_press.png/.pdf` *(2×3 solid-masked velocity + white streamlines & matched gauge pressure at HLP-1/sponson, HLP-3, and Wingtip)*
   - `fig05_horizontal_planes_blown_wing.png/.pdf` *(1×2 solid-masked mirrored full-aircraft velocity planes: HLP thrust axis beneath wing & above-wing plane)*
   - `fig06_wing_cp_and_suction.png/.pdf` *(chordwise `C_p` sections + wing surface `C_p` map highlighting global lowest pressure / highest suction)*
   - `fig07_rpm_sweep_scaling.png/.pdf` *(1×2 RPM sweep forces with `s^2` fits + no-swirl marker, and `T_gross`/`T_net` with `D_air/s^2` & `|L_air|/s^2` collapse inset)*
   - `fig08_swirl_comparison_and_load_shift.png/.pdf` *(1×3 downstream transverse plane Swirl ON vs Swirl OFF + wing spanwise load shift `Delta(dL/dz)`)*

4. **Native Fluent 3D High-Res Renders (`DELIVERABLES\fluent_renders\`, `>= 1920x1080` PNG)**:
   - `render01_mesh_farfield_hexcore.png`
   - `render02_mesh_wing_inflation_closeup.png`
   - `render03_pathlines_slipstreams_3d.png`
   - `render04_pathlines_wingtip_vortex_3d.png`
   - `render05_surface_pressure_contour_3d.png`
   - `render06_velocity_streamlines_3d.png`

5. **Coursework Attachment Ansys Files (`DELIVERABLES\ansys_submission\`, verified HDF5 & reloadable)**:
   - `X57_DEP_fine_rpm100.msh.h5`
   - `X57_DEP_fine_rpm100.cas.h5`
   - `X57_DEP_fine_rpm100.dat.h5`

Begin now with `env_f_only.ps1`, `control_gate.py status`, reading `AGENTS.md` and the 5 skills, and executing Stage `S0_ENV_AUDIT`.
