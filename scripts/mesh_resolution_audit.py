"""Measure directional actuator resolution and native octree face-edge scales."""
import h5py
import numpy as np

from cut_fluent_cells import bounds


def rotor_ray_floors(regions, targets):
    result = {}
    for rotor in regions:
        item = {}
        for direction in ('axial', 'radial'):
            rays = [r for r in rotor['face_crossing_rays'] if r['direction']==direction]
            measured = [r['cells_crossed'] for r in rays if r['cells_crossed'] is not None]
            blocked = [r['azimuth_deg'] for r in rays if r['wall_or_open_boundary_hits']>0]
            floor = targets[direction+'_cells_min']
            item[direction] = dict(floor=floor,valid_ray_counts=measured,
                                   obstructed_ray_azimuth_deg=blocked,
                                   passed=(len(rays)==4 and len(measured)+len(blocked)==4
                                           and bool(measured) and min(measured)>=floor))
        result[rotor['name']]=item
    return result


def fine_sizing_controls(config,rotors,geometry):
    """Audit the named design targets separately from measured native dimensions."""
    bounds_target=[[-1.,-.85,.35],[2.8,.95,5.65]]
    records={}
    controls={}
    for row in config.get("sizes",[]):
        for label in row.get("labels",[]):
            if label in controls:
                raise ValueError(f"Duplicate sizing control for {label}")
            controls[label]=row

    def record(label,band):
        row=controls.get(label,{})
        value=row.get("size")
        records[label]=dict(reference_band_m=list(band),nominal_size_m=value,geometry_present=label in geometry,
            passed=(label in geometry and row.get("type")=="Body Of Influence" and isinstance(value,(int,float))
                    and band[0]<=value<=band[1]))

    record("near_wake_boi",(.050,.065))
    record("mid_wake_boi",(.080,.110))
    for rotor in rotors:
        key=rotor["name"].lower().replace("-","_")
        record(key+"_boi",(.010,.014) if key=="wt_1" else (.007,.009))
        label=key+"_jet_core_boi"
        record(label,(.035,.045))
        cx,cy,cz=rotor["center_m"]
        radius=rotor["r_tip_m"]
        tube_bounds=[[cx+rotor["thickness_m"]/2,cy-radius,cz-radius],
                     [bounds_target[1][0],cy+radius,cz+radius]]
        records[label]["matches_calibrated_envelope_bounds"]=bool(label in geometry and
                    np.allclose(geometry[label],tube_bounds,rtol=0,atol=1.e-6))
        records[label]["passed"] &= records[label]["matches_calibrated_envelope_bounds"]
    expected={"WT-1"}|{f"HLP-{i}" for i in range(1,7)}
    inventory_ok=len(rotors)==7 and {r["name"] for r in rotors}==expected
    bounds_ok=bool(np.allclose(geometry["near_wake_boi"],bounds_target,rtol=0,atol=1.e-6))
    return dict(method="Requested nominal BOI target sizes with bounds checked against input body coordinates. "
                       "Independent native cell measurements are stored separately.",
                expected_near_box_bounds_m=bounds_target,near_box_matches=bounds_ok,
                calibrated_seven_rotors=inventory_ok,controls=records,
                passed=bounds_ok and inventory_ok and all(x["passed"] for x in records.values()))

def native_wake_hex_edges(mesh_path, xyz, centers, volume, owner, neighbor, rotor_model, eligible, targets):
    """Measure actual face-ring edge extrema per non-prism hexahedron in the wake."""
    # Assign cells in overlapping downstream disk envelopes to the nearest axis,
    # normalized by disk radius. Ties retain the first rotor in the calibrated model.
    tube_id=np.full(len(centers),-1,np.int8)
    nearest=np.full(len(centers),np.inf)
    memberships=np.zeros(len(centers),np.uint8)
    for i,rotor in enumerate(rotor_model):
        cx,cy,cz=rotor['center_m']
        radial=np.hypot(centers[:,1]-cy,centers[:,2]-cz)/rotor['r_tip_m']
        covered=(centers[:,0]>=cx+rotor['thickness_m']/2) & (radial<=1) & eligible
        memberships[covered]+=1
        assign=covered & (radial<nearest)
        tube_id[assign]=i
        nearest[assign]=radial[assign]
    lo_edge=np.full(len(centers),np.inf)
    hi_edge=np.zeros(len(centers))
    edge_sum=np.zeros(len(centers))
    edge_uses=np.zeros(len(centers),int)
    with h5py.File(mesh_path) as h:
        mesh=h['meshes/1']
        ctype=np.zeros(len(centers),np.int16)
        for block in mesh['cells/ctype'].values():
            a,b=bounds(block)
            ctype[a:b+1]=(block['cell-types'][:] if 'cell-types' in block
                          else int(np.asarray(block.attrs['elementType']).item()))
        candidate=eligible & (ctype==4)
        for block in mesh['faces/nodes'].values():
            lo,hi=bounds(block)
            n=block['nnodes'][:].astype(np.int64)
            offset=np.r_[0,n.cumsum()]
            for i in range(0,len(n),20000):
                j=min(i+20000,len(n))
                own,adj=owner[lo+i:lo+j],neighbor[lo+i:lo+j]
                keep=candidate[own] | candidate[adj]
                if not keep.any():
                    continue
                nodes=block['nodes'][offset[i]:offset[j]]
                starts=offset[i:j]-offset[i]
                for m in np.unique(n[i:j][keep]):
                    rows=np.flatnonzero(keep & (n[i:j]==m))
                    ring=xyz[nodes[starts[rows,None]+np.arange(m)]]
                    lengths=np.linalg.norm(np.roll(ring,-1,axis=1)-ring,axis=2)
                    low,high=lengths.min(axis=1),lengths.max(axis=1)
                    length_sum=lengths.sum(axis=1)
                    for cells in (own[rows],adj[rows]):
                        selected=candidate[cells]
                        np.minimum.at(lo_edge,cells[selected],low[selected])
                        np.maximum.at(hi_edge,cells[selected],high[selected])
                        np.add.at(edge_sum,cells[selected],length_sum[selected])
                        np.add.at(edge_uses,cells[selected],m)
    return summarize_wake_edges(rotor_model,tube_id,memberships,candidate,volume,lo_edge,hi_edge,
                                edge_sum,edge_uses,targets)


def summarize_wake_edges(rotors,tube_id,memberships,candidate,volume,lo_edge,hi_edge,edge_sum,edge_uses,targets):
    from mesh_region_budget import quant
    if (np.any(edge_uses[candidate]==0) or not np.isfinite(lo_edge[candidate]).all()
            or np.any(lo_edge[candidate]<=0) or np.any(hi_edge[candidate]<lo_edge[candidate])
            or not np.isfinite(volume[candidate]).all() or np.any(volume[candidate]<=0)):
        raise ValueError('Incomplete native hex topology or volume')
    mean_edge=np.zeros(len(candidate))
    mean_edge[candidate]=edge_sum[candidate]/edge_uses[candidate]
    if not np.isfinite(mean_edge[candidate]).all():
        raise ValueError('Nonfinite mean face-ring edge')

    def summary(mask,band):
        low,high=lo_edge[mask],hi_edge[mask]
        lengths,vol=mean_edge[mask],volume[mask]
        a,b=band
        count=len(lengths)
        weight=float(vol.sum())
        mean=float(np.average(lengths,weights=vol)) if count else None
        # Roundoff at an exact octree edge target is not a physical size deviation.
        eps=64*np.finfo(float).eps*max(1.,b)
        below=lengths<a-eps
        above=lengths>b+eps
        fractions={k:float(vol[take].sum()/weight) if count else None for k,take in
                   [('below',below),('in_band',~(below|above)),('above',above)]}
        return dict(hex_count=count,hex_volume_m3=weight,reference_band_m=[a,b],
                    minimum_face_edge_per_hex_m=quant(low),maximum_face_edge_per_hex_m=quant(high),
                    mean_face_edge_per_hex_m=quant(lengths),volume_weighted_mean_edge_m=mean,
                    volume_fraction_of_mean_edge=fractions,
                    count_all_edges_in_band=int(((low>=a-eps)&(high<=b+eps)).sum()),
                    count_any_edge_above_upper=int((high>b+eps).sum()),
                    count_any_edge_below_lower=int((low<a-eps).sum()),
                    representative_resolution_at_or_finer_than_upper=bool(mean is not None and mean<=b+eps))

    core=summary(candidate & (tube_id>=0),targets['core'])
    outer=summary(candidate & (tube_id<0),targets['outer_transition'])
    per_rotor={rotor['name']:summary(candidate & (tube_id==i),targets['core'])
               for i,rotor in enumerate(rotors)}
    assigned=sum(item['hex_count'] for item in per_rotor.values())
    if assigned!=core['hex_count'] or assigned+outer['hex_count']!=int(candidate.sum()):
        raise ValueError('Hex region counts are inconsistent')
    return dict(method='Actual CFF face-ring edge lengths on native type-4 non-prism wake cells. '
                'Each cell size is the arithmetic mean over its face-ring edge occurrences '
                '(twelve edges counted twice on six quadrilateral faces). Regional means and '
                'below/in/above fractions use native polyhedral volume. The sizing region is the '
                'calibrated full-radius disk envelope from the downstream disk face to the near-box exit; '
                'it is a pre-solve geometry, not a measurement of contracted fluid streamtubes.',
                overlap_assignment='Minimum transverse distance divided by disk radius; ties retain calibrated order.',
                overlapping_hex_count=int(np.count_nonzero(candidate & (memberships>1))),
                gate_basis='Per-tube and outer-region volume-weighted mean physical edge must be at or finer '
                           'than its target upper size. Local transitions and locally finer cells are allowed. '
                           'Fractions, percentiles and individual edge extrema are diagnostic, with no fraction cutoff.',
                core=core,outer_transition=outer,per_rotor_core=per_rotor)
