"""Prepare the five 2D HLP-3 section meshes. Coordinates and dimensions are in metres."""
import argparse
import json
from pathlib import Path
from collections import defaultdict
import numpy as np
from scipy.interpolate import PchipInterpolator

ROOT=Path(__file__).resolve().parents[1]
CASES=("opt2d_01_clean","opt2d_02_flap15","opt2d_03_flap30","opt2d_04_slat_flap30","opt2d_05_camber_opt")


def section_envelope():
    audit=json.loads((ROOT/"01_geometry/geometry_audit.json").read_text())
    rotor=audit["starboard_propellers_detected"][2]
    z=rotor["z_axis_m"]
    tags=json.loads((ROOT/"01_geometry/cad_component_regions.json").read_text())
    with np.load(ROOT/"01_geometry/cad_components.npz") as f:
        tri=np.concatenate([f[k] for k,v in tags.items() if v=="wall_wing"]).astype(float)
    seg=[]
    for face in tri[(tri[:,:,2].min(1)<z)&(tri[:,:,2].max(1)>=z)]:
        nxt=np.roll(face,-1,axis=0)
        mask=(face[:,2]<z)!=(nxt[:,2]<z)
        a,b=face[mask],nxt[mask]
        seg.append((a+(b-a)*((z-a[:,2])/(b[:,2]-a[:,2]))[:,None])[:,:2])
    a,b=np.asarray(seg).transpose(1,0,2)
    xmin=min(a[:,0].min(),b[:,0].min()); xmax=max(a[:,0].max(),b[:,0].max())
    chord=xmax-xmin
    xi=(1-np.cos(np.linspace(.00005,np.pi-.00005,161)))/2
    upper=[];lower=[]
    for station in xi:
        x=xmin+station*chord
        mask=(a[:,0]<x)!=(b[:,0]<x)
        ta,tb=a[mask],b[mask]
        y=ta[:,1]+(tb[:,1]-ta[:,1])*(x-ta[:,0])/(tb[:,0]-ta[:,0])
        upper.append(y.max());lower.append(y.min())
    xi[0]=0;xi[-1]=1
    u,l=PchipInterpolator(xi,upper),PchipInterpolator(xi,lower)
    return xmin,chord,u,l,rotor


def ring_points(surfaces):
    upper, lower = surfaces
    return np.concatenate((upper, lower[::-1], upper[:1]))


def boundary_distance(first, second):
    """Minimum distance between closed section polylines, including intersecting segments."""
    a, u = first[:-1, None, :], np.diff(first, axis=0)[:, None, :]
    b, v = second[None, :-1, :], np.diff(second, axis=0)[None, :, :]
    cross = lambda i, j: i[..., 0]*j[..., 1] - i[..., 1]*j[..., 0]
    det = cross(u, v)
    with np.errstate(divide="ignore", invalid="ignore"):
        t, w = cross(b-a, v)/det, cross(b-a, u)/det
    if np.any((t>=0) & (t<=1) & (w>=0) & (w<=1)):
        return 0.
    def point_edges(point, base, direction):
        d = point-base
        length2 = np.sum(direction**2, axis=-1, keepdims=True)
        k = np.divide(np.sum(d*direction, axis=-1, keepdims=True), length2,
                      out=np.zeros_like(d[..., :1]), where=length2>0)
        return np.linalg.norm(d - np.clip(k, 0., 1.)*direction, axis=-1).min()
    return min(point_edges(a,b,v),point_edges(b,a,u))


def deploy_flap(main, flap, chord):
    from scipy.optimize import brentq
    main_ring, flap_ring = ring_points(main), ring_points(flap)
    dx = main_ring[:,0].max() - .01*chord - flap_ring[:,0].min()
    def error(dy):
        return boundary_distance(main_ring, flap_ring+[dx,dy]) - .02*chord
    # Approach from below to select the deployed flap on the pressure side.
    lower = -.4*chord
    for upper in np.linspace(lower, .1*chord, 51)[1:]:
        if error(upper) <= 0:
            shift = [dx, brentq(error, lower, upper, xtol=1.e-12)]
            return tuple(side+shift for side in flap)
        lower = upper
    raise ValueError("Cannot place the flap at the specified physical slot gap and overlap")


def elements(case):
    xmin,c,u,l,rotor=section_envelope()
    def element(a,b,mode,angle=0.,shift=(0.,0.)):
        x=a+(b-a)*(1-np.cos(np.linspace(0,np.pi,81)))/2
        mid=(u(x)+l(x))/2
        half=(u(x)-l(x))/2
        if a>0:
            # Rounded leading edge at the cut, matched to the CAD thickness downstream.
            t=np.clip((x-a)/min(.045,(b-a)/4),0,1)
            half*=np.sqrt(t*(2-t))
        if b<1:
            t=np.clip((b-x)/min(.065,(b-a)/4),0,1)
            half*=t*(2-t)
        if mode=="camber":
            mid+=.03*c*4*x*(1-x)
        def surface(sign):
            xx=xmin+c*x; yy=mid+sign*half
            if mode=="plain":
                ramp=np.clip((x-.73)/.04,0,1)
                rot=-np.deg2rad(15)*(ramp*ramp*(3-2*ramp))
                pivot=.75
            else:
                rot=np.deg2rad(angle); pivot=a if a else b
            x0=xmin+pivot*c; y0=float((u(pivot)+l(pivot))/2)
            return np.c_[x0+np.cos(rot)*(xx-x0)-np.sin(rot)*(yy-y0)+shift[0]*c,
                         y0+np.sin(rot)*(xx-x0)+np.cos(rot)*(yy-y0)+shift[1]*c]
        return surface(1),surface(-1)
    if case==CASES[0]: parts={"main":element(0,1,"clean")}
    elif case==CASES[1]: parts={"main":element(0,1,"plain")}
    elif case==CASES[-1]: parts={"main":element(0,1,"camber")}
    else:
        slat=case==CASES[3]
        parts={"main":element(.15 if slat else 0,.75,"main")}
        parts["flap"]=deploy_flap(parts["main"],element(.75,1,"slotted",-30),c)
        if slat:
            # In x-aft, y-up coordinates positive rotation lowers the leading edge.
            parts["slat"]=element(0,.15,"slat",20,(-.024,.017))
    return xmin,c,rotor,parts


def write_fluent(path, model, zones):
    nodes,xyz,_=model.mesh.getNodes()
    order=np.argsort(nodes); nodes=nodes[order]; xyz=xyz.reshape(-1,3)[order,:2]
    kinds,_,groups=model.mesh.getElements(2)
    # Gmsh can also return unused geometric control-point nodes from fitted splines.
    used=np.unique(np.concatenate(groups))
    keep=np.searchsorted(nodes,used)
    if np.any(nodes[keep]!=used):raise ValueError("2D nodes missing from Gmsh coordinates")
    xyz=xyz[keep];nodes=used
    cells=[];kinds_out=[]
    for kind,flat in zip(kinds,groups):
        width={2:3,3:4}[int(kind)]
        ids=np.searchsorted(nodes,flat.reshape(-1,width))+1
        xy=xyz[ids-1]
        area=np.sum(xy[:,:,0]*np.roll(xy[:,:,1],-1,axis=1)-xy[:,:,1]*np.roll(xy[:,:,0],-1,axis=1),axis=1)
        if np.any(area<=0): raise ValueError("Nonpositive cell area")
        cells.extend(ids.tolist()); kinds_out.extend([1 if width==3 else 3]*len(ids))
    edge_labels={}
    for zone,curves in zones.items():
        for curve in curves:
            _,_,conn=model.mesh.getElements(1,curve)
            for block in conn:
                for a,b in (np.searchsorted(nodes,block.reshape(-1,2))+1).tolist():
                    edge_labels[tuple(sorted((a,b)))]=zone
    edges={}
    for i,cell in enumerate(cells,1):
        for a,b in zip(cell,cell[1:]+cell[:1]):
            key=tuple(sorted((a,b)))
            if key in edges:
                e=edges[key]
                if (e[0],e[1])!=(b,a) or e[3]: raise ValueError("Inconsistent interior edge")
                e[3]=i
            else: edges[key]=[a,b,i,0]
    by_zone=defaultdict(list)
    for k,e in edges.items():
        by_zone["interior" if e[3] else edge_labels[k]].append(e)
    with path.open("w",encoding="ascii",newline="\n") as f:
        f.write(f'(0 "2D HLP-3 airfoil grid")\n(2 2)\n(10 (0 1 {len(xyz):x} 0 2))\n(10 (1 1 {len(xyz):x} 1 2)(\n')
        np.savetxt(f,xyz,fmt="%.13g")
        f.write(f'))\n(12 (0 1 {len(cells):x} 0))\n(12 (2 1 {len(cells):x} 1 0)(\n')
        for start in range(0,len(cells),256):
            f.write(" ".join(map(str,kinds_out[start:start+256]))+"\n")
        f.write(f'))\n(45 (2 fluid air)())\n(13 (0 1 {len(edges):x} 0))\n')
        first=1
        for zid,(zone,faces) in enumerate(by_zone.items(),3):
            typ,code={"interior":("interior",2),"inlet":("velocity-inlet",10),
                      "outlet":("pressure-outlet",5),"ambient_top":("pressure-inlet",4)}.get(zone,("wall",3))
            if zone.startswith("inlet_"): typ,code="velocity-inlet",10
            last=first+len(faces)-1
            f.write(f'(13 ({zid:x} {first:x} {last:x} {code:x} 2)(\n')
            np.savetxt(f,np.array(faces),fmt="%x %x %x %x")
            f.write(f'))\n(45 ({zid} {typ} {zone})())\n')
            first=last+1
    return {"cells":len(cells),"nodes":len(nodes),"triangles":kinds_out.count(1),"quadrilaterals":kinds_out.count(3),
            "boundary_edges":{k:len(v) for k,v in by_zone.items() if k!="interior"}}


def generate(case,scale,inlet,folder=None,first_height=5.e-6):
    import gmsh
    xmin,c,rotor,parts=elements(case)
    folder=ROOT/"02_mesh"/case if folder is None else Path(folder)
    folder.mkdir(exist_ok=True,parents=True)
    gmsh.initialize([],readConfigFiles=False)
    try:
        gmsh.option.setNumber("General.Terminal",0)
        gmsh.model.add(case);g=gmsh.model.geo
        left=rotor["x_disk_m"]+.04
        right=xmin+9*c
        yc=rotor["y_axis_m"]
        box=[(left,-1.70),(right,-1.70),(right,yc+7*c),(left,yc+7*c)]
        corners=[g.addPoint(x,y,0,.12*scale) for x,y in box]
        if abs(inlet["plane_x_m"]-left)>1.e-8 or abs(inlet["station_z_m"]-rotor["z_axis_m"])>1.e-8:
            raise ValueError("Inlet coordinates do not match the requested HLP station.")
        lines=[g.addLine(corners[i],corners[i+1]) for i in range(3)]
        zones={k:[v] for k,v in zip(["ground","outlet","ambient_top"],lines)}
        bands=inlet["open_bands"]
        if not bands or abs(bands[0]["bottom_m"]-box[0][1])>1.e-7 or abs(bands[-1]["top_m"]-box[-1][1])>1.e-7:
            raise ValueError("Native inlet profile does not cover the outer flow boundaries.")
        ys=sorted(set([segment[key] for segment in bands for key in ("bottom_m","top_m")]),reverse=True)
        pts=[corners[3]]+[g.addPoint(left,y,0,.007*scale) for y in ys[1:-1]]+[corners[0]]
        for a,b,upper_y,lower_y in zip(pts[:-1],pts[1:],ys[:-1],ys[1:],strict=True):
            y=(upper_y+lower_y)/2
            band=next((item for item in bands if item["bottom_m"]<=y<=item["top_m"]),None)
            line=g.addLine(a,b);lines.append(line)
            zones.setdefault(band["zone"] if band else "spinner_mask",[]).append(line)
        holes=[g.addCurveLoop(lines)]
        walls=[]
        for label,(upper,lower) in parts.items():
            top=upper[::2];bottom=lower[::-2]
            def add_point(q):
                return g.addPoint(q[0],q[1],0,.0025*scale)
            upper_ids=[add_point(q) for q in top]
            # Preserve the CAD's finite trailing-edge thickness and close it with a face.
            rear=upper_ids[-1] if np.linalg.norm(top[-1]-bottom[0])<1.e-7 else add_point(bottom[0])
            nose=upper_ids[0] if np.linalg.norm(top[0]-bottom[-1])<1.e-7 else add_point(bottom[-1])
            lower_ids=[rear]+[add_point(q) for q in bottom[1:-1]]+[nose]
            curves=[g.addSpline(upper_ids)]
            if rear!=upper_ids[-1]:
                curves.append(g.addLine(upper_ids[-1],rear))
            curves.append(g.addSpline(lower_ids))
            if nose!=upper_ids[0]:
                curves.append(g.addLine(nose,upper_ids[0]))
            holes.append(g.addCurveLoop(curves));zones["wall_"+label]=curves;walls.extend(curves)
        g.addPlaneSurface(holes);g.synchronize()
        field=gmsh.model.mesh.field
        bl=field.add("BoundaryLayer")
        field.setNumbers(bl,"CurvesList",walls)
        for name,value in [("Size",first_height),("SizeFar",.003*scale),("Ratio",1.14),("Thickness",.005*c),("Quads",1)]:
            field.setNumber(bl,name,value)
        field.setAsBoundaryLayer(bl)
        dist=field.add("Distance");field.setNumbers(dist,"CurvesList",walls);field.setNumber(dist,"Sampling",300)
        thr=field.add("Threshold");field.setNumber(thr,"InField",dist)
        for k,v in [("SizeMin",.0026*scale),("SizeMax",.12*scale),("DistMin",.025*c),("DistMax",1.8*c)]:
            field.setNumber(thr,k,v)
        wake=field.add("Box")
        for k,v in [("XMin",left),("XMax",xmin+3*c),("YMin",yc-.50*c),("YMax",yc+.50*c),("VIn",.008*c*scale),("VOut",.12*scale)]:
            field.setNumber(wake,k,v)
        mx=field.add("Min");field.setNumbers(mx,"FieldsList",[thr,wake]);field.setAsBackgroundMesh(mx)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary",0)
        gmsh.model.mesh.generate(2)
        staging=folder/"section.pending.msh"
        stats=write_fluent(staging,gmsh.model,zones)
        if not stats["quadrilaterals"]:raise ValueError("No boundary-layer quads.")
        if not 60000 <= stats["cells"] <= 120000:
            staging.unlink()
            return stats
        staging.replace(folder/"section.msh")
        meta={"case":case, "inlet_profile":inlet,
              "inlet_mean_speed_m_s":inlet["inlet_mean_speed_m_s"],"section_z_m":rotor["z_axis_m"],"chord_m":c,"x_le_m":xmin,"inlet_x_m":left,
              "first_cell_height_target_m":first_height,"mesh_size_scale":scale,"stats":stats,
              "source":"https://ntrs.nasa.gov/citations/20180003474",
              "assumptions":"25%-chord flap at 30 deg follows NASA design parameters. Slotted nose, cove, translations, slat geometry and continuous 15-deg hinge are coursework design assumptions. Each section uses the CAD chordwise envelope; slot geometry is not manufacturer CAD."}
        if "flap" in parts:
            main, flap = ring_points(parts["main"]), ring_points(parts["flap"])
            meta["flap_slot_gap_over_c"] = boundary_distance(main,flap)/c
            meta["flap_overlap_over_c"] = (main[:,0].max()-flap[:,0].min())/c
        if "slat" in parts:
            meta.update(slat_reference_chord_fraction=.15,slat_downward_deployment_deg=20)
        (folder/"section_config.json").write_text(json.dumps(meta,indent=2),encoding="utf-8");print(case,stats,flush=True)
        return stats
    finally: gmsh.finalize()


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("case",choices=CASES)
    ap.add_argument("--scale",type=float,default=1.)
    ap.add_argument("--first-height",type=float,default=5.e-6)
    ap.add_argument("--inlet",required=True,type=Path,help="Native fine_rpm100 HLP-3 inlet.json")
    args=ap.parse_args()
    inlet=json.loads(args.inlet.read_text(encoding="utf-8-sig"))
    if inlet.get("source_case_id")!="fine_rpm100":
        ap.error("A verified fine_rpm100 profile is required for production.")
    import subprocess, sys
    if min(args.scale,args.first_height)<=0:
        ap.error("Both mesh scale and first height must be positive.")
    def gate():
        code=subprocess.call([sys.executable,"-B",str(ROOT/"scripts/control_gate.py"),"check"])
        if code:raise SystemExit(code)
    scale=args.scale
    for trial in range(6):
        gate()
        result=generate(args.case,scale,inlet,first_height=args.first_height)
        gate()
        if 60000<=result["cells"]<=120000:
            break
        print(f"Mesh trial {trial+1}: {result['cells']} cells; adjusting scale.",flush=True)
        scale*=np.clip((result["cells"]/95000.)**.6,.50,1.90)
    else:
        raise RuntimeError("Could not reach the 60,000–120,000 2D grid budget")
