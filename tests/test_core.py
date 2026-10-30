from io import BytesIO
import json
import time
from pathlib import Path
import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from assetsx_engine.analysis import extract_svg_elements, separate
from assetsx_engine.config import Settings
from assetsx_engine.security import validate_svg,detect_format
from assetsx_engine.vectorization import vectorize
from assetsx_engine.validate import validate_vector
from assetsx_engine.api import create_app


def sample():
    im=Image.new('RGBA',(128,96),(0,0,0,0))
    d=ImageDraw.Draw(im);d.rectangle((12,15,50,72),fill='#ff0000');d.ellipse((60,10,105,65),fill='#0088cc')
    f=BytesIO();im.save(f,format='PNG');return f.getvalue()


def app(tmp_path):
    return create_app(Settings(root=tmp_path,inbound_token='only-my-secret',max_pixels=1_000_000))


def test_artboard_paths_preserve_native_canvas_and_alpha():
    image=Image.open(BytesIO(sample())).convert('RGBA')
    svg,report=vectorize(image,strategy='shapes',max_colors=6,min_area=10)
    assert report['backend']=='artboard_opencv_color_contours'
    assert report['original_dimensions']==[128,96]
    assert report['embedded_rasters']==0
    assert b'<path ' in svg and b'<image ' not in svg
    assert validate_vector(svg)['true_vector']


def test_block_external_svg_and_pdf_signature():
    with pytest.raises(ValueError):validate_svg(b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.test/a.png"/></svg>')
    with pytest.raises(ValueError):detect_format('art.pdf',b'not-a-pdf')
    with pytest.raises(ValueError):detect_format('art.ai',b'Adobe Illustrator')


def test_svg_edit_and_preserve(tmp_path):
    raw=b'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><rect id="logo" width="80" height="50" fill="#00ff00"/><text x="3" y="60">ABC</text></svg>'
    from assetsx_engine.editing import edit_svg
    elements=extract_svg_elements(raw)
    updated,notes=edit_svg(raw,[{'action':'recolor','element_ids':[elements[0]['id']],'params':{'color':'#112233'}},
                                {'action':'replace_text','element_ids':[elements[1]['id']],'params':{'text':'GOLD'}}],elements)
    assert b'#112233' in updated and b'GOLD' in updated
    assert validate_vector(updated)['true_vector']


def test_authenticated_upload_and_job(tmp_path):
    with TestClient(app(tmp_path)) as client:
        assert client.get('/health').status_code==200
        assert client.get('/v1/capabilities').status_code==401
        h={'Authorization':'Bearer only-my-secret'}
        a=client.post('/v1/assets',headers=h,files={'file':('logo.png',sample(),'image/png')})
        assert a.status_code==201,a.text
        asset=a.json();assert len(asset['elements'])>=2
        r=client.post('/v1/jobs',headers=h,json={'asset_id':asset['id'],'strategy':'shapes','selected_element_ids':[],
              'edits':[{'action':'add_shape','params':{'x':5,'y':5,'width':25,'height':10,'color':'#0000FF'}}],
              'formats':['png','transparent_png','svg','pdf','eps','ai_handoff','zip']})
        assert r.status_code==202,r.text
        identifier=r.json()['id']
        for _ in range(200):
            j=client.get(f'/v1/jobs/{identifier}',headers=h).json()
            if j['state'] in ('completed','failed'):break
            time.sleep(.07)
        assert j['state']=='completed',j
        assert j['report']['vector_validation']['true_vector']
        for name in ['asset.svg','asset.eps','asset.pdf','complete_asset_pack.zip','analysis_validation.json']:
            file=client.get(f'/v1/jobs/{identifier}/download/{name}',headers=h)
            assert file.status_code==200,(name,file.status_code)
        assert client.get(f'/v1/jobs/{identifier}/download/source.bin',headers=h).status_code==404


def test_element_only_selection_and_quality_same(tmp_path):
    with TestClient(app(tmp_path)) as client:
        h={'Authorization':'Bearer only-my-secret'}
        asset=client.post('/v1/assets',headers=h,files={'file':('mark.png',sample(),'image/png')}).json()
        ids=[asset['elements'][0]['id']]
        jobs=[]
        for mode in ('quality','cost_effective'):
            res=client.post('/v1/jobs',headers=h,json={'asset_id':asset['id'],'mode':mode,'strategy':'shapes',
                        'selected_element_ids':ids,'formats':['svg','zip']})
            assert res.status_code==202,res.text
            for _ in range(120):
                info=client.get('/v1/jobs/'+res.json()['id'],headers=h).json()
                if info['state'] in ('failed','completed'):break
                time.sleep(.05)
            assert info['state']=='completed',info
            jobs.append(info)
        assert jobs[0]['report']['vectorization']['path_count']==jobs[1]['report']['vectorization']['path_count']
        assert jobs[0]['report']['quality_policy']==jobs[1]['report']['quality_policy']


def test_font_export_not_misrepresented(tmp_path):
    from assetsx_engine.exports import FORMATS
    assert 'ttf' not in FORMATS and 'otf' not in FORMATS and 'ai' not in FORMATS
