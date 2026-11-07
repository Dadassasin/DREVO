"""Real GitHub -> home disk -> signed JPEG -> proposed SQLite receipt test.

Private URLs and image bytes stay in ignored .local/qa. No genealogical reading is asserted.
"""
import argparse
import hashlib
import io
import json
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
from app.config import Settings
from app.db import make_db
from app.github_sync.client import GitHubClient
from app.images.payloads import direct_origin
from app.images.storage import original, render
from app.models import Page, Link, Message, Entity, State
from app.services.entities import serialize
from sqlalchemy import select
from decode_image_payload import assemble

REPORT = ROOT / '.local/qa/image-delivery.json'
PAGES = ['fc8804986f8a240b4b0736dda59a0456', 'e5a194c8f74a08f5d5fe9ce610474d4a']


def save(report):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def confirmed_digest(factory):
    with factory() as db:
        rows = [serialize(e) for e in db.scalars(select(Entity).where(Entity.status == 'confirmed').order_by(Entity.id))]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def wait_read(client, path):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            return client.read(path)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
        print('Waiting for automatic worker:', path, flush=True)
        time.sleep(10)
    raise TimeoutError(path)


def prepare(client, factory):
    report = {'created_at': time.time(), 'confirmed_before': confirmed_digest(factory), 'requests': [], 'visual_chat_status': 'PENDING'}
    for page in PAGES:
        raw = {'schema_version': '1.0', 'request_id': str(uuid.uuid4()), 'operation': 'get_image_payload',
               'page_id': page, 'delivery': 'github_base64', 'variant': 'crop', 'x': 0, 'y': 100, 'width': 2500,
               'height': 1400 if page == PAGES[0] else 1000, 'output_max_width': 2500, 'quality': 90}
        client.write('requests/images/' + raw['request_id'] + '.json', raw)
        report['requests'].append(raw)
    operation = {'schema_version': '1.0', 'operation_id': str(uuid.uuid4()), 'operation': 'save_research_progress',
                 'title': 'Технический тест доставки JPG 0056–0057',
                 'data': {'goal': 'Проверить передачу пикселей; это не расшифровка документа.',
                          'sources': [{'page_id': page} for page in PAGES],
                          'viewed_page_ids': [], 'studied_page_ids': [],
                          'next_action': 'Проверить чтение настоящего JPEG инструментом обычного ChatGPT.'}, 'living': False}
    client.write('inbox/progress/' + operation['operation_id'] + '.json', operation)
    report['proposal_operation_id'] = operation['operation_id']
    save(report)
    print('Created two image requests and one technical proposed research task in PRIVATE GitHub.', flush=True)


def verify(client, factory, settings):
    report = json.loads(REPORT.read_text(encoding='utf-8'))
    results = []
    with httpx.Client(timeout=45, follow_redirects=False) as http:
        for raw in report['requests']:
            response = wait_read(client, 'responses/images/' + raw['request_id'] + '.json')
            assert response['status'] == 'completed', response
            p = response['image_payload']
            with factory() as db:
                page = db.get(Page, raw['page_id'])
                with original(settings, page).open('rb') as stream:
                    assert hashlib.file_digest(stream, 'sha256').hexdigest() == p['source_sha256'] == page.sha256
                expected = render(settings, page, 'crop', {name: raw[name] for name in ('x', 'y', 'width', 'height', 'output_max_width', 'quality')})
                before = db.get(Link, p['link_id']).hits
            routes = []
            for name, url in [('funnel', p['direct_url']), ('vercel', p['url'])]:
                assert url, 'Direct Funnel URL missing'
                head = http.head(url)
                assert head.status_code == 200 and not head.content
                with factory() as db:
                    after_head = db.get(Link, p['link_id']).hits
                    assert after_head == before
                image = http.get(url)
                assert image.status_code == 200 and not image.history
                assert image.headers['content-type'] == 'image/jpeg'
                assert int(head.headers['content-length']) == len(image.content) == p['bytes']
                assert hashlib.sha256(image.content).hexdigest() == p['sha256'] == hashlib.sha256(expected).hexdigest()
                assert Image.open(io.BytesIO(image.content)).size == (p['width'], p['height'])
                (REPORT.parent / ('payload-' + p['jpg_number'] + '.jpg')).write_bytes(image.content)
                with factory() as db:
                    after_get = db.get(Link, p['link_id']).hits
                    assert after_get == before + 1
                routes.append({'route': name, 'head_status': head.status_code, 'get_status': image.status_code,
                               'headers': {key: image.headers.get(key) for key in ('content-type', 'content-length', 'content-disposition', 'cache-control', 'cdn-cache-control', 'location')},
                               'hits_before': before, 'hits_after_head': after_head, 'hits_after_get': after_get})
                before = after_get
            results.append({'request_id': raw['request_id'], 'image_payload': p, 'source_and_crop_sha256_verified': True, 'routes': routes})
    receipt = wait_read(client, 'outbox/receipts/' + report['proposal_operation_id'] + '.json')
    with factory() as db:
        message = db.get(Message, report['proposal_operation_id'])
        entity = db.get(Entity, receipt['entity_id'])
        assert message.response == receipt
        assert entity.status == receipt['status'] == 'proposed' and entity.kind == 'research_task'
        assert entity.title.startswith('Технический тест доставки')
        assert not entity.data.get('viewed_page_ids') and not entity.data.get('studied_page_ids')
        report['sync'] = db.get(State, 'sync').value
    report.update(verified_at=time.time(), results=results, sqlite_receipt=receipt,
                  confirmed_data_unchanged=confirmed_digest(factory) == report['confirmed_before'])
    assert report['confirmed_data_unchanged']
    save(report)
    print(json.dumps({'images': len(results), 'direct_and_vercel': '200 JPEG; HEAD no hits', 'source_and_render_sha256': 'MATCH', 'sqlite': receipt['status'], 'confirmed_data_unchanged': True, 'visual_chat_status': 'PENDING'}), flush=True)


def diagnose(client, factory, settings):
    response = client.read('responses/pages/278d9d72-9c91-4d19-8d98-bfba825ae324.json')
    origin = direct_origin()
    result = []
    with httpx.Client(timeout=40, follow_redirects=False) as http:
        for page in response['pages']:
            url = urlsplit(page['url'])
            for name, address in [('vercel', page['url']), ('funnel', origin + urlunsplit(('', '', url.path, url.query, '')))]:
                head = http.head(address)
                get = http.get(address)
                result.append({'jpg': page['jpg_number'], 'route': name, 'head': head.status_code, 'get': get.status_code,
                               'bytes': len(get.content), 'redirects': len(get.history),
                               'headers': {key: get.headers.get(key) for key in ('content-type', 'content-length', 'content-disposition', 'cache-control', 'location')},
                               'seconds_remaining': round(page['expires'] - time.time())})
    path = REPORT.with_name('image-http-diagnostic-' + str(int(time.time())) + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)


def verify_bytes(client, factory, settings):
    """Download bytes ONLY through authenticated GitHub JSON, never image URLs."""
    report = json.loads(REPORT.read_text(encoding='utf-8'))
    results = []
    for raw in report['requests']:
        response = wait_read(client, 'responses/images/' + raw['request_id'] + '.json')
        assert response['status'] == 'completed', response
        p = response['image_payload']
        downloaded = {}
        def load(path):
            value = client.read(path)
            downloaded[path] = value
            return value
        data = assemble(response, load)
        with factory() as db:
            page = db.get(Page, raw['page_id'])
            with original(settings, page).open('rb') as stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == p['source_sha256'] == page.sha256
            expected = render(settings, page, raw['variant'], {name: raw[name] for name in ('x', 'y', 'width', 'height', 'output_max_width', 'quality')})
            assert hashlib.sha256(data).hexdigest() == hashlib.sha256(expected).hexdigest()
            hits = db.get(Link, p['link_id']).hits
        assert Image.open(io.BytesIO(data)).size == (p['width'], p['height'])
        (REPORT.parent / ('github-payload-' + p['jpg_number'] + '.jpg')).write_bytes(data)
        # Offline decoder artifacts for a client with a file/vision tool.
        folder = REPORT.parent / ('github-parts-' + p['jpg_number']); folder.mkdir(exist_ok=True)
        (folder / 'response.json').write_text(json.dumps(response), encoding='utf-8')
        for path, value in downloaded.items():
            (folder / Path(path).name).write_text(json.dumps(value), encoding='utf-8')
        results.append({'request_id': raw['request_id'], 'image_payload': p,
                        'downloaded_via': 'private_github_json_only', 'decoded_parts': len(downloaded),
                        'source_and_crop_sha256_verified': True, 'https_image_get_hits': hits})
        print('Decoded real JPG', p['jpg_number'], 'from', len(downloaded), 'GitHub JSON parts;', len(data), 'bytes', flush=True)
    receipt = wait_read(client, 'outbox/receipts/' + report['proposal_operation_id'] + '.json')
    with factory() as db:
        assert db.get(Message, report['proposal_operation_id']).response == receipt
        entity = db.get(Entity, receipt['entity_id'])
        assert entity.status == 'proposed' and entity.kind == 'research_task'
        report['sync'] = db.get(State, 'sync').value
    report.update(verified_at=time.time(), results=results, sqlite_receipt=receipt,
                  byte_transport='WORKING', visual_chat_status='PENDING',
                  confirmed_data_unchanged=confirmed_digest(factory) == report['confirmed_before'])
    assert report['confirmed_data_unchanged']
    save(report)
    print('GitHub bytes verified; proposed SQLite receipt verified; confirmed data unchanged.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'verify', 'verify-bytes', 'diagnose'])
    action = parser.parse_args().action
    settings = Settings(); engine, factory = make_db(settings)
    client = GitHubClient(settings)
    try:
        client.private_check()
        if action == 'prepare': prepare(client, factory)
        elif action == 'verify': verify(client, factory, settings)
        elif action == 'verify-bytes': verify_bytes(client, factory, settings)
        else: diagnose(client, factory, settings)
    finally:
        client.close(); engine.dispose()


if __name__ == '__main__':
    main()
