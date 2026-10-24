"""Конфигурация из окружения: читается один раз, при ошибке приложение падает."""

from __future__ import annotations

import pytest

from app.config import ConfigError, load_settings


def test_defaults_are_applied() -> None:
    settings = load_settings({})
    assert settings.environment == "local"
    assert settings.log_level == "INFO"
    assert settings.cors_origins
    assert settings.request_id_header == "X-Request-ID"


def test_valid_environment_is_parsed() -> None:
    settings = load_settings(
        {
            "APP_NAME": "test",
            "APP_ENV": "dev",
            "LOG_LEVEL": "debug",
            "CORS_ORIGINS": "http://localhost:5173,http://localhost:3000",
            "CORS_ALLOW_CREDENTIALS": "true",
        }
    )
    assert settings.app_name == "test"
    assert settings.environment == "dev"
    assert settings.log_level == "DEBUG"
    assert settings.cors_origins == ("http://localhost:5173", "http://localhost:3000")
    assert settings.cors_allow_credentials is True


@pytest.mark.parametrize(
    ("env", "fragment"),
    [
        ({"APP_ENV": "bogus"}, "APP_ENV"),
        ({"LOG_LEVEL": "LOUD"}, "LOG_LEVEL"),
        ({"CORS_ORIGINS": "ftp://bad"}, "CORS_ORIGINS"),
        ({"CORS_ALLOW_CREDENTIALS": "perhaps"}, "CORS_ALLOW_CREDENTIALS"),
    ],
)
def test_broken_environment_fails_with_explanation(env: dict[str, str], fragment: str) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_settings(env)
    message = str(excinfo.value)
    assert fragment in message
    assert "Поправьте значения" in message


def test_all_problems_are_reported_at_once() -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_settings({"APP_ENV": "bogus", "LOG_LEVEL": "LOUD"})
    message = str(excinfo.value)
    assert "APP_ENV" in message
    assert "LOG_LEVEL" in message
