"""Assemble an independent structural source table for the P12 fluid/solid join."""
import csv,json
from pathlib import Path
import numpy as np
from prepare_mapdl_shell import ROOT,OUT,SECTIONS
from fsi_provenance import accepted_result

CASES=('fine_rpm100','medium_rpm100_takeoff_v10','medium_opt_hlp_vector10')
HEAD=['source_domain','case','structural_grid','element_id','component','wingbox','pylon','x_m','y_m','z_m','area_m2',
      'sigma_vm_top_Pa','sigma_vm_bottom_Pa','S1_top_Pa','S1_bottom_Pa','S3_top_Pa','S3_bottom_Pa',
      'tresca_max_shear_top_Pa','tresca_max_shear_bottom_Pa','Sxy_local_top_Pa','Sxy_local_bottom_Pa','Umean_x_m','Umean_y_m','Umean_z_m','FoS']
def build():
    mesh=np.load(OUT/'models/fine/shell_mesh.npz');ele=mesh['elements']
    out=ROOT/'04_postproc/fsi_structural';out.mkdir(parents=True,exist_ok=True)
    target=out/'stress_and_bl_structural.csv';tmp=target.with_suffix('.csv.tmp');evidence={}
    try:
        with tmp.open('w',newline='',encoding='utf8') as fp:
            writer=csv.writer(fp);writer.writerow(HEAD)
            for case in CASES:
                folder=OUT/('fine_struct__'+case);report,native=accepted_result('fine',case)
                transfer=json.loads((folder/'load_transfer.json').read_text())
                if not report['equilibrium']['passed'] or transfer['case']!=case or transfer['grid']!='fine':raise ValueError(('Unaccepted FSI result',case))
                with np.load(folder/'shell_fields.npz') as d:
                    u=d['displacement_vector_m'];counts=4-(ele[:,2]==ele[:,3]).astype(int);U=u[ele].sum(1);U[counts==3]-=u[ele[counts==3,3]];U/=counts[:,None]
                    arrays=[d[x] for x in ['top_bottom_vm_Pa','top_bottom_S1_Pa','top_bottom_S3_Pa','top_bottom_tresca_max_shear_Pa','top_bottom_local_shell_sxy_Pa']]
                    for j in range(len(ele)):
                        values=[v for a in arrays for v in a[j]]
                        writer.writerow(['MAPDL SHELL181',case,'fine',j+1,SECTIONS[int(d['section'][j])],int(d['wingbox'][j]),int(d['pylon'][j]),
                            *d['centroid_m'][j],d['area_m2'][j],*values,*U[j],d['safety_factor'][j]])
                evidence[case]={'folder':str(folder),'elements':len(ele),'load_signature':native['load_signature'],'model_signature':native['model_signature'],'geometry_signature':native['geometry_signature'],'load_sources_sha256':transfer['sha256']}
        tmp.replace(target)
    except BaseException:
        if tmp.exists():tmp.unlink()
        raise
    (out/'stress_and_bl_structural_provenance.json').write_text(json.dumps(evidence,indent=2))
    return target
if __name__=='__main__':print(build())

