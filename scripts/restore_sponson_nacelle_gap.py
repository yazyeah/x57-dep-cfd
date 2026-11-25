"""Restore the local nacelle–sponson gap by subdividing the input skin and fitting both CAD cross sections."""
from pathlib import Path
import argparse,json,shutil,time
import numpy as np
def stl_triangles(path):
    return np.fromfile(path,dtype=dtype,offset=84)['v'].copy()
ROOT=Path(__file__).resolve().parents[1]
GEO=ROOT/"01_geometry"
dtype=np.dtype([("n","<f4",3),("v","<f4",(3,3)),("attr","<u2")])

def write_stl(path,tri):
    data=np.zeros(len(tri),dtype=dtype);data["v"]=tri
    n=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);data["n"]=n/np.linalg.norm(n,axis=1)[:,None]
    with path.open("wb") as f:
        f.write(b"X57 CAD gap fitted surface".ljust(80,b" "));f.write(len(data).to_bytes(4,"little"));data.tofile(f)

def smooth(x,low,high):
    t=np.clip((x-low)/(high-low),0,1);return t*t*(3-2*t)

def weight(p,kind):
    x,y,z=p.T
    w=smooth(x,-.175,-.125)*(1-smooth(x,.115,.165))
    if kind=="sponson":
        return w*smooth(z,.745,.785)*(1-smooth(y,-.75,-.71))
    return w*smooth(z,.788,.805)*(1-smooth(z,.968,.985))*(1-smooth(y,.045,.065))*smooth(y,-.16,-.12)

def refine(v,f,kind,target):
    for step in range(6):
        edges=np.stack((f,np.roll(f,-1,1)),axis=2).reshape(-1,2)
        und,rev=np.unique(np.sort(edges,axis=1),axis=0,return_inverse=True)
        a,b=v[und[:,0]],v[und[:,1]]
        active=(weight((a+b)/2,kind)>1.e-4)&(np.linalg.norm(a-b,axis=1)>target)
        if not active.any():break
        ids=np.full(len(und),-1,int);ids[active]=len(v)+np.arange(active.sum())
        mid=ids[rev].reshape(-1,3);v=np.concatenate((v,(a[active]+b[active])/2))
        bits=(mid>=0)@np.array([1,2,4]);out=[f[bits==0]]
        for shift in range(3):
            for mask,two in [(1<<shift,False),((1<<shift)|(1<<((shift+1)%3)),True)]:
                keep=bits==mask
                A,B,C=np.roll(f[keep],-shift,axis=1).T
                I,J,_=np.roll(mid[keep],-shift,axis=1).T
                if two:
                    out.extend([np.c_[I,B,J],np.c_[A,I,C],np.c_[I,J,C]])
                else:
                    out.extend([np.c_[A,I,C],np.c_[I,B,C]])
        mask=bits==7;A,B,C=f[mask].T;I,J,K=mid[mask].T
        out.extend([np.c_[A,I,K],np.c_[I,B,J],np.c_[K,J,C],np.c_[I,J,K]])
        f=np.concatenate(out)
    return v,f

class Sections:
    def __init__(self,tri):
        self.tri=tri.astype(float);low=tri[:,:,0].min(1);high=tri[:,:,0].max(1)
        self.binwidth=.006
        self.lookup={b:self.tri[(low<(b+1)*self.binwidth)&(high>=b*self.binwidth)]
                     for b in range(-34,32)}
    def radial(self,p):
        x=p[0];tris=self.lookup[int(np.floor(x/self.binwidth))]
        # A deterministic microscopic nudge resolves coincident CAD section vertices.
        x+=2.e-10
        before=tris[:,:,0]<=x;nxt=np.roll(tris,-1,axis=1);mask=before!=np.roll(before,-1,axis=1)
        a=tris[mask];b=nxt[mask]
        if len(a)<4:return p
        seg=(a[:,1:]+(b[:,1:]-a[:,1:])*((x-a[:,0])/(b[:,0]-a[:,0]))[:,None]).reshape(-1,2,2)
        allp=seg.reshape(-1,2);center=(allp.min(axis=0)+allp.max(axis=0))/2
        direction=p[1:]-center; a,b=seg[:,0]-center,seg[:,1]-center;side=b-a
        cross=lambda v,w:v[...,0]*w[...,1]-v[...,1]*w[...,0]
        det=cross(direction,side)
        with np.errstate(invalid="ignore",divide="ignore"):
            t=cross(a,side)/det;v=cross(a,direction)/det
        valid=(np.abs(det)>1e-18)&(t>0)&(v>=-1e-9)&(v<=1+1e-9)
        if not valid.any():return p
        # Use the nearest external branch to the sleeve's actual local skin.
        ts=t[valid];chosen=ts[np.argmin(np.abs(ts-1))]
        return np.r_[p[0],center+chosen*direction]

def fit_component(tri,cad,kind,target):
    v,idx=np.unique(tri.reshape(-1,3),axis=0,return_inverse=True); f=idx.reshape(-1,3)
    e,freq=np.unique(np.sort(np.stack((f,np.roll(f,-1,1)),axis=2).reshape(-1,2),axis=1),axis=0,return_counts=True)
    # Protect all original interfaces with neighboring named walls. Reject any future
    # split on a seam rather than writing a T junction into the assembled shell.
    seam=e[freq==1]; ends=v[seam]
    if len(seam) and np.any((weight(ends.mean(axis=1),kind)>1e-4)&(np.linalg.norm(ends[:,0]-ends[:,1],axis=1)>target)):
        raise ValueError("Requested refinement overlaps a named-wall interface.")
    orig=len(f);v=v.astype(float);v,f=refine(v,f,kind,target)
    w=weight(v,kind);section=Sections(cad);maximum=0.
    for i in np.flatnonzero(w>0):
        original=v[i].copy();v[i]+=w[i]*(section.radial(original)-original)
        maximum=max(maximum,np.linalg.norm(v[i]-original))
    return v[f].astype("f4"),dict(input_triangles=orig,output_triangles=len(f),weighted_vertices=int((w>0).sum()),max_displacement_m=float(maximum))

def economy_patch(tri,kind,original_count,level):
    """Decimate only the fitted local sleeve; require its exact shared boundary to survive."""
    from meshlib import mrmeshpy as mr,mrmeshnumpy as mp
    params={"coarse":(1050,1550,.00125,.055),"medium":(2000,2800,.00075,.044),"fine":(3200,4400,.00040,.032)}
    ns,nn,tol,longest=params[level]
    additional=ns if kind=="sponson" else nn
    local=(weight(tri.reshape(-1,3),kind).reshape(-1,3)>0).any(axis=1)
    patch=tri[local]; v,ids=np.unique(patch.reshape(-1,3),axis=0,return_inverse=True)
    f=ids.reshape(-1,3).astype("i4")
    def boundary(points,faces):
        e,c=np.unique(np.sort(np.stack([faces,np.roll(faces,-1,1)],axis=2).reshape(-1,2),axis=1),axis=0,return_counts=True)
        return {tuple(sorted((tuple(points[u]),tuple(points[w])))) for u,w in e[c==1]}
    old=boundary(v,f)
    mesh=mp.meshFromFacesVerts(f,v.astype("f4"));q=mr.DecimateSettings()
    q.stabilizer=.00001
    q.maxDeletedFaces=max(0,len(tri)-original_count-additional);q.maxError=tol;q.maxEdgeLen=longest
    q.touchBdVerts=False;q.touchNearBdEdges=True;q.optimizeVertexPos=True;q.preventNormalFlips=True
    q.maxTriangleAspectRatio=35.;q.packMesh=True
    mr.decimateMesh(mesh,q)
    f2=mp.getNumpyFaces(mesh.topology).copy();v2=mp.getNumpyVerts(mesh).copy()
    if old!=boundary(v2,f2):raise ValueError("Decimation changed a shared boundary edge.")
    if mr.findSelfCollidingTrianglesBS(mesh).count():raise ValueError("Local decimation produced a self intersection.")
    reduced=np.concatenate([tri[~local],v2[f2]])
    return reduced,dict(level=level,qem_max_error_m=tol,maximum_collapsed_edge_m=longest,original_local_faces=len(patch),
                        reduced_local_faces=len(f2),locked_boundary_edges=len(old),added_faces=len(reduced)-original_count)


def ray(tri,x,z):
    use=(tri[:,:,0].min(1)<=x)&(tri[:,:,0].max(1)>=x)&(tri[:,:,2].min(1)<=z)&(tri[:,:,2].max(1)>=z)
    A,B,C=tri[use].astype(float).transpose(1,0,2); u=B-A;v=C-A
    det=u[:,0]*v[:,2]-u[:,2]*v[:,0]
    with np.errstate(invalid="ignore",divide="ignore"):
        a=((x-A[:,0])*v[:,2]-(z-A[:,2])*v[:,0])/det
        b=(u[:,0]*(z-A[:,2])-u[:,2]*(x-A[:,0]))/det
    hit=(np.abs(det)>1.e-17)&(a>=-1.e-8)&(b>=-1.e-8)&(a+b<=1.00000001)
    return A[hit,1]+a[hit]*u[hit,1]+b[hit]*v[hit,1]

def validate_probes(source,target,orig):
    records=[]
    for x in [-.10,-.075,-.05,-.025,0,.025,.05,.075,.10]:
        for z in [.85,.855,.86,.865,.87,.875,.88,.885,.88832]:
            row={"x_m":x,"z_m":z}
            for prefix,patches in [("cad",orig),("before",source),("after",target)]:
                s=ray(patches["sponson"],x,z); n=ray(patches["nacelle"],x,z)
                smax=float(s.max()) if len(s) else None;nmin=float(n.min()) if len(n) else None
                row[prefix+"_sponson_top_m"]=smax;row[prefix+"_nacelle_lower_m"]=nmin
                row[prefix+"_gap_m"]=nmin-smax if smax is not None and nmin is not None else None
            records.append(row)
    return records

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("source",type=Path);p.add_argument("destination",type=Path);p.add_argument("--target-mm",type=float,default=3.5);p.add_argument("--level",choices=("coarse","medium","fine"));a=p.parse_args();start=time.perf_counter()
    src=a.source.resolve(strict=True);out=a.destination.resolve()
    if not out.is_relative_to(GEO) or out.exists() or not src.is_relative_to(GEO):p.error("Use a new output directory and a source under 01_geometry.")
    if not 1.5<=a.target_mm<=8:p.error("Specify a local fitted edge size of 1.5–8 mm.")
    before={};after={};orig={};metrics={}
    with np.load(GEO/"cad_components.npz") as cad:
        for kind,tag,num in [("sponson","sponson","56"),("nacelle","nacelles","42")]:
            orig[kind]=cad[num];before[kind]=stl_triangles(src/f"wall_{tag}.stl")
            after[kind],metrics[kind]=fit_component(before[kind],orig[kind],kind,a.target_mm/1000)
            if a.level:
                after[kind],ec=economy_patch(after[kind],kind,len(before[kind]),a.level)
                metrics[kind].update(ec,output_triangles=len(after[kind]))
    records=validate_probes(before,after,orig)
    mismatch=[r for r in records if (r["cad_gap_m"] is None)!=(r["after_gap_m"] is None)]
    err=[abs(r["cad_gap_m"]-r["after_gap_m"]) for r in records if r["cad_gap_m"] is not None and r["after_gap_m"] is not None]
    if mismatch or not err or max(err)>=.003:
        raise ValueError(f"Unresolved CAD clearance: {len(mismatch)} existence mismatches, maximum {max(err,default=float('inf'))} m")
    out.mkdir(parents=True,exist_ok=False)
    for source in src.glob("*.stl"):
        key={"wall_nacelles":"nacelle","wall_sponson":"sponson"}.get(source.stem)
        if key:write_stl(out/source.name,after[key])
        else:shutil.copyfile(source,out/source.name)
    diag=dict(source=str(src),level=a.level,elapsed_s=time.perf_counter()-start,target_edge_mm=a.target_mm,method="Conforming local midpoint subdivision and smooth radial remapping to CAD cross-section segments. Only exterior portions of source components 42/56 in the gap are moved.",metrics=metrics,probes=records)
    (out/"gap_cad_fit.json").write_text(json.dumps(diag,indent=2),encoding="utf8")
    print(metrics);print([row for row in records if row["x_m"]==0 and row["z_m"] in (.86,.87,.88,.88832)])

if __name__=="__main__":main()
