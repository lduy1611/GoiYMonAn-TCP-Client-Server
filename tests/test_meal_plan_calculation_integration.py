"""Real local TCP/HTTP transport, using temporary legacy DBs and synthetic reviews.

Never connects MySQL, imports pilot dossiers, or publishes an approval.
"""
from copy import deepcopy
from dataclasses import replace
import sqlite3

from fastapi.testclient import TestClient
import pytest

from source.client.tcp_client import TCPClient, TCPClientError
from source.common.protocol import ProtocolError, encode_frame, success_response
from source.server.meal_plan_calculation import calculate, unavailable, validate
from source.web.main import app
from tests.calculation_fixtures import fixture_catalog, test_line
from tests.meal_plan_fixtures import REQUEST_ID
from tests.test_meal_plan_integration import meal_tcp
from tests.test_web_meal_plan import meal_web
from tests.test_meal_plan_calculation import INVALID_PAYLOADS


def test_legacy_sqlite_adapter_stays_disabled_and_returns_incomplete(meal_web):
    web, server = meal_web
    body = web.post('/api/meal-plan/calculate', json={"recipe_ids": [30, 29, 9], "people": 4})
    assert body.status_code == 200 and body.json()["ok"]
    data = body.json()["data"]
    assert data["recipe_ids"] == [30, 29, 9] and data["people"] == 4
    assert data["status"] == "INCOMPLETE" and data["known_ingredients"] == []
    assert all(r["reasons"][0]["code"] == "APPROVED_DATA_UNAVAILABLE" for r in data["recipes"])
    assert body.json()["request_id"] == body.headers["x-request-id"]
    # SQLite remains the legacy-only regression adapter, without v2 data or proposal imports.
    connection = server.repository.connect()
    try:
        assert not connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'v2_%'").fetchall()
    finally:
        connection.close()


def test_http_to_tcp_uses_only_server_supplied_test_catalog(meal_web, monkeypatch):
    web, server = meal_web
    seen = []
    def loader(connection, recipe_ids):
        seen.append(recipe_ids)
        return fixture_catalog(recipe_ids)
    monkeypatch.setattr(server.repository, "calculation_catalog", loader)
    response = web.post('/api/meal-plan/calculate', json={"recipe_ids": [1, 5], "people": 4})
    assert response.status_code == 200
    data = response.json()["data"]
    assert seen == [(1, 5)] and data["status"] == "COMPLETE"
    assert data["known_ingredients"][0]["quantity_value"] == "250"
    assert data["portion_policy_version"].startswith("TEST_ONLY")
    # Recalculate using the same recipe/revision IDs, not the previous scaled output.
    again = web.post('/api/meal-plan/calculate', json={"recipe_ids": [1, 5], "people": 2}).json()["data"]
    assert again["known_ingredients"][0]["quantity_value"] == "125"
    assert [r["revision_id"] for r in again["recipes"]] == [101, 105]


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
def test_bad_http_contract_never_reaches_tcp(monkeypatch, payload):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid payload reached TCP")
    monkeypatch.setattr(TCPClient, "request", forbidden)
    with TestClient(app) as client:
        response = client.post('/api/meal-plan/calculate', json=payload)
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_PAYLOAD"


def test_real_tcp_rejects_bad_payloads_and_unknown_ids_without_losing_connection(meal_tcp):
    client = TCPClient(port=meal_tcp[1], persistent=True)
    try:
        for payload in INVALID_PAYLOADS:
            reply = client.request("CALCULATE_MEAL_PLAN", payload, REQUEST_ID)
            assert not reply["ok"] and reply["error"]["code"] == "INVALID_PAYLOAD"
        sock = client.sock
        reply = client.request("CALCULATE_MEAL_PLAN", {"recipe_ids": [999], "people": 4}, REQUEST_ID)
        assert reply["error"]["code"] == "NOT_FOUND"
        assert client.request("PING", {})["ok"] and client.sock is sock
    finally:
        client.close()


def test_missing_recipe_maps_to_http_404(meal_web):
    response = meal_web[0].post('/api/meal-plan/calculate', json={"recipe_ids": [999], "people": 4})
    assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("code,status", [("TIMEOUT", 504), ("UPSTREAM_UNAVAILABLE", 503),
    ("UPSTREAM_PROTOCOL", 502), ("FRAME_LENGTH", 502), ("DB_ERROR", 503)])
def test_existing_gateway_transport_error_mapping(monkeypatch, code, status):
    def unavailable_tcp(*args, **kwargs):
        raise TCPClientError(code)
    monkeypatch.setattr(TCPClient, "request", unavailable_tcp)
    with TestClient(app) as web:
        response = web.post('/api/meal-plan/calculate', json={"recipe_ids": [1], "people": 4})
    assert response.status_code == status and response.json()["error"]["code"] == code


def test_db_error_is_not_disguised_as_missing_approval(meal_web, monkeypatch):
    def broken(*args):
        raise sqlite3.DatabaseError("TEST_ONLY simulated database failure")
    monkeypatch.setattr(meal_web[1].repository, "calculation_catalog", broken)
    response = meal_web[0].post('/api/meal-plan/calculate', json={"recipe_ids": [1], "people": 4})
    assert response.status_code == 503 and response.json()["error"]["code"] == "DB_ERROR"


def test_stopped_tcp_server_returns_existing_503(meal_web):
    web, server = meal_web
    server.shutdown()
    response = web.post('/api/meal-plan/calculate', json={"recipe_ids": [1], "people": 4})
    assert response.status_code == 503


@pytest.mark.parametrize("corruption", ["recipe_ids", "people", "completeness", "reason", "provenance", "quantity"])
def test_invalid_upstream_calculation_is_502(monkeypatch, corruption):
    data = {"dataset_version": "TEST_ONLY", **calculate(validate({"recipe_ids": [1], "people": 4}), fixture_catalog((1,)))}
    if corruption == "recipe_ids":
        data["recipe_ids"] = [5]
        data["recipes"][0]["recipe_id"] = 5
    elif corruption == "people":
        data["people"] = 3
    elif corruption == "completeness":
        data["totals_complete"] = False
    elif corruption == "reason":
        data = {"dataset_version": "TEST_ONLY", **unavailable(validate({"recipe_ids": [1], "people": 4}))}
        data["recipes"][0]["reasons"] = []
    elif corruption == "provenance":
        data["known_ingredients"][0]["uses"][0]["line_id"] = 49
    else:
        data["known_ingredients"][0]["quantity_min"] = "-1"
    monkeypatch.setattr(TCPClient, "request", lambda self, op, payload, request_id=None: success_response(request_id, data))
    with TestClient(app) as web:
        response = web.post('/api/meal-plan/calculate', json={"recipe_ids": [1], "people": 4})
    assert response.status_code == 502 and response.json()["error"]["code"] == "UPSTREAM_PROTOCOL"


def test_frame_limit_fallback_preserves_selection_and_connection(meal_tcp, monkeypatch):
    server, port = meal_tcp
    ids = (1, 2, 3, 4, 5, 6)
    catalog = fixture_catalog(ids)
    revisions = {rid: replace(rev, lines=tuple(test_line(i, ingredient_id=1000+i,
        name="TEST_ONLY_" + "x" * 240, ingredient_form="TEST_ONLY_" + "y" * 60)
        for i in range(1, 51))) for rid, rev in catalog.revisions.items()}
    catalog = replace(catalog, revisions=revisions)
    raw = calculate(validate({"recipe_ids": list(ids), "people": 100}), catalog)
    with pytest.raises(ProtocolError, match="65536"):
        encode_frame(success_response(REQUEST_ID, {"dataset_version": "TEST_ONLY", **raw}))
    monkeypatch.setattr(server.repository, "calculation_catalog", lambda *args: catalog)
    client = TCPClient(port=port, persistent=True)
    try:
        response = client.request("CALCULATE_MEAL_PLAN", {"recipe_ids": list(ids), "people": 100})
        assert response["ok"] and len(encode_frame(response)) <= 65540
        data = response["data"]
        assert data["recipe_ids"] == list(ids) and data["people"] == 100
        assert data["status"] == "INCOMPLETE" and data["known_ingredients"] == []
        assert all(r["reasons"][0]["code"] == "RESULT_TOO_LARGE" for r in data["recipes"])
        sock = client.sock
        assert client.request("PING", {})["ok"] and client.sock is sock
    finally:
        client.close()


def test_calculation_does_not_change_generators_search_or_b0_p1(meal_tcp, monkeypatch):
    server, port = meal_tcp
    monkeypatch.setattr(server.repository, "calculation_catalog", lambda *args: fixture_catalog())
    client = TCPClient(port=port, persistent=True)
    calls = [("GENERATE_MEAL_PLAN", {}), ("GENERATE_MEAL_PLAN_V2", {}),
             ("SEARCH_RECIPES", {"query": "ca"})] + [("RECOMMEND",
             {"ingredient_ids": [1, 2], "algorithm": a}) for a in ("baseline", "proposed")]
    try:
        before = deepcopy([client.request(op, payload, REQUEST_ID) for op, payload in calls])
        for people in (2, 4, 8):
            assert client.request("CALCULATE_MEAL_PLAN", {"recipe_ids": [1, 5], "people": people})["data"]["status"] == "COMPLETE"
        assert [client.request(op, payload, REQUEST_ID) for op, payload in calls] == before
    finally:
        client.close()
