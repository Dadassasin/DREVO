import time
from urllib.parse import urlsplit
import pytest
from fastapi import HTTPException
from app.models import Page,Case,State
from app.security.links import allow_page_temporarily,issue


def test_temporary_grant_does_not_open_case_or_other_page(imported):
    app,client,settings,folder,auth,pages=imported
    with app.state.factory() as db:
        first=db.get(Page,pages[0]['id']);second=db.get(Page,pages[1]['id'])
        grant=allow_page_temporarily(db,first,'Explicit single-page test',1)
        link=issue(db,settings,app.state.secret,first)
        assert link['expires']<=grant['expires']
        with pytest.raises(HTTPException): issue(db,settings,app.state.secret,second)
        assert db.get(Case,first.case_id).publication=='private_only'
        db.commit()
    parsed=urlsplit(link['url'])
    assert client.get(parsed.path+'?'+parsed.query).status_code==200
    assert client.get(parsed.path).status_code==403


def test_replacement_grant_does_not_revive_previous_permission(imported):
    app,client,settings,folder,auth,pages=imported
    with app.state.factory() as db:
        page=db.get(Page,pages[0]['id'])
        allow_page_temporarily(db,page,'First authorization')
        old=issue(db,settings,app.state.secret,page)
        allow_page_temporarily(db,page,'New authorization')
        current=issue(db,settings,app.state.secret,page)
        db.commit()
    def get(link):
        p=urlsplit(link['url']);return client.get(p.path+'?'+p.query)
    assert get(old).status_code==403
    assert get(current).status_code==200
    with app.state.factory() as db:
        row=db.get(State,'page_sharing_grant:'+pages[0]['id'])
        row.value={**row.value,'expires':time.time()-1};db.commit()
    assert get(current).status_code==403


def test_temporary_grant_allows_only_original_and_crop(imported):
    app,client,settings,folder,auth,pages=imported
    with app.state.factory() as db:
        page=db.get(Page,pages[0]['id']);allow_page_temporarily(db,page,'Explicit resource scope')
        with pytest.raises(HTTPException): issue(db,settings,app.state.secret,page,'preview')
        link=issue(db,settings,app.state.secret,page,'crop',{'x':1,'y':2,'width':50,'height':60})
        db.commit()
    p=urlsplit(link['url']);assert client.get(p.path+'?'+p.query).status_code==200
