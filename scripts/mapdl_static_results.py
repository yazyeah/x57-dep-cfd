"""Write the static MAPDL solve and read back equilibrium and structural statistics."""
import argparse,json,shutil
from pathlib import Path
import numpy as np
from prepare_mapdl_shell import OUT
from mapdl_shell_fields import apdl_commands,process

def equilibrium(xyz,reactions,input_wrench,force_scale,moment_scale):
    rf=reactions[:,:3].sum(0)
    rm=np.cross(xyz,reactions[:,:3]).sum(0)+reactions[:,3:].sum(0)
    residual=np.r_[rf,rm]+input_wrench
    frac=[np.linalg.norm(residual[:3])/max(force_scale,1e-12),np.linalg.norm(residual[3:])/max(moment_scale,1e-12)]
    return {'reactions_wrench':np.r_[rf,rm].tolist(),'residual_wrench':residual.tolist(),
            'normalization_force_N':force_scale,'normalization_moment_Nm':moment_scale,
            'relative_force_moment_errors':frac,'passed':bool(max(frac)<1e-3)}
def write(grid,work):
    model=OUT/'models'/grid;mesh=np.load(model/'shell_mesh.npz')
    shutil.copyfile(model/'model.inp',work/'model.inp')
    reaction_ids=np.union1d(mesh['sym'],np.union1d(mesh['main'],mesh['nose']))
    sym=set(mesh['sym']);gear=set(np.r_[mesh['main'],mesh['nose']])
    cmds=['/CLEAR,NOSTART','/INPUT,model,inp','/SOLU','ANTYPE,STATIC','NLGEOM,OFF','EQSLV,SPARSE',
          '/INPUT,mapped_loads,inp','OUTRES,ALL,LAST','SAVE','SOLVE','FINISH','/POST1','SET,LAST',
          'RSYS,0','ALLSEL,ALL','*GET,NN,NODE,0,NUM,MAX','*GET,NE,ELEM,0,NUM,MAX',
          '*DIM,UXV,ARRAY,NN','*DIM,UYV,ARRAY,NN','*DIM,UZV,ARRAY,NN','*DIM,NIDS,ARRAY,NN',
          '*VFILL,NIDS(1),RAMP,1,1','*VGET,UXV(1),NODE,1,U,X','*VGET,UYV(1),NODE,1,U,Y',
          '*VGET,UZV(1),NODE,1,U,Z','*CFOPEN,node_displacement,csv','*VWRITE,NIDS(1),UXV(1),UYV(1),UZV(1)',
          "(F10.0,3(',',E21.13))",'*CFCLOS','*DIM,ST,ARRAY,NE','*DIM,SB,ARRAY,NE','*DIM,EIDS,ARRAY,NE',
          '*VFILL,EIDS(1),RAMP,1,1','SHELL,TOP','ETABLE,TOPVM,S,EQV','*VGET,ST(1),ELEM,1,ETAB,TOPVM',
          'SHELL,BOT','ETABLE,BOTVM,S,EQV','*VGET,SB(1),ELEM,1,ETAB,BOTVM',
          '*CFOPEN,element_stress,csv','*VWRITE,EIDS(1),ST(1),SB(1)',"(F10.0,2(',',E21.13))",'*CFCLOS',
          '*CFOPEN,support_reactions,csv']
    cmds=cmds[:-1]+apdl_commands()+[cmds[-1]]
    for j in reaction_ids:
        dofs={2,3,4} if j in sym else set()
        if j in gear:dofs.update([0,1])
        # Only constrain/measure the intended components; all absent reactions
        # are exactly zero. Rotational reactions are in N m for shell DOFs.
        for k,axis in enumerate(['FX','FY','FZ','MX','MY','MZ']):
            cmds.append(f'*GET,RV{k},NODE,{j+1},RF,{axis}' if k in dofs else f'RV{k}=0')
        cmds.extend([f'*VWRITE,{j+1},RV0,RV1,RV2,RV3,RV4,RV5',"(F10.0,6(',',E17.9))"])
    cmds+=['*CFCLOS','FINISH',"/COM,X57_MAPDL_EXPORT_COMPLETE",'/EXIT,NOSAV']
    (work/'solve.inp').write_text('\n'.join(cmds)+'\n',encoding='ascii')

def check(grid,work):
    mesh=np.load(OUT/'models'/grid/'shell_mesh.npz');v=mesh['xyz'];n=len(v);ne=len(mesh['elements'])
    def table(name,count):
        t=np.loadtxt(work/(name+'.csv'),delimiter=',',ndmin=2)
        if not np.isfinite(t).all() or len(t)!=count:raise ValueError(('Invalid MAPDL export',name,count))
        ix=t[:,0].astype(int)-1
        if len(set(ix))!=len(ix):raise ValueError('Duplicate export IDs '+name)
        return ix,t[:,1:]
    ids,U=table('node_displacement',n);assert np.array_equal(ids,np.arange(n))
    ids,S=table('element_stress',ne);assert np.array_equal(ids,np.arange(ne))
    constrained=np.union1d(mesh['sym'],np.union1d(mesh['main'],mesh['nose']))
    ids,R=table('support_reactions',len(constrained));assert np.array_equal(ids,constrained)
    L=np.load(work/'nodal_loads.npy');inp=np.array(json.loads((work/'load_transfer.json').read_text())['global_input_wrench'])
    fscale=float(np.linalg.norm(L[:,:3],axis=1).sum())
    mscale=float(np.linalg.norm(np.cross(v,L[:,:3])+L[:,3:],axis=1).sum())
    eq=equilibrium(v[ids],R,inp,fscale,mscale)
    regions=process(work,mesh,S,U)
    vm=S.max(1);mass=mesh['area_m2'];sort=np.argsort(vm);ac=np.cumsum(mass[sort]);p99=vm[sort[np.searchsorted(ac,.99*ac[-1])]]
    a=int(np.argmax(vm));tip=U[mesh['tip']]
    report={'grid':grid,'equilibrium':eq,'component_envelopes':regions,'peak_element_average_top_or_bottom_von_mises_Pa':float(vm[a]),
            'peak_element_1based':a+1,'peak_element_centroid_m':v[np.unique(mesh['elements'][a])].mean(0).tolist(),
            'area_weighted_p99_von_mises_Pa':float(p99),'wingtip_patch_mean_displacement_m':tip.mean(0).tolist(),
            'wingtip_patch_mean_displacement_magnitude_m':float(np.linalg.norm(tip.mean(0))),
            'linear_elastic_nominal_yield_ratio':503e6/float(vm[a]) if vm[a]>0 else None,
            'interpretation':'Section gauges, wing box, rigid empennage lugs and gear attachment patches are assumed. Yield ratio is specific to modeled static loads; local support peaks and surface discretization depend on the idealization.'}
    (work/'structural_metrics.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    if not eq['passed']:raise ValueError('Reaction equilibrium check failed')
    return report
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('action',choices=['write','check']);a.add_argument('grid',choices=['coarse','medium','fine']);a.add_argument('workdir',type=Path)
    args=a.parse_args();work=args.workdir.resolve()
    if not work.is_relative_to(OUT.resolve()):raise ValueError('Expected an FSI work folder inside the project workspace')
    if args.action=='write':write(args.grid,work)
    else:print(json.dumps(check(args.grid,work),indent=2))
