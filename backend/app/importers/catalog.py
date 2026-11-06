import hashlib
import re
import shutil
import warnings
import zipfile
from pathlib import Path
from PIL import Image
from sqlalchemy import select
from ..models import Case, Page, ImportRun, AuditEvent, Link
from sqlalchemy import update
from ..images.storage import EXTENSIONS, allowed_path, safe_member, thumbnail, clean_cache


def natural(value):
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', str(value))]


def case_metadata(name):
    stem = Path(name).stem if name.lower().endswith('.zip') else name
    match = re.fullmatch(r'GAKK_F(\d+)_Op(\d+)_D(\d+)(?:_\d+)?', stem, re.I)
    if match:
        fond, inventory, number = match.groups()
        return f'gakk-{fond}-{inventory}-{number}', f'ГАКК · Ф. {fond} · Оп. {inventory} · Д. {number}', fond, inventory, number
    identifier = hashlib.sha256(stem.encode()).hexdigest()[:20]
    return f'case-{identifier}', stem, None, None, None


def read_sidecar(source, archive=None):
    metadata = {}
    if archive:
        candidates = [info for info in archive.infolist() if info.filename.lower().endswith('.txt') and info.file_size < 65536][:5]
        texts = [archive.read(info).decode('utf-8-sig', errors='replace') for info in candidates]
    else:
        texts = [p.read_text(encoding='utf-8-sig', errors='replace') for p in list(source.glob('*.txt'))[:5] if p.stat().st_size < 65536]
    for value in texts:
        for line in value.splitlines():
            for label, field in [('Шифр:', 'reference'), ('Название:', 'description'), ('ID документа:', 'document_id'), ('Ссылка:', 'source_url'), ('Количество сканов:', 'expected_pages')]:
                if line.startswith(label):
                    metadata[field] = line[len(label):].strip()
    return metadata


def run_import(factory, settings, run_id):
    from .lock import import_lock
    try:
        with import_lock(settings):
            return _run_import(factory, settings, run_id)
    except ValueError as exc:
        with factory() as db:
            run = db.get(ImportRun, run_id)
            run.status = 'failed'
            run.errors = [{'error': str(exc)}]
            db.commit()


def _run_import(factory, settings, run_id):
    with factory() as db:
        run = db.get(ImportRun, run_id)
        run.status = 'running'
        db.commit()
        errors = []
        try:
            root = allowed_path(settings, run.path)
            if root.is_file() and root.suffix.lower() != '.zip':
                raise ValueError('Выберите каталог или ZIP')
            # Each directory containing images is one case. Root ZIPs are individual cases.
            sources = [root] if root.is_file() else sorted({p.parent for p in root.rglob('*') if p.is_file() and p.suffix.lower() in EXTENSIONS} | {p for p in root.rglob('*') if p.is_file() and p.suffix.lower() == '.zip'}, key=lambda p: natural(str(p)))
            for source in sources:
                source = allowed_path(settings, source)
                case_id, title, fond, inventory, number = case_metadata(source.name)
                if not db.get(Case, case_id):
                    db.add(Case(id=case_id, title=title, fond=fond, inventory=inventory, number=number))
                    db.commit()
                archive = zipfile.ZipFile(source) if source.is_file() else None
                try:
                    metadata = read_sidecar(source, archive)
                    case = db.get(Case, case_id)
                    if metadata and not case.metadata_json.get('sidecar_imported'):
                        case.metadata_json = {**case.metadata_json, **metadata, 'sidecar_imported': True}
                        if metadata.get('description') and case.metadata_status != 'confirmed':
                            case.title = metadata['description']
                        reference = re.fullmatch(r'F(\d+)_Op(\d+)_D(\d+)', metadata.get('reference', ''), re.I)
                        if reference and case.metadata_status != 'confirmed':
                            case.fond, case.inventory, case.number = reference.groups()
                        db.commit()
                    if archive:
                        infos = archive.infolist()
                        if len(infos) > 100000 or sum(i.file_size for i in infos) > settings.max_zip_bytes:
                            raise ValueError('ZIP превышает лимиты')
                        for info in infos:
                            safe_member(info, settings)
                        entries = sorted([i for i in infos if not i.is_dir() and Path(i.filename).suffix.lower() in EXTENSIONS], key=lambda i: natural(i.filename))
                    else:
                        entries = sorted([p for p in source.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS], key=lambda p: natural(p.name))
                    for entry in entries:
                        run.scanned += 1
                        try:
                            member = entry.filename if archive else None
                            path = source if archive else allowed_path(settings, entry)
                            filename = Path(member).name if member else path.name
                            stamp = f'{path.stat().st_mtime_ns}:{entry.CRC}' if archive else str(path.stat().st_mtime_ns)
                            size = entry.file_size if archive else path.stat().st_size
                            source_key = f'{path}|{member or ""}'
                            page_id = hashlib.sha256(f'{case_id}|{source_key}'.encode()).hexdigest()[:32]
                            old = db.get(Page, page_id)
                            if old and old.size == size and old.mtime_ns == stamp:
                                run.skipped += 1
                                if run.skipped % 50 == 0:
                                    db.commit()
                                continue
                            if size > settings.max_member_bytes:
                                raise ValueError('Файл превышает лимит размера')
                            with archive.open(entry) if archive else path.open('rb') as stream:
                                sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                            with archive.open(entry) if archive else path.open('rb') as stream:
                                with warnings.catch_warnings():
                                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                                    with Image.open(stream) as image:
                                        width, height, fmt = image.width, image.height, image.format
                                        if width * height > settings.max_image_pixels:
                                            raise ValueError('Изображение превышает лимит пикселей')
                                        image.verify()
                            duplicate = db.scalar(select(Page.id).where(Page.sha256 == sha, Page.id != page_id).limit(1))
                            digits = re.search(r'(\d+)$', Path(filename).stem)
                            stored = path
                            stored_member = member
                            if run.mode == 'managed':
                                stored = settings.data_dir / 'managed' / (sha + Path(filename).suffix.lower())
                                if not stored.exists():
                                    temp = stored.with_suffix('.tmp')
                                    with archive.open(entry) if archive else path.open('rb') as src, temp.open('wb') as dst:
                                        shutil.copyfileobj(src, dst, 1024 * 1024)
                                    temp.replace(stored)
                                stored_member = None
                            values = dict(case_id=case_id, source_key=source_key, path=str(stored), zip_member=stored_member, filename=filename, jpg_number=digits.group(1) if digits else str(run.scanned).zfill(4), sha256=sha, size=size, mtime_ns=stamp, width=width, height=height, format=fmt, duplicate_of=duplicate)
                            if old:
                                if old.sha256 != sha:
                                    db.add(AuditEvent(entity_id=old.id, action='source_changed', author='importer', details={'old_sha256': old.sha256, 'new_sha256': sha, 'import_id': run_id}))
                                    db.execute(update(Link).where(Link.page_id == old.id).values(revoked=True))
                                for field, value in values.items():
                                    setattr(old, field, value)
                                page = old
                            else:
                                page = Page(id=page_id, **values)
                                db.add(page)
                            db.flush()
                            thumbnail(settings, page)
                            run.imported += 1
                            if duplicate:
                                run.duplicates += 1
                            db.commit()
                        except Exception as exc:
                            db.rollback()
                            errors.append({'file': str(getattr(entry, 'filename', entry)), 'error': str(exc)[:300]})
                            run = db.get(ImportRun, run_id)
                            run.errors = errors[-500:]
                            db.commit()
                    if run.imported and run.imported % 500 == 0:
                        clean_cache(settings)
                    db.commit()
                finally:
                    if archive:
                        archive.close()
            clean_cache(settings)
            run.status = 'completed_with_errors' if errors else 'completed'
        except Exception as exc:
            run.status = 'failed'
            errors.append({'error': str(exc)[:300]})
        run.errors = errors[-500:]
        db.commit()
