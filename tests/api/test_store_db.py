from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import reset_settings_cache
from app.db import repositories as repo
from app.db.build import build
from app.db.connection import connect
from app.db.documents import add_document, save_classification
from app.db.load_clients import load_clients
from app.db.load_counterparties import load_counterparties
from app.db.load_payments import load_payments
from app.main import app

DATA = Path(__file__).resolve().parent.parent / "data"
SAMPLE = DATA / "clients_sample.csv"


@pytest.fixture()
def db_mode(tmp_path, monkeypatch):
    db_path = str(tmp_path / "app.db")
    build(db_path)
    conn = connect(db_path)
    try:
        load_clients(conn, str(SAMPLE))
        load_payments(conn, str(DATA / "payments_sample.csv"))
        load_counterparties(conn, str(DATA / "counterparties_sample.csv"))
        doc_id, _ = add_document(
            conn,
            kind="news",
            title="Курс юаня обновил максимум",
            source_name="Интерфакс",
            doc_date="2026-09-12",
            chunks=[{"section_path": None, "text": "Курс юаня вырос до 13,1 рубля."}],
        )
        save_classification(
            conn,
            doc_id,
            ["курс и валюта"],
            {"entities": [], "importance": 0.8, "key_facts": [{"text": "Курс юаня 13,1 ₽"}]},
        )
        repo.save_relevance(conn, "U_1465", [{"doc_id": doc_id, "score": 0.9, "reasons": ["ВЭД"]}])
    finally:
        conn.close()

    monkeypatch.setenv("USE_DB", "true")
    monkeypatch.setenv("DB_PATH", db_path)
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    reset_settings_cache()
    yield db_path
    reset_settings_cache()


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_db_mode_full_flow(db_mode):
    with TestClient(app) as client:
        viewer = _login(client, "viewer", "viewer-demo")

        clients = client.get("/clients", headers=viewer)
        assert clients.status_code == 200
        assert "U_1465" in [item["client_id"] for item in clients.json()]

        profile = client.get("/clients/U_1465/profile", headers=viewer)
        assert profile.status_code == 200
        assert profile.json()["payments"]
        connections = profile.json()["connections"]
        assert connections["top_outgoing"][0]["counterparty_id"] == "F_2"
        assert connections["top_incoming"][0]["counterparty_id"] == "F_1"
        assert connections["geography"]["cities"] == ["Казань", "Москва"]

        feed = client.get("/clients/U_1465/feed", headers=viewer)
        assert feed.status_code == 200
        assert feed.json()["total"] == 1
        event_id = feed.json()["items"][0]["event_id"]

        event = client.get(f"/events/{event_id}", headers=viewer)
        assert event.status_code == 200
        assert event.json()["facts"][0]["text"] == "Курс юаня 13,1 ₽"
        assert "13,1" in event.json()["text"]

        started = client.post(f"/clients/U_1465/events/{event_id}/insight", json={}, headers=viewer)
        assert started.status_code == 202
        run_id = started.json()["run_id"]
        assert run_id.isdigit()

        run = client.get(f"/runs/{run_id}", headers=viewer)
        assert run.status_code == 200
        assert run.json()["status"] == "done"
        assert run.json()["insight_id"]

        insight = client.get(f"/clients/U_1465/events/{event_id}/insight", headers=viewer)
        assert insight.status_code == 200
        insight_id = insight.json()["insight_id"]

        feedback = client.post("/feedback", json={"insight_id": insight_id, "rating": 1}, headers=viewer)
        assert feedback.status_code == 202

        existing = client.get(f"/clients/U_1465/events/{event_id}/insight", headers=viewer)
        assert existing.status_code == 200
        assert existing.json()["insight_id"] == insight_id

        missing = client.get("/runs/run_deadbeef", headers=viewer)
        assert missing.status_code == 404

        admin = _login(client, "admin", "admin-demo")
        trace = client.get(f"/runs/{run_id}/trace", headers=admin)
        assert trace.status_code == 200
        assert trace.json()["steps"]

        usage = client.get("/admin/usage", headers=admin)
        assert usage.status_code == 200
        assert usage.json()["days"]

        added = client.post(
            "/admin/news",
            headers=admin,
            json={
                "title": "ЦБ сохранил ключевую ставку",
                "text": "Банк России сохранил ключевую ставку на уровне 14% годовых.",
                "published_at": "2026-10-25T12:00:00Z",
                "source_name": "Проверка",
            },
        )
        assert added.status_code == 201
        assert added.json()["status"] == "done"
        assert added.json()["event_id"].isdigit()

    conn = connect(db_mode)
    try:
        assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 1
    finally:
        conn.close()
