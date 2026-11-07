"""Real GitHub/Funnel test using one generated JPEG, never a historical document."""
import argparse
import hashlib
import io
import json
import secrets
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'backend'))
from PIL import Image,ImageDraw,ImageFont
import httpx
from app.config import Settings
from app.db import make_db
from app.models import Case,Page,Entity,Link,Message
from app.security.links import key,issue,signature
from app.github_sync.client import GitHubClient
from app.services.backup import backup

STATE=ROOT/'.local/qa/live-probe-state.json'
CASE='technical-api-test-case-v1'
PAGE='technical-api-test-page-v1'


def prepare():
    s=Settings()
    if not s.github_token: raise RuntimeError('Configure the fine-grained GitHub token locally first')
    client=GitHubClient(s)
    client.private_check()
    backup(s,ROOT/'.local/backups/before-live-integration.sqlite3')
    engine,factory=make_db(s)
    with factory() as db:
        page=db.get(Page,PAGE)
        if not page:
            path=s.data_dir/'managed/drevo-api-test.jpg'
            challenge=secrets.token_hex(3).upper()
            image=Image.new('RGB',(1200,600),'white')
            draw=ImageDraw.Draw(image)
            font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',72)
            draw.text((70,100),'DREVO API TEST',fill='black',font=font)
            draw.text((70,240),'CODE '+challenge,fill='black',font=font)
            draw.text((70,380),'TECHNICAL IMAGE',fill='black',font=font)
            image.save(path,'JPEG',quality=95)
            sha=hashlib.sha256(path.read_bytes()).hexdigest()
            db.add(Case(id=CASE,title='Технический тест API — не архивный документ',publication='signed_links_allowed',metadata_json={'technical_fixture':True}))
            db.flush()
            db.add(Page(id=PAGE,case_id=CASE,source_key='technical-fixture:v1',path=str(path),zip_member=None,filename=path.name,jpg_number='TEST-0001',sha256=sha,size=path.stat().st_size,mtime_ns=str(path.stat().st_mtime_ns),width=1200,height=600,format='JPEG'))
            db.commit()
        else:
            assert page.case_id==CASE and db.get(Case,CASE).metadata_json.get('technical_fixture')
    identifier=str(uuid.uuid4())
    request={'schema_version':'1.0','request_id':identifier,'operation':'get_pages','created_by':'chatgpt','status':'pending','case_id':CASE,'page_numbers':['TEST-0001'],'variant':'original'}
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps({'request':request,'page_id':PAGE,'created_at':time.time()}),encoding='utf-8')
    client.write('requests/pages/'+identifier+'.json',request)
    print(json.dumps({'request_committed':True,'request_id':identifier,'technical_fixture_only':True}),flush=True)
    client.close();engine.dispose()


def poll(client,path,seconds=600):
    start=time.monotonic()
    while time.monotonic()-start<seconds:
        try: return client.read(path)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code!=404: raise
        elapsed=int(time.monotonic()-start)
        if elapsed%30<10: print('Waiting for worker receipt:',path,'elapsed',elapsed,flush=True)
        time.sleep(10)
    raise TimeoutError('No server receipt at '+path)


def verify():
    s=Settings();client=GitHubClient(s);client.private_check()
    state=json.loads(STATE.read_text(encoding='utf-8'))
    response=poll(client,'responses/pages/'+state['request']['request_id']+'.json')
    assert response['status']=='completed',response.get('error')
    link=response['pages'][0]
    assert link['page_id']==PAGE
    report={'technical_fixture_only':True,'github_request_response':'WORKING','image_reading_by_chatgpt':'BLOCKED','public_index_url':s.public_api_url+'/ai/index.json','test_image_url':link['url'],'expires':link['expires']}
    engine,factory=make_db(s);secret=key(s)
    with httpx.Client(timeout=45) as http:
        report['health']=http.get(s.public_api_url+'/api/v1/health').status_code
        image=http.get(link['url']);report['signed_image']=image.status_code
        assert image.status_code==200 and Image.open(io.BytesIO(image.content)).size==(1200,600)
        path=urlsplit(link['url']).path
        report['without_signature']=http.get(s.public_api_url+path).status_code
        report['bad_signature']=http.get(link['url'][:-1]+('A' if link['url'][-1]!='A' else 'B')).status_code
        assert report['without_signature']==403 and report['bad_signature']==403
        for mode in ('expired','revoked','limit'):
            with factory() as db:
                generated=issue(db,s,secret,db.get(Page,PAGE))
                row=db.get(Link,generated['link_id'])
                if mode=='expired': row.expires=time.time()-10
                if mode=='revoked': row.revoked=True
                if mode=='limit': row.max_hits=1
                url=s.public_api_url+path+'?token='+row.id+'.'+signature(secret,row)
                db.commit()
            if mode=='limit': assert http.get(url).status_code==200
            report[mode]=http.get(url).status_code
            assert report[mode]==(410 if mode=='expired' else 403)
        with factory() as db:
            generated=issue(db,s,secret,db.get(Page,PAGE),'crop',{'x':10,'y':10,'width':100,'height':120,'output_max_width':2400})
            db.commit()
        crop=http.get(generated['url'])
        assert crop.status_code==200 and Image.open(io.BytesIO(crop.content)).size==(100,120)
        report['signed_crop']=crop.status_code
    operation=state.get('proposal_id') or str(uuid.uuid4())
    state['proposal_id']=operation
    STATE.write_text(json.dumps(state),encoding='utf-8')
    proposal={'schema_version':'1.0','operation_id':operation,'operation':'save_transcription','created_by':'chatgpt','title':'Техническая проверка GitHub → SQLite; не результат чтения ChatGPT','data':{'text':'DREVO API TEST — technical integration driver, not an OCR result','sources':[{'page_id':PAGE,'sha256':link['sha256']}],'confidence':'unknown'}}
    client.write('inbox/transcriptions/'+operation+'.json',proposal)
    receipt=poll(client,'outbox/receipts/'+operation+'.json')
    assert receipt['status']=='proposed',receipt
    with factory() as db:
        entity=db.get(Entity,receipt['entity_id'])
        assert entity and entity.kind=='transcription' and entity.status=='proposed'
        message=db.get(Message,operation)
        assert message and message.response==receipt
    # Same UUID/content in another inbox file exercises durable idempotency in a later poll.
    client.write('inbox/transcriptions/'+operation+'-retry.json',proposal)
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        from app.models import State
        with factory() as db:
            done=db.get(State,'blob:inbox/transcriptions/'+operation+'-retry.json')
            if done:
                from sqlalchemy import select,func
                assert db.scalar(select(func.count()).select_from(Entity).where(Entity.id==receipt['entity_id']))==1
                assert db.get(Message,operation).response==receipt
                report['github_idempotency']='WORKING'
                break
        print('Waiting for duplicate operation acknowledgement',flush=True)
        time.sleep(10)
    else: raise TimeoutError('Duplicate receipt was not processed')
    report.update(github_proposal_sqlite='WORKING',receipt_id=operation,entity_id=receipt['entity_id'],verified_at=time.time())
    (ROOT/'.local/qa/integration-live.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
    client.close();engine.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','verify']);args=parser.parse_args()
    (prepare if args.action=='prepare' else verify)()
