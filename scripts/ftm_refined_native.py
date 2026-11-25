"""Fluent v252 embedded Python. Apply and verify the native scoped FTM tasks."""
import hashlib
import json
import math
from pathlib import Path


def task_ok(task):
    done = task.Execute()
    if done is False or task.State.get_state() != 'Up-to-date':
        raise RuntimeError('Fluent did not complete the FTM task')


def check_exit(work):
    if any((work/flag).exists() for flag in ('exit-fluent.txt', 'exit-fluent')):
        raise RuntimeError('Native managed stop requested')


def install(workflow, meshing, cfg_path):
    path=Path(cfg_path)
    cfg=json.loads(path.read_text(encoding='utf-8'))
    work=path.parent
    for plan in cfg['continuous_parent_inputs']:
        check_exit(work)
        walls=plan['walls']
        prefs=dict(ShowLocalPrismPreferences=True, Continuous='Stair Step',
                   SplitPrism='Yes',NumberOfSplitLayers=plan['split_count'])
        args=dict(AddChild='yes',BLControlName=plan['name'],OffsetMethodType='uniform',
                  FaceScope=dict(RegionsType='named-fluid-regions',GrowOn='selected-zones'),
                  RegionScope=['external_fluid'],ZoneSelectionList=walls,
                  FirstHeight=plan['parent_height_m'], Rate=plan['parent_growth'],
                  NumberOfLayers=plan['parent_count'],LocalPrismPreferences=prefs)
        parent=workflow.TaskObject['Add Boundary Layers']
        parent.Arguments.set_state(args)
        parent.AddChildToTask()
        parent.InsertCompoundChildTask()
        child=workflow.TaskObject[plan['name']]
        child.Arguments.set_state(args)
        task_ok(child)
        state=child.Arguments.get_state()
        (work/(plan['name']+'_task.json')).write_text(json.dumps(state,indent=2),encoding='utf-8')
        if (set(state.get('BLZoneList',[]))!=set(walls)
                or state.get('BLRegionList')!=['external_fluid']
                or state.get('NumberOfLayers')!=plan['parent_count']
                or state['LocalPrismPreferences'].get('NumberOfSplitLayers')!=plan['split_count']
                or state['LocalPrismPreferences'].get('SplitPrism')!='Yes'
                or not math.isclose(state['FirstHeight'],plan['parent_height_m'])
                or not math.isclose(state['Rate'],plan['parent_growth'])):
            raise RuntimeError('Native wall scope did not retain its registered physical settings')
        print('X57 executed FTM scoped prisms',plan['name'],walls,flush=True)


def execute_volume(task,work,meshing,diagnose):
    try:
        task_ok(task)
    except Exception as error:
        if diagnose:
            import traceback
            import runpy
            original=traceback.format_exc()
            try:
                helper=work.parents[2]/"scripts"/"ftm_failure_faces.py"
                runpy.run_path(str(helper))["capture"](meshing,work,task,error,original,globals().get("meshing_utilities"))
            except Exception as secondary:
                print("X57 failed-fill diagnostic unavailable:",repr(secondary),flush=True)
        raise


def fill(workflow,meshing,cfg_path):
    path=Path(cfg_path)
    cfg=json.loads(path.read_text(encoding='utf-8'))
    work=path.parent
    check_exit(work)
    for plan in cfg['continuous_parent_inputs']:
        child=workflow.TaskObject[plan['name']]
        if (child.State.get_state()!='Up-to-date'
                or set(child.Arguments.get_state().get('BLZoneList',[]))!=set(plan['walls'])):
            raise RuntimeError('Missing native scoped BL control in the restart')
    reg=meshing.GlobalSettings.FTMRegionData
    r=reg.get_state()
    names=r['AllRegionNameList']
    types=r['AllRegionTypeList']
    fills=list(r['AllRegionVolumeFillList'])
    idx=names.index('external_fluid')
    if types.count('fluid')!=1 or types[idx]!='fluid':
        raise RuntimeError('Unexpected native fluid regions')
    fills[idx]='poly-hexcore'
    sizes=[str(cfg['max_size'])]*len(names)
    reg.AllRegionVolumeFillList.set_state(fills)
    reg.AllRegionSizeList.set_state(sizes)
    quality=cfg['orthogonal_quality']
    if not 0.0<=quality<=0.10: raise ValueError('FTM generation OrthogonalQuality must be in [0.0, 0.10]')
    args=dict(EnableParallel=True,AdvancedOptions=True,SaveVolumeMesh=cfg.get('native_save_volume_mesh',False),
              EditVolumeSettings=True,OrthogonalQuality=quality,
              AllRegionNameList=names,AllRegionVolumeFillList=fills,AllRegionSizeList=sizes,
              FillWithSizeField='Yes',QualityMethod='Orthogonal')
    if cfg.get('native_conformal_prism_split'):
        args['ConformalPrismSplit']='Yes'
    v=meshing.GenerateTheVolumeMeshFTM.create_instance()
    v.set_state(args)
    state=v.get_state()
    if cfg.get('native_conformal_prism_split') and not v.ConformalPrismSplit.is_active():
        raise RuntimeError('Native FTM conformal prism split is inactive')
    if any(state.get(k)!=v for k,v in args.items()):
        raise RuntimeError('The volume generator did not retain the requested settings')
    (work/'volume_readback.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
    with Path(cfg['size_field_path']).open('rb') as stream:
        sig=hashlib.sha256()
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            sig.update(chunk)
    (work/'size_field_used.sha256').write_text(sig.hexdigest()+'\n',encoding='ascii')
    task=workflow.TaskObject['Generate the Volume Mesh']
    task.Arguments.set_state(args)
    task_state=task.Arguments.get_state()
    if task_state.get("OrthogonalQuality")!=quality:
        raise RuntimeError("Volume task did not retain the generation OrthogonalQuality")
    execute_volume(task,work,meshing,cfg.get('diagnose_failed_fill',False))
    print('X57 completed native Poly-Hexcore generation',flush=True)
