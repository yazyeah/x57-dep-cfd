"""Combine native MAPDL picture pixels and add engineering labels in Times New Roman."""
from PIL import Image, ImageDraw, ImageFont, ImageOps
import numpy as np
from publication_fonts import font_file

def read_native(path, panel):
    with Image.open(path) as source:
        if source.format != "PNG" or source.width < 1920 or source.height < 1080:
            raise ValueError(f"MAPDL native image is below the required resolution: {path}")
        image = source.convert("RGB")
    rgb = np.asarray(image)
    if min(rgb[0,0].min(),rgb[-1,-1].min(),rgb[0,-1].min(),rgb[-1,0].min()) < 247:
        raise ValueError(f"MAPDL background is not white: {path}")
    # Retrieve the geometry from the geometry-only viewport. All pixel values,
    # including the native undeformed overlay and element boundaries, are retained.
    ink = np.min(rgb, axis=2) < 243
    chroma = np.ptp(rgb, axis=2) > 13
    if np.count_nonzero(chroma) < .005*ink.size:
        raise ValueError(f"Blank or monochrome native contour: {path}")
    # Check the actual PNG device applied the requested palette before attaching
    # its calibrated legend. Hue differences are independent of surface lighting.
    sample=rgb[::5,::5].astype(float)
    vibrant=np.ptp(sample,axis=2)>28
    pixels=sample[vibrant]
    if len(pixels)<50:
        raise ValueError(f"Insufficient colored native pixels: {path}")
    pal=np.array([[int(c[j:j+2],16) for j in (1,3,5)] for c in panel["palette"]],dtype=float)
    def hue(values):
        return (values-values.min(axis=1)[:,None])/np.maximum(np.ptp(values,axis=1)[:,None],1.)
    hues=hue(pixels)
    d=np.min(np.linalg.norm(hues[:,None,:]-hue(pal)[None,:,:],axis=2),axis=1)
    if np.quantile(d,.80)>.19:
        raise ValueError(f"MAPDL native palette disagrees with declared legend: {path}")
    lo,hi=panel["color_limits"]
    actual=panel["actual_range"]
    indices=np.minimum(np.maximum(np.floor((np.asarray(actual)-lo)/(hi-lo)*9).astype(int),0),8)
    if indices[0]==indices[1]:
        single=np.linalg.norm(hues-hue(pal)[indices[0]],axis=1)
        if np.median(single)>.20:
            raise ValueError(f"Native colors disagree with the measured single-bin field: {path}")
    rows,cols = np.where(ink)
    if (rows.min() < 2 or cols.min() < 2 or
            rows.max() >= image.height-2 or cols.max() >= image.width-2):
        raise ValueError(f"Clipped geometry or unexpected MAPDL border: {path}")
    geometry = image.crop((int(cols.min()),int(rows.min()),int(cols.max()+1),int(rows.max()+1)))
    if panel["mirror_z0"]:
        if panel["up"] != "X" or panel["view_vector"][2] != 0:
            raise ValueError("A projected reflection requires the camera to lie in the symmetry plane")
        other = ImageOps.mirror(geometry)
        whole = Image.new("RGB",(2*geometry.width,geometry.height),"white")
        left,right = (other,geometry) if panel["view_vector"][1] > 0 else (geometry,other)
        whole.paste(left,(0,0)); whole.paste(right,(left.width,0))
        geometry = whole
    return geometry

def compose(panels,raw_files,name,peak,min_fos,umax):
    if len(panels)!=len(raw_files) or len(panels) not in (1,2):
        raise ValueError("Native plot count differs from the planned composite")
    w,h = 2400,1560
    canvas = Image.new("RGB",(w*len(panels),h),"white")
    draw = ImageDraw.Draw(canvas)
    title_font=ImageFont.truetype(str(font_file(True)),52)
    text_font=ImageFont.truetype(str(font_file()),38)
    foot_font=ImageFont.truetype(str(font_file()),32)
    draw.text((78,42),name,font=title_font,fill="#152734")
    for i,(panel,path) in enumerate(zip(panels,raw_files)):
        x0=i*w
        draw.text((x0+78,145),panel["label"],font=title_font,fill="#182e3b")
        picture=read_native(path,panel)
        # Never enlarge native raster data to reach the publication resolution.
        picture.thumbnail((w-136,945),Image.Resampling.LANCZOS)
        canvas.paste(picture,(x0+(w-picture.width)//2,220+(945-picture.height)//2))
        left,right=x0+180,x0+w-180
        y=1210
        for j,color in enumerate(panel["palette"]):
            draw.rectangle((left+(right-left)*j/9,y,left+(right-left)*(j+1)/9,y+34), fill=color)
        lo,hi=panel["color_limits"]
        for j in (0,3,6,9):
            t=j/9
            xx=left+(right-left)*t
            draw.line((xx,y+35,xx,y+48),fill="#1a2e37",width=2)
            draw.text((xx,y+50),format(lo+(hi-lo)*t,".4g"),font=foot_font,fill="black",anchor="mt")
        draw.text((x0+w//2,y+100),panel["unit_label"],font=text_font,fill="black",anchor="mt")
        draw.text((x0+78,1380),panel["note"],font=foot_font,fill="#263f4c")
    summary=(f"Global peak von Mises stress {peak:.4g} MPa     Minimum yield safety factor {min_fos:.4g}"
             f"     Maximum displacement {umax*1000:.4g} mm")
    draw.text((78,h-70),summary,font=text_font,fill="#182e3b")
    return canvas
