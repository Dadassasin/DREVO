import io
import json
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image


def test_public_diagnostics_do_not_expose_private_settings(env):
    app,c,s,folder,auth=env
    health=c.get('/api/v1/health')
    assert health.json()=={'status':'ok','service':'drevo-api','version':app.version}
    capabilities=c.get('/api/v1/system/capabilities')
    assert capabilities.status_code==200
    for value in (str(s.data_dir),str(s.archive_root),s.github_token or 'PRIVATE-SENTINEL'):
        assert value not in health.text+capabilities.text
    assert c.get('/api/cases').status_code==401
    for path in ('/docs','/redoc','/openapi.json'):
        assert c.get(path).status_code==404


def test_versioned_resource_routes_keep_authorization(imported):
    _,c,_,_,auth,pages=imported
    identifier=pages[0]['id']
    paths=[f'/api/v1/pages/{identifier}',f'/api/v1/pages/{identifier}/image',f'/api/v1/pages/{identifier}/crop?x=0&y=0&width=20&height=30']
    for path in paths:
        assert c.get(path).status_code==401
        assert c.get(path,headers=auth['viewer']).status_code==200
    response=c.get(paths[2],headers=auth['viewer'])
    assert Image.open(io.BytesIO(response.content)).size==(20,30)
    assert c.get(f'/api/v1/pages/{identifier}/crop?x=-1&y=0&width=20&height=30',headers=auth['viewer']).status_code==422


def test_signed_crop_is_bound_to_original_pixels_and_resource(imported):
    _,c,_,_,auth,pages=imported
    c.patch('/api/cases/gakk-801-40-98',json={'publication':'signed_links_allowed','rights_checked':True},headers=auth['admin'])
    issued=c.post('/api/links',json={'page_id':pages[0]['id'],'crop':{'x':1,'y':2,'width':25,'height':35}},headers=auth['admin']).json()
    split=urlsplit(issued['url']);url=split.path+'?'+split.query
    assert split.path.startswith('/ai/crops/')
    r=c.get(url+'&x=0&y=0&width=600&height=400')
    assert Image.open(io.BytesIO(r.content)).size==(25,35)
    assert c.get(url.replace(pages[0]['id'],pages[1]['id'])).status_code==403
    assert c.get(split.path).status_code==403


def test_static_ai_files_are_public_data_not_application_code():
    root=Path(__file__).resolve().parents[2]
    index=json.loads((root/'frontend/public/ai/index.json').read_text(encoding='utf-8'))
    assert index['api_version']=='1.0.0'
    assert index['github']['visibility']=='private'
    assert index['chatgpt']['status']!='WORKING'
    assert (root/'frontend/public/ai/instructions.md').is_file()
    rewrites=json.loads((root/'frontend/vercel.json').read_text())['rewrites']
    assert not any(row['source']=='/ai/:path*' for row in rewrites)


def test_filtered_search_paginates_matches_not_raw_candidates(env):
    from app.models import Entity
    from app.services.entities import search
    app,_,_,_,_=env
    with app.state.factory() as db:
        for index in range(60):
            db.add(Entity(kind='finding',title=f'Technical {index}',data={'place':'A' if index%2 else 'B'},status='proposed',author='test',updated=float(index)))
        db.commit()
        first=search(db,'',place='A',offset=0,limit=10)
        second=search(db,'',place='A',offset=10,limit=10)
        assert len(first)==len(second)==10
        assert not {e['id'] for e in first} & {e['id'] for e in second}
