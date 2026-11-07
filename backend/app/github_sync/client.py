import base64
import hashlib
import json
import re
import time
from urllib.parse import quote
import httpx


class _BranchMoved(Exception):
    def __init__(self, error):
        self.error = error


class GitHubClient:
    def __init__(self, settings, transport=None):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', settings.github_repo):
            raise ValueError('Укажите owner/DREVO-Research-Data')
        if not settings.github_token or any(ord(char) < 33 or ord(char) > 126 for char in settings.github_token):
            raise ValueError('GitHub token отсутствует или имеет недопустимый формат')
        self.settings = settings
        self.http = httpx.Client(base_url='https://api.github.com', timeout=30, transport=transport, headers={'Authorization': f'Bearer {settings.github_token}', 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        self.prefix = f'/repos/{settings.github_repo}'

    def close(self):
        self.http.close()

    def private_check(self):
        result = self.http.get(self.prefix)
        result.raise_for_status()
        if not result.json().get('private'):
            raise ValueError('Синхронизация разрешена только с PRIVATE репозиторием')

    def tree(self):
        result = self.http.get(f'{self.prefix}/git/trees/{self.settings.github_branch}', params={'recursive': '1'})
        result.raise_for_status()
        value = result.json()
        if value.get('truncated'):
            raise ValueError('GitHub tree truncated: разбейте репозиторий на меньшие наборы')
        return value

    def read(self, path):
        result = self.http.get(f'{self.prefix}/contents/{quote(path, safe="/")}', params={'ref': self.settings.github_branch})
        result.raise_for_status()
        data = result.json()
        if data.get('size', 0) > self.settings.max_message_bytes or data.get('encoding') != 'base64':
            raise ValueError('Недопустимый размер или формат GitHub-сообщения')
        decoded = base64.b64decode(data['content'], validate=False)
        if len(decoded) > self.settings.max_message_bytes:
            raise ValueError('Сообщение превышает лимит')
        value = json.loads(decoded)
        if not isinstance(value, dict):
            raise ValueError('GitHub-сообщение должно быть JSON-объектом')
        return value

    def write(self, path, value):
        for attempt in range(3):
            try:
                return self._write_once(path, value)
            except _BranchMoved as exc:
                if attempt == 2:
                    raise exc.error
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (500, 502, 503, 504) or attempt == 2:
                    raise
            except httpx.TransportError:
                if attempt == 2:
                    raise
            time.sleep(2 ** attempt)

    def _write_once(self, path, value):
        path = quote(path, safe='/')
        raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
        existing = self.http.get(f'{self.prefix}/contents/{path}', params={'ref': self.settings.github_branch})
        sha = None
        if existing.status_code == 200:
            old = existing.json()
            if base64.b64decode(old.get('content', '')) == raw:
                return
            sha = old['sha']
        elif existing.status_code != 404:
            existing.raise_for_status()
        payload = {'message': f'DREVO sync: {path}', 'branch': self.settings.github_branch, 'content': base64.b64encode(raw).decode()}
        if sha:
            payload['sha'] = sha
        result = self.http.put(f'{self.prefix}/contents/{path}', json=payload)
        if result.status_code == 409:
            # Parallel writes to different files can move the branch head. Retry only
            # if this file itself did not change; never overwrite a changed file blindly.
            current = self.http.get(f'{self.prefix}/contents/{path}', params={'ref': self.settings.github_branch})
            if current.status_code == 200 and base64.b64decode(current.json().get('content', '')) == raw:
                return
            current_sha = current.json().get('sha') if current.status_code == 200 else None
            if current.status_code in (200, 404) and current_sha == sha:
                try:
                    result.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise _BranchMoved(exc) from exc
        result.raise_for_status()

    def delete_entity_export(self, path):
        # Only disposable generated snapshots, never requests, receipts or historical input.
        if not re.fullmatch(r'outbox/research-context/entities-\d{4}\.json', path):
            raise ValueError('Удаление разрешено только для устаревшего entity-export')
        address=f'{self.prefix}/contents/{quote(path, safe="/")}'
        existing=self.http.get(address,params={'ref':self.settings.github_branch})
        if existing.status_code==404:
            return
        existing.raise_for_status()
        response=self.http.request('DELETE',address,json={'message':'DREVO: remove obsolete generated export','branch':self.settings.github_branch,'sha':existing.json()['sha']})
        response.raise_for_status()

    def image_bundle(self, files=None, delete=()):
        """Atomic private image-part publication/expiry; never force-update a branch."""
        files = files or {}
        pattern = r'responses/images/[a-f0-9-]{36}(?:\.json|/part-\d{4}\.json)'
        if not files and not delete:
            return
        if any(not re.fullmatch(pattern, path) for path in files):
            raise ValueError('Разрешены только manifest/parts изображения')
        if any(not re.fullmatch(r'responses/images/[a-f0-9-]{36}/part-\d{4}\.json', path) for path in delete):
            raise ValueError('Удаление разрешено только для временных частей изображения')
        self.private_check()
        ref = f'{self.prefix}/git/ref/heads/{quote(self.settings.github_branch, safe="/")}'
        for attempt in range(3):
            try:
                head_response = self.http.get(ref); head_response.raise_for_status()
                head = head_response.json()['object']['sha']
                tree_response = self.http.get(f'{self.prefix}/git/trees/{head}', params={'recursive': '1'})
                tree_response.raise_for_status(); tree = tree_response.json()
                if tree.get('truncated'):
                    raise ValueError('GitHub tree truncated')
                existing = {row['path']: row['sha'] for row in tree['tree'] if row['type'] == 'blob'}
                entries = []
                for path, value in files.items():
                    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n'
                    encoded = raw.encode()
                    sha = hashlib.sha1(b'blob ' + str(len(encoded)).encode() + b'\0' + encoded).hexdigest()
                    if existing.get(path) == sha:
                        continue
                    if path in existing:
                        raise ValueError('Конфликт существующего image bundle: ' + path)
                    entries.append({'path': path, 'mode': '100644', 'type': 'blob', 'content': raw})
                entries.extend({'path': path, 'mode': '100644', 'type': 'blob', 'sha': None} for path in delete if path in existing)
                if not entries:
                    return
                created = self.http.post(f'{self.prefix}/git/trees', json={'base_tree': tree['sha'], 'tree': entries})
                created.raise_for_status()
                commit = self.http.post(f'{self.prefix}/git/commits', json={'message': 'DREVO: image byte bundle' if files else 'DREVO: expire image parts', 'tree': created.json()['sha'], 'parents': [head]})
                commit.raise_for_status()
                updated = self.http.patch(f'{self.prefix}/git/refs/heads/{quote(self.settings.github_branch, safe="/")}', json={'sha': commit.json()['sha'], 'force': False})
                if updated.status_code in (409, 422) and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                updated.raise_for_status()
                return
            except httpx.TransportError:
                if attempt == 2:
                    raise
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in (500, 502, 503, 504) or attempt == 2:
                    raise
            time.sleep(2 ** attempt)
