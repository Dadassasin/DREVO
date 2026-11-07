import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path
from fastapi import HTTPException
from sqlalchemy import update
from ..models import Case, Link, Page, State, AuditEvent


def allow_page_temporarily(db, page, reason, minutes=30):
    """Local operator grant for one explicitly requested scan; case stays private."""
    if not 1 <= minutes <= 30 or not reason.strip():
        raise ValueError('Укажите причину и срок от 1 до 30 минут')
    value = {'id': secrets.token_urlsafe(24), 'expires': time.time() + minutes * 60,
             'sha256': page.sha256, 'operations': ['original', 'crop'], 'reason': reason}
    name = 'page_sharing_grant:' + page.id
    row = db.get(State, name)
    if row:
        row.value = value
    else:
        db.add(State(key=name, value=value))
    db.add(AuditEvent(entity_id=page.id, action='temporary_page_sharing', author='local_operator',
                      details={'expires': value['expires'], 'operations': value['operations'], 'reason': reason}))
    db.flush()
    return value


def page_grant(db, page, operation):
    row = db.get(State, 'page_sharing_grant:' + page.id)
    value = row.value if row else {}
    if value.get('expires', 0) > time.time() and value.get('sha256') == page.sha256 and operation in value.get('operations', []):
        return value
    return None


def key(settings):
    path = settings.data_dir / 'signing.key'
    try:
        with path.open('xb') as stream:
            stream.write(secrets.token_bytes(64))
    except FileExistsError:
        pass
    return path.read_bytes()


def signature(secret, link):
    payload = json.dumps([link.id, link.page_id, link.operation, link.params, link.created, link.expires], sort_keys=True, separators=(',', ':'))
    return base64.urlsafe_b64encode(hmac.new(secret, payload.encode(), hashlib.sha256).digest()).decode().rstrip('=')


def issue(db, settings, secret, page, operation='original', params=None):
    case = db.get(Case, page.case_id)
    grant = None
    if case.publication not in ('signed_links_allowed', 'public_allowed'):
        grant = page_grant(db, page, operation)
        if not grant:
            raise HTTPException(403, 'Выдача копий для этого дела не разрешена. Проверьте условия использования и настройки приватности.')
    if not settings.public_api_url.startswith('https://'):
        raise HTTPException(409, 'Для внешних ссылок задайте HTTPS-адрес API')
    signed_params = {**(params or {}), '_sha256': page.sha256}
    expires = time.time() + settings.link_minutes * 60
    if grant:
        signed_params['_grant_id'] = grant['id']
        expires = min(expires, grant['expires'])
    link = Link(page_id=page.id, operation=operation, params=signed_params, expires=expires)
    db.add(link)
    db.flush()
    token = link.id + '.' + signature(secret, link)
    resource = 'crops' if operation == 'crop' else 'images'
    return {'link_id': link.id, 'url': f'{settings.public_api_url}/ai/{resource}/{page.id}?token={token}', 'expires': link.expires}


def consume(db, secret, page_id, token, *, count_hit=True):
    try:
        identifier, signed = token.split('.', 1)
    except ValueError:
        raise HTTPException(403, 'Неверная подпись')
    link = db.get(Link, identifier)
    if not link or not hmac.compare_digest(signature(secret, link), signed) or link.page_id != page_id:
        raise HTTPException(403, 'Неверная подпись')
    if link.expires <= time.time():
        raise HTTPException(410, 'Срок ссылки истёк. Запросите renew_image_links.')
    page = db.get(Page, page_id)
    if not page:
        raise HTTPException(403, 'Выдача копий отключена')
    if '_grant_id' in link.params:
        grant = page_grant(db, page, link.operation)
        if not grant or grant['id'] != link.params['_grant_id']:
            raise HTTPException(403, 'Разрешение на выбранную страницу отозвано или истекло')
    elif db.get(Case, page.case_id).publication == 'private_only':
        raise HTTPException(403, 'Выдача копий отключена')
    if link.params.get('_sha256') != page.sha256:
        raise HTTPException(403, 'Источник изменён после выдачи ссылки. Запросите новое разрешение.')
    if link.revoked or link.hits >= link.max_hits:
        raise HTTPException(403, 'Ссылка отозвана или достигнут лимит запросов')
    if count_hit:
        result = db.execute(update(Link).where(Link.id == identifier, Link.revoked == False, Link.hits < Link.max_hits).values(hits=Link.hits + 1))
        if result.rowcount != 1:
            raise HTTPException(403, 'Ссылка отозвана или достигнут лимит запросов')
        db.commit()
    return link
