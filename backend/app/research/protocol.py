import hashlib
import json
import time
from fastapi import HTTPException
from sqlalchemy import select, func
from ..models import Page, Case, Entity, Message, AuditEvent
from ..schemas.messages import PageRequest, InboxMessage, EntityInput
from ..security.links import issue
from ..images.storage import validate_crop
from ..images.payloads import prepare as prepare_payload
from ..services.entities import create_entity, validate_sources, serialize, index_entity, search

OPERATIONS = {'create_record': 'record', 'add_person_mention': 'person_mention', 'save_transcription': 'transcription', 'add_evidence': 'evidence', 'propose_relationship': 'relationship', 'create_finding': 'finding', 'save_research_progress': 'research_task', 'create_person': 'person', 'create_claim': 'claim', 'save_annotation': 'annotation', 'create_hypothesis': 'hypothesis'}


def context(db, settings):
    cases = []
    for case in db.scalars(select(Case).order_by(Case.id)):
        row = serialize(case)
        row['page_count'] = db.scalar(select(func.count()).select_from(Page).where(Page.case_id == case.id))
        cases.append(row)
    entities = db.scalars(select(Entity).order_by(Entity.updated.desc())).all()
    hidden = {e.id for e in entities if e.living and not settings.export_living}
    changed = True
    while changed:
        previous = len(hidden)
        for entity in entities:
            refs = []
            for name, value in entity.data.items():
                if name.endswith('_id') and isinstance(value, str):
                    refs.append(value)
                if name.endswith('_ids') and isinstance(value, list):
                    refs.extend(v for v in value if isinstance(v, str))
            if any(ref in hidden for ref in refs):
                hidden.add(entity.id)
        changed = len(hidden) != previous
    # Fail closed: do not export loose findings/transcriptions that may name a living person
    # unless the author classified them as nonliving; this is documented in privacy settings.
    visible = [serialize(e) for e in entities if e.id not in hidden]
    studied = sorted({p for e in visible if e['kind'] == 'research_task' for p in e['data'].get('studied_page_ids', [])})
    return {'schema_version': '1.0', 'cases': cases, 'entities': visible, 'studied_page_ids': studied, 'integration_status': 'unverified'}


def process(db, settings, secret, raw):
    if not db.in_transaction():
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
    encoded = json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()
    if len(encoded) > settings.max_message_bytes:
        raise HTTPException(413, 'Сообщение превышает лимит размера')
    model = InboxMessage.model_validate(raw) if 'operation_id' in raw else PageRequest.model_validate(raw)
    identifier = str(model.operation_id if isinstance(model, InboxMessage) else model.request_id)
    fingerprint = hashlib.sha256(encoded).hexdigest()
    prior = db.get(Message, identifier)
    if prior:
        if prior.digest != fingerprint:
            db.add(AuditEvent(entity_id=identifier, action='message_conflict', author='chatgpt', details={'original_digest': prior.digest, 'incoming_digest': fingerprint}))
            return {'request_id': identifier, 'status': 'conflicted', 'error': 'UUID уже использован с другим содержимым'}
        return prior.response
    count = db.scalar(select(func.count()).select_from(Message).where(Message.created > time.time() - 3600))
    if count >= 300:
        raise HTTPException(429, 'Лимит 300 сообщений в час')
    response = {'request_id': identifier, 'status': 'completed', 'processed_at': time.time()}
    try:
        with db.begin_nested():
            if isinstance(model, InboxMessage):
                response.update(import_result(db, model))
            elif model.operation == 'search':
                visible = {e['id'] for e in context(db, settings)['entities']}
                response['results'] = [{key: e[key] for key in ('id', 'kind', 'title', 'status', 'version')} for e in search(db, model.query, limit=30) if e['id'] in visible]
            elif model.operation == 'get_research_context':
                exported = context(db, settings)
                response['context'] = {'manifest': 'manifest.json', 'case_count': len(exported['cases']), 'entity_count': len(exported['entities']), 'integration_status': 'unverified', 'instruction': 'Читайте актуальные catalog, page_indexes и entity_shards из manifest.json; полный контекст разбит на файлы.'}
            elif model.operation == 'get_image_payload':
                response['image_payload'] = prepare_payload(db, settings, secret, model)
            elif model.operation == 'renew_image_links' and (old := db.get(Message, str(model.renew_request_id))) and 'image_payload' in old.response:
                previous = old.response['image_payload']
                renewed = PageRequest.model_validate({**previous['request'],
                    'delivery': 'github_base64' if previous.get('base64_in_github') else 'https', 'request_id': identifier})
                response['image_payload'] = prepare_payload(db, settings, secret, renewed)
            else:
                response['pages'] = page_response(db, settings, secret, model)
    except HTTPException as exc:
        response.update(status='error', error=exc.detail, http_status=exc.status_code)
    db.add(Message(id=identifier, digest=fingerprint, response=response))
    db.flush()
    return response


def page_response(db, settings, secret, request):
    if request.operation == 'renew_image_links':
        original = db.get(Message, str(request.renew_request_id))
        if not original or not original.response.get('pages'):
            raise HTTPException(404, 'Исходный запрос не найден')
        result = []
        for old in original.response['pages']:
            page = db.get(Page, old['page_id'])
            params = old.get('crop')
            result.append(dict(old, **issue(db, settings, secret, page, 'crop' if params else old['variant'], params)))
        return result
    if request.operation == 'get_crop':
        page = db.get(Page, request.page_id)
        if not page:
            raise HTTPException(404, 'Страница не найдена')
        params = {k: getattr(request, k) for k in ('x', 'y', 'width', 'height', 'output_max_width')}
        if any(v is None for v in params.values()):
            raise HTTPException(422, 'Укажите координаты вырезки')
        validate_crop(page, params)
        pages = [page]
        variant = 'crop'
    else:
        if not request.case_id or not request.page_numbers:
            raise HTTPException(422, 'Укажите дело и номера JPG')
        pages = db.scalars(select(Page).where(Page.case_id == request.case_id, Page.jpg_number.in_(request.page_numbers))).all()
        if set(p.jpg_number for p in pages) != set(request.page_numbers):
            raise HTTPException(404, 'Не все страницы найдены')
        params, variant = None, request.variant
    result = []
    for page in pages:
        case = db.get(Case, page.case_id)
        result.append({'page_id': page.id, 'jpg_number': page.jpg_number, 'case_id': case.id, 'citation': f'{case.title}, JPG {page.jpg_number}', 'width': page.width, 'height': page.height, 'sha256': page.sha256, 'variant': variant, 'crop': params, **issue(db, settings, secret, page, variant, params)})
    return result


def import_result(db, model):
    if model.operation == 'propose_correction':
        original = db.get(Entity, model.entity_id)
        if not original:
            raise HTTPException(404, 'Исправляемая сущность не найдена')
        if original.data.get('correction_for'):
            raise HTTPException(422, 'Исправляйте исходную запись, а не другое предложение исправления')
        data = model.data.model_dump(mode='json', exclude_defaults=True)
        validate_sources(db, original.kind, data)
        conflict = original.version != model.expected_version
        # Corrections are separate proposals. Confirmed facts are never overwritten by sync.
        proposed = Entity(kind='finding', title=model.title, data={'correction_for': original.id, 'expected_version': model.expected_version, 'replacement_kind': original.kind, 'replacement_data': data, 'sources': data.get('sources', []), 'text': data.get('text', '')}, author='chatgpt', living=model.living or original.living, status='conflicted' if conflict else 'proposed')
        db.add(proposed)
        db.flush()
        index_entity(db, proposed)
        db.add(AuditEvent(entity_id=proposed.id, action='correction_proposal', author='chatgpt', details={'target': original.id}))
        return {'entity_id': proposed.id, 'status': proposed.status, 'version': proposed.version}
    kind = OPERATIONS[model.operation]
    if model.entity_id:
        existing = db.get(Entity, model.entity_id)
        if not existing or existing.kind != kind:
            raise HTTPException(422, 'Неверная сущность обновления')
        if existing.version != model.expected_version or existing.status == 'confirmed':
            return {'status': 'conflicted', 'entity_id': existing.id, 'version': existing.version}
        if kind != 'research_task':
            raise HTTPException(422, 'Для исправлений используйте propose_correction')
        data = model.data.model_dump(mode='json', exclude_defaults=True)
        validate_sources(db, kind, data)
        before = serialize(existing)
        existing.data, existing.title = data, model.title
        existing.living = existing.living or model.living
        existing.status = 'proposed'
        existing.version += 1
        existing.updated = time.time()
        index_entity(db, existing)
        db.add(AuditEvent(entity_id=existing.id, action='progress', author='chatgpt', details={'before': before, 'after': serialize(existing)}))
        return {'entity_id': existing.id, 'status': existing.status, 'version': existing.version}
    payload = EntityInput(kind=kind, title=model.title, data=model.data, living=model.living)
    entity = create_entity(db, payload, 'chatgpt')
    return {'entity_id': entity.id, 'status': entity.status, 'version': entity.version}
