import hashlib
import secrets
import time
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import delete, select, func
from ..models import AccessCode, Session, LoginAttempt

hasher = PasswordHasher(type=Type.ID)
bearer = HTTPBearer(auto_error=False)
dummy_hash = hasher.hash(secrets.token_urlsafe(32))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def login(factory, settings, code, ip):
    now = time.time()
    with factory() as db:
        failures = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.ip == ip, LoginAttempt.at > now - 900, LoginAttempt.success == False))
        last = db.scalar(select(func.max(LoginAttempt.at)).where(LoginAttempt.ip == ip, LoginAttempt.success == False)) or 0
        if failures >= 8 or now - last < min(2 ** failures, 30):
            raise HTTPException(429, 'Слишком много попыток. Подождите и повторите вход.')
        role = None
        codes = db.scalars(select(AccessCode)).all()
        for item in codes:
            try:
                if hasher.verify(item.hash, code):
                    role = item.role
            except (VerificationError, InvalidHashError):
                pass
        if not codes:
            try:
                hasher.verify(dummy_hash, code)
            except VerificationError:
                pass
        db.add(LoginAttempt(ip=ip, success=role is not None))
        db.execute(delete(LoginAttempt).where(LoginAttempt.at < now - 86400 * 30))
        if role is None:
            db.commit()
            raise HTTPException(401, 'Неверный код доступа')
        token = secrets.token_urlsafe(48)
        expires = now + settings.session_hours * 3600
        db.add(Session(digest=digest(token), role=role, expires=expires))
        db.commit()
        return {'token': token, 'role': role, 'expires': expires}


def require(*roles):
    def dependency(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials is None:
            raise HTTPException(401, 'Требуется вход')
        with request.app.state.factory() as db:
            session = db.get(Session, digest(credentials.credentials))
            if not session or session.expires <= time.time():
                raise HTTPException(401, 'Сессия истекла')
            if roles and session.role not in roles:
                raise HTTPException(403, 'Недостаточно прав')
            return session.role
    return dependency
