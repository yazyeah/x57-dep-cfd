"""Tiny isolated provenance regression, replacing neither a P2 grid nor an FSI solve."""
import json,tempfile
from pathlib import Path
import h5py,numpy as np
import fsi_provenance as prov
import compare_x57_cases as cases
from p2_geometry_io import TYPES,write_surface,write_binary_stl
from prepare_mapdl_shell import read_skin,canonical_faces

def require_rejection(fn):
    try:fn()
    except (ValueError,FileNotFoundError):return True
    raise AssertionError('Changed evidence unexpectedly accepted')

def check():
    operational=prov.ROOT;pre=operational/'03_cases/fsi_structural/preflight';pre.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=pre) as raw:
        root=Path(raw).resolve();save=prov.ROOT,prov.MODELS,cases.ROOT
        prov.ROOT=root;prov.MODELS=root/'03_cases/fsi_structural/models';cases.ROOT=root
        try:
            geom=root/'01_geometry/provenance_fixture';geom.mkdir(parents=True)
            t=np.array([[[0.,0,0],[1.,0,0],[0.,1.,0.]]],dtype='f4')
            patches={k:t+[0.,0.,j] for j,k in enumerate(TYPES)}
            msh=geom/'aircraft_domain.msh';write_surface(msh,patches,verify_shell=False)
            for k in prov.WALLS:write_binary_stl(geom/(k+'.stl'),patches[k],k)
            cad=root/'01_geometry/cad_patches';cad.mkdir();write_binary_stl(cad/'wall_wing.stl',t,'analytic-fixture')
            native=root/'02_mesh/coarse/fixture.mesh';native.parent.mkdir(parents=True);native.write_bytes(b'analytic identity fixture')
            cfg=native.parent/'mesh_config.json';prov.commit(cfg,dict(shell=str(msh),source_surface_dir=str(geom)))
            qa=native.parent/'mesh_qa.json';source=dict(meshing_config_path=str(cfg),meshing_config_sha256=prov.source_hash(cfg),source_surface_dir=str(geom),source_surface_sha256=prov.source_hash(msh))
            prov.commit(qa,dict(passed=True,level='coarse',source_mesh=str(native),mesh_sha256=prov.source_hash(native),source_geometry=source))
            record=prov.geometry();lock=prov.lock_geometry(record);xyz,ff,tt=read_skin(record)
            assert len(ff)==5 and np.array_equal(tt,np.arange(5))
            assert np.array_equal(canonical_faces(t),canonical_faces(np.roll(t,1,axis=1)))
            assert not np.array_equal(canonical_faces(t),canonical_faces(t[:,::-1]))
            signatures=[];models={}
            for grid in ('coarse','medium','fine'):
                work=prov.MODELS/grid;work.mkdir(parents=True)
                (work/'model.inp').write_text('fixture '+grid);(work/'shell_mesh.npz').write_bytes(grid.encode())
                files=prov.hashes([work/'model.inp',work/'shell_mesh.npz'])
                digest=prov.signature(dict(geometry=record['signature'],grid=grid,model_files_sha256=files))
                prov.commit(work/'model.json',dict(level=grid,model_generator_sha256=prov.source_hash(Path(prov.__file__).with_name('prepare_mapdl_shell.py')),geometry_signature=record['signature'],geometry_lock=str(lock),model_files_sha256=files,model_signature=digest))
                model=prov.accepted_model(grid);signatures.append(model['geometry_signature']);models[grid]=model['model_signature']
            assert len(set(signatures))==1 and len(set(models.values()))==3
            dom=root/'03_cases/coarse_rpm100';dom.mkdir()
            case=dom/'fixture.cas.h5';data=dom/'fixture.dat.h5'
            with h5py.File(case,'w') as fp:
                top=fp.create_group('meshes/1/cells/zoneTopology');top['minId']=[1];top['maxId']=[1]

            with h5py.File(data,'w') as fp:
                field=fp.create_dataset('results/1/phase-1/cells/SV_P/1',data=[0.]);field.attrs['minId']=np.uint64(1);field.attrs['maxId']=np.uint64(1);fp.create_dataset('settings/Case File',data=np.array([b'fixture.cas.h5']))
            from cfd_case_identity import reference,bind_pair
            prov.commit(root/'02_mesh/grid_ladder_qa.json',dict(passed=True,mesh_sha256={'coarse':prov.source_hash(native)}))
            ref=reference(root,dom.name,False)
            endpoint=dict(passed=True,accepted_stem='fixture')
            endpoint.update(bind_pair(endpoint,case,data,ref));prov.commit(dom/'iteration_qa.json',endpoint)

            prov.commit(dom/'fluent_discrete_disk_integrals.json',{'fixture':0})
            prov.commit(root/'01_geometry/geometry_audit.json',{'fixture':1})
            for nm in ['map_cfd_shell_loads','extract_fluent_fields']:
                dest=root/'scripts'/(nm+'.py');dest.parent.mkdir(exist_ok=True);dest.write_text('#fixture')
            identity=prov.load_identity('fine',dom.name);work=prov.MODELS.parent/('fine_struct__'+dom.name);work.mkdir()
            (work/'mapped_loads.inp').write_text('fixture');(work/'nodal_loads.npy').write_bytes(b'inputs')
            prov.commit(work/'load_transfer.json',dict(load_identity=identity,mapped_files_sha256=prov.hashes([work/'mapped_loads.inp',work/'nodal_loads.npy'])))
            prov.verify_transfer('fine',dom.name)
            with h5py.File(data,'a') as fp:fp.attrs['changed']=0.1
            stale_load=require_rejection(lambda:prov.verify_transfer('fine',dom.name))
            file=prov.MODELS/'fine/model.inp';file.write_text('changed support')
            stale_model=require_rejection(lambda:prov.accepted_model('fine'))
            wing=geom/'wall_wing.stl';write_binary_stl(wing,patches['wall_wing'][:,::-1],'wing')
            stale_wall=require_rejection(lambda:read_skin(prov.geometry()))
            native.write_bytes(b'changed accepted volume')
            stale_native=require_rejection(prov.geometry)
            evidence=dict(classification='Temporary analytical identity fixture. No production CFD or structural solution.',
                          shared_geometry_signature_across_three_levels=len(set(signatures))==1,separate_structural_signatures=len(set(models.values()))==3,
                          stale_cfd_data_rejected=stale_load,stale_group_or_support_deck_rejected=stale_model,
                          reversed_STL_faces_rejected=stale_wall,changed_accepted_volume_rejected=stale_native)
        finally:prov.ROOT,prov.MODELS,cases.ROOT=save
    prov.commit(pre/'source_signature_qa.json',evidence)
    print(json.dumps(evidence))
if __name__=='__main__':check()

