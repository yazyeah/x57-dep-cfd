"""Build load comparisons from QA-accepted native Fluent checkpoints."""
from pathlib import Path
import json
import h5py
import numpy as np
import pandas as pd
from assess_fluent_case import flux_value
from extract_fluent_fields import extract_walls
from cfd_verification import weighted_distribution

ROOT=Path(__file__).resolve().parents[1]
BASE="medium_rpm100"
ZERO="medium_rpm000"
HLP=BASE+"_hlp_only"
WT=BASE+"_wt_only"
ALT=BASE+"_alt_swirl"
OGE=BASE+"_oge"
ROLL=BASE+"_takeoff_v10"
RKE=BASE+"_rke"
VECTOR="medium_opt_hlp_vector10"
CASES3=["coarse_rpm100",BASE,"fine_rpm100","medium_rpm050","medium_rpm075",BASE+"_noswirl",HLP,WT,ALT,ROLL,OGE,RKE,VECTOR]
STEMS={13:"fig13_propulsion_decomposition_and_synergy",14:"fig14_ground_effect_and_takeoff_roll",
       15:"fig15_turbulence_model_sensitivity",16:"fig16_highlift_design_optimization_cfd",
       19:"fig19_multi_case_ablation_heatmap_and_radar"}
LABEL={BASE:"Nominal",ZERO:"Unpowered",HLP:"HLP only",WT:"Wingtip only",ALT:"Alternating",OGE:"Open lower boundary",
       ROLL:"Rolling, 10 m/s",RKE:"Realizable k–ε",VECTOR:"HLP vector −10°",
       "coarse_rpm100":"Coarse", "fine_rpm100":"Fine","medium_rpm050":"50% speed","medium_rpm075":"75% speed",BASE+"_noswirl":"Zero swirl"}
PROVENANCE="Native CFD: converged Fluent CFF case/data and terminal force reports. Derived: full-aircraft forces are twice half-model x/y loads. Model inputs: calibrated disk targets and fixed reference dynamic pressure."

def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def accepted(name):
    case=ROOT/"03_cases"/name
    qa=read_json(case/"iteration_qa.json") if name!=ZERO else read_json(case/"static_equilibrium_audit.json")
    if name==ZERO:
        if qa.get("passed") is not True or qa.get("count_in_18") is not False:
            raise ValueError("Zero source requires a passed auxiliary native equilibrium audit")
        if any(abs(qa[k])>tol for k,tol in [("MaxVelocity",1e-6),("MaxAbsGaugePressure",1e-4),("MaxTemperatureDeparture",1e-5)]):
            raise ValueError("Zero-source equilibrium tolerances failed.")
    elif qa.get("passed") is not True:
        raise ValueError(f"{name} has no passing iteration QA.")
    stem=qa.get("accepted_stem") or qa.get("output_stem")
    if not stem:
        candidates=[p.name[:-7] for p in case.glob("*.cas.h5") if "autosave" not in p.name.lower() and p.with_name(p.name[:-7]+".dat.h5").is_file()]
        if len(candidates)!=1:raise ValueError(f"{name} must identify an unambiguous accepted_stem in its QA.")
        stem=candidates[0]
    if Path(stem).name!=stem:raise ValueError("Invalid checkpoint stem in accepted QA.")
    cas=case/(stem+".cas.h5"); dat=case/(qa.get("accepted_data") or stem+".dat.h5")
    if dat.resolve().parent!=case.resolve():raise ValueError("Invalid accepted data path in QA.")
    from fluent_checkpoints import case_for_data
    if case_for_data(dat).resolve()!=cas.resolve():
        raise ValueError(f"Accepted data references a different case: {name}")
    if name!=ZERO:
        from cfd_case_identity import verify_endpoint
        verify_endpoint(ROOT,name,qa,cas,dat,name not in CASES3)
    return qa,cas,dat

def reference():
    model=read_json(ROOT/"DELIVERABLES/data/actuator_disk_model.json")
    rot=model["rotors"];area=sum(np.pi*(d["r_tip_m"]**2-d["r_hub_m"]**2) for d in rot)
    q=sum(d["targets"][-1]["thrust_N"] for d in rot)/(4*area)
    return q,read_json(ROOT/"01_geometry/geometry_audit.json")["wing_reference"]

def load3(name):
    qa,cas,dat=accepted(name)
    folder=cas.parent; stem=cas.name[:-7]
    end=read_json(folder/(stem+"_force_and_flux.json"))
    native=end["half_model_force_N"];r=end["half_model_actuator_reaction_N"]
    q,g=reference();area=g["full_planform_area_m2"];c=g["mean_aerodynamic_chord_m"]
    if not np.isclose(q,float(read_json(folder/"solver_physics.json")["q_ref_Pa"]),rtol=2e-8):
        raise ValueError(f"{name}: inconsistent coefficient reference dynamic pressure.")
    force=2*native["airframe"]["ForceY"];drag=2*native["airframe"]["ForceX"]
    moment=2*flux_value(end["half_model_pitch_moment_Nm"],"airframe-pitch-mz-half")
    a=native["airframe"]
    return dict(case=name,label=LABEL[name],dimension="3D",native_case=str(cas.relative_to(ROOT)),native_data=str(dat.relative_to(ROOT)),
                qa_file=str((folder/("static_equilibrium_audit.json" if name==ZERO else "iteration_qa.json")).relative_to(ROOT)),
                provenance=PROVENANCE,q_ref_Pa=q,S_ref_m2=area,c_ref_m=c,
                half_airframe_lift_native_N=a["ForceY"],half_airframe_drag_native_N=a["ForceX"],
                L_wall_N=force,D_wall_N=drag,Mz_wall_Nm=moment,L_wing_N=2*native["wing"]["ForceY"],
                L_pressure_N=2*a["PressureForceY"],L_viscous_N=2*a["ViscousForceY"],
                L_actuator_reaction_N=2*r["y"],Fx_actuator_reaction_N=2*r["x"],
                L_installed_N=force+2*r["y"],Fx_installed_N=drag+2*r["x"],
                C_L=force/(q*area),C_D=drag/(q*area),C_M=moment/(q*area*c),
                CL_pressure=2*a["PressureForceY"]/(q*area),CL_viscous=2*a["ViscousForceY"]/(q*area),
                L_over_D=force/drag if abs(drag)>1e-10*q*area else np.nan,
                L_std_N=qa["forces_full_aircraft"]["L_air"]["std_N"] if name!=ZERO else np.nan,
                D_std_N=qa["forces_full_aircraft"]["D_air"]["std_N"] if name!=ZERO else np.nan,
                Mz_std_Nm=qa["forces_full_aircraft"]["Mz"]["std_Nm"] if name!=ZERO else np.nan,
                prescribed_runway_condition="ambient pressure opening" if name==OGE else ("+x moving no-slip" if name==ROLL else "stationary no-slip"),
                prescribed_runway_speed_m_s=(np.nan if name==OGE else 10.0 if name==ROLL else 0.0),
                prescribed_turbulence_model="realizable k-epsilon with enhanced wall treatment" if name==RKE else "curvature-corrected k-omega SST",
                prescribed_rotor_loading="static calibrated schedule on matched cases; see actuator_disk_model.json",
                U_inf_prescribed_m_s=10.0 if name==ROLL else 0.0,
                final_iteration=qa.get("final_iteration"),qa_passed=True)

def synergy(rows):
    t=pd.DataFrame(rows).set_index("case")
    terms=t.loc[[BASE,HLP,WT,ZERO]]
    result={}
    for k in ["L_wall_N","L_wing_N","D_wall_N","Mz_wall_Nm","L_installed_N","C_L","C_D"]:
        a,b,c,d=terms[k].to_numpy()
        result[k]=a-b-c+d
    return result

def comparisons3(numbers):
    ids=set()
    if 13 in numbers: ids.update([BASE,ZERO,HLP,WT,ALT])
    if 14 in numbers: ids.update([BASE,OGE,ROLL])
    if 15 in numbers: ids.update([BASE,RKE])
    if 16 in numbers: ids.update([BASE,VECTOR])
    if 19 in numbers: ids.update(CASES3)
    return {n:load3(n) for n in [*CASES3,ZERO] if n in ids}

def table13(cases):
    ids=[ZERO,HLP,WT,BASE,ALT]
    t=pd.DataFrame([cases[n] for n in ids]); t["record_type"]="accepted_native_and_derived"
    delta={"case":"full_minus_hlp_minus_wingtip_plus_unpowered","label":"Non-additive interaction",
           "record_type":"derived_factorial_contrast","dimension":"3D",**synergy(t.to_dict("records")),
           "provenance":"Derived from four accepted cases: full − HLP only − wingtip only + unpowered."}
    return pd.concat([t,pd.DataFrame([delta])],ignore_index=True)

def table14(cases):
    ids=[n for n in [BASE,OGE,ROLL,RKE] if n in cases]
    t=pd.DataFrame([cases[n] for n in ids])
    for k in ["L_wall_N","L_wing_N","D_wall_N","Mz_wall_Nm","C_L","C_D"]:
        t["delta_"+k]=t[k]-cases[BASE][k]
    return t
