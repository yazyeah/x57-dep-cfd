"""Execute inside Fluent 25.2 Cortex after reading the mesh or checkpoint."""
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(os.environ['X57_WORKSPACE'])
CASE = Path.cwd()
CFG = json.loads((CASE / 'solver_config.json').read_text(encoding='utf-8-sig'))
if CASE.resolve().is_relative_to(ROOT / '00_env_audit'):
    fixture = True
else:
    if not CASE.resolve().is_relative_to(ROOT / '03_cases'):
        raise ValueError('Solver work directory outside designated case folders')
    fixture = False
sys.path.insert(0, str(Path(os.environ['FLUENT_PROD_DIR']) / 'cortex/pylib'))
import flsetup
flsetup.insert_pyfluent_module_path()
from flapi.flproxy import Proxy
from flapi.generated.solver.settings_252 import root

s = root()
s.set_flproxy(Proxy)
model = json.loads((ROOT / 'DELIVERABLES/data/actuator_disk_model.json').read_text())
geo = json.loads((ROOT/'01_geometry/geometry_audit.json').read_text())
case_name = CFG.get('case_name', CASE.name)
is_roll = case_name.endswith('_takeoff_v10')
is_oge = case_name.endswith('_oge')
is_rke = case_name.endswith('_rke')
ambient_zones=['farfield_inlet','farfield_top','farfield_side','farfield_outlet']
if is_oge:
    ambient_zones.append('runway_ground')
rotors = model['rotors']
if fixture:
    # Unit-test annulus contains two or four unit-volume cells in the rectilinear mesh.
    rotors = [dict(name='fixture',center_m=[-.5,0,.5],r_hub_m=.1,r_tip_m=1.3,
                   thickness_m=.5,positive_x_spin_sign=1,targets=[dict(s=1,thrust_N=.1,torque_magnitude_Nm=.01)])]

def write_record(name,value):
    path=CASE/name
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
    tmp.replace(path)

def named(name, definition):
    s.setup.named_expressions[name]={'definition':definition}
    return name

def scalar(name, definition):
    named(name,definition)
    value=float(s.setup.named_expressions[name].get_value())
    if not math.isfinite(value):
        raise ValueError(f'Nonfinite field integral {name}')
    return value

def apply_disks():
    fluids = s.setup.cell_zone_conditions.fluid
    locations = repr(fluids.get_object_names())
    report=[]
    combined=[[],[],[]]
    for idx,p in enumerate(rotors,1):
        pref=f'Dep{idx}'
        x0,y0,z0=p['center_m']
        hub,tip=p['r_hub_m'],p['r_tip_m']
        thick=p['thickness_m']
        xloc=f'(x-({x0:.13g} [m]))'
        dy=named(pref+'Y',f'y-({y0:.13g} [m])')
        dz=named(pref+'Z',f'z-({z0:.13g} [m])')
        # The vectoring study rotates the momentum vector and its supporting annulus.
        # The positive radial basis in the x-y plane remains orthogonal to the thrust axis.
        hlp=p['name'].startswith('HLP')
        tilt=math.radians(10.0 if hlp and case_name=='medium_opt_hlp_vector10' else 0.)
        cosine,sine=math.cos(tilt),math.sin(tilt)
        axial=named(pref+'Axial',f'{cosine:.16g}*{xloc}-{sine:.16g}*{dy}')
        radial_y=named(pref+'RadialY',f'{sine:.16g}*{xloc}+{cosine:.16g}*{dy}')
        radius=named(pref+'Radius',f'sqrt({radial_y}**2+{dz}**2)')
        h=named(pref+'Ratio',f'max(0,min(1,({radius}-{hub:.13g} [m])/{tip-hub:.13g} [m]))')
        inside=named(pref+'Mask',f'IF(abs({axial})<={thick/2:.13g} [m],1,0)')
        # Clamped h makes weights zero inside the spinner and outside the disk.
        wt=named(pref+'ThrustWeight',f'{inside}*{h}*sqrt(1-{h})')
        wq=named(pref+'TorqueWeight',f'{inside}*sqrt({h}*(1-{h}))')
        vt=scalar(pref+'ThrustVolume',f'VolumeInt({wt},{locations})')
        vq=scalar(pref+'TorqueVolume',f'VolumeInt({wq},{locations})')
        if min(vt,vq)<=0:
            raise ValueError(f'{p["name"]} has zero fluid-cell support. Inspect cell sizing and disk coordinates.')
        nom=p['targets'][-1]
        active=not ((case_name.endswith('_wt_only') and hlp) or (case_name.endswith('_hlp_only') and not hlp))
        speed2=CFG['s']**2*int(active)
        sense=p['positive_x_spin_sign']
        if case_name.endswith('_alt_swirl') and hlp and int(p['name'].split('-')[-1])%2==0:
            sense=-sense
        thrust=nom['thrust_N']*speed2
        torque=nom['torque_magnitude_Nm']*speed2*sense*int(CFG['swirl'])
        normal_source=named(pref+'Fn',f'{thrust/vt:.15g} [N m^-3]*{wt}')
        amp=named(pref+'SwirlAmplitude',f'{torque/vq:.15g} [N m^-2]*{wq}/max({radius},{hub:.13g} [m])**2')
        fb=named(pref+'Fb',f'-{amp}*{dz}')
        fx=named(pref+'Fx',f'{cosine:.16g}*{normal_source}+{sine:.16g}*{fb}')
        fy=named(pref+'Fy',f'-{sine:.16g}*{normal_source}+{cosine:.16g}*{fb}')
        fz=named(pref+'Fz',f'{amp}*{radial_y}')
        tdis=scalar(pref+'AppliedThrust',f'VolumeInt({cosine:.16g}*{fx}-{sine:.16g}*{fy},{locations})')
        qdis=scalar(pref+'AppliedTorque',f'VolumeInt({radial_y}*{fz}-{dz}*({sine:.16g}*{fx}+{cosine:.16g}*{fy}),{locations})')
        if abs(tdis-thrust)>max(1e-9,.005*abs(thrust)) or abs(qdis-torque)>max(1e-9,.005*abs(torque)):
            raise ValueError(f'{p["name"]} disk integral mismatch')
        force_values=[scalar(pref+'IntegratedF'+axis,f'VolumeInt({term},{locations})')
                      for axis,term in zip('XYZ',(fx,fy,fz))]
        moment_terms=[f'{dy}*{fz}-{dz}*{fy}',f'{dz}*{fx}-{xloc}*{fz}',f'{xloc}*{fy}-{dy}*{fx}']
        moment_values=[scalar(pref+'IntegratedM'+axis,f'VolumeInt({term},{locations})')
                       for axis,term in zip('XYZ',moment_terms)]
        if not math.isclose(cosine*force_values[0]-sine*force_values[1],tdis,rel_tol=1e-7,abs_tol=1e-8):
            raise ValueError(f"{p['name']} force projection disagrees with native thrust")
        if not math.isclose(cosine*moment_values[0]-sine*moment_values[1],qdis,rel_tol=1e-7,abs_tol=1e-8):
            raise ValueError(f"{p['name']} moment projection disagrees with native torque")
        report.append(dict(center_m=[x0,y0,z0],discrete_force_vector_N=force_values,
                           discrete_moment_about_center_Nm=moment_values,vector_load_convention='Momentum source on fluid; negate for structural reaction.',
                           name=p['name'],active=active,spin_sign=sense,thrust_axis=[cosine,-sine,0.0],thrust_target_N=thrust,torque_target_Nm=torque,
                           raw_thrust_weight_volume_m3=vt,raw_torque_weight_volume_m3=vq,
                           discrete_thrust_N=tdis,discrete_torque_Nm=qdis))
        for bucket,item in zip(combined,(fx,fy,fz)):
            bucket.append(item)
    for idx,axis in enumerate('xyz'):
        name=named('DepSource'+axis.upper(),'+'.join(combined[idx]))
        for zone in fluids.get_object_names():
            sources=fluids[zone].sources
            sources.enable=True
            term=sources.terms[axis+'-momentum']
            term.resize(size=1)
            term[0].option='value'
            term[0].value=name
    write_record('fluent_discrete_disk_integrals.json',report)
    write_record('fluent_named_expressions.json',s.setup.named_expressions.get_state())

def set_enum(option, requested):
    """Resolve spelling variations against the active settings API options."""
    compact=lambda value: ''.join(ch for ch in value.casefold() if ch.isalnum())
    choices=option.allowed_values()
    for value in choices:
        if compact(value)==compact(requested):
            option.set_state(value)
            return
    raise ValueError(f'Choice {requested!r} outside available options {choices}')

ORDER_EQUATIONS=['density','mom','k','epsilon' if is_rke else 'omega','temperature']

def set_scheme_order(first):
    """Switch convective schemes; first-order is used only for short warm-up/recovery spans."""
    disc=s.solution.methods.spatial_discretization
    applied={}
    for eq in ORDER_EQUATIONS:
        value='first-order-upwind' if first else 'second-order-upwind'
        try:
            disc.discretization_scheme[eq]=value
            applied[eq]=value
        except Exception as exc:  # equation absent for this model
            applied[eq]=f'unchanged ({exc.__class__.__name__})'
    try:
        disc.discretization_scheme['pressure']='standard' if first else 'second-order'
        applied['pressure']='standard' if first else 'second-order'
    except Exception as exc:
        applied['pressure']=f'unchanged ({exc.__class__.__name__})'
    return applied

def robust_numerics():
    """Fluent-native stabilisation for the few low orthogonal-quality cells of a faceted CAD mesh."""
    record={}
    methods=s.solution.methods
    try:
        pmn=methods.poor_mesh_robustness.poor_mesh_numerics
        pmn.enable=True
        pmn.orthogonal_quality_threshold_enabled=True
        pmn.orthogonal_quality_threshold=0.05
        record['poor_mesh_numerics']=pmn.get_state()
    except Exception as exc:
        record['poor_mesh_numerics']=f'unavailable: {exc}'
    try:
        methods.high_order_term_relaxation.enable=True
        record['high_order_term_relaxation']=methods.high_order_term_relaxation.get_state()
    except Exception as exc:
        record['high_order_term_relaxation']=f'unavailable: {exc}'
    write_record('solver_robustness.json',record)
    print('X57-ROBUST-NUMERICS',json.dumps(record,default=str)[:400],flush=True)
    return record

def configure():
    s.setup.models.energy.enabled=True
    visc=s.setup.models.viscous
    if is_rke:
        visc.model='k-epsilon'
        set_enum(visc.k_epsilon_model,'realizable')
        set_enum(visc.near_wall_treatment.wall_treatment,'enhanced-wall-treatment')
    else:
        visc.model='k-omega'
        visc.k_omega_model='sst'
        visc.options.production_limiter.enabled=True
        visc.options.curvature_correction.enabled=True
    air=s.setup.materials.fluid['air']
    air.density.option='ideal-gas'
    air.viscosity.option='constant'
    air.viscosity.value=1.789e-5
    s.setup.general.operating_conditions.operating_pressure=101325
    bounds=s.setup.boundary_conditions
    types={zone:('pressure_outlet' if zone=='farfield_outlet' else 'pressure_inlet') for zone in ambient_zones}
    if is_roll:
        types={zone:'pressure_far_field' for zone in ambient_zones}
    types['symmetry']='symmetry'
    for zone,ztype in types.items():
        if zone not in getattr(bounds,ztype).get_object_names():
            bounds.set_zone_type(zone_list=[zone],new_type=ztype.replace('_','-'))
    if is_roll:
        mach=10./math.sqrt(1.4*287.058*288.15)
        for zone in ambient_zones:
            bc=bounds.pressure_far_field[zone]
            bc.momentum.gauge_pressure.value=0.
            bc.momentum.mach_number.value=mach
            for i,value in enumerate((1.,0.,0.)):
                bc.momentum.flow_direction[i].value=value
            bc.thermal.temperature.value=288.15
            bc.turbulence.turbulence_specification='Intensity and Viscosity Ratio'
            bc.turbulence.turbulent_intensity=.01
            bc.turbulence.turbulent_viscosity_ratio=5.
        runway=bounds.wall['runway_ground'].momentum
        set_enum(runway.wall_motion,'Moving Wall')
        runway.relative=False
        runway.rotating=False
        runway.speed.value=10.
        for i,value in enumerate((1.,0.,0.)):
            runway.direction[i].value=value
    else:
        for zone in bounds.pressure_inlet.get_object_names():
            bc=bounds.pressure_inlet[zone]
            bc.momentum.gauge_total_pressure.value=0.
            bc.thermal.total_temperature.value=288.15
            bc.turbulence.turbulence_specification='Intensity and Viscosity Ratio'
            bc.turbulence.turbulent_intensity=.01
            bc.turbulence.turbulent_viscosity_ratio=5.
        bc=bounds.pressure_outlet['farfield_outlet']
        bc.momentum.gauge_pressure.value=0.
        set_enum(bc.momentum.backflow_dir_spec_method,'From Neighboring Cell')
        bc.thermal.backflow_total_temperature.value=288.15
        bc.turbulence.turbulence_specification='Intensity and Viscosity Ratio'
        bc.turbulence.backflow_turbulent_intensity=.01
        bc.turbulence.backflow_turbulent_viscosity_ratio=5.
    walls=bounds.wall.get_object_names()
    aft=[name for name in walls if name.startswith('wall_')]
    wing=[name for name in aft if name.startswith('wall_wing')]
    if not wing or (not fixture and ((not is_oge and 'runway_ground' not in walls) or len(aft)<5)):
        raise ValueError(f'Incomplete airframe or runway wall labels {walls}')
    methods=s.solution.methods
    methods.p_v_coupling.flow_scheme='Coupled'
    methods.pseudo_time_method.formulation.coupled_solver='global-time-step'
    methods.warped_face_gradient_correction.enable=True
    disc=methods.spatial_discretization
    disc.gradient_scheme='least-square-cell-based'
    for eq in ['density','mom','k','epsilon' if is_rke else 'omega','temperature','pressure']:
        disc.discretization_scheme[eq]='second-order' if eq=='pressure' else 'second-order-upwind'
    # Half-model forces are doubled outside Fluent; Cp uses one constant disk-induced velocity.
    rr=model['rotors']
    area=sum(math.pi*(p['r_tip_m']**2-p['r_hub_m']**2) for p in rr)
    all_t=sum(p['targets'][-1]['thrust_N'] for p in rr)
    scale=(all_t/(2*model['rho_kg_m3']*area))**.5
    refs=s.setup.reference_values
    refs.velocity=scale
    refs.density=model['rho_kg_m3']
    refs.area=geo['wing_reference']['full_planform_area_m2']/2
    refs.pressure=0.
    refs.temperature=288.15
    refs.viscosity=1.789e-5
    refs.length=geo['wing_reference']['mean_aerodynamic_chord_m']
    reports=s.solution.report_definitions
    names=[]
    for name,zones,vec in [('airframe-lift-half',aft,[0,1,0]),('airframe-drag-half',aft,[1,0,0]),
                            ('wing-lift-half',wing,[0,1,0]),('wing-drag-half',wing,[1,0,0])]:
        reports.force[name]={'zones':zones,'force_vector':vec}
        names.append(name)
    pitch='airframe-pitch-mz-half'
    reports.moment[pitch]={'zones':aft,'mom_center':[0.,0.,0.],'mom_axis':[0.,0.,1.]}
    names.append(pitch)
    if not fixture:
        s.solution.monitor.residual.options.plot=True
        s.solution.monitor.report_plots['x57-force-live']={'report_defs':names[:-1], 'active':True, 'frequency':1, 'title':'Half-aircraft forces [N]'}
        s.solution.monitor.report_plots['x57-moment-live']={'report_defs':[pitch], 'active':True, 'frequency':1, 'title':'Half-aircraft pitching moment about CAD origin [N m]'}
    monitors=s.solution.monitor.report_files
    monitors['x57-forces']={'report_defs':names,'file_name':str(CASE/'force_history.out'),'frequency':1}
    apply_disks()
    write_record('solver_physics.json',dict(methods=methods.get_state(),reference=refs.get_state(),
                 air=air.get_state(),viscous=s.setup.models.viscous.get_state(),
                 half_aircraft_force_reports=reports.force.get_state(),q_ref_Pa=.5*model['rho_kg_m3']*scale**2,
                 moment_reports=reports.moment.get_state(),open_boundaries={z:getattr(bounds,types[z])[z].get_state() for z in ambient_zones},
                 runway=bounds.wall['runway_ground'].momentum.get_state() if 'runway_ground' in walls else None))
    print('X57-PHYSICS-CONFIGURED', flush=True)

if CFG['mode'] != 'resume':
    configure()
    if CFG['s']==0:
        initialization=s.solution.initialization
        initialization.initialization_type='standard'
        defaults=initialization.defaults
        expected={'pressure':0.,'x-velocity':0.,'y-velocity':0.,'z-velocity':0.,'temperature':288.15}
        for variable,value in expected.items():
            if variable not in defaults.get_object_names():
                raise ValueError(f'Standard initialization variable {variable} missing from {defaults.get_object_names()}')
            defaults[variable]=value
        initialization.standard_initialize()
    elif CFG['mode']=='mesh':
        s.solution.initialization.hybrid_initialize()
        if CFG.get('interpolation'):
            s.file.interpolate.read_data(file_name=CFG['interpolation'],cell_zones=s.setup.cell_zone_conditions.fluid.get_object_names())

if not CFG.get('extract_only'):
    pseudo=s.solution.run_calculation.pseudo_time_settings.time_step_method
    requested=CFG.get('pseudo_time_scale')
    if requested is not None:
        set_enum(pseudo.time_step_method, 'automatic')
        pseudo.time_step_size_scale_factor=float(requested)
    effective=float(pseudo.time_step_size_scale_factor.get_state())
    if requested is not None and not math.isclose(effective,requested,rel_tol=1.e-10):
        raise RuntimeError(f'Fluent pseudo-time factor readback {effective} differs from request {requested}')
    write_record(CFG['output_stem']+'_block_controls.json',
                 dict(iterations=CFG['iterations'],input_case=CFG['input_file'],input_data=CFG.get('input_data'),
                      requested_time_scale_factor=requested,effective_time_scale_factor=effective,
                      time_step_method=pseudo.time_step_method.get_state()))
    if not fixture:
        robust_numerics()
    # Apply autosave after reading the current case; reading a file restores its saved settings.
    auto=s.file.auto_save
    auto.data_frequency=100
    auto.case_frequency='each-time'
    auto.retain_most_recent_files=True
    auto.max_files=2
    auto.root_name=str(CASE/'autosave')
    # External acceptance uses 200 contiguous force samples and all residual and flux criteria.
    # Prevent Fluent's default residual-only test from truncating the requested block.
    residual = s.solution.monitor.residual
    residual.options.n_save=max(2000,CFG['iterations']+100)
    for equation in residual.equations.get_object_names():
        residual.equations[equation].check_convergence=False
    if CFG['mode'] != 'resume' and not fixture:
        s.file.write_case_data(file_name=str(CASE/(CFG['output_stem']+'_initialized.cas.h5')))
    s.file.start_transcript(file_name=str(CASE/(CFG['output_stem']+'_iterations.trn')))
    import time
    iterate_started=time.perf_counter()
    warm=int(CFG.get('first_order_iterations') or 0)
    if 0<warm<CFG['iterations']:
        # Short first-order span (initial block or divergence recovery), then the
        # second-order schemes that every accepted endpoint is assessed with.
        write_record(CFG['output_stem']+'_warmup.json',dict(first_order_iterations=warm,
                     first=set_scheme_order(True)))
        s.solution.run_calculation.iterate(iter_count=warm)
        set_scheme_order(False)
        s.solution.run_calculation.iterate(iter_count=CFG['iterations']-warm)
    else:
        s.solution.run_calculation.iterate(iter_count=CFG['iterations'])
    iterate_seconds=time.perf_counter()-iterate_started
    s.file.stop_transcript()
    write_record(CFG['output_stem']+'_iteration_timing.json',
                 dict(requested_iterations=CFG['iterations'], solver_wall_seconds=iterate_seconds))
    s.file.write_case_data(file_name=str(CASE/(CFG['output_stem']+'.cas.h5')))

if (CASE/(CFG['output_stem']+'_iterations.trn')).is_file():
    import csv
    tr=(CASE/(CFG['output_stem']+'_iterations.trn')).read_text(errors='replace')
    header=None
    history=[]
    for line in tr.splitlines():
        vals=line.split()
        if vals[:2]==['iter','continuity'] and 'time/iter' in vals:
            header=vals[:vals.index('time/iter')]
        elif header and len(vals)>=len(header) and vals[0].isdigit():
            try:
                history.append([int(vals[0])]+[float(n) for n in vals[1:len(header)]])
            except ValueError:
                continue
    if not header or not history:
        raise RuntimeError('Fluent transcript has no scaled residual history')
    with (CASE/(CFG['output_stem']+'_residuals.csv')).open('w',newline='') as stream:
        out=csv.writer(stream)
        out.writerow(header)
        out.writerows(history)
elif not CFG.get('extract_only'):
    raise RuntimeError('Native iteration transcript missing')

# Native integral reports in N on half-aircraft surfaces and signed flux in kg/s.
walls = s.setup.boundary_conditions.wall.get_object_names()
loads = {}
groups={'airframe':[n for n in walls if n.startswith('wall_')]}
for name in ('wing','fuselage','nacelles','sponson','empennage'):
    group=[n for n in walls if n.startswith('wall_'+name)]
    if group:
        groups[name]=group
for label,zones in groups.items():
    loads[label]={}
    for axis in 'xy':
        for kind in ['PressureForce','ViscousForce','Force']:
            key=kind+axis.upper()
            loads[label][key]=scalar('Final'+label.title()+key,f'{kind}({zones!r}).{axis}')
if CFG['s']==0:
    volume_zones=repr(s.setup.cell_zone_conditions.fluid.get_object_names())
    extrema={n:scalar('Equilibrium'+n,f'Maximum({expr},{volume_zones})')
             for n,expr in [('MaxVelocity','Velocity.mag'),('MaxAbsGaugePressure','abs(StaticPressure)'),
                             ('MaxTemperatureDeparture','abs(StaticTemperature-288.15 [K])')]}
    write_record('static_equilibrium_native.json',dict(accepted_stem=CFG['output_stem'],initialization='Uniform static standard initialization on matched medium grid; all disk momentum sources zero by speed multiplier.',**extrema,force_N=loads))
reports = s.solution.report_definitions
flux = {}
for zone in ambient_zones:
    name='mass-'+zone.replace('_','-')
    reports.surface[name]={'report_type':'surface-massflowrate','surface_names':[zone]}
    flux[zone]=reports.compute(report_defs=[name])
volume_zones=repr(s.setup.cell_zone_conditions.fluid.get_object_names())
reaction={axis:-scalar('NativeDiskForce'+axis.upper(),f'VolumeInt(DepSource{axis.upper()},{volume_zones})') for axis in 'xyz'}
reaction_moment={axis:-scalar('NativeDiskMoment'+axis.upper(),f'VolumeInt({term},{volume_zones})')
                 for axis,term in zip('xyz',['y*DepSourceZ-z*DepSourceY','z*DepSourceX-x*DepSourceZ','x*DepSourceY-y*DepSourceX'])}
reaction_mz=reaction_moment['z']
records=json.loads((CASE/'fluent_discrete_disk_integrals.json').read_text())
if all('discrete_force_vector_N' in d and 'discrete_moment_about_center_Nm' in d for d in records):
    by_disk_f=[0.,0.,0.];by_disk_m=[0.,0.,0.]
    for d in records:
        c=d['center_m'];fv=d['discrete_force_vector_N'];mv=d['discrete_moment_about_center_Nm']
        for i,(j,k) in enumerate(((1,2),(2,0),(0,1))):
            by_disk_f[i]-=fv[i]
            by_disk_m[i]-=mv[i]+c[j]*fv[k]-c[k]*fv[j]
    for i,ax in enumerate('xyz'):
        if not (math.isclose(by_disk_f[i],reaction[ax],rel_tol=1e-7,abs_tol=1e-5) and
                math.isclose(by_disk_m[i],reaction_moment[ax],rel_tol=1e-7,abs_tol=1e-5)):
            raise ValueError(f'Origin-shifted per-disk reactions differ from global source integral on {ax}')

write_record(CFG['output_stem']+'_force_and_flux.json',dict(half_model_force_N=loads,native_flux_reports=flux,
             pitch_origin_m=[0,0,0],half_model_pitch_moment_Nm=reports.compute(report_defs=['airframe-pitch-mz-half']),
             half_model_actuator_reaction_N=reaction,half_model_actuator_reaction_Mz_Nm=reaction_mz,
             half_model_actuator_reaction_moment_about_origin_Nm=reaction_moment,
             half_model_wall_plus_actuator_N={k:loads['airframe']['Force'+k.upper()]+reaction[k] for k in 'xy'}))
full_fields=bool(fixture or CFG.get('export_full_fields') or case_name=='fine_rpm100')
if CFG.get('export_full_fields') or (fixture or CFG.get('extract_only')) and (full_fields or case_name in ('medium_rpm100','medium_rpm100_noswirl')):
    import csv
    import re
    ascii_export=s.file.export.ascii
    available=ascii_export.cell_func_domain.allowed_values()
    def normalized(token):
        return re.sub('[^a-z0-9]','',token.casefold())
    lookup={normalized(q):q for q in available}
    # ID is paired with pressure to verify the global CFF ordering after an MPI restart.
    aliases={'cell_id':['cell-id'], 'pressure_Pa':['pressure','static-pressure'],
             'omega_x_per_s':['x-vorticity','axial-vorticity']}
    if full_fields:
        aliases.update(u_m_s=['x-velocity'],v_m_s=['y-velocity'],w_m_s=['z-velocity'],
                       rho_kg_m3=['density'],total_pressure_Pa=['total-pressure'],
                       k_m2_s2=['turb-kinetic-energy','turbulent-kinetic-energy'],
                       mu_t_Pa_s=['viscosity-turb','turb-viscosity','turbulent-viscosity','eddy-viscosity'])
        for velocity,component in zip('uvw','xyz'):
            for direction in 'xyz':
                aliases[f'd{velocity}_d{direction}_per_s']=[
                    f'd{component}-velocity-d{direction}',f'd{velocity}-velocity-d{direction}',
                    f'd{velocity}-d{direction}',f'{component}-velocity-gradient-{direction}']
    selection={}
    for quantity,options in aliases.items():
        picked=next((lookup[normalized(q)] for q in options if normalized(q) in lookup),None)
        if picked is None:
            raise ValueError(f'Native field {quantity} missing; Fluent supports {available}')
        selection[quantity]=picked
    stem=CFG['output_stem']
    csv_name=stem+('_cell_fields.csv' if full_fields else '_vorticity.csv')
    output=CASE/csv_name
    temp=CASE/('pending_'+csv_name)
    ascii_export(file_name=str(temp),surface_name_list=[],delimiter='comma',
                 cell_func_domain=list(selection.values()),location='cell-center')
    with temp.open(newline='') as inp:
        reader=csv.reader(inp,skipinitialspace=True)
        header=next(reader,None)
        first=next(reader,None)
    if not header or not first or len(first)!=len(header) or len(header)<len(selection)+3:
        raise ValueError(f'Unexpected native ASCII volume export {header!r} sample={first!r}')
    output.parent.mkdir(parents=True,exist_ok=True)
    temp.replace(output)
    write_record(stem+'_native_field_manifest.json',dict(file=csv_name,location='cell-center',
                 native_fields=selection,header=header,case=stem+'.cas.h5',
                 data=Path(CFG['input_data']).name if CFG.get('extract_only') else stem+'.dat.h5'))
if CFG.get('export_interpolation'):
    interp=s.file.interpolate.write_data
    fields=['pressure','x-velocity','y-velocity','z-velocity','temperature','turb-kinetic-energy','specific-diss-rate']
    target=CASE/(CFG['output_stem']+'.ip')
    import uuid
    pending=target.with_name(target.stem+'_'+uuid.uuid4().hex+'.ip')
    interp(file_name=str(pending),cell_zones=s.setup.cell_zone_conditions.fluid.get_object_names(),fields=fields,binary_format=True)
    if not pending.is_file() or not pending.stat().st_size:
        raise RuntimeError("Fluent did not write native interpolation fields")
    pending.replace(target)
    import hashlib
    def native_sha256(path):
        hash_value=hashlib.sha256()
        with path.open('rb') as handle:
            for part in iter(lambda:handle.read(1024*1024),b''):
                hash_value.update(part)
        return hash_value.hexdigest()
    source_case=Path(CFG['input_file'])
    source_data=Path(CFG['input_data'])
    write_record(CFG['output_stem']+'_interpolation.json',
                 dict(source_case=source_case.name,source_data=source_data.name,
                      case_sha256=native_sha256(source_case),data_sha256=native_sha256(source_data),
                      interpolation_file=target.name,interpolation_sha256=native_sha256(target)))
print('X57-SOLVER-BLOCK-SAVED',CFG['output_stem'],flush=True)
