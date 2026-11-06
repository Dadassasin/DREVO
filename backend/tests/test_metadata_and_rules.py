from sqlalchemy import select
from app.models import Case
from app.schemas.messages import HistoricalDate
import pytest


def test_sidecar_metadata_preserves_page_ids(imported):
    app,c,s,folder,auth,pages=imported
    (folder/'Описание.txt').write_text('Шифр: F801_Op40_D98\nНазвание: Метрическая книга за 1918 год\nСсылка: https://krdar.kaisa.ru/documents/909927385\n',encoding='utf-8')
    c.post('/api/imports',json={'path':str(folder)},headers=auth['admin'])
    result=c.get('/api/cases/gakk-801-40-98',headers=auth['viewer']).json()
    assert result['title']=='Метрическая книга за 1918 год'
    assert result['metadata_status']=='proposed'
    assert result['metadata_json']['source_url'].endswith('/909927385')
    assert c.get('/api/cases/gakk-801-40-98/pages',headers=auth['viewer']).json()['items'][0]['id']==pages[0]['id']


def test_editable_search_rules_reindex_without_changing_original(env):
    app,c,s,folder,auth=env
    entity=c.post('/api/entities',json={'kind':'person','title':'Матюх','data':{'text':'Оригинал Матюх'}},headers=auth['researcher']).json()
    assert c.get('/api/entities?q=Макуха',headers=auth['viewer']).json()==[]
    rules={'rules':[{'source':'матюх','target':'макуха'}]}
    assert c.patch('/api/search-rules',json=rules,headers=auth['viewer']).status_code==403
    assert c.patch('/api/search-rules',json=rules,headers=auth['admin']).status_code==200
    result=c.get('/api/entities?q=Макуха',headers=auth['viewer']).json()
    assert result[0]['id']==entity['id']
    assert result[0]['title']=='Матюх' and result[0]['data']['text']=='Оригинал Матюх'


def test_julian_gregorian_date_validation():
    assert HistoricalDate(original='29 февраля 1900',calendar='julian',year=1900,month=2,day=29).day==29
    with pytest.raises(ValueError):
        HistoricalDate(original='29 февраля 1900',calendar='gregorian',year=1900,month=2,day=29)
    with pytest.raises(ValueError):
        HistoricalDate(original='31 февраля',month=2,day=31)
