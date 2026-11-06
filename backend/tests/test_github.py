import base64
import hashlib
import json
import uuid
import httpx
import pytest
from app.github_sync.client import GitHubClient
from app.github_sync.worker import sync_once
from app.models import Entity


class GitHubMock:
    def __init__(self, files=None, private=True):
        self.files = files or {}
        self.private = private
        self.writes = 0
        self.fail_write = False

    def handler(self, request):
        path = request.url.path
        assert request.headers['authorization'].startswith('Bearer ')
        if path == '/repos/test/DREVO-Research-Data':
            return httpx.Response(200, json={'private': self.private})
        if '/git/trees/' in path:
            return httpx.Response(200, json={'sha': 'commit-1', 'tree': [{'type': 'blob', 'path': p, 'sha': hashlib.sha1(json.dumps(v).encode()).hexdigest(), 'size': len(json.dumps(v))} for p,v in self.files.items()]})
        name = path.split('/contents/', 1)[1]
        if request.method == 'GET':
            if name not in self.files:
                return httpx.Response(404, json={})
            data = json.dumps(self.files[name], ensure_ascii=False, sort_keys=True, indent=2) + '\n'
            return httpx.Response(200, json={'encoding': 'base64', 'size': len(data.encode()), 'content': base64.b64encode(data.encode()).decode(), 'sha': 'current-sha'})
        if self.fail_write:
            return httpx.Response(409, json={'message': 'SHA conflict'})
        self.files[name] = json.loads(base64.b64decode(json.loads(request.content)['content']))
        self.writes += 1
        return httpx.Response(200, json={'content': {'sha': 'new-sha'}})


def test_sync_request_receipt_private_and_idempotent(imported):
    app,c,s,folder,auth,pages=imported
    s.github_repo='test/DREVO-Research-Data'
    s.github_token='test-only-token'
    identifier=str(uuid.uuid4())
    raw={'operation_id':identifier,'operation':'create_record','title':'Рождение Макуха','data':{'event_type':'birth','sources':[{'page_id':pages[0]['id']}],'dates':[{'original':'1918','year':1918,'calendar':'unknown'}]}}
    mock=GitHubMock({'inbox/records/'+identifier+'.json':raw})
    client=GitHubClient(s,transport=httpx.MockTransport(mock.handler))
    result=sync_once(app.state.factory,s,app.state.secret,client)
    assert result['handled']==1
    receipt=mock.files['outbox/receipts/'+identifier+'.json']
    assert receipt['status']=='proposed'
    assert mock.files['manifest.json']['integration_status']=='unverified'
    assert mock.files['outbox/research-context/catalog.json']
    writes=mock.writes
    assert sync_once(app.state.factory,s,app.state.secret,client)['handled']==0
    assert mock.writes==writes
    # HTTP API querying same JSON observes the same receipt, not a second record.
    assert c.post('/api/protocol',json=raw,headers=auth['admin']).json()==receipt
    assert len(c.get('/api/entities?kind=record',headers=auth['viewer']).json())==1
    mock.private=False
    with pytest.raises(ValueError,match='PRIVATE'):
        sync_once(app.state.factory,s,app.state.secret,client)
    client.close()


def test_sync_retry_after_github_conflict_and_living_excluded(imported):
    app,c,s,folder,auth,pages=imported
    s.github_repo='test/DREVO-Research-Data';s.github_token='test-token'
    identifier=str(uuid.uuid4())
    mock=GitHubMock({'requests/search/'+identifier+'.json':{'request_id':identifier,'operation':'search','query':'Макуха'}})
    client=GitHubClient(s,transport=httpx.MockTransport(mock.handler))
    mock.fail_write=True
    with pytest.raises(httpx.HTTPStatusError):
        sync_once(app.state.factory,s,app.state.secret,client)
    mock.fail_write=False
    living=c.post('/api/entities',json={'kind':'person','title':'НЕ ЭКСПОРТИРОВАТЬ','living':True,'data':{}},headers=auth['researcher']).json()
    sync_once(app.state.factory,s,app.state.secret,client)
    assert 'responses/search/'+identifier+'.json' in mock.files
    assert living['id'] not in json.dumps({k:v for k,v in mock.files.items() if k.startswith('outbox/research-context/')})
    client.close()


def test_invalid_json_request_receipt(imported):
    app,c,s,folder,auth,pages=imported
    s.github_repo='test/DREVO-Research-Data';s.github_token='test-token'
    mock=GitHubMock({'requests/pages/bad.json':{'request_id':'not-a-uuid','operation':'get_pages'}})
    client=GitHubClient(s,transport=httpx.MockTransport(mock.handler))
    sync_once(app.state.factory,s,app.state.secret,client)
    assert any(k.startswith('outbox/receipts/invalid-') for k in mock.files)
    client.close()
