import io
import time
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func, delete, update
from ..models import Case, Page, Entity, Session, AccessCode, Link, ImportRun, AuditEvent, Message, State
from ..security.auth import require, login, digest, hasher
from ..security.links import issue, consume
from ..images.storage import original, render, thumbnail, allowed_path, validate_crop
from ..importers.catalog import run_import
from ..importers.lock import import_active
from ..schemas.messages import EntityInput, ReviewInput, Crop
from ..services.entities import serialize, search, create_entity, review, search_rules, index_entity
from ..services.backup import backup
from ..research.protocol import process, context
from ..github_sync.worker import sync_once

router = APIRouter()
read = Depends(require('viewer', 'researcher', 'admin'))
write = Depends(require('researcher', 'admin'))
admin = Depends(require('admin'))


class LoginBody(BaseModel):
    code: str = Field(min_length=1, max_length=256)


@router.get('/health')
def health():
    return {'status': 'ok', 'service': 'ДРЕВО'}


@router.get('/api/v1/health')
def public_health(request: Request):
    # No archive queries, settings, identifiers or filesystem paths are exposed.
    with request.app.state.engine.connect() as connection:
        connection.exec_driver_sql('SELECT 1')
    return {'status': 'ok', 'service': 'drevo-api', 'version': request.app.version}


@router.get('/api/v1/system/capabilities')
def public_capabilities(request: Request):
    return {
        'service': 'drevo-api', 'api_version': request.app.version,
        'authentication': {'type': 'bearer_session', 'login': '/api/auth/login', 'code_in_url': False},
        'capabilities': ['reference_import', 'zip_import', 'protected_images', 'original_pixel_crops',
                         'signed_images', 'revocation', 'research_proposals', 'github_exchange'],
        'integration': {'github_configured': bool(request.app.state.settings.github_repo and request.app.state.settings.github_token),
                        'chatgpt': 'PARTIAL', 'ordinary_chat_image_test': 'WORKING',
                        'github_chat_write': 'CLIENT_DEPENDENT'},
        'ai_instructions': '/ai/instructions.md',
    }


@router.post('/api/auth/login')
def sign_in(payload: LoginBody, request: Request):
    return login(request.app.state.factory, request.app.state.settings, payload.code, request.client.host if request.client else 'unknown')


@router.post('/api/auth/logout')
def logout(request: Request, role=read):
    with request.app.state.factory() as db:
        db.execute(delete(Session).where(Session.digest == digest(request.headers['authorization'].split(' ', 1)[1])))
        db.commit()
    return {'status': 'ok'}


@router.get('/api/me')
def me(role=read):
    return {'role': role}


@router.get('/api/dashboard')
def dashboard(request: Request, role=read):
    with request.app.state.factory() as db:
        count = lambda model, *conditions: db.scalar(select(func.count()).select_from(model).where(*conditions))
        return {'cases': count(Case), 'pages': count(Page), 'people': count(Entity, Entity.kind == 'person'), 'proposals': count(Entity, Entity.status.in_(['proposed', 'needs_review', 'conflicted'])), 'tasks': [serialize(e) for e in db.scalars(select(Entity).where(Entity.kind == 'research_task').order_by(Entity.updated.desc()).limit(5))], 'recent': [serialize(e) for e in db.scalars(select(Entity).order_by(Entity.updated.desc()).limit(8))], 'integration_status': 'unverified'}


@router.get('/api/cases')
def cases(request: Request, q: str = '', fond: str = '', inventory: str = '', limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), role=read):
    with request.app.state.factory() as db:
        stmt = select(Case)
        if q:
            stmt = stmt.where(Case.title.contains(q))
        if fond:
            stmt = stmt.where(Case.fond == fond)
        if inventory:
            stmt = stmt.where(Case.inventory == inventory)
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.scalars(stmt.order_by(Case.fond, Case.inventory, Case.number).offset(offset).limit(limit))
        return {'total': total, 'items': [dict(serialize(c), page_count=db.scalar(select(func.count()).select_from(Page).where(Page.case_id == c.id))) for c in rows]}


@router.get('/api/cases/{identifier}')
def get_case(identifier: str, request: Request, role=read):
    with request.app.state.factory() as db:
        case = db.get(Case, identifier)
        if not case:
            raise HTTPException(404, 'Дело не найдено')
        return serialize(case)


class CaseUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    publication: Literal['private_only', 'signed_links_allowed', 'public_allowed'] | None = None
    rights_checked: bool = False
    metadata_status: Literal['proposed', 'confirmed'] | None = None
    title: str | None = Field(default=None, max_length=500)
    metadata_json: dict | None = None


@router.patch('/api/cases/{identifier}')
def update_case(identifier: str, payload: CaseUpdate, request: Request, role=admin):
    with request.app.state.factory() as db:
        case = db.get(Case, identifier)
        if not case:
            raise HTTPException(404, 'Дело не найдено')
        if payload.publication and payload.publication != 'private_only' and not payload.rights_checked:
            raise HTTPException(422, 'Подтвердите проверку прав на выдачу архивных копий')
        before = serialize(case)
        for name, value in payload.model_dump(exclude_none=True).items():
            if name != 'rights_checked':
                setattr(case, name, value)
        db.add(AuditEvent(entity_id=identifier, action='case_settings', author=role, details={'before': before, 'after': serialize(case)}))
        db.commit()
        return serialize(case)


def public_page(page):
    result = serialize(page)
    for key in ('path', 'source_key', 'zip_member', 'mtime_ns'):
        result.pop(key, None)
    return result


@router.get('/api/cases/{identifier}/pages')
def pages(identifier: str, request: Request, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0), role=read):
    with request.app.state.factory() as db:
        if not db.get(Case, identifier):
            raise HTTPException(404, 'Дело не найдено')
        stmt = select(Page).where(Page.case_id == identifier)
        total = db.scalar(select(func.count()).select_from(stmt.subquery()))
        rows = db.scalars(stmt.order_by(Page.jpg_number, Page.filename).offset(offset).limit(limit))
        return {'total': total, 'items': [public_page(p) for p in rows]}


@router.get('/api/cases/{identifier}/progress')
def case_progress(identifier: str, request: Request, role=read):
    with request.app.state.factory() as db:
        pages = db.scalars(select(Page).where(Page.case_id == identifier).order_by(Page.jpg_number)).all()
        if not db.get(Case, identifier):
            raise HTTPException(404, 'Дело не найдено')
        identifiers = {p.id for p in pages}
        viewed, studied = set(), set()
        for entity in db.scalars(select(Entity).where(Entity.kind == 'research_task', Entity.status != 'rejected')):
            viewed.update(set(entity.data.get('viewed_page_ids', [])) & identifiers)
            studied.update(set(entity.data.get('studied_page_ids', [])) & identifiers)
        return {'total': len(pages), 'studied': len(studied), 'partial': len(viewed - studied), 'unviewed': len(identifiers - viewed - studied), 'next_pages': [public_page(p) for p in pages if p.id not in studied][:20]}


@router.get('/api/v1/pages/{identifier}')
@router.get('/api/pages/{identifier}')
def get_page(identifier: str, request: Request, role=read):
    with request.app.state.factory() as db:
        page = db.get(Page, identifier)
        if not page:
            raise HTTPException(404, 'Страница не найдена')
        return public_page(page)


class PageUpdate(BaseModel):
    book_page: str | None = Field(default=None, max_length=100)
    archival_leaf: str | None = Field(default=None, max_length=100)
    section: str | None = Field(default=None, max_length=300)


@router.patch('/api/pages/{identifier}')
def edit_page(identifier: str, payload: PageUpdate, request: Request, role=write):
    with request.app.state.factory() as db:
        page = db.get(Page, identifier)
        if not page:
            raise HTTPException(404, 'Страница не найдена')
        before = public_page(page)
        for k, v in payload.model_dump().items():
            setattr(page, k, v)
        db.add(AuditEvent(entity_id=identifier, action='page_metadata', author=role, details={'before': before, 'after': public_page(page)}))
        db.commit()
        return public_page(page)


def image_response(settings, page, variant, params=None):
    if variant == 'original':
        return FileResponse(original(settings, page), media_type={'JPEG': 'image/jpeg', 'PNG': 'image/png', 'TIFF': 'image/tiff'}.get(page.format, 'application/octet-stream'), filename=page.filename, content_disposition_type='inline')
    if variant == 'thumbnail':
        return FileResponse(thumbnail(settings, page), media_type='image/jpeg')
    return Response(render(settings, page, variant, params), media_type='image/jpeg')


@router.get('/api/v1/pages/{identifier}/image')
@router.get('/api/pages/{identifier}/image')
def image(identifier: str, request: Request, variant: Literal['original', 'preview', 'thumbnail'] = 'preview', role=read):
    with request.app.state.factory() as db:
        page = db.get(Page, identifier)
        if not page:
            raise HTTPException(404, 'Страница не найдена')
        return image_response(request.app.state.settings, page, variant)


@router.post('/api/v1/pages/{identifier}/crop')
@router.post('/api/pages/{identifier}/crop')
def crop(identifier: str, payload: Crop, request: Request, role=read):
    with request.app.state.factory() as db:
        page = db.get(Page, identifier)
        if not page:
            raise HTTPException(404, 'Страница не найдена')
        return image_response(request.app.state.settings, page, 'crop', payload.model_dump())


@router.get('/api/v1/pages/{identifier}/crop')
def crop_get(identifier: str, request: Request, x: int, y: int, width: int, height: int,
             output_max_width: int = 2400, role=read):
    return crop(identifier, Crop(x=x, y=y, width=width, height=height, output_max_width=output_max_width), request, role)


@router.get('/ai/crops/{identifier}')
def ai_crop(identifier: str, request: Request, token: str = ''):
    if not token:
        raise HTTPException(403, 'Требуется подписанная ссылка')
    with request.app.state.factory() as db:
        link = consume(db, request.app.state.secret, identifier, token)
        if link.operation != 'crop':
            raise HTTPException(403, 'Разрешение не относится к вырезке')
        return image_response(request.app.state.settings, db.get(Page, identifier), 'crop', link.params)


@router.get('/ai/images/{identifier}')
def ai_image(identifier: str, request: Request, token: str = ''):
    if not token:
        raise HTTPException(403, 'Требуется подписанная ссылка')
    with request.app.state.factory() as db:
        link = consume(db, request.app.state.secret, identifier, token)
        page = db.get(Page, identifier)
        return image_response(request.app.state.settings, page, link.operation, link.params)


@router.get('/api/entities')
def entities(request: Request, q: str = '', kind: str | None = None, status: str | None = None, case_id: str | None = None, year_from: int | None = None, year_to: int | None = None, place: str | None = None, event_type: str | None = None, fuzzy: bool = False, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), role=read):
    with request.app.state.factory() as db:
        return search(db, q, kind, status, case_id, year_from, year_to, place, event_type, fuzzy, limit, offset)


@router.post('/api/entities')
def add_entity(payload: EntityInput, request: Request, role=write):
    with request.app.state.factory() as db:
        entity = create_entity(db, payload, role)
        db.commit()
        return serialize(entity)


@router.get('/api/entities/{identifier}')
def get_entity(identifier: str, request: Request, role=read):
    with request.app.state.factory() as db:
        entity = db.get(Entity, identifier)
        if not entity:
            raise HTTPException(404, 'Сущность не найдена')
        return dict(serialize(entity), history=[serialize(a) for a in db.scalars(select(AuditEvent).where(AuditEvent.entity_id == identifier).order_by(AuditEvent.at))])


@router.post('/api/entities/{identifier}/review')
def review_entity(identifier: str, payload: ReviewInput, request: Request, role=write):
    with request.app.state.factory() as db:
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
        entity = db.get(Entity, identifier)
        if not entity:
            raise HTTPException(404, 'Сущность не найдена')
        result = review(db, entity, payload, role)
        db.commit()
        return serialize(result)


@router.get('/api/tree')
def tree(request: Request, role=read):
    with request.app.state.factory() as db:
        return {'people': [serialize(e) for e in db.scalars(select(Entity).where(Entity.kind == 'person', Entity.status != 'rejected'))], 'relationships': [serialize(e) for e in db.scalars(select(Entity).where(Entity.kind == 'relationship', Entity.status != 'rejected'))]}


class SearchRule(BaseModel):
    source: str = Field(min_length=1, max_length=30)
    target: str = Field(max_length=30)


class SearchRulesInput(BaseModel):
    rules: list[SearchRule] = Field(max_length=30)


@router.get('/api/search-rules')
def get_search_rules(request: Request, role=read):
    with request.app.state.factory() as db:
        return {'rules': search_rules(db)}


@router.patch('/api/search-rules')
def edit_search_rules(payload: SearchRulesInput, request: Request, role=admin):
    with request.app.state.factory() as db:
        value = payload.model_dump()
        row = db.get(State, 'search_rules')
        if row:
            row.value = value
        else:
            db.add(State(key='search_rules', value=value))
        db.flush()
        for entity in db.scalars(select(Entity)).yield_per(100):
            index_entity(db, entity)
        db.add(AuditEvent(action='search_rules', author=role, details=value))
        db.commit()
        return value


class ImportInput(BaseModel):
    path: str
    mode: Literal['reference', 'managed'] = 'reference'


@router.post('/api/imports')
def start_import(payload: ImportInput, request: Request, background: BackgroundTasks, role=admin):
    settings = request.app.state.settings
    path = allowed_path(settings, payload.path)
    if import_active(settings):
        raise HTTPException(409, 'Импорт уже выполняется. Дождитесь окончания.')
    with request.app.state.factory() as db:
        active = db.scalar(select(ImportRun).where(ImportRun.status.in_(['pending', 'running'])))
        if active:
            raise HTTPException(409, 'Импорт уже выполняется. Дождитесь окончания.')
        run = ImportRun(path=str(path), mode=payload.mode)
        db.add(run)
        db.commit()
        background.add_task(run_import, request.app.state.factory, settings, run.id)
        return serialize(run)


@router.get('/api/imports')
def imports(request: Request, role=admin):
    with request.app.state.factory() as db:
        return [serialize(i) for i in db.scalars(select(ImportRun).order_by(ImportRun.created.desc()).limit(50))]


@router.post('/api/protocol')
def protocol(payload: dict, request: Request, role=admin):
    with request.app.state.factory() as db:
        response = process(db, request.app.state.settings, request.app.state.secret, payload)
        db.commit()
        return response


@router.get('/api/integration')
def integration(request: Request, role=admin):
    with request.app.state.factory() as db:
        state = db.get(State, 'sync')
        return {'integration_status': 'unverified', 'github_configured': bool(request.app.state.settings.github_repo and request.app.state.settings.github_token), 'sync': state.value if state else {'status': 'not_configured'}, 'links': [serialize(l) for l in db.scalars(select(Link).order_by(Link.created.desc()).limit(50))], 'messages': [serialize(m) for m in db.scalars(select(Message).order_by(Message.created.desc()).limit(30))]}


@router.post('/api/integration/sync')
def sync(request: Request, role=admin):
    settings = request.app.state.settings
    if not settings.github_repo or not settings.github_token:
        raise HTTPException(409, 'GitHub не настроен. Задайте переменные окружения на сервере.')
    try:
        return sync_once(request.app.state.factory, settings, request.app.state.secret)
    except Exception as exc:
        raise HTTPException(502, f'Синхронизация не выполнена: {type(exc).__name__}')


@router.post('/api/links/revoke-all')
def revoke_all(request: Request, role=admin):
    with request.app.state.factory() as db:
        db.execute(update(Link).values(revoked=True))
        db.commit()
    return {'status': 'ok'}


@router.post('/api/links/{identifier}/revoke')
def revoke(identifier: str, request: Request, role=admin):
    with request.app.state.factory() as db:
        link = db.get(Link, identifier)
        if not link:
            raise HTTPException(404, 'Ссылка не найдена')
        link.revoked = True
        db.commit()
    return {'status': 'ok'}


class LinkInput(BaseModel):
    page_id: str
    variant: Literal['original', 'preview', 'thumbnail'] = 'preview'
    crop: Crop | None = None


@router.post('/api/links')
def create_link(payload: LinkInput, request: Request, role=admin):
    with request.app.state.factory() as db:
        page = db.get(Page, payload.page_id)
        if not page:
            raise HTTPException(404, 'Страница не найдена')
        params = payload.crop.model_dump() if payload.crop else None
        if params:
            validate_crop(page, params)
        result = issue(db, request.app.state.settings, request.app.state.secret, page, 'crop' if params else payload.variant, params)
        db.commit()
        return result


class CodeInput(BaseModel):
    role: Literal['viewer', 'researcher', 'admin']
    code: str = Field(min_length=12, max_length=256)


@router.post('/api/settings/code')
def change_code(payload: CodeInput, request: Request, role=admin):
    with request.app.state.factory() as db:
        row = db.get(AccessCode, payload.role)
        if row:
            row.hash = hasher.hash(payload.code)
        else:
            db.add(AccessCode(role=payload.role, hash=hasher.hash(payload.code)))
        db.execute(delete(Session).where(Session.role == payload.role))
        db.add(AuditEvent(action='rotate_code', author=role, details={'role': payload.role}))
        db.commit()
    return {'status': 'ok', 'message': 'Код изменён, сессии роли завершены'}


@router.post('/api/settings/revoke-sessions')
def revoke_sessions(request: Request, role=admin):
    with request.app.state.factory() as db:
        db.execute(delete(Session))
        db.commit()
    return {'status': 'ok'}


@router.get('/api/settings')
def settings_view(request: Request, role=admin):
    settings = request.app.state.settings
    with request.app.state.factory() as db:
        return {'archive_root': str(settings.archive_root), 'data_dir': str(settings.data_dir), 'frontend_origin': settings.frontend_origin, 'public_api_url': settings.public_api_url, 'github_repo': settings.github_repo, 'export_living': settings.export_living, 'roles': list(db.scalars(select(AccessCode.role))), 'integration_status': 'unverified'}


@router.post('/api/backups')
def create_backup(request: Request, role=admin):
    settings = request.app.state.settings
    path = backup(settings, settings.data_dir / 'backups' / f'drevo-{time.time_ns()}.sqlite3')
    return {'file': path.name, 'integrity': 'ok'}
