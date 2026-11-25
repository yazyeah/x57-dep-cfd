"""Validate a Fluent cell-center ASCII manifest against the exact paired CFF case/data."""
from pathlib import Path
import argparse
import json
import re

import h5py
import numpy as np
import pandas as pd

from cut_fluent_cells import bounds, read_id_blocks
from extract_fluent_fields import sample


def normalized(token):
    return re.sub("[^a-z0-9]", "", str(token).casefold())


def verify(manifest):
    manifest=manifest.resolve(strict=True)
    m=json.loads(manifest.read_text())
    folder=manifest.parent
    files=[(folder/m[k]).resolve(strict=True) for k in ("file","case","data")]
    if any(f.parent!=folder for f in files):
        raise ValueError("Manifest paths must name files adjacent to the manifest.")
    csvfile,case,data=files
    table=pd.read_csv(csvfile,skipinitialspace=True,encoding="utf-8-sig")
    if not len(table) or not np.isfinite(table.to_numpy(dtype=float)).all():
        raise ValueError("The native ASCII table contains missing or nonfinite data.")
    cols={normalized(c):c for c in table}
    required={q:cols[normalized(alias)] for q,alias in m["native_fields"].items()}
    xyz=table[[cols[k+"coordinate"] for k in "xyz"]].to_numpy()
    observations=table[required["pressure_Pa"]].to_numpy()
    with h5py.File(case) as fc, h5py.File(data) as fd:
        mesh=fc["meshes/1"]
        cell_ids=np.concatenate([np.arange(int(lo),int(hi)+1,dtype=np.int64)
                                 for lo,hi in zip(mesh["cells/zoneTopology/minId"],mesh["cells/zoneTopology/maxId"],strict=True)])
        cell_ids.sort()
        if len(cell_ids)!=len(table):
            raise ValueError(f"Expected {len(cell_ids)} fluid cells; ASCII contains {len(table)} rows.")
        pressure=sample(fd["results/1/phase-1/cells"],"SV_P",cell_ids).reshape(-1)
        sample_rows=np.unique(np.linspace(0,len(cell_ids)-1,min(31,len(cell_ids))).astype(int))
        chosen=cell_ids[sample_rows]
        nf=int(max(mesh["faces/zoneTopology/maxId"]))
        nodes=read_id_blocks(mesh["nodes/coords"],int(max(mesh["nodes/zoneTopology/maxId"])),float,3)
        owners=read_id_blocks(mesh["faces/c0"],nf,np.int64)
        neighbors=read_id_blocks(mesh["faces/c1"],nf,np.int64)
        bounds_lo={c:np.full(3,np.inf) for c in chosen}
        bounds_hi={c:np.full(3,-np.inf) for c in chosen}
        for block in mesh["faces/nodes"].values():
            lo,hi=bounds(block)
            mask=np.isin(owners[lo:hi+1],chosen)|np.isin(neighbors[lo:hi+1],chosen)
            if not mask.any():
                continue
            offsets=np.r_[0,np.cumsum(block["nnodes"][:],dtype=np.int64)]
            for i in np.flatnonzero(mask):
                pts=nodes[block["nodes"][offsets[i]:offsets[i+1]]]
                for c in (owners[i+lo],neighbors[i+lo]):
                    if c in bounds_lo:
                        bounds_lo[c]=np.minimum(bounds_lo[c],pts.min(axis=0))
                        bounds_hi[c]=np.maximum(bounds_hi[c],pts.max(axis=0))
        cmin=np.asarray([bounds_lo[c] for c in chosen])
        cmax=np.asarray([bounds_hi[c] for c in chosen])
        for id_column in dict.fromkeys([required["cell_id"],cols.get("cellnumber")]):
            if id_column is None:
                continue
            ids=table[id_column].to_numpy()
            if np.any(ids!=np.rint(ids)):
                continue
            order=np.argsort(ids)
            for offset in (0,1):
                if not np.array_equal(ids[order]+offset,cell_ids):
                    continue
                err=abs(pressure-observations[order])
                aligned=np.allclose(pressure,observations[order],rtol=4.e-6,atol=5.e-6)
                loc=xyz[order[sample_rows]]
                box_match=np.all((loc>=cmin-5.e-6)&(loc<=cmax+5.e-6))
                if aligned and box_match:
                    return dict(passed=True,cells=len(table),native_id_column=id_column,
                                add_to_native_id_for_cff=offset,pressure_max_abs_error_Pa=float(err.max()),
                                pressure_rtol=4.e-6,pressure_atol_Pa=5.e-6,cell_boxes_checked=len(chosen),
                                cell_box_tolerance_m=5.e-6,cell_center_coordinate_columns=[cols[k+"coordinate"] for k in "xyz"],
                                fields=required)
    raise ValueError("No native ID convention matches all CFF pressures and sampled CFF cell boxes.")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest",type=Path)
    args=parser.parse_args()
    result=verify(args.manifest)
    name=args.manifest.name.replace("_native_field_manifest.json","_native_field_qa.json")
    if name==args.manifest.name:
        parser.error("Expected the Fluent worker's _native_field_manifest.json")
    args.manifest.with_name(name).write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
