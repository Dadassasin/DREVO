import json
import sqlite3
from pathlib import Path


def backup(settings, destination):
    path = Path(destination).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path == settings.db_path.resolve():
        raise ValueError('Резервная копия не может совпадать с рабочей БД')
    with sqlite3.connect(settings.db_path) as source, sqlite3.connect(path) as target:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Проверка копии не пройдена')
    config = settings.model_dump(mode='json')
    for secret in ('github_token',):
        config.pop(secret, None)
    path.with_suffix('.config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    return path


def restore(settings, source):
    path = Path(source).resolve()
    if path == settings.db_path.resolve() or not path.is_file():
        raise ValueError('Некорректный файл резервной копии')
    with sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True) as saved:
        if saved.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Резервная копия повреждена')
        with sqlite3.connect(settings.db_path) as target:
            saved.backup(target)
            target.execute('DELETE FROM sessions')
            target.execute('UPDATE links SET revoked=1')
    return settings.db_path
