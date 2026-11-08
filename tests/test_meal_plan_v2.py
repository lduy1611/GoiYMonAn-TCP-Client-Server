from itertools import product
import time

import pytest
from source.client.tcp_client import TCPClient, TCPClientError
from source.common.protocol import ProtocolError, encode_frame
from source.server.meal_plan import default_classification, generate_meal_plan, validate_meal_plan
from source.server.meal_plan_v2 import generate, validate
from tests.meal_plan_fixtures import REQUEST_ID, full_dataset
from tests.test_meal_plan_integration import meal_tcp
from tests.test_web_meal_plan import meal_web


def run(payload=None, recipes=None):
    return generate(full_dataset()[0] if recipes is None else recipes,
                    validate(payload or {}, REQUEST_ID), default_classification(), REQUEST_ID)


def current(data):
    return {i["slot"]: i["recipe_id"] for i in data["plan"]["items"]}


@pytest.mark.parametrize("counts", [dict(zip(("main", "vegetable", "soup"), v))
                                  for v in product(range(3), repeat=3) if sum(v)])
def test_all_count_configurations_have_distinct_correct_roles(counts):
    reply = run({"counts": counts})
    plan = reply["plan"]
    assert plan and len(plan["items"]) == sum(counts.values())
    assert len(set(current(reply).values())) == sum(counts.values())
    assert all(default_classification().categories[i["recipe_id"]] == i["slot"].split(":")[0] for i in plan["items"])
    assert {g: sum(i["slot"].startswith(g + ":") for i in plan["items"]) for g in counts} == counts


@pytest.mark.parametrize("locks", [["main:1"], ["main:1", "vegetable:1"], ["main:1", "vegetable:1", "soup:1"]])
def test_explicit_pins_are_never_changed(locks):
    old = current(run())
    result = run({"action": "regenerate", "current_plan": old, "locked_slots": locks})
    if len(locks) == 3:
        assert result["plan"] is None and result["reason"]["code"] == "ALL_LOCKED"
        # Applying conditions can still validate the unchanged pinned plan.
        assert current(run({"current_plan": old, "locked_slots": locks})) == old
    else:
        assert all(current(result)[k] == old[k] for k in locks)
        assert current(result) != old


def test_single_replace_locks_every_other_slot_on_server():
    counts = {"main": 2, "vegetable": 2, "soup": 2}
    old = current(run({"counts": counts}))
    reply = run({"counts": counts, "current_plan": old, "replace_slot": "soup:2", "locked_slots": ["main:1"]})
    new = current(reply)
    assert reply["changed_slots"] == ["soup:2"]
    assert all(new[k] == old[k] for k in old if k != "soup:2")
    pinned = run({"counts": counts, "current_plan": old, "replace_slot": "soup:2", "locked_slots": ["soup:2"]})
    assert pinned["reason"]["code"] == "PINNED_TARGET" and pinned["plan"] is None


def test_count_changes_keep_pins_and_do_not_silently_remove_pinned_positions():
    old = current(run())
    reply = run({"counts": {"main": 2, "vegetable": 1, "soup": 1}, "current_plan": old, "locked_slots": ["main:1"]})
    expanded = current(reply)
    assert len(expanded) == 4 and expanded["main:1"] == old["main:1"]
    conflict = run({"current_plan": expanded, "locked_slots": ["main:2"]})
    assert conflict["plan"] is None and conflict["reason"]["code"] == "PINNED_SLOT_REMOVED"
    assert conflict["reason"]["slots"] == ["main:2"]


def test_filters_exclude_optional_ingredients_and_report_pinned_conflicts():
    recipes = full_dataset()[0]
    by_id = {r["id"]: r for r in recipes}
    result = run({"excluded_ids": [7], "max_minutes": 60, "max_total_minutes": 100})
    assert result["plan"] and result["plan"]["total_minutes"] <= 100
    assert all(7 not in by_id[i]["all_ids"] and by_id[i]["minutes"] <= 60 for i in current(result).values())
    old = {"main:1": 4, "vegetable:1": 9, "soup:1": 6}
    conflict = run({"current_plan": old, "locked_slots": ["main:1"], "excluded_ids": [7]})
    assert conflict["reason"]["code"] == "LOCKED_RECIPE_INCOMPATIBLE"
    assert conflict["reason"]["slots"] == ["main:1"]


def test_shortage_and_combination_constraints_have_specific_reasons():
    small = [r for r in full_dataset()[0] if r["id"] in {1, 5, 6}]
    shortage = run({"counts": {"main": 1, "vegetable": 2, "soup": 1}}, small)
    assert shortage["reason"]["code"] == "INSUFFICIENT_GROUP"
    assert shortage["reason"]["groups"] == [{"group": "vegetable", "requested": 2, "available": 1}]
    assert shortage["reason"]["suggestions"]
    for limits in ({"max_missing": 0}, {"max_total_minutes": 1}):
        assert run(limits)["reason"]["code"] == "CONSTRAINTS_UNSATISFIED"
    old = current(run({}, small))
    assert run({"action": "regenerate", "current_plan": old}, small)["reason"]["code"] == "NO_ALTERNATIVE"


def test_reordering_is_not_an_alternative_and_input_order_does_not_change_results():
    small = [r for r in full_dataset()[0] if r["id"] in {1, 3, 5, 6}]
    payload = {"counts": {"main": 2, "vegetable": 1, "soup": 1}}
    first = run(payload, small)
    assert first == run(payload, list(reversed(small)))
    assert run({**payload, "current_plan": current(first), "action": "regenerate"}, small)["plan"] is None


@pytest.mark.parametrize("payload", [
    {"counts": {"main": 3, "vegetable": 1, "soup": 1}},
    {"counts": {"main": 0, "vegetable": 0, "soup": 0}},
    {"counts": {"main": True, "vegetable": 1, "soup": 1}}, {"counts": {"main": 1}},
    {"current_plan": {"main:1": 1, "soup:1": 1}}, {"current_plan": {"main:2": 1}},
    {"locked_slots": ["main:1"]}, {"locked_slots": [None]}, {"current_plan": None},
    {"replace_slot": "soup:1"}, {"current_plan": {"main:1": 1}, "locked_slots": ["main:1", "main:1"]},
    {"max_total_minutes": 1441}, {"max_minutes": False}, {"ingredient_ids": [True]},
    {"ingredient_ids": [1], "excluded_ids": [1]}, {"avoid_recipe_ids": {"main": [1]}},
    {"region": "north"}, {"servings": 4}, {"action": None},
])
def test_invalid_payloads_rejected_on_tcp_and_http(meal_web, payload):
    with pytest.raises(ProtocolError):
        validate(payload, REQUEST_ID)
    web, _ = meal_web
    assert web.post("/api/meal-plan/v2", json=payload).status_code == 422


def test_gateway_transport_and_tcp_legacy_compatibility(meal_web, monkeypatch):
    web, _ = meal_web
    assert 'meal-plan-v2.js?v=meal-vegetarian-1' in web.get('/meal-plan').text
    assert 'meal-plan.js?v=meal-web-3' in web.get('/meal-plan/v1').text
    seen, original = [], TCPClient.request
    def spy(client, op, payload, request_id=None):
        seen.append(op)
        return original(client, op, payload, request_id)
    monkeypatch.setattr(TCPClient, "request", spy)
    reply = web.post('/api/meal-plan/v2', json={"counts": {"main": 2, "vegetable": 2, "soup": 2}})
    assert reply.status_code == 200 and reply.json()["data"]["algorithm"] == "meal-plan-v2"
    assert reply.json()["request_id"] == reply.headers["x-request-id"]
    assert seen == ["GENERATE_MEAL_PLAN_V2"]
    legacy = web.post('/api/meal-plan', json={"ingredient_ids": [1, 2, 6, 7], "max_missing": 2, "max_total_minutes": 90}).json()["data"]
    assert legacy["algorithm"] == "meal-plan-v1"
    assert [i["recipe_id"] for i in legacy["plan"]["items"]] == [1, 5, 29]
    assert web.get('/recipes/1?return_to=%2Fmeal-plan%2Fv1').text.count('href="/meal-plan/v1"') >= 2


def test_persistent_connection_v1_recommend_and_search_unchanged(meal_tcp):
    client = TCPClient(port=meal_tcp[1], persistent=True)
    calls = [("GENERATE_MEAL_PLAN", {}), ("SEARCH_RECIPES", {"query": "cá"})] + [
        ("RECOMMEND", {"ingredient_ids": [1, 2], "algorithm": a}) for a in ("baseline", "proposed")]
    try:
        before = [client.request(op, p, REQUEST_ID) for op, p in calls]
        sock = client.sock
        reply = client.request("GENERATE_MEAL_PLAN_V2", {"counts": {"main": 2, "vegetable": 2, "soup": 2}}, REQUEST_ID)
        assert reply["ok"] and len(encode_frame(reply)) <= 65540
        assert [client.request(op, p, REQUEST_ID) for op, p in calls] == before and client.sock is sock
        assert client.request("GENERATE_MEAL_PLAN_V2", {"current_plan": {"main:1": 999}})["error"]["code"] == "INVALID_PAYLOAD"
        assert client.request("PING", {})["ok"]
    finally:
        client.close()


def test_oversized_response_becomes_small_business_failure(meal_tcp, monkeypatch):
    server, port = meal_tcp
    monkeypatch.setattr(server.repository, 'get_recipe', lambda conn, rid: {
        "id": rid, "ingredients": [{"id": i, "name": "ế" * 255, "quantity": "ế" * 255, "is_required": True} for i in range(1, 51)]})
    client = TCPClient(port=port, persistent=True)
    try:
        reply = client.request("GENERATE_MEAL_PLAN_V2", {}, REQUEST_ID)
        assert reply["ok"] and reply["data"]["reason"]["code"] == "RESULT_TOO_LARGE"
        assert reply["data"]["plan"] is None and len(encode_frame(reply)) <= 65540
        assert client.request("PING", {})["ok"]
    finally:
        client.close()


@pytest.mark.parametrize("code,status", [("TIMEOUT", 504), ("UPSTREAM_UNAVAILABLE", 503)])
def test_gateway_reports_upstream_errors(meal_web, monkeypatch, code, status):
    def fail(*a, **kw):
        raise TCPClientError(code)
    monkeypatch.setattr(TCPClient, 'request', fail)
    assert meal_web[0].post('/api/meal-plan/v2', json={}).status_code == status


def test_largest_search_stays_within_transport_budget():
    start = time.monotonic()
    result = run({"counts": {"main": 2, "vegetable": 2, "soup": 2}})
    assert result["plan"] and time.monotonic() - start < 5
