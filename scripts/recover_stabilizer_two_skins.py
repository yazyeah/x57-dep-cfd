"""Recover the two distinct stabilizer skins at artificial interior pockets in its earlier wrap."""
import argparse,json
import numpy as np,triangle
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from p2_geometry_io import *
from verify_p2_cad_shell import verify,quality
def main(src,out):
    ps={k:stl_triangles(src/(k+'.stl')) for k in TYPES};cad=np.load(GEO/'cad_components.npz')['55'].astype(float)
    v,f=indices(ps['wall_empennage']);ctr=v[f].mean(1)
    select=(((ctr[:,0]-4.8142)/.021)**2+((ctr[:,2]-.535)/.149)**2<1)&(ctr[:,1]<-.41)
    edges,cnt=np.unique(np.sort(f[select][:,[[0,1],[1,2],[2,0]]].reshape(-1,2),axis=1),axis=0,return_counts=True)
    rim=edges[cnt==1];ids,inv=np.unique(rim,return_inverse=True);segments=inv.reshape(-1,2)
    u,g=connected_components(coo_matrix((np.ones(len(segments)),segments.T),shape=(len(ids),len(ids))),directed=False)
    if u!=2:raise ValueError(('Expected only upper and lower skin loops, got',u))
    new=[];stats=[]
    for zone in range(2):
        subset=np.where(g==zone)[0];ii=ids[subset];xyz=v[ii];mapid=np.full(len(ids),-1,int);mapid[subset]=np.arange(len(subset));ss=mapid[segments[g[segments[:,0]]==zone]]
        if not np.all(np.bincount(ss.ravel(),minlength=len(ii))==2):raise ValueError('Non-simple patch')
        pts=xyz[:,[0,2]].astype(float);pl=triangle.triangulate({'vertices':pts,'segments':ss},'pYQ')
        if len(pl['vertices'])!=len(ii):raise ValueError('Border intersects')
        top=xyz[:,1].mean()>-.447;values=[];caches={}
        def Y(x,z):
            if z not in caches:caches[z]=section_segments(cad,z)
            ss0=caches[z];xq=np.clip(x,ss0[:,:,0].min()+2e-6,ss0[:,:,0].max()-2e-6);ys=heights(ss0,xq)
            if len(ys)<2:raise ValueError(('Missing material in candidate',x,z))
            return ys.max() if top else ys.min()
        dev=np.array([yy-Y(x,z) for x,yy,z in xyz]);a,b=pts[ss].transpose(1,0,2);ed=b-a;dd=np.sum(ed**2,1)
        tris=pts[pl['triangles']];A,B,C=tris.transpose(1,0,2);e=B-A;h=C-A;det=e[:,0]*h[:,1]-e[:,1]*h[:,0]
        lo=pts.min(0);hi=pts.max(0);step=.0085
        for k,z in enumerate(np.arange(lo[1]+step/2,hi[1],step*.866)):
            for x in np.arange(lo[0]+(1+k%2)*step/2,hi[0],step):
                p=np.array([x,z]);r=p-A;i=(r[:,0]*h[:,1]-r[:,1]*h[:,0])/det;j=(r[:,1]*e[:,0]-r[:,0]*e[:,1])/det
                if not np.any((i>0)&(j>0)&(i+j<1)):continue
                frac=np.clip(np.sum((p-a)*ed,1)/np.maximum(dd,1e-20),0,1);d=np.linalg.norm(p-a-frac[:,None]*ed,axis=1);m=d.argmin()
                if d[m]<.0034:continue
                offset=(1-frac[m])*dev[ss[m,0]]+frac[m]*dev[ss[m,1]];weight=max(0.,1.-d[m]/.012)**2;values.append([x,Y(x,z)+weight*offset,z])
        block=np.vstack([xyz,np.array(values)]);res=triangle.triangulate({'vertices':block[:,[0,2]],'segments':ss},'pYQ');ff=res['triangles']
        if len(res['vertices'])!=len(block):raise ValueError('Planar mesher introduced an intersection')
        if not top:ff=ff[:,::-1]
        new.append(block[ff].astype('f4'));stats.append(dict(upper=bool(top),added=len(ff),min_shape=float(quality(block[ff]).min())))
    ps['wall_empennage']=np.concatenate([v[f[~select]],*new]);save_patches(out,ps);verify(out,True)
    results=[]
    for z in np.linspace(.42,.65,24):
        cs=section_segments(cad,z);ts=section_segments(ps['wall_empennage'].astype(float),z)
        for x in np.linspace(4.809,4.824,11):
            yc=heights(cs,x);yt=heights(ts,x);results.append({'x_m':x,'z_m':z,'mesh_ray_count':len(yt),'delta_thickness_m':float(np.ptp(yt)-np.ptp(yc))})
    bad=sum(q['mesh_ray_count']!=2 for q in results);maxerr=max(abs(q['delta_thickness_m']) for q in results)
    if bad or maxerr>.003:raise ValueError(('Stabilizer did not recover its profile',bad,maxerr))
    (out/'stabilizer_dent_qa.json').write_text(json.dumps({'patches':stats,'rays':results,'maximum_error_m':maxerr},indent=2));print(stats,maxerr)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('src',type=Path);p.add_argument('dest',type=Path);a=p.parse_args();main(a.src,a.dest)

