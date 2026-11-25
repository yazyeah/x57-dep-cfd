---
name: x57-geometry-prep
description: Verified geometry audit, coordinate restoration, unit conversion, blade removal, actuator-disk zone placement, and boundary naming for the NASA X-57 Maxwell DEP coursework CAD files (CW1-X-57.glb and CW1--X-57_metool.stl).
---

# X-57 DEP Aircraft Geometry Audit & Preparation

## 1. Ground-Truth Geometry Findings (Pre-Verified)

Both provided files in `F:\FEA Coursework\` (READ-ONLY — never edit originals!) represent the exact same 1,369,522-triangle NASA X-57 Maxwell geometry:
- `F:\FEA Coursework\CW1-X-57.glb`: glTF 2.0 (Draco-compressed), 1 node (`x57`), 1 mesh (`x57`), `4,108,566 / 3 = 1,369,522` triangles.
- `F:\FEA Coursework\CW1--X-57_metool.stl`: Binary STL, `1,369,522` triangles (`68,476,184` bytes).

### CRITICAL FINDING #1 — Units are INCHES, NOT Meters!
- Raw coordinate span in the files is `X: 342.60`, `Y: 92.19`, `Z: 432.588`.
- Multiplying by `0.0254 m/in` yields the exact real-world NASA X-57 Maxwell dimensions:
  - Total length (`X`): `8.702 m` (`x ∈ [-3.5321, +5.1699] m`, nose at `-x`, tail at `+x`, `+x` = aft/streamwise).
  - Total height (`Y`): `2.341 m` (`y ∈ [-1.0995, +1.2419] m`, `+y` = vertically upward; flat fuselage belly at `y ≈ -1.100 m`).
  - Total span including wingtip propeller blades (`Z`): `10.988 m` (`z ∈ [-5.4939, +5.4939] m`, wingtip prop hub at `z = ±4.819 m`, exact wing span `~9.64 m`).

### CRITICAL FINDING #2 — Baked Tilt Quaternion in `CW1--X-57_metool.stl`
- `CW1-X-57.glb` Node 0 carries an export viewport rotation quaternion:
  `q = [qx, qy, qz, qw] = [-0.0030793173, -0.0006708748, 0.0471761860, 0.9988816380]`
  corresponding to `roll(X) = -0.356°`, `yaw(Y) = -0.060°`, `pitch(Z) = +5.408°`.
- `CW1--X-57_metool.stl` has this rotation **baked into its vertices**, tilting the fuselage belly and breaking `z = 0` symmetry (`z ∈ [-5.4975, +5.4901] m`).
- Applying the inverse rotation `R^T` (`v_level = v_stl @ R`) and scaling by `0.0254` restores the **exact level, `z = 0`-symmetric CAD frame** (`z ∈ [-5.4939, +5.4939] m`, matching GLB local accessor bounds to `< 0.2 mm`)!
- **ALWAYS document this coordinate & unit restoration explicitly** in `01_geometry/geometry_audit.json` and `DELIVERABLES/handoff_notes.md`.

### CRITICAL FINDING #3 — Reference Frame, Runway Plane & Pre-Verified Propeller Table
In the restored level metric frame (`01_geometry/geometry_audit.json`, already generated and verified!):
- **`+x`**: Streamwise aft (nose `x = -3.5321 m`, wing leading edge around `x ≈ -0.45 m`, wing trailing edge around `x ≈ +0.30 m`, tail end `x = +5.1699 m`).
- **`+y`**: Vertical up (`+y` = positive lift force). Fuselage belly sits level near `y = -1.0995 m`; main wing lower/upper surfaces span roughly `y ∈ [-0.08, +0.20] m`; all 6 HLP thrust axes lie at **`y = +0.0024 m`** (underslung relative to the wing!), while the wingtip cruise propeller axis lies at **`y = +0.1339 m`**.
- **`+z`**: Starboard wing (`z = 0` is the exact symmetry plane, `|z_max + z_min| = 6e-6 m`!). For the half-aircraft CFD domain, keep **`z >= 0`**.
- **Runway ground plane**: Place at **`y = -1.70 m`** (`0.6005 m` below fuselage belly, realistic X-57/P2006T ground clearance for sea-level static taxiing; check that no blade tip or fuselage part penetrates `y = -1.70 m`!).
- **Verified Starboard (`+z`) Propeller Disk Geometry** (from `01_geometry/geometry_audit.json`):
  | Prop | `x_disk` (m) | `y_axis` (m) | `z_axis` (m) | `R_tip` (m) | `D` (m) | Nominal RPM | Blades |
  |---|---:|---:|---:|---:|---:|---:|---:|
  | `HLP-1` | `-0.6791` | `+0.0024` | `0.8883` | `0.2885` | `0.5770` | `5400` | 5 |
  | `HLP-2` | `-0.6288` | `+0.0024` | `1.4644` | `0.2885` | `0.5770` | `5400` | 5 |
  | `HLP-3` | `-0.6791` | `+0.0024` | `2.0406` | `0.2885` | `0.5770` | `5400` | 5 |
  | `HLP-4` | `-0.5912` | `+0.0024` | `2.6167` | `0.2885` | `0.5770` | `5400` | 5 |
  | `HLP-5` | `-0.6415` | `+0.0024` | `3.1928` | `0.2885` | `0.5770` | `5400` | 5 |
  | `HLP-6` | `-0.5536` | `+0.0024` | `3.7689` | `0.2885` | `0.5770` | `5400` | 5 |
  | `WT-1`  | `-0.5905` | `+0.1339` | `4.8192` | `0.7654` | `1.5309` | `2700` | 3 |
  *(Notice the authentic NASA X-57 axial staggering of HLPs 1–6 and exact `D_HLP = 0.577 m`, `D_WT = 1.531 m`!)*

---

## 2. Step-by-Step Geometry Pipeline (Stage S1)

1. **Run the pre-built auditor script first**:
   ```powershell
   . "F:\FEA Coursework\Workspace\scripts\env_f_only.ps1"
   & $env:X57_PYTHON "F:\FEA Coursework\Workspace\scripts\inspect_x57_geometry.py" --export-level-stl
   ```
   This produces inside `F:\FEA Coursework\Workspace\01_geometry\`:
   - `geometry_audit.json`: exact verified bounding boxes, symmetry error, wing chord/span/planform area estimates, sponson clearance at `x = 0`, and detected axial/vertical/spanwise centers & outer/hub radii for all 6 HLPs (`HLP-1`..`HLP-6`) and the wingtip cruise propeller (`WT-1`) on the `+z` starboard wing.
   - `x57_full_level_meters.stl`: full aircraft in restored level metric frame (`m`).
   - `x57_half_starboard_raw_meters.stl`: `z >= 0` half-aircraft clipped cleanly at `z = 0`.

2. **Exact Propeller Extraction & Blade Removal (for Actuator-Disk CFD)**:
   - Because `CW1--X-57_metool.stl` includes frozen static 5-blade HLPs (6 per wing) and a 3-blade wingtip propeller, **you MUST remove the stationary solid blade triangles** before fluid meshing when using the Actuator-Disk model — otherwise stationary solid blades sit right inside the actuator disk and create huge unphysical blockage drag!
   - Keep the **spinners/hubs, motor nacelles, pylons, wing, fuselage, sponson (main-gear fairing), and empennage** completely intact!
   - Measure and verify from the triangles around each hub:
     - Exact axial plane `x_disk`, vertical axis `y_axis`, spanwise center `z_axis`
     - Exact outer tip radius `R_tip` and spinner/hub root radius `R_hub` (expected: HLP `R_tip ≈ 0.275–0.288 m`, Wingtip `R_tip ≈ 0.75–0.76 m`; ALWAYS use the exact measured CAD values from `geometry_audit.json`!).
   - Verify after blade removal that the remaining nacelle/spinner caps are closed/wrappable (no giant gaping holes at the blade root that let the Fluent Meshing Fault-Tolerant Wrapper leak inside the nacelle!).

3. **Sponson Clearance & Critical Gap Verification**:
   - At `z ≈ 0.86 m` (`HLP-1` station), there is an open vertical clearance (~`0.73–0.78 m`) between the lower main-gear sponson and the HLP-1 nacelle/wing underside.
   - Record the **exact CAD clearance** at `x = 0, z = z_HLP1`, and later verify the **wrapped mesh clearance** on Coarse/Medium/Fine grids so wrapping NEVER bridges the sponson to the wing/nacelle!

4. **Named Surface Regions & Actuator-Disk Fluid Zones**:
   Split or label the half-aircraft surfaces (via Python STL solid regions, SpaceClaim/Discovery script, or Fluent Meshing CAD labels) into clean named wall zones so Fluent can report component-by-component forces and wing-only `Cp` directly:
   - `wall_wing` (ideally split into `wall_wing_upper` and `wall_wing_lower`, or full `wall_wing` cleanly separated from nacelles/fuselage so wing vertical force & wing `Cp` are exact!)
   - `wall_fuselage`
   - `wall_nacelles` (6 HLP nacelles/pylons + wingtip nacelle)
   - `wall_sponson`
   - `wall_empennage` (vertical + horizontal tail)
   - External domain boundaries: `symmetry` (`z = 0`), `runway_ground` (`y = -1.70 m`), `farfield_inlet` / `farfield_outlet` / `farfield_top` / `farfield_side` (or unified open `pressure_farfield` / `pressure_outlet` + `pressure_inlet` as defined in `ansys-fluent-dep-cfd`).
   - 7 thin annular/cylindrical actuator-disk fluid zones (or BOI-refined fluid sub-zones if applying coordinate-masked volumetric momentum sources inside the main fluid zone!):
     - **Pro Tip for Ansys Student v252**: Coordinate-masked volumetric momentum source terms via Fluent Named Expressions inside a single continuous fluid zone (with local cylindrical Bodies of Influence `BOI_disk_1..7` in Fluent Meshing to guarantee >= 4–6 axial cells across disk thickness `t_disk` and >= 12–16 radial cells across `R_tip`) eliminate non-conformal interface failures, avoid extra interior face count overhead under the Student cell limit, and yield silky-smooth pressure jumps across each disk! Alternatively, explicit conformal thin disk cell zones (`disk_hlp1`..`disk_hlp6`, `disk_wingtip`) also work cleanly if conformal interior faces are verified. Whichever you choose, verify exact integrated disk volume and thrust/torque in Fluent!

5. **Visual Sanity Check of Prepared Geometry**:
   Generate a quick multi-view verification PNG (`01_geometry/geometry_prep_check.png`) showing the cleaned half-aircraft (blades removed), the 7 actuator-disk outlines, the `z = 0` symmetry plane, and the `y = -1.70 m` runway plane BEFORE launching Fluent Meshing!
