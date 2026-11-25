"""Executed by Fluent v252's embedded Python after reading a fine case/data pair.
The pilot config uses a separate workdir and synthetic rectangular fixture.
"""
from pathlib import Path
import json, math, os, subprocess, sys, traceback
sys.path.insert(0,r'D:\Ansys\ANSYS Inc\ANSYS Student\v252\fluent\fluent25.2.0\cortex\pylib')
import flsetup
flsetup.insert_pyfluent_module_path()
from flapi.flproxy import Proxy
from flapi.generated.solver.settings_252 import root
s=root();s.set_flproxy(Proxy)
work=Path.cwd();base=Path(os.environ['X57_WORKSPACE']).resolve(strict=True)
sys.path.insert(0,str(base/'scripts'))
from publication_fonts import configure_fluent_font
font_evidence={}
cfg=json.loads((work/'render_config.json').read_text())
pilot=cfg['mode']=='smoke'
dest=work
graphics=s.results.graphics
surfaces=s.results.surfaces
views=graphics.views
picture=graphics.picture
picture.use_window_resolution=False
picture.x_resolution=2560;picture.y_resolution=1440
walls=list(cfg['wall_zones'])
stats={}
def save(name,position,target,up,width):
    camera=views.camera
    camera.projection(type='orthographic')
    camera.position(xyz=position);camera.target(xyz=target);camera.up_vector(xyz=up)
    camera.field(width=width,height=width*9/16)
    path=dest/(name+'.png')
    picture.save_picture(file_name=path.as_posix())
    if not path.is_file() or path.stat().st_size<1000:raise RuntimeError('Native image missing: '+str(path))
    stats[name]={'engine':'ANSYS Fluent 2025 R2','source_case':cfg.get('case_file'),
                 'source_data':cfg.get('data_file'),'run_id':cfg.get('run_id'),'native_png_bytes':path.stat().st_size,'position':position,'target':target,'width_m':width}
def mesh(name,zones,wire=False):
    graphics.mesh[name]={'surfaces_list':zones,'options':{'faces':not wire,'edges':wire}}
    ob=graphics.mesh[name]
    if wire:ob.edge_type_options.edge_type='all'
    return ob
def rake(name,a,b,count):
    surfaces.rake_surface[name]={'p0':a,'p1':b,'number_of_points':count}
    return name
def flow(name,seeds,body=True):
    graphics.pathline[name]={'field':'velocity-magnitude','release_from_surfaces':seeds}
    obj=graphics.pathline[name];obj.step=3000
    if body:
        obj.draw_mesh=True;obj.mesh_object='airframe'
    prepare_legend(name,obj)
    return obj
def cut(name,z):
    surfaces.plane_surface[name]={'method':'xy-plane','z':z}
    return name
def mirror(enabled):
    if cfg.get('symmetry'):views.mirror_zones=[cfg['symmetry']] if enabled else []
def isolated(name,method):
    try:
        method()
        print('X57-NATIVE-VIEW-SAVED',name,flush=True)
    except Exception as exc:
        print('X57-NATIVE-VIEW-FAILED',name,str(exc),flush=True);traceback.print_exc()
        stats[name]={'error':str(exc)}
    (work/'native_font_evidence.json').write_text(json.dumps(font_evidence,indent=2))
    (work/'native_render_evidence.json').write_text(json.dumps(stats,indent=2))
def select_field(setting,choices):
    options=list(setting.allowed_values())
    for name in choices:
        for actual in options:
            if actual.casefold()==name.casefold():return actual
    raise RuntimeError('Unavailable Fluent field '+repr(choices)+' in '+repr(options))

def field_object(name,options,zones):
    graphics.contour[name]={}
    obj=graphics.contour[name];field=select_field(obj.field,options)
    obj.field=field;obj.surfaces_list=zones;obj.filled=True;obj.node_values=False
    prepare_legend(name,obj)
    return obj

def prepare_legend(name,obj):
    evidence=configure_fluent_font(obj.color_map)
    evidence['field']=obj.field.get_state()
    font_evidence[name]=evidence
    return evidence

def field_range(obj):
    bounds=obj.range_options
    bounds.compute()
    lo=float(bounds.minimum.get_state());hi=float(bounds.maximum.get_state())
    if not math.isfinite(lo) or not math.isfinite(hi) or hi<=lo:
        raise ValueError('Invalid scalar range '+repr((lo,hi)))
    return [lo,hi]

def configure_render_background():
    graphics.colors.background='white';graphics.colors.foreground='black'
    for attr in ('left_top','left_bottom','right_top','right_middle','right_bottom'):
        setattr(graphics.colors.titles,attr,'')
    picture.invert_background=False

def store_frame(name,obj,legends,position,target,up,width,metadata=None):
    obj.display()
    save(name,position,target,up,width)
    row=stats[name];row['up']=up;row['source_case']=cfg['case_file']
    row['metadata']=metadata or {};row['legend_records']=[]
    missing=[]
    for key,legend,units in legends:
        ev=font_evidence[key];record={'object':key,'field':ev['field'],'units':units,'font':ev}
        if not ev['exact']:
            record['range']=field_range(legend);record['palette']=legend.color_map.color.get_state()
            record['descending_vertical_bar']=True
            missing.append((key,legend))
        row['legend_records'].append(record)
    if missing:
        if len(missing)!=1:raise RuntimeError('A fallback frame requires one measured native swatch')
        original=dest/(name+'.png');ref=dest/'original_native';clean=dest/'clean_native';ref.mkdir(exist_ok=True);clean.mkdir(exist_ok=True)
        raw=ref/original.name
        raw.write_bytes(original.read_bytes())
        for _,legend in missing:legend.color_map.visible=False
        obj.display()
        camera=views.camera;camera.projection(type='orthographic');camera.position(xyz=position);camera.target(xyz=target);camera.up_vector(xyz=up);camera.field(width=width,height=width*9/16)
        clean_path=clean/original.name;picture.save_picture(file_name=clean_path.as_posix())
        for _,legend in missing:legend.color_map.visible=True
        row['original_native']=str(raw);row['clean_native']=str(clean_path);row['font_overlay_required']=True

def as_scene(name,objects):
    s.results.scene[name]={}
    scene=s.results.scene[name]
    for entry in objects:scene.graphics_objects.add(name=entry)
    return scene

def extra_mesh():
    mirror(False)
    z=cfg.get('sponson_section_z',.86)
    section=cut('sponson-gap-plane',z)
    grid=mesh('sponson-gap-grid',[section],True)
    target=[-.18,-.34,z];pos=[target[0],target[1],z+2]
    store_frame(PRIMARY[2],grid,[],pos,target,[0,1,0],2.10,{'z_m':z,'disk':cfg['disks'][0]['name']})

def pressure_face(name,bottom):
    mirror(True)
    key='pressure-bottom' if bottom else 'pressure-top'
    ob=field_object(key,['pressure','static-pressure'],walls)
    pos=[-6,-10,8] if bottom else [-6,10,8]
    store_frame(name,ob,[(key,ob,'Pa')],pos,[.4,0,0],[0,0,1],12.,{'side':'bottom' if bottom else 'top'})

def isovortex():
    mirror(False)
    key='q-vortex-wake'
    surfaces.iso_surface[key]={}
    iso=surfaces.iso_surface[key];iso.field=select_field(iso.field,['q-criterion','q-criterion-magnitude'])
    iso.range.compute();lo=float(iso.range.minimum.get_state());hi=float(iso.range.maximum.get_state())
    if not math.isfinite(hi) or hi<=0:raise ValueError('No positive physical Q criterion is present')
    threshold=max(max(0.,lo)+(hi-max(0.,lo))*.002,.00001)
    if threshold>=hi:raise ValueError('Q isosurface threshold falls outside the active field')
    iso.iso_values=[threshold]
    ob=field_object('q-speed',['velocity-magnitude'],[key]);ob.draw_mesh=True;ob.mesh_object='airframe'
    store_frame(PRIMARY[8],ob,[('q-speed',ob,'m/s')],[6,4,9],[1.5,.1,3.85],[0,1,0],7.,
                {'Q_isovalue_s^-2':threshold,'evaluated_Q_range_s^-2':[lo,hi],'positive_range_fraction':.002})

def oilflow():
    mirror(True)
    surf=field_object('surface-yplus',['y-plus','wall-yplus','wall-y-plus'],walls)
    key='surface-oilflow'
    graphics.pathline[key]={};oil=graphics.pathline[key]
    oil.field=select_field(oil.field,['y-plus','wall-yplus','wall-y-plus','velocity-magnitude'])
    oil.release_from_surfaces=walls;oil.option.oil_flow=True;oil.option.onzone=walls
    oil.step=1200;oil.skip=70;oil.color_map.visible=False
    scene=as_scene('skin-and-oil',['surface-yplus',key])
    store_frame(PRIMARY[9],scene,[('surface-yplus',surf,'1')],[-5,9,7],[.6,0,0],[0,0,1],12.,
               {'oil_flow_native':True,'oil_on_zones':walls,'seed_skip':70})

def native_field_aliases(name):
    # Fluent exposes named expressions as postprocessing field variables.
    return [name, 'expr:'+name, 'expr-'+name, 'expression-'+name,
            'named-expression-'+name]


def surface_area(surface, label):
    key='X57Area'+label
    s.setup.named_expressions[key]={'definition':"Area(['"+surface+"'])"}
    area=float(s.setup.named_expressions[key].get_value())
    if not math.isfinite(area) or area<=0:
        raise ValueError('No native fluid surface for '+surface)
    return area


def wake_panels(number):
    mirror(False)
    spec=cfg['wake_display']
    shear=number==15
    name=PRIMARY[number-1]
    prefix='x57-r'+str(number)
    variable='X57ModeledShearXY' if shear else 'X57TotalPressureCoeff'
    qref=spec['q_ref_Pa']
    definition=('TurbulenceViscosity*(dVelocitydy.x+dVelocitydx.y)' if shear
                else 'TotalPressure/('+format(qref,'.17g')+' [Pa])')
    s.setup.named_expressions[variable]={'definition':definition}
    aliases=native_field_aliases(variable)
    key=prefix+'-iso'
    surfaces.iso_surface[key]={}
    iso=surfaces.iso_surface[key]
    choices=(['turb-kinetic-energy','turbulent-kinetic-energy'] if shear else ['total-pressure'])
    iso.field=select_field(iso.field,choices)
    threshold=spec['k_isovalue_m2_s2'] if shear else spec['Cp0_isovalue']*qref
    iso.range.compute()
    bounds=[float(iso.range.minimum.get_state()),float(iso.range.maximum.get_state())]
    if not bounds[0]<threshold<bounds[1]:
        raise ValueError(f'Native iso threshold {threshold} outside field limits {bounds}')
    iso.iso_values=[threshold]
    area=surface_area(key,'Shell'+str(number))
    camera=([7.1,4.6,8.1],[.45,-.22,2.65],[0,1,0],8.2)
    iso_label=prefix+'-shell'
    field=field_object(iso_label,aliases if shear else ['velocity-magnitude'],[key])
    field.draw_mesh=True
    field.mesh_object='airframe'
    iso_name=name+'_shell'
    field_units='Pa' if shear else 'm/s'
    store_frame(iso_name,field,[(iso_label,field,field_units)],*camera,
                metadata={'iso_field':iso.field.get_state(),'iso_value':threshold,
                          'iso_unit':'m2/s2' if shear else 'Pa','native_field_range':bounds,
                          'positive_wake_percentile':85,'surface_area_m2':area})
    production_control()
    groups=[]
    areas=[]
    zmin,zmax,ymin,ymax=spec['wake_zy_bounds_m']
    for i,x in enumerate(spec['sections_x_m']):
        plane=prefix+'-section-'+str(i)
        surfaces.plane_surface[plane]={'method':'three-points','p0':[x,ymin,zmin],
            'p1':[x,ymax,zmin],'p2':[x,ymax,zmax],'bounded':True}
        groups.append(plane)
        areas.append(surface_area(plane,'Section'+str(number)+'N'+str(i)))
    plane_label=prefix+'-slices'
    section=field_object(plane_label,aliases,groups)
    section.draw_mesh=True
    section.mesh_object='airframe'
    plane_name=name+'_slices'
    store_frame(plane_name,section,[(plane_label,section,'Pa' if shear else '1')],*camera,
                metadata={'sections_x_m':spec['sections_x_m'],'sections_area_m2':areas,
                          'sections_zy_bounds_m':spec['wake_zy_bounds_m']})
    stats[name]={'panels':[iso_name,plane_name],'expression':variable,'definition':definition,
                 'q_ref_Pa':qref,'k_or_Cp0_isovalue':spec['k_isovalue_m2_s2'] if shear else spec['Cp0_isovalue']}


def production_control():
    if pilot:return
    code=subprocess.run([os.environ['X57_PYTHON'],'-B',str(base/'scripts/control_gate.py'),'check'],
                        stdout=subprocess.PIPE,stderr=subprocess.STDOUT).returncode
    if code or any((work/n).exists() for n in ('exit-fluent.txt','exit-fluent')):
        raise SystemExit(code or 10)

def render():
    configure_render_background()
    mesh('airframe',walls)
    st=cfg.copy()
    def farfield():
        ob=mesh('farfield-grid',[cfg['symmetry']],True)
        ob.display()
        if pilot:save('render01_mesh_farfield_hexcore',[.5,0,5.],[.5,0,0],[0,1,0],3.9)
        else:save('render01_mesh_farfield_hexcore',[5,7.5,60],[5,7.5,0],[0,1,0],50.5)
    def layers():
        z=cfg['section_z']
        m=mesh('inflation-grid',[cut('inflation-cut',z)],True)
        m.display()
        x,y=cfg['leading_edge_xy']
        save('render02_mesh_wing_inflation_closeup',[x,y,z+1],[x,y,z],[0,1,0],cfg['closeup_width_m'])
    def pressure():
        mirror(True)
        graphics.contour['skin-pressure']={'field':'pressure','surfaces_list':walls,'filled':True,'node_values':False}
        graphics.contour['skin-pressure'].display()
        if pilot:save('render05_surface_pressure_contour_3d',[4,3,6],[.5,0,.9],[0,1,0],4.8)
        else:save('render05_surface_pressure_contour_3d',[-6,10,8],[.4,0,0],[0,1,0],12.)
    def lines(name,kind):
        props=cfg['disks'];ss=[]
        for p in (props[-1:] if kind=='tip' else props):
            x=p['x_disk_m']+p['thickness_m']/2+.002;y=p['y_axis_m'];z=p['z_axis_m']
            r1=p['inner_radius_m']+.02*(p['outer_radius_m']-p['inner_radius_m'])
            r2=p['outer_radius_m']-.04*(p['outer_radius_m']-p['inner_radius_m'])
            m=12 if kind=='tip' else 6
            for i in range(m):
                a=math.pi*2*i/m;c=math.cos(a);t=math.sin(a)
                ss.append(rake(name+'-'+p['name'].lower()+'-'+str(i),[x,y+r1*c,z+r1*t],[x,y+r2*c,z+r2*t],4))
        if kind=='global':
            for i in range(4):
                yd=-.35+.25*i if pilot else -.7+i*.5
                ss.append(rake('ambient-'+str(i),[-.8 if pilot else -4.,yd,.1],[-.8 if pilot else -4.,yd,1.8 if pilot else 5.4],18))
        mirror(kind!='tip')
        pathlines=flow(name,ss)
        if pilot:pos,tgt,w=[3,2,5],[.4,0,1],4.8
        elif kind=='tip':pos,tgt,w=[5.2,3.1,8.8],[1.35,.12,4.75],4.9
        elif kind=='all':pos,tgt,w=[-6.4,9.5,8.4],[1.2,0,0],13.
        else:pos,tgt,w=[-8.,11.,10.],[1.6,0,0],15.5
        store_frame(name,pathlines,[(name,pathlines,'m/s')],pos,tgt,[0,1,0],w,{'release_surfaces':ss})
    def surface_field(num, field_name, choices, bottom, units):
        mirror(True)
        obj=field_object(field_name,choices,walls)
        angle=[-6,-9,7] if bottom else [-6,9,7]
        store_frame(PRIMARY[num-1],obj,[(field_name,obj,units)],angle,[.35,0,0],[0,0,1],12.,
                    {"surface_view":"bottom" if bottom else "top"})
    jobs = {
        1:farfield, 2:layers, 3:extra_mesh,
        4:lambda:lines(PRIMARY[3],"all"),5:lambda:lines(PRIMARY[4],"tip"),
        6:lambda:surface_field(6,"pressure-top",["pressure","static-pressure"],False,"Pa"),
        7:lambda:surface_field(7,"pressure-bottom",["pressure","static-pressure"],True,"Pa"),
        8:lambda:lines(PRIMARY[7],"global"),9:isovortex,10:oilflow,
        15:lambda:wake_panels(15),16:lambda:wake_panels(16),
        13:lambda:surface_field(13,"wall-shear-top",["wall-shear","wall-shear-stress","wall-shear-stress-magnitude"],False,"Pa"),
        14:lambda:surface_field(14,"wall-shear-bottom",["wall-shear","wall-shear-stress","wall-shear-stress-magnitude"],True,"Pa"),
    }
    for key in cfg["numbers"]:
        if any((work/name).exists() for name in ("exit-fluent.txt","exit-fluent")):
            print("X57-NATIVE-RENDER-PAUSED",flush=True)
            return
        production_control()
        isolated(PRIMARY[key-1],jobs[key])
        production_control()
    if any("error" in row for row in stats.values()):
        raise RuntimeError("Incomplete native renders. See native_render_evidence.json")
    print("X57-NATIVE-RENDER-PASS",flush=True)
PRIMARY=cfg["names"]
render()
