"""Общие фикстуры тестов: приложение и токены."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("APP_NAME", "alfa_llm_test")
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("VIEWER_PASSWORD", "viewer-demo")
os.environ.setdefault("ADMIN_PASSWORD", "admin-demo")


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    """Тестовый клиент приложения."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def viewer_headers(client: TestClient) -> dict[str, str]:
    """Заголовки с токеном обычного пользователя."""
    response = client.post(
        "/auth/login",
        json={"username": "viewer", "password": "viewer-demo"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin_headers(client: TestClient) -> dict[str, str]:
    """Заголовки с токеном администратора."""
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin-demo"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
