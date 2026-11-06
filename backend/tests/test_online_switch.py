import importlib.util
import json
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('switch_online',ROOT/'scripts/switch_online.py')
switch=importlib.util.module_from_spec(spec)
spec.loader.exec_module(switch)


def test_upload_contains_only_frontend_and_routes_to_current_pc(tmp_path):
    root=tmp_path/'project'
    source=root/'frontend'
    (source/'src').mkdir(parents=True)
    for name in ('index.html','package.json','package-lock.json','tsconfig.json','vite.config.ts'):
        (source/name).write_text('public',encoding='utf-8')
    (source/'src/main.tsx').write_text('public',encoding='utf-8')
    (source/'vercel.json').write_text((ROOT/'frontend/vercel.json').read_text(),encoding='utf-8')
    (source/'.env.local').write_text('SECRET',encoding='utf-8')
    (source/'.vercel').mkdir()
    (source/'.vercel/auth.json').write_text('TOKEN',encoding='utf-8')
    (root/'drevo.sqlite3').write_text('PRIVATE',encoding='utf-8')
    stage=tmp_path/'upload';stage.mkdir()
    origin='https://second-pc.tail12345.ts.net'
    switch.prepare_stage(root,origin,'https://site.example',stage)
    assert all(row['destination'].startswith(origin+'/') for row in json.loads((stage/'vercel.json').read_text())['rewrites'])
    assert json.loads((stage/'public/drevo-origin.json').read_text())=={'origin':origin}
    for file in stage.rglob('*'):
        if file.is_file(): assert not any(secret in file.read_text() for secret in ('SECRET','TOKEN','PRIVATE'))
    assert not (stage/'.env.local').exists() and not (stage/'.vercel').exists()


@pytest.mark.parametrize('origin',['http://pc.tail123.ts.net','https://pc.tail123.ts.net/evil','https://evil.example','https://user@pc.tail123.ts.net'])
def test_invalid_origin_rejected_before_upload(tmp_path,origin):
    with pytest.raises(ValueError): switch.prepare_stage(ROOT,origin,'https://site.example',tmp_path)


def test_switch_checks_remote_marker_instead_of_trusting_local_state(monkeypatch):
    monkeypatch.setattr(switch,'fetch_json',lambda url: {'origin':'https://other.tail123.ts.net'} if 'drevo-origin' in url else {'status':'ok'})
    assert not switch.already_active('https://site.example','https://this.tail123.ts.net')
    monkeypatch.setattr(switch,'fetch_json',lambda url: {'origin':'https://this.tail123.ts.net'} if 'drevo-origin' in url else {'status':'ok'})
    assert switch.already_active('https://site.example','https://this.tail123.ts.net')
