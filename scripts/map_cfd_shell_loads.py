"""Conservative half-aircraft face and motor-reaction transfer to SHELL181 nodes.
Forces are in N, moments about the restored CAD origin are in N m.
"""
import argparse,json
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from prepare_mapdl_shell import ROOT,OUT,WALLS
from extract_fluent_fields import extract_walls
from fsi_provenance import load_identity,hashes,commit

def resultant(xyz,force,couple=None):
    moment=np.cross(xyz,force).sum(0)
    if couple is not None:moment+=couple.sum(0)
    return np.r_[force.sum(0),moment]

def nearest_triangle(x,n,v,faces):
    tri=v[faces]
    normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
    normal/=np.linalg.norm(normal,axis=1)[:,None]
    tree=cKDTree(tri.mean(1));result=[];weights=[];miss=[];align=[]
    for lo in range(0,len(x),2048):
        q=x[lo:lo+2048,None,:];src_normal=n[lo:lo+len(q),None,:]
        _,ids=tree.query(q[:,0,:],k=min(18,len(tri)),workers=2)
        ids=np.asarray(ids).reshape(len(q),-1)
        T=tri[ids];e=T[:,:,1]-T[:,:,0];f=T[:,:,2]-T[:,:,0];g=q-T[:,:,0]
        dot=lambda a,b:np.einsum('...i,...i->...',a,b)
        ee=dot(e,e);ef=dot(e,f);ff=dot(f,f);eg=dot(e,g);fg=dot(f,g)
        det=ee*ff-ef**2
        b=(ff*eg-ef*fg)/det;c=(ee*fg-ef*eg)/det
        bary=np.stack((1-b-c,b,c),axis=-1)
        p=np.einsum('nkj,nkji->nki',bary,T)
        dist=dot(q-p,q-p);dist[bary.min(2)<0]=np.inf
        for i,j in [(0,1),(1,2),(2,0)]:
            d=T[:,:,j]-T[:,:,i];a=np.clip(dot(q-T[:,:,i],d)/dot(d,d),0,1)
            gap=q-(T[:,:,i]+a[:,:,None]*d);d2=dot(gap,gap);m=d2<dist
            dist[m]=d2[m];bary[m]=0
            bary[:,:,i][m]=1-a[m];bary[:,:,j][m]=a[m]
        orient=dot(normal[ids],src_normal)
        # Prefer the same side of the shell; nearest distance breaks ties.
        score=dist.copy();score[orient<0.05]+=1.
        k=np.argmin(score,axis=1);ix=np.arange(len(q))
        result.append(faces[ids[ix,k]]);weights.append(bary[ix,k]);miss.append(np.sqrt(dist[ix,k]));align.append(orient[ix,k])
    return np.vstack(result),np.vstack(weights),np.concatenate(miss),np.concatenate(align)

def scatter(x,F,v,nodes,w,loads):
    if not np.allclose(w.sum(1),1,rtol=0,atol=5e-10):raise ValueError('Invalid partition of unity')
    projected=(v[nodes]*w[:,:,None]).sum(1)
    extra=np.cross(x-projected,F)
    for j in range(w.shape[1]):
        np.add.at(loads[:,:3],nodes[:,j],F*w[:,j,None])
        np.add.at(loads[:,3:],nodes[:,j],extra*w[:,j,None])

def motor_reaction(v,idx,point,force,torque):
    x=v[idx];w=np.full(len(x),1/len(x));center=np.sum(x*w[:,None],axis=0)
    r=x-center;I=np.eye(3)*np.sum(w*np.sum(r*r,axis=1))-(r*w[:,None]).T@r
    if np.linalg.cond(I)>1e6:raise ValueError('Insufficient mount-patch support for torque')
    spin=np.linalg.solve(I,torque+np.cross(point-center,force))
    return w[:,None]*(force+np.cross(spin,r))

def evaluate(mesh,w,disk_specs,disks):
    v=mesh['xyz'];faces=mesh['faces'];tags=mesh['face_zone'];nodal=np.zeros((len(v),6));desired=np.zeros(6);checks=[]
    mapped_faces=0
    for tag,group in enumerate(WALLS):
        mask=np.char.startswith(w['component'].astype(str),group)
        if not mask.any():raise ValueError('CFD wall zone missing: '+group)
        X=w['xyz'][mask];A=w['inward_fluid_area_vector_m2'][mask]
        n=A/np.linalg.norm(A,axis=1)[:,None]
        pressure=-np.asarray(w['p_gauge_Pa'][mask]).reshape(-1,1)*A
        viscous=-w['wall_shear_storage'][mask]
        face,wgt,dev,agree=nearest_triangle(X,n,v,faces[tags==tag])
        force=pressure+viscous
        scatter(X,force,v,face,wgt,nodal);desired+=resultant(X,force);mapped_faces+=len(X)
        checks.append(dict(zone=group,faces=len(X),pressure_wrench=resultant(X,pressure).tolist(),
                shear_wrench=resultant(X,viscous).tolist(),projection_distance_m_p50_p95_max=np.quantile(dev,[.5,.95,1]).tolist(),
                source_faces_without_matching_normal=int(sum(agree<.05))))
    if mapped_faces!=len(w['xyz']):raise ValueError('Unmapped or multiply mapped Fluent wall face')
    airframe=desired.copy();mount_nodes=np.unique(faces[tags==2])
    for p in disk_specs:
        d=next(el for el in disks if el['name']==p['name'])
        axis=np.asarray(d['thrust_axis'],float);assert abs(np.linalg.norm(axis)-1)<1e-8
        origin=np.array([p['x_disk_m'],p['y_axis_m'],p['z_axis_m']])
        applied_force=np.asarray(d['discrete_force_vector_N'],dtype=float)
        center_moment=np.asarray(d['discrete_moment_about_center_Nm'],dtype=float)
        if applied_force.shape!=(3,) or center_moment.shape!=(3,) or not np.all(np.isfinite([applied_force,center_moment])):
            raise ValueError('Incomplete discrete 3D motor reaction at '+p['name'])
        if not (np.isclose(applied_force@axis,d['discrete_thrust_N'],atol=1e-7,rtol=1e-6)
                and np.isclose(center_moment@axis,d['discrete_torque_Nm'],atol=1e-7,rtol=1e-6)):
            raise ValueError('Inconsistent axial projection of the Fluent body-force density integrals at '+p['name'])
        force=-applied_force;torque=-center_moment
        # Finite ring of structural shell nodes around the idealized motor attachment.
        wt=p['name']=='WT-1';mount=origin+[.32 if wt else .20,0,0]
        rel=v[mount_nodes]-mount
        use=(abs(rel[:,0])<(.07 if wt else .055))&(np.linalg.norm(rel[:,1:],axis=1)<(.22 if wt else .12))
        idx=mount_nodes[use]
        if len(idx)<5:raise ValueError('Too few structural mount nodes: '+p['name'])
        local=motor_reaction(v,idx,origin,force,torque);nodal[idx,:3]+=local
        target=np.r_[force,torque+np.cross(origin,force)]
        if not np.allclose(resultant(v[idx],local),target,atol=1e-8):raise ValueError('Mount transfer failed')
        desired+=target;checks.append(dict(motor=p['name'],nodes=len(idx),reaction_wrench_about_origin=target.tolist()))
    actual=resultant(v,nodal[:,:3],nodal[:,3:])
    if not np.allclose(actual,desired,atol=2e-7,rtol=1e-10):raise ValueError('Global force/moment conservation failed')
    return nodal,{'global_input_wrench':desired.tolist(),'airframe_only_wrench':airframe.tolist(),
                  'mapped_wrench':actual.tolist(),'componentwise_transfer_residual':(actual-desired).tolist(),'loads':checks}

def produce(grid,case_path):
    case_path=case_path.resolve();folder=case_path.parent
    if folder.parent!=ROOT/'03_cases' or folder.name not in [x+'_rpm100' for x in ('coarse','medium','fine')]+['medium_rpm100_takeoff_v10','medium_opt_hlp_vector10'] or not case_path.name.endswith('.cas.h5'):raise ValueError('Expected an accepted baseline, takeoff-roll, or vectored-thrust case')
    from compare_x57_cases import accepted
    qa,accepted_case,data=accepted(folder.name)
    if not qa['passed'] or accepted_case.resolve()!=case_path:
        raise ValueError('Only the accepted Fluent case/data pair can supply structural loads')
    identity=load_identity(grid,folder.name)
    w=extract_walls(case_path,data)
    mesh=np.load(OUT/'models'/grid/'shell_mesh.npz')
    specs=json.loads((ROOT/'01_geometry/geometry_audit.json').read_text(encoding='utf-8-sig'))['starboard_propellers_detected']
    disks=json.loads((folder/'fluent_discrete_disk_integrals.json').read_text())
    loads,report=evaluate(mesh,w,specs,disks)
    reported=qa['half_model_endpoint_force_N']['airframe']
    for i,ax in enumerate('XY'):
        expected=reported['Force'+ax]
        if not np.isclose(report['airframe_only_wrench'][i],expected,atol=.02,rtol=.002):
            raise ValueError(('Native aerodynamic force and extracted force disagree',ax,expected,report['airframe_only_wrench'][i]))
    wrench=report['airframe_only_wrench']
    origin=np.asarray(qa['pitch_origin_m'],dtype=float)
    mapped_pitch=wrench[5]-np.cross(origin,wrench[:3])[2]
    if not np.isclose(mapped_pitch,float(qa['half_model_endpoint_pitch_Nm']),atol=.02,rtol=.002):
        raise ValueError(('Native aerodynamic pitch moment and mapped moment disagree',mapped_pitch,qa['half_model_endpoint_pitch_Nm']))
    work=OUT/(grid+'_struct__'+folder.name);work.mkdir(parents=True,exist_ok=True)
    np.save(work/'nodal_loads.npy',loads)
    with (work/'mapped_loads.inp').open('w',encoding='ascii') as h:
        for i,row in enumerate(loads,1):
            for key,val in zip(('FX','FY','FZ','MX','MY','MZ'),row):
                if val!=0.:h.write(f'F,{i},{key},{val:.15e}\n')
    if load_identity(grid,folder.name)!=identity:raise ValueError('The accepted endpoint or shell model changed during mapping')
    report['load_identity']=identity
    report['sha256']=identity['source_sha256']
    report['mapped_files_sha256']=hashes([work/'mapped_loads.inp',work/'nodal_loads.npy'])
    report.update({'case':folder.name,'grid':grid,'pressure_and_shear':'Half-aircraft native gauge face pressure and integrated wall shear, airframe sign convention; force projection conserves resultant and arm using nodal shell couples.','mounts':'Opposite of signed Fluent disk thrust and signed torque; equivalent force system on assumed finite nacelle mount rings.'})
    commit(work/'load_transfer.json',report)
    return work
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('grid',choices=['coarse','medium','fine']);a.add_argument('accepted_case',type=Path);args=a.parse_args();print(produce(args.grid,args.accepted_case))
