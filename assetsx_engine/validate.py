"""Artboard SVG preflight adapted for safe true-vector export; never certify Illustrator without testing it."""
import re
import math
from collections import Counter
from defusedxml import ElementTree as SafeET
from .security import local, validate_svg

NUMBER=re.compile(r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?')
ACCEPTED={'svg','g','defs','title','desc','metadata','path','circle','ellipse','rect','line',
          'polygon','polyline','text','tspan','linearGradient','radialGradient','stop','pattern','clipPath','mask'}

def validate_vector(data:bytes, *, strict:bool=True)->dict:
    errors=[];warnings=[]
    try:
        validate_svg(data)
        root=SafeET.fromstring(data)
    except Exception as exc:
        return {'true_vector':False,'valid_svg':False,'errors':[str(exc)],'status':'INVALID_VECTOR'}
    tags=Counter(local(e.tag) for e in root.iter())
    for node in root.iter():
        t=local(node.tag)
        if t not in ACCEPTED:errors.append('Unsupported node: '+t)
        if t=='path':
            d=node.get('d','')
            if not d or not re.match(r'^\s*[Mm]',d):errors.append('Invalid path')
            tokens=NUMBER.findall(d)
            try:
                if any(not math.isfinite(float(x)) or abs(float(x))>1e8 for x in tokens):errors.append('Nonfinite geometry')
            except ValueError:errors.append('Invalid path number')
        if t=='text':warnings.append('Live SVG text uses system font; outline conversion recommended before printing')
    meaningful=sum(tags[k] for k in ['path','circle','ellipse','rect','line','polygon','polyline','text'])
    if meaningful<1:errors.append('No meaningful vector shapes')
    return {'valid_svg':not errors,'true_vector':not errors,'status':'TRUE_VECTOR' if not errors else 'INVALID_VECTOR',
            'path_count':tags['path'],'shape_count':meaningful,'text_count':tags['text'],
            'gradient_count':tags['linearGradient']+tags['radialGradient'],
            'pattern_count':tags['pattern'],'embedded_raster_count':0,
            'errors':errors,'warnings':sorted(set(warnings)),
            'illustrator_compatibility':'UNVERIFIED_DESKTOP_APPLICATION',
            'strict':strict}
