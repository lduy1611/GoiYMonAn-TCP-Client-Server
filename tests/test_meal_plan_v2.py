from itertools import product
import time

import pytest
from source.client.tcp_client import TCPClient, TCPClientError
from source.common.protocol import ProtocolError, encode_frame
from source.server.meal_plan import default_classification, generate_meal_plan, validate_meal_plan
from source.server.meal_plan_v2 import generate, validate
from source.server.meal_preferences import Catalog
from tests.meal_plan_fixtures import REQUEST_ID, full_dataset
from tests.test_meal_plan_integration import meal_tcp
from tests.test_web_meal_plan import meal_web


def run(payload=None, recipes=None):
    return generate(full_dataset()[0] if recipes is None else recipes,
                    validate(payload or {}, REQUEST_ID), default_classification(), REQUEST_ID)


def current(data):
    return {i["slot"]: i["recipe_id"] for i in data["plan"]["items"]}


@pytest.mark.parametrize("payload", [
    {"counts": {"main": 1, "vegetable": 1, "soup": 1}},
    {"counts": {"main": 2, "vegetable": 1, "soup": 1}, "ingredient_ids": [1, 2]},
    {"counts": {"main": 1, "vegetable": 1, "soup": 1}, "excluded_ids": [7]},
    {"counts": {"main": 1, "vegetable": 1, "soup": 1}, "max_total_minutes": 1},
])
def test_compact_search_matches_exhaustive_oracle_on_small_catalog(payload):
    recipes = [recipe for recipe in full_dataset()[0] if recipe["id"] in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}]
    options = validate(payload, REQUEST_ID)
    classification = default_classification()
    compact = generate(recipes, options, classification, REQUEST_ID)
    exhaustive = generate(recipes, options, classification, REQUEST_ID, _force_exhaustive=True)
    assert compact == exhaustive


def test_compact_search_matches_exhaustive_oracle_with_current_plan_and_pins():
    recipes = [recipe for recipe in full_dataset()[0] if recipe["id"] in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}]
    classification = default_classification()
    initial_options = validate({"counts": {"main": 1, "vegetable": 1, "soup": 1}}, REQUEST_ID)
    initial = generate(recipes, initial_options, classification, REQUEST_ID)
    payload = {"counts": {"main": 1, "vegetable": 1, "soup": 1},
               "current_plan": current(initial), "locked_slots": ["main:1"],
               "action": "regenerate"}
    options = validate(payload, REQUEST_ID)
    compact = generate(recipes, options, classification, REQUEST_ID)
    exhaustive = generate(recipes, options, classification, REQUEST_ID, _force_exhaustive=True)
    assert compact == exhaustive


def test_compact_search_falls_back_to_exact_oracle_without_numpy_vector_bitcount(monkeypatch):
    recipes = [recipe for recipe in full_dataset()[0] if recipe["id"] in {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12}]
    options = validate({"counts": {"main": 1, "vegetable": 1, "soup": 1}}, REQUEST_ID)
    expected = generate(recipes, options, default_classification(), REQUEST_ID, _force_exhaustive=True)
    monkeypatch.setattr("source.server.meal_plan_v2._vectorized_exact_best", lambda *args, **kwargs: (None, False))
    assert generate(recipes, options, default_classification(), REQUEST_ID) == expected


@pytest.mark.parametrize("counts", [dict(zip(("main", "vegetable", "soup"), v))
                                  for v in product(range(3), repeat=3) if sum(v)])
def test_all_count_configurations_have_distinct_correct_roles(counts):
    reply = run({"counts": counts})
    plan = reply["plan"]
    assert plan and len(plan["items"]) == sum(counts.values())
    assert len(set(current(reply).values())) == sum(counts.values())
    assert all(default_classification().categories[i["recipe_id"]] == i["slot"].split(":")[0] for i in plan["items"])
    assert {g: sum(i["slot"].startswith(g + ":") for i in plan["items"]) for g in counts} == counts


def test_automatic_six_people_layout_uses_exact_roles_and_distinct_recipes():
    reply = run({"people": 6})
    assert reply["counts"] == {"main": 2, "vegetable": 1, "soup": 1}
    assert reply["plan"] and len(reply["plan"]["items"]) == 4
    assert len({item["recipe_id"] for item in reply["plan"]["items"]}) == 4


@pytest.mark.parametrize("occasion,people,counts", [
    ("guests",1,{"main":3,"vegetable":1,"soup":0}),
    ("guests",3,{"main":3,"vegetable":1,"soup":0}),
    ("guests",4,{"main":3,"vegetable":1,"soup":1}),
    ("guests",5,{"main":3,"vegetable":1,"soup":1}),
    ("guests",6,{"main":4,"vegetable":1,"soup":1}),
    ("guests",8,{"main":4,"vegetable":1,"soup":1}),
    ("guests",12,{"main":4,"vegetable":1,"soup":1}),
    ("drinking",1,{"main":2,"vegetable":1,"soup":0}),
    ("drinking",3,{"main":2,"vegetable":1,"soup":0}),
    ("drinking",4,{"main":3,"vegetable":1,"soup":0}),
    ("drinking",5,{"main":3,"vegetable":1,"soup":0}),
    ("drinking",6,{"main":4,"vegetable":1,"soup":0}),
    ("drinking",8,{"main":4,"vegetable":1,"soup":0}),
    ("drinking",9,{"main":4,"vegetable":2,"soup":0}),
    ("drinking",12,{"main":4,"vegetable":2,"soup":0}),
])
def test_guest_and_drinking_automatic_count_structures(occasion, people, counts):
    options = validate({"people":people,"preferences":{"occasion":occasion}}, REQUEST_ID)
    assert options.counts == counts


def _special_catalog():
    recipes, _ = full_dataset()
    base = default_classification()
    roles = dict(base.categories)
    side_ids = {46,47,48}
    roles.update({rid:"side" for rid in side_ids})
    classification = type(base)("special-layout-fixture", roles)
    guest_ids = frozenset(roles)
    drinking_ids = frozenset(roles)
    veg_ids = {1,2,3,4,5,6,46,47,48}
    assessments = {rid:{"status":"VERIFIED"} for rid in veg_ids}
    metadata = Catalog("special-layout-meta", {}, roles, assessments,
        contexts={"occasion":{"guests":guest_ids,"drinking":drinking_ids}})
    return recipes, classification, metadata, side_ids


@pytest.mark.parametrize("occasion,people", [("guests",2),("guests",4),("guests",6),("guests",8),("guests",12),
                                               ("drinking",2),("drinking",4),("drinking",6),("drinking",8),("drinking",12)])
@pytest.mark.parametrize("diet", [None,"vegetarian"])
def test_guest_drinking_roles_are_exact_unique_and_support_pins_and_swaps(occasion,people,diet):
    recipes, classification, metadata, side_ids = _special_catalog()
    preferences={"occasion":occasion}
    if diet: preferences["diet"]=diet
    options=validate({"people":people,"preferences":preferences},REQUEST_ID)
    result=generate(recipes,options,classification,REQUEST_ID,metadata)
    assert result["plan"], result["reason"]
    slots=current(result)
    assert len(slots)==len(set(slots.values()))==sum(options.counts.values())
    role_map=classification.categories
    if occasion=="guests":
        assert role_map[slots["main:1"]]=="side"
        assert all(role_map[slots[f"main:{i}"]]=="main" for i in range(2,options.counts["main"]+1))
        assert all(role_map[slots[f"vegetable:{i}"]]=="vegetable" for i in range(1,options.counts["vegetable"]+1))
        assert all(role_map[slots[f"soup:{i}"]]=="soup" for i in range(1,options.counts["soup"]+1))
    else:
        assert all(role_map[slots[f"main:{i}"]]=="main" for i in range(1,options.counts["main"]+1))
        assert all(role_map[slots[f"vegetable:{i}"]]=="side" for i in range(1,options.counts["vegetable"]+1))
    if diet:
        assert set(slots.values()) <= set(metadata.vegetarian_ids)
    initial=slots.copy()
    pinned=generate(recipes,validate({"people":people,"preferences":preferences,"current_plan":initial,
        "locked_slots":[next(iter(initial))],"action":"regenerate"},REQUEST_ID),classification,REQUEST_ID,metadata)
    assert pinned["plan"] and current(pinned)[next(iter(initial))]==initial[next(iter(initial))]
    target=next(k for k in initial if k!=next(iter(initial)))
    replaced=generate(recipes,validate({"people":people,"preferences":preferences,"current_plan":initial,
        "replace_slot":target},REQUEST_ID),classification,REQUEST_ID,metadata)
    if replaced["plan"]:
        assert all(current(replaced)[k]==initial[k] for k in initial if k!=target)


def test_special_layout_search_matches_exhaustive_oracle_and_reports_missing_appetizer():
    recipes, classification, metadata, side_ids = _special_catalog()
    options=validate({"people":6,"preferences":{"occasion":"guests"}},REQUEST_ID)
    assert generate(recipes,options,classification,REQUEST_ID,metadata)==generate(
        recipes,options,classification,REQUEST_ID,metadata,_force_exhaustive=True)
    no_side=Catalog("no-appetizer",{},classification.categories,
        contexts={"occasion":{"guests":frozenset(set(classification.categories)-side_ids)}})
    unavailable=generate(recipes,options,classification,REQUEST_ID,no_side)
    assert unavailable["plan"] is None
    assert unavailable["reason"]["code"]=="INSUFFICIENT_GROUP"
    assert "khai vị" in unavailable["reason"]["message"].lower()


def test_large_layout_transition_keeps_exact_ranking_and_can_report_more_than_six_changed_slots():
    recipes, classification, metadata, _side_ids = _special_catalog()
    original = generate(recipes, validate({"people": 12}, REQUEST_ID), classification, REQUEST_ID, metadata)
    current_plan = {item["slot"]: item["recipe_id"] for item in original["plan"]["items"]}
    options = validate({"people": 12, "preferences": {"occasion": "guests"},
                        "current_plan": current_plan}, REQUEST_ID)

    optimized = generate(recipes, options, classification, REQUEST_ID, metadata)
    exhaustive = generate(recipes, options, classification, REQUEST_ID, metadata, _force_exhaustive=True)

    assert optimized == exhaustive
    assert len(optimized["changed_slots"]) <= 12


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


def test_custom_layout_allows_more_than_two_dishes_per_group_without_relaxing_constraints():
    counts = {"main": 3, "vegetable": 2, "soup": 1}
    result = run({"layout_mode": "custom", "people": 4, "counts": counts})
    assert result["plan"] and result["layout_mode"] == "custom"
    assert len(result["plan"]["items"]) == 6
    assert len(set(current(result).values())) == 6
    assert {g: sum(i["slot"].startswith(g + ":") for i in result["plan"]["items"]) for g in counts} == counts
    assert all(default_classification().categories[i["recipe_id"]] == i["slot"].split(":")[0]
               for i in result["plan"]["items"])


def test_custom_layout_rejects_over_six_dishes_and_automatic_policy_remains_fixed():
    with pytest.raises(ProtocolError):
        validate({"layout_mode": "custom", "counts": {"main": 4, "vegetable": 2, "soup": 1}}, REQUEST_ID)
    with pytest.raises(ProtocolError):
        validate({"layout_mode": "automatic", "people": 4,
                  "counts": {"main": 2, "vegetable": 2, "soup": 1}}, REQUEST_ID)
    with pytest.raises(ProtocolError):
        validate({"layout_mode": "custom", "counts": {"main": 2, "vegetable": 2, "soup": 2},
                  "current_plan": {"main:7": 1}}, REQUEST_ID)


def test_custom_pin_conflict_is_reported_and_not_silently_removed():
    old = current(run({"layout_mode": "custom", "people": 4,
                       "counts": {"main": 2, "vegetable": 1, "soup": 1}}))
    conflict = run({"layout_mode": "custom", "people": 4,
                    "counts": {"main": 1, "vegetable": 1, "soup": 1},
                    "current_plan": old, "locked_slots": ["main:2"]})
    assert conflict["plan"] is None
    assert conflict["reason"]["code"] == "PINNED_SLOT_REMOVED"
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
    assert 'meal-plan-v2.js?v=meal-shopping-20261110-3' in web.get('/meal-plan').text
    assert 'meal-plan.js?v=meal-web-4' in web.get('/meal-plan/v1').text
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
    detail = web.get('/recipes/1?return_to=%2Fmeal-plan%2Fv1').text
    assert detail.count('href="/meal-plan/v1"') == 1
    assert 'class="back"' in detail


def test_gateway_and_tcp_accept_custom_multi_dish_group(meal_web):
    web, _ = meal_web
    response = web.post('/api/meal-plan/v2', json={
        "layout_mode": "custom", "people": 4,
        "counts": {"main": 3, "vegetable": 2, "soup": 1},
    })
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["layout_mode"] == "custom"
    assert data["counts"] == {"main": 3, "vegetable": 2, "soup": 1}
    if data["plan"]:
        assert len(data["plan"]["items"]) == 6
        assert len({item["recipe_id"] for item in data["plan"]["items"]}) == 6
    else:
        assert data["reason"]["code"] == "INSUFFICIENT_GROUP"


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


def test_snack_occasion_uses_tagged_side_and_starch_candidates_without_core_role_mislabeling():
    recipes, _ingredients = full_dataset()
    ids = [46, 47, 48, 49, 50]
    roles = dict(default_classification().categories)
    roles.update({46: "side", 47: "starch", 48: "other", 49: "side", 50: "starch"})
    classification = type(default_classification())("test-snack", roles)
    metadata = Catalog("test-snack-meta", {}, roles, contexts={"occasion": {"snack": frozenset(ids)}})
    choice = next(c for c in metadata.capabilities(layout_support=True)["choices"]["occasion"] if c["code"] == "snack")
    assert choice["enabled"] and choice["recipe_count"] == 5
    assert choice["supported_people"] == list(range(1, 9))

    options = validate({"people": 4, "preferences": {"occasion": "snack"}}, REQUEST_ID)
    result = generate(recipes, options, classification, REQUEST_ID, metadata)
    items = result["plan"]["items"]
    assert len(items) == 3 and len({item["recipe_id"] for item in items}) == 3
    assert {item["recipe_id"] for item in items} <= set(ids)

    pinned_id = items[0]["recipe_id"]
    current_plan = {item["slot"]: item["recipe_id"] for item in items}
    pinned = generate(recipes, validate({"people": 4, "preferences": {"occasion": "snack"},
        "current_plan": current_plan, "locked_slots": [items[0]["slot"]], "action": "regenerate"}, REQUEST_ID),
        classification, REQUEST_ID, metadata)
    assert next(item["recipe_id"] for item in pinned["plan"]["items"] if item["slot"] == items[0]["slot"]) == pinned_id
    assert len({item["recipe_id"] for item in pinned["plan"]["items"]}) == 3

    too_slow = generate(recipes, validate({"people": 4, "max_minutes": 1,
        "preferences": {"occasion": "snack"}}, REQUEST_ID), classification, REQUEST_ID, metadata)
    assert too_slow["plan"] is None and too_slow["reason"]["code"] == "INSUFFICIENT_SNACK_CHOICES"


def test_snack_filter_only_supports_people_count_that_available_distinct_candidates_can_fill():
    roles = {46: "starch", 47: "side"}
    metadata = Catalog("test-snack-short", {}, roles,
        contexts={"occasion": {"snack": frozenset(roles)}})
    choice = next(c for c in metadata.capabilities(layout_support=True)["choices"]["occasion"] if c["code"] == "snack")
    assert choice["enabled"] is True and choice["supported_people"] == [1, 2]


def test_snack_overlap_optimization_matches_exhaustive_oracle_on_small_catalog():
    recipes, _details = full_dataset()
    snack_ids = {46, 47, 48, 49, 50}
    roles = dict(default_classification().categories)
    roles.update({rid: "side" for rid in snack_ids})
    classification = type(default_classification())("test-snack-oracle", roles)
    metadata = Catalog("test-snack-oracle-meta", {}, roles,
                       contexts={"occasion": {"snack": frozenset(snack_ids)}})
    options = validate({"people": 6, "preferences": {"occasion": "snack"}}, REQUEST_ID)
    exact = generate(recipes, options, classification, REQUEST_ID, metadata)
    exhaustive = generate(recipes, options, classification, REQUEST_ID, metadata, _force_exhaustive=True)
    assert exact == exhaustive
    current = {item["slot"]: item["recipe_id"] for item in exact["plan"]["items"]}
    cases = (
        {"people": 6, "preferences": {"occasion": "snack"}, "current_plan": current,
         "locked_slots": ["main:1"], "action": "regenerate"},
        {"people": 6, "preferences": {"occasion": "snack"}, "current_plan": current,
         "locked_slots": ["main:1"], "replace_slot": "vegetable:1"},
    )
    for body in cases:
        options = validate(body, REQUEST_ID)
        assert generate(recipes, options, classification, REQUEST_ID, metadata) == generate(
            recipes, options, classification, REQUEST_ID, metadata, _force_exhaustive=True)


def test_twelve_person_snack_search_avoids_role_permutation_explosion():
    recipes, _details = full_dataset()
    snack_ids = set(range(32, 51))
    roles = dict(default_classification().categories)
    roles.update({rid: "side" for rid in snack_ids})
    classification = type(default_classification())("test-snack-large", roles)
    metadata = Catalog("test-snack-large-meta", {}, roles,
                       contexts={"occasion": {"snack": frozenset(snack_ids)}})
    options = validate({"people": 12, "preferences": {"occasion": "snack"}}, REQUEST_ID)
    start = time.monotonic()
    result = generate(recipes, options, classification, REQUEST_ID, metadata)
    elapsed = time.monotonic() - start
    assert result["plan"] and len(result["plan"]["items"]) == 6
    assert len({item["recipe_id"] for item in result["plan"]["items"]}) == 6
    assert {item["recipe_id"] for item in result["plan"]["items"]} <= snack_ids
    assert elapsed < 5
    current = {item["slot"]: item["recipe_id"] for item in result["plan"]["items"]}
    pinned_options = validate({"people": 12, "preferences": {"occasion": "snack"},
                               "current_plan": current, "locked_slots": ["main:1"],
                               "action": "regenerate"}, REQUEST_ID)
    start = time.monotonic()
    pinned_result = generate(recipes, pinned_options, classification, REQUEST_ID, metadata)
    pinned_elapsed = time.monotonic() - start
    assert pinned_result["plan"] and len(pinned_result["plan"]["items"]) == 6
    assert len({item["recipe_id"] for item in pinned_result["plan"]["items"]}) == 6
    assert next(item["recipe_id"] for item in pinned_result["plan"]["items"] if item["slot"] == "main:1") == current["main:1"]
    assert pinned_elapsed < 5
