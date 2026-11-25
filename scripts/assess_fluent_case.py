"""Check aircraft convergence from native histories and reports, with every criterion retained."""
from pathlib import Path
import argparse
import json
import re
import numpy as np
import pandas as pd
from cfd_verification import force_tail, mass_balance
from fasttrack_profile import (FORCE_TIERS, FORCE_NEAR_ZERO_ABS, MASS_TIERS, REDUCTION_ORDERS,
                               RESIDUAL_TIERS, TIER_ORDER, ROOT as WS_ROOT)


def _stat(st, key):
    return st.get(key+"_N", st.get(key+"_Nm"))


def force_tier_ok(label, st, tier, lift_mean=None, c_ref=None):
    """Plateau test of one 200-iteration force window at the requested tier."""
    rel_std, rel_drift = FORCE_TIERS[tier]
    abs_std, abs_drift = FORCE_NEAR_ZERO_ABS[tier]
    mean, sd, drift = abs(_stat(st, "mean")), _stat(st, "std"), abs(_stat(st, "drift"))
    if not all(np.isfinite([mean, sd, drift])) or st.get("sustained_monotone_drift"):
        return False
    scale = mean
    if label == "Mz" and tier != "strict" and lift_mean and c_ref:
        # A pitching moment about the CAD origin can be small; judge it against the
        # characteristic moment |L| * MAC instead of its own (possibly tiny) mean.
        scale = max(mean, abs(lift_mean) * c_ref)
    if scale <= 1.0:
        return bool(sd < abs_std and drift < abs_drift)
    return bool(sd < rel_std * scale and drift < rel_drift * scale)


def residual_category(eq):
    if eq == "continuity":
        return "continuity"
    if eq.endswith("velocity"):
        return "velocity"
    if eq == "energy":
        return "energy"
    return "turbulence"


def read_force_monitor(path):
    lines=path.read_text(encoding="utf-8",errors="replace").splitlines()
    names=None
    rows={}
    for line in lines:
        if line.strip().startswith('("Iteration"'):
            names=re.findall(r'"([^"]+)"',line)
        elif names and re.match(r"^\s*\d+\s+",line):
            fields=line.split()
            if len(fields)==len(names):
                rows[int(fields[0])]=[float(x) for x in fields[1:]]
    if not rows:
        raise ValueError("No native force history.")
    return pd.DataFrame.from_dict(rows,orient="index",columns=names[1:]).sort_index()


def flux_value(result, name):
    if isinstance(result,(int,float)):
        return float(result)
    if isinstance(result,dict) and name in result:
        return flux_value(result[name], name)
    if isinstance(result,(tuple,list)):
        # Native report computation can return [report-dictionary, iteration].
        matching=[v for v in result if isinstance(v,dict) and name in v]
        if len(matching)==1:
            return flux_value(matching[0],name)
        if len(result)==1:
            return flux_value(result[0],name)
    raise ValueError(f"Unrecognized native flux report for {name}: {result!r}")


def assess(folder, stem):
    forces=read_force_monitor(folder/"force_history.out")
    residuals=pd.read_csv(folder/(stem+"_residuals.csv")).drop_duplicates(subset="iter",keep="last").set_index("iter").sort_index()
    end=int(residuals.index[-1])
    force=forces.loc[:end]
    if int(force.index[-1])!=end:
        raise ValueError("Force and residual histories end at different iterations.")
    stats={}
    for label,col in [("L_air","airframe-lift-half"),("L_wing","wing-lift-half"),("D_air","airframe-drag-half"),("Mz","airframe-pitch-mz-half")]:
        st=force_tail(force.index.values,force[col].values*2.)
        if label=="Mz":
            st={k.replace("_N","_Nm"):v for k,v in st.items()}
        st["units"]="N m" if label=="Mz" else "N"
        st["preferred_0p3_percent"]=bool(st["relative_std"] is not None and st["relative_std"]<.003 and st["relative_drift"]<.003)
        stats[label]=st
    limits={"continuity":1.e-3,"x-velocity":1.e-4,"y-velocity":1.e-4,"z-velocity":1.e-4,
            "energy":1.e-6,"k":1.e-4,("epsilon" if folder.name.endswith("_rke") else "omega"):1.e-4}
    # Retain the first observed residual of this case across accepted continuation blocks.
    # Use the original transient only for reduction diagnostics. Acceptance uses the current tail.
    current_path=folder/(stem+"_residuals.csv")
    sources=sorted((f for f in folder.glob("*_residuals.csv") if f.stat().st_mtime<=current_path.stat().st_mtime),
                   key=lambda f:f.stat().st_mtime)
    full=pd.concat([pd.read_csv(f) for f in sources]).drop_duplicates("iter",keep="last").set_index("iter").sort_index()
    full=full.loc[:end]
    rtail=residuals[list(limits)].iloc[-50:]
    start=full.iloc[0]
    reductions={}
    warm_start=folder.name.startswith("medium_") and folder.name!="medium_rpm100" or folder.name=="fine_rpm100"
    for eq,limit in limits.items():
        first,tail=float(start[eq]),float(rtail[eq].max())
        whole=full[eq].to_numpy()
        inherited_below=bool(warm_start and np.isfinite(whole).all() and (whole<limit).all())
        reductions[eq]={"start":first,"max_final_50":tail,
                        "orders":float(np.log10(first/tail)) if min(first,tail)>0 else None,
                        "warm_start_under_criterion_for_entire_history":inherited_below,
                        "passes":bool(np.isfinite(whole).all() and (whole>=0).all() and
                                      (tail<=1e-4*first or inherited_below))}

    if len(rtail)<50 or not np.all(np.diff(rtail.index)==1):
        raise ValueError("Residuals require 50 contiguous observations in the final block.")
    cont=rtail["continuity"].to_numpy()
    # Redline allows a stationary plateau between 5e-4 and 1e-3. Quantify a
    # rise against the observed scatter of ten five-iteration block means.
    blocks=cont.reshape(10,5).mean(axis=1)
    a,b=blocks[:5],blocks[5:]
    rise=float(b.mean()-a.mean())
    noise=float(2*np.sqrt(a.var(ddof=1)/5+b.var(ddof=1)/5))
    cont_stable=bool(np.max(cont)<5.e-4 or rise<=noise)
    flux_and_force=json.loads((folder/(stem+"_force_and_flux.json")).read_text())
    flux={key:flux_value(vals,"mass-"+key.replace("_","-")) for key,vals in flux_and_force["native_flux_reports"].items()}
    closure=mass_balance(list(flux.values()))
    expected={"farfield_inlet","farfield_outlet","farfield_side","farfield_top"}
    if folder.name.endswith("_oge"):
        expected.add("runway_ground")
    if set(flux)!=expected:
        raise ValueError("Missing open boundary flux.")
    disks=json.loads((folder/"fluent_discrete_disk_integrals.json").read_text())
    if len(disks)!=7 or len({x["name"] for x in disks})!=7:
        raise ValueError("Require 7 aircraft actuator records.")
    for disk in disks:
        for prop,unit in [("thrust","N"),("torque","Nm")]:
            ref=disk[f"{prop}_target_{unit}"]
            val=disk[f"discrete_{prop}_{unit}"]
            disk[prop+"_error_fraction"]=abs(val-ref)/abs(ref) if ref else None
            disk[prop+"_passes"]=bool(abs(val-ref)<.01*abs(ref) if ref else abs(val)<1.e-10)
    consistent=True
    native=flux_and_force["half_model_force_N"]
    for zone,ax,name in [("airframe","Y","airframe-lift-half"),("airframe","X","airframe-drag-half"),
                         ("wing","Y","wing-lift-half")]:
        consistent &= bool(np.isclose(native[zone]["Force"+ax],force[name].iloc[-1],rtol=1.e-5,atol=1.e-5))
    moment=flux_value(flux_and_force["half_model_pitch_moment_Nm"],"airframe-pitch-mz-half")
    consistent &= bool(np.isclose(moment,force["airframe-pitch-mz-half"].iloc[-1],rtol=1.e-5,atol=1.e-5))
    for zone in native.values():
        for axis in ("X","Y"):
            consistent &= bool(np.isclose(zone["PressureForce"+axis]+zone["ViscousForce"+axis],
                                          zone["Force"+axis],rtol=1.e-5,atol=1.e-5))
    strict_checks={"force_platform":all(st["stable"] for st in stats.values()),
            "residual_thresholds":all(np.isfinite(rtail[c]).all() and (rtail[c]<limit).all() for c,limit in limits.items()),
            "continuity_stability":cont_stable,
            "residual_reduction":all(entry["passes"] for entry in reductions.values()),
            "mass_balance":closure["imbalance_fraction"]<.005,
            "disk_integrals":all(x["thrust_passes"] and x["torque_passes"] for x in disks),
            "force_consistency":consistent}
    # Fast-track tiers. Deterministic invariants (disk integrals, report consistency) are never relaxed.
    try:
        c_ref=float(json.loads((WS_ROOT/"01_geometry/geometry_audit.json").read_text(encoding="utf-8-sig"))
                    ["wing_reference"]["mean_aerodynamic_chord_m"])
    except (OSError,KeyError,ValueError,TypeError):
        c_ref=None
    lift_mean=_stat(stats["L_air"],"mean")
    tier_checks={}
    for tier in TIER_ORDER:
        lim={eq:RESIDUAL_TIERS[tier][residual_category(eq)] for eq in limits}
        orders=REDUCTION_ORDERS[tier]
        red_ok=True
        for eq,entry in reductions.items():
            whole=full[eq].to_numpy()
            inherited=bool(warm_start and np.isfinite(whole).all() and (whole<lim[eq]).all())
            first,tail=entry["start"],entry["max_final_50"]
            need=orders
            if warm_start and len(whole):
                # A warm branch starts from a converged field: measure the drop from the
                # post-perturbation peak (first 50 iterations), one order less than a cold start.
                first=float(np.nanmax(whole[:50]));need=max(1.,orders-1.)
            red_ok&=bool(np.isfinite(whole).all() and (whole>=0).all() and (tail<=10.**(-need)*first or inherited))
        stable=bool(np.max(cont)<.5*lim["continuity"] or rise<=noise)
        tier_checks[tier]=dict(
            force_platform=all(force_tier_ok(k,st,tier,lift_mean,c_ref) for k,st in stats.items()),
            residual_thresholds=all(np.isfinite(rtail[c]).all() and (rtail[c]<lim[c]).all() for c in limits),
            continuity_stability=stable,residual_reduction=red_ok,
            mass_balance=closure["imbalance_fraction"]<MASS_TIERS[tier],
            disk_integrals=strict_checks["disk_integrals"],force_consistency=strict_checks["force_consistency"])
    tier_checks["strict"]=dict(strict_checks)
    best_tier=next((t for t in TIER_ORDER if all(tier_checks[t].values())),None)
    # 'budget' is only granted by the case driver once the case budget is spent.
    acceptance_tier=best_tier if best_tier in ("strict","engineering") else None
    checks=dict(tier_checks[acceptance_tier or "engineering"])
    data_name=stem+".dat.h5"
    cfgpath=folder/"solver_config.json"
    if cfgpath.is_file():
        cfg=json.loads(cfgpath.read_text(encoding="utf-8-sig"))
        if cfg.get("output_stem")==stem and cfg.get("extract_only") and cfg.get("input_data"):
            data_name=Path(cfg["input_data"]).name
    tail_values=rtail.to_numpy(dtype=float)
    diverged=bool(not np.isfinite(tail_values).all() or np.nanmax(tail_values)>1.0)
    return {"case":folder.name,"accepted_stem":stem,"accepted_data":data_name,"final_iteration":end,"passed":all(checks.values()) and not diverged,"checks":checks,
            "diverged":diverged,
            "acceptance_tier":acceptance_tier,"best_available_tier":best_tier,"strict_checks":strict_checks,"tier_checks":tier_checks,
            "forces_full_aircraft":stats,"half_model_endpoint_force_N":native,"half_model_endpoint_pitch_Nm":moment,
            "pitch_origin_m":flux_and_force["pitch_origin_m"],"final_scaled_residuals":rtail.iloc[-1].to_dict(),
            "max_last_50_scaled_residuals":rtail.max().to_dict(),"signed_native_flux_kg_s":flux,
            "mass_balance":closure,"disk_integrals":disks,"scaled_residual_reduction":reductions,
            "continuity_last50":{"max":float(np.max(cont)),"preferred_target":5.e-4,"redline":1.e-3,
                                 "second_minus_first25":rise,"twice_block_mean_standard_error":noise},
            "continuity_last50_log10_slope_per_iteration":float(np.polyfit(np.arange(len(rtail)),np.log10(rtail['continuity'].clip(lower=1e-300)),1)[0])}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("case_folder",type=Path)
    p.add_argument("stem")
    a=p.parse_args()
    result=assess(a.case_folder,a.stem)
    (a.case_folder/"iteration_qa.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({k:result[k] for k in ("case","final_iteration","passed","checks")},indent=2))
    raise SystemExit(0 if result["passed"] else 1)
