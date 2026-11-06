import time
import uuid
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Case(Base):
    __tablename__ = 'cases'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    archive: Mapped[str] = mapped_column(default='ГАКК', index=True)
    fond: Mapped[str | None] = mapped_column(index=True)
    inventory: Mapped[str | None] = mapped_column(index=True)
    number: Mapped[str | None] = mapped_column(index=True)
    metadata_status: Mapped[str] = mapped_column(default='proposed')
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    publication: Mapped[str] = mapped_column(default='private_only')


class Page(Base):
    __tablename__ = 'pages'
    __table_args__ = (UniqueConstraint('case_id', 'source_key'),)
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey('cases.id'), index=True)
    source_key: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    zip_member: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    jpg_number: Mapped[str] = mapped_column(index=True)
    book_page: Mapped[str | None]
    archival_leaf: Mapped[str | None]
    section: Mapped[str | None]
    sha256: Mapped[str] = mapped_column(index=True)
    size: Mapped[int] = mapped_column(Integer)
    mtime_ns: Mapped[str]
    width: Mapped[int]
    height: Mapped[int]
    format: Mapped[str]
    duplicate_of: Mapped[str | None]


class AccessCode(Base):
    __tablename__ = 'access_codes'
    role: Mapped[str] = mapped_column(String, primary_key=True)
    hash: Mapped[str] = mapped_column(Text)


class Session(Base):
    __tablename__ = 'sessions'
    digest: Mapped[str] = mapped_column(String, primary_key=True)
    role: Mapped[str]
    expires: Mapped[float] = mapped_column(Float)


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    ip: Mapped[str] = mapped_column(index=True)
    at: Mapped[float] = mapped_column(default=time.time, index=True)
    success: Mapped[bool] = mapped_column(Boolean)


class Link(Base):
    __tablename__ = 'links'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    page_id: Mapped[str] = mapped_column(ForeignKey('pages.id'))
    operation: Mapped[str]
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    created: Mapped[float] = mapped_column(default=time.time)
    expires: Mapped[float]
    revoked: Mapped[bool] = mapped_column(default=False)
    hits: Mapped[int] = mapped_column(default=0)
    max_hits: Mapped[int] = mapped_column(default=100)


class Entity(Base):
    """Common versioned storage; kind keeps domain entities distinct, never merges identities."""
    __tablename__ = 'entities'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(default='proposed', index=True)
    version: Mapped[int] = mapped_column(default=1)
    author: Mapped[str]
    created: Mapped[float] = mapped_column(default=time.time)
    updated: Mapped[float] = mapped_column(default=time.time, index=True)
    living: Mapped[bool] = mapped_column(default=False)


class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    entity_id: Mapped[str | None] = mapped_column(index=True)
    action: Mapped[str]
    author: Mapped[str]
    at: Mapped[float] = mapped_column(default=time.time)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[str] = mapped_column(primary_key=True)
    digest: Mapped[str]
    response: Mapped[dict] = mapped_column(JSON)
    created: Mapped[float] = mapped_column(default=time.time, index=True)


class ImportRun(Base):
    __tablename__ = 'imports'
    id: Mapped[str] = mapped_column(primary_key=True, default=uid)
    path: Mapped[str] = mapped_column(Text)
    mode: Mapped[str]
    status: Mapped[str] = mapped_column(default='pending')
    scanned: Mapped[int] = mapped_column(default=0)
    imported: Mapped[int] = mapped_column(default=0)
    skipped: Mapped[int] = mapped_column(default=0)
    duplicates: Mapped[int] = mapped_column(default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    created: Mapped[float] = mapped_column(default=time.time)


class State(Base):
    __tablename__ = 'state'
    key: Mapped[str] = mapped_column(primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
