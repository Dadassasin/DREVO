import shutil
from sqlalchemy import select
from app.models import Page, ImportRun
from app.importers.catalog import run_import
from app.db import make_db
from app.config import Settings


def test_reimport_after_relocation_preserves_page_ids(imported, tmp_path):
    app, client, settings, folder, auth, pages = imported
    destination=tmp_path/'external'/folder.name
    shutil.copytree(folder,destination)
    original_ids={page['id'] for page in pages}
    settings.archive_root=destination.parent
    with app.state.factory() as db:
        for page in db.scalars(select(Page)):
            path=destination/page.filename
            page.path=str(path)
            page.source_key=f'{path}|'
            page.mtime_ns=str(path.stat().st_mtime_ns)
        run=ImportRun(path=str(destination),mode='reference')
        db.add(run);db.commit();run_id=run.id
    run_import(app.state.factory,settings,run_id)
    with app.state.factory() as db:
        assert {p.id for p in db.scalars(select(Page))}==original_ids
        assert db.get(ImportRun,run_id).skipped==2


def test_import_skips_internal_data_folder(tmp_path):
    from PIL import Image
    archive=tmp_path/'archive'
    data=archive/'.drevo'
    settings=Settings(archive_root=archive,data_dir=data,_env_file=None)
    engine,factory=make_db(settings,initialize=True)
    Image.new('RGB',(20,20)).save(data/'cache'/'generated.jpg')
    with factory() as db:
        run=ImportRun(path=str(archive),mode='reference');db.add(run);db.commit();run_id=run.id
    run_import(factory,settings,run_id)
    with factory() as db:
        assert list(db.scalars(select(Page)))==[]
        assert db.get(ImportRun,run_id).status=='completed'
    engine.dispose()
