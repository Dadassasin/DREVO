import argparse
import getpass
import hashlib
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from sqlalchemy import select, delete
from alembic.config import Config
from alembic import command
from .config import Settings, ROOT
from .db import make_db
from .models import AccessCode, Entity, ImportRun, Session, Page, AuditEvent
from .security.auth import hasher
from .importers.catalog import run_import
from .services.backup import backup, restore
from .services.entities import index_entity
from .schemas.messages import PageRequest, InboxMessage, EntityInput


def migrate():
    command.upgrade(Config(str(ROOT / 'backend' / 'alembic.ini')), 'head')


def setup_code(settings, role, generated=False):
    code = secrets.token_urlsafe(18) if generated else getpass.getpass(f'Код роли {role} (минимум 12 символов): ')
    if len(code) < 12:
        raise ValueError('Код слишком короткий')
    if not generated and code != getpass.getpass('Повторите код: '):
        raise ValueError('Коды не совпадают')
    _, factory = make_db(settings)
    with factory() as db:
        row = db.get(AccessCode, role)
        if row:
            row.hash = hasher.hash(code)
        else:
            db.add(AccessCode(role=role, hash=hasher.hash(code)))
        db.execute(delete(Session).where(Session.role == role))
        db.commit()
    if generated:
        # One-time bootstrap is local-only and never printed into execution logs.
        path = settings.data_dir / 'INITIAL-ACCESS.txt'
        path.write_text(f'ДРЕВО — локальный код администратора\n{code}\n\nОткройте http://127.0.0.1:8000 и войдите.\nПосле входа измените код в Настройках и удалите этот файл.\n', encoding='utf-8')
        print('Локальный код создан: .local/INITIAL-ACCESS.txt (не публикуйте файл).')
    else:
        print('Код сохранён как Argon2id-хеш. Сессии роли завершены.')


def seed_demo(settings):
    _, factory = make_db(settings)
    seed_file = settings.data_dir / 'demo-seed.json'
    if not seed_file.is_file():
        raise ValueError('Создайте приватный demo-seed.json в каталоге данных. Семейные карточки не входят в публичный код.')
    samples = json.loads(seed_file.read_text(encoding='utf-8'))
    if not isinstance(samples, list) or any(not isinstance(row, list) or len(row) != 3 or not all(isinstance(value, str) for value in row) for row in samples):
        raise ValueError('Ожидается массив [id, название, примечание] для каждой карточки')
    with factory() as db:
        for identifier, title, note in samples:
            if not db.get(Entity, identifier):
                entity = Entity(id=identifier, kind='person', title=title, data={'demo': True, 'source_note': note, 'text': 'Пример из ТЗ. Источник ещё не привязан и факт системой не проверен.'}, status='needs_review', author='specification', living=False)
                db.add(entity)
                db.flush()
                index_entity(db, entity)
        db.commit()
    print('Приватные карточки загружены без фиктивных источников и родственных связей.')


def schemas():
    folder = ROOT / 'research-template'
    for path in ('requests/pages', 'requests/crops', 'requests/search', 'requests/research', 'responses/pages', 'responses/crops', 'responses/search', 'responses/research', 'inbox/records', 'inbox/transcriptions', 'inbox/people', 'inbox/relationships', 'inbox/findings', 'inbox/evidence', 'inbox/progress', 'inbox/claims', 'inbox/annotations', 'outbox/receipts', 'outbox/research-context', 'outbox/conflicts', 'schemas'):
        (folder / path).mkdir(parents=True, exist_ok=True)
        (folder / path / '.gitkeep').touch()
    for name, model in (('request', PageRequest), ('inbox', InboxMessage), ('entity', EntityInput)):
        (folder / 'schemas' / (name + '.schema.json')).write_text(json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2), encoding='utf-8')
    (folder / 'manifest.json').write_text(json.dumps({'schema_version': '1.0', 'integration_status': 'unverified', 'catalog': 'outbox/research-context/catalog.json', 'entity_shards': []}, indent=2), encoding='utf-8')
    print('research-template подготовлен: копируйте только в PRIVATE DREVO-Research-Data.')


def main():
    parser = argparse.ArgumentParser(description='ДРЕВО — локальное управление')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('migrate')
    configure = sub.add_parser('set-code')
    configure.add_argument('--role', choices=['viewer', 'researcher', 'admin'], default='admin')
    sub.add_parser('bootstrap')
    imp = sub.add_parser('import')
    imp.add_argument('path', nargs='?')
    imp.add_argument('--mode', choices=['reference', 'managed'], default='reference')
    for action in ('backup', 'restore'):
        sub.add_parser(action).add_argument('path')
    sub.add_parser('seed-demo')
    sub.add_parser('schemas')
    sub.add_parser('check')
    integrity = sub.add_parser('verify-integrity')
    integrity.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    settings = Settings()
    if args.command == 'migrate':
        migrate()
    elif args.command == 'set-code':
        setup_code(settings, args.role)
    elif args.command == 'bootstrap':
        migrate()
        _, factory = make_db(settings)
        with factory() as db:
            if not db.get(AccessCode, 'admin'):
                setup_code(settings, 'admin', generated=True)
        schemas()
    elif args.command == 'import':
        _, factory = make_db(settings)
        with factory() as db:
            run = ImportRun(path=str(Path(args.path or settings.archive_root).resolve()), mode=args.mode)
            db.add(run)
            db.commit()
            identifier = run.id
        run_import(factory, settings, identifier)
        with factory() as db:
            run = db.get(ImportRun, identifier)
            print(json.dumps({'id': run.id, 'status': run.status, 'imported': run.imported, 'skipped': run.skipped, 'duplicates': run.duplicates, 'errors': run.errors}, ensure_ascii=False))
            if run.status == 'failed':
                raise SystemExit(1)
    elif args.command == 'backup':
        print(backup(settings, args.path))
    elif args.command == 'restore':
        print(restore(settings, args.path))
    elif args.command == 'seed-demo':
        seed_demo(settings)
    elif args.command == 'schemas':
        schemas()
    elif args.command == 'check':
        with sqlite3.connect(settings.db_path) as db:
            result = db.execute('PRAGMA integrity_check').fetchone()[0]
            count = db.execute('SELECT count(*) FROM pages').fetchone()[0]
        print(json.dumps({'integrity': result, 'pages': count, 'archive_exists': settings.archive_root.is_dir(), 'integration': 'unverified'}))
    elif args.command == 'verify-integrity':
        from .images.storage import original
        _, factory = make_db(settings)
        checked, errors = 0, []
        with factory() as db:
            statement = select(Page).order_by(Page.id)
            if args.limit:
                statement = statement.limit(args.limit)
            for page in db.scalars(statement).yield_per(100):
                try:
                    with original(settings, page).open('rb') as stream:
                        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
                    if checksum != page.sha256:
                        errors.append({'page_id': page.id, 'error': 'sha256_mismatch'})
                except Exception as exc:
                    errors.append({'page_id': page.id, 'error': type(exc).__name__})
                checked += 1
            report = {'checked': checked, 'errors': errors, 'at': time.time()}
            db.add(AuditEvent(action='integrity_check', author='local_cli', details=report))
            db.commit()
        (settings.data_dir / 'integrity.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
        if errors:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
