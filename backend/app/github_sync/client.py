import base64
import json
import re
from urllib.parse import quote
import httpx


class GitHubClient:
    def __init__(self, settings, transport=None):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', settings.github_repo):
            raise ValueError('Укажите owner/DREVO-Research-Data')
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
        return json.loads(decoded)

    def write(self, path, value):
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
        # 409 remains an error. Next poll re-reads the new SHA; no blind overwrite.
        result.raise_for_status()
