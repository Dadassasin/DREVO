"""Publish only frontend source, routing it to this PC's Funnel origin."""
import argparse
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent


def prepare_stage(root, origin, site, stage):
    if not re.fullmatch(r'https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net', origin):
        raise ValueError('Expected an HTTPS Tailscale hostname without a path')
    source = root / 'frontend'
    for name in ('index.html', 'package.json', 'package-lock.json', 'tsconfig.json', 'vite.config.ts'):
        shutil.copyfile(source / name, stage / name)
    shutil.copytree(source / 'src', stage / 'src')
    config = json.loads((source / 'vercel.json').read_text(encoding='utf-8'))
    config['rewrites'] = [
        {'source': '/api/:path*', 'destination': origin + '/api/:path*'},
        {'source': '/ai/:path*', 'destination': origin + '/ai/:path*'},
        {'source': '/health', 'destination': origin + '/health'},
    ]
    config.setdefault('headers', []).append({'source': '/drevo-origin.json', 'headers': [
        {'key': 'Cache-Control', 'value': 'no-store'},
        {'key': 'CDN-Cache-Control', 'value': 'no-store'},
    ]})
    (stage / 'vercel.json').write_text(json.dumps(config, indent=2), encoding='utf-8')
    (stage / 'public').mkdir()
    (stage / 'public/drevo-origin.json').write_text(json.dumps({'origin': origin}), encoding='utf-8')
    (stage / '.vercelignore').write_text('*\n!index.html\n!package.json\n!package-lock.json\n!tsconfig.json\n!vite.config.ts\n!vercel.json\n!public\n!public/**\n!src\n!src/**\n', encoding='utf-8')


def fetch_json(url):
    with urlopen(Request(url, headers={'Cache-Control': 'no-cache'}), timeout=25) as response:
        return json.load(response)


def already_active(site, origin):
    try:
        marker = fetch_json(site + '/drevo-origin.json?t=' + str(time.time_ns()))
        return marker.get('origin') == origin and fetch_json(site + '/health').get('status') == 'ok'
    except (OSError, ValueError):
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('origin')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args()
    config = json.loads((ROOT / 'scripts/online.json').read_text(encoding='utf-8'))
    # Validate before making network or account changes.
    if not re.fullmatch(r'https://[a-z0-9-]+\.[a-z0-9-]+\.ts\.net', args.origin):
        raise ValueError('Invalid Funnel origin')
    if not args.force and already_active(config['site'], args.origin):
        print('Сайт уже подключён к этому ПК: ' + config['site'], flush=True)
        return
    cli = ['npx.cmd', '--yes', 'vercel@' + config['cli_version']]
    identity = subprocess.run(cli + ['whoami', '--json'], cwd=ROOT, capture_output=True)
    if identity.returncode:
        print('Войдите в свой Vercel. Авторизация останется только на этом ПК.', flush=True)
        subprocess.run(cli + ['login'], cwd=ROOT, check=True)
    print('Переключаю сайт на ' + args.origin + '. Дождитесь завершения.', flush=True)
    # npm on Windows can briefly retain a directory handle after a successful deploy.
    with tempfile.TemporaryDirectory(prefix='drevo-online-', ignore_cleanup_errors=True) as directory:
        stage = Path(directory)
        prepare_stage(ROOT, args.origin, config['site'], stage)
        # This temporary folder is outside Git and contains no .env, DB or credentials.
        subprocess.run(cli + ['deploy', '--prod', '--yes', '--project', config['project'],
            '--scope', config['scope'], '--build-env', 'VITE_API_URL=' + config['site'],
            '--build-env', 'PAGES_BASE=/'], cwd=stage, check=True)
    for attempt in range(6):
        if already_active(config['site'], args.origin):
            print('Сайт переключён и отвечает: ' + config['site'], flush=True)
            return
        if attempt < 5:
            time.sleep(5)
    raise RuntimeError('Не удалось подтвердить новый маршрут. Локальный сервер работает; повторите start_online.bat.')


if __name__ == '__main__':
    main()
