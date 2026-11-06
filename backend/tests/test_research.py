import time
import uuid
from urllib.parse import urlsplit
from sqlalchemy import select
from fastapi.testclient import TestClient
from app.main import create_app
from app.models import Link, Entity, Message
from app.services.backup import backup, restore


def protocol(c, auth, **fields):
    fields.setdefault('request_id', str(uuid.uuid4()))
    return c.post('/api/protocol', json=fields, headers=auth['admin'])


def test_signed_links_permissions_tamper_expiry_revocation(imported):
    app, c, settings, folder, auth, pages = imported
    page = pages[0]
    request = {'operation': 'get_pages', 'case_id': page['case_id'], 'page_numbers': ['0057']}
    assert protocol(c, auth, **request).json()['http_status'] == 403
    assert c.patch('/api/cases/' + page['case_id'], json={'publication': 'signed_links_allowed'}, headers=auth['admin']).status_code == 422
    c.patch('/api/cases/' + page['case_id'], json={'publication': 'signed_links_allowed', 'rights_checked': True}, headers=auth['admin'])
    result = protocol(c, auth, **request).json()
    link = result['pages'][0]
    url = urlsplit(link['url'])
    address = url.path + '?' + url.query
    assert c.get(address).status_code == 200
    assert c.get(address).status_code == 200
    assert c.get(url.path).status_code == 403
    assert c.get(address + 'x').status_code == 403
    assert c.get(address.replace(page['id'], pages[1]['id'])).status_code == 403
    crop_result = protocol(c, auth, operation='get_crop', page_id=page['id'], x=10, y=20, width=30, height=40).json()
    assert crop_result['pages'][0]['crop']['x'] == 10
    with app.state.factory() as db:
        row = db.get(Link, link['link_id'])
        row.created -= 4000
        row.expires -= 4000
        db.commit()
    # Re-signed expired URL tests the time check, rather than the tamper check.
    from app.security.links import signature
    with app.state.factory() as db:
        row = db.get(Link, link['link_id'])
        expired = url.path + '?token=' + row.id + '.' + signature(app.state.secret, row)
    assert c.get(expired).status_code == 410
    renewed = protocol(c, auth, operation='renew_image_links', renew_request_id=result['request_id']).json()['pages'][0]
    renewed_url = urlsplit(renewed['url'])
    assert c.get(renewed_url.path + '?' + renewed_url.query).status_code == 200
    c.post('/api/links/' + renewed['link_id'] + '/revoke', headers=auth['admin'])
    assert c.get(renewed_url.path + '?' + renewed_url.query).status_code == 403
    c.post('/api/links/revoke-all', headers=auth['admin'])


def test_inbox_idempotence_conflicts_sources_review_and_search(imported):
    app, c, s, folder, auth, pages = imported
    source = {'page_id': pages[0]['id'], 'crop': {'x': 1, 'y': 1, 'width': 100, 'height': 100}}
    raw = {'operation_id': str(uuid.uuid4()), 'operation': 'save_transcription', 'title': 'Макуха Андрей', 'data': {'text': 'Макуха', 'uncertain': True, 'sources': [source]}}
    first = c.post('/api/protocol', json=raw, headers=auth['admin']).json()
    assert first['status'] == 'needs_review'
    assert c.post('/api/protocol', json=raw, headers=auth['admin']).json() == first
    changed = dict(raw, title='Мануха')
    assert c.post('/api/protocol', json=changed, headers=auth['admin']).json()['status'] == 'conflicted'
    assert len(c.get('/api/entities?kind=transcription', headers=auth['viewer']).json()) == 1
    identifier = first['entity_id']
    reviewed = c.post(f'/api/entities/{identifier}/review', json={'status': 'confirmed', 'expected_version': 1, 'note': 'Проверено по вырезке'}, headers=auth['researcher'])
    assert reviewed.status_code == 200, reviewed.text
    assert c.post(f'/api/entities/{identifier}/review', json={'status': 'rejected', 'expected_version': 1, 'note': 'Старая версия'}, headers=auth['researcher']).status_code == 409
    correction = {'operation_id': str(uuid.uuid4()), 'operation': 'propose_correction', 'entity_id': identifier, 'expected_version': 1, 'title': 'Изменение', 'data': {'text': 'Мануха', 'sources': [source]}}
    assert c.post('/api/protocol', json=correction, headers=auth['admin']).json()['status'] == 'conflicted'
    assert c.get('/api/entities/' + identifier, headers=auth['viewer']).json()['data']['text'] == 'Макуха'
    assert len(c.get('/api/entities?q=Макуха', headers=auth['viewer']).json()) == 1
    assert c.get('/api/entities?q=Махуха&fuzzy=true', headers=auth['viewer']).json()
    assert c.post('/api/entities', json={'kind': 'record', 'title': 'Нет источника', 'data': {}}, headers=auth['researcher']).status_code == 422
    assert c.post('/api/entities', json={'kind': 'transcription', 'title': 'Сомнение', 'data': {'uncertain': True, 'sources': [{'page_id': pages[0]['id']}]}}, headers=auth['researcher']).status_code == 422
    bad_date = {'kind': 'person', 'title': 'Дата', 'data': {'dates': [{'original': '1918', 'calendar': 'unknown', 'modern_equivalent': '1918-01-01'}]}}
    assert c.post('/api/entities', json=bad_date, headers=auth['researcher']).status_code == 422


def test_progress_restart_backup_restore(imported, tmp_path):
    app, c, settings, folder, auth, pages = imported
    raw = {'operation_id': str(uuid.uuid4()), 'operation': 'save_research_progress', 'title': 'Найти родителей', 'data': {'goal': 'Исследовать', 'viewed_page_ids': [pages[0]['id']], 'studied_page_ids': [], 'next_action': 'Проверить страницу целиком'}}
    result = c.post('/api/protocol', json=raw, headers=auth['admin']).json()
    identifier = result['entity_id']
    saved = backup(settings, tmp_path / 'saved.sqlite3')
    second = create_app(settings)
    with TestClient(second) as restarted:
        entity = restarted.get('/api/entities/' + identifier, headers=auth['viewer']).json()
        assert entity['data']['viewed_page_ids'] == [pages[0]['id']]
        assert not entity['data'].get('studied_page_ids')
    with app.state.factory() as db:
        entity = db.get(Entity, identifier)
        entity.title = 'changed'
        db.commit()
    restore(settings, saved)
    with app.state.factory() as db:
        assert db.get(Entity, identifier).title == 'Найти родителей'
    assert c.get('/api/me', headers=auth['viewer']).status_code == 401


def test_relationship_requires_evidence_and_confirmation(imported):
    _, c, _, _, auth, pages = imported
    people = [c.post('/api/entities', json={'kind': 'person', 'title': title, 'data': {}}, headers=auth['researcher']).json() for title in ('Отец', 'Сын')]
    relationship = c.post('/api/entities', json={'kind': 'relationship', 'title': 'Предполагаемый отец', 'data': {'from_person_id': people[0]['id'], 'to_person_id': people[1]['id'], 'relationship_type': 'parent'}}, headers=auth['researcher']).json()
    path = '/api/entities/' + relationship['id'] + '/review'
    assert c.post(path, json={'status': 'confirmed', 'expected_version': 1, 'note': 'Проверка'}, headers=auth['researcher']).status_code == 422
    assert c.post(path, json={'status': 'confirmed', 'expected_version': 1, 'note': 'Проверка', 'acknowledge_significant': True}, headers=auth['researcher']).status_code == 422


def test_human_can_apply_versioned_correction_with_audit(imported):
    _,c,_,_,auth,pages=imported
    source={'page_id':pages[0]['id']}
    record=c.post('/api/entities',json={'kind':'transcription','title':'Исходное прочтение','data':{'text':'Первое','sources':[source]}},headers=auth['researcher']).json()
    c.post('/api/entities/'+record['id']+'/review',json={'status':'confirmed','expected_version':1,'note':'Проверено'},headers=auth['researcher'])
    raw={'operation_id':str(uuid.uuid4()),'operation':'propose_correction','entity_id':record['id'],'expected_version':2,'title':'Исправление чтения','data':{'text':'Уточнённое','sources':[source]}}
    proposed=c.post('/api/protocol',json=raw,headers=auth['admin']).json()
    assert proposed['status']=='proposed'
    url='/api/entities/'+proposed['entity_id']+'/review'
    review={'status':'confirmed','expected_version':1,'note':'Повторно сверено по оригиналу'}
    assert c.post(url,json=review,headers=auth['researcher']).status_code==422
    review['acknowledge_significant']=True
    assert c.post(url,json=review,headers=auth['researcher']).status_code==200
    corrected=c.get('/api/entities/'+record['id'],headers=auth['viewer']).json()
    assert corrected['data']['text']=='Уточнённое' and corrected['version']==3
    assert len(corrected['history'])==3
