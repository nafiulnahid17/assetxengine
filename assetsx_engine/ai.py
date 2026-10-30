"""OpenRouter vision fallback; mode changes model pool, never core tracing/validation."""
import base64
from io import BytesIO
import httpx
from PIL import Image
from .config import Settings

class AIUnavailable(RuntimeError):pass


def vision_analysis(image:Image.Image,mode:str,config:Settings)->dict:
    models=config.quality_vision_models if mode=='quality' else config.cost_vision_models
    if not config.enable_ai or not config.openrouter_api_key or not models:
        raise AIUnavailable('AI analysis disabled or model credentials not configured')
    work=image.copy();work.thumbnail((1280,1280));bio=BytesIO();work.convert('RGB').save(bio,'JPEG',quality=85)
    content=[{'type':'text','text': 'Analyze this visual asset for editable graphics production. Identify logo/text/number/pattern/shapes and possible copyrighted or complex elements. Do not invent text. Reply concise JSON with asset_type, elements, recommendations, caveats.'},
             {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(bio.getvalue()).decode()}}]
    failures=[]
    with httpx.Client(timeout=config.ai_timeout) as client:
        for model in models:
            try:
                response=client.post(config.openrouter_base_url.rstrip('/')+'/chat/completions',
                    headers={'Authorization':'Bearer '+config.openrouter_api_key},
                    json={'model':model,'messages':[{'role':'user','content':content}],
                          'temperature':0.0,'max_tokens':900})
                response.raise_for_status()
                message=response.json()['choices'][0]['message']['content']
                if not isinstance(message,str) or not message.strip():raise ValueError('Empty vision response')
                return {'model':model,'text':message,'mode':mode,'fallback_count':len(failures)}
            except (httpx.HTTPError,KeyError,TypeError,IndexError,ValueError) as exc:
                failures.append({'model':model,'error':type(exc).__name__})
    raise AIUnavailable('All compatible vision models failed: '+str(failures))
