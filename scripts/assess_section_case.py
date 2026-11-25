"""Assess a native Fluent 2D section using per-unit-span forces and actual wall y-plus."""
import argparse
import json
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from assess_fluent_case import flux_value, read_force_monitor
from cfd_verification import force_tail, mass_balance, weighted_distribution
from cut_fluent_cells import zones
from extract_fluent_fields import sample
from read_x57_section import mesh2


def assess(folder, stem):
    cfg=json.loads((folder/"section_config.json").read_text())
    residual_files=sorted(folder.glob("*_residuals.csv"),key=lambda p:p.stat().st_mtime_ns)
    endpoint=pd.read_csv(folder/(stem+"_residuals.csv"))
    end=int(endpoint["iter"].iloc[-1])
    data=pd.concat([pd.read_csv(p) for p in residual_files if p.stat().st_mtime_ns <= (folder/(stem+"_residuals.csv")).stat().st_mtime_ns])
    history=data.drop_duplicates("iter",keep="last").set_index("iter").sort_index().loc[:end]
    limits=dict.fromkeys(("continuity","x-velocity","y-velocity","energy","k","omega"),1.e-6)
    window=history.loc[:,list(limits)].iloc[-50:]
    if len(window)!=50 or not np.all(np.diff(window.index)==1):
        raise ValueError("Need 50 consecutive native residual records")
    monitor=read_force_monitor(folder/"force_history.out").loc[:end]
    if not len(monitor) or monitor.index[-1]!=end:
        raise ValueError("The force and residual histories have different endpoints")
    forces={name:force_tail(monitor.index,monitor[name]) for name in ("section-lift","section-drag","main-lift","section-pitch")}
    flux_data=json.loads((folder/(stem+"_flux.json")).read_text())
    flux={name:flux_value(rec,"mass-"+name) for name,rec in flux_data.items()}
    expected={"ambient_top","outlet"} | {b["zone"] for b in cfg["inlet_profile"]["open_bands"]}
    if set(flux)!=expected:
        raise ValueError("Missing or extraneous open-boundary mass flux")
    closure=mass_balance(list(flux.values()))
    cas=folder/(stem+".cas.h5")
    dat=folder/(stem+".dat.h5")
    with h5py.File(cas) as fc, h5py.File(dat) as fd:
        m=fc["meshes/1"]
        xyz, edges, _, _, _, _=mesh2(m)
        parts=zones(m["faces/zoneTopology"])
        ids=np.concatenate([np.arange(lo,hi+1) for name,(lo,hi) in parts.items() if name in ("wall_main","wall_flap","wall_slat")])
        length=np.linalg.norm(xyz[edges[ids,1]]-xyz[edges[ids,0]],axis=1)
        yp=weighted_distribution(sample(fd["results/1/phase-1/faces"],"SV_WALL_YPLUS",ids).reshape(-1), length)
    residual_history=history[list(limits)]
    if not np.isfinite(residual_history.to_numpy()).all() or (residual_history<0).any().any():
        raise ValueError("Section scaled residuals must be finite and nonnegative at every native iteration")
    initial=residual_history.iloc[0]
    maximum=window.max()
    scale=np.maximum(initial.to_numpy(),np.finfo(float).tiny)
    orders=np.log10(scale/np.maximum(maximum.to_numpy(),np.finfo(float).tiny))
    strict_checks=dict(mesh_budget=60000<=cfg["stats"]["cells"]<=120000,
                force_platform=all(item["stable"] for item in forces.values()),
                residual_thresholds=all(np.isfinite(window[k]).all() and (window[k]<v).all() for k,v in limits.items()),
                residual_reduction=all((residual_history[k]<v).all() or (orders[i]>=4.) for i,(k,v) in enumerate(limits.items())),
                mass_balance=closure["imbalance_fraction"]<.005, wall_resolution=yp["maximum"]<.5)
    # Fast-track tiers; wall y+ stays a recorded target (y+ max < 0.5 strict, < 1 engineering).
    from fasttrack_profile import (FORCE_TIERS, MASS_TIERS, REDUCTION_ORDERS, SECTION_RESIDUAL_TIERS,
                                   SECTION_YPLUS_MAX, TIER_ORDER)
    def plateau(item, tier):
        rs, rd = FORCE_TIERS[tier]
        mean, sd, drift = abs(item["mean_N"]), item["std_N"], abs(item["drift_N"])
        if item.get("sustained_monotone_drift") or not np.isfinite([mean, sd, drift]).all():
            return False
        # Per-unit-span 2D loads: use a 1 N/m absolute floor for near-zero means.
        return bool(sd < max(rs*mean, 1e-3) and drift < max(rd*mean, 5e-4)) if mean > 1.0 else bool(sd < 1.0 and drift < 0.5)
    tier_checks={}
    for tier in TIER_ORDER:
        lim={k:SECTION_RESIDUAL_TIERS[tier]["continuity" if k=="continuity" else "other"] for k in limits}
        tier_checks[tier]=dict(mesh_budget=strict_checks["mesh_budget"],
            force_platform=all(plateau(item,tier) for item in forces.values()),
            residual_thresholds=all(np.isfinite(window[k]).all() and (window[k]<lim[k]).all() for k in limits),
            residual_reduction=all((residual_history[k]<lim[k]).all() or (orders[i]>=REDUCTION_ORDERS[tier]) for i,k in enumerate(limits)),
            mass_balance=closure["imbalance_fraction"]<MASS_TIERS[tier],
            wall_resolution=yp["maximum"]<SECTION_YPLUS_MAX[tier])
    tier_checks["strict"]=dict(strict_checks)
    best_tier=next((t for t in TIER_ORDER if all(tier_checks[t].values())),None)
    acceptance_tier=best_tier if best_tier in ("strict","engineering") else None
    checks=dict(tier_checks[acceptance_tier or "engineering"])
    win=window.to_numpy(dtype=float)
    diverged=bool(not np.isfinite(win).all() or np.nanmax(win)>1.0)
    return dict(case=folder.name,final_iteration=end,accepted_stem=stem if all(checks.values()) else None,diverged=diverged,
                passed=all(checks.values()),checks=checks,acceptance_tier=acceptance_tier,best_available_tier=best_tier,
                assessed_stem=stem,strict_checks=strict_checks,tier_checks=tier_checks,
                force_units="N/m; section-pitch is N m/m",forces_per_span=forces,
                full_history_start=history.index[0].item(),residual_reduction_orders=dict(zip(limits, orders.tolist())),
                final_scaled_residuals=window.iloc[-1].to_dict(),max_last_50_scaled_residuals=maximum.to_dict(),
                signed_native_flux_kg_s_per_m=flux,mass_balance=closure,airfoil_yplus=yp,
                parent_inlet_case=cfg["inlet_profile"]["source_case_id"],inlet_profile=cfg["inlet_profile"]["profile_file"])


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("folder",type=Path)
    p.add_argument("stem")
    a=p.parse_args()
    result=assess(a.folder,a.stem)
    (a.folder/"iteration_qa.json").write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
    print(json.dumps({"case":a.folder.name,"iteration":result["final_iteration"],"checks":result["checks"]}))
    raise SystemExit(0 if result["passed"] else 1)

