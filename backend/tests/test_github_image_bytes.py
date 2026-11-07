import copy
import io
import importlib.util
from pathlib import Path
import uuid
import httpx
import pytest
from PIL import Image
from app.images import payloads
from app.github_sync.client import GitHubClient
from app.github_sync.worker import sync_once
from test_github import GitHubMock

decoder_spec=importlib.util.spec_from_file_location('image_byte_decoder',Path(__file__).resolve().parents[2]/'scripts/decode_image_payload.py')
decoder=importlib.util.module_from_spec(decoder_spec)
decoder_spec.loader.exec_module(decoder)
assemble=decoder.assemble


def setup(imported, monkeypatch):
    app,c,s,folder,auth,pages=imported
    monkeypatch.setattr(payloads,'direct_origin',lambda: None)
    c.patch('/api/cases/'+pages[0]['case_id'],json={'publication':'signed_links_allowed','rights_checked':True},headers=auth['admin'])
    s.github_repo='test/DREVO-Research-Data';s.github_token='test-token'
    raw={'request_id':str(uuid.uuid4()),'operation':'get_image_payload','page_id':pages[0]['id'],'variant':'original','output_max_width':600,'part_bytes':4096}
    mock=GitHubMock({'requests/images/'+raw['request_id']+'.json':raw})
    client=GitHubClient(s,transport=httpx.MockTransport(mock.handler))
    return app,c,s,auth,raw,mock,client


def test_github_bytes_reassemble_retry_and_cleanup(imported,monkeypatch):
    app,c,s,auth,raw,mock,client=setup(imported,monkeypatch)
    assert sync_once(app.state.factory,s,app.state.secret,client)['handled']==1
    response=mock.files['responses/images/'+raw['request_id']+'.json']
    p=response['image_payload'];assert p['delivery']=='github_base64_parts'
    assert p['part_count']>=2 and p['base64_in_github']
    image=assemble(response,lambda path:mock.files[path])
    assert Image.open(io.BytesIO(image)).size==(600,400)
    before=mock.writes
    assert sync_once(app.state.factory,s,app.state.secret,client)['handled']==0
    assert mock.writes==before
    corrupt=copy.deepcopy(mock.files[p['parts'][0]['path']]);corrupt['data']='AAAA'
    with pytest.raises(ValueError):assemble(response,lambda path:corrupt)
    reordered=copy.deepcopy(response);reordered['image_payload']['parts'].reverse()
    with pytest.raises(ValueError):assemble(reordered,lambda path:mock.files[path])
    renewed_id=str(uuid.uuid4())
    mock.files['requests/pages/'+renewed_id+'.json']={'request_id':renewed_id,'operation':'renew_image_links','renew_request_id':raw['request_id']}
    sync_once(app.state.factory,s,app.state.secret,client)
    renewed=mock.files['responses/pages/'+renewed_id+'.json']
    assert renewed==mock.files['responses/images/'+renewed_id+'.json']
    assert assemble(renewed,lambda path:mock.files[path])==image
    c.post('/api/links/'+p['link_id']+'/revoke',headers=auth['admin'])
    sync_once(app.state.factory,s,app.state.secret,client)
    assert all(part['path'] not in mock.files for part in p['parts'])
    assert 'responses/images/'+raw['request_id']+'.json' in mock.files
    assert 'requests/images/'+raw['request_id']+'.json' in mock.files
    client.close()


def test_atomic_bundle_retry_and_preservation(env,monkeypatch):
    _,_,s,_,_=env;s.github_repo='test/DREVO-Research-Data';s.github_token='test-token'
    identifier=str(uuid.uuid4());path='responses/images/'+identifier+'.json'
    files={path:{'request_id':identifier},'responses/images/'+identifier+'/part-0000.json':{'data':'AAA='}}
    mock=GitHubMock({'unrelated.json':{'keep':True}})
    moved=False
    def handler(request):
        nonlocal moved
        if request.method=='PATCH' and not moved:
            assert path not in mock.files  # Neither manifest nor parts visible before branch update.
            moved=True;mock.files['parallel.json']={'keep':'also'};mock.head='parallel-commit'
            return httpx.Response(422,json={'message':'branch moved'})
        return mock.handler(request)
    client=GitHubClient(s,transport=httpx.MockTransport(handler))
    client.image_bundle(files)
    assert mock.files['parallel.json']=={'keep':'also'}
    assert mock.files['unrelated.json']=={'keep':True}
    assert all(mock.files[k]==v for k,v in files.items())
    writes=mock.writes;client.image_bundle(files);assert mock.writes==writes
    with pytest.raises(ValueError):client.image_bundle({path:{'changed':True}})
    with pytest.raises(ValueError):client.image_bundle(delete=['unrelated.json'])
    mock.private=False
    with pytest.raises(ValueError,match='PRIVATE'):client.image_bundle(files)
    client.close()


def test_daily_quota_and_https_backward_compatibility(imported,monkeypatch):
    app,c,s,auth,raw,mock,client=setup(imported,monkeypatch)
    monkeypatch.setattr(payloads,'MAX_GITHUB_DAILY_BYTES',1)
    response=c.post('/api/protocol',json=raw,headers=auth['admin']).json()
    assert response['http_status']==429
    raw.update(request_id=str(uuid.uuid4()),delivery='https')
    response=c.post('/api/protocol',json=raw,headers=auth['admin']).json()
    assert response['image_payload']['delivery']=='temporary_https_jpeg'
    client.close()
