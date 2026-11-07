"""Bounded JPEG copies for signed HTTPS and private GitHub byte delivery."""
import base64
import hashlib
import io
import json
import re
import subprocess
import time
from PIL import Image
from fastapi import HTTPException
from sqlalchemy import select
from ..models import Link, Page, Message
from ..security.links import issue, consume, signature
from .storage import original, render, validate_crop

MAX_BYTES = 2_000_000
MAX_ACTIVE = 32
MAX_GITHUB_DAILY_BYTES = 20_000_000
NAME = re.compile(r'payload-[a-f0-9-]{36}\.jpg')


def cleanup(db, settings):
    folder = settings.data_dir / 'image-payloads'
    if not folder.exists():
        return
    # Grace covers an in-progress generation whose DB transaction has not committed.
    live = {link.params['_payload']['file'] for link in db.scalars(select(Link).where(Link.expires > time.time(), Link.revoked == False)) if '_payload' in link.params}
    for path in folder.iterdir():
        if (NAME.fullmatch(path.name) or path.name.endswith('.jpg.tmp')) and path.is_file() and not path.is_symlink():
            if path.name not in live and path.stat().st_mtime < time.time() - 120:
                path.unlink(missing_ok=True)


def direct_origin():
    """Optional Windows Funnel address; failure does not break local delivery."""
    try:
        result = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, timeout=3, check=True)
        host = json.loads(result.stdout)['Self']['DNSName'].rstrip('.')
        if re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.ts\.net', host):
            return 'https://' + host
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        pass
    return None


def prepare(db, settings, secret, request):
    page = db.get(Page, request.page_id)
    if not page:
        raise HTTPException(404, 'Страница не найдена')
    active = sum('_payload' in link.params for link in db.scalars(select(Link).where(Link.expires > time.time(), Link.revoked == False)))
    if active >= MAX_ACTIVE:
        raise HTTPException(429, 'Лимит 32 активных изображений. Дождитесь истечения ссылок или отзовите их.')
    params = {'output_max_width': request.output_max_width, 'quality': request.quality}
    if request.variant == 'crop':
        params.update({name: getattr(request, name) for name in ('x', 'y', 'width', 'height')})
        validate_crop(page, params)
    # Permission is checked before reading the source. The signed params are finalized below.
    permission = issue(db, settings, secret, page, request.variant, params)
    link = db.get(Link, permission['link_id'])
    source = original(settings, page)
    with source.open('rb') as stream:
        source_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    if source_sha != page.sha256:
        raise HTTPException(409, 'Контрольная сумма исходного JPG изменилась. Повторите импорт.')
    # Even variant=original is a bounded reading copy, never a full-resolution archive export.
    data = render(settings, page, request.variant, params)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, 'Изображение превышает 2 МБ. Запросите меньшую вырезку или output_max_width. Качество автоматически не снижается.')
    with Image.open(io.BytesIO(data)) as image:
        width, height = image.size
    github = request.delivery == 'github_base64'
    if github:
        used = sum(m.response.get('image_payload', {}).get('bytes', 0)
                   for m in db.scalars(select(Message).where(Message.created > time.time() - 86400))
                   if m.response.get('image_payload', {}).get('base64_in_github'))
        if used + len(data) > MAX_GITHUB_DAILY_BYTES:
            raise HTTPException(429, 'Лимит передачи изображений в GitHub: 20 МБ за 24 часа. Запросите меньшую вырезку или используйте delivery=https.')
    metadata = {'file': f'payload-{request.request_id}.jpg', 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'width': width, 'height': height}
    link.params = {**link.params, '_payload': metadata}
    db.flush()
    token = link.id + '.' + signature(secret, link)
    path = f'/ai/images/{page.id}/payload/{token}.jpg'
    folder = settings.data_dir / 'image-payloads'
    folder.mkdir(exist_ok=True)
    target = folder / metadata['file']
    temp = target.with_suffix('.jpg.tmp')
    try:
        temp.write_bytes(data)
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    origin = direct_origin()
    parts = []
    if github:
        for index, offset in enumerate(range(0, len(data), request.part_bytes)):
            chunk = data[offset:offset + request.part_bytes]
            parts.append({'index': index, 'offset': offset, 'bytes': len(chunk),
                          'sha256': hashlib.sha256(chunk).hexdigest(),
                          'path': f'responses/images/{request.request_id}/part-{index:04d}.json'})
    return {'delivery': 'github_base64_parts' if github else 'temporary_https_jpeg', 'base64_in_github': github,
            'encoding': 'base64' if github else None, 'parts': parts, 'part_count': len(parts),
            'git_history_retains_bytes': github,
            'compatibility': 'decode_parts_to_jpeg_then_use_file_vision_tool; ordinary_chat_visual_test_pending' if github else 'requires_image_fetch_tool; ordinary_chat_visual_test_pending',
            'page_id': page.id, 'jpg_number': page.jpg_number, 'source_sha256': source_sha,
            **{k: v for k, v in metadata.items() if k != 'file'}, 'mime_type': 'image/jpeg',
            'url': settings.public_api_url.rstrip('/') + path,
            'direct_url': origin + path if origin else None,
            'link_id': link.id, 'expires': link.expires, 'max_gets': link.max_hits,
            'head_counts_as_get': False, 'request': request.model_dump(mode='json')}


def github_files(db, settings, secret, response):
    """Build all parts; worker publishes them and the manifest in one commit."""
    payload = response['image_payload']
    link = db.get(Link, payload['link_id'])
    if not link:
        raise HTTPException(410, 'Разрешение не найдено')
    consume(db, secret, payload['page_id'], link.id + '.' + signature(secret, link), count_hit=False)
    data = read(settings, link.params)
    if hashlib.sha256(data).hexdigest() != payload['sha256']:
        raise HTTPException(409, 'Контрольная сумма payload не совпала')
    files = {}
    for part in payload['parts']:
        chunk = data[part['offset']:part['offset'] + part['bytes']]
        if hashlib.sha256(chunk).hexdigest() != part['sha256']:
            raise HTTPException(409, 'Контрольная сумма части не совпала')
        files[part['path']] = {'request_id': response['request_id'], 'encoding': 'base64',
                               **{k: v for k, v in part.items() if k != 'path'},
                               'data': base64.b64encode(chunk).decode('ascii')}
    files[f'responses/images/{response["request_id"]}.json'] = response
    return files


def read(settings, params):
    info = params['_payload']
    if not NAME.fullmatch(info['file']):
        raise HTTPException(403, 'Неверный ресурс')
    path = settings.data_dir / 'image-payloads' / info['file']
    if not path.is_file() or path.is_symlink():
        raise HTTPException(410, 'Временная копия удалена. Запросите renew_image_links.')
    if path.stat().st_size > MAX_BYTES:
        raise HTTPException(409, 'Временная копия повреждена')
    data = path.read_bytes()
    if len(data) != info['bytes'] or hashlib.sha256(data).hexdigest() != info['sha256']:
        raise HTTPException(409, 'Контрольная сумма временной копии не совпала')
    return data
