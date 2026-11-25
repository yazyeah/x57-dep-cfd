"""Static actuator targets for the coursework geometry. Run under env_d_only and control_gate."""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
from scipy.optimize import brentq
from scipy.spatial import ConvexHull
from scipy.spatial.distance import cdist
from inspect_x57_geometry import INPUT_STL, IN2M, quat_to_matrix

ROOT = Path(__file__).resolve().parents[1]
RHO = 1.225
MU = 1.789e-5
THICKNESS = 0.05
# Subsampled OpenFAST NACA64_A17 polar. Columns are alpha in degrees, Cl and Cd.
POLAR = np.array([list(map(float, line.split())) for line in """-90 -0.067 1.3587
-85 -0.184 1.3456
-80 -0.299 1.3181
-75 -0.409 1.2765
-70 -0.512 1.2212
-65 -0.606 1.1532
-60 -0.689 1.0731
-55 -0.759 0.9822
-50 -0.814 0.882
-45 -0.85 0.7742
-40 -0.866 0.661
-35 -0.86 0.5451
-30 -0.829 0.4295
-25 -0.853 0.3071
-20 -0.958 0.1785
-15 -1.105 0.0535
-10 -0.711 0.0111
-5 -0.151 0.0079
-4 -0.017 0.0072
-2 0.213 0.0054
0 0.442 0.0052
2 0.67 0.0053
4 0.898 0.0054
5 1.011 0.0058
6 1.103 0.0091
8 1.257 0.0124
9 1.326 0.0136
10 1.382 0.015
11 1.415 0.0383
12 1.434 0.0613
13 1.451 0.0841
14 1.448 0.1065
15 1.445 0.1287
16 1.448 0.1509
18 1.448 0.1947
20 1.428 0.2379
25 1.168 0.3377
30 0.926 0.4294
35 0.8 0.5324
40 0.804 0.6452
45 0.793 0.7573
50 0.763 0.8664
55 0.717 0.9708
60 0.656 1.0693
65 0.582 1.1606
70 0.495 1.2438
75 0.398 1.3178
80 0.291 1.3809
85 0.176 1.4304
90 0.053 1.4565""".splitlines()])
NASA_HLP = 'https://ntrs.nasa.gov/citations/20240014295'
NASA_CRUISE = 'https://ntrs.nasa.gov/citations/20240006496'
POLAR_SOURCE = 'https://raw.githubusercontent.com/OpenFAST/r-test/main/glue-codes/openfast/5MW_Baseline/Airfoils/NACA64_A17.dat'

def cylinder_section(tri, r):
    """Intersect edges with the circular cylinder and return axial and arc coordinates."""
    starts = tri.reshape(-1, 3)
    delta = (np.roll(tri, -1, axis=1) - tri).reshape(-1, 3)
    a = np.sum(delta[:, 1:]**2, axis=1)
    b = 2 * np.sum(starts[:, 1:] * delta[:, 1:], axis=1)
    c = np.sum(starts[:, 1:]**2, axis=1) - r**2
    d = b*b - 4*a*c
    keep = (a > 1e-16) & (d >= 0)
    xyz = []
    for sign in (-1, 1):
        u = (-b[keep] + sign*np.sqrt(d[keep])) / (2*a[keep])
        valid = (u >= 0) & (u <= 1)
        xyz.append((starts[keep] + u[:, None]*delta[keep])[valid])
    xyz = np.vstack(xyz)
    return xyz[:, 0], np.arctan2(xyz[:, 2], xyz[:, 1])

def measure_chord(x, angle, r):
    # The chord endpoints are the farthest apart pair on the unwrapped cylindrical section.
    theta0 = np.angle(np.mean(np.exp(1j*angle)))
    s = r*np.angle(np.exp(1j*(angle-theta0)))
    section = np.c_[s, x]
    hull = section[ConvexHull(section).vertices]
    dist = cdist(hull, hull)
    i,j = np.unravel_index(dist.argmax(), dist.shape)
    ds,dx = hull[i]-hull[j]
    return float(dist[i,j]), float(np.degrees(np.arctan(dx/ds)))

def cad_geometry(audit):
    rot = quat_to_matrix(audit['baked_stl_rotation_removed']['glb_node0_quaternion_xyzw'])
    dtype = np.dtype([('normal','<f4',3), ('v','<f4',(3,3)), ('attr','<u2')])
    disk = np.memmap(INPUT_STL, mode='r', dtype=dtype, offset=84)
    props=audit['starboard_propellers_detected']
    first_blade=[];remaining=13656
    nearby={p['name']:[] for p in props}
    for start in range(0,len(disk),30000):
        xyz=np.einsum('tij,jk->tik',disk['v'][start:start+30000],rot)*IN2M
        star=xyz[xyz[:,:,2].max(axis=1)>-1e-5]
        if remaining and len(star):
            part=star[:remaining].copy();first_blade.append(part);remaining-=len(part)
        cent=star.mean(axis=1)
        for p in props:
            center=np.array([p['x_disk_m'],p['y_axis_m'],p['z_axis_m']])
            r=.70*p['r_tip_m']
            choose=(abs(cent[:,0]-center[0])<.08)&(np.linalg.norm(cent[:,1:]-center[1:],axis=1)<1.3*r)
            if np.any(choose):nearby[p['name']].append(star[choose]-center)
    if remaining:raise ValueError('Incomplete original wingtip blade in supplied CAD')
    wt=np.concatenate(first_blade)
    p = audit['starboard_propellers_detected'][-1]
    wt[:, :, 1:] -= [p['y_axis_m'], p['z_axis_m']]
    root,tip = p['r_effective_hub_m'],p['r_tip_m']
    xyzr = np.linalg.norm(wt[:,:,1:],axis=2)
    assert abs(xyzr.max()-tip) < 0.002 and xyzr.min() < root
    fractions = np.linspace(.002, .998, 60)
    stations = []
    for r in root + (tip-root)*fractions:
        selected = wt[(xyzr.min(1)<=r) & (xyzr.max(1)>=r)]
        x,theta = cylinder_section(selected,r)
        chord,slope = measure_chord(x,theta,r)
        stations.append([float(r),chord,abs(slope)])
    # Determine rotation from isolated arcs at 70 percent blade radius on each propeller.
    signs = {}
    for p in props:
        r=.70*p['r_tip_m']
        tri=np.concatenate(nearby.pop(p['name']))
        xr,ang = cylinder_section(tri,r)
        order = np.argsort(ang)
        ang,xr = ang[order],xr[order]
        gaps = np.diff(np.r_[ang,ang[0]+2*np.pi])
        breaks = np.flatnonzero(gaps>.18)
        arcs = []
        for end,start in zip(breaks,np.roll(breaks,1)):
            ids = np.arange(start+1, end+1 if end>start else end+1+len(ang)) % len(ang)
            if len(ids) < 10:
                continue
            chord,slope = measure_chord(xr[ids],ang[ids],r)
            if .015 < chord < .22 and 8 < abs(slope) < 78:
                arcs.append(slope)
        if len(arcs)!=p['blade_count'] or min(arcs)*max(arcs) <= 0:
            raise ValueError(f"Inspect {p['name']}: slopes {arcs} gaps {len(breaks)}")
        signs[p['name']] = dict(positive_x_spin_sign=int(-np.sign(np.median(arcs))),measured_chord_slopes_deg=arcs)
    return np.array(stations),signs

def wingtip_bemt(p, sections, degrees, n):
    """Coupled annular axial/angular momentum and blade-element equilibrium at J=0."""
    root,tip = p['r_effective_hub_m'],p['r_tip_m']
    dr = (tip-root)/n
    r = root+(np.arange(n)+.5)*dr
    chord = np.interp(r, sections[:,0], sections[:,1])
    beta = np.interp(r, sections[:,0], sections[:,2])+degrees
    solidity8 = p['blade_count']*chord/(8*np.pi*r)
    omega = p['nominal_rpm']*2*np.pi/60
    def coefficients(phi):
        sn,cs = np.sin(phi),np.cos(phi)
        # Prandtl finite blade tip and hub loss factors.
        k = .5*p['blade_count']/sn
        f = 4/np.pi**2*np.arccos(np.exp(-k*(tip-r)/r))*np.arccos(np.exp(-k*(r-root)/root))
        alpha = beta-np.degrees(phi)
        cl = np.interp(alpha, POLAR[:,0], POLAR[:,1])
        cd = np.interp(alpha, POLAR[:,0], POLAR[:,2])
        cn,ct = cl*cs-cd*sn,cl*sn+cd*cs
        return cn,ct,f
    low,high = np.full(n,1.e-6),np.full(n,np.pi/2-1.e-6)
    if np.any(coefficients(low)[0]<=0):
        raise ValueError('Trial collective produces a windmilling annulus')
    for _ in range(50):
        phi = (low+high)/2
        cn,ct,f = coefficients(phi)
        too_large = np.sin(phi)**2 - solidity8*cn/f > 0
        high = np.where(too_large,phi,high)
        low = np.where(too_large,low,phi)
    sn,cs = np.sin(phi),np.cos(phi)
    rel_speed = omega*r/(cs+solidity8*ct/(f*sn))
    line_force = .5*RHO*rel_speed**2 * p['blade_count'] * chord
    thrust = np.sum(line_force*cn)*dr
    torque = np.sum(line_force*ct*r)*dr
    axial = rel_speed*sn
    tangential = omega*r-rel_speed*cs
    np.testing.assert_allclose(line_force*cn, 4*np.pi*RHO*f*r*axial**2,rtol=1e-8)
    np.testing.assert_allclose(line_force*ct*r,4*np.pi*RHO*f*r**2*axial*tangential,rtol=1e-8)
    return dict(thrust_N=thrust,torque_Nm=torque,relative_mach_range=[rel_speed.min()/340.3,rel_speed.max()/340.3],
                section_reynolds_range=[(RHO*rel_speed*chord/MU).min(),(RHO*rel_speed*chord/MU).max()],
                angle_of_attack_deg=[(beta-np.degrees(phi)).min(),(beta-np.degrees(phi)).max()])

def input_digest():
    with INPUT_STL.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def model(audit):
    measurements = audit
    for p in audit['starboard_propellers_detected']:
        p['r_effective_hub_m'] = measurements['spinner_radii'][p['name']]['maximum_over_disk_slab_m']
    sections,signs = cad_geometry(audit)
    properties = audit['starboard_propellers_detected']
    wt = properties[-1]
    # NASA publishes cruise torque at 100 percent command and 2700 rpm.
    target = 127.5
    def solve_collective(n):
        return brentq(lambda deg:wingtip_bemt(wt,sections,deg,n)['torque_Nm']-target, -22., -18.)
    collective = solve_collective(256)
    cruise = wingtip_bemt(wt, sections, collective,256)
    check = wingtip_bemt(wt, sections, solve_collective(512),512)
    # NASA fixed mode uses 4800 RPM. Extrapolate one 5-KEAS interval using two closest rows.
    # Standard-atmosphere Table 16 thrust in lbf and Table 14 torque in Nm.
    t4800 = (2*69.9-68.8)*4.4482216152605
    q4800 = 2*21.1-21.3
    n0,d0 = 4800/60,2*.28796
    hlp_ct = t4800/(RHO*n0**2*d0**4)
    hlp_cq = q4800/(RHO*n0**2*d0**5)
    rotors=[]
    for p in properties:
        n = p['nominal_rpm']/60
        d = 2*p['r_tip_m']
        if p['name']=='WT-1':
            thrust,torque=cruise['thrust_N'],cruise['torque_Nm']
        else:
            thrust,torque = hlp_ct*RHO*n*n*d**4, hlp_cq*RHO*n*n*d**5
        root,tip=p['r_effective_hub_m'],p['r_tip_m']
        width=tip-root
        # 2 pi t integral r w(s) dr; integrals of beta polynomials on s in [0,1].
        norm_t=2*np.pi*THICKNESS*width*(4*root/15+16*width/105)
        norm_q=2*np.pi*THICKNESS*width*(np.pi*root/8+np.pi*width/16)
        rotors.append(dict(name=p['name'],center_m=[p['x_disk_m'],p['y_axis_m'],p['z_axis_m']],
                           r_hub_m=root,spinner_measurement=measurements['spinner_radii'][p['name']],r_tip_m=tip,thickness_m=THICKNESS,nominal_rpm=p['nominal_rpm'],
                           **signs[p['name']],ct=thrust/(RHO*n*n*d**4),cq=torque/(RHO*n*n*d**5),
                           continuum_norm_t_m3=norm_t,continuum_norm_q_m3=norm_q,
                           targets=[dict(s=s,rpm=p['nominal_rpm']*s,thrust_N=thrust*s*s,
                                         torque_magnitude_Nm=torque*s*s,shaft_power_W=torque*2*np.pi*n*s**3)
                                    for s in (.5,.75,1.)]))
    return dict(status='prescribed model inputs; discrete Fluent verification pending',rho_kg_m3=RHO,
        sources=dict(hlp=NASA_HLP,cruise=NASA_CRUISE,cruise_section_polar=POLAR_SOURCE),
        geometry_input_sha256=input_digest(),
        hlp_calibration=dict(method='Linear extrapolation of the NASA calibrated BEMT performance map from 5 and 10 KEAS to zero, then similarity scaling of CT and CQ to CAD diameter and requested RPM.',
        fixed_mode_rpm=4800,table_14_torque_Nm_5_10_KEAS=[21.1,21.3],table_16_thrust_lbf_5_10_KEAS=[69.9,68.8],
        diameter_reference_m=d0,table_configuration='80-degree deployed folding HLP, standard sea-level atmosphere.',
        limitation='A small extrapolation of predicted near-static data. Prescribed RPM ignores HLP current and torque limiting.'),
        cruise_calibration=dict(method='Isolated static BEMT. CAD blade chord and geometric twist from cylinder intersections; uniform collective trim matches the published full torque command at nominal RPM. Pitch is held fixed for the sweep.',
            torque_target_Nm=target,collective_offset_deg=collective,section_data_columns=['r_m','chord_m','pitch_deg'],section_data=sections.tolist(),
            polar='NACA64_A17 surrogate at Re 750000 including its original rotational stall correction. Real MT blade polars and controller flight dynamics are unavailable. No compressibility or further Reynolds correction.',
            quadrature='256 equally spaced annulus midpoints with Prandtl tip and hub losses and induced swirl.',
            coarse_fine_difference_N=check['thrust_N']-cruise['thrust_N'],**cruise),
        source_terms=dict(hub_definition='Maximum CAD spinner radius over the entire 0.05 m disk slab.',radial_fraction='h=(r-rhub)/(rtip-rhub)',extent='abs(x-xdisk)<=t/2; rhub<=r<=rtip',
            axial='Sx=T/norm_t*h*sqrt(1-h)',tangential='Stheta=sign*Q/norm_q*sqrt(h*(1-h))/r; Sy=-Stheta*(z-zaxis)/r; Sz=Stheta*(y-yaxis)/r',
            discrete_normalization='For each grid integrate both dimensionless weight fields over fluid cell volumes to replace continuum norms. Recheck each source force and torque using Fluent reports.',
            swirl_off='Hold axial thrust at the matched swirl-on value. Set tangential source to zero.',
            mirrored_configuration='Starboard CAD rotation follows negative axial-to-positive-azimuth chord slope for positive-x rotation. Reflecting to port reverses axial torque. NASA reports alternating adjacent HLPs on the later simulator configuration.'),
        rotors=rotors,fluent_discrete_integrals=None)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--write', action='store_true')
    args=parser.parse_args()
    model_data=model(json.loads((ROOT/'01_geometry'/'geometry_audit.json').read_text(encoding='utf-8-sig')))
    for p in model_data['rotors']:
        print(p['name'],p['positive_x_spin_sign'],p['targets'][-1])
    print('WT collective offset:',model_data['cruise_calibration']['collective_offset_deg'])
    if args.write:
        dest=ROOT/'DELIVERABLES'/'data'/'actuator_disk_model.json'
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp=dest.with_suffix('.tmp')
        tmp.write_text(json.dumps(model_data,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        tmp.replace(dest)
