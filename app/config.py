"""Конфигурация приложения из переменных окружения.

Все настройки читаются один раз при старте. Если переменная задана неверно,
приложение падает сразу и с понятным текстом, а не молча работает с
неверными значениями.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse

from dotenv import load_dotenv

ENVIRONMENTS = ("local", "dev", "staging", "production")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8080",
)

DEFAULT_REQUEST_ID_HEADER = "X-Request-ID"


class ConfigError(RuntimeError):
    """Конфигурацию прочитать не удалось."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Значения настроек, разобранные из окружения."""

    app_name: str
    environment: str
    log_level: str
    cors_origins: tuple[str, ...]
    cors_allow_credentials: bool
    request_id_header: str
    viewer_password: str
    admin_password: str
    daily_token_limit_tokens: int | None
    budget_rub: float | None
    use_db: bool
    db_path: str
    llm_provider: str

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


def _parse_cors_origins(raw: str) -> tuple[str, ...]:
    origins = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not origins:
        raise ValueError("список пуст")
    for origin in origins:
        parsed = urlparse(origin)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"адрес '{origin}' не является http(s)-адресом")
    return origins


def _parse_bool(raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"значение '{raw}' не является true/false")


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Читает настройки из окружения.

    Собирает все проблемы сразу и сообщает их одним сообщением: так при
    старте видно, что именно поправить.
    """
    if env is None:
        load_dotenv(override=False)

    source = os.environ if env is None else env
    problems: list[str] = []

    def read(name: str, default: str | None = None) -> str | None:
        value = source.get(name)
        if value is None or value.strip() == "":
            if default is None:
                problems.append(f"переменная {name} не задана")
                return None
            return default
        return value.strip()

    app_name = read("APP_NAME", "alfa_llm") or "alfa_llm"

    environment = read("APP_ENV", "local") or "local"
    if environment not in ENVIRONMENTS:
        problems.append(f"APP_ENV={environment!r} — допустимо: {', '.join(ENVIRONMENTS)}")
        environment = "local"

    log_level = (read("LOG_LEVEL", "INFO") or "INFO").upper()
    if log_level not in LOG_LEVELS:
        problems.append(f"LOG_LEVEL={log_level!r} — допустимо: {', '.join(LOG_LEVELS)}")
        log_level = "INFO"

    raw_origins = read("CORS_ORIGINS", ",".join(DEFAULT_CORS_ORIGINS))
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    if raw_origins is not None:
        try:
            cors_origins = _parse_cors_origins(raw_origins)
        except ValueError as exc:
            problems.append(f"CORS_ORIGINS — {exc}; ожидается список http(s)-адресов через запятую")
            cors_origins = DEFAULT_CORS_ORIGINS

    raw_credentials = read("CORS_ALLOW_CREDENTIALS", "false")
    cors_allow_credentials = False
    if raw_credentials is not None:
        try:
            cors_allow_credentials = _parse_bool(raw_credentials)
        except ValueError as exc:
            problems.append(f"CORS_ALLOW_CREDENTIALS — {exc}")

    request_id_header = read("REQUEST_ID_HEADER", DEFAULT_REQUEST_ID_HEADER) or DEFAULT_REQUEST_ID_HEADER

    viewer_password = read("VIEWER_PASSWORD", "viewer-demo") or "viewer-demo"
    admin_password = read("ADMIN_PASSWORD", "admin-demo") or "admin-demo"

    daily_token_limit_tokens: int | None = None
    raw_limit = source.get("DAILY_TOKEN_LIMIT_TOKENS", "").strip()
    if raw_limit:
        try:
            daily_token_limit_tokens = int(raw_limit)
            if daily_token_limit_tokens <= 0:
                raise ValueError
        except ValueError:
            problems.append(f"DAILY_TOKEN_LIMIT_TOKENS={raw_limit!r} — ожидается целое число больше нуля")
            daily_token_limit_tokens = None

    budget_rub: float | None = None
    raw_budget = source.get("BUDGET_RUB", "").strip()
    if raw_budget:
        try:
            budget_rub = float(raw_budget)
            if budget_rub <= 0:
                raise ValueError
        except ValueError:
            problems.append(f"BUDGET_RUB={raw_budget!r} — ожидается число больше нуля")
            budget_rub = None

    raw_use_db = read("USE_DB", "false")
    use_db = False
    if raw_use_db is not None:
        try:
            use_db = _parse_bool(raw_use_db)
        except ValueError as exc:
            problems.append(f"USE_DB — {exc}")

    db_path = read("DB_PATH", "data/app.db") or "data/app.db"

    llm_provider = (read("LLM_PROVIDER", "fake") or "fake").lower()
    if llm_provider not in ("fake", "remote"):
        problems.append(f"LLM_PROVIDER={llm_provider!r} — допустимо: fake, remote")
        llm_provider = "fake"

    if environment == "production" and cors_allow_credentials and "*" in cors_origins:
        problems.append("в production нельзя одновременно разрешать CORS_ALLOW_CREDENTIALS и Origin '*'")
    if environment == "production" and llm_provider == "fake":
        problems.append("в production нельзя использовать LLM_PROVIDER=fake")

    if problems:
        listed = "\n".join(f"  - {problem}" for problem in problems)
        raise ConfigError(
            "Не удалось прочитать конфигурацию из переменных окружения:\n"
            f"{listed}\n"
            "Поправьте значения и запустите приложение снова."
        )

    return Settings(
        app_name=app_name,
        environment=environment,
        log_level=log_level,
        cors_origins=cors_origins,
        cors_allow_credentials=cors_allow_credentials,
        request_id_header=request_id_header,
        viewer_password=viewer_password,
        admin_password=admin_password,
        daily_token_limit_tokens=daily_token_limit_tokens,
        budget_rub=budget_rub,
        use_db=use_db,
        db_path=db_path,
        llm_provider=llm_provider,
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Возвращает настройки, читая их из окружения при первом обращении."""
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def reset_settings_cache() -> None:
    """Сбрасывает кеш настроек. Нужно в тестах, где меняют окружение."""
    global _settings
    _settings = None
