"""Execute in the native Fluent 2025 R2 2ddp solver after reading a section mesh or checkpoint."""
import csv
import json
import os
import sys
from pathlib import Path

workspace = Path(os.environ["X57_WORKSPACE"]).resolve()
work = Path.cwd().resolve()
if work.parent != workspace / "03_cases":
    raise ValueError("Section run must use its workspace case directory")
sys.path.insert(0, str(Path(os.environ["FLUENT_PROD_DIR"]) / "cortex/pylib"))
import flsetup
flsetup.insert_pyfluent_module_path()
from flapi.flproxy import Proxy
from flapi.generated.solver.settings_252 import root

cfg = json.loads((work/"section_config.json").read_text())
run = json.loads((work/"section_run.json").read_text())
s = root()
s.set_flproxy(Proxy)
boundary = s.setup.boundary_conditions
reports = s.solution.report_definitions
inlet = cfg["inlet_profile"]
stem = run["stem"]
airfoils = sorted(name for name in boundary.wall.get_object_names() if name.startswith("wall_"))
if "wall_main" not in airfoils:
    raise ValueError(f"Missing the main airfoil in {airfoils}")


def pick(option, *tokens):
    def norm(x):
        return "".join(c for c in x.lower() if c.isalnum())
    choices = option.allowed_values()
    for token in tokens:
        for choice in choices:
            if norm(choice) == norm(token):
                option.set_state(choice)
                return
    raise ValueError(f"{tokens} absent from active Fluent choices {choices}")


def set_profile(variable, name, field):
    pick(variable.option, "profile")
    variable.profile_name.set_state(name)
    variable.field_name.set_state(field)


if not run["resume"]:
    s.setup.models.energy.enabled = True
    visc = s.setup.models.viscous
    visc.model = "k-omega"
    visc.k_omega_model = "sst"
    visc.options.curvature_correction.enabled = True
    visc.options.production_limiter.enabled = True
    air = s.setup.materials.fluid["air"]
    air.density.option = "ideal-gas"
    air.viscosity.option = "constant"
    air.viscosity.value = 1.789e-5
    s.setup.general.operating_conditions.operating_pressure = 101325
    s.file.read_profile(file_name=inlet["profile_file"])
    for band in inlet["open_bands"]:
        face = boundary.velocity_inlet[band["zone"]]
        pick(face.momentum.velocity_specification_method, "Components")
        field_name = band["profile"]
        for i, component in enumerate(("u", "v")):
            set_profile(face.momentum.velocity_components[i], field_name, component)
        pick(face.turbulence.turbulence_specification, "K and Omega", "K and Specific Dissipation Rate")
        set_profile(face.turbulence.turbulent_kinetic_energy, field_name, "k")
        set_profile(face.turbulence.specific_dissipation_rate, field_name, "omega")
        face.thermal.temperature.value = 288.15
    top = boundary.pressure_inlet["ambient_top"]
    top.momentum.gauge_total_pressure.value = 0.
    top.thermal.total_temperature.value = 288.15
    outlet = boundary.pressure_outlet["outlet"]
    outlet.momentum.gauge_pressure.value = 0.
    outlet.thermal.backflow_total_temperature.value = 288.15
    methods = s.solution.methods
    methods.warped_face_gradient_correction.enable = True
    methods.p_v_coupling.flow_scheme = "Coupled"
    methods.pseudo_time_method.formulation.coupled_solver = "global-time-step"
    disc = methods.spatial_discretization
    disc.gradient_scheme = "least-square-cell-based"
    for eq in ("pressure","density","mom","k","omega","temperature"):
        disc.discretization_scheme[eq] = "second-order" if eq == "pressure" else "second-order-upwind"
    for report, zones, axis in (("section-lift", airfoils,[0,1,0]),("section-drag",airfoils,[1,0,0]),("main-lift",["wall_main"],[0,1,0])):
        reports.force[report] = dict(zones=zones,force_vector=axis)
    reports.moment["section-pitch"] = dict(zones=airfoils,mom_axis=[0,0,1],mom_center=[0,0,0])
    names = ["section-lift","section-drag","main-lift","section-pitch"]
    s.solution.monitor.report_files["section-history"] = dict(report_defs=names,file_name=str(work/"force_history.out"),frequency=1)
    s.solution.monitor.report_plots["section-forces"] = dict(report_defs=names[:3],active=True,frequency=1,title="Section forces per metre span")
    s.solution.monitor.report_plots["section-moment"] = dict(report_defs=names[3:],active=True,frequency=1,title="Pitch moment per metre span")
    for zone in ["ambient_top", "outlet"] + [b["zone"] for b in inlet["open_bands"]]:
        reports.surface["mass-"+zone] = dict(report_type="surface-massflowrate", surface_names=[zone])
    s.solution.initialization.hybrid_initialize()

residual = s.solution.monitor.residual
residual.options.plot = True
residual.options.n_save = max(2000,run["iterations"] + 100)
for name in residual.equations.get_object_names():
    residual.equations[name].check_convergence = False
auto = s.file.auto_save
auto.root_name = str(work/"autosave")
auto.data_frequency = 50
auto.case_frequency = "each-time"
auto.retain_most_recent_files = True
auto.max_files = 2
scale = s.solution.run_calculation.pseudo_time_settings.time_step_method.time_step_size_scale_factor
scale.set_state(run["time_scale"])
actual_scale = float(scale.get_state())
if abs(actual_scale-run["time_scale"]) > 1.e-10:
    raise ValueError("Fluent did not apply the requested pseudo-time scale")
(work/(stem+"_block_controls.json")).write_text(json.dumps({"pseudo_time_scale":actual_scale}),encoding="utf-8")
if not run["resume"]:
    s.file.write_case_data(file_name=str(work/(stem+"_initialized.cas.h5")))
transcript = work/(stem+"_iterations.trn")
s.file.start_transcript(file_name=str(transcript))
import time
iterate_started=time.perf_counter()
s.solution.run_calculation.iterate(iter_count=run["iterations"])
elapsed=time.perf_counter()-iterate_started
s.file.stop_transcript()
(work/(stem+"_iteration_timing.json")).write_text(json.dumps(dict(requested_iterations=run["iterations"],solver_wall_seconds=elapsed)),encoding="utf-8")
s.file.write_case_data(file_name=str(work/(stem+".cas.h5")))

header = None
rows = []
for line in transcript.read_text(errors="replace").splitlines():
    fields = line.split()
    if fields[:2] == ["iter","continuity"] and "time/iter" in fields:
        header = fields[:fields.index("time/iter")]
    elif header and fields and fields[0].isdigit() and len(fields)>=len(header):
        try:
            rows.append([int(fields[0])] + list(map(float,fields[1:len(header)])))
        except ValueError:
            continue
if not header or not rows:
    raise RuntimeError("The native transcript contains no residual records")
with (work/(stem+"_residuals.csv")).open("w",newline="") as stream:
    writer=csv.writer(stream)
    writer.writerow(header)
    writer.writerows(rows)
flux={}
for zone in ["ambient_top","outlet"]+[b["zone"] for b in inlet["open_bands"]]:
    flux[zone]=reports.compute(report_defs=["mass-"+zone])
(work/(stem+"_flux.json")).write_text(json.dumps(flux,indent=2),encoding="utf-8")
print("X57-SECTION-BLOCK-SAVED",stem,flush=True)

