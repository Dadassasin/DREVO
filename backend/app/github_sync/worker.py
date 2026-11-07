import hashlib
import json
import re
import time
import httpx
from sqlalchemy import select
from ..config import Settings
from ..db import make_db
from ..models import State, Page
from ..security.links import key
from ..research.protocol import process, context
from .client import GitHubClient
from ..schemas.messages import PageRequest, InboxMessage, EntityInput

REQUEST_FOLDERS = {'pages', 'crops', 'search', 'research'}
INBOX_FOLDERS = {'records', 'transcriptions', 'people', 'relationships', 'findings', 'evidence', 'progress', 'research-progress', 'claims', 'annotations', 'hypotheses'}


def set_state(db, name, value):
    row = db.get(State, name)
    if row:
        row.value = value
    else:
        db.add(State(key=name, value=value))


def sync_once(factory, settings, secret, client=None):
    owned = client is None
    client = client or GitHubClient(settings)
    try:
        client.private_check()
        tree = client.tree()
        remote_shas = {item['path']: item['sha'] for item in tree.get('tree', []) if item.get('type') == 'blob'}

        def publish(path, value):
            raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
            blob_sha = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            with factory() as db:
                old = db.get(State, 'export:' + path)
                if old and old.value.get('sha') == blob_sha and remote_shas.get(path) == blob_sha:
                    return
            client.write(path, value)
            with factory() as db:
                set_state(db, 'export:' + path, {'sha': blob_sha})
                db.commit()
        handled = 0
        # Cursor is diagnostic; UUID receipts ensure safe retries even after partial writes.
        for blob in tree.get('tree', []):
            path = blob['path']
            parts = path.split('/')
            if blob.get('type') != 'blob' or len(parts) != 3 or not path.endswith('.json'):
                continue
            if not (parts[0] == 'requests' and parts[1] in REQUEST_FOLDERS or parts[0] == 'inbox' and parts[1] in INBOX_FOLDERS):
                continue
            if blob.get('size', 0) > settings.max_message_bytes:
                continue
            if handled >= 100:
                break
            with factory() as db:
                cursor = db.get(State, 'blob:' + path)
                if cursor and cursor.value.get('sha') == blob['sha']:
                    continue
            try:
                raw = client.read(path)
                if not isinstance(raw, dict):
                    raise ValueError('Сообщение должно быть JSON-объектом')
                if ('operation_id' in raw) != (parts[0] == 'inbox'):
                    raise ValueError('Тип сообщения не соответствует папке обмена')
                with factory() as db:
                    result = process(db, settings, secret, raw)
                    db.commit()
                if parts[0] == 'requests':
                    destination = f'responses/{parts[1]}/{result["request_id"]}.json'
                else:
                    destination = f'outbox/receipts/{result["request_id"]}.json'
                client.write(destination, result)
                if result['status'] == 'conflicted':
                    client.write(f'outbox/conflicts/{result["request_id"]}.json', result)
                with factory() as db:
                    set_state(db, 'blob:' + path, {'sha': blob['sha']})
                    db.commit()
                handled += 1
            except (ValueError, KeyError) as exc:
                error_id = hashlib.sha256((path + blob['sha']).encode()).hexdigest()[:32]
                client.write(f'outbox/receipts/invalid-{error_id}.json', {'status': 'error', 'path': path, 'error': str(exc)[:1000]})
                with factory() as db:
                    set_state(db, 'blob:' + path, {'sha': blob['sha']})
                    db.commit()
                handled += 1
        with factory() as db:
            exported = context(db, settings)
        # Stable shards permit incremental updates: unchanged files are not committed again.
        manifest = {'schema_version': '1.0', 'integration_status': 'unverified', 'catalog': 'outbox/research-context/catalog.json', 'entity_shards': [], 'studied_pages': 'outbox/research-context/studied-pages.json'}
        publish(manifest['studied_pages'], exported['studied_page_ids'])
        for case in exported['cases']:
            case['page_indexes'] = []
            with factory() as db:
                pages = db.scalars(select(Page).where(Page.case_id == case['id']).order_by(Page.jpg_number, Page.id)).all()
                for i in range(0, len(pages), 200):
                    path = f'outbox/research-context/pages-{case["id"]}-{i // 200:04d}.json'
                    case['page_indexes'].append(path)
                    value = [{'page_id': p.id, 'jpg_number': p.jpg_number, 'book_page': p.book_page, 'archival_leaf': p.archival_leaf, 'section': p.section, 'width': p.width, 'height': p.height, 'sha256': p.sha256} for p in pages[i:i+200]]
                    publish(path, value)
        publish(manifest['catalog'], exported['cases'])
        # Chunk by bytes as well as count; long transcriptions must remain readable via Contents API.
        shards, current, size = [], [], 0
        for entity in sorted(exported['entities'], key=lambda e: e['id']):
            entity_size = len(json.dumps(entity, ensure_ascii=False).encode())
            if current and (len(current) >= 50 or size + entity_size > 200000):
                shards.append(current)
                current, size = [], 0
            current.append(entity)
            size += entity_size
        if current:
            shards.append(current)
        for i, shard in enumerate(shards):
            path = f'outbox/research-context/entities-{i:04d}.json'
            manifest['entity_shards'].append(path)
            publish(path, shard)
        manifest['schemas'] = {}
        for name, model in (('request', PageRequest), ('inbox', InboxMessage), ('entity', EntityInput)):
            path = f'schemas/{name}.schema.json'
            manifest['schemas'][name] = path
            publish(path, model.model_json_schema())
        publish('manifest.json', manifest)
        for path in remote_shas:
            if re.fullmatch(r'outbox/research-context/entities-\d{4}\.json',path) and path not in manifest['entity_shards']:
                client.delete_entity_export(path)
        with factory() as db:
            set_state(db, 'sync', {'status': 'ok', 'last_sync': time.time(), 'last_commit': tree.get('sha'), 'handled': handled, 'integration_status': 'unverified'})
            db.commit()
        return {'status': 'ok', 'handled': handled}
    finally:
        if owned:
            client.close()


def main():
    settings = Settings()
    engine, factory = make_db(settings)
    secret = key(settings)
    backoff = settings.sync_seconds
    while True:
        try:
            if settings.github_repo and settings.github_token:
                sync_once(factory, settings, secret)
                backoff = settings.sync_seconds
            else:
                with factory() as db:
                    set_state(db, 'sync', {'status': 'not_configured', 'integration_status': 'unverified'})
                    db.commit()
        except Exception as exc:
            # Exception text may include GitHub URLs. Never log access headers or image tokens.
            with factory() as db:
                set_state(db, 'sync', {'status': 'error', 'error_type': type(exc).__name__, 'http_status': exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None, 'at': time.time(), 'integration_status': 'unverified'})
                db.commit()
            backoff = min(max(backoff * 2, 60), 3600)
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (403, 429):
                try:
                    retry = int(exc.response.headers.get('retry-after', '60'))
                    reset = int(exc.response.headers.get('x-ratelimit-reset', '0')) - int(time.time())
                    backoff = max(backoff, min(max(retry, reset), 7200))
                except ValueError:
                    pass
        time.sleep(max(backoff, 15))


if __name__ == '__main__':
    main()
