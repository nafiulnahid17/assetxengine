"""AssetsX vectorization bridge: adapted from the user's Artboard AI code.

Provenance: nafiulnahid17/Artboard-AI---Resolution-Independent- (main, 2026-10-30)
app/pipeline/vectorization.py @ a5aa5cca, app/vector/contour.py @ 40497d79,
app/vector/vtracer_engine.py @ a129bb5f, and public artboardai-engine
artboard_engine/tracing.py @ ad7c50bd.

Changes: preserve original dimensions, strict output bounds, select regions, no fixed jersey
canvas, no hidden raster in SVG. Quality rules invariant across billing modes.
"""
from __future__ import annotations
import io
import math
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET
import cv2
import numpy as np
from PIL import Image
from defusedxml import ElementTree as SafeET
from .security import validate_svg

SVG = 'http://www.w3.org/2000/svg'
ET.register_namespace('', SVG)
NS = '{'+SVG+'}'
MAX_PATHS = 20000
MAX_ANCHORS = 800000


def _d(contour, epsilon: float) -> tuple[str,int]:
    if epsilon > 0:
        contour = cv2.approxPolyDP(contour, epsilon, True)
    points = contour.reshape(-1,2)
    if len(points) < 3:
        return '',0
    return 'M ' + ' L '.join(f'{float(x):.3f},{float(y):.3f}' for x,y in points) + ' Z',len(points)


def contour_trace(image: Image.Image, max_colors: int = 12, min_area: int = 24,
                  mono: bool = False, epsilon: float=0.7, selected_bounds=None) -> tuple[bytes, dict]:
    """Artboard contour.trace adapted to native dimensions and explicit alpha.

    RETR_CCOMP preserves holes using SVG evenodd paths; all output paths are editable.
    """
    arr=np.asarray(image.convert('RGBA'))
    alpha=arr[...,3]
    if mono:
        gray=cv2.cvtColor(arr[...,:3],cv2.COLOR_RGB2GRAY)
        _,ink=cv2.threshold(gray,0,255,cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
        labels=np.where((ink>0)&(alpha>8),0,-1)
        colors=[(0,'#000000')]
    else:
        q=image.convert('RGB').quantize(colors=max_colors,method=Image.Quantize.FASTOCTREE,
                                        dither=Image.Dither.NONE)
        labels=np.asarray(q).astype(np.int16)
        labels[alpha<=8]=-1
        rgb=q.getpalette()
        colors=[(int(ix),'#%02X%02X%02X'%tuple(rgb[int(ix)*3:int(ix)*3+3]))
                for ix in np.unique(labels) if ix>=0]
    root=ET.Element(NS+'svg',{'viewBox':f'0 0 {image.width} {image.height}',
                              'width':str(image.width),'height':str(image.height),'version':'1.1'})
    paths=anchors=0
    for ix,color in colors:
        mask=np.uint8(labels==ix)*255
        contours,hierarchy=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_NONE)
        if hierarchy is None: continue
        for i,c in enumerate(contours):
            if hierarchy[0,i,3]!=-1 or abs(cv2.contourArea(c)) < min_area: continue
            bbox=cv2.boundingRect(c)
            if selected_bounds and not any(_overlap(bbox, sb) for sb in selected_bounds):
                continue
            d,n=_d(c,epsilon)
            if not d:continue
            k=hierarchy[0,i,2]
            while k!=-1:
                if abs(cv2.contourArea(contours[k]))>=min_area:
                    hd,hn=_d(contours[k],epsilon)
                    if hd:
                        d+=' '+hd
                        n+=hn
                k=hierarchy[0,k,0]
            anchors+=n
            if paths>=MAX_PATHS or anchors>MAX_ANCHORS:
                raise ValueError('VECTOR_TOO_COMPLEX: trace exceeds path/anchor complexity limits')
            ET.SubElement(root,NS+'path',{'id':f'asset_{paths:05d}','fill':color,
                                           'fill-rule':'evenodd','d':d})
            paths+=1
    if paths<1:raise ValueError('VECTOR_EMPTY: no meaningful regions traced')
    result=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    validate_svg(result)
    return result, {'backend':'artboard_opencv_color_contours' if not mono else 'artboard_opencv_mono_contours',
                    'path_count':paths,'anchor_count':anchors,'embedded_rasters':0,
                    'alpha_preserved':True,'original_dimensions':[image.width,image.height],
                    'trace_note':'Raster-to-vector is an approximation, not recovery of original editable design layers.'}


def _overlap(b1,b2):
    x,y,w,h=b1; a,b,c,d=b2
    return max(x,a)<min(x+w,a+c) and max(y,b)<min(y+h,b+d)


def vtracer_trace(image:Image.Image, max_colors:int=12, timeout:int=60) -> tuple[bytes,dict]:
    """Artboard native vtracer worker model, with external timeout and bounded results."""
    try:import vtracer
    except ImportError as exc: raise RuntimeError('VTracer dependency not installed') from exc
    # VTracer encodes colors of opaque images; transparent assets use contour fallback
    # to avoid filling transparent holes with opaque background pixels.
    if image.convert('RGBA').getextrema()[3][0] < 255:
        raise RuntimeError('Transparent source: preserve alpha using contour tracing')
    with tempfile.TemporaryDirectory(prefix='assetsx-trace-') as td:
        t=Path(td); src=t/'source.png'; dst=t/'result.svg'
        work=image.copy(); work.thumbnail((2800,2800)); work.convert('RGB').save(src)
        cmd=[sys.executable,'-m','assetsx_engine.vtracer_worker',str(src),str(dst),str(max_colors)]
        subprocess.run(cmd,check=True,capture_output=True,timeout=timeout)
        if dst.stat().st_size>24*1024*1024:raise ValueError('Oversized vector result')
        root=SafeET.fromstring(dst.read_bytes())
        count=0
        for parent in root.iter():
            for node in list(parent):
                if node.tag.split('}')[-1]=='path' and not node.get('d','').strip(): parent.remove(node)
                elif node.tag.split('}')[-1]=='path':count+=1
        if count<1:raise ValueError('No traced vector paths')
        scale_x=image.width/work.width;scale_y=image.height/work.height
        if scale_x!=1 or scale_y!=1:
            grp=ET.Element(NS+'g',{'transform':f'scale({scale_x:.9f} {scale_y:.9f})'})
            for node in list(root):root.remove(node);grp.append(node)
            root.append(grp)
        root.set('viewBox',f'0 0 {image.width} {image.height}')
        root.set('width',str(image.width));root.set('height',str(image.height))
        data=ET.tostring(root,encoding='utf-8',xml_declaration=True)
        validate_svg(data)
        return data,{'backend':'artboard_vtracer','path_count':count,'embedded_rasters':0,
                     'original_dimensions':[image.width,image.height],
                     'trace_note':'Raster-to-vector approximates source; review brand and typography fidelity.'}


def vectorize(image:Image.Image,strategy:str='auto',max_colors:int=12,min_area:int=24,
              selected_bounds=None) -> tuple[bytes,dict]:
    if strategy not in {'auto','shapes','monochrome','multicolor','color_regions','existing_vector'}:
        raise ValueError('Unknown vectorization strategy')
    if strategy=='existing_vector':raise ValueError('Existing vector strategy only valid for SVG input')
    mono=strategy=='monochrome'
    # Precision paths, transparency and selection use Artboard contour engine.
    if strategy in ('multicolor','auto') and selected_bounds is None:
        try:return vtracer_trace(image,max_colors=max_colors)
        except (RuntimeError,ValueError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
            data,info=contour_trace(image,max_colors,min_area,mono=False,selected_bounds=selected_bounds)
            info['native_fallback_reason']=str(exc)[:220]
            return data,info
    return contour_trace(image,max_colors,min_area,mono=mono,selected_bounds=selected_bounds,
                         epsilon=.35 if strategy in ('shapes','monochrome') else .7)
