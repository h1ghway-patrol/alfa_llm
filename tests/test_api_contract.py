"""Сквозной сценарий фронта на заглушках: вход → клиент → лента → инсайт → источник."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "app is running"}


def test_login_and_me(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"username": "viewer", "password": "viewer-demo"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "viewer"

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "viewer"


def test_login_with_wrong_password(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"username": "viewer", "password": "wrong"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_client_list_and_profile(client: TestClient, viewer_headers: dict[str, str]) -> None:
    listing = client.get("/clients", headers=viewer_headers)
    assert listing.status_code == 200
    client_ids = [item["client_id"] for item in listing.json()]
    assert "U_1465" in client_ids

    profile = client.get("/clients/U_1465/profile", headers=viewer_headers)
    assert profile.status_code == 200
    body = profile.json()
    assert body["client_id"] == "U_1465"
    assert body["products"]
    assert body["tags"]


def test_feed_filters(client: TestClient, viewer_headers: dict[str, str]) -> None:
    feed = client.get("/clients/U_1465/feed", headers=viewer_headers)
    assert feed.status_code == 200
    body = feed.json()
    assert body["items"]
    assert body["total"] == len(body["items"])
    for item in body["items"]:
        assert 0.0 <= item["relevance_score"] <= 1.0
        assert len(item["relevance_reasons"]) <= 3

    filtered = client.get(
        "/clients/U_1465/feed",
        params={"topic": "key_rate", "limit": 2},
        headers=viewer_headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] <= 2
    for item in filtered.json()["items"]:
        assert "key_rate" in item["topics"]


def test_event_and_source(client: TestClient, viewer_headers: dict[str, str]) -> None:
    event = client.get("/events/doc_2026_09_11_key_rate", headers=viewer_headers)
    assert event.status_code == 200
    assert event.json()["event_id"] == "doc_2026_09_11_key_rate"

    source = client.get("/sources/src_key_rate_2026_09_11", headers=viewer_headers)
    assert source.status_code == 200
    assert source.json()["freshness"] in ("actual", "outdated", "unknown")


def test_ready_insight_is_returned_immediately(
    client: TestClient, viewer_headers: dict[str, str]
) -> None:
    response = client.get(
        "/clients/U_1465/events/doc_2026_09_11_key_rate/insight",
        headers=viewer_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "done"
    assert body["what_happened"]
    assert body["consequences"]["risks"] is not None


def test_missing_insight_returns_404(client: TestClient, viewer_headers: dict[str, str]) -> None:
    response = client.get(
        "/clients/U_57706/events/doc_2026_09_08_labor/insight",
        headers=viewer_headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_run_flow_creates_insight(client: TestClient, viewer_headers: dict[str, str]) -> None:
    response = client.post(
        "/clients/U_57706/events/doc_2026_09_08_labor/insight",
        json={},
        headers=viewer_headers,
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    assert response.json()["status"] in ("queued", "running", "done")

    run = client.get(f"/runs/{run_id}", headers=viewer_headers)
    assert run.status_code == 200
    assert run.json()["status"] == "done"
    assert run.json()["insight_id"]

    insight = client.get(
        "/clients/U_57706/events/doc_2026_09_08_labor/insight",
        headers=viewer_headers,
    )
    assert insight.status_code == 200
    assert insight.json()["insight_id"] == run.json()["insight_id"]


def test_ask_and_feedback(client: TestClient, viewer_headers: dict[str, str]) -> None:
    ask = client.post(
        "/clients/U_1465/events/doc_2026_09_11_key_rate/ask",
        json={"question": "Как это повлияет на обслуживание кредита?"},
        headers=viewer_headers,
    )
    assert ask.status_code == 200
    assert ask.json()["answer"]

    feedback = client.post(
        "/feedback",
        json={"insight_id": "ins_2026_09_11_u_1465", "rating": 1, "comment": "Полезно"},
        headers=viewer_headers,
    )
    assert feedback.status_code == 202
    assert feedback.json()["status"] == "accepted"


def test_admin_news_and_usage(client: TestClient, admin_headers: dict[str, str]) -> None:
    usage = client.get("/admin/usage", headers=admin_headers)
    assert usage.status_code == 200
    body = usage.json()
    assert set(body) == {"days", "total_tokens", "daily_limit_tokens", "budget_rub"}
    assert body["total_tokens"] == sum(day["tokens_in"] + day["tokens_out"] for day in body["days"])

    news = client.post(
        "/admin/news",
        json={
            "title": "Тестовая новость",
            "text": "Текст тестовой новости для проверки контракта.",
            "published_at": "2026-10-01T10:00:00Z",
            "source_name": "Интерфакс",
        },
        headers=admin_headers,
    )
    assert news.status_code == 201
    assert news.json()["status"] == "queued"


def test_admin_endpoints_forbidden_for_viewer(
    client: TestClient, viewer_headers: dict[str, str]
) -> None:
    response = client.get("/admin/usage", headers=viewer_headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
