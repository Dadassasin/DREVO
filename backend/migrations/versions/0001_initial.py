"""Initial archive and research schema."""
from alembic import op
from app.models import Base

revision = '0001'
down_revision = None


def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    bind.exec_driver_sql('CREATE VIRTUAL TABLE entity_fts USING fts5(id UNINDEXED, title, body, tokenize="unicode61 remove_diacritics 2")')


def downgrade():
    op.get_bind().exec_driver_sql('DROP TABLE entity_fts')
    Base.metadata.drop_all(op.get_bind())
