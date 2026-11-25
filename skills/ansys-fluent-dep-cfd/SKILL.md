---
name: ansys-fluent-dep-cfd
description: Complete ANSYS Student v252 Fluent Meshing and Solver playbook for the NASA X-57 DEP aircraft at static taxiing (V~0), covering Student license limits, Poly-Hexcore + y+~1 inflation, k-omega SST, Actuator-Disk with Swirl, simulation matrix, and checkpoint/resume journals.
---

# ANSYS Fluent v252 (Student Edition) DEP Aircraft CFD Playbook

## 1. Environment & License Constraints (CRITICAL — Verify in Stage S0!)

- **Installed Solver**: `D:\Ansys\ANSYS Inc\ANSYS Student\v252\fluent\ntbin\win64\fluent.exe`
- **Hardware**: Intel Core i7-14650HX (16C/24T), **15.7 GB RAM**, RTX 4060 Laptop GPU, **~48 GB free on E:**.
- **ANSYS Student v252 Hard Caps (MUST verify empirically in Stage S0!)**:
  - **Cell/Node Limit**: Typically **1,048,576 (1M) cells/nodes** in Ansys Student 2025 R2 (older versions were 512k). Run a quick Stage S0 license probe in `00_env_audit\` to log the exact cell/node cap and max parallel cores (typically **`-t4`** for ANSYS Student!).
  - **RAM Safety**: With 16 GB system RAM, keep Fluent solver runs at `-t4` (matching Student cap) and `<= 980,000` cells so memory stays comfortably under ~6–8 GB.
- **Locale & Launch Rule**: Always run via `scripts/run_fluent_managed.py` (which enforces `AWP_LOCALE252=en-us`, F:-drive temp dirs, PID registration, and pause/checkpoint watchdog).

---

## 2. Computational Domain & Boundary Conditions

Use a **Half-Aircraft Symmetry Domain (`z >= 0`)** (exact symmetry about `z = 0` for level X-57 with symmetric counter-rotating port/starboard propellers; doubles spatial resolution under the Student cell limit; full aircraft is mirrored in post-processing and clearly labeled!).

### Recommended Domain Extents (meters, restored level frame)
- `x ∈ [-18.0, +30.0] m` (~3.5 aircraft lengths upstream of nose, ~4.8 aircraft lengths downstream of tail for full slipstream & wake development)
- `y ∈ [-1.70, +18.0] m` (bottom plane = runway ground at `y = -1.70 m`; top ~18 m above wing)
- `z ∈ [0.0, +20.0] m` (`z = 0` symmetry plane; starboard farfield ~3.6 semi-spans out)

### Fluid & Operating Conditions (Exact Coursework Specification)
- **Fluid**: Air as **ideal gas** (`ideal-gas` density law; verify `rho_ref = 1.225 kg/m³` at `T_op = 288.15 K`, `P_op = 101325 Pa` -> `rho = P/(R*T) = 101325/(287.058*288.15) = 1.2250 kg/m³`!).
  - Enable Energy Equation (required by Fluent when using `ideal-gas`!). Set farfield total temperature `T_0 = 288.15 K` (confirm `rho ≈ 1.225 kg/m³` in farfield!).
- **Dynamic Viscosity**: Constant `mu = 1.789e-5 kg/(m·s)` (exact coursework value).
- **Operating Pressure**: `101325 Pa` (sea-level static pressure); gauge pressure = `0 Pa` at ambient farfield.

### Boundary Conditions for Static Taxiing (`V_inf ≈ 0`)
- **`symmetry` (`z = 0`)**: `symmetry`
- **`runway_ground` (`y = -1.70 m`)**: Stationary no-slip `wall` (static start of taxiing, ground velocity = `0 m/s`).
- **Aircraft surfaces** (`wall_wing`, `wall_fuselage`, `wall_nacelles`, `wall_sponson`, `wall_empennage`): No-slip adiabatic `wall`.
- **Open Ambient Farfield (`farfield_inlet`, `farfield_top`, `farfield_side`, `farfield_outlet`)**:
  - **Best practice for static hover / taxiing (`V ≈ 0`)**:
    - Upstream / top / side (`farfield_inlet`, `farfield_top`, `farfield_side`): `pressure-inlet` with **Gauge Total Pressure = `0 Pa`** (so ambient stagnant air is drawn in naturally by propeller suction at `p_total = p_atm`, `T_total = 288.15 K`, low turbulence intensity `I = 0.5%`, viscosity ratio `mu_t/mu = 2`, direction normal to boundary or from neighboring cell).
    - Downstream (`farfield_outlet`): `pressure-outlet` with **Gauge Static Pressure = `0 Pa`**, backflow total temperature `288.15 K`, backflow direction normal to boundary (or `from-neighboring-cell` to avoid artificial entrainment resistance), `I = 0.5%`, `mu_t/mu = 2`.
    - **Note on regularization**: Pure `V = 0` works cleanly with `pressure-inlet (p_t=0)` + `pressure-outlet (p_s=0)` because the 7 propellers actively pump flow through the domain! If initial transients cause farfield oscillations, initialize with a gentle axial velocity `u = 0.5 m/s` (then let the `p_t = 0 / p_s = 0` BCs relax naturally to true static entrainment) OR document a tiny taxi regularization (e.g. `V_taxi = 0.1–0.5 m/s` if velocity-inlet is ever needed — prefer true `p_t = 0 Pa` static open boundaries first!).

---

## 3. Meshing Strategy (Poly-Hexcore + `y+ ≈ 1` Inflation + 3-Level Grid Study)

Coursework requirements:
- **Hex elements in the far field** -> Use **Fluent Meshing Poly-Hexcore** (Cartesian hexahedral elements throughout the farfield and BOI wake regions, polyhedral transition only near complex curved junctions!).
- **Inflation layers on aircraft surfaces targeting `y+ ≈ 1`**:
  - Representative local slipstream speed over blown wing: `U_ref ≈ 30–45 m/s`, wing chord `c ≈ 0.65–0.75 m` -> `Re_c ≈ 1.4e6 – 2.2e6`.
  - Flat-plate estimate for `y+ = 1`: `Delta y_1 ≈ 1.1e-5` to `1.8e-5 m` (`0.012 – 0.018 mm`).
  - Use **12–16 prism layers**, growth ratio `1.18–1.22` (last-ratio / smooth-transition checked so total BL thickness covers ~`2–5 mm`), applied on `wall_wing`, `wall_fuselage`, `wall_nacelles`, `wall_sponson`, `wall_empennage`.
  - Verify actual area-weighted mean `y+` and `95th percentile y+` on `wall_wing` after solving — target wing mean `y+ ≈ 0.5 – 1.5`!
- **Wake & Actuator-Disk Refinement (Bodies of Influence — BOIs)**:
  - BOI-1 (Propeller Disks): fine local sizing around all 6 HLPs + wingtip disk (`x ∈ [-0.95, -0.50] m`) so each disk has `>= 4–6` axial cells and `>= 14` radial cells.
  - BOI-2 (Blown Wing & Near Slipstream): `x ∈ [-1.1, +2.5] m`, `y ∈ [-1.0, +0.9] m`, `z ∈ [0.0, +5.8] m` to cleanly resolve wing circulation, nacelle-wing interaction, sponson gap, and slipstream contraction.
  - BOI-3 (Mid Wake & Empennage): `x ∈ [-1.5, +6.5] m`, `y ∈ [-1.7, +1.5] m`, `z ∈ [0.0, +6.5] m`.
- **3-Level Systematic Mesh Convergence Study (Strictly Under Student Cell Limit!)**:
  Assume Student limit = `1,048,576` cells (adjust proportionally if Stage S0 reveals `512,000`!). Target:
  - **Coarse (`coarse`)**: `~260k – 330k` cells (half-aircraft; equivalent `~520k – 660k` full aircraft)
  - **Medium (`medium`)**: `~520k – 620k` cells (half-aircraft; equivalent `~1.04M – 1.24M` full aircraft; grid refinement ratio `r_21 ≈ 1.25`)
  - **Fine (`fine`)**: `~860k – 960k` cells (half-aircraft; equivalent `~1.72M – 1.92M` full aircraft; grid refinement ratio `r_32 ≈ 1.20`; safely below 1,048,576 cap!)
  - Keep **identical topology & first-layer `y+ ≈ 1` strategy** across grids while systematically refining surface sizes & BOI volume sizes, and check **minimum orthogonal quality > 0.10** (target `> 0.15`) and **sponson open clearance** on every grid!

---

## 4. Turbulence & Propeller Modelling (Actuator-Disk with Swirl)

### Turbulence Model
- **`k-omega SST`** (Shear Stress Transport, Menter): industry standard for adverse pressure gradients, high-curvature wing leading edges, nacelle-wing junction flows, and swirling propeller wakes; directly resolves the viscous sublayer when `y+ ≈ 1`. Enable **Production Limiter** (and optionally **Curvature Correction** for swirling slipstreams — log exact setting!).

### Propeller Model: Actuator-Disk with Axial Thrust + Tangential Swirl
State clearly why Actuator-Disk with Swirl is chosen:
1. Directly captures both **axial slipstream acceleration/contraction** AND **azimuthal swirl velocity (upwash/downwash asymmetry across wing & wingtip vortex attenuation)** without requiring 20–40M cells to resolve 14 spinning 3D blade boundary layers (impossible under Student 1M cell limit).
2. Implemented cleanly in Fluent 2025 R2 via **Named Expressions volumetric momentum sources** (`x-momentum`, `y-momentum`, `z-momentum`) inside the 7 thin disk regions (thickness `t_d ≈ 0.04–0.06 m`, annular `R_hub <= r <= R_tip`) — zero external C compiler required, 100% reproducible, and natively differentiable/scalable with speed fraction `s = RPM / RPM_nom`!

### Physics-Based Calibration of Disk Loading (BEMT / Momentum Theory)
Calibrate the 6 HLPs (`5400 RPM` nominal, `R_tip ≈ 0.288 m` or exact CAD `R_tip`) and 1 Wingtip Cruise Prop (`2700 RPM` nominal, `R_tip ≈ 0.762 m` or exact CAD `R_tip`) from published NASA X-57 Mod III/IV geometry & static hover/take-off BEMT (Goldstein / radial-weighted thrust & torque distribution):
- Radial distribution (Goldstein-type, vanishing smoothly at hub `r = R_hub` and tip `r = R_tip` to prevent unphysical sharp shear spikes):
  - Normalized radial coordinate: `r_hat = (r - R_hub) / (R_tip - R_hub)` for `r ∈ [R_hub, R_tip]`
  - Thrust weight: `w_T(r_hat) = r_hat * sqrt(1 - r_hat)` (peaks near `r_hat = 0.67`, realistic blade loading!)
  - Torque/swirl weight: `w_Q(r_hat) = sqrt(r_hat * (1 - r_hat))` (or radial `f_theta(r) = (Q_disk / I_Q) * w_Q(r_hat) / r` integrated exactly so total axial force = `T_disk` and total torque = `Q_disk`!)
- **Rotation Direction (NASA X-57 Maxwell Convention — CRITICAL!)**:
  - **Wingtip Cruise Propeller (`WT-1` on `+z` starboard wing)**: **Inboard-Up** rotation! (Counter-rotating against the natural wingtip vortex to reduce induced drag! Looking from behind the aircraft toward nose `-x`, the starboard wingtip propeller rotates **counter-clockwise** so its inboard side sweeps UP `+y` and outboard side sweeps DOWN `-y`, whereas its bottom sweeps outboard `+z` and top sweeps inboard `-z` — verify sign via right-hand rule in `+x` aft, `+y` up, `+z` starboard frame!).
  - **6 HLPs (`HLP-1..6` on `+z` starboard wing)**: Co-rotating **inboard-up** (same sense as starboard wingtip prop — NASA X-57 Mod IV design, or verify twist direction of the actual CAD blades in `CW1--X-57_metool.stl` during Stage S1 and document!).
  - **CHECK CAD BLADE PITCH/TWIST IN STAGE S1**: You have the actual 3D blades in `CW1--X-57_metool.stl`! Inspect blade pitch direction on starboard `+z` wing to confirm exact spin direction and document it in `actuator_disk_model.json`!
- **Static Thrust & Torque Magnitude Calibration (Documented Transparently!)**:
  - Use BEMT (or NASA X-57 published static thrust / power curves at `5400 RPM` HLP & `2700 RPM` wingtip prop):
    - Typical NASA X-57 static take-off thrust at nominal RPM: each HLP ~`220–400 N` (12 HLPs ~`2.6–4.8 kN`), each wingtip prop ~`900–1400 N` (2 wingtip props ~`1.8–2.8 kN`), total gross full-aircraft static thrust `T_gross ≈ 5.0–7.5 kN` (note: reference Figure 13b shows `T_gross ≈ 6.61 kN` at 100% RPM!).
    - Compute exact thrust coefficient `C_T` and torque/power coefficient `C_Q` from a transparent Python BEMT script (`scripts/bemt_calibrate.py`) using the exact CAD blade radii, blade counts (5 blades per HLP, 3 blades per wingtip prop), and NACA/Clark-Y/MH-114 sectional polars, scaling `T(s) = s^2 * T_nom` and `Q(s) = s^2 * Q_nom` across speed fraction `s = RPM / RPM_nom` (`s = 0.50, 0.75, 1.00`)!
    - **Verify in Fluent**: After meshing, compute the exact discrete volume integral of the axial momentum source `∫ S_x dV` and torque `∫ (r × S_theta) dV` over the actual mesh cells in Fluent, and apply any small discretization correction factor (typically `0.98–1.02`) so the discrete Fluent thrust matches `T_disk` to `< 0.5%`!

---

## 5. Solver Settings & Checkpoint-Safe Journal Pattern

- **Pressure-Velocity Coupling**: `Coupled` with **Pseudo-Transient** enabled (automatic time-step scaling or conservative length scale factor `0.5–1.0` for rock-solid convergence at `V ≈ 0`).
- **Spatial Discretization**:
  - Gradient: `Least Squares Cell Based`
  - Pressure: `Second Order`
  - Momentum, Energy, `k`, `omega`: `Second Order Upwind` (can start first 100–150 iterations with First Order Upwind for smooth ramp-up, then switch to Second Order Upwind for at least 600–1200+ iterations until forces & residuals are fully converged!).
- **Mandatory Fluent Graceful-Exit & Auto-Save Setup in EVERY Solver Journal**:
  ```scheme
  ; Enable graceful checkpoint-and-exit when Control Gate drops 'exit-fluent'
  (set! checkpoint/exit-filename "exit-fluent")
  (set! checkpoint/check-filename "check-fluent")
  /file/auto-save/data-frequency 100
  /file/auto-save/case-frequency if-case-is-modified
  /file/auto-save/retain-most-recent-files yes
  /file/auto-save/max-files 2
  ```
  This guarantees that if the user clicks `02_PAUSE_WORK.bat` or `03_STOP_GRACEFUL.bat`, Fluent cleanly writes the latest `.cas.h5`/`.dat.h5` and exits with zero lost iterations!

---

## 6. Complete Simulation Matrix (6 Core Runs)

| Case ID | Grid | HLP RPM | Wingtip RPM | Speed Fraction `s` | Swirl | Purpose |
|---|---|---|---|---|---|---|
| `coarse_rpm100` | Coarse | 5400 | 2700 | `1.00` | ON | Grid Study Level 1 |
| `medium_rpm100` | Medium | 5400 | 2700 | `1.00` | ON | Grid Study Level 2 + Sweep Baseline |
| `fine_rpm100` | Fine | 5400 | 2700 | `1.00` | ON | Grid Study Level 3 + Hero Flowfield & Submission Attachment |
| `medium_rpm050` | Medium | 2700 | 1350 | `0.50` | ON | RPM Scaling Study (50%) |
| `medium_rpm075` | Medium | 4050 | 2025 | `0.75` | ON | RPM Scaling Study (75%) |
| `medium_rpm100_noswirl` | Medium | 5400 | 2700 | `1.00` | OFF | Swirl Isolation Control Case |

*(Tip: Initialize `medium_rpm050`, `medium_rpm075`, and `medium_rpm100_noswirl` directly from the converged `medium_rpm100` data file to cut convergence time in half!)*
