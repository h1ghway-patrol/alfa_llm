"""Единый формат ошибок, `request_id` и заголовок `X-Request-ID`."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_unknown_route_uses_common_error_format(client: TestClient) -> None:
    response = client.get("/no-such-route")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "request_id"}
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"]


def test_error_body_carries_request_id_header(client: TestClient) -> None:
    response = client.get("/no-such-route")
    assert response.headers["X-Request-ID"] == response.json()["error"]["request_id"]


def test_request_id_is_generated_when_missing(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_incoming_request_id_is_preserved(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-ID": "trace-from-gateway"})
    assert response.headers["X-Request-ID"] == "trace-from-gateway"


def test_validation_error_format(client: TestClient) -> None:
    response = client.post("/auth/login", json={"username": "", "password": ""})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["message"]
    assert body["error"]["request_id"]


def test_unauthorized_error_format(client: TestClient) -> None:
    response = client.get("/clients")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
