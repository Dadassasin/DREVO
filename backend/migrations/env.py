from alembic import context
from app.config import Settings
from app.db import make_db
from app.models import Base

engine, _ = make_db(Settings())
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()
