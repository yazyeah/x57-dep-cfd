"""Elementwise stress envelopes from both SHELL181 faces. Values are stored in SI."""
import json
import numpy as np
def element_centers(values, elements):
    """Return a mean over the three or four distinct SHELL181 nodes."""
    triangle = elements[:, 2] == elements[:, 3]
    total = values[elements].sum(axis=1)
    total[triangle] -= values[elements[triangle, 3]]
    return total / (4 - triangle.astype(int))[:, None]


def source_hash(path):
    import hashlib
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def apdl_commands():
    commands=[]
    for face in ['TOP','BOT']:
        fields=[('P1','1'),('P2','2'),('P3','3'),('SXY','XY')]
        commands.extend(['SHELL,'+face,'RSYS,SOLU'])
        for label,component in fields:
            name=face[0]+label
            commands.extend([f'ETABLE,{name},S,{component}',f'*DIM,A{name},ARRAY,NE',f'*VGET,A{name}(1),ELEM,1,ETAB,{name}'])
        args=','.join('A'+face[0]+label+'(1)' for label,_ in fields)
        commands.extend([f'*CFOPEN,element_{face.lower()}_principal_local,csv','*VWRITE,EIDS(1),'+args,"(F10.0,4(',',E21.13))",'*CFCLOS'])
    return commands+['RSYS,0']
def process(work,mesh,S,U):
    n=len(S);faces=mesh['elements'];c=element_centers(mesh['xyz'],faces)
    P=[]
    for side in ['top','bot']:
        data=np.loadtxt(work/('element_'+side+'_principal_local.csv'),delimiter=',',ndmin=2)
        if data.shape!=(n,5) or not np.isfinite(data).all() or not np.array_equal(data[:,0].astype(int),1+np.arange(n)):
            raise ValueError('Incomplete SHELL181 stress output on '+side)
        P.append(data[:,1:])
    principal=np.stack(P,axis=1)
    if (np.diff(principal[:,:,:3],axis=2)>np.maximum(abs(principal[:,:,:2]),1)*1.e-6).any():raise ValueError('Principal ordering invalid')
    maxshear=(principal[:,:,0]-principal[:,:,2])/2
    vm=S.max(1);fos=np.divide(503e6,vm,out=np.full(len(vm),np.inf),where=vm>0)
    displacement=np.linalg.norm(U,axis=1)
    np.savez_compressed(work/'shell_fields.npz',element_id=np.arange(1,n+1),node_id=np.arange(1,len(U)+1),centroid_m=c,area_m2=mesh['area_m2'],
        section=mesh['element_section'],pylon=mesh['pylon'],wingbox=mesh['wingbox'],displacement_vector_m=U,displacement_magnitude_m=displacement,
        top_bottom_vm_Pa=S,top_bottom_S1_Pa=principal[:,:,0],top_bottom_S2_Pa=principal[:,:,1],top_bottom_S3_Pa=principal[:,:,2],
        top_bottom_tresca_max_shear_Pa=maxshear,top_bottom_local_shell_sxy_Pa=principal[:,:,3],safety_factor= fos)
    records={}
    masks=[(name,mesh['element_section']==k) for k,name in enumerate(['wall_wing','wall_fuselage','wall_nacelles','wall_sponson','wall_empennage'])]
    for name,mask in masks+[('WINGBOX',mesh['wingbox']),('PYLON',mesh['pylon'])]:
        if not np.any(mask):raise ValueError('Missing structure region '+name)
        records[name]=dict(elems=int(mask.sum()),peak_vm_Pa=float(vm[mask].max()),max_S1_Pa=float(principal[mask,:,0].max()),min_S3_Pa=float(principal[mask,:,2].min()),
             peak_tresca_max_shear_Pa=float(maxshear[mask].max()),peak_abs_local_sxy_Pa=float(abs(principal[mask,:,3]).max()),
             max_displacement_m=float(displacement[np.unique(faces[mask])].max()),min_von_mises_yield_factor=float(fos[mask].min()) if np.isfinite(fos[mask].min()) else None)
    (work/'component_stress_metrics.json').write_text(json.dumps(records,indent=2,allow_nan=False))
    return records

