"""Attach native Fluent cell fields to VTK CFF blocks with checked CFF-to-VTK correspondence."""
from pathlib import Path
import h5py
import numpy as np
import pyvista as pv
from vtkmodules.vtkIOFLUENTCFF import vtkFLUENTCFFReader
from vtkmodules.vtkCommonDataModel import vtkStaticCellLocator
from extract_fluent_fields import sample

NATIVE=("SV_P","SV_U","SV_V","SV_W")


def mapped_volume(case,data,volume,requested):
    """Return one unstructured fluid grid, native CFF cell IDs, and coverage evidence."""
    case,data,volume=map(lambda p:Path(p).resolve(strict=True),(case,data,volume))
    r=vtkFLUENTCFFReader();r.SetFileName(str(case));r.SetRenameArrays(False);r.UpdateInformation()
    r.DisableAllCellArrays();r.DisableAllFaceArrays()
    native_pair=case.name[:-7]+".dat.h5"==data.name
    names={r.GetCellArrayName(i) for i in range(r.GetNumberOfCellArrays())}
    if native_pair:
        if not set(NATIVE)<=names:raise ValueError("CFF VTK reader did not expose native pressure and three velocity components")
        for name in NATIVE:r.SetCellArrayStatus(name,1)
    r.Update();mb=pv.wrap(r.GetOutput());blocks=[b for b in mb if b is not None and b.n_cells]
    with h5py.File(case) as fc,h5py.File(data) as fd,h5py.File(volume) as f:
        if Path(f.attrs["mesh"]).resolve()!=case or Path(f.attrs["data"]).resolve()!=data:
            raise ValueError("Mapped field tensor belongs to a different accepted case or data")
        top=fc["meshes/1/cells/zoneTopology"]
        intervals=list(zip(top["minId"][:].astype(int),top["maxId"][:].astype(int),strict=True))
        if len(intervals)!=len(blocks):raise ValueError("Expected exactly one VTK fluid block per Fluent native volume zone")
        nc=sum(b.n_cells for b in blocks)
        if nc!=len(f["xyz_m"]):raise ValueError("Incomplete native VTK volume coverage")
        fields=fd["results/1/phase-1/cells"]
        evidence=[];zones_used=set()
        for blk in blocks:
            locator=vtkStaticCellLocator();locator.SetDataSet(blk);locator.BuildLocator()
            options=[(lo,hi) for lo,hi in intervals if hi-lo+1==blk.n_cells and (lo,hi) not in zones_used]
            validated=[]
            for lo,hi in options:
                ids=np.arange(lo,hi+1)
                xyz=f["xyz_m"][lo-1:hi];pressure=f["p_gauge_Pa"][lo-1:hi];velocity=f["velocity_m_s"][lo-1:hi]
                if not all(np.allclose(source,sample(fields,key,ids).reshape(-1),rtol=6e-6,atol=7e-6)
                           for source,key in zip([pressure,*velocity.T],NATIVE)):
                    raise ValueError("Joined volume and native pressure/velocity HDF values disagree")
                vset=[blk.cell_data[k] for k in NATIVE] if native_pair else []
                probes=np.unique(np.linspace(0,blk.n_cells-1,min(151,blk.n_cells),dtype=int))
                loc=np.array([locator.FindCell(v) for v in xyz[probes]],dtype=int)
                if np.any(loc<0):continue
                direct=(native_pair and np.array_equal(loc,probes) and
                        all(np.allclose(v,s,rtol=6e-6,atol=7e-6) for v,s in zip(vset,[pressure,*velocity.T])))
                if direct:
                    order=np.arange(len(ids));method="full native pressure and 3 velocity arrays plus stratified centroid locator"
                else:
                    # Explicitly align a renamed autosave or MPI-reordered block with physical volume centroids.
                    locations=np.fromiter((locator.FindCell(v) for v in xyz),dtype=int,count=len(ids))
                    if (locations<0).any() or len(np.unique(locations))!=len(ids):continue
                    order=np.argsort(locations)
                    if native_pair and not all(np.allclose(v,s[order],rtol=6e-6,atol=7e-6) for v,s in zip(vset,[pressure,*velocity.T])):continue
                    method="all geometry centroids located bijectively, with four HDF native fields checked"
                validated.append((lo,hi,order,method,len(probes)))
            if len(validated)!=1:raise ValueError("Ambiguous or invalid VTK and native zone mapping")
            lo,hi,order,method,nprobe=validated[0];zones_used.add((lo,hi))
            blk.cell_data["native_cell_id"]=np.arange(lo,hi+1)[order]
            for key in requested:blk.cell_data[key]=f[key][lo-1:hi][order]
            evidence.append(dict(first_native_cell=int(lo),last_native_cell=int(hi),cell_count=blk.n_cells,
                                 sampled_centroids=nprobe,method=method))
    result=blocks[0] if len(blocks)==1 else pv.MultiBlock(blocks).combine(merge_points=True)
    return result,evidence
