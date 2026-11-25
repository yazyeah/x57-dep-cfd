"""White-background native-field comparison renders for X-57 views 11 and 12."""
import argparse,json
from pathlib import Path
import h5py
import numpy as np
import pyvista as pv
from PIL import Image
from cmcrameri import cm
from cut_fluent_cells import bounds,read_id_blocks,zones
from extract_fluent_fields import extract_slice
from compare_x57_cases import ROOT,BASE,OGE,VECTOR,accepted,read_json
from read_x57_section import load_section,case_names
from publication_fonts import configure_pyvista
from native_fluent_render_provenance import endpoint
from cfd_case_identity import digest
from control_gate import atomic_write_json

NAMES={11:"render11_ige_vs_oge_wake_3d",12:"render12_opt_highlift_flow_comparison"}
CAM=[(7.1,4.6,8.1),(.45,-.22,2.65),(0,1,0)]
RANGE=(-1.3,3.15,-1.68,1.25,-.01,5.8)
OUT=ROOT/"DELIVERABLES/fluent_renders"
EVIDENCE=ROOT/"04_postproc/native_render_evidence"


def body(case):
    face_groups=[]
    with h5py.File(case) as f:
        m=f["meshes/1"];xyz=read_id_blocks(m["nodes/coords"],int(max(m["nodes/zoneTopology/maxId"])),float,3)
        for nm,(low,high) in zones(m["faces/zoneTopology"]).items():
            if not nm.startswith("wall_"):continue
            for g in m["faces/nodes"].values():
                lo,hi=bounds(g);a=max(low,lo);b=min(high,hi)
                if a>b:continue
                nn=g["nnodes"][:].astype(np.int64);span=np.r_[0,np.cumsum(nn)]
                ids=g["nodes"][span[a-lo]:span[b-lo+1]]
                for n in np.unique(nn[a-lo:b-lo+1]):
                    inds=a-lo+np.flatnonzero(nn[a-lo:b-lo+1]==n)
                    refs=ids[(span[inds]-span[a-lo])[:,None]+np.arange(n)]
                    face_groups.append(np.column_stack((np.full(len(inds),n),refs)).ravel())
        faces=np.concatenate(face_groups)
    return pv.PolyData(xyz,faces).clean()


def poly_surface(polys,values,axis,coord):
    if len(polys)!=len(values) or not len(values):raise ValueError("Empty native cut")
    pp=np.concatenate(polys);pts=np.insert(pp,axis,coord,axis=1)
    offset=0;faces=[]
    for p in polys:
        n=len(p);faces.extend([n,*range(offset,offset+n)]);offset+=n
    obj=pv.PolyData(pts,np.asarray(faces,int));obj.cell_data["scalar"]=values
    return obj


def plane(case,data,axis,coord):
    f=extract_slice(case,data,axis,coord);inds=f["offsets"];points=f["xy"]
    speed=np.sqrt(sum(f[k]**2 for k in ("u_m_s","v_m_s","w_m_s")))
    axes=f["projected_axes"]
    take=np.ones(len(speed),dtype=bool)
    for j,a in enumerate(axes):
        l,h=RANGE[2*a:2*a+2];take&=(np.minimum.reduceat(points[:,j],inds[:-1])<h)&(np.maximum.reduceat(points[:,j],inds[:-1])>l)
    selected=np.flatnonzero(take)
    obj=poly_surface([points[inds[i]:inds[i+1]] for i in selected],speed[selected],axis,coord)
    return obj.clip_box(RANGE,invert=False,crinkle=False)


def plotter(title):
    p=pv.Plotter(off_screen=True,window_size=(1420,1400));p.set_background("white")
    p.enable_ssao(radius=.15,bias=.003,kernel_size=32)
    p.enable_anti_aliasing("ssaa")
    if title:p.add_text(title,position="upper_left",font_size=18,color="#172733")
    return p


def add_body(p,airframe):
    p.add_mesh(airframe,color="#cbd3d7",smooth_shading=True,split_sharp_edges=True,show_edges=False,ambient=.36,diffuse=.64)


def scalarbar(label):
    return dict(title=label,color="#172733",vertical=False,position_x=.07,position_y=.03,width=.86,height=.085,
                label_font_size=15,title_font_size=16,fmt="%.2g",n_labels=5)


def shot(p,cam=CAM,scale=3.35):
    p.camera_position=cam;p.enable_parallel_projection();p.camera.parallel_scale=scale
    configure_pyvista(p)
    try:return p.screenshot(return_img=True)
    finally:p.close()


def save_view(number,images,evidence):
    paths=OUT;paths.mkdir(parents=True,exist_ok=True);EVIDENCE.mkdir(parents=True,exist_ok=True)
    merged=np.concatenate(images,axis=1)
    if merged.shape[0]<1080 or merged.shape[1]<1920:raise ValueError("Native comparison image is too small")
    image=Image.fromarray(merged);target=paths/(NAMES[number]+".png")
    pending=target.with_suffix(".pending.png");image.save(pending);pending.replace(target)
    inputs=(BASE,OGE) if number==11 else (VECTOR,case_names()[3])
    record=dict(engine="PyVista",published_sha256=digest(target),accepted_sources=[endpoint(n) for n in inputs],image=target.name,pixel_size=list(image.size),font="Times New Roman",**evidence)
    atomic_write_json(EVIDENCE/(NAMES[number]+".json"),record)


def compare_ground(stations=(.35,1.2,3.)):
    fields=[];cases=[]
    # Compare identical x planes and identical camera/limits on matched medium meshes.
    for name in [BASE,OGE]:
        _,case,data=accepted(name);cases.append((case,data))
        fields.append([plane(case,data,0,x) for x in stations])
    vmax=max(float(np.percentile(c.cell_data["scalar"],99)) for block in fields for c in block)
    images=[]
    for i,(case,data) in enumerate(cases):
        p=plotter(["a   Stationary runway (IGE)","b   Open lower boundary (OGE)"][i]);add_body(p,body(case))
        for j,obj in enumerate(fields[i]):
            p.add_mesh(obj,scalars="scalar",cmap=cm.batlow,clim=[0,max(vmax,1e-9)],opacity=.77,
                       scalar_bar_args=scalarbar("Speed (m/s)"),show_scalar_bar=j==0)
        images.append(shot(p))
    save_view(11,images,dict(native_files=[[str(a),str(b)] for a,b in cases],section_x_m=list(stations),
                            speed_range_m_s=[0,vmax],camera=CAM,definition="Matched starboard half-domain, three exact fluid cuts"))


def compare_highlift():
    _,case,data=accepted(VECTOR);rot=read_json(ROOT/"DELIVERABLES/data/actuator_disk_model.json")["rotors"][2]
    coord=rot["center_m"][2];native=plane(case,data,2,coord)
    name=case_names()[3];row,w,(polys,fields)=load_section(name,flow=True);chord=row["c_ref_m"]
    x0,x1=w.x_m.min()-.23*chord,w.x_m.max()+.46*chord;ym=.5*(w.y_m.min()+w.y_m.max())
    box=(x0,x1,ym-.36*chord,ym+.36*chord)
    keep=[i for i,g in enumerate(polys) if g[:,0].min()<=box[1] and g[:,0].max()>=box[0] and g[:,1].min()<=box[3] and g[:,1].max()>=box[2]]
    two=poly_surface([polys[i] for i in keep],np.hypot(fields["u_m_s"][keep],fields["v_m_s"][keep]),2,0.)
    two=two.clip_box((*box,-.05,.05),invert=False)
    vmax=max(np.percentile(obj.cell_data["scalar"],99) for obj in [native,two]);lims=[0,max(vmax,1e-9)]
    a=plotter("a   3D, HLP axes deflected 10 degrees");add_body(a,body(case))
    a.add_mesh(native,scalars="scalar",cmap=cm.batlow,clim=lims,opacity=.93,scalar_bar_args=scalarbar("Speed (m/s)"))
    b=plotter("b   2D, slat and 30-degree flap")
    b.add_mesh(two,scalars="scalar",cmap=cm.batlow,clim=lims,lighting=False,scalar_bar_args=scalarbar("Speed (m/s)"))
    xc=(x0+x1)*.5
    save_view(12,[shot(a),shot(b,[(xc,ym,3.),(xc,ym,0.),(0,1,0)],max((x1-x0)*.56,(box[3]-box[2])*.60))],
              dict(vector_case=str(case),vector_data=str(data),section_case=row["native_case"],section_data=row["native_data"],
                   HLP3_z_m=coord,speed_range_m_s=lims,section_viewport_xy_m=box,
                   definition="Separate 3D half-aircraft and 2D unit-depth native optimizations; common speed color range"))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("numbers",nargs="+",type=int,choices=list(NAMES))
    nums=parser.parse_args().numbers
    if 11 in nums:compare_ground()
    if 12 in nums:compare_highlift()
