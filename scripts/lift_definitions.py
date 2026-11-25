"""Side-by-side lift definitions from the accepted native endpoints (report table; never blocks the run).

All values come from real accepted Fluent results. Columns:
  wall_lift_N            aerodynamic lift: pressure + viscous vertical force on every aircraft wall, x2 (PRIMARY)
  wing_lift_N            same, wing walls only
  gross_thrust_N         actuator-disk thrust applied (reaction on the aircraft), x2
  net_force_forward_N    gross thrust - wall drag
  installed_vertical_N   wall lift + vertical actuator reaction (= wall lift for horizontal shafts)
  attitude_retained_vertical_N
                         ANALYTIC ESTIMATE if the 5.408 deg nose-up rotation baked into the supplied CAD were
                         kept as a real ground attitude: rigid rotation of the level-frame body forces,
                         L cos(theta) + (T - D) sin(theta). Flow changes from the tilt are NOT simulated.
  thrust_vertical_component_N  T sin(theta), the part many blade/MRF set-ups count inside "lift" when the
                         CAD tilt is retained.
"""
import json
import math
import sys

import pandas as pd

from compare_x57_cases import ROOT, accepted, load3

CASES = ["coarse_rpm100", "medium_rpm100", "fine_rpm100", "medium_rpm050", "medium_rpm075"]


def main():
    theta_deg = float(json.loads((ROOT / "01_geometry/geometry_audit.json").read_text(encoding="utf-8-sig"))
                      ["baked_stl_rotation_removed"]["approx_euler_deg"]["pitch_z"])
    th = math.radians(theta_deg)
    rows = []
    for name in CASES:
        try:
            qa, _, _ = accepted(name)
            t = load3(name)
        except Exception as exc:  # a missing case is reported, never invented
            rows.append(dict(case=name, status=f"unavailable: {exc.__class__.__name__}"))
            continue
        f = qa["forces_full_aircraft"]
        lift, wing, drag = f["L_air"]["mean_N"], f["L_wing"]["mean_N"], f["D_air"]["mean_N"]
        thrust = -float(t["Fx_actuator_reaction_N"])          # reaction acts forward (-x)
        rows.append(dict(case=name, status="accepted", acceptance_tier=qa.get("acceptance_tier"),
                         wall_lift_N=lift, wall_lift_rel_std=f["L_air"]["relative_std"], wing_lift_N=wing,
                         wall_drag_N=drag, gross_thrust_N=thrust, net_force_forward_N=thrust - drag,
                         installed_vertical_N=float(t["L_installed_N"]),
                         attitude_retained_vertical_N=lift * math.cos(th) + (thrust - drag) * math.sin(th),
                         thrust_vertical_component_N=thrust * math.sin(th), cad_pitch_deg=theta_deg,
                         C_L=t["C_L"], C_D=t["C_D"], q_ref_Pa=t["q_ref_Pa"]))
    frame = pd.DataFrame(rows)
    out = ROOT / "DELIVERABLES" / "data"
    out.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out / "lift_definitions.csv", index=False)
    (out / "lift_definitions.json").write_text(json.dumps(dict(
        primary_definition="wall_lift_N: aerodynamic lift on all aircraft walls in the level (de-rotated) frame",
        attitude_note=(f"The supplied CAD carries a baked {theta_deg:.3f} deg nose-up rotation (with 0.36 deg roll and "
                       "0.06 deg yaw), treated as an export artefact and removed. attitude_retained_vertical_N is an "
                       "analytic rigid-rotation estimate for comparison only; the tilted flow field was not simulated."),
        rows=rows), indent=2, default=str), encoding="utf-8")
    print(frame.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
