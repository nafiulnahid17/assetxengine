"""Deterministic asset classification, SVG node discovery, and raster component isolation."""
from __future__ import annotations
from collections import Counter
from io import BytesIO
from dataclasses import dataclass
import cv2
import numpy as np
from PIL import Image
from defusedxml import ElementTree as SafeET
from .security import local

SVG_EDITABLE = {"path","rect","circle","ellipse","polygon","polyline","line","text"}


def palette(image: Image.Image, n: int = 12) -> list[str]:
    im = image.copy().convert("RGBA")
    im.thumbnail((450,450))
    arr = np.asarray(im)
    valid = arr[arr[:,:,3] > 30][:,:3]
    if len(valid) == 0:
        return []
    # 32-level bins make this resistant to antialiasing noise.
    bucket = (valid // 32 * 32 + 16).astype(np.uint8)
    freq = Counter(map(tuple, bucket.tolist()))
    return ["#%02X%02X%02X" % rgb for rgb,_ in freq.most_common(n)]


def extract_svg_elements(data: bytes) -> list[dict]:
    root = SafeET.fromstring(data)
    elements = []
    for index, node in enumerate(root.iter()):
        kind = local(node.tag)
        if kind not in SVG_EDITABLE:
            continue
        item_id = node.get("id") or f"assetx_{index}"
        elements.append({"id":f"svg:{index}","source_id":item_id,"node_index":index,"kind":kind,
                         "fill":node.get("fill"),"stroke":node.get("stroke"),
                         "text":(node.text or "").strip() if kind == "text" else None})
    return elements[:5000]


def _labels_and_mask(image: Image.Image, colors: int = 12):
    arr = np.asarray(image.convert("RGBA"))
    img = Image.fromarray(arr[:,:,:3],"RGB")
    q = img.quantize(colors=colors,method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    labels = np.asarray(q)
    rgb_palette=q.getpalette()
    return labels, arr[:,:,3], rgb_palette


def separate(image: Image.Image, colors: int=12, min_area: int=24, limit: int=256) -> list[dict]:
    w,h=image.size
    downscale=min(1.0, 1600 / max(w,h))
    if downscale < 1:
        small=image.resize((max(1,round(w*downscale)),max(1,round(h*downscale))), Image.Resampling.NEAREST)
    else: small=image
    labels, alpha, rgb = _labels_and_mask(small,colors=colors)
    elements=[]
    for ix in np.unique(labels):
        mask=np.uint8((labels==ix) & (alpha>24))
        count, lab, stats, cents=cv2.connectedComponentsWithStats(mask, connectivity=8)
        color=rgb[int(ix)*3:int(ix)*3+3]
        if len(color)!=3: continue
        hexcolor="#%02X%02X%02X"%tuple(color)
        for n in range(1,count):
            x,y,ww,hh,area=map(int,stats[n])
            if area < max(1, round(min_area*downscale*downscale)):
                continue
            box=[round(x/downscale),round(y/downscale),round(ww/downscale),round(hh/downscale)]
            elements.append({"id":f"raster:{int(ix)}:{n}","kind":"color_region","color":hexcolor,
                             "bounds":box,"area":round(area/(downscale**2)),"mask_color_index":int(ix),
                             "component_index":int(n),"confidence":None})
    elements.sort(key=lambda e:e['area'], reverse=True)
    return elements[:limit]


def element_mask(image: Image.Image, elem: dict, colors:int=12) -> Image.Image:
    """Recover selected connected region; same quantization as separate()."""
    from PIL import Image
    labels, alpha, _ = _labels_and_mask(image,colors=colors)
    i=int(elem["mask_color_index"])
    base=np.uint8((labels==i) & (alpha>24))
    count, lab, stats,_=cv2.connectedComponentsWithStats(base,connectivity=8)
    n=int(elem["component_index"])
    if n<1 or n>=count:
        # High-resolution labels can differ from downsampled labels: select geometric bbox.
        x,y,w,h=elem['bounds']; out=np.zeros_like(base)
        out[y:y+h,x:x+w]=base[y:y+h,x:x+w]
        return Image.fromarray(out*255, mode='L')
    return Image.fromarray(np.uint8(lab==n)*255,mode='L')


def classify(origin:str, img:Image.Image, elements:list, name:str="") -> str:
    if origin=="vector_svg":
        types={e["kind"] for e in elements}
        if "text" in types: return "text/wordmark or mixed vector"
        return "existing_vector"
    if origin in {"vector_pdf_mixed","eps_raster_import"}: return "existing_vector_or_mixed"
    colors=len(palette(img, 32))
    w,h=img.size
    if name.lower().endswith((".jpg",".jpeg")) and colors>16: return "photograph"
    if colors<=4: return "logo_icon_or_line_art"
    if w/h > 3: return "wordmark_or_banner"
    if colors>18: return "illustration_or_photograph"
    return "mixed_graphic"


def ocr(image: Image.Image) -> list[dict]:
    """Optional local OCR: no auto-font-match claims. Bounding boxes are approximate."""
    try:
        import pytesseract
        d=pytesseract.image_to_data(image.convert("RGB"), output_type=pytesseract.Output.DICT, timeout=15)
        output=[]
        for i,t in enumerate(d["text"]):
            if t.strip() and float(d['conf'][i])>25:
                output.append({"text":t,"bounds":[d[k][i] for k in ('left','top','width','height')],"confidence":float(d['conf'][i])/100})
        return output[:150]
    except (ImportError, OSError, RuntimeError):
        return []
