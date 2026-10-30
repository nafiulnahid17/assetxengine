"""Non-destructive raster edit commands and editable SVG node transformations.

Unknown/unimplemented operations are explicit errors, never silent no-ops.
"""
from __future__ import annotations
from io import BytesIO
from xml.etree import ElementTree as ET
import re
import numpy as np
import cv2
from PIL import Image,ImageDraw,ImageFont,ImageOps,ImageFilter
from defusedxml import ElementTree as SafeET
from .security import local,validate_svg
from .analysis import element_mask

SVG_NS='http://www.w3.org/2000/svg'


def color(value:str)->tuple[int,int,int,int]:
    if not re.fullmatch(r'#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?',value):
        raise ValueError('Color must be hexadecimal #RRGGBB or #RRGGBBAA')
    return tuple(bytes.fromhex(value[1:])) + ((255,) if len(value)==7 else ())


def edit_raster(img:Image.Image,edits:list,elements:list[dict]) -> tuple[Image.Image,list[str]]:
    out=img.convert('RGBA')
    warnings=[]
    byid={e['id']:e for e in elements}
    for op in edits:
        a=op.action if hasattr(op,'action') else op['action']
        ids=op.element_ids if hasattr(op,'element_ids') else op.get('element_ids',[])
        p=op.params if hasattr(op,'params') else op.get('params',{})
        if a in {'recolor','remove','opacity'}:
            if not ids:raise ValueError(a+' requires selected element IDs')
            if not all(i in byid for i in ids):raise ValueError('Unknown element ID; reanalyze after geometric editing')
            mask=Image.new('L',out.size,0)
            for k in ids:
                reg=element_mask(img,byid[k])
                # Element IDs computed from original image. Geometry transforms invalidate IDs.
                if reg.size!=mask.size:raise ValueError('Element geometry changed; select elements again')
                mask=Image.fromarray(np.maximum(np.asarray(mask),np.asarray(reg)).astype('uint8'),'L')
            arr=np.asarray(out).copy();sel=np.asarray(mask)>0
            if a=='recolor':
                c=color(str(p.get('color','#000000')));arr[sel,:3]=c[:3]
            if a=='remove':arr[sel,3]=0
            if a=='opacity':arr[sel,3]=(arr[sel,3].astype(float)*max(0,min(1,float(p.get('alpha',1))))).astype('uint8')
            out=Image.fromarray(arr,'RGBA')
        elif a=='crop':
            x,y,w,h=[int(p[k]) for k in ['x','y','width','height']]
            if min(w,h)<1 or min(x,y)<0 or x+w>out.width or y+h>out.height:raise ValueError('Invalid crop bounds')
            out=out.crop((x,y,x+w,y+h))
        elif a=='resize':
            w,h=int(p['width']),int(p['height'])
            if w<1 or h<1 or w*h>16_000_000:raise ValueError('Unsafe output dimensions')
            out=out.resize((w,h),Image.Resampling.LANCZOS)
        elif a=='rotate':out=out.rotate(float(p.get('degrees',0)),expand=bool(p.get('expand',True)),resample=Image.Resampling.BICUBIC)
        elif a=='flip':out=ImageOps.mirror(out) if p.get('axis','horizontal')=='horizontal' else ImageOps.flip(out)
        elif a=='background_change':
            bg=Image.new('RGBA',out.size,color(str(p['color'])));bg.alpha_composite(out);out=bg
        elif a=='background_remove':
            arr=np.asarray(out).copy();threshold=float(p.get('threshold',25))
            if not 0<=threshold<=200:raise ValueError('Invalid threshold')
            corner=np.median(np.array([arr[0,0,:3],arr[0,-1,:3],arr[-1,0,:3],arr[-1,-1,:3]]),axis=0)
            dist=np.linalg.norm(arr[:,:,:3].astype(float)-corner,axis=2)
            arr[dist<threshold,3]=0
            out=Image.fromarray(arr,'RGBA')
            warnings.append('Background removal is simple corner-color keying, not semantic segmentation; inspect complex edges')
        elif a=='enhance':
            from PIL import ImageEnhance
            out=ImageEnhance.Contrast(out).enhance(float(p.get('contrast',1.1)))
            out=ImageEnhance.Sharpness(out).enhance(float(p.get('sharpness',1.2)))
        elif a in {'add_text','add_shape'}:
            layer=Image.new('RGBA',out.size);draw=ImageDraw.Draw(layer)
            if a=='add_text':
                text=str(p.get('text',''))
                if len(text)>400 or not text:raise ValueError('Text must be 1..400 characters')
                fsize=int(p.get('size',48)); fsize=max(4,min(fsize,400))
                # Use supplied permitted installed system font only, not arbitrary user disk path.
                font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',fsize)
                draw.text((int(p.get('x',0)),int(p.get('y',0))),text,font=font,fill=color(str(p.get('color','#000000'))))
                warnings.append('Raster text was drawn with DejaVu Sans; editable font layer not recovered from raster')
            else:
                x,y,w,h=[int(p[k]) for k in ['x','y','width','height']]
                if min(w,h)<1:raise ValueError('Invalid shape size')
                shape=str(p.get('shape','rectangle'))
                bounds=(x,y,x+w,y+h)
                if shape=='rectangle':draw.rectangle(bounds,fill=color(str(p.get('color','#000000'))))
                elif shape=='ellipse':draw.ellipse(bounds,fill=color(str(p.get('color','#000000'))))
                else:raise ValueError('Unsupported added shape')
            out.alpha_composite(layer)
        else:
            raise ValueError(f'Editing operation not implemented: {a}')
    return out,warnings


def edit_svg(raw:bytes,edits:list,elements:list[dict],selected:list[str]|None=None)->tuple[bytes,list[str]]:
    """Preserve native vector nodes; element edits select exact node indexes from analysis."""
    validate_svg(raw)
    root=SafeET.fromstring(raw)
    nodes=list(root.iter());byid={e['id']:e for e in elements}
    warnings=[]
    parent={child:n for n in root.iter() for child in n}
    for op in edits:
        a=op.action if hasattr(op,'action') else op['action']
        ids=op.element_ids if hasattr(op,'element_ids') else op.get('element_ids',[])
        p=op.params if hasattr(op,'params') else op.get('params',{})
        if a not in {'recolor','remove','opacity','replace_text','rotate','move','add_text','add_shape'}:
            raise ValueError(f'Editing operation not implemented for native SVG: {a}')
        if a in {'add_text','add_shape'}:
            if a=='add_text':
                n=ET.SubElement(root,'{'+SVG_NS+'}text',{'x':str(float(p.get('x',0))),
                   'y':str(float(p.get('y',30))),'fill':str(p.get('color','#000000')),
                   'font-size':str(float(p.get('size',30)))})
                n.text=str(p.get('text',''))[:400]
                warnings.append('Added text remains live SVG text; font availability may vary')
            else:
                ET.SubElement(root,'{'+SVG_NS+'}rect',{'x':str(float(p.get('x',0))),
                   'y':str(float(p.get('y',0))),'width':str(float(p.get('width',100))),
                   'height':str(float(p.get('height',100))),'fill':str(p.get('color','#000000'))})
            continue
        if not ids:raise ValueError(a+' requires element IDs')
        if not all(i in byid for i in ids):raise ValueError('Unrecognized SVG element ID')
        for identifier in ids:
            item=byid[identifier];n=nodes[item['node_index']]
            if a=='recolor':n.set('fill',str(p.get('color','#000000')))
            if a=='remove':
                if n not in parent:raise ValueError('Cannot remove SVG root')
                parent[n].remove(n)
            if a=='opacity':n.set('opacity',str(max(0,min(1,float(p.get('alpha',1))))))
            if a=='replace_text':
                if local(n.tag)!='text':raise ValueError('replace_text requires SVG text element')
                n.text=str(p.get('text',''))[:400]
            if a=='rotate':n.set('transform',(n.get('transform','')+' rotate('+str(float(p.get('degrees',0)))+')').strip())
            if a=='move':n.set('transform',(n.get('transform','')+' translate('+str(float(p.get('dx',0)))+' '+str(float(p.get('dy',0)))+')').strip())
    encoded=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    validate_svg(encoded)
    return encoded,warnings
