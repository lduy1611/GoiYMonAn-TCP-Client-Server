from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from source.client.tcp_client import TCPClientError
from source.database.seed import seed
from source.server.main import TCPServer
from source.web.main import app


@pytest.fixture
def web_with_tcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "recipes.db"
    seed(db)
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server = TCPServer("127.0.0.1", port, db)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            probe = socket.create_connection(("127.0.0.1", port), timeout=0.1)
            probe.close()
            break
        except OSError:
            time.sleep(0.01)
    monkeypatch.setenv("TCP_HOST", "127.0.0.1")
    monkeypatch.setenv("TCP_PORT", str(port))
    with TestClient(app) as client:
        yield client, server, thread
    server.shutdown()
    thread.join(timeout=2)


def test_web_routes_use_real_tcp_server(web_with_tcp):
    client, server, _ = web_with_tcp
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.headers["x-request-id"] == health.json()["request_id"]
    assert health.json()["data"]["status"] == "ok"

    ingredients = client.get("/api/ingredients", params={"query": "cà", "limit": 20})
    assert ingredients.status_code == 200
    assert ingredients.json()["data"]["items"][0]["name"] == "Cà chua"

    recommendation = client.post("/api/recommend", json={"ingredient_ids": [1, 2], "max_minutes": 20, "top_k": 5})
    assert recommendation.status_code == 200
    assert recommendation.json()["data"]["algorithm"] == "proposed"
    assert recommendation.json()["data"]["items"]

    detail = client.get("/api/recipes/1")
    assert detail.status_code == 200
    assert detail.json()["data"]["title"] == "Trứng sốt cà chua"

    detail_page = client.get("/recipes/1")
    assert detail_page.status_code == 200
    assert 'data-recipe-id="1"' in detail_page.text
    assert "/static/detail.js" in detail_page.text


def test_web_reports_tcp_outage_without_db_bypass(web_with_tcp):
    client, server, thread = web_with_tcp
    server.shutdown()
    thread.join(timeout=2)
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["ok"] is False
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_web_page_and_validation(web_with_tcp):
    client, _, _ = web_with_tcp
    page = client.get("/")
    assert page.status_code == 200
    assert "Hôm nay ăn gì?" in page.text
    invalid = client.post("/api/recommend", json={"ingredient_ids": []})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "INVALID_PAYLOAD"
    overlap = client.post("/api/recommend", json={"ingredient_ids": [1], "excluded_ids": [1]})
    assert overlap.status_code == 422
    assert overlap.json()["error"]["code"] == "INVALID_PAYLOAD"


def test_missing_recipe_is_404_with_correlated_error(web_with_tcp):
    client, _, _ = web_with_tcp
    response = client.get("/api/recipes/999999")
    assert response.status_code == 404
    envelope = response.json()
    assert envelope["version"] == 1
    assert envelope["ok"] is False
    assert envelope["data"] is None
    assert envelope["request_id"] == response.headers["x-request-id"]
    assert envelope["error"] == {"code": "NOT_FOUND", "message": "Không tìm thấy món ăn với mã đã yêu cầu."}
    assert client.get("/api/recipes/1").status_code == 200
    assert client.get("/api/health").status_code == 200


@pytest.mark.parametrize("code,status", [("TRUNCATED_FRAME", 502), ("TIMEOUT", 504)])
def test_web_maps_incomplete_or_timed_out_tcp_response(monkeypatch, code, status):
    def fail_request(*_args, **_kwargs):
        raise TCPClientError(code)
    monkeypatch.setattr("source.web.main.TCPClient.request", fail_request)
    with TestClient(app) as client:
        response = client.get("/api/recipes/1")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["request_id"] == response.headers["x-request-id"]
