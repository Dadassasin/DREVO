from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from app.config import Settings
from app.main import create_app
from app.models import AccessCode
from app.security.auth import hasher


@pytest.fixture
def env(tmp_path):
    archive = tmp_path / 'archive'
    folder = archive / 'GAKK_F801_Op40_D98_909927385'
    folder.mkdir(parents=True)
    Image.new('RGB', (600, 400), 'white').save(folder / 'scan_0057.jpg')
    Image.new('RGB', (500, 300), 'gray').save(folder / 'scan_0058.png')
    settings = Settings(archive_root=archive, data_dir=tmp_path / 'data', public_api_url='https://archive.example', _env_file=None)
    app = create_app(settings, initialize=True)
    with app.state.factory() as db:
        for role in ('admin', 'researcher', 'viewer'):
            db.add(AccessCode(role=role, hash=hasher.hash(role + '-secret-code')))
        db.commit()
    with TestClient(app) as client:
        tokens = {role: client.post('/api/auth/login', json={'code': role + '-secret-code'}).json()['token'] for role in ('admin', 'researcher', 'viewer')}
        yield app, client, settings, folder, {role: {'Authorization': 'Bearer ' + token} for role, token in tokens.items()}


@pytest.fixture
def imported(env):
    app, client, settings, folder, auth = env
    result = client.post('/api/imports', json={'path': str(folder)}, headers=auth['admin'])
    assert result.status_code == 200, result.text
    pages = client.get('/api/cases/gakk-801-40-98/pages', headers=auth['viewer']).json()['items']
    return (*env, pages)
