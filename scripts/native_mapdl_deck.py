"""Assemble MAPDL commands for native SHELL181 pictures and independent field readback."""
import numpy as np

# Color indices 1..9 are assigned explicitly for the raster PNG device.
ENGINEERING = ["#153c68", "#245d89", "#337fab", "#61a2b0", "#a9ccc0",
               "#f1d895", "#edaa60", "#cd6549", "#8d3037"]
SIGNED = ["#22486d", "#356997", "#6b94b3", "#adc8d3", "#e4e9e5",
          "#dbc7b1", "#c49178", "#a46353", "#773a42"]
LABELS = ["MRED", "MAGE", "BMAG", "BLUE", "CBLU", "CYAN", "GCYA", "GREE", "YGRE"]
MARKER = "X57_NATIVE_POST1_RENDER_COMPLETE"

def fields_for_comparison(fields):
    shear = fields["top_bottom_local_shell_sxy_Pa"]
    selected = np.argmax(np.abs(shear), axis=1)
    return {
        "VMMPA": np.max(fields["top_bottom_vm_Pa"], axis=1) * 1e-6,
        "S1MPA": np.max(fields["top_bottom_S1_Pa"], axis=1) * 1e-6,
        "S3MPA": np.min(fields["top_bottom_S3_Pa"], axis=1) * 1e-6,
        "TRESCA": np.max(fields["top_bottom_tresca_max_shear_Pa"], axis=1) * 1e-6,
        "XYMPA": shear[np.arange(len(shear)), selected] * 1e-6,
        "FOSCAP": np.minimum(fields["safety_factor"], 20.0),
    }

def verify_readback(folder,fields):
    """Compare every plotted value and all three native displacement components."""
    paths=[folder/"element_readback.csv",folder/"node_readback.csv"]
    refs=[np.column_stack(list(fields_for_comparison(fields).values())),fields["displacement_vector_m"]]
    for path,reference in zip(paths,refs):
        values=np.loadtxt(path,delimiter=",",ndmin=2)
        if values.shape!=reference.shape or not np.allclose(values,reference,rtol=5e-8,atol=1e-12):
            raise ValueError(f"POST1 source readback disagrees with accepted signed RST export: {path}")
    return paths

def field_commands():
    lines = ["/CLEAR,NOSTART", "/NOPR", "/INPUT,model,inp", "/GOPR", "/POST1",
             "FILE,source,rst", "SET,LAST", "ALLSEL,ALL", "/GRAPHICS,FULL",
             "*GET,ECNT,ELEM,0,NUM,MAX", "*GET,NCNT,NODE,0,NUM,MAX"]
    for face, prefix in (("TOP", "T"), ("BOT", "B")):
        lines += ["SHELL," + face, "RSYS,0", f"ETABLE,{prefix}VM,S,EQV", "RSYS,SOLU"]
        for key, comp in (("P1","1"), ("P3","3"), ("XY","XY")):
            lines.append(f"ETABLE,{prefix}{key},S,{comp}")
    lines += ["RSYS,0", "SMAX,VMMPA,TVM,BVM,1E-6,1E-6",
              "SMAX,S1MPA,TP1,BP1,1E-6,1E-6", "SMIN,S3MPA,TP3,BP3,1E-6,1E-6",
              "SADD,TTR,TP1,TP3,5E-7,-5E-7", "SADD,BTR,BP1,BP3,5E-7,-5E-7",
              "SMAX,TRESCA,TTR,BTR", "SADD,XYMPA,TXY,,1E-6", "SADD,FOSCAP,VMMPA,,1"]
    for name in ["TOPXY","BOTXY","ABTOP","ABBOT","PICKT","PICKB","XTV","XBV","XOUT","VMVAL","VMDEN","FOSVAL"]:
        lines.append(f"*DIM,{name},ARRAY,ECNT")
    lines += ["*VGET,TOPXY(1),ELEM,1,ETAB,TXY", "*VGET,BOTXY(1),ELEM,1,ETAB,BXY",
              "*VFUN,ABTOP(1),ABS,TOPXY(1)", "*VFUN,ABBOT(1),ABS,BOTXY(1)",
              "*VOPER,PICKT(1),ABTOP(1),GE,ABBOT(1)", "*VOPER,PICKB(1),ABTOP(1),LT,ABBOT(1)",
              "*VOPER,XTV(1),PICKT(1),MULT,TOPXY(1)", "*VOPER,XBV(1),PICKB(1),MULT,BOTXY(1)",
              "*VFACT,1E-6", "*VOPER,XOUT(1),XTV(1),ADD,XBV(1)", "*VPUT,XOUT(1),ELEM,1,ETAB,XYMPA",
              "*VGET,VMVAL(1),ELEM,1,ETAB,VMMPA", "*VOPER,VMDEN(1),VMVAL(1),MAX,25.15",
              "*VOPER,FOSVAL(1),503,DIV,VMDEN(1)", "*VPUT,FOSVAL(1),ELEM,1,ETAB,FOSCAP"]
    keys = ["VMMPA","S1MPA","S3MPA","TRESCA","XYMPA","FOSCAP"]
    for i,key in enumerate(keys):
        lines.extend([f"*DIM,RE{i},ARRAY,ECNT",f"*VGET,RE{i}(1),ELEM,1,ETAB,{key}"])
    lines += ["*CFOPEN,element_readback,csv","*VWRITE,"+",".join(f"RE{i}(1)" for i in range(len(keys))),
              "(E18.10,5(',',E18.10))","*CFCLOS"]
    for i,axis in enumerate("XYZ"):
        lines.extend([f"*DIM,RU{i},ARRAY,NCNT",f"*VGET,RU{i}(1),NODE,1,U,{axis}"])
    return lines + ["*CFOPEN,node_readback,csv","*VWRITE,RU0(1),RU1(1),RU2(1)",
                    "(E18.10,2(',',E18.10))","*CFCLOS"]

def selection(mask):
    ids = np.flatnonzero(mask) + 1
    if len(ids) < 3:
        raise ValueError("Fewer than three elements in native plot region")
    runs = np.split(ids, np.flatnonzero(np.diff(ids) != 1) + 1)
    return ["ALLSEL,ALL","ESEL,NONE"] + [f"ESEL,A,ELEM,,{r[0]},{r[-1]}" for r in runs] + ["NSLE,S"]

def plot_deck(panels, masks):
    lines = field_commands()
    lines += ["/SHOW,PNG,,,8", "PNGR,COLOR,2","PNGR,ORIENT,HORIZONTAL","/GFILE,2400",
              "/RGB,INDEX,100,100,100,0","/RGB,INDEX,0,0,0,15","/TRIAD,OFF",
              "/PLOPTS,INFO,0","/PLOPTS,FRAME,0","/PLOPTS,TITLE,0","/PLOPTS,MINM,0",
              "/PLOPTS,LOGO,0","/EDGE,1,0","/TYPE,1,6","/DIST,1,AUTO"]
    for p in panels:
        lines.append(f"! X57_PANEL {p['number']} {p['field']} {p['region']}")
        lines += selection(masks[p["region"]])
        for index,(color,label) in enumerate(zip(p["palette"],LABELS),1):
            percentages = [int(color[j:j+2],16)*100/255 for j in (1,3,5)]
            rgb = ",".join(f"{v:.5f}" for v in percentages)
            lines += [f"/RGB,INDEX,{rgb},{index}",f"/COLOR,CNTR,{label},{index}"]
        lines += ["/COLOR,SMIN,"+LABELS[0],"/COLOR,SMAX,"+LABELS[-1]]
        view = ",".join(str(v) for v in p["view_vector"])
        lo, hi = np.asarray(p["color_limits"]) / p["label_multiplier"]
        lines += ["/AUTO,1", f"/VIEW,1,{view}", "/VUP,1,"+p["up"], "/VCONE,1,0",
                  f"/CONTOUR,1,9,{lo:.12g},,{hi:.12g}",
                  "/DSCALE,1,"+str(p.get("deformation_factor") or "OFF"),p["plot_command"]]
    return "\n".join(lines + ["/SHOW,CLOSE","/COM,"+MARKER,"FINISH","/EXIT,NOSAVE",""])
