from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from source.client.tcp_client import TCPClient
from source.common import protocol
from tests.meal_plan_fixtures import REQUEST_ID, ROOT, running_repository, sqlite_repository


@pytest.fixture
def meal_tcp(tmp_path):
    repository = sqlite_repository(tmp_path / "meal-50.sqlite")
    with running_repository(repository) as (server, port):
        yield server, port


def test_tcp_meal_and_old_operations_keep_contract_and_persistent_connection(meal_tcp, tmp_path):
    _, port = meal_tcp
    client = TCPClient(port=port, persistent=True)
    old_calls = [("PING", {}), ("LIST_INGREDIENTS", {"query":"cà"}),
                 ("GET_RECIPE", {"recipe_id":1}), ("SEARCH_RECIPES", {"query":"dau phu"})]
    old_calls += [("RECOMMEND", {"ingredient_ids":[1,2],"algorithm":algorithm})
                  for algorithm in ("baseline", "proposed")]
    try:
        before = [client.request(op, payload, REQUEST_ID) for op,payload in old_calls]
        assert all(response["ok"] for response in before)
        sock = client.sock
        payload = {"ingredient_ids":[1,2,6,7], "max_minutes":60, "max_total_minutes":90, "max_missing":2}
        response = client.request("GENERATE_MEAL_PLAN", payload, REQUEST_ID)
        assert response["ok"] and response["request_id"] == REQUEST_ID and response["version"] == 1
        data = response["data"]
        assert data["dataset_version"] == "meal-test-50" and data["classification_version"] == "meal-categories-v1"
        assert data["algorithm"] == "meal-plan-v1" and data["changed_slots"] == []
        assert [i["recipe_id"] for i in data["plan"]["items"]] == [1,5,29]
        assert data["plan"]["missing_ids"] == [39,44]
        assert "score" not in data["plan"] and "score" not in data["plan"]["items"][0]
        (tmp_path / "meal-plan-demo.json").write_text(json.dumps({"request":{
            "version":1,"request_id":REQUEST_ID,"op":"GENERATE_MEAL_PLAN","payload":payload},
            "response":response}, ensure_ascii=False, indent=2), encoding="utf-8")
        assert [client.request(op, body, REQUEST_ID) for op,body in old_calls] == before
        assert client.sock is sock
        assert before[-2]["data"]["algorithm"] == "baseline"
        assert before[-1]["data"]["algorithm"] == "proposed"
    finally:
        client.close()


@pytest.mark.parametrize("payload", [
    {"ingredient_ids":[999]}, {"excluded_ids":[999]}, {"ingredient_ids":[True]},
    {"max_missing":False}, {"unexpected":1},
    {"current_plan":{"main":999,"vegetable":5,"soup":6}},
    {"current_plan":{"main":8,"vegetable":5,"soup":6}},
])
def test_tcp_rejects_invalid_or_unknown_ids_and_still_serves_ping(meal_tcp, payload):
    _, port = meal_tcp
    client = TCPClient(port=port, persistent=True)
    try:
        response = client.request("GENERATE_MEAL_PLAN", payload, REQUEST_ID)
        assert response["ok"] is False and response["data"] is None
        assert response["request_id"] == REQUEST_ID and response["error"]["code"] == "INVALID_PAYLOAD"
        sock = client.sock
        assert client.request("PING", {})["ok"] and client.sock is sock
    finally:
        client.close()


def test_tcp_replacement_and_no_match_are_successful_business_responses(meal_tcp):
    _, port = meal_tcp
    client = TCPClient(port=port)
    current = {"main":1,"vegetable":5,"soup":29}
    replacement = client.request("GENERATE_MEAL_PLAN", {"current_plan":current,"locked_slots":["main","vegetable"]})
    assert replacement["ok"] and replacement["data"]["changed_slots"] == ["soup"]
    assert [i["recipe_id"] for i in replacement["data"]["plan"]["items"]][:2] == [1,5]
    empty = client.request("GENERATE_MEAL_PLAN", {"max_missing":0}, REQUEST_ID)
    assert empty["ok"] and empty["data"]["plan"] is None
    assert empty["data"]["reason"]["code"] == "CONSTRAINTS_UNSATISFIED"
    assert empty["data"]["changed_slots"] == [] and empty["data"]["warnings"]


def test_old_server_operation_allowlist_returns_unknown_operation(meal_tcp, monkeypatch):
    # The pre-B validator is unchanged except for this one new allowlist entry.
    monkeypatch.setattr(protocol, "SUPPORTED_OPS", protocol.SUPPORTED_OPS - {"GENERATE_MEAL_PLAN"})
    _, port = meal_tcp
    client = TCPClient(port=port, persistent=True)
    try:
        response = client.request("GENERATE_MEAL_PLAN", {}, REQUEST_ID)
        assert not response["ok"] and response["error"]["code"] == "UNKNOWN_OPERATION"
        assert response["request_id"] == REQUEST_ID
        assert client.request("PING", {})["ok"]
    finally:
        client.close()


@pytest.mark.parametrize("stdout_encoding", ["utf-8", "cp1252"])
def test_cli_can_generate_meal_without_http(meal_tcp, stdout_encoding):
    _, port = meal_tcp
    env = {**os.environ, "PYTHONIOENCODING":stdout_encoding, "PYTHONDONTWRITEBYTECODE":"1"}
    result = subprocess.run([sys.executable, "-B", "-m", "source.client.cli", "--host", "127.0.0.1",
        "--port", str(port), "--op", "GENERATE_MEAL_PLAN", "--payload", '{}'],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0, result.stderr
    response = json.loads(result.stdout)
    assert response["version"] == 1 and response["ok"] and len(response["data"]["plan"]["items"]) == 3
    assert protocol.valid_uuid(response["request_id"])
