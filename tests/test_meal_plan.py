from __future__ import annotations

from collections import Counter
import json

import pytest

from source.common.protocol import ProtocolError, encode_body, encode_frame, success_response
from source.server.meal_plan import (ALGORITHM, CATEGORY_COUNTS, CATEGORY_PATH, Classification, SLOTS,
    build_shopping_lists, default_classification, generate_meal_plan, load_classification, validate_meal_plan)
from tests.meal_plan_fixtures import REQUEST_ID, full_dataset, sql_rows


def test_classification_matches_all_50_sql_recipes_and_approved_groups():
    catalog = json.loads(CATEGORY_PATH.read_text(encoding="utf-8"))
    rows = catalog["recipes"]
    assert len(rows) == 50 and len({row["recipe_id"] for row in rows}) == 50
    assert {row["recipe_id"]: row["title"] for row in rows} == {row[0]: row[1] for row in sql_rows("recipes")}
    categories = default_classification()
    assert categories.version == "meal-categories-v1"
    assert Counter(categories.categories.values()) == CATEGORY_COUNTS
    expected = {
        "main": {1,2,3,4,7,10,17,26,27,33,34,35,36,37,38,39,40,41,42,43,44,46,49},
        "vegetable": {5,9,45,47}, "soup": {6,28,29,30,31,32},
        "starch": {8,11,12,13,14,15,18,19,20,21,22,23,24,25,50}, "other": {16,48},
    }
    assert {group: {rid for rid, value in categories.categories.items() if value == group}
            for group in CATEGORY_COUNTS} == expected


@pytest.mark.parametrize("change", ["duplicate", "missing", "unknown_id", "wrong_category", "bad_type", "empty_version"])
def test_invalid_classification_is_rejected(tmp_path, change):
    catalog = json.loads(CATEGORY_PATH.read_text(encoding="utf-8"))
    if change == "duplicate":
        catalog["recipes"].append(catalog["recipes"][0])
    elif change == "missing":
        catalog["recipes"].pop()
    elif change == "unknown_id":
        catalog["recipes"][0]["recipe_id"] = 999
    elif change == "wrong_category":
        catalog["recipes"][0]["category"] = "vegetable"
    elif change == "bad_type":
        catalog["recipes"][0]["recipe_id"] = True
    else:
        catalog["classification_version"] = ""
    path = tmp_path / "categories.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError):
        load_classification(path)


def test_duplicate_json_keys_in_classification_are_rejected(tmp_path):
    path = tmp_path / "categories.json"
    path.write_text('{"classification_version":"one","classification_version":"two","recipes":[]}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_classification(path)


@pytest.mark.parametrize("payload", [
    None, [], {"unknown": 1}, {"algorithm": "baseline"}, {"ingredient_ids": None},
    {"ingredient_ids": [True]}, {"ingredient_ids": ["1"]}, {"ingredient_ids": [0]},
    {"ingredient_ids": [1.0]}, {"ingredient_ids": [1] * 31}, {"excluded_ids": {}},
    {"excluded_ids": [False]}, {"excluded_ids": [-1]}, {"excluded_ids": [1] * 31},
    {"ingredient_ids": [1], "excluded_ids": [1]},
    {"max_minutes": 0}, {"max_minutes": 241}, {"max_minutes": True}, {"max_minutes": "30"},
    {"max_total_minutes": 0}, {"max_total_minutes": 721}, {"max_total_minutes": 2.5},
    {"max_total_minutes": False}, {"max_missing": -1}, {"max_missing": 51},
    {"max_missing": True}, {"max_missing": "2"}, {"current_plan": []},
    {"current_plan": {"main": 1}},
    {"current_plan": {"main": 1, "vegetable": 5, "soup": True}},
    {"current_plan": {"main": 1, "vegetable": 5, "soup": 1}},
    {"locked_slots": ["main"]}, {"locked_slots": "main"}, {"locked_slots": [True]},
    {"current_plan": {"main": 1, "vegetable": 5, "soup": 6}, "locked_slots": ["main", "main"]},
    {"current_plan": {"main": 1, "vegetable": 5, "soup": 6}, "locked_slots": ["main", "vegetable", "soup"]},
    {"current_plan": {"main": 1, "vegetable": 5, "soup": 6}, "locked_slots": ["dessert"]},
])
def test_strict_payload_validation(payload):
    with pytest.raises(ProtocolError) as error:
        validate_meal_plan(payload, REQUEST_ID)
    assert error.value.code == "INVALID_PAYLOAD" and error.value.request_id == REQUEST_ID


def generate(payload, recipes=None, classification=None):
    if recipes is None:
        recipes, _ = full_dataset()
    return generate_meal_plan(recipes, validate_meal_plan(payload, REQUEST_ID),
                              classification or default_classification(), REQUEST_ID)


def ids(result):
    return tuple(item["recipe_id"] for item in result["plan"]["items"])


def test_empty_selection_and_default_missing_limit_are_supported():
    options = validate_meal_plan({}, REQUEST_ID)
    assert not options.selected and options.max_missing is None
    result = generate({})
    assert result["plan"] and result["algorithm"] == ALGORITHM
    assert result["changed_slots"] == []
    assert not result["plan"]["matched_ids"]
    assert result["plan"]["missing_count"] == len(result["plan"]["required_ids"])
    assert "score" not in result["plan"]
    assert [item["slot"] for item in result["plan"]["items"]] == list(SLOTS)
    assert len(set(ids(result))) == 3


def test_full_dataset_missing_and_time_limits_and_stable_order():
    payload = {"ingredient_ids": [1,2,6,7], "max_minutes": 60, "max_total_minutes": 90, "max_missing": 2}
    result = generate(payload)
    assert ids(result) == (1,5,29)
    assert result["plan"]["missing_ids"] == [39,44]
    assert result["plan"]["total_minutes"] == 82
    assert result["plan"]["time_basis"] == "sum_of_recipe_minutes"
    recipes, _ = full_dataset()
    assert generate(payload, reversed(recipes)) == result
    assert generate({**payload, "ingredient_ids": [1,2,6,7,1]}) == result
    faster = generate({**payload, "max_total_minutes":81})
    assert ids(faster) == (3,5,29) and faster["plan"]["total_minutes"] == 77
    assert generate({**payload, "max_minutes":54})["plan"] is None
    for filters in ({"max_minutes": 1}, {"max_total_minutes": 1}, {"max_missing": 0}):
        empty = generate(filters)
        assert empty["plan"] is None and empty["reason"]["message"]
        assert empty["warnings"] == ["NO_COMPLETE_MEAL_PLAN"]


def test_zero_missing_with_all_required_ingredients_available():
    result = generate({"ingredient_ids":[1,2,6,7,39,44], "max_missing":0})
    assert ids(result) == (1,5,29) and result["plan"]["missing_count"] == 0
    _, details = full_dataset()
    shopping = build_shopping_lists([r for r in details if r["id"] in ids(result)], frozenset({1,2,6,7,39,44}))
    assert shopping["shopping_list"] == []
    assert shopping["optional_missing_ids"] == [8,24]


def test_exclusions_include_optional_ingredients():
    recipes, _ = full_dataset()
    result = generate({"excluded_ids": [7]}, recipes)
    by_id = {recipe["id"]: recipe for recipe in recipes}
    assert result["plan"]
    assert all(7 not in by_id[rid]["all_ids"] for rid in ids(result))
    # Garlic is optional for the locked tofu main, but must still disqualify it.
    locked = generate({"current_plan": {"main": 4, "vegetable": 9, "soup": 6},
                       "locked_slots": ["main"], "excluded_ids": [7]})
    assert locked["plan"] is None and locked["reason"]["code"] == "LOCKED_RECIPE_INCOMPATIBLE"


@pytest.mark.parametrize("filters", [{"excluded_ids": [7]}, {"max_minutes": 10}])
def test_locked_dishes_never_change_to_escape_filters(filters):
    result = generate({"current_plan": {"main": 1, "vegetable": 5, "soup": 29},
                       "locked_slots": ["vegetable", "soup"], **filters})
    assert result["plan"] is None and result["changed_slots"] == []
    assert result["reason"]["code"] == "LOCKED_RECIPE_INCOMPATIBLE"


@pytest.mark.parametrize("current", [
    {"main": 999, "vegetable": 5, "soup": 6},
    {"main": 8, "vegetable": 5, "soup": 6},
    {"main": 5, "vegetable": 1, "soup": 6},
])
def test_unknown_or_wrong_category_current_recipe_is_invalid(current):
    with pytest.raises(ProtocolError) as error:
        generate({"current_plan": current})
    assert error.value.code == "INVALID_PAYLOAD" and error.value.request_id == REQUEST_ID


def test_replacement_changes_only_the_unlocked_dish():
    result = generate({"current_plan": {"main": 1, "vegetable": 5, "soup": 29},
                       "locked_slots": ["main", "vegetable"]})
    assert ids(result)[:2] == (1,5) and ids(result)[2] != 29
    assert result["changed_slots"] == ["soup"]


def test_whole_plan_prefers_changing_all_three_slots():
    current = {"main": 1, "vegetable": 5, "soup": 29}
    result = generate({"current_plan": current})
    assert result["changed_slots"] == list(SLOTS)
    assert all(item["recipe_id"] != current[item["slot"]] for item in result["plan"]["items"])


def test_whole_plan_falls_back_to_one_change_and_never_claims_noop_success():
    recipes, _ = full_dataset()
    # Only main can change in this reduced, valid catalog.
    recipes = [recipe for recipe in recipes if recipe["id"] in {1,3,5,6}]
    current = {"main": 1, "vegetable": 5, "soup": 6}
    result = generate({"current_plan": current}, recipes)
    assert ids(result) == (3,5,6) and result["changed_slots"] == ["main"]
    assert result["warnings"] == ["PARTIAL_REGENERATION"]
    empty = generate({"current_plan": current}, [recipe for recipe in recipes if recipe["id"] != 3])
    assert empty["plan"] is None and empty["changed_slots"] == []
    assert empty["reason"]["code"] == "NO_ALTERNATIVE"
    assert generate({"current_plan": current, "locked_slots": ["main", "vegetable"]}, recipes)["plan"] is None


def test_whole_plan_can_change_two_slots_without_relaxing_exclusions():
    recipes, _ = full_dataset()
    recipes = [r for r in recipes if r["id"] in {1,3,5,9,6,28}]
    result = generate({"current_plan":{"main":1,"vegetable":5,"soup":6}, "excluded_ids":[11]}, recipes)
    assert ids(result) == (3,5,28)
    assert result["changed_slots"] == ["main","soup"]
    assert result["warnings"] == ["PARTIAL_REGENERATION"]


def test_unique_missing_shared_ingredients_and_tie_break_preferences():
    classification = Classification("test", {1:"main", 2:"main", 3:"vegetable", 4:"soup"})
    def recipe(rid, required, minutes=10):
        return {"id":rid, "title":f"Món {rid}", "minutes":minutes,
                "required_ids":set(required), "all_ids":set(required)}
    recipes = [recipe(1,[1,2],15), recipe(2,[2],5), recipe(3,[2]), recipe(4,[2])]
    result = generate({"ingredient_ids": [1], "max_missing": 1}, recipes, classification)
    assert ids(result) == (1,3,4)  # More available ingredients beats shorter time.
    assert result["plan"]["missing_ids"] == [2] and result["plan"]["missing_count"] == 1
    assert sum(item["missing_count"] for item in result["plan"]["items"]) == 3
    # Same union missing/matched: fewer per-dish missing outranks time, then ID breaks ties.
    recipes = [recipe(1,[1,2]), recipe(2,[1],20), recipe(3,[2]), recipe(4,[2])]
    assert ids(generate({"ingredient_ids":[1]}, recipes, classification)) == (2,3,4)


def test_missing_category_has_clear_reason():
    recipes, _ = full_dataset()
    result = generate({}, [r for r in recipes if default_classification().categories[r["id"]] != "vegetable"])
    assert result["plan"] is None and result["reason"]["slots"] == ["vegetable"]


def test_shopping_groups_shared_required_and_optional_without_converting_quantities():
    def ingredient(i, quantity, required):
        return {"id":i, "name":f"Nguyên liệu {i}", "quantity":quantity, "is_required":required}
    details = [
        {"id":1, "ingredients":[ingredient(1,"1 củ",False), ingredient(2,"200 g",False), ingredient(3,"2 quả",True)]},
        {"id":2, "ingredients":[ingredient(1,"50 g",True), ingredient(2,"1 tép",False)]},
        {"id":3, "ingredients":[ingredient(1,"2 phần",True)]},
    ]
    result = build_shopping_lists(details, frozenset({3}))
    assert [item["ingredient_id"] for item in result["shopping_list"]] == [1]
    assert [item["ingredient_id"] for item in result["optional_shopping_list"]] == [2]
    assert result["optional_missing_ids"] == [2]
    assert [use["quantity"] for use in result["shopping_list"][0]["uses"]] == ["1 củ","50 g","2 phần"]
    assert [use["is_required"] for use in result["shopping_list"][0]["uses"]] == [False,True,True]
    assert build_shopping_lists(details, frozenset({1,2,3}))["shopping_list"] == []


def test_actual_dataset_shopping_and_frame_limits():
    result = generate({"ingredient_ids":[1,2,6,7], "max_missing":2, "max_total_minutes":90})
    _, details = full_dataset()
    selected_details = [r for r in details if r["id"] in ids(result)]
    result["plan"].update(build_shopping_lists(selected_details, frozenset({1,2,6,7})))
    assert [(i["ingredient_id"], i["uses"][0]["quantity"]) for i in result["plan"]["shopping_list"]] == [(39,"300 g"),(44,"400 g")]
    assert result["plan"]["optional_missing_ids"] == [8,24]
    response = success_response(REQUEST_ID, {"dataset_version":"test", **result})
    frame = encode_frame(response)
    assert int.from_bytes(frame[:4], "big") == len(frame) - 4 <= 65536
    assert json.loads(frame[4:].decode("utf-8")) == response
    envelope = {"version":1,"request_id":REQUEST_ID,"op":"GENERATE_MEAL_PLAN","payload":{}}
    # Exact existing byte limit, not a new or increased protocol limit.
    padding = 65536 - len(encode_body({**envelope, "padding":""}))
    assert len(encode_frame({**envelope, "padding":"x" * padding})) == 65540
    with pytest.raises(ProtocolError, match="65536"):
        encode_frame({**envelope, "padding":"x" * (padding + 1)})
