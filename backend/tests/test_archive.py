import hashlib
import io
import shutil
import time
import zipfile
from PIL import Image
from sqlalchemy import select
from app.models import ImportRun, Page, Case, Session


def test_auth_roles_and_private_images(imported):
    app, c, s, folder, auth, pages = imported
    assert c.get('/api/cases').status_code == 401
    assert c.get('/api/pages/' + pages[0]['id'] + '/image').status_code == 401
    assert c.post('/api/auth/login', json={'code': 'wrong'}).status_code == 401
    assert c.post('/api/imports', json={'path': str(folder)}, headers=auth['viewer']).status_code == 403
    assert c.post('/api/entities', json={'kind': 'person', 'title': 'Test', 'data': {}}, headers=auth['viewer']).status_code == 403
    assert c.get('/api/me', headers=auth['researcher']).json()['role'] == 'researcher'
    for _ in range(9):
        response = c.post('/api/auth/login', json={'code': 'wrong'})
    assert response.status_code == 429
    with app.state.factory() as db:
        db.query(Session).update({'expires': time.time() - 1})
        db.commit()
    assert c.get('/api/cases', headers=auth['viewer']).status_code == 401


def test_reference_incremental_duplicate_and_images(imported):
    app, c, s, folder, auth, pages = imported
    assert len(pages) == 2
    assert pages[0]['jpg_number'] == '0057'
    assert pages[0]['book_page'] is None
    assert 'path' not in pages[0]
    path = '/api/pages/' + pages[0]['id']
    response = c.get(path + '/image?variant=original', headers=auth['viewer'])
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == pages[0]['sha256']
    assert response.headers['cache-control'] == 'private, no-store'
    assert Image.open(io.BytesIO(c.get(path + '/image?variant=thumbnail', headers=auth['viewer']).content)).width <= 240
    crop = c.post(path + '/crop', json={'x': 10, 'y': 20, 'width': 100, 'height': 90}, headers=auth['viewer'])
    assert Image.open(io.BytesIO(crop.content)).size == (100, 90)
    for params in ({'x': 590, 'y': 0, 'width': 100, 'height': 50}, {'x': -1, 'y': 0, 'width': 10, 'height': 10}):
        assert c.post(path + '/crop', json=params, headers=auth['viewer']).status_code == 422
    c.post('/api/imports', json={'path': str(folder)}, headers=auth['admin'])
    last = c.get('/api/imports', headers=auth['admin']).json()[0]
    assert last['skipped'] == 2 and last['imported'] == 0
    shutil.copyfile(folder / 'scan_0057.jpg', folder / 'scan_0059.jpg')
    c.post('/api/imports', json={'path': str(folder)}, headers=auth['admin'])
    last = c.get('/api/imports', headers=auth['admin']).json()[0]
    assert last['duplicates'] == 1
    with app.state.factory() as db:
        assert db.scalar(select(Page).where(Page.jpg_number == '0059')).duplicate_of


def test_path_boundaries(env, tmp_path):
    app, c, s, folder, auth = env
    assert c.post('/api/imports', json={'path': str(tmp_path)}, headers=auth['admin']).status_code == 400
    assert c.post('/api/imports', json={'path': str(folder / '..' / '..' / '..')}, headers=auth['admin']).status_code == 400


def test_zip_reference_and_managed(env):
    app, c, s, folder, auth = env
    zip_path = s.archive_root / 'GAKK_F250_Op2_D98.zip'
    with zipfile.ZipFile(zip_path, 'w') as z:
        z.write(folder / 'scan_0057.jpg', 'nested/scan_0057.jpg')
    c.post('/api/imports', json={'path': str(zip_path)}, headers=auth['admin'])
    p = c.get('/api/cases/gakk-250-2-98/pages', headers=auth['viewer']).json()['items'][0]
    assert c.get(f'/api/pages/{p["id"]}/image?variant=original', headers=auth['viewer']).content == (folder / 'scan_0057.jpg').read_bytes()
    zip2 = s.archive_root / 'GAKK_F250_Op2_D99.zip'
    shutil.copyfile(zip_path, zip2)
    c.post('/api/imports', json={'path': str(zip2), 'mode': 'managed'}, headers=auth['admin'])
    with app.state.factory() as db:
        p2 = db.scalar(select(Page).where(Page.case_id == 'gakk-250-2-99'))
        assert p2.zip_member is None and 'managed' in p2.path


def test_zip_slip_bomb_and_corruption(env):
    app, c, s, folder, auth = env
    for name, member, content in [('slip.zip', '../escape.jpg', b'bad'), ('bomb.zip', 'bomb.jpg', b'0' * 1_000_000), ('broken.zip', 'image.jpg', b'not an image')]:
        path = s.archive_root / name
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(member, content)
        c.post('/api/imports', json={'path': str(path)}, headers=auth['admin'])
        result = c.get('/api/imports', headers=auth['admin']).json()[0]
        assert result['errors'] and result['imported'] == 0


def test_body_limit(env):
    _, c, _, _, auth = env
    assert c.post('/api/protocol', content=b'a' * 300000, headers=auth['admin']).status_code == 413
