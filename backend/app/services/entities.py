import json
import re
import time
import unicodedata
import copy
from difflib import SequenceMatcher
from fastapi import HTTPException
from sqlalchemy import select, text
from ..models import Entity, Page, Case, AuditEvent
from ..models import State
from ..schemas.messages import ReviewInput, EntityInput
from ..images.storage import validate_crop


def serialize(item):
    return {column.name: getattr(item, column.name) for column in item.__table__.columns}


DEFAULT_RULES = [{'source': 'ё', 'target': 'е'}, {'source': 'ѣ', 'target': 'е'}, {'source': 'і', 'target': 'и'}, {'source': 'ъ ', 'target': ' '}]


def search_rules(db):
    state = db.get(State, 'search_rules')
    return state.value['rules'] if state else DEFAULT_RULES


def normalize(value, rules=None):
    result = unicodedata.normalize('NFKC', value).casefold()
    for rule in DEFAULT_RULES if rules is None else rules:
        result = result.replace(rule['source'], rule['target'])
    return result


def index_entity(db, entity):
    rules = search_rules(db)
    db.execute(text('DELETE FROM entity_fts WHERE id=:id'), {'id': entity.id})
    db.execute(text('INSERT INTO entity_fts(id,title,body) VALUES (:id,:title,:body)'), {'id': entity.id, 'title': normalize(entity.title, rules), 'body': normalize(json.dumps(entity.data, ensure_ascii=False), rules)})


def validate_sources(db, kind, data, demo=False):
    sources = data.get('sources', [])
    if kind in ('record', 'transcription', 'person_mention', 'evidence', 'annotation') and not sources and not demo:
        raise HTTPException(422, 'Укажите конкретную страницу первоисточника')
    for source in sources:
        page = db.get(Page, source['page_id'])
        if not page:
            raise HTTPException(422, 'Страница-источник не найдена')
        if source.get('sha256') and source['sha256'] != page.sha256:
            raise HTTPException(409, 'Источник изменился. Проверьте новый скан и создайте новую привязку.')
        source['sha256'] = page.sha256
        if source.get('crop'):
            validate_crop(page, source['crop'])
    if kind != 'research_task' and data.get('uncertain') and (not sources or not any(s.get('crop') for s in sources)):
        raise HTTPException(422, 'Неуверенное прочтение требует вырезки оригинала')
    refs = {'person_id': 'person', 'record_id': 'record', 'claim_id': 'claim', 'from_person_id': 'person', 'to_person_id': 'person'}
    for key, expected_kind in refs.items():
        if data.get(key):
            entity = db.get(Entity, data[key])
            if not entity or entity.kind != expected_kind:
                raise HTTPException(422, f'Некорректная ссылка {key}')
    for identifier in data.get('evidence_ids', []):
        entity = db.get(Entity, identifier)
        if not entity or entity.kind != 'evidence':
            raise HTTPException(422, 'Доказательство не найдено')
    if kind == 'relationship' and (not data.get('from_person_id') or not data.get('to_person_id') or data['from_person_id'] == data['to_person_id']):
        raise HTTPException(422, 'Связь требует двух разных персон')
    for identifier in data.get('case_ids', []):
        if not db.get(Case, identifier):
            raise HTTPException(422, 'Дело не найдено')
    for identifier in data.get('studied_page_ids', []) + data.get('viewed_page_ids', []):
        if not db.get(Page, identifier):
            raise HTTPException(422, 'Страница прогресса не найдена')


def create_entity(db, payload, author):
    data = payload.data.model_dump(mode='json', exclude_defaults=True)
    if data.get('demo'):
        raise HTTPException(422, 'Демонстрационный флаг разрешён только локальной командой seed-demo')
    validate_sources(db, payload.kind, data)
    entity = Entity(kind=payload.kind, title=payload.title, data=data, status='proposed' if author == 'chatgpt' else ('needs_review' if data.get('uncertain') else 'proposed'), author=author, living=payload.living)
    db.add(entity)
    db.flush()
    index_entity(db, entity)
    db.add(AuditEvent(entity_id=entity.id, action='create', author=author, details={'after': serialize(entity)}))
    return entity


def search(db, query, kind=None, status=None, case_id=None, year_from=None, year_to=None, place=None, event_type=None, fuzzy=False, limit=50, offset=0):
    rules = search_rules(db)
    norm = lambda value: normalize(value, rules)
    stmt = select(Entity)
    if kind:
        stmt = stmt.where(Entity.kind == kind)
    if status:
        stmt = stmt.where(Entity.status == status)
    words = re.findall(r'\w+', norm(query), re.UNICODE)
    if words and not fuzzy:
        match = ' AND '.join('"' + word + '"*' for word in words)
        identifiers = db.execute(text('SELECT id FROM entity_fts WHERE entity_fts MATCH :q LIMIT 2000'), {'q': match}).scalars().all()
        stmt = stmt.where(Entity.id.in_(identifiers))
    post_filter = bool(fuzzy or any((case_id, year_from, year_to, place, event_type)))
    rows = db.scalars(stmt.order_by(Entity.updated.desc()).limit(5000 if post_filter else limit).offset(0 if post_filter else offset)).all()
    result = []
    for item in rows:
        data = item.data
        if case_id and not any(db.get(Page, s['page_id']).case_id == case_id for s in data.get('sources', [])) and case_id not in data.get('case_ids', []):
            continue
        years = [d.get('year') for d in data.get('dates', []) if d.get('year')]
        if year_from and not any(y >= year_from for y in years):
            continue
        if year_to and not any(y <= year_to for y in years):
            continue
        if place and norm(place) not in norm(data.get('place', '')):
            continue
        if event_type and data.get('event_type') != event_type:
            continue
        score = SequenceMatcher(None, norm(query), norm(item.title)).ratio() if fuzzy and words else 1
        if fuzzy and words and score < .35 and not any(w in norm(item.title) for w in words):
            continue
        result.append(dict(serialize(item), candidate_score=round(score, 3)))
    if fuzzy:
        result.sort(key=lambda x: x['candidate_score'], reverse=True)
        return result[offset:offset + limit]
    return result[offset:offset + limit] if post_filter else result[:limit]


def review(db, entity, payload, author):
    if entity.version != payload.expected_version:
        raise HTTPException(409, 'Версия изменена. Обновите карточку перед проверкой.')
    if payload.status in ('proposed', 'conflicted', 'needs_review'):
        raise HTTPException(422, 'Выберите результат проверки')
    if entity.kind == 'finding' and entity.data.get('correction_for') and payload.status == 'confirmed':
        target = db.get(Entity, entity.data['correction_for'])
        if not target or target.version != entity.data.get('expected_version'):
            raise HTTPException(409, 'Исправляемая запись изменилась. Создайте предложение для актуальной версии.')
        correction = ReviewInput(status='confirmed', expected_version=target.version, note=payload.note, acknowledge_significant=payload.acknowledge_significant, replacement=EntityInput(kind=target.kind, title=target.title, living=target.living or entity.living, data=entity.data['replacement_data']))
        review(db, target, correction, author)
    if (entity.kind == 'relationship' and payload.status == 'confirmed' or entity.status == 'confirmed') and not payload.acknowledge_significant:
        raise HTTPException(422, 'Требуется явное подтверждение существенного изменения')
    before = serialize(entity)
    if payload.replacement:
        if payload.replacement.kind != entity.kind:
            raise HTTPException(422, 'Тип сущности менять нельзя')
        data = payload.replacement.data.model_dump(mode='json', exclude_defaults=True)
        validate_sources(db, entity.kind, data)
        entity.data = data
        entity.title = payload.replacement.title
        entity.living = payload.replacement.living
    if payload.status in ('confirmed', 'human_reviewed'):
        checked_data = copy.deepcopy(entity.data)
        validate_sources(db, entity.kind, checked_data, demo=checked_data.get('demo', False))
        entity.data = checked_data
    if entity.kind == 'relationship' and payload.status == 'confirmed' and not entity.data.get('evidence_ids'):
        raise HTTPException(422, 'Для подтверждения родства добавьте доказательства')
    if payload.status == 'confirmed' and entity.kind == 'relationship':
        if not all(db.get(Entity, identifier).status == 'confirmed' for identifier in entity.data['evidence_ids']):
            raise HTTPException(422, 'Сначала подтвердите доказательства')
        if not any(db.get(Entity, identifier).data.get('supports', True) for identifier in entity.data['evidence_ids']):
            raise HTTPException(422, 'Нет подтверждающего доказательства: выбранные источники только опровергают утверждение')
    entity.status = payload.status
    entity.version += 1
    entity.updated = time.time()
    index_entity(db, entity)
    db.add(AuditEvent(entity_id=entity.id, action='review', author=author, details={'note': payload.note, 'before': before, 'after': serialize(entity)}))
    return entity
