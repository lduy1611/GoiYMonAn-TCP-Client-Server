"""Portion arithmetic over explicitly synthetic, simulated-review fixtures only."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

import pytest

from source.common.protocol import ProtocolError
from source.server.meal_plan_calculation import calculate, validate, Catalog, Review, Unit
from source.web.meal_plan_calculation_contract import CalculationData
from tests.calculation_fixtures import fixture_catalog, test_line, TEST_REVIEW


def run(catalog=None, recipe_ids=(1, 5), people=4):
    data = calculate(validate({"recipe_ids": list(recipe_ids), "people": people}),
                     fixture_catalog(recipe_ids) if catalog is None else catalog)
    CalculationData.model_validate({"dataset_version": "TEST_ONLY", **data})
    return data


def change_recipe(catalog, key=1, **changes):
    return replace(catalog, revisions={**catalog.revisions,
        key: replace(catalog.revisions[key], **changes)})


def change_line(catalog, **changes):
    revision = catalog.revisions[1]
    return change_recipe(catalog, lines=(replace(revision.lines[0], **changes), *revision.lines[1:]))


def codes(data, index=0):
    return {r["code"] for r in data["recipes"][index]["reasons"]}


def test_exact_range_count_and_shared_ingredient_totals():
    data = run()
    assert data["status"] == "COMPLETE" and data["totals_complete"]
    assert data["recipe_ids"] == [1, 5]
    assert [(r["base_servings"], r["target_servings"]) for r in data["recipes"]] == [("2", "4"), ("4", "4")]
    vegetable, liquid, countable = data["known_ingredients"]
    assert vegetable["quantity_value"] == "250" and vegetable["unit"] == "g"
    assert [u["quantity_value"] for u in vegetable["uses"]] == ["200", "50"]
    assert liquid["quantity_value"] is None and (liquid["quantity_min"], liquid["quantity_max"]) == ("400", "600")
    assert countable["quantity_value"] == "1" and countable["unit"] == "piece"


def test_base_servings_identity_recalculation_and_no_input_or_pin_mutation():
    state = {"recipe_ids": [5, 1], "locked_slots": ["main:1"]}
    catalog = fixture_catalog((5, 1))
    before_catalog, before_state = deepcopy(catalog), deepcopy(state)
    first = run(catalog, state["recipe_ids"], 2)
    assert first["recipes"][0]["lines"][0]["quantity_value"] == "100"
    second = run(catalog, state["recipe_ids"], 4)
    assert second["recipes"][0]["lines"][0]["quantity_value"] == "200"
    assert run(catalog, state["recipe_ids"], 2) == first
    assert catalog == before_catalog and state == before_state


def test_same_ingredient_in_multiple_stages_counts_each_use_once():
    catalog = fixture_catalog((1,))
    catalog = change_recipe(catalog, lines=(test_line(1, amount_min="10"), test_line(2, amount_min="20")))
    data = run(catalog, (1,), 2)
    assert len(data["known_ingredients"]) == 1
    assert data["known_ingredients"][0]["quantity_value"] == "30"
    assert [u["line_id"] for u in data["known_ingredients"][0]["uses"]] == [1, 2]


@pytest.mark.parametrize("field,value", [
    ("unit", "kg"), ("ingredient_form", "test_cooked"),
    ("measurement_basis", "gross"), ("purpose", "cooking_medium"),
])
def test_incompatible_shared_ingredient_uses_remain_separate(field, value):
    catalog = fixture_catalog()
    revision = catalog.revisions[5]
    catalog = change_recipe(catalog, 5, lines=(replace(revision.lines[0], **{field: value}), revision.lines[1]))
    data = run(catalog)
    groups = [g for g in data["known_ingredients"] if g["ingredient_id"] == 1001]
    assert len(groups) == 2 and [g["quantity_value"] for g in groups] == ["200", "50"]


@pytest.mark.parametrize("review", [Review(), Review("REJECTED", "test", "test"),
    Review("APPROVED"), Review("APPROVED", "test", None)])
def test_revision_status_alone_or_unreviewed_dossier_never_enables_math(review):
    data = run(change_recipe(fixture_catalog(), review=review))
    assert data["status"] == "INCOMPLETE" and not data["totals_complete"]
    assert codes(data) == {"REVISION_NOT_APPROVED"}
    assert data["recipes"][0]["revision_id"] is None and data["recipes"][0]["lines"] == []


@pytest.mark.parametrize("changes,reason", [
    ({"base_servings": None}, "INVALID_BASE_SERVINGS"),
    ({"base_servings": "0"}, "INVALID_BASE_SERVINGS"),
    ({"servings_review": Review()}, "SERVINGS_NOT_APPROVED"),
    ({"serving_basis": "unknown"}, "SERVINGS_NOT_APPROVED"),
    ({"content_complete": False}, "INGREDIENTS_INCOMPLETE"),
    ({"lines": ()}, "INVALID_REVISION"),
    ({"recipe_id": 999}, "INVALID_REVISION"),
    ({"lines": (test_line(), test_line())}, "INVALID_REVISION"),
])
def test_missing_recipe_basis_has_specific_reason(changes, reason):
    data = run(change_recipe(fixture_catalog(), **changes))
    assert reason in codes(data)
    assert data["recipes"][0]["lines"] == []


@pytest.mark.parametrize("changes,reason", [
    ({"review": Review()}, "LINE_NOT_APPROVED"),
    ({"ingredient_form": None}, "INVALID_INGREDIENT"),
    ({"ingredient_id": None}, "INVALID_INGREDIENT"),
    ({"measurement_basis": None}, "INVALID_INGREDIENT"),
    ({"name": " " * 500 + "test"}, "INVALID_INGREDIENT"),
    ({"amount_kind": "to_taste", "amount_min": None}, "UNKNOWN_QUANTITY"),
    ({"amount_kind": "unknown", "amount_min": None}, "UNKNOWN_QUANTITY"),
    ({"unit": "spoon_without_definition"}, "UNIT_NOT_APPROVED"),
    ({"scaling_review": Review()}, "SCALING_NOT_APPROVED"),
    ({"scaling_mode": "unimplemented"}, "UNSUPPORTED_SCALING"),
])
def test_partial_results_never_turn_missing_amounts_into_zero(changes, reason):
    data = run(change_line(fixture_catalog(), **changes))
    assert data["status"] == "INCOMPLETE" and not data["totals_complete"]
    assert data["recipes"][0]["reasons"][0]["line_id"] == 1
    assert codes(data) == {reason}
    # Only the other recipe's known 50 g is counted, explicitly under partial totals.
    vegetable = next(g for g in data["known_ingredients"] if g["ingredient_id"] == 1001)
    assert vegetable["quantity_value"] == "50" and len(vegetable["uses"]) == 1


@pytest.mark.parametrize("amount", [None, "", "0", "-1", "NaN", "Infinity", "1e9", "1/2", "9" * 1000,
    "0.0000001", True, 3.0, Decimal("NaN"), Decimal("1E+999999"), Decimal("1E-999999")])
def test_invalid_server_amount_is_incomplete(amount):
    assert "INVALID_QUANTITY" in codes(run(change_line(fixture_catalog(), amount_min=amount)))


@pytest.mark.parametrize("changes", [
    {"amount_kind": "range", "amount_min": "3", "amount_max": "2"},
    {"amount_kind": "range", "amount_max": None}, {"amount_max": "101"},
])
def test_inconsistent_ranges_rejected(changes):
    assert "INVALID_QUANTITY" in codes(run(change_line(fixture_catalog(), **changes)))


def test_approved_fixed_quantity_does_not_scale_with_people():
    data = run(change_line(fixture_catalog(), scaling_mode="fixed"), people=100)
    assert data["recipes"][0]["lines"][0]["quantity_value"] == "100"


@pytest.mark.parametrize("bad_unit", [Unit("g", "mass", "test", Review()),
    Unit("g", "mass", "", TEST_REVIEW), Unit("other", "mass", "test", TEST_REVIEW)])
def test_unit_approval_and_definition_required(bad_unit):
    catalog = fixture_catalog()
    assert "UNIT_NOT_APPROVED" in codes(run(replace(catalog, units={**catalog.units, "g": bad_unit})))


def test_portion_policy_required_and_bound_to_exact_selection_and_revisions():
    catalog = fixture_catalog()
    assert "PORTION_POLICY_UNAVAILABLE" in codes(run(replace(catalog, portion_policy=None)))
    policy = catalog.portion_policy
    assert "PORTION_POLICY_UNAVAILABLE" in codes(run(replace(catalog, portion_policy=replace(policy, review=Review()))))
    assert "PORTION_POLICY_UNAVAILABLE" in codes(run(catalog, (1,), 4))
    allocation = policy.allocations[1]
    for field, value, reason in [("revision_id", 999, "PORTION_POLICY_MISMATCH"),
        ("serving_basis", "adult_equivalent", "PORTION_POLICY_MISMATCH"),
        ("servings_per_person", "0", "INVALID_PORTION_ALLOCATION")]:
        changed = replace(policy, allocations={**policy.allocations, 1: replace(allocation, **{field: value})})
        assert reason in codes(run(replace(catalog, portion_policy=changed)))


def test_explicit_approved_allocation_can_reduce_one_dish_without_guessing():
    catalog = fixture_catalog()
    policy = catalog.portion_policy
    policy = replace(policy, allocations={**policy.allocations,
        1: replace(policy.allocations[1], servings_per_person="0.5")})
    data = run(replace(catalog, portion_policy=policy))
    assert data["recipes"][0]["target_servings"] == "2"
    assert data["recipes"][0]["lines"][0]["quantity_value"] == "100"


def test_fractional_results_bound_outward_and_aggregate_before_rounding():
    catalog = fixture_catalog((1, 5, 6))
    for recipe_id in (1, 5, 6):
        catalog = change_recipe(catalog, recipe_id, base_servings=Decimal("3"),
                                lines=(test_line(amount_min=Decimal("1")),))
    data = run(catalog, (1, 5, 6), 1)
    line = data["recipes"][0]["lines"][0]
    assert line["quantity_value"] is None and line["precision"] == "outward_6dp"
    assert Fraction(line["quantity_min"]) <= Fraction(1, 3) <= Fraction(line["quantity_max"])
    assert data["known_ingredients"][0]["quantity_value"] == "1"
    assert data["known_ingredients"][0]["precision"] == "exact"


def test_production_unavailable_and_missing_revision_are_incomplete():
    for catalog, reason in [(Catalog(available=False), "APPROVED_DATA_UNAVAILABLE"),
                            (Catalog(available="yes"), "APPROVED_DATA_UNAVAILABLE"),
                            (Catalog(), "REVISION_NOT_APPROVED")]:
        data = run(catalog)
        assert data["known_ingredients"] == [] and codes(data) == {reason}
        assert data["status"] == "INCOMPLETE" and not data["totals_complete"]


INVALID_PAYLOADS = [
    {}, {"recipe_ids": [], "people": 4}, {"recipe_ids": [1] * 7, "people": 4},
    {"recipe_ids": [1, 1], "people": 4}, {"recipe_ids": [True], "people": 4},
    {"recipe_ids": ["1"], "people": 4}, {"recipe_ids": [0], "people": 4},
    {"recipe_ids": [4294967296], "people": 4}, {"recipe_ids": [1], "people": True},
    {"recipe_ids": [1], "people": "4"}, {"recipe_ids": [1], "people": 4.0},
    {"recipe_ids": [1], "people": 0}, {"recipe_ids": [1], "people": 101},
    {"recipe_ids": [1], "people": -1}, {"recipe_ids": [1], "people": None},
    {"recipe_ids": None, "people": 4}, {"recipe_ids": "1", "people": 4},
    {"recipe_ids": [1], "people": 4, "revision": {"status": "APPROVED"}},
    {"recipe_ids": [1], "people": 4, "base_servings": 2},
    {"recipe_ids": [1], "people": 4, "locked_slots": []},
]


@pytest.mark.parametrize("payload", INVALID_PAYLOADS)
def test_tcp_contract_rejects_coercion_duplicates_and_client_approval_data(payload):
    with pytest.raises(ProtocolError) as exc:
        validate(payload, "test-id")
    assert exc.value.code == "INVALID_PAYLOAD" and exc.value.request_id == "test-id"
