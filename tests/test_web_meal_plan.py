from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from source.client.tcp_client import TCPClient, TCPClientError
from source.common.protocol import error_response, success_response
from source.web.main import app
from tests.meal_plan_fixtures import running_repository, sqlite_repository


@pytest.fixture
def meal_web(tmp_path, monkeypatch):
    repository = sqlite_repository(tmp_path / "meal-web.sqlite")
    with running_repository(repository) as (server, port):
        monkeypatch.setenv("TCP_HOST", "127.0.0.1")
        monkeypatch.setenv("TCP_PORT", str(port))
        with TestClient(app) as web:
            yield web, server


def test_meal_page_and_home_link_preserve_existing_routes(meal_web):
    web, _ = meal_web
    page = web.get("/meal-plan")
    assert page.status_code == 200 and 'data-classification-version="meal-categories-v1"' in page.text
    assert 'id="meal-form"' in page.text and '/static/meal-plan-v2.js?v=beverage-cards-20261113-2' in page.text
    assert 'id="meal-count-main"' in page.text and 'id="meal-custom-layout"' in page.text
    assert 'id="meal-structure"' not in page.text
    assert 'meal-pref-occasion' not in page.text and 'Ngân sách' not in page.text and 'Dịp ăn' not in page.text
    assert 'class="panel meal-people"' in page.text
    assert 'id="meal-portions"' not in page.text and 'Khẩu phần theo số người' not in page.text
    assert 'id="meal-shopping"' in page.text and 'id="meal-copy-list"' in page.text
    assert 'href="/meal-plan"' in web.get("/").text
    assert web.get("/recipes/1").status_code == 200
    assert web.post("/api/recommend", json={"ingredient_ids":[1,2]}).json()["data"]["algorithm"] == "proposed"
    assert web.post("/api/search", json={"query":"đậu phụ"}).json()["data"]["total"] > 0


def test_gateway_uses_real_tcp_and_preserves_request_id(meal_web, monkeypatch, tmp_path):
    web, _ = meal_web
    original = TCPClient.request
    seen = []
    def spy(client, op, payload, request_id=None):
        seen.append((op,payload,request_id))
        return original(client,op,payload,request_id)
    monkeypatch.setattr(TCPClient,"request",spy)
    payload = {"ingredient_ids":[1,2,6,7],"max_minutes":60,"max_total_minutes":90,"max_missing":2}
    response = web.post("/api/meal-plan",json=payload)
    body = response.json()
    assert response.status_code == 200 and body["ok"]
    assert seen[0][0] == "GENERATE_MEAL_PLAN" and seen[0][1] == {**payload,"excluded_ids":[],"locked_slots":[]}
    assert seen[0][2] == body["request_id"] == response.headers["x-request-id"]
    assert [i["recipe_id"] for i in body["data"]["plan"]["items"]] == [1,5,29]
    assert body["data"]["plan"]["missing_ids"] == [39,44]
    (tmp_path/"http-meal-demo.json").write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding="utf-8")


def test_http_replacement_and_empty_outcome(meal_web):
    web, _ = meal_web
    current = {"main":1,"vegetable":5,"soup":29}
    changed = web.post("/api/meal-plan", json={"current_plan":current,"locked_slots":["main","vegetable"]}).json()["data"]
    assert changed["changed_slots"] == ["soup"] and changed["plan"]["items"][0]["recipe_id"] == 1
    all_changed = web.post("/api/meal-plan",json={"current_plan":current}).json()["data"]
    assert all_changed["changed_slots"] == ["main","vegetable","soup"]
    empty = web.post("/api/meal-plan",json={"max_missing":0})
    assert empty.status_code == 200 and empty.json()["data"]["plan"] is None
    locked = web.post("/api/meal-plan",json={"current_plan":current,"locked_slots":["vegetable"],"excluded_ids":[7]})
    assert locked.json()["data"]["reason"]["code"] == "LOCKED_RECIPE_INCOMPATIBLE"


def test_http_partial_regeneration_comes_from_tcp(meal_web):
    web, _ = meal_web
    filters = {"excluded_ids":[11,46,22]}
    first = web.post("/api/meal-plan",json=filters).json()["data"]["plan"]
    current = {i["slot"]:i["recipe_id"] for i in first["items"]}
    changed = web.post("/api/meal-plan",json={**filters,"current_plan":current,"locked_slots":[]}).json()["data"]
    assert changed["warnings"] == ["PARTIAL_REGENERATION"]
    assert changed["changed_slots"] == ["main","soup"]


@pytest.mark.parametrize("occasion", ["snack", "drinking"])
def test_meal_v2_gateway_accepts_existing_snack_and_drinking_preferences(meal_web, occasion):
    web, _ = meal_web
    response = web.post("/api/meal-plan/v2", json={"people": 4, "preferences": {"occasion": occasion}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["algorithm"] == "meal-plan-v2"
    assert body["request_id"] == response.headers["x-request-id"]


def test_meal_v2_contract_accepts_layout_transition_with_removed_and_added_slots():
    from source.web.meal_plan_v2_contract import Data

    slots = ["main:1", "main:2", "main:3", "main:4", "vegetable:1", "soup:1"]
    data = {
        "dataset_version": "test-dataset", "classification_version": "test-classification",
        "algorithm": "meal-plan-v2", "layout_mode": "automatic",
        "counts": {"main": 4, "vegetable": 1, "soup": 1},
        "plan": {
            "items": [{"slot": slot, "recipe_id": 100 + index, "title": f"Dish {index}",
                       "minutes": 10, "matched_ids": [], "missing_ids": [], "missing_count": 0}
                      for index, slot in enumerate(slots)],
            "required_ids": [], "matched_ids": [], "missing_ids": [], "missing_count": 0,
            "total_minutes": 60, "time_basis": "sum_of_recipe_minutes",
            "shopping_list": [], "optional_shopping_list": [], "optional_missing_ids": [],
        },
        "changed_slots": ["main:1", "main:2", "main:3", "main:4", "vegetable:1", "vegetable:2", "soup:1", "soup:2"],
        "warnings": [], "reason": None, "preferences": {"occasion": "guests"},
        "metadata_version": "test-metadata", "people": 12,
    }

    parsed = Data.model_validate(data)
    assert len(parsed.changed_slots) == 8


@pytest.mark.parametrize("payload", [
    {"servings":2}, {"ingredient_ids":[True]}, {"ingredient_ids":[999]}, {"excluded_ids":[0]},
    {"ingredient_ids":[1],"excluded_ids":[1]}, {"max_missing":False}, {"max_minutes":"30"},
    {"max_total_minutes":721}, {"locked_slots":["main"]},
    {"current_plan":{"main":1,"vegetable":5,"soup":6},"locked_slots":["main","main"]},
    {"current_plan":{"main":999,"vegetable":5,"soup":6}},
    {"current_plan":{"main":1,"vegetable":5,"soup":6,"other":8}},
])
def test_http_rejects_bad_payload_without_server_failure(meal_web,payload):
    web, _ = meal_web
    response = web.post("/api/meal-plan",json=payload)
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_PAYLOAD"
    assert response.headers["x-request-id"] == response.json()["request_id"]
    assert web.get("/api/health").status_code == 200


@pytest.mark.parametrize("code,status", [("TIMEOUT",504),("UPSTREAM_UNAVAILABLE",503),("UPSTREAM_PROTOCOL",502)])
def test_gateway_transport_errors_are_mapped(meal_web,monkeypatch,code,status):
    def unavailable(*args,**kwargs):
        raise TCPClientError(code)
    monkeypatch.setattr(TCPClient,"request",unavailable)
    response = meal_web[0].post("/api/meal-plan",json={})
    assert response.status_code == status and response.json()["error"]["code"] == code


def test_stopped_real_tcp_server_returns_503(meal_web):
    web, server = meal_web
    server.shutdown()
    response = web.post("/api/meal-plan",json={})
    assert response.status_code in {503, 504} and not response.json()["ok"]
    assert response.json()["error"]["code"] in {"UPSTREAM_UNAVAILABLE", "CONNECT_TIMEOUT", "TIMEOUT", "UPSTREAM_DISCONNECTED"}


def test_old_server_unknown_operation_is_reported(meal_web,monkeypatch):
    monkeypatch.setattr(TCPClient,"request",lambda self,op,payload,request_id=None:
                        error_response(request_id,"UNKNOWN_OPERATION","unsupported operation"))
    response = meal_web[0].post("/api/meal-plan",json={})
    assert response.status_code == 502 and response.json()["error"]["code"] == "UNKNOWN_OPERATION"


@pytest.mark.parametrize("bad", [{"unexpected":1}, {"dataset_version":"test","plan":{}}, None])
def test_malformed_upstream_meal_data_is_502(meal_web,monkeypatch,bad):
    monkeypatch.setattr(TCPClient,"request",lambda self,op,payload,request_id=None: success_response(request_id,bad))
    response = meal_web[0].post("/api/meal-plan",json={})
    assert response.status_code == 502 and response.json()["error"]["code"] == "UPSTREAM_PROTOCOL"
