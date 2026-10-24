"""Схемы аутентификации: вход, текущий пользователь, роли."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.schemas.common import NonEmptyStr

Role = Literal["viewer", "admin"]
"""Роль пользователя: `viewer` — просмотр, `admin` — ещё и админские эндпоинты."""


class LoginRequest(BaseModel):
    """Тело `POST /auth/login`."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"username": "viewer", "password": "viewer-password"},
            ]
        }
    )

    username: NonEmptyStr = Field(description="Имя пользователя.")
    password: SecretStr = Field(
        description=(
            "Пароль. Схема хранит его как секрет: чтобы прочитать значение, "
            "нужен `payload.password.get_secret_value()`. Пароль в логи не пишется."
        ),
    )


class UserOut(BaseModel):
    """Пользователь в ответах API (без пароля и соли)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"id": 1, "username": "viewer", "role": "viewer"},
            ]
        }
    )

    id: int = Field(description="Внутренний идентификатор пользователя.")
    username: str = Field(description="Имя пользователя.")
    role: Role = Field(description="Роль: `viewer` или `admin`.")


class LoginResponse(BaseModel):
    """Ответ `POST /auth/login`: токен и профиль вошедшего."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "access_token": "k3Zq8xT1c0aQ9bW7eR2yU4iO6pA1sD5fG7hJ3kL8mN0",
                    "token_type": "bearer",
                    "expires_at": "2026-10-22T18:30:00Z",
                    "user": {"id": 1, "username": "viewer", "role": "viewer"},
                }
            ]
        }
    )

    access_token: str = Field(
        description=(
            "Токен доступа. Передаётся в заголовке `Authorization: Bearer <токен>`. "
            "В логи не попадает."
        ),
    )
    token_type: Literal["bearer"] = Field(default="bearer", description="Тип токена, всегда `bearer`.")
    expires_at: datetime = Field(description="Момент, после которого токен перестаёт действовать.")
    user: UserOut = Field(description="Профиль вошедшего пользователя.")


class MeResponse(BaseModel):
    """Ответ `GET /auth/me`: текущий пользователь."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"user": {"id": 1, "username": "viewer", "role": "viewer"}},
            ]
        }
    )

    user: UserOut = Field(description="Текущий пользователь.")
