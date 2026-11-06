import io
import uuid
from urllib.parse import urlsplit
from PIL import Image
from app.models import Link


def test_cors_exact_origin_and_bearer_invalidation(env):
    _,c,s,folder,auth=env
    good=c.options('/api/cases',headers={'Origin':s.frontend_origin,'Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'Authorization'})
    assert good.headers['access-control-allow-origin']==s.frontend_origin
    bad=c.options('/api/cases',headers={'Origin':'https://untrusted.example','Access-Control-Request-Method':'GET'})
    assert 'access-control-allow-origin' not in bad.headers
    c.post('/api/auth/logout',headers=auth['viewer'])
    assert c.get('/api/me',headers=auth['viewer']).status_code==401


def test_signed_crop_and_hit_limit(imported):
    app,c,s,folder,auth,pages=imported
    c.patch('/api/cases/gakk-801-40-98',json={'publication':'signed_links_allowed','rights_checked':True},headers=auth['admin'])
    crop={'x':5,'y':7,'width':70,'height':80}
    issued=c.post('/api/links',json={'page_id':pages[0]['id'],'crop':crop},headers=auth['admin']).json()
    split=urlsplit(issued['url']);address=split.path+'?'+split.query
    response=c.get(address)
    assert response.status_code==200
    assert Image.open(io.BytesIO(response.content)).size==(70,80)
    with app.state.factory() as db:
        row=db.get(Link,issued['link_id']);row.hits=row.max_hits;db.commit()
    assert c.get(address).status_code==403
    c.patch('/api/cases/gakk-801-40-98',json={'publication':'private_only'},headers=auth['admin'])
    assert c.get(address).status_code==403


def test_protocol_rejects_unknown_operations_and_no_executable_messages(env):
    _,c,_,_,auth=env
    for operation in ('delete_record','execute','../file','confirm_relationship'):
        response=c.post('/api/protocol',json={'operation_id':str(uuid.uuid4()),'operation':operation,'title':'Test','data':{}},headers=auth['admin'])
        assert response.status_code==422


def test_partial_page_is_not_fully_studied(imported):
    app,c,s,folder,auth,pages=imported
    c.post('/api/entities',json={'kind':'research_task','title':'Часть страницы','data':{'viewed_page_ids':[pages[0]['id']],'sources':[{'page_id':pages[0]['id'],'crop':{'x':0,'y':0,'width':10,'height':10}}]}},headers=auth['researcher'])
    report=c.get('/api/cases/gakk-801-40-98/progress',headers=auth['viewer']).json()
    assert report['studied']==0 and report['partial']==1 and report['unviewed']==1


def test_living_person_never_appears_in_github_search(env):
    app,c,s,folder,auth=env
    c.post('/api/entities',json={'kind':'person','title':'Чувствительный человек','living':True,'data':{}},headers=auth['researcher'])
    response=c.post('/api/protocol',json={'request_id':str(uuid.uuid4()),'operation':'search','query':'Чувствительный'},headers=auth['admin']).json()
    assert response['results']==[]


def test_changed_original_is_not_silently_used_for_old_evidence(imported):
    app,c,s,folder,auth,pages=imported
    entity=c.post('/api/entities',json={'kind':'transcription','title':'Прежний источник','data':{'text':'Текст','sources':[{'page_id':pages[0]['id']}]}},headers=auth['researcher']).json()
    assert entity['data']['sources'][0]['sha256']==pages[0]['sha256']
    Image.new('RGB',(600,400),'blue').save(folder/'scan_0057.jpg')
    assert c.get('/api/pages/'+pages[0]['id']+'/image',headers=auth['viewer']).status_code==409
    c.post('/api/imports',json={'path':str(folder)},headers=auth['admin'])
    response=c.post('/api/entities/'+entity['id']+'/review',json={'status':'confirmed','expected_version':1,'note':'Проверка'},headers=auth['researcher'])
    assert response.status_code==409
