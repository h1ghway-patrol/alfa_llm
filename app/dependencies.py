"""Зависимости FastAPI: текущий пользователь и проверка роли.

В режиме фикстур пользователи и сессии живут в памяти. При `USE_DB=true`
учётки, хэши паролей и сессии читаются из SQLite.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.db import repositories as repo
from app.db.passwords import verify_password
from app.schemas.auth import Role, UserOut
from app.store import db_mode, db_session

TOKEN_TTL = timedelta(hours=8)

STUB_USERS: dict[str, tuple[int, str, Role]] = {
    "viewer": (1, "viewer", "viewer"),
    "admin": (2, "admin", "admin"),
}

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Токен из `POST /auth/login`. Кнопка Authorize вставляет его сюда.",
)

_sessions: dict[str, tuple[str, datetime]] = {}


def _stub_passwords() -> dict[str, str]:
    settings = get_settings()
    return {"viewer": settings.viewer_password, "admin": settings.admin_password}


def issue_token(username: str) -> tuple[str, datetime]:
    """Выдаёт токен пользователю. Возвращает токен и срок его действия."""
    expires_at = datetime.now(timezone.utc) + TOKEN_TTL
    if db_mode():
        with db_session() as conn:
            user = repo.get_user_by_username(conn, username)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"code": "unauthorized", "message": "Неверный логин или пароль"},
                )
            token = repo.create_session(conn, user["id"], int(TOKEN_TTL.total_seconds()))
        return token, expires_at
    if username not in STUB_USERS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Неверный логин или пароль"},
        )
    token = secrets.token_urlsafe(32)
    _sessions[token] = (username, expires_at)
    return token, expires_at


def verify_credentials(username: str, password: str) -> UserOut:
    """Проверяет логин и пароль пользователя."""
    if db_mode():
        with db_session() as conn:
            user = repo.get_user_by_username(conn, username)
        if user is None or not verify_password(password, user["password_hash"], user["salt"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "unauthorized", "message": "Неверный логин или пароль"},
            )
        return UserOut(id=user["id"], username=user["username"], role=user["role"])

    entry = STUB_USERS.get(username)
    expected = _stub_passwords().get(username)
    if entry is None or expected is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Неверный логин или пароль"},
        )
    if not secrets.compare_digest(password, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Неверный логин или пароль"},
        )
    user_id, name, role = entry
    return UserOut(id=user_id, username=name, role=role)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> UserOut:
    """Достаёт текущего пользователя из заголовка `Authorization`."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "unauthorized",
                "message": "Требуется токен: заголовок Authorization: Bearer <токен>",
            },
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    if db_mode():
        with db_session() as conn:
            user = repo.get_session_user(conn, token)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "unauthorized", "message": "Токен недействителен или истёк"},
            )
        return UserOut(id=user["id"], username=user["username"], role=user["role"])
    session = _sessions.get(token)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Токен недействителен или истёк"},
        )
    username, expires_at = session
    if expires_at < datetime.now(timezone.utc):
        _sessions.pop(token, None)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Токен недействителен или истёк"},
        )
    user_id, name, role = STUB_USERS[username]
    return UserOut(id=user_id, username=name, role=role)


def require_role(role: Role):
    """Зависимость, требующая конкретной роли."""

    def dependency(user: UserOut = Depends(get_current_user)) -> UserOut:
        if user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "forbidden",
                    "message": f"Нужна роль «{role}», у вас «{user.role}»",
                },
            )
        return user

    return dependency
