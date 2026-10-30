"""AssetsX REST API; no client file paths and no public direct access to arbitrary files."""
from __future__ import annotations
import secrets
from contextlib import asynccontextmanager
from fastapi import FastAPI,UploadFile,File,HTTPException,Depends,Header
from fastapi.responses import FileResponse
from .config import Settings
from .models import ProcessRequest
from .security import safe_uuid
from .service import Service

def create_app(settings:Settings|None=None)->FastAPI:
    settings=settings or Settings.from_env()
    service=Service(settings)
    @asynccontextmanager
    async def lifespan(app):
        yield
        service.close()
    app=FastAPI(title='AssetsX AI Engine',version='0.1.0',lifespan=lifespan)
    app.state.service=service
    def authorize(authorization:str|None=Header(None)):
        token=settings.inbound_token
        if not token:
            raise HTTPException(503,'ASSETSX_INBOUND_TOKEN not configured')
        if not authorization or not authorization.startswith('Bearer ') or not secrets.compare_digest(authorization[7:],token):
            raise HTTPException(401,'Unauthorized')
    @app.get('/health')
    def health():return {'ok':True,'engine':'AssetsX AI','version':'0.1.0'}
    @app.get('/v1/capabilities',dependencies=[Depends(authorize)])
    def capabilities():
        from .exports import FORMATS
        return {'input':['png','jpg','jpeg','webp','svg','eps','pdf','pdf-compatible-ai'],
                'output':sorted(FORMATS),'strategies':['auto','shapes','monochrome','multicolor','color_regions','existing_vector'],
                'ai_enabled':settings.enable_ai,'quality_rules_identical':True,
                'limitations':['No proprietary non-PDF AI input','No native Illustrator .ai writer',
                               'No modified licensed font export yet','Complex semantic background removal and AI image editing not yet implemented',
                               'Raster segmentation approximates original layers; PDF/EPS imported as preview']}
    @app.post('/v1/assets',dependencies=[Depends(authorize)],status_code=201)
    async def upload(file:UploadFile=File(...)):
        try:
            # Read max+1 to reject oversized streams safely.
            data=await file.read(settings.max_upload_mb*1024*1024+1)
            return service.register(file.filename or 'upload',data)
        except ValueError as exc:raise HTTPException(422,str(exc))
    @app.get('/v1/assets/{asset_id}',dependencies=[Depends(authorize)])
    def get_asset(asset_id:str,ocr:bool=False):
        try:return service.analysis(asset_id,ocr)
        except (FileNotFoundError,ValueError) as exc:raise HTTPException(404,str(exc))
    @app.get('/v1/assets/{asset_id}/preview',dependencies=[Depends(authorize)])
    def get_preview(asset_id:str):
        try:
            path=service.asset_dir(asset_id)/'preview.png'
            if not path.is_file():raise FileNotFoundError()
        except (ValueError,FileNotFoundError):raise HTTPException(404,'Asset not found')
        return FileResponse(path,media_type='image/png')
    @app.post('/v1/jobs',dependencies=[Depends(authorize)],status_code=202)
    def submit(req:ProcessRequest):
        try:return service.submit(req)
        except FileNotFoundError:raise HTTPException(404,'Asset not found')
        except ValueError as exc:raise HTTPException(422,str(exc))
    @app.get('/v1/jobs/{job_id}',dependencies=[Depends(authorize)])
    def get_job(job_id:str):
        try:return service.job(job_id)
        except (ValueError,FileNotFoundError):raise HTTPException(404,'Job not found')
    @app.get('/v1/jobs/{job_id}/download/{filename}',dependencies=[Depends(authorize)])
    def download(job_id:str,filename:str):
        try:
            m=service.job(job_id)
            if m['state']!='completed' or filename not in m['outputs'] or '/' in filename or '\\' in filename:
                raise FileNotFoundError()
            path=service.job_dir(job_id)/'output'/filename
            if not path.is_file():raise FileNotFoundError()
        except (ValueError,FileNotFoundError):raise HTTPException(404,'Output unavailable')
        return FileResponse(path,filename=filename)
    return app
