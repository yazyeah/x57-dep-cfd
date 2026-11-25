"""Recover the physical CAD components needed by P2 from the archived geometry orientation."""
import json
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from p2_geometry_io import *
import inspect_x57_geometry as original
def main():
    source=ROOT/'02_mesh/coarse/iso45/aircraft_domain.msh';patches=read_patches(source)
    save_patches(GEO/'p2_iso45',patches)
    print('Recovered named fluid shell',sum(map(len,patches.values())),flush=True)
    audit=json.loads((GEO/'geometry_audit.json').read_text(encoding='utf-8-sig'))
    raw=np.memmap(original.INPUT_STL,mode='r',offset=84,dtype=dtype)
    transform=original.quat_to_matrix(audit['baked_stl_rotation_removed']['glb_node0_quaternion_xyzw'])*original.IN2M
    tris=raw['v'].astype(float)@transform;tris=tris[tris[:,:,2].max(1)>-1e-5]
    _,inv=np.unique(np.ascontiguousarray(np.round(tris.reshape(-1,3),6)).view('V24'),return_inverse=True);f=inv.reshape(-1,3)
    ok=(np.diff(np.sort(f,axis=1),axis=1)!=0).all(1);ids=np.flatnonzero(ok)
    _,first=np.unique(np.ascontiguousarray(np.sort(f[ok],axis=1)).view('V24'),return_index=True);keep=np.sort(ids[first]);f=f[keep]
    edges=np.sort(np.concatenate([f[:,[0,1]],f[:,[1,2]],f[:,[2,0]]]),axis=1)
    _,ei=np.unique(np.ascontiguousarray(edges.astype('i4')).view('i8').ravel(),return_inverse=True);o=np.argsort(ei,kind='stable')
    adjacent=ei[o[:-1]]==ei[o[1:]];i=o[:-1][adjacent]%len(f);j=o[1:][adjacent]%len(f)
    _,labs=connected_components(coo_matrix((np.ones(len(i)),(i,j)),shape=(len(f),len(f))),directed=False)
    group={};tags={};blades=0
    for label in np.unique(labs):
        t=tris[keep[labs==label]].copy();mi=t.min((0,1));ma=t.max((0,1))
        if ma[0]<-.4 and ma[0]-mi[0]<.09:blades+=1;continue
        tag='wall_fuselage' if mi[0]<-3 else 'wall_sponson' if mi[1]<-.75 else 'wall_empennage' if mi[0]>2.5 else 'wall_wing' if ma[2]-mi[2]>4 else 'wall_nacelles'
        t[:,:,2][abs(t[:,:,2])<1e-5]=0;posit=t[:,:,2]>=0;parts=[t[posit.all(1)]]
        extra=[]
        for tr in t[posit.any(1)&~posit.all(1)]:
            poly=[]
            for a,b in zip(tr,np.roll(tr,-1,axis=0)):
                if a[2]>=0:poly.append(a)
                if a[2]*b[2]<0:
                    p=a+(b-a)*a[2]/(a[2]-b[2]);p[2]=0;poly.append(p)
            extra.extend([[poly[0],poly[k],poly[k+1]] for k in range(1,len(poly)-1)])
        if extra:parts.append(np.array(extra))
        group[str(label)]=np.concatenate(parts).astype('f4');tags[str(label)]=tag
    assert blades==33 and tags['51']=='wall_wing' and tags['54']=='wall_empennage' and tags['56']=='wall_sponson',tags
    np.savez(GEO/'cad_components.npz',**group);(GEO/'cad_component_regions.json').write_text(json.dumps(tags,indent=2))
    for tag in WALLS:write_binary_stl(GEO/'cad_patches'/(tag+'.stl'),np.concatenate([group[k] for k in group if tags[k]==tag]),tag)
    print('Verified component map',tags,flush=True)
if __name__=='__main__':main()

