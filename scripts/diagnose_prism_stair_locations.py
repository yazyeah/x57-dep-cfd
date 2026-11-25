"""Map every Fluent stair-step coordinate onto its input, corrected wall and source CAD."""
import argparse,json,re
from pathlib import Path
import numpy as np
from p2_geometry_io import GEO,WALLS,stl_triangles,indices,section_segments,heights

def boxes(tr):
    return tr.min(1),tr.max(1)

def closest(tr,point):
    a,b,c=tr.transpose(1,0,2)
    v=b-a;w=c-a;normal=np.cross(v,w)
    norm=np.einsum('ij,ij->i',normal,normal)
    projection=point-normal*(np.sum((point-a)*normal,axis=1)/np.maximum(norm,1.e-30))[:,None]
    inside=np.ones(len(tr),bool)
    edges=np.roll(tr,-1,axis=1)-tr
    for j in range(3):
        inside &= (np.sum(np.cross(edges[:,j],projection-tr[:,j])*normal,axis=1)>=-1e-19)
    t=np.clip(np.sum((point-tr)*edges,axis=2)/np.maximum(np.sum(edges**2,axis=2),1.e-30),0,1)
    feet=tr+t[:,:,None]*edges
    out=feet[np.arange(len(tr)),np.argmin(np.sum((feet-point)**2,axis=2),axis=1)]
    out[inside]=projection[inside]
    d=np.linalg.norm(out-point,axis=1)
    j=d.argmin()
    return int(j),float(d[j]),out[j]

def neighborhood(tr,point,radius=.032):
    mn,mx=boxes(tr)
    mask=np.all((mn<=point+radius)&(mx>=point-radius),axis=1)
    if not mask.any():return None
    table=tr[mask].astype(float);idx,d,foot=closest(table,point)
    v,f=indices(table)
    N=np.cross(table[:,1]-table[:,0],table[:,2]-table[:,0])
    N/=np.maximum(np.linalg.norm(N,axis=1)[:,None],1.e-22)
    e=f[:,[[0,1],[1,2],[2,0]]].reshape(-1,2)
    key,inv,count=np.unique(np.sort(e,axis=1),axis=0,return_inverse=True,return_counts=True)
    order=np.argsort(inv);s=np.r_[0,count.cumsum()[:-1]][count==2]
    ka=key[count==2]
    dihedral=np.degrees(np.arccos(np.clip(np.sum(N[order[s]//3]*N[order[s+1]//3],1),-1,1)))
    a,b=v[ka].transpose(1,0,2);ed=b-a
    t=np.clip(np.sum((foot-a)*ed,1)/np.maximum(np.sum(ed*ed,1),1.e-24),0,1)
    D=np.linalg.norm(a+t[:,None]*ed-foot,axis=1)
    extent=[(float(dihedral[D<r].max()) if (D<r).any() else None) for r in [.006,.015]]
    sides=np.roll(table,-1,axis=1)-table
    qual=2*np.sqrt(3)*np.linalg.norm(np.cross(sides[:,0],sides[:,1]),axis=1)/np.maximum(np.sum(sides**2,axis=(1,2)),1.e-23)
    return {'distance_mm':1000*d,'foot':foot.tolist(),'normal':N[idx].tolist(),'max_nearby_turn_deg_6_15mm':extent,'nearest_face_shape':float(qual[idx]),'face_index_0based':int(np.flatnonzero(mask)[idx])}

def ys(tr,x,z):
    hit=(tr[:,:,0].min(1)<=x)&(tr[:,:,0].max(1)>=x)&(tr[:,:,2].min(1)<=z)&(tr[:,:,2].max(1)>=z)
    return list(heights(section_segments(tr[hit].astype(float),z),x)) if hit.any() else []

def merged(intervals):
    out=[]
    for lo,hi in sorted(intervals):
        if out and lo<=out[-1][1]+1.e-6:out[-1][1]=max(hi,out[-1][1])
        else:out.append([lo,hi])
    return out

def main(log,comparison,out):
    txt=log.read_text(errors='replace')
    lines=re.search(r'stair stepping occurred at the following (\d+) locations(.*?)(?:removing cells for stair stepping)',txt,re.S)
    points=[(int(n),np.array([float(v) for v in s.split()])) for n,s in re.findall(r'(\d+) layers removed at \(([^)]*)\)',lines[2])]
    if len(points)!=int(lines[1]):raise ValueError('Incomplete native stair-step report')
    cfg=json.loads((log.parent/'mesh_config.json').read_text())
    src=Path(cfg['source_surface_dir'])
    rows=[dict(id=i+1,layers_removed=n,point_m=p.tolist(),cad=[],raw_intervals=[]) for i,(n,p) in enumerate(points)]
    for group,directory in [('input',src),('candidate',comparison)]:
        for label in WALLS:
            tr=stl_triangles(directory/(label+'.stl'))
            for (_,point),row in zip(points,rows):
                result=neighborhood(tr,point)
                if result and (group not in row or row[group]['distance_mm']>result['distance_mm']):
                    row[group]=dict(zone=label,**result)
                x,y,z=point
                profiles=ys(tr,x+1.7e-6,z+2.3e-6)
                if profiles:row.setdefault(group+'_ray_y',[]).extend(profiles)
    regions=json.loads((GEO/'cad_component_regions.json').read_text())
    with np.load(GEO/'cad_components.npz') as cad:
        for k,zone in regions.items():
            tr=cad[k]
            for (_,point),row in zip(points,rows):
                result=neighborhood(tr,point)
                if result and result['distance_mm']<32:row['cad'].append(dict(component=int(k),zone=zone,**result))
                x,y,z=point
                prof=ys(tr,x+1.7e-6,z+2.3e-6)
                if prof:
                    if len(prof)%2:
                        row.setdefault('ambiguous_cad_components',{})[k]=prof
                    else:
                        row['raw_intervals']+=list(zip(prof[::2],prof[1::2]))
    for row in rows:
        row['cad'].sort(key=lambda t:t['distance_mm'])
        row['cad_union_y']=merged(row.pop('raw_intervals'))
        for t in ['input','candidate']:
            row[t+'_ray_y']=sorted(set(row.get(t+'_ray_y',[])))
    result=dict(source=str(log),input=str(src),candidate=str(comparison),rows=rows)
    out.write_text(json.dumps(result,indent=2),encoding='utf8')
    for r in rows:
        cad=r['cad'][0];cand=r['candidate']
        print(r['id'],r['layers_removed'],r['point_m'],r['input']['zone'],cand['zone'],round(cand['distance_mm'],2),cad['component'],round(cad['distance_mm'],2),[None if v is None else round(v) for v in r['input']['max_nearby_turn_deg_6_15mm']],[None if v is None else round(v) for v in cand['max_nearby_turn_deg_6_15mm']],r['cad_union_y'],r['candidate_ray_y'])
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('transcript',type=Path);p.add_argument('candidate',type=Path);p.add_argument('output',type=Path);a=p.parse_args();main(a.transcript,a.candidate,a.output)

