import hashlib
import io
import time
import uuid
from urllib.parse import urlsplit
import httpx
import pytest
from PIL import Image
from app.models import Link, Message, Case
from app.images import payloads
from app.security.links import signature
from app.github_sync.client import GitHubClient
from app.github_sync.worker import sync_once
from test_github import GitHubMock


@pytest.fixture
def ready(imported, monkeypatch):
    monkeypatch.setattr(payloads, 'direct_origin', lambda: 'https://test.tail123.ts.net')
    app,c,s,folder,auth,pages=imported
    c.patch('/api/cases/'+pages[0]['case_id'],json={'publication':'signed_links_allowed','rights_checked':True},headers=auth['admin'])
    return imported


def request(c, auth, page, **kwargs):
    raw={'operation':'get_image_payload','request_id':str(uuid.uuid4()),'page_id':page,'variant':'crop','x':10,'y':20,'width':100,'height':120,**kwargs}
    return raw,c.post('/api/protocol',json=raw,headers=auth['admin'])


def test_payload_integrity_head_retries_and_idempotence(ready):
    app,c,s,folder,auth,pages=ready
    raw,result=request(c,auth,pages[0]['id'])
    assert result.status_code==200,result.text
    result=result.json();assert result['status']=='completed',result
    p=result['image_payload'];path=urlsplit(p['url']).path
    assert not urlsplit(p['url']).query and path.endswith('.jpg')
    assert p['direct_url'].startswith('https://test.tail123.ts.net/')
    assert not p['base64_in_github'] and p['bytes']<2_000_000
    assert c.post('/api/protocol',json=raw,headers=auth['admin']).json()==result
    for _ in range(3):
        head=c.head(path);assert head.status_code==200 and head.content==b''
        assert int(head.headers['content-length'])==p['bytes']
    with app.state.factory() as db:assert db.get(Link,p['link_id']).hits==0
    for _ in range(2):
        image=c.get(path)
        assert image.status_code==200
        assert image.headers['content-type']=='image/jpeg'
        assert image.headers['content-disposition'].startswith('inline')
        assert image.headers['cache-control']=='private, no-store'
        assert image.headers['cdn-cache-control']=='no-store'
        assert hashlib.sha256(image.content).hexdigest()==p['sha256']
        assert Image.open(io.BytesIO(image.content)).size==(100,120)
    assert p['source_sha256']==pages[0]['sha256']
    with app.state.factory() as db:
        link=db.get(Link,p['link_id']);assert link.hits==2
        link.max_hits=2;db.commit()
    assert c.head(path).status_code==403
    assert c.get(path).status_code==403


def test_payload_revoke_expire_renew_tamper_and_cleanup(ready):
    app,c,s,folder,auth,pages=ready
    raw,r=request(c,auth,pages[0]['id']);p=r.json()['image_payload'];path=urlsplit(p['url']).path
    assert c.get(path.replace(pages[0]['id'],pages[1]['id'])).status_code==403
    changed = 'A' if path[-5] != 'A' else 'B'
    assert c.get(path[:-5]+changed+'.jpg').status_code==403
    with app.state.factory() as db:
        link=db.get(Link,p['link_id']);filename=link.params['_payload']['file']
    target=s.data_dir/'image-payloads'/filename
    correct=target.read_bytes();target.write_bytes(b'corrupted')
    assert c.get(path).status_code==409
    with app.state.factory() as db:assert db.get(Link,p['link_id']).hits==0
    target.write_bytes(correct)
    c.post('/api/links/'+p['link_id']+'/revoke',headers=auth['admin'])
    assert c.head(path).status_code==403
    renewed=c.post('/api/protocol',json={'request_id':str(uuid.uuid4()),'operation':'renew_image_links','renew_request_id':raw['request_id']},headers=auth['admin']).json()
    fresh=renewed['image_payload'];assert fresh['link_id']!=p['link_id']
    assert c.get(urlsplit(fresh['url']).path).status_code==200
    with app.state.factory() as db:
        link=db.get(Link,fresh['link_id']);link.expires=time.time()-1;db.commit()
        expired=f'/ai/images/{pages[0]["id"]}/payload/{link.id}.{signature(app.state.secret,link)}.jpg'
    assert c.head(expired).status_code==410
    import os
    for file in target.parent.glob('*.jpg'):os.utime(file,(time.time()-180,time.time()-180))
    with app.state.factory() as db:payloads.cleanup(db,s)
    assert not list(target.parent.glob('*.jpg'))


def test_permissions_and_size_limits_are_enforced(ready, monkeypatch):
    app,c,s,folder,auth,pages=ready
    raw,r=request(c,auth,pages[0]['id'],x=-1)
    assert r.status_code==422
    _,r=request(c,auth,pages[0]['id'],width=99999)
    assert r.json()['http_status']==422
    _,r=request(c,auth,pages[0]['id'],quality=30)
    assert r.status_code==422
    with app.state.factory() as db:
        db.get(Case,pages[0]['case_id']).publication='private_only';db.commit()
    _,r=request(c,auth,pages[0]['id'])
    assert r.json()['http_status']==403
    assert not (s.data_dir/'image-payloads').exists()
    with app.state.factory() as db:
        db.get(Case,pages[0]['case_id']).publication='signed_links_allowed';db.commit()
    monkeypatch.setattr(payloads,'MAX_BYTES',10)
    _,r=request(c,auth,pages[0]['id'])
    assert r.json()['http_status']==413
    assert not (s.data_dir/'image-payloads').exists()
    monkeypatch.setattr(payloads,'MAX_BYTES',2_000_000)
    monkeypatch.setattr(payloads,'MAX_ACTIVE',0)
    _,r=request(c,auth,pages[0]['id'])
    assert r.json()['http_status']==429


def test_github_image_request_and_no_binary_in_history(ready):
    app,c,s,folder,auth,pages=ready
    s.github_repo='test/DREVO-Research-Data';s.github_token='test-token'
    raw={'request_id':str(uuid.uuid4()),'operation':'get_image_payload','page_id':pages[0]['id'],'variant':'preview','output_max_width':400,'quality':90}
    mock=GitHubMock({'requests/images/'+raw['request_id']+'.json':raw})
    client=GitHubClient(s,transport=httpx.MockTransport(mock.handler))
    assert sync_once(app.state.factory,s,app.state.secret,client)['handled']==1
    result=mock.files['responses/images/'+raw['request_id']+'.json']
    assert result['status']=='completed'
    assert result['image_payload']['width']==400
    assert len(str(result))<4000
    assert sync_once(app.state.factory,s,app.state.secret,client)['handled']==0
    with app.state.factory() as db:assert db.get(Message,raw['request_id']).response==result
    client.close()


def test_existing_query_urls_support_head_without_spending_hits(ready):
    app,c,s,folder,auth,pages=ready
    for operation in ('get_pages','get_crop'):
        fields={'case_id':pages[0]['case_id'],'page_numbers':['0057']} if operation=='get_pages' else {'page_id':pages[0]['id'],'x':1,'y':2,'width':30,'height':40}
        result=c.post('/api/protocol',json={'operation':operation,'request_id':str(uuid.uuid4()),**fields},headers=auth['admin']).json()
        p=result['pages'][0];u=urlsplit(p['url']);url=u.path+'?'+u.query
        head=c.head(url);assert head.status_code==200 and not head.content
        response=c.get(url);assert response.status_code==200
        assert head.headers['content-length']==str(len(response.content))
        with app.state.factory() as db:assert db.get(Link,p['link_id']).hits==1
