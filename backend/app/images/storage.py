import hashlib
import io
import os
import shutil
import warnings
import zipfile
import threading
from pathlib import Path, PurePosixPath
from PIL import Image
from fastapi import HTTPException

EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}
IMAGE_SLOTS = threading.BoundedSemaphore(2)


def allowed_path(settings, value, must_exist=True):
    path = Path(value).resolve()
    roots = [settings.archive_root.resolve(), (settings.data_dir / 'managed').resolve()]
    if not any(path.is_relative_to(root) for root in roots) or (must_exist and not path.exists()):
        raise HTTPException(400, 'Путь вне разрешённого архива или файл не найден')
    return path


def safe_member(info, settings):
    name = info.filename.replace('\\', '/')
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or ':' in name or (info.external_attr >> 16) & 0o170000 == 0o120000:
        raise ValueError('Небезопасный путь ZIP')
    if info.file_size > settings.max_member_bytes or info.file_size / max(info.compress_size, 1) > 250:
        raise ValueError('Превышен лимит размера или сжатия ZIP')


def clean_cache(settings, keep=None):
    keep = keep or set()
    files = []
    with os.scandir(settings.data_dir / 'cache') as entries:
        for entry in entries:
            if entry.is_file(follow_symlinks=False):
                stat = entry.stat()
                files.append((stat.st_mtime, stat.st_size, Path(entry.path)))
    total = sum(size for _, size, _ in files)
    if total <= settings.max_cache_bytes:
        return
    for _, size, path in sorted(files):
        if total <= settings.max_cache_bytes:
            break
        if path.suffix != '.tmp' and path not in keep:
            try:
                path.unlink()
                total -= size
            except OSError:
                pass


def original(settings, page):
    path = allowed_path(settings, page.path)
    if not page.zip_member:
        if not path.is_relative_to((settings.data_dir / 'managed').resolve()):
            stat = path.stat()
            if stat.st_size != page.size or str(stat.st_mtime_ns) != page.mtime_ns:
                raise HTTPException(409, 'Исходный файл изменился. Повторите импорт перед просмотром.')
        return path
    target = settings.data_dir / 'cache' / (page.sha256 + '.' + page.format.lower())
    if target.exists():
        os.utime(target, None)
        return target
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(page.zip_member)
        safe_member(info, settings)
        temp = target.with_name(target.name + '.' + os.urandom(6).hex() + '.tmp')
        try:
            with archive.open(info) as source, temp.open('wb') as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            with temp.open('rb') as check:
                if hashlib.file_digest(check, 'sha256').hexdigest() != page.sha256:
                    raise HTTPException(409, 'Содержимое ZIP изменено. Повторите импорт.')
            temp.replace(target)
            clean_cache(settings, keep={target})
        finally:
            temp.unlink(missing_ok=True)
    return target


def validate_crop(page, params):
    x, y, w, h = (params[k] for k in ('x', 'y', 'width', 'height'))
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > page.width or y + h > page.height or w * h > 40_000_000:
        raise HTTPException(422, 'Вырезка выходит за границы или превышает 40 млн пикселей')


def render(settings, page, variant='preview', params=None):
    with IMAGE_SLOTS:
        return _render(settings, page, variant, params)


def _render(settings, page, variant='preview', params=None):
    path = original(settings, page)
    if variant == 'crop':
        validate_crop(page, params)
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(path) as source:
            if source.width * source.height > settings.max_image_pixels:
                raise HTTPException(413, 'Слишком большое изображение')
            if variant == 'crop':
                x, y, w, h = (params[k] for k in ('x', 'y', 'width', 'height'))
                image = source.crop((x, y, x + w, y + h))
                max_width = params.get('output_max_width', 2400)
                image.thumbnail((max_width, max_width * 4))
            else:
                limit = 240 if variant == 'thumbnail' else 4096
                source.draft('RGB', (limit, limit))
                source.thumbnail((limit, limit))
                image = source.copy()
            if image.mode != 'RGB':
                image = image.convert('RGB')
            output = io.BytesIO()
            image.save(output, 'JPEG', quality=90)
            return output.getvalue()


def thumbnail(settings, page):
    target = settings.data_dir / 'cache' / (page.sha256 + '-thumb.jpg')
    if not target.exists():
        temp = target.with_name(target.name + '.' + os.urandom(6).hex() + '.tmp')
        temp.write_bytes(render(settings, page, 'thumbnail'))
        temp.replace(target)
    return target
