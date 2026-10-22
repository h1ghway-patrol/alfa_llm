"""Зависимости FastAPI: текущий пользователь и проверка роли.

Реализация — заглушка на фиксированных учётках из окружения и сессиях в
памяти (задача B-4 заменит её на полноценные сессии с хэшами паролей в БД).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status

from app.config import get_settings
from app.schemas.auth import Role, UserOut

TOKEN_TTL = timedelta(hours=8)

STUB_USERS: dict[str, tuple[int, str, Role]] = {
    "viewer": (1, "viewer", "viewer"),
    "admin": (2, "admin", "admin"),
}

_sessions: dict[str, tuple[str, datetime]] = {}


def _stub_passwords() -> dict[str, str]:
    settings = get_settings()
    return {"viewer": settings.viewer_password, "admin": settings.admin_password}


def issue_token(username: str) -> tuple[str, datetime]:
    """Выдаёт токен фикстурному пользователю. Возвращает токен и срок его действия."""
    if username not in STUB_USERS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "unauthorized", "message": "Неверный логин или пароль"},
        )
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + TOKEN_TTL
    _sessions[token] = (username, expires_at)
    return token, expires_at


def verify_credentials(username: str, password: str) -> UserOut:
    """Проверяет логин и пароль фикстурного пользователя."""
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


def get_current_user(request: Request) -> UserOut:
    """Достаёт текущего пользователя из заголовка `Authorization`."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "unauthorized",
                "message": "Требуется токен: заголовок Authorization: Bearer <токен>",
            },
        )
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
