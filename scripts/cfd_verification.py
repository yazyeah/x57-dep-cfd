"""Verification calculations for full-aircraft forces and Fluent reports."""
import numpy as np
from scipy.optimize import brentq


def weighted_distribution(yplus, face_area):
    values = np.asarray(yplus, dtype=float)
    areas = np.asarray(face_area, dtype=float)
    if not len(values) or values.shape != areas.shape or np.any(areas <= 0):
        raise ValueError("Wall y+ requires positive area on every matched face.")
    if not np.isfinite(values).all() or not np.isfinite(areas).all() or np.any(values < 0):
        raise ValueError("Invalid wall values or areas.")
    order = np.argsort(values)
    cdf = np.cumsum(areas[order]) / np.sum(areas)
    median, p95 = values[order[np.searchsorted(cdf,[.5,.95])]]
    return dict(mean=float(np.average(values,weights=areas)), median=float(median),
                p95=float(p95), maximum=float(values.max()), face_count=int(len(values)),
                total_area_m2=float(areas.sum()))


def force_tail(iterations, forces):
    iterations = np.asarray(iterations)
    y = np.asarray(forces, dtype=float)[-200:]
    if len(y) != 200 or not np.all(np.diff(iterations[-200:]) == 1) or not np.isfinite(y).all():
        raise ValueError("Require 200 finite force reports on consecutive iterations.")
    mean = float(np.mean(y))
    sd = float(np.std(y,ddof=1))
    drift = float(y[100:].mean() - y[:100].mean())
    threshold = .005 * abs(mean)
    # Only a mean within one absolute unit of zero uses the dimensional fallback.
    near_zero = abs(mean) <= 1.0
    std_limit = 1.0 if near_zero else threshold
    drift_limit = 0.5 if near_zero else threshold
    steps = np.diff(y)
    sustained_trend = bool((np.all(steps >= 0) and np.any(steps > 0)) or
                           (np.all(steps <= 0) and np.any(steps < 0)))
    return dict(first_iteration=int(iterations[-200]), last_iteration=int(iterations[-1]),
                near_zero_absolute_tolerance=near_zero, mean_N=mean, std_N=sd, drift_N=drift, relative_std=sd/abs(mean) if mean else None,
                relative_drift=abs(drift/mean) if mean else None, std_limit_N=std_limit, drift_limit_N=drift_limit, sustained_monotone_drift=sustained_trend,
                stable=bool(sd < std_limit and abs(drift) < drift_limit and not sustained_trend))


def mass_balance(signed_boundary_fluxes):
    flux=np.asarray(signed_boundary_fluxes,dtype=float)
    inflow=flux[flux>0].sum()
    outflow=-flux[flux<0].sum()
    if not (np.isfinite(flux).all() and min(inflow,outflow)>0):
        raise ValueError("Need positive inlet and negative outlet fluxes.")
    return dict(inlet_kg_s=float(inflow), outlet_kg_s=float(outflow),
                imbalance_fraction=float(abs(inflow-outflow)/(.5*(inflow+outflow))))


def gci_from_spacing(spacings, values, *, fluid_grid=True):
    """Three-grid Celik (2008) diagnostics and the project's §9 fallback uncertainty.

    Inputs are ordered coarse, medium, fine. The printed raw extrapolations use
    Celik Eq. (4) even for alternating data, for which those numbers are diagnostic.
    """
    h=np.asarray(spacings,dtype=float)
    v=np.asarray(values,dtype=float)
    if h.shape!=(3,) or v.shape!=(3,) or not np.all(np.isfinite([h,v])) or np.any(h<=0) or not np.all(np.diff(h)<0):
        raise ValueError("Three finite values on decreasing positive coarse/medium/fine spacings required")
    from mesh_ladder_limits import ratio_pass
    r32,r21=h[:-1]/h[1:]
    l21,l32=np.log([r21,r32])
    e32,e21=v[0]-v[1],v[1]-v[2]
    floor=32*np.finfo(float).eps*max(float(np.max(abs(v))),np.finfo(float).tiny)
    regular=min(abs(e32),abs(e21))>floor
    pattern=("oscillatory" if np.sign(e32)!=np.sign(e21) else "monotonic") if regular else "indeterminate"
    ratio=e32/e21 if regular else None
    safety=1.25

    def pct(a,b):
        return float(100*abs(a/b)) if b!=0 and a is not None else None

    def inv_denom(x):
        return np.exp(-x)/(-np.expm1(-x))

    def estimate(order):
        if order is None or order<=0:return None
        c21=-e21*inv_denom(order*l21);c32=-e32*inv_denom(order*l32)
        fine=v[2]+c21;med=v[1]+c32
        uf=safety*abs(c21);um=safety*abs(c32);pf=pct(uf,v[2]);pm=pct(um,v[1])
        asym=pm*np.exp(-order*l21)/pf if pf is not None and pf>0 and pm is not None else None
        return dict(order=float(order),extrapolated=float(fine),extrapolated_32=float(med),
                    fine_absolute_GCI=float(uf),medium_absolute_GCI=float(um),fine_percent_GCI=pf,medium_percent_GCI=pm,
                    approximate_relative_error_21_pct=pct(e21,v[2]),approximate_relative_error_32_pct=pct(e32,v[1]),
                    extrapolated_relative_error_21_pct=pct(c21,fine),extrapolated_relative_error_32_pct=pct(c32,med),
                    asymptotic_ratio=float(asym) if asym is not None else None)

    candidates=[]
    sign_branch=None
    if regular:
        logmag=np.log(abs(e32))-np.log(abs(e21))
        sig=1 if ratio>0 else -1
        def log_denom(x):
            return x+np.log(-np.expm1(-x)) if sig==1 else np.logaddexp(0.,x)
        def rhs(order):
            return logmag+log_denom(order*l21)-log_denom(order*l32)
        def residual(order):
            return order*l21-abs(rhs(order))
        # Bracket both branches of Eq. (3a), including a negative-log/expanding sequence.
        initial=abs(logmag)/l21
        hi=max(128.,16*(1+initial),16*abs(logmag)/min(l21,l32))
        probe=np.geomspace(1.e-10,hi,401)
        function=np.array([residual(q) for q in probe])
        for i in range(len(probe)-1):
            if function[i]==0:
                candidates.append(float(probe[i]))
            elif np.signbit(function[i])!=np.signbit(function[i+1]):
                candidates.append(float(brentq(residual,probe[i],probe[i+1],xtol=1.e-12)))
        if np.isclose(l21,l32,rtol=2.e-13,atol=0):
            candidates=[float(initial)] if initial>1.e-10 else [0.]
        # A positive-log branch corresponds to a decaying one-term model (alternating
        # or monotone). The other branch receives only a diagnostic absolute order.
        compatible=[q for q in candidates if q>0 and rhs(q)>0]
        order=min(compatible or candidates,key=lambda q:abs(q-initial)) if candidates else None
        if order is not None:sign_branch="contracting" if order>0 and rhs(order)>0 else "noncontracting"
    else:
        order=None
    raw=estimate(order)
    qualified=bool(raw and pattern=="monotonic" and sign_branch=="contracting" and .5-1e-9<=order<=3.+1e-9)
    theoretical=estimate(2.)
    spread=float(np.ptp(v));mid=float((v.max()+v.min())/2)
    half=spread/2
    def combined(index,level):
        if not regular and spread<=floor:return None
        if qualified:return raw[level+"_absolute_GCI"]
        # Centre the final interval at the actual reported grid value. Cover the
        # entire midrange±half-range interval as well as raw and formal-order GCI.
        return float(max(theoretical[level+"_absolute_GCI"],abs(v[index]-mid)+half,
                         raw[level+"_absolute_GCI"] if raw else 0.))
    uf,um=combined(2,"fine"),combined(1,"medium")
    status=("Qualified monotonic three-grid estimate" if qualified else
            "Repeated or unresolved differences; observed order indeterminate" if not regular else
            "Oscillatory differences; raw extrapolation is diagnostic" if pattern=="oscillatory" else
            "Noncontracting sequence or observed order outside [0.5,3.0]")
    out=dict(h_coarse_medium_fine_m=h.tolist(),values_coarse_medium_fine=v.tolist(),r_coarse_medium=float(r32),
             r_medium_fine=float(r21),r21=float(r21),r32=float(r32),safety_factor=safety,
             epsilon32=float(e32),epsilon21=float(e21),epsilon32_over_epsilon21=float(ratio) if ratio is not None else None,
             observed_order=order,order_candidates=candidates,celik_log_branch=sign_branch,convergence_type=pattern,
             qualified_monotonic_order=qualified,status=status,
             project_refinement_ratio_pass=ratio_pass(r32,r21) if fluid_grid else bool(min(r32,r21)>1.1),celik_preferred_ratio_exceeded=bool(min(r32,r21)>1.3),
             fallback_activated=not qualified,raw_celik=raw,formal_second_order=theoretical,
             half_range_U_osc=half,range_midpoint=mid,observed_range_interval=[float(v.min()),float(v.max())],
             reported_fine_absolute_uncertainty=uf,reported_medium_absolute_uncertainty=um,
             reported_fine_percent_uncertainty=pct(uf,v[2]),reported_medium_percent_uncertainty=pct(um,v[1]),
             reported_fine_interval=[float(v[2]-uf),float(v[2]+uf)] if uf is not None else None,
             reported_method="raw three-grid GCI" if qualified else "project fault manual §9: envelope of raw GCI, formal p=2 GCI and measured range",
             method_source="https://doi.org/10.1115/1.2960953")
    for key in theoretical:
        if key!="order":
            out[key]=raw[key] if raw else None
    out["approximate_relative_error_21_pct"]=pct(e21,v[2]);out["approximate_relative_error_32_pct"]=pct(e32,v[1])
    return out


def gci(cell_counts, force, volume_m3):
    n=np.asarray(cell_counts,dtype=float);vol=np.asarray(volume_m3,dtype=float)
    if n.shape!=(3,) or not np.isfinite(n).all() or np.any(n<=0) or not np.all(np.diff(n)>0):
        raise ValueError("Three increasing positive native cell counts required")
    if vol.shape not in ((),(3,)) or not np.isfinite(vol).all() or np.any(vol<=0):
        raise ValueError("Positive fluid volume required for each grid")
    return gci_from_spacing(np.cbrt(vol/n),force)


def gci_threshold(record,limit_percent):
    """Strict redline; a fallback bound alone does not verify an indeterminate observed GCI."""
    raw=record["fine_percent_GCI"];reported=record["reported_fine_percent_uncertainty"]
    return bool(raw is not None and reported is not None and max(raw,reported)<limit_percent)

def rpm_scaling(fractions, force):
    s=np.asarray(fractions,dtype=float)
    y=np.asarray(force,dtype=float)
    if len(s)<3 or np.any(s<=0) or not np.isfinite(y).all():
        raise ValueError("The fit uses independent, nonzero, converged swirl-on runs.")
    x=s*s
    slope=np.dot(x,y)/np.dot(x,x)
    prediction=slope*x
    sst=np.sum((y-y.mean())**2)
    return dict(squared_rpm_coefficient=float(slope), r_squared_centered=float(
        1-np.sum((y-prediction)**2)/sst) if sst else None, normalized=(y/x).tolist())
