"""Watertight CSG from the two installed CAD parts; locally repair the last 3 mm of part 7."""
import numpy as np,triangle
from p2_geometry_io import *
from rejoin_p2_tail_tip import clip,ring,bridge
from meshlib import mrmeshpy as mr,mrmeshnumpy as mn
from verify_p2_cad_shell import geom
from restore_p2_hlp5_fairing import mesh,boolean

def cap(t,z):
    r=ring(t,z,True)[:-1]
    ids=np.arange(len(r));seg=np.c_[ids,np.roll(ids,-1)]
    q=triangle.triangulate({'vertices':r[:,:2].astype(float),'segments':seg},'pYQ')
    if len(q['vertices'])!=len(r):raise ValueError('CAD cross-section intersects itself')
    f=q['triangles'];orientation=np.sum(r[:,0]*np.roll(r[:,1],-1)-r[:,1]*np.roll(r[:,0],-1))
    if orientation<0:f=f[:,::-1]
    return np.vstack([t,r[f]])

def closed(t):
    v,f=indices(t);o=mesh(v,f)
    if o.volume()<0:o.topology.flipOrientation()
    return o

def part_body(cad,lo,hi=None):
    t=clip(cad,lo,1)
    if hi is not None:t=clip(t.astype(float),hi,-1)
    t=cap(t,lo)
    if hi is not None:t=cap(t,hi)
    return closed(t)

def actual(cads,b):
    from restore_p2_hlp5_fairing import boolean
    prefix=part_body(cads[0],b-.003,.20121);pylon=part_body(cads[1],b-.00297)
    if len(mr.findRightBoundary(prefix.topology)) or mr.findSelfCollidingTrianglesBS(prefix).count():raise ValueError('Raw forebody is not valid')
    if len(mr.findRightBoundary(pylon.topology)) or mr.findSelfCollidingTrianglesBS(pylon).count():raise ValueError('Raw fairing is not valid')
    aft=part_body(cads[0],.20068)
    fix=mr.RebuildMeshSettings();fix.voxelSize=.00011;fix.decimate=True
    rebuilt=mr.rebuildMesh(aft,fix);rebuilt.pack()
    if len(mr.findRightBoundary(rebuilt.topology)) or mr.findSelfCollidingTrianglesBS(rebuilt).count():raise ValueError('Local terminal repair is not watertight')
    body=boolean(prefix,rebuilt,mr.BooleanOperation.Union)
    whole=boolean(body,pylon,mr.BooleanOperation.Union)
    v,f=geom(whole);tr=v[f]
    # Reverse the solid envelope for the inward-pointing fluid boundary.
    tr=clip(tr[:,::-1].astype(float),b,1)
    return tr

