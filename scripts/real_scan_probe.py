"""Verify a user-authorized real scan through GitHub, Funnel, FastAPI and SQLite."""
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'backend'))
import httpx
from PIL import Image
from sqlalchemy import select
from app.config import Settings
from app.db import make_db
from app.models import Case,Page,Entity,Link,Message,State
from app.security.links import allow_page_temporarily
from app.images.storage import original,render
from app.services.backup import backup
from app.services.entities import serialize
from app.github_sync.client import GitHubClient

STATE_PATH=ROOT/'.local/qa/real-scan-state.json'
CROP={'x':250,'y':200,'width':1600,'height':1200,'output_max_width':2400}


def fingerprint(entity):
    return hashlib.sha256(json.dumps(serialize(entity),sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def funnel_origin():
    exe=shutil.which('tailscale') or str(Path(os.environ['ProgramFiles'])/'Tailscale/tailscale.exe')
    value=json.loads(subprocess.check_output([exe,'status','--json']))
    config=json.loads(subprocess.check_output([exe,'funnel','status','--json']))
    host=value['Self']['DNSName'].rstrip('.')
    assert value['BackendState']=='Running'
    assert config['AllowFunnel'].get(host+':443') is True
    assert config['Web'][host+':443']['Handlers']['/']['Proxy']=='http://127.0.0.1:8000'
    return 'https://'+host


def prepare():
    settings=Settings();client=GitHubClient(settings);client.private_check()
    backup(settings,ROOT/'.local/backups/before-real-scan.sqlite3')
    engine,factory=make_db(settings)
    with factory() as db:
        pages=db.scalars(select(Page).join(Case).where(Case.fond=='801',Case.inventory=='40',Case.number=='98',Page.jpg_number=='0057')).all()
        assert len(pages)==1,'The requested scan must resolve uniquely'
        page=pages[0];source=original(settings,page)
        assert source.is_relative_to(settings.archive_root.resolve())
        with source.open('rb') as stream: checksum=hashlib.file_digest(stream,'sha256').hexdigest()
        assert checksum==page.sha256
        entities={e.id:fingerprint(e) for e in db.scalars(select(Entity))}
        grant=allow_page_temporarily(db,page,'Explicit user request: GAKK F801 Op40 D98 JPG0057 and coordinate crop; single-page integration test',30)
        state={'page_id':page.id,'case_id':page.case_id,'sha256':page.sha256,'filename':page.filename,'dimensions':[page.width,page.height],
               'case_publication':db.get(Case,page.case_id).publication,'original_mtime_ns':source.stat().st_mtime_ns,
               'entities_before':entities,'grant_expires':grant['expires'],'funnel_origin':funnel_origin(),'crop':CROP,
               'image_request_id':str(uuid.uuid4()),'crop_request_id':str(uuid.uuid4()),'record_operation_id':str(uuid.uuid4())}
        assert state['case_publication']=='private_only'
        db.commit()
    STATE_PATH.parent.mkdir(parents=True,exist_ok=True)
    STATE_PATH.write_text(json.dumps(state,indent=2),encoding='utf-8')
    client.write('requests/pages/'+state['image_request_id']+'.json',{'schema_version':'1.0','request_id':state['image_request_id'],'operation':'get_pages','case_id':state['case_id'],'page_numbers':['0057'],'variant':'original'})
    client.write('requests/crops/'+state['crop_request_id']+'.json',{'schema_version':'1.0','request_id':state['crop_request_id'],'operation':'get_crop','page_id':state['page_id'],**CROP})
    print(json.dumps({'real_scan_requests_committed':True,'page_id':state['page_id'],'case_still_private':True,'single_page_grant_expires':grant['expires']}),flush=True)
    client.close();engine.dispose()


def poll(client,path):
    deadline=time.monotonic()+300
    while time.monotonic()<deadline:
        try: return client.read(path)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code!=404: raise
        print('Waiting for real backend receipt:',path,flush=True)
        time.sleep(10)
    raise TimeoutError(path)


def verify():
    state=json.loads(STATE_PATH.read_text(encoding='utf-8'))
    settings=Settings();client=GitHubClient(settings);client.private_check()
    engine,factory=make_db(settings)
    responses={}
    for kind,key in (('pages','image_request_id'),('crops','crop_request_id')):
        value=poll(client,'responses/'+kind+'/'+state[key]+'.json')
        assert value['status']=='completed',value
        responses[kind]=value['pages'][0]
        assert responses[kind]['page_id']==state['page_id']
    report={'resource':'GAKK F801 Op40 D98 JPG0057','page_id':state['page_id'],'sha256':state['sha256'],
            'dimensions':state['dimensions'],'funnel_origin':state['funnel_origin'],'crop':state['crop'],'grant_expires':state['grant_expires']}
    with httpx.Client(timeout=60) as http:
        assert http.get(state['funnel_origin']+'/api/v1/health').json()['status']=='ok'
        with factory() as db:
            page=db.get(Page,state['page_id']);source=original(settings,page)
            assert source.stat().st_mtime_ns==state['original_mtime_ns']
            with source.open('rb') as stream: assert hashlib.file_digest(stream,'sha256').hexdigest()==state['sha256']
            expected_crop=render(settings,page,'crop',state['crop'])
        for kind in ('pages','crops'):
            link=responses[kind];parts=urlsplit(link['url'])
            direct=state['funnel_origin']+parts.path+'?'+parts.query
            with factory() as db: before=db.get(Link,link['link_id']).hits
            response=http.get(direct);assert response.status_code==200
            digest=hashlib.sha256(response.content).hexdigest()
            expected=state['sha256'] if kind=='pages' else hashlib.sha256(expected_crop).hexdigest()
            assert digest==expected,'HTTP bytes must match the home-disk source/render'
            size=list(Image.open(io.BytesIO(response.content)).size)
            assert size==(state['dimensions'] if kind=='pages' else [state['crop']['width'],state['crop']['height']])
            with factory() as db: after_direct=db.get(Link,link['link_id']).hits
            assert after_direct==before+1,'Direct request must be consumed by home FastAPI'
            proxied=http.get(link['url']);assert proxied.status_code==200 and hashlib.sha256(proxied.content).hexdigest()==expected
            with factory() as db: after_proxy=db.get(Link,link['link_id']).hits
            assert after_proxy==after_direct+1,'Vercel must proxy to home FastAPI, not serve a static JPEG'
            assert 'no-store' in response.headers.get('cache-control','')
            assert http.get(state['funnel_origin']+parts.path).status_code==403
            report[kind]={'url':direct,'proxy_url':link['url'],'http_status':200,'sha256':digest,'size':size,
                          'home_hit_counter':[before,after_direct,after_proxy],'home_bytes_verified':True}
        operation=state['record_operation_id']
        proposal={'schema_version':'1.0','operation_id':operation,'operation':'create_record','created_by':'chatgpt',
                  'title':'ИНТЕГРАЦИОННЫЙ ТЕСТ — ГАКК Ф801 Оп40 Д98 JPG0057; не расшифровка',
                  'data':{'text':'Техническая проверка добавления исторической записи по реальному источнику. Содержание документа не расшифровывалось; генеалогические факты не утверждаются.',
                          'event_type':'integration_test','confidence':'unknown','source_note':'Explicit user-authorized real-scan integration test',
                          'sources':[{'page_id':state['page_id'],'sha256':state['sha256'],'crop':state['crop']}]}}
        client.write('inbox/records/'+operation+'.json',proposal)
        receipt=poll(client,'outbox/receipts/'+operation+'.json')
        assert receipt['status']=='proposed',receipt
        access=(settings.data_dir/'INITIAL-ACCESS.txt').read_text(encoding='utf-8').splitlines()[1].strip()
        login=http.post('http://127.0.0.1:8000/api/auth/login',json={'code':access});login.raise_for_status()
        headers={'Authorization':'Bearer '+login.json()['token']}
        try:
            duplicate=http.post('http://127.0.0.1:8000/api/protocol',json=proposal,headers=headers)
            assert duplicate.status_code==200 and duplicate.json()==receipt
            via_api=http.get(state['funnel_origin']+'/api/entities/'+receipt['entity_id'],headers=headers)
            assert via_api.status_code==200 and via_api.json()['status']=='proposed' and via_api.json()['kind']=='record'
        finally: http.post('http://127.0.0.1:8000/api/auth/logout',headers=headers)
        with factory() as db:
            entity=db.get(Entity,receipt['entity_id']);assert entity and entity.kind=='record' and entity.status=='proposed'
            for identifier,fingerprint_before in state['entities_before'].items():
                assert fingerprint(db.get(Entity,identifier))==fingerprint_before,'Pre-existing data changed'
            assert len(db.scalars(select(Entity)).all())==len(state['entities_before'])+1
            assert db.get(Message,operation).response==receipt
            assert db.get(Case,state['case_id']).publication=='private_only'
            sync=db.get(State,'sync')
            report.update(github_sync='WORKING',operation_id=operation,entity_id=entity.id,record_status=entity.status,
                          existing_entities_unchanged=True,confirmed_data_unchanged=True,case_still_private=True,
                          fastapi_protocol_idempotency=True,sync_snapshot=sync.value if sync else None,verified_at=time.time())
    (ROOT/'.local/qa/real-scan-probe.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
    client.close();engine.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','verify']);args=parser.parse_args()
    (prepare if args.action=='prepare' else verify)()
