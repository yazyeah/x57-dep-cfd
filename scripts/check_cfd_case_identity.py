"""Read existing Fluent smoke files and exercise wrong-grid restart rejection on one 2D cell."""
import json,os,shutil,tempfile
from pathlib import Path
import h5py,numpy as np
from fluent_checkpoints import case_for_data
from cfd_case_identity import canonical_mesh,connectivity_digest
from run_x57_converged import matching_restart

def test():
    root=Path(__file__).resolve().parents[1]
    discovery=root/'00_env_audit/solver_discovery'
    native=[canonical_mesh(discovery/p) for p in ['setup_smoke.msh','synthetic_actuator_test.cas.h5','synthetic_postproc_fixture.cas.h5']]
    if len(set(native))!=1:raise AssertionError('Native 3D equivalence failed')
    with tempfile.TemporaryDirectory(dir=discovery) as temp:
        work=Path(temp);section=work/'section.msh'
        section.write_text('(2 2)\n(10 (0 1 4 0 2))\n(10 (1 1 4 1 2)(\n0 0\n1 0\n1 1\n0 1\n))\n(12 (0 1 1 0))\n(13 (3 1 4 3 2)(\n1 2 1 0\n2 3 1 0\n3 4 1 0\n4 1 1 0\n))\n')
        target=canonical_mesh(section)
        def pair(stem,dx):
            p=work/(stem+'.cas.h5');d=work/(stem+'.dat.h5')
            with h5py.File(p,'w') as fp:
                z=fp.create_group('meshes/1/cells/zoneTopology');z['minId']=[1];z['maxId']=[1]
                # The same square is rotated in node order and face order.
                coords=fp.create_dataset('meshes/1/nodes/coords/1',data=[[1.+dx,1.],[0.,1.],[0.,0.],[1.,0.]])
                coords.attrs['minId']=1;coords.attrs['maxId']=4
                g=fp.create_group('meshes/1/faces/nodes/1');g['nnodes']=[2,2,2,2];g['nodes']=[1,2,3,4,1,4,3,2]
            with h5py.File(d,'w') as fp:
                fp['settings/Case File']=[p.name.encode()];ds=fp.create_dataset('results/1/phase-1/cells/SV_P/1',data=[1.])
                ds.attrs['minId']=1;ds.attrs['maxId']=1
            return p,d
        correct,correct_dat=pair('historic_autosaved_case',0);bad,bad_dat=pair('newer_wrong_mesh',.01)
        # Data may name a different native checkpoint stem. Follow its HDF5 case reference.
        alias=work/'historic_data_00050.dat.h5';correct_dat.rename(alias)
        os.utime(alias,(1000,1000));os.utime(bad_dat,(1001,1001))
        if canonical_mesh(correct)!=target or canonical_mesh(bad)==target:raise AssertionError('2D topology comparison failed')
        if matching_restart(work,target)!=(correct,alias) or case_for_data(alias)!=correct:raise AssertionError('Mismatched first restart selected')
        altered=canonical_mesh(bad)
        section.write_text(section.read_text().replace('1 1\n0 1\n','1.01 1\n0 1\n'))
        if canonical_mesh(section)!=altered:raise AssertionError('Modified 2D mesh was not detected')
    evidence=dict(classification='Native 12-cell solver smoke comparison and isolated one-cell 2D identity fixture.',
                  native_3D_matching_mesh_sha256=native[0],native_3D_case_pairs_compared=2,reordered_2D_nodes_faces_match=True,
                  changed_section_geometry_detected=True,rejected_newer_wrong_mesh_restart=True,recovered_autosave_via_native_case_reference=True)
    (discovery/'cfd_grid_identity_qa.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence))
if __name__=='__main__':test()

