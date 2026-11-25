"""Remove the artificial x=4.81831 m stabilizer Boolean seam along both exposed skins."""
import argparse,json
import numpy as np
from scipy.sparse import coo_matrix
from p2_geometry_io import *
from verify_p2_cad_shell import verify,quality
def run(src,out):
    ps={n:stl_triangles(src/(n+'.stl')) for n in TYPES};v0,f=indices(ps['wall_empennage']);v=v0.astype(float)
    cad=np.load(GEO/'cad_components.npz')['55'].astype(float);low=cad.min(1);high=cad.max(1)
    def rays(x,z):
        tri=cad[(low[:,0]<=x)&(high[:,0]>=x)&(low[:,2]<=z)&(high[:,2]>=z)];a,b,c=tri.transpose(1,0,2)
        e,g=b-a,c-a;d=e[:,0]*g[:,2]-e[:,2]*g[:,0];k=abs(d)>1e-15;a,e,g,d=a[k],e[k],g[k],d[k]
        dx=x-a[:,0];dz=z-a[:,2];p=(dx*g[:,2]-dz*g[:,0])/d;q=(dz*e[:,0]-dx*e[:,2])/d;k=(p>=-1e-8)&(q>=-1e-8)&(p+q<=1.0000001)
        return a[k,1]+e[k,1]*p[k]+g[k,1]*q[k]
    x,y,z=v.T;eligible=(abs(x-4.81831)<.036)&(z>.061)&(z<1.59);side=np.zeros(len(v),int);weight=np.zeros(len(v))
    for i in np.flatnonzero(eligible):
        yhit=rays(x[i],z[i])
        if len(yhit)<2 or np.ptp(yhit)<.016:continue
        side[i]=1 if y[i]>.5*(yhit.min()+yhit.max()) else -1
        xw=np.clip((.019-abs(x[i]-4.81831))/.007,0,1);zw=np.clip(min(z[i]-.077,1.572-z[i])/.028,0,1)
        weight[i]=xw*zw
    ed,n=np.unique(np.sort(f[:,[[0,1],[1,2],[2,0]]].reshape(-1,2),axis=1),axis=0,return_counts=True)
    weight[np.unique(ed[n==1])]=0;ed=ed[(side[ed[:,0]]==side[ed[:,1]])&(side[ed[:,0]]!=0)];a,b=np.r_[ed[:,0],ed[:,1]],np.r_[ed[:,1],ed[:,0]]
    G=coo_matrix((np.ones(len(a)),(a,b)),shape=(len(v),len(v))).tocsr();degree=np.maximum(np.asarray(G.sum(axis=1)).ravel(),1)
    active=weight>0
    for _ in range(12):
        smooth=(G@v)/degree[:,None];v[:,0]+=.40*weight*(smooth[:,0]-v[:,0]);v[:,2]+=.40*weight*(smooth[:,2]-v[:,2])
    for i in np.flatnonzero(active):
        h=rays(v[i,0],v[i,2])
        if len(h)<2:raise ValueError(('Projected vertex outside stabilizer',i))
        dest=h.max() if side[i]>0 else h.min();v[i,1]=v0[i,1]+weight[i]*(dest-v0[i,1])
    ps['wall_empennage']=v[f].astype('f4');save_patches(out,ps);verify(out,True)
    tri=ps['wall_empennage'].astype(float);c=tri.mean(1);n=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);n/=np.linalg.norm(n,axis=1)[:,None]
    q=quality(tri);center=np.array([4.818301,-.426453,.916837]);i=np.argmin(np.linalg.norm(c-center,axis=1))
    e=f[:,[[0,1],[1,2],[2,0]]].reshape(-1,2);u,inv,count=np.unique(np.sort(e,axis=1),axis=0,return_inverse=True,return_counts=True);o=np.argsort(inv);st=np.r_[0,np.cumsum(count)[:-1]];pos=v[u].mean(1);sel=(count==2)&(abs(pos[:,0]-4.81831)<.006)&(pos[:,2]>.15)&(pos[:,2]<1.52);i1,i2=o[st[sel]]//3,o[st[sel]+1]//3;ang=np.degrees(np.arccos(np.clip(np.sum(n[i1]*n[i2],axis=1),-1,1)))
    rec={'moved_nodes':int(active.sum()),'max_node_displacement_m':float(np.linalg.norm(v-v0,axis=1).max()),'nearest_face_normal':n[i].tolist(),'nearest_face_shape':float(q[i]),'whole_seam_max_normal_turn_deg':float(ang.max()),'whole_seam_95pct_deg':float(np.quantile(ang,.95)),'seam_turns_above_70deg':int((ang>70).sum()),'minimum_tail_shape':float(q.min())}
    (out/'tail_seam_qa.json').write_text(json.dumps(rec,indent=2));print(rec)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('dest',type=Path);a=p.parse_args();run(a.source,a.dest)

