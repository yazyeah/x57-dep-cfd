"""Assemble the finalized recovered P2 geometry from the independently validated component patches."""
import argparse,shutil
from p2_geometry_io import *
from verify_p2_cad_shell import verify
def assemble(level):
    src=GEO/('cad_level_'+level);out=GEO/('p2_ready_'+level);out.mkdir(exist_ok=True)
    for tag in TYPES:
        path=src/(tag+'.stl')
        if level=='coarse' and tag=='wall_empennage':path=GEO/'p2_hinge_seed/wall_empennage.stl'
        if level in ('medium','fine') and tag=='wall_wing':path=GEO/'p2_graded_wing_final'/(level+'.stl')
        shutil.copyfile(path,out/(tag+'.stl'))
    verify(out,True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('level',choices=['coarse','medium','fine']);assemble(p.parse_args().level)

