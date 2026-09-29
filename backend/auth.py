import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db import get_db
from backend.models import User, UserSession

SESSION_COOKIE = "kisan_session"
SESSION_DAYS = 7


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(raw: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_https(request: Request) -> bool:
    if request.headers.get("x-forwarded-proto", "").lower() == "https":
        return True
    if os.getenv("RENDER", "").strip():
        return True
    return request.url.scheme == "https"


def create_session(db: Session, user_id: int) -> str:
    """Create a server-side session and return the raw token for the cookie."""
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(
        UserSession(
            user_id=user_id,
            token_hash=_token_hash(token),
            created_at=now,
            expires_at=now + timedelta(days=SESSION_DAYS),
        )
    )
    db.commit()
    return token


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, httponly=True, samesite="lax")


def session_user(db: Session, request: Request) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    row = db.scalar(
        select(UserSession).where(UserSession.token_hash == _token_hash(token))
    )
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        db.delete(row)
        db.commit()
        return None
    return db.get(User, row.user_id)


def _user_from_header(db: Session, x_user_id: str | None) -> User | None:
    """Legacy X-User-ID header: demo/test compatibility only."""
    if x_user_id is None or not x_user_id.strip():
        return None
    try:
        user_id = int(x_user_id.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="X-User-ID must be a numeric user id.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Unknown user id.")
    if not user.is_demo:
        raise HTTPException(
            status_code=401,
            detail="Registered accounts must sign in to access their data.",
        )
    return user


def optional_user(
    request: Request,
    x_user_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    """Session cookie first; demo header second; None only in legacy farmer/field mode."""
    user = session_user(db, request)
    if user is not None:
        return user
    return _user_from_header(db, x_user_id)


def get_current_user(
    user: User | None = Depends(optional_user),
) -> User:
    if user is None:
        raise HTTPException(
            status_code=400,
            detail="Sign in first, or use a demo user id (for example X-User-ID: 1001).",
        )
    return user
