"""Isolated browser QA fixture; never writes technical test records into the real archive."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
import uvicorn
from sqlalchemy import select
from app.config import Settings, ROOT
from app.main import create_app
from app.models import AccessCode, ImportRun
from app.security.auth import hasher
from app.importers.catalog import run_import

folder = ROOT / '.local' / 'ui-fixture' / 'archive' / 'GAKK_F801_Op40_D98_test'
folder.mkdir(parents=True, exist_ok=True)
for i in range(1, 4):
    image = Image.new('RGB', (1600, 1200), 'white')
    draw = ImageDraw.Draw(image)
    draw.text((100, 70), f'TECHNICAL TEST IMAGE - NOT A HISTORICAL SOURCE - PAGE {i}', fill='black', font_size=35)
    for y in range(150, 1100, 70):
        draw.line((100, y, 1500, y), fill='gray', width=2)
        draw.text((120, y + 10), f'Test record {i} / line {y}', fill='black', font_size=25)
    image.save(folder / f'page_{i:04d}.jpg')
test_url = ROOT / '.local' / 'tunnel-url.txt'
settings = Settings(archive_root=folder.parent, data_dir=ROOT / '.local' / 'ui-fixture' / 'data', public_api_url=test_url.read_text().strip() if test_url.exists() else 'http://127.0.0.1:8001', _env_file=None)
app = create_app(settings, initialize=True)
with app.state.factory() as db:
    if not db.get(AccessCode, 'admin'):
        db.add(AccessCode(role='admin', hash=hasher.hash('technical-ui-test-only')))
    run = ImportRun(path=str(folder), mode='reference')
    db.add(run)
    db.commit()
    run_id = run.id
run_import(app.state.factory, settings, run_id)
uvicorn.run(app, host='127.0.0.1', port=8001, access_log=False)
