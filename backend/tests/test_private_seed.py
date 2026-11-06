import json
from app.cli import seed_demo


def test_family_seed_is_loaded_from_private_data_folder(env):
    app,c,settings,folder,auth=env
    path=settings.data_dir/'demo-seed.json'
    path.write_text(json.dumps([['private-test-person','Приватная тестовая персона','Техническая проверка приватной загрузки']],ensure_ascii=False),encoding='utf-8')
    seed_demo(settings)
    seed_demo(settings)
    people=c.get('/api/entities?kind=person',headers=auth['viewer']).json()
    assert len(people)==1
    assert people[0]['title']=='Приватная тестовая персона'
    assert people[0]['status']=='needs_review'
