"""Deterministic export and Artboard-inspired strict SVG preflight.

No file with a .ai suffix is generated: true native .ai requires Illustrator.
"""
from __future__ import annotations
from io import BytesIO
from pathlib import Path
import json
import subprocess
import zipfile
import cairosvg
from PIL import Image
from .validate import validate_vector

FORMATS={'png','transparent_png','svg','eps','pdf','ai_handoff','zip','report','text_outlines'}

def _inkscape(svg:Path,out:Path,fmt:str):
    try:
        subprocess.run(['inkscape',str(svg),'--export-type='+fmt,'--export-filename='+str(out)],
                       check=True,timeout=90,capture_output=True)
    except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
        raise RuntimeError('Inkscape conversion failed; EPS not available') from exc
    if not out.is_file() or out.stat().st_size<20:raise RuntimeError('Empty Inkscape export')


def export(output_dir:Path, image:Image.Image,svg:bytes,requested:list[str],report:dict) -> list[str]:
    if not set(requested)<=FORMATS:
        raise ValueError('Unsupported export requested')
    report['vector_validation']=validate_vector(svg)
    if not report['vector_validation']['true_vector']:
        raise ValueError('True-vector preflight failed')
    output_dir.mkdir(parents=True,exist_ok=True)
    out=output_dir/'asset.svg';out.write_bytes(svg)
    results=['asset.svg']
    if 'png' in requested:
        a=Image.new('RGBA',image.size,'white');a.alpha_composite(image.convert('RGBA'))
        a.convert('RGB').save(output_dir/'modified.png',optimize=True);results.append('modified.png')
    if 'transparent_png' in requested:
        image.convert('RGBA').save(output_dir/'transparent.png',optimize=True);results.append('transparent.png')
    if 'pdf' in requested:
        try:cairosvg.svg2pdf(bytestring=svg,write_to=str(output_dir/'asset.pdf'))
        except Exception as exc:raise RuntimeError('PDF export failed') from exc
        results.append('asset.pdf')
    if 'eps' in requested:
        _inkscape(out,output_dir/'asset.eps','eps');results.append('asset.eps')
    if 'ai_handoff' in requested:
        (output_dir/'ILLUSTRATOR_HANDOFF.txt').write_text(
            'This is not a native Adobe .ai file. Open asset.svg/asset.eps in Adobe Illustrator; '
            'review text and geometry, then Save As native .ai.\n',encoding='utf-8')
        results.append('ILLUSTRATOR_HANDOFF.txt')
    if 'text_outlines' in requested:
        # Text remains live; no misleading faux outline is generated.
        report.setdefault('warnings',[]).append('Text-to-glyph outlines needs a confirmed font file and licensed local conversion; no outlines claimed')
    (output_dir/'analysis_validation.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    results.append('analysis_validation.json')
    if 'zip' in requested:
        with zipfile.ZipFile(output_dir/'complete_asset_pack.zip','w',zipfile.ZIP_DEFLATED) as z:
            for name in results:z.write(output_dir/name,arcname=name)
        results.append('complete_asset_pack.zip')
    return results
