"""Роутер аутентификации: вход и текущий пользователь."""

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user, issue_token, verify_credentials
from app.schemas.auth import LoginRequest, LoginResponse, MeResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Вход в систему",
    responses={401: {"description": "Неверный логин или пароль"}},
)
def login(payload: LoginRequest) -> LoginResponse:
    """Принимает логин и пароль, возвращает токен доступа и профиль пользователя."""
    user = verify_credentials(payload.username, payload.password.get_secret_value())
    token, expires_at = issue_token(user.username)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_at=expires_at,
        user=user,
    )


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Текущий пользователь",
    responses={401: {"description": "Требуется токен"}},
)
def me(user: UserOut = Depends(get_current_user)) -> MeResponse:
    """Возвращает профиль пользователя, которому принадлежит предъявленный токен."""
    return MeResponse(user=user)
