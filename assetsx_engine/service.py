"""Persistent local asset/job manifests; asynchronous worker execution; safe UUID access.

Single-instance service: no distributed queue or cross-container job recovery is claimed.
"""
from __future__ import annotations
import io
import json
import os
import threading
import uuid
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from PIL import Image
from .analysis import palette, extract_svg_elements, separate, classify, ocr
from .ai import vision_analysis, AIUnavailable
from .config import Settings
from .editing import edit_raster, edit_svg
from .exports import export
from .ingest import preview
from .models import AssetInfo, ProcessRequest
from .security import detect_format, safe_uuid
from .vectorization import vectorize
from .fidelity import compare_preview


def now():return datetime.now(timezone.utc).isoformat()

def atomic(path:Path,obj:dict):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(obj,indent=2,default=str),encoding='utf-8')
    os.replace(tmp,path)

class Service:
    def __init__(self,settings:Settings):
        self.settings=settings
        self.settings.validate()
        self.root=settings.root.resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.executor=ThreadPoolExecutor(max_workers=settings.workers,thread_name_prefix='assetsx')
        self.lock=threading.RLock()

    def asset_dir(self,asset_id:str)->Path:
        return self.root/'assets'/safe_uuid(asset_id)

    def job_dir(self,job_id:str)->Path:
        return self.root/'jobs'/safe_uuid(job_id)

    def register(self,name:str,data:bytes)->dict:
        if not data or len(data)>self.settings.max_upload_mb*1024*1024:raise ValueError('Invalid asset size')
        fmt,note=detect_format(name,data)
        image,origin,warnings=preview(data,fmt,self.settings.max_pixels)
        elements=(extract_svg_elements(data) if origin=='vector_svg' else separate(image))
        if note:warnings.append(note)
        # Preserve the source, normalized raster preview, and manifest individually.
        ident=uuid.uuid4().hex;dir=self.asset_dir(ident);dir.mkdir(parents=True,exist_ok=False)
        (dir/'source.bin').write_bytes(data)
        image.save(dir/'preview.png')
        info=AssetInfo(id=ident,filename=Path(name).name,format=fmt,input_mode=origin,
                      width=image.width,height=image.height,
                      asset_type=classify(origin,image,elements,name),elements=elements,
                      palette=palette(image),import_warnings=warnings).model_dump()
        atomic(dir/'info.json',info)
        return info

    def asset(self,ident:str)->dict:
        path=self.asset_dir(ident)/'info.json'
        if not path.is_file():raise FileNotFoundError('Asset ID not found')
        return json.loads(path.read_text())

    def analysis(self,ident:str,run_ocr:bool=False)->dict:
        a=self.asset(ident)
        if run_ocr:
            with Image.open(self.asset_dir(ident)/'preview.png') as img:a['ocr']=ocr(img)
        return a

    def job(self,ident:str)->dict:
        path=self.job_dir(ident)/'manifest.json'
        if not path.is_file():raise FileNotFoundError('Job ID not found')
        return json.loads(path.read_text())

    def submit(self,req:ProcessRequest)->dict:
        self.asset(req.asset_id)
        ident=uuid.uuid4().hex;folder=self.job_dir(ident);folder.mkdir(parents=True,exist_ok=False)
        record={'id':ident,'asset_id':req.asset_id,'state':'queued','stage':'queued',
                'progress':0,'mode':req.mode.value,'strategy':req.strategy.value,
                'created_at':now(),'updated_at':now(),'outputs':[],'error':None}
        atomic(folder/'request.json',req.model_dump(mode='json'))
        atomic(folder/'manifest.json',record)
        self.executor.submit(self._execute,ident)
        return record

    def _update(self,ident:str,**changes):
        with self.lock:
            m=self.job(ident);m.update(changes);m['updated_at']=now()
            atomic(self.job_dir(ident)/'manifest.json',m)

    def _execute(self,ident:str):
        try:
            self._update(ident,state='running',stage='prepare',progress=5)
            folder=self.job_dir(ident)
            req=ProcessRequest.model_validate_json((folder/'request.json').read_text())
            a=self.asset(req.asset_id)
            source=self.asset_dir(req.asset_id)/'source.bin'
            img=Image.open(self.asset_dir(req.asset_id)/'preview.png').convert('RGBA')
            warnings=list(a['import_warnings'])
            report={'engine':'AssetsX AI v0.1.0','mode':req.mode.value,'asset_id':req.asset_id,
                    'type':a['asset_type'],'source_format':a['format'],'warnings':warnings,
                    'quality_policy':'Same tracing, validation and export rules for both AI modes',
                    'production_ready':False,'operator_review_required':True,
                    'source_dimensions':[img.width,img.height],
                    'input_element_count':len(a['elements'])}
            if req.ai_analyze:
                self._update(ident,stage='ai_analysis',progress=15)
                try:report['ai_analysis']=vision_analysis(img,req.mode.value,self.settings)
                except AIUnavailable as exc:
                    report['ai_analysis']={'status':'unavailable','reason':str(exc)}
                    warnings.append('AI analysis unavailable; deterministic pipeline continued')
            if req.ai_edit_prompt:
                # No claim that a vision-only model can edit an image.
                raise ValueError('AI_EDIT_NOT_CONFIGURED: image-edit generation requires a verified, compatible provider adapter. Use deterministic edit commands.')
            self._update(ident,stage='edit',progress=30)
            edits=req.edits
            is_native_svg=a['input_mode']=='vector_svg'
            if is_native_svg:
                edited_svg,notes=edit_svg(source.read_bytes(),edits,a['elements'],req.selected_element_ids)
                from .ingest import preview as render
                img,_,_=render(edited_svg,'svg',self.settings.max_pixels)
                warnings+=notes
                if req.strategy in ('auto','existing_vector'):
                    svg=edited_svg
                    trace={'backend':'native_svg_preserved','path_count':len(extract_svg_elements(svg)),
                           'embedded_rasters':0,'original_dimensions':[img.width,img.height]}
                else:
                    svg,trace=vectorize(img,req.strategy.value,req.max_colors,req.min_area)
            else:
                if req.selected_element_ids and not all(i in {e['id'] for e in a['elements']} for i in req.selected_element_ids):
                    raise ValueError('Unknown selected region ID')
                img,notes=edit_raster(img,edits,a['elements'])
                warnings+=notes
                # Existing input converted to a native SVG only if it really is safe editable SVG.
                if req.strategy.value=='existing_vector':raise ValueError('Existing vector strategy requires an SVG input')
                bounds=[e['bounds'] for e in a['elements'] if e['id'] in req.selected_element_ids] or None
                self._update(ident,stage='vectorize',progress=55)
                svg,trace=vectorize(img,req.strategy.value,req.max_colors,req.min_area,selected_bounds=bounds)
            report['vectorization']=trace
            try:
                report['fidelity']=compare_preview(img,svg,folder/'output')
            except Exception as exc:
                report['fidelity']={'status':'unavailable','reason':type(exc).__name__}
                warnings.append('Preview fidelity comparison unavailable; manual inspection required')
            report['modified_dimensions']=[img.width,img.height]
            report['selected_element_count']=len(req.selected_element_ids)
            self._update(ident,stage='export_and_validate',progress=78)
            results=export(folder/'output',img,svg,req.formats,report)
            if report.get('fidelity',{}).get('comparison'):
                results.extend([report['fidelity']['comparison'],report['fidelity']['heatmap']])
                if 'zip' in req.formats:
                    from zipfile import ZipFile, ZIP_DEFLATED
                    with ZipFile(folder/'output'/'complete_asset_pack.zip','a',ZIP_DEFLATED) as z:
                        for name in (report['fidelity']['comparison'],report['fidelity']['heatmap']):
                            z.write(folder/'output'/name,arcname=name)
            report['output_files']=results
            self._update(ident,state='completed',stage='done',progress=100,outputs=results,report=report)
        except Exception as exc:
            self._update(ident,state='failed',stage='failed',progress=100,
                         error=(type(exc).__name__+': '+str(exc))[:600])

    def close(self):self.executor.shutdown(wait=True,cancel_futures=False)
