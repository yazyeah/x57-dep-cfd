---
name: cfd-verification-and-physics-qa
description: Rigorous verification, convergence analysis (GCI, y+, mass/momentum balance), sign-convention audit, and anti-hallucination physics QA for the X-57 DEP CFD coursework.
---

# CFD Verification, Convergence & Physics QA

## 1. Zero-Fabrication & Physics Honesty Rules

1. **NEVER fabricate, extrapolate, or alter CFD results.** Every single number written to `DELIVERABLES\data\` MUST be computed directly from converged Fluent solution files / report files / exported cell data.
2. **Double-check all coordinate & force sign conventions**:
   - Coordinate system: `+x` = aft (drag direction), `-x` = forward (thrust direction), `+y` = upward (lift direction), `+z` = starboard.
   - **Half-to-Full Aircraft Factor (`× 2`)**: Because the CFD domain simulates the `z >= 0` half-aircraft, ALWAYS store BOTH half-domain raw Fluent forces AND full-aircraft (`× 2`) forces explicitly in JSON/CSV with unambiguous column names!
   - **Airframe Aerodynamic Forces vs. Propulsive Forces**:
     - `L_air` (full-aircraft wall vertical force, `+y`): `2 * F_y(all aircraft walls)`
     - `L_wing` (wing-only vertical force, `+y`): `2 * F_y(wall_wing)`
     - `D_air` (full-aircraft airframe drag, `+x`): `2 * F_x(all aircraft walls)`
     - `T_gross` (gross static propeller thrust, forward `-x` magnitude): `2 * sum(integrated disk thrust)`
     - `T_net` (net forward take-off force): `T_gross - D_air`
   - **Be honest about clean-wing static vertical force!** On a clean un-flapped cruise-configuration NASA X-57 wing at static `V_inf = 0` with underslung HLPs, the high-speed jet contracting beneath the wing lower surface can create strong lower-surface suction — potentially resulting in a small or even negative static vertical force on the clean wing (whereas deflecting trailing-edge flaps turns the blown slipstream downward to generate large positive static lift increment!). Report the **exact converged CFD value and sign**, decompose upper vs. lower surface pressure integration to explain the physical mechanism clearly, and use this exact physical insight to anchor the coursework's **Design Modifications** section (trailing-edge Fowler/slotted flap, leading-edge droop/slat, camber increase, HLP vertical alignment/tilt!).

---

## 2. Reference Scaling for Non-Dimensional Coefficients at `V_inf ≈ 0`

Because freestream taxiing speed is `V_inf ≈ 0`, standard `q_inf = 0.5 * rho * V_inf^2` is zero! You MUST define a clear, physically meaningful, constant reference dynamic pressure `q_ref` and document it everywhere:
- Recommended primary reference: **Area-weighted slipstream reference dynamic pressure** `q_ref = 0.5 * rho_ref * V_ref^2` where `V_ref` is e.g. the nominal momentum-theory mean induced jet velocity across the blown disks (or wingtip/HLP characteristic disk velocity `V_ref = sqrt(T_gross / (2 * rho_ref * A_disks))`, typically ~`20–30 m/s`, OR `q_disk = T_gross / A_disks`), AND wing reference area `S_ref` (full-aircraft wing planform area measured directly from CAD, ~`6.19 m²` for X-57 Mod IV — use exact CAD measured area!).
- Compute and export:
  - Wing pressure coefficient: `C_p = (p_static - p_ref) / q_ref` (also report raw `p_gauge [Pa]` everywhere so results are completely scale-independent!)
  - Lift and Drag coefficients for the mesh convergence study: `C_L = L_air / (q_ref * S_ref)` and `C_D = D_air / (q_ref * S_ref)` (plus wing-only `C_L_wing`, `C_D_wing`, and raw Newtons `L_air`, `L_wing`, `D_air`).
- Record `rho_ref`, `V_ref`, `q_ref`, `S_ref`, `MAC` (mean aerodynamic chord), and `b` (wingspan) in `DELIVERABLES\data\summary_metrics.json`.

---

## 3. Quantitative Acceptance Gates (Must Pass Before Stage Completion)

### Gate A — Iterative Convergence & Strict Lift Stability (Every Case — HARD GATE)
- **Strict Lift & Drag Plateau Stability (Primary Criterion)**:
  - Monitor full-aircraft vertical force (`L_air`), wing vertical force (`L_wing`), and full-aircraft drag (`D_air`) vs. iteration for EVERY case.
  - Over the final **200–300 iterations** (sliding window):
    - **No monotonic drift**: Difference between the final two consecutive 100-iteration window means MUST be `< 0.5%` (target `< 0.3%`), or `< 0.5 N` if the force magnitude is near zero.
    - **Low fluctuation**: Standard deviation over the final 200 iterations MUST be `< 0.5%` of mean (target `< 0.3%`), or `< 1.0 N` if the force magnitude is near zero.
    - If forces are still drifting or oscillating above threshold, reduce the Pseudo-Transient Time Scale Factor / under-relaxation factors and continue iterating until flat and stationary. NEVER terminate early at a fixed iteration cap!
    - If minor physical vortex-shedding periodicity persists despite damped steady settings, run across multiple complete oscillation cycles, verify zero mean drift across cycles, report the cycle-averaged mean + `± sigma` band, and document transparently in `handoff_notes.md`.
- **Residuals**: Continuity `< 1e-3` (target `< 5e-4`) and flat; x/y/z momentum and `k`/`omega` `< 1e-4`; energy `< 1e-6`, under Second Order Upwind discretization.
- **Global Mass Flux Imbalance**: `|m_dot_in + m_dot_out| / m_dot_total < 0.1%` target (hard ceiling `< 0.5%`).
- **Actuator-Disk Source Integral Audit**: Verify discrete Fluent volume integral of axial thrust and torque over every disk matches target `T_disk`, `Q_disk` to `< 1.0%` (target `< 0.5%`).
- **Auditable Evidence**: Export per-case residuals, mass imbalance %, last-200-iter means, std devs, and window drifts to `DELIVERABLES\data\convergence_qa.csv`, AND plot BOTH residuals and force histories (annotated with the final 200-iter steady window mean and `± sigma` band) in `fig03_convergence_histories.png/.pdf`.

### Gate B — Boundary Layer (`y+`) Audit (`coarse`, `medium`, `fine`)
- Compute area-weighted mean `y+`, median `y+`, 95th percentile `y+`, and max `y+` separately on `wall_wing` and full aircraft walls.
- Target on `fine_rpm100`: `wall_wing` area-weighted mean `y+ ≈ 0.5 – 1.5`, 95th percentile `< 3.0`. Export full `y+` histogram/table to `DELIVERABLES\data\yplus_stats.csv`.

### Gate C — 3-Grid Mesh Convergence & GCI (`coarse_rpm100`, `medium_rpm100`, `fine_rpm100`)
- Effective grid size `h = (V_domain / N_cells)^(1/3)` (or local aircraft/BOI cell spacing), refinement ratios `r_21 = h_coarse / h_medium`, `r_32 = h_medium / h_fine`.
- Compute apparent order of convergence `p`, Richardson-extrapolated value `phi_ext`, and Roache Grid Convergence Index `GCI_fine` (`Fs = 1.25` for 3 grids) for `L_air`, `L_wing`, `D_air`, `C_L`, `C_D`.
- Also verify **wrapped geometric fidelity** (e.g., sponson clearance at `x = 0, z = z_HLP1` matches CAD within `< 5 mm` on Fine grid).

### Gate D — RPM Scaling & Swirl Physics Checks
- **RPM Sweep (`s = 0.50, 0.75, 1.00`)**: Fit `L_air(s) = a_L * s^2`, `L_wing(s) = a_Lw * s^2`, `D_air(s) = a_D * s^2`; compute `R^2` (under `s^2` actuator-disk loading at static `V = 0`, aerodynamic forces should collapse closely onto `s^2` scaling, `R^2 > 0.99`!) and check dimensionless collapse of `D_air / s^2` and `|L_air| / s^2`.
- **Swirl Isolation (`medium_rpm100` vs `medium_rpm100_noswirl`)**: Extract spanwise wing sectional lift `dL_wing/dz(z)` for both cases and compute `Delta(dL/dz) = (dL/dz)_SwirlON - (dL/dz)_SwirlOFF`, separating inboard HLP swirl peaks/troughs vs. outboard wingtip counter-rotating swirl gain!
- **Peak Suction Location**: Identify exact `(x, y, z)`, spanwise fraction `2z/b`, chordwise fraction `x/c`, minimum `p_gauge [Pa]`, and minimum `C_p` on the wing surface!
