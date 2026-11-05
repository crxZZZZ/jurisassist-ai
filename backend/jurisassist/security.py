import hashlib
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session as DBSession

from jurisassist.db import get_db
from jurisassist.models import RateBucket, Session, User, now

hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
COOKIE = "juris_session"
CSRF_COOKIE = "juris_csrf"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_matches(hashed: str, password: str) -> bool:
    try:
        return hasher.verify(hashed, password)
    except VerificationError:
        return False


def current_user(request: Request, db: DBSession = Depends(get_db)) -> User:
    raw = request.cookies.get(COOKIE, "")
    session = db.get(Session, digest(raw))
    if session is None or session.expires_at < now():
        raise HTTPException(401, "Entre para continuar.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("X-CSRF-Token", "")
        if not csrf or not secrets.compare_digest(session.csrf_hash, digest(csrf)):
            raise HTTPException(403, "Proteção CSRF: atualize a página e tente novamente.")
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(401, "Sessão encerrada.")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Acesso administrativo necessário.")
    return user


def rate_limit(db: DBSession, key: str, limit: int, seconds: int = 60):
    """Atomic, shared limit: works across API processes; no process-local bypass."""
    at = now()
    bucket = digest(f"{key}:{int(at.timestamp()) // seconds}")
    insert = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    statement = (
        insert(RateBucket)
        .values(key=bucket, count=1, expires_at=at + timedelta(seconds=seconds * 2))
        .on_conflict_do_update(
            index_elements=[RateBucket.key], set_={"count": RateBucket.count + 1}
        )
        .returning(RateBucket.count)
    )
    count = db.scalar(statement)
    db.execute(delete(RateBucket).where(RateBucket.expires_at < at))
    db.commit()
    if count > limit:
        raise HTTPException(
            429, "Muitas solicitações. Aguarde um minuto.", headers={"Retry-After": str(seconds)}
        )


def active_session(db: DBSession, token: str):
    return db.scalar(select(Session).where(Session.token_hash == digest(token)))
