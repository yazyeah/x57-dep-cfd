"""Derive rotor-wake and stress diagnostics from Fluent's native cell-centre export."""
import argparse
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from compare_x57_cases import ROOT, accepted
from cut_fluent_cells import cut_mesh
from verify_native_cell_export import verify


def turbulence_diagnostics(gradient, mu_t):
    """gradient[n,i,j] = dU_i/dx_j in the aircraft-fixed right-handed CAD axes."""
    strain = .5*(gradient+gradient.transpose(0,2,1))
    spin = .5*(gradient-gradient.transpose(0,2,1))
    q = .5*(np.sum(spin*spin,axis=(1,2))-np.sum(strain*strain,axis=(1,2)))
    omega = np.column_stack((gradient[:,2,1]-gradient[:,1,2],gradient[:,0,2]-gradient[:,2,0],gradient[:,1,0]-gradient[:,0,1]))
    return q, omega, mu_t*(gradient[:,0,1]+gradient[:,1,0])


def write_volume(case_name):
    qa,cas,dat=accepted(case_name)
    if not qa.get("passed"):
        raise ValueError("Wake extraction needs the accepted native aircraft endpoint")
    stem=qa["accepted_stem"]
    manifest=cas.parent/(stem+"_native_field_manifest.json")
    metadata=json.loads(manifest.read_text())
    if (cas.parent/metadata["case"]).resolve()!=cas or (dat.parent/metadata["data"]).resolve()!=dat:
        raise ValueError("Native field extraction belongs to a different Fluent endpoint")
    alignment=verify(manifest)
    qref=float(json.loads((cas.parent/"solver_physics.json").read_text())["q_ref_Pa"])
    if qref<=0:
        raise ValueError("Positive disk-induced reference dynamic pressure required in static conditions")
    table=cas.parent/metadata["file"]
    folder=ROOT/"04_postproc"/case_name
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/"native_volume_fields.h5"
    staging=target.with_suffix(".pending.h5")
    n=alignment["cells"]
    field=alignment["fields"]
    axis="xyz"
    gradients=["d"+u+"_d"+x+"_per_s" for u in "uvw" for x in axis]
    required=["pressure_Pa","total_pressure_Pa","rho_kg_m3","k_m2_s2","mu_t_Pa_s","u_m_s","v_m_s","w_m_s","omega_x_per_s",*gradients]
    columns={field[key] for key in required}|{alignment["native_id_column"],*alignment["cell_center_coordinate_columns"]}
    seen=np.zeros(n,dtype=bool)
    with h5py.File(staging,"w") as h:
        h.attrs.update(case=case_name,accepted_stem=stem,mesh=str(cas),data=str(dat),q_ref_Pa=qref,
                       reynolds_shear="Modeled -rho<u'v'> = mu_t*(du/dy+dv/dx), Boussinesq SST/RKE closure.",
                       q_criterion="Q = (||Omega||_F^2 - ||S||_F^2)/2; rotation dominance, s^-2.",
                       total_pressure_coefficient="Fluent gauge total pressure / q_ref")
        ds={}
        for key in ["xyz_m","velocity_m_s","vorticity_s_inv","rho_kg_m3","p_gauge_Pa","p0_gauge_Pa","Cp0","k_m2_s2",
                    "mu_t_Pa_s","reynolds_shear_xy_Pa","Q_s_inv2","q_second_invariant_s_inv2"]:
            shape=(n,3) if key in {"xyz_m","velocity_m_s","vorticity_s_inv"} else (n,)
            ds[key]=h.create_dataset(key, shape, dtype="f8",chunks=True,shuffle=True,compression="lzf")
        max_error=0.
        scale=0.
        for chunk in pd.read_csv(table,skipinitialspace=True,usecols=list(columns),chunksize=65536):
            global_ids=chunk[alignment["native_id_column"]].to_numpy(dtype=np.int64)+alignment["add_to_native_id_for_cff"]
            order=np.argsort(global_ids)
            idx=global_ids[order]-1
            if np.any(idx<0) or np.any(idx>=n) or np.any(np.diff(idx)==0) or np.any(seen[idx]):
                raise ValueError("Native volume export contains invalid cell identifiers")
            seen[idx]=True
            g=chunk[[field[k] for k in gradients]].to_numpy().reshape(-1,3,3)
            q,vorticity,stress=turbulence_diagnostics(g,chunk[field["mu_t_Pa_s"]].to_numpy())
            native=chunk[field["omega_x_per_s"]].to_numpy()
            max_error=max(max_error,float(np.max(np.abs(vorticity[:,0]-native))))
            scale=max(scale,float(np.max(np.abs(g[:,2,1])+np.abs(g[:,1,2]))))
            values={"xyz_m":chunk[alignment["cell_center_coordinate_columns"]].to_numpy(),
                    "velocity_m_s":chunk[[field[k] for k in ("u_m_s","v_m_s","w_m_s")]].to_numpy(),
                    "vorticity_s_inv":vorticity,"rho_kg_m3":chunk[field["rho_kg_m3"]].to_numpy(),
                    "p_gauge_Pa":chunk[field["pressure_Pa"]].to_numpy(),"p0_gauge_Pa":chunk[field["total_pressure_Pa"]].to_numpy(),
                    "Cp0":chunk[field["total_pressure_Pa"]].to_numpy()/qref,"k_m2_s2":chunk[field["k_m2_s2"]].to_numpy(),
                    "mu_t_Pa_s":chunk[field["mu_t_Pa_s"]].to_numpy(),"reynolds_shear_xy_Pa":stress,"Q_s_inv2":q,
                    "q_second_invariant_s_inv2":q+.5*np.trace(g,axis1=1,axis2=2)**2}
            # Consecutive runs are efficiently writable HDF slabs even after partitioned MPI exports.
            runs=np.split(np.arange(len(idx)),np.flatnonzero(np.diff(idx)!=1)+1)
            for key,array in values.items():
                arr=array[order]
                for part in runs:
                    ds[key][idx[part[0]]:idx[part[-1]]+1]=arr[part[0]:part[-1]+1]
        if not np.all(seen) or max_error>max(1.e-5,2.e-5*scale):
            raise ValueError(f"Native vorticity/curl mismatch or missing values: {max_error} s^-1")
        h.attrs["curl_x_vs_fluent_max_abs_error_s_inv"]=max_error
    os.replace(staging,target)
    return target


def intersect(case_name,axis,coordinate,label):
    if Path(label).name!=label:
        raise ValueError("Use a case-local slice name")
    _,cas,_=accepted(case_name)
    folder=ROOT/"04_postproc"/case_name
    result=cut_mesh(cas,axis,coordinate)
    cells=result["cell_ids"]-1
    ids,unmap=np.unique(cells,return_inverse=True)
    with h5py.File(folder/"native_volume_fields.h5") as f:
        if Path(f.attrs["mesh"])!=cas:
            raise ValueError("Cut mesh differs from the stored fields")
        # Access in contiguous slabs instead of submitting long HDF point selections.
        def take(name):
            group=f[name]
            out=np.empty((len(ids),)+group.shape[1:],dtype=group.dtype)
            first=np.r_[0,np.flatnonzero(np.diff(ids//65536))+1,len(ids)]
            for a,b in zip(first[:-1],first[1:]):
                lo,hi=ids[a],ids[b-1]+1
                out[a:b]=group[lo:hi][ids[a:b]-lo]
            return out[unmap]
        for key in ("p_gauge_Pa","Cp0","k_m2_s2","rho_kg_m3","reynolds_shear_xy_Pa","Q_s_inv2","vorticity_s_inv"):
            result[key]=take(key)
        result["axial_vorticity_s_inv"]=result["vorticity_s_inv"][:,0]
        velocity=take("velocity_m_s")
        for i,key in enumerate(("u_m_s","v_m_s","w_m_s")):
            result[key]=velocity[:,i]
    target=folder/(label+"_slice.npz")
    np.savez_compressed(target,**result)
    return target


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case")
    parser.add_argument("--slice",nargs=3,metavar=("AXIS","COORDINATE_M","LABEL"))
    args=parser.parse_args()
    print(intersect(args.case,"xyz".index(args.slice[0]),float(args.slice[1]),args.slice[2]) if args.slice else write_volume(args.case))

