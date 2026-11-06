from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from .models import Base


def make_db(settings, initialize=False):
    settings.prepare()
    engine = create_engine(f'sqlite:///{settings.db_path.as_posix()}', connect_args={'check_same_thread': False, 'timeout': 30})

    @event.listens_for(engine, 'connect')
    def pragmas(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA busy_timeout=30000')

    if initialize:
        Base.metadata.create_all(engine)
        create_fts(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)


def create_fts(engine):
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE VIRTUAL TABLE IF NOT EXISTS entity_fts USING fts5(id UNINDEXED, title, body, tokenize="unicode61 remove_diacritics 2")')
