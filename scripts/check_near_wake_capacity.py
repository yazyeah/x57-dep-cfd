"""Conservative packing bound for fully size-limited octree cells in the Fine near-wake box."""
import json
import math
from pathlib import Path

import numpy as np

from p2_geometry_io import WALLS, stl_triangles
from control_gate import atomic_write_json

ROOT = Path(__file__).resolve().parents[1]


def free_volume(box, exclusions, pad):
    low, high = box[0] + pad, box[1] - pad
    clipped = []
    for a, b in exclusions:
        a = np.maximum(a - pad, low)
        b = np.minimum(b + pad, high)
        if np.all(b > a):
            clipped.append((a, b))
    bounds = np.asarray(clipped)
    cuts = [np.unique(np.r_[low[k], bounds[:, :, k].ravel(), high[k]]) for k in range(3)]
    center = np.stack(np.meshgrid(*[(c[1:]+c[:-1])/2 for c in cuts], indexing='ij'), axis=-1)
    dx, dy, dz = np.meshgrid(*(np.diff(c) for c in cuts), indexing='ij')
    free = np.ones(dx.shape, dtype=bool)
    for a, b in clipped:
        free &= ~((center >= a) & (center <= b)).all(axis=-1)
    return float((dx*dy*dz)[free].sum())


def main():
    directory = ROOT / '01_geometry/p2_fine_tail_symmetry'
    cfg = json.loads((ROOT / '02_mesh/fine/f_scoped_tail_01/mesh_config.json').read_text())
    box = np.array(cfg['near_wake_bounds'], dtype=float)
    exclusions = []
    for wall in WALLS:
        surface = stl_triangles(directory / (wall + '.stl')).astype(float)
        # A whole solid-component bounding box is conservative. The additional 3 mm
        # also exceeds the specified total Fine wing stack at the maximum 1.18 growth.
        exclusions.append((surface.min(axis=(0, 1)) - .003, surface.max(axis=(0, 1)) + .003))
    rotors = json.loads((ROOT / 'DELIVERABLES/data/actuator_disk_model.json').read_text())['rotors']
    for r in rotors:
        center = np.array(r['center_m'])
        half = np.array([r['thickness_m']/2, r['r_tip_m'], r['r_tip_m']])
        exclusions.append((center-half, center+half))
    edge = .045
    # Round a full cube diagonal UP so that cells intersecting boundaries cannot inflate
    # the lower bound; Fluent's interior octree hexes are Cartesian cubes.
    pad = math.ceil(edge*np.sqrt(3)*1000)/1000
    volume = free_volume(box, exclusions, pad)
    capacity = math.floor(1_044_000 * .24)
    result = dict(applies_if='All ordinary fluid in the entire near-wake box must have octree cells of at most 45 mm edge. A refinement target only for actual jet tubes is a different physical domain.',
                  near_wake_bounds_m=box.tolist(), box_volume_m3=float(np.prod(box[1]-box[0])),
                  cube_edge_upper_m=edge, margin_m=pad, excluded_bounds_m=[np.asarray(t).tolist() for t in exclusions],
                  excluded_airframe_layer_padding_m=.003, guaranteed_free_inner_volume_m3=volume,
                  required_cells_lower_bound=math.ceil(volume / edge**3), maximum_count_at_24_percent=capacity,
                  minimum_fraction_of_maximum_fine_cells=math.ceil(volume/edge**3)/1_044_000,
                  diagnostic_only=True)
    sensitivity = []
    for extra in (.010, .025, .050):
        padded = [(a-extra, b+extra) for a, b in exclusions]
        clear = free_volume(box, padded, pad)
        sensitivity.append(dict(extra_padding_each_side_m=extra,remaining_volume_m3=clear,
                                required_cells=math.ceil(clear/edge**3)))
    result['additional_exclusion_padding_sensitivity'] = sensitivity
    atomic_write_json(ROOT / '02_mesh/fine/near_wake_capacity_bound.json', result)
    print(json.dumps({k:v for k,v in result.items() if k!='excluded_bounds_m'}))


if __name__ == '__main__':
    main()
