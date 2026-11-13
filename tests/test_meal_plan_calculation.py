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


def test_v3_trusted_catalog_allocates_one_shared_main_food_budget():
    catalog = fixture_catalog((1, 5))
    first = catalog.revisions[1]
    second = catalog.revisions[5]
    catalog = replace(catalog, trust_admin_catalog=True, revisions={
        1: replace(first, base_servings="4", role="main", data_status="verified", lines=(replace(first.lines[0], amount_min="400", measurement_basis="gross"), replace(first.lines[1], purpose="seasoning"))),
        5: replace(second, base_servings="4", role="main", data_status="estimated", lines=(replace(second.lines[0], amount_min="200", measurement_basis="gross"), replace(second.lines[1], purpose="seasoning"))),
    })
    for adults, children, occasion, expected in [(4, 0, "daily", "600"), (4, 1, "daily", "690"),
                                                  (4, 0, "guests", "720"), (4, 0, "drinking", "880")]:
        data = calculate(validate({"recipe_ids": [1, 5], "people": adults+children,
                                   "adults": adults, "children": children, "occasion": occasion}), catalog)
        total = sum(Decimal(item["quantity_value"]) for item in data["known_ingredients"]
                    if item["ingredient_id"] == 1001)
        if occasion == "daily":
            assessment = next(group for group in data["service_assessment"]["groups"] if group["role"] == "main")
            assert assessment["source_capacity"] == "8"
            assert assessment["requested_servings"] == ("4" if children == 0 else "4.6")
            assert assessment["adjustment_factor"] == "1"
            assert assessment["status"] == "estimated"
            assert total == Decimal("600")
        else:
            main = next(group for group in data["portion_groups"] if group["role"] == "main")
            assert main["target"] == expected
            assert total == Decimal(expected)
        CalculationData.model_validate({"dataset_version": "TEST_ONLY", **data})


def test_v3_daily_four_main_dishes_keep_original_quantities():
    recipe_ids = (1, 5, 6, 7)
    catalog = fixture_catalog(recipe_ids)
    revisions = {}
    for recipe_id, amount in zip(recipe_ids, (100, 200, 300, 400)):
        revision = catalog.revisions[recipe_id]
        driver = replace(revision.lines[0], amount_kind="exact", amount_min=str(amount),
                         amount_max=str(amount), unit="g", measurement_basis="gross",
                         purpose="main", requirement="required", scaling_mode="linear")
        revisions[recipe_id] = replace(revision, role="main", data_status="verified", base_servings="4",
                                       lines=(driver,))
    catalog = replace(catalog, trust_admin_catalog=True, portion_policy=None, revisions=revisions)

    for people in (2, 4, 6, 9, 11, 12):
        data = calculate(validate({"recipe_ids": list(recipe_ids), "people": people,
                                   "adults": people, "children": 0}), catalog)
        main = next(group for group in data["service_assessment"]["groups"] if group["role"] == "main")
        main_ingredient = next(item for item in data["known_ingredients"] if item["ingredient_id"] == 1001)

        assert main["status"] == "verified"
        assert main["source_capacity"] == "16"
        assert main["adjustment_factor"] == "1"
        assert main_ingredient["quantity_value"] == "1000"
        assert len(main_ingredient["uses"]) == 4
        CalculationData.model_validate({"dataset_version": "TEST_ONLY", **data})


@pytest.mark.parametrize("field,value", [("amount_kind", "range"), ("unit", None),
                                          ("measurement_basis", "prepared"), ("scaling_mode", "fixed")])
def test_v3_group_allocation_stays_incomplete_without_compatible_driver(field, value):
    catalog = fixture_catalog((1,))
    revision = catalog.revisions[1]
    line = replace(revision.lines[0], **{"measurement_basis": "gross", field: value})
    catalog = replace(catalog, trust_admin_catalog=True,
                      revisions={1: replace(revision, role="main", lines=(line, revision.lines[1]))})
    data = calculate(validate({"recipe_ids": [1], "people": 4}), catalog)
    assert data["status"] == "INCOMPLETE"
    assert "MEAL_ALLOCATION_UNAVAILABLE" in codes(data)
    assert data["recipes"][0]["target_servings"] == data["recipes"][0]["base_servings"]


def test_v3_daily_original_amounts_stay_fixed_from_two_to_twelve_people():
    catalog = fixture_catalog((1,))
    revision = catalog.revisions[1]
    catalog = replace(catalog, trust_admin_catalog=True, revisions={1: replace(revision,
        role="main", data_status="verified", base_servings="4", lines=(replace(revision.lines[0], amount_min="400", measurement_basis="gross"),
                                                replace(revision.lines[1], purpose="seasoning")))})
    for people in range(2, 13):
        data = calculate(validate({"recipe_ids": [1], "people": people}), catalog)
        assessment = next(group for group in data["service_assessment"]["groups"] if group["role"] == "main")
        assert assessment["status"] == "verified" and assessment["requested_servings"] == str(people)
        assert assessment["source_capacity"] == "4"
        assert data["known_ingredients"][0]["quantity_value"] == "400"
        assert (data["status"] == "COMPLETE") == (people <= 2)


def test_v3_daily_unreviewed_source_servings_remain_unknown_and_unscaled():
    catalog = fixture_catalog((1,))
    revision = catalog.revisions[1]
    catalog = replace(catalog, trust_admin_catalog=True, revisions={1: replace(revision,
        role="main", data_status="needs_review", base_servings="4")})
    data = calculate(validate({"recipe_ids": [1], "people": 8}), catalog)
    assessment = data["service_assessment"]["groups"][0]
    assert assessment["status"] == "unknown" and assessment["source_capacity"] is None
    assert assessment["recipes"][0]["source_servings"] is None
    assert data["status"] == "INCOMPLETE"
    assert data["known_ingredients"][0]["quantity_value"] == "100"
    CalculationData.model_validate({"dataset_version": "TEST_ONLY", **data})


def test_v3_soup_uses_only_verified_broth_volume_as_group_driver():
    catalog = fixture_catalog((1,))
    revision = catalog.revisions[1]
    lines = (replace(revision.lines[0], amount_min="1", unit="l", measurement_basis="gross"),
             replace(revision.lines[1], purpose="seasoning"))
    catalog = replace(catalog, trust_admin_catalog=True, revisions={1: replace(revision,
        role="soup", data_status="verified", base_servings="4", lines=lines)},
        units={**catalog.units, "l": Unit("l", "volume", "TEST_ONLY litre")})
    data = calculate(validate({"recipe_ids": [1], "people": 4}), catalog)
    soup = next(group for group in data["service_assessment"]["groups"] if group["role"] == "soup")
    assert soup["status"] == "verified" and soup["source_capacity"] == "4"
    assert soup["adjustment_factor"] == "1"
    assert CalculationData.model_validate({"dataset_version": "TEST_ONLY", **data})


def test_v3_public_ingredient_ids_above_uint32_are_calculated_and_validated():
    catalog = fixture_catalog((1,))
    high_id = 4294967297
    line = replace(catalog.revisions[1].lines[0], ingredient_id=high_id)
    catalog = change_recipe(catalog, lines=(line,))
    data = run(catalog, (1,), 4)
    assert data["status"] == "COMPLETE"
    assert data["recipes"][0]["lines"][0]["ingredient_id"] == high_id
    assert data["known_ingredients"][0]["ingredient_id"] == high_id


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


@pytest.mark.parametrize("requirement", ["required", "optional"])
def test_grouped_uses_keep_requirement_for_frontend_and_provenance(requirement):
    catalog = fixture_catalog((1,))
    catalog = change_recipe(catalog, lines=(replace(catalog.revisions[1].lines[0], requirement=requirement),))
    data = run(catalog, (1,), 4)
    assert data["known_ingredients"][0]["requirement"] == requirement
    assert data["known_ingredients"][0]["uses"][0]["requirement"] == requirement


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
    ({"ingredient_id": None}, "INVALID_INGREDIENT"),
    ({"name": " " * 500 + "test"}, "INVALID_INGREDIENT"),
    ({"purpose": "invalid_enum"}, "INVALID_PURPOSE"),
    ({"measurement_basis": "invalid_enum"}, "INVALID_MEASUREMENT_BASIS"),
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


@pytest.mark.parametrize("purpose", ["main", "seasoning", "cooking_medium", "garnish", "unknown"])
def test_v3_purpose_values_are_preserved_and_known_amounts_scale(purpose):
    catalog = change_line(fixture_catalog((1,)), purpose=purpose)
    data = run(catalog, (1,), 2)
    line = data["recipes"][0]["lines"][0]
    group = data["known_ingredients"][0]
    assert line["quantity_value"] == "100"
    assert group["purpose"] == purpose
    assert group["mergeable"] is (purpose != "unknown")
    assert data["status"] == "COMPLETE"


@pytest.mark.parametrize("changes", [
    {"ingredient_form": None},
    {"measurement_basis": None},
    {"measurement_basis": "unknown"},
    {"requirement": "unknown"},
    {"purpose": "unknown"},
])
def test_nonessential_or_unknown_metadata_does_not_block_per_line_calculation(changes):
    catalog = change_line(fixture_catalog((1,)), **changes)
    data = run(catalog, (1,), 2)
    assert data["status"] == "COMPLETE" and data["totals_complete"]
    assert data["recipes"][0]["lines"][0]["quantity_value"] == "100"
    assert data["known_ingredients"][0]["mergeable"] is False
    assert data["known_ingredients"][0]["uses"][0]["quantity_value"] == "100"


def test_lines_without_compatible_metadata_stay_separate_but_both_scale():
    catalog = fixture_catalog((1, 5))
    left = replace(catalog.revisions[1].lines[0], ingredient_form=None, measurement_basis="unknown")
    right = replace(catalog.revisions[5].lines[0], ingredient_form=None, measurement_basis="unknown")
    catalog = change_recipe(catalog, 1, lines=(left,))
    catalog = change_recipe(catalog, 5, lines=(right,))
    data = run(catalog, (1, 5), 2)
    groups = [g for g in data["known_ingredients"] if g["ingredient_id"] == 1001]
    assert data["status"] == "COMPLETE"
    assert len(groups) == 2 and all(g["mergeable"] is False and len(g["uses"]) == 1 for g in groups)
    assert [g["quantity_value"] for g in groups] == ["100", "25"]


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


def test_v3_can_explain_missing_structured_portion_data_without_approval_workflow():
    data = run(Catalog(available=False, unavailable_reason="STRUCTURED_PORTION_DATA_UNAVAILABLE"))
    assert codes(data) == {"STRUCTURED_PORTION_DATA_UNAVAILABLE"}


def test_v3_missing_base_servings_reports_one_precise_blocker():
    catalog = change_recipe(fixture_catalog((1,)), base_servings=None)
    catalog = replace(catalog, trust_admin_catalog=True, portion_policy=None)
    data = run(catalog, (1,), 4)
    blockers = [r["code"] for r in data["recipes"][0]["reasons"]]
    assert blockers == ["INVALID_BASE_SERVINGS"]


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


def test_daily_soup_uses_declared_recipe_servings_without_inventing_broth_targets():
    catalog=fixture_catalog((1,))
    revision=catalog.revisions[1]
    solid=replace(revision.lines[0],amount_min="400",unit="g",measurement_basis="gross")
    oil=replace(revision.lines[1],amount_kind="exact",amount_min="10",amount_max="10",unit="ml",purpose="cooking_medium",measurement_basis="gross",scaling_mode="linear")
    catalog=replace(catalog,trust_admin_catalog=True,revisions={1:replace(revision,role="soup",data_status="verified",base_servings="4",lines=(solid,oil))},
                    units={**catalog.units,"ml":Unit("ml","volume","TEST_ONLY ml")})
    result=calculate(validate({"recipe_ids":[1],"people":4}),catalog)
    assert not result["totals_complete"]
    assert result["recipes"][0]["target_servings"] == "4"
    assert not result["portion_groups"]
    assert [line["quantity_value"] for line in result["recipes"][0]["lines"]]==["400","10"]
    broth=replace(solid,line_id=3,ingredient_id=3,amount_min="1000",unit="ml")
    catalog=replace(catalog,revisions={1:replace(catalog.revisions[1],lines=(solid,oil,broth))})
    result=calculate(validate({"recipe_ids":[1],"people":4}),catalog)
    assert not result["totals_complete"]
    assert [line["quantity_value"] for line in result["recipes"][0]["lines"]]==["400","10","1000"]


def test_academic_reference_profiles_preserve_units_and_prepared_food():
    from scripts.complete_reference_portions import explicit_amount,profile,basis,reasonable_peer
    from decimal import Decimal
    assert explicit_amount("1/2 con")== (Decimal("0.5"),"piece")
    assert explicit_amount("2 xap")== (Decimal("2"),"source_stack")
    assert explicit_amount("1 muong")== (Decimal("1"),"source_spoon")
    assert explicit_amount("mot it") is None
    assert basis({"name":"Bun","ingredient_form":None})[0]=="prepared"
    assert basis({"name":"Tom","ingredient_form":"boc vo, bo chi"})[0]=="edible"
    assert profile("Muoi","main")[2]!=profile("Thit ga","main")[2]
    assert not reasonable_peer("ml",Decimal("75"),"cooking-fat","trang chao")
    assert reasonable_peer("ml",Decimal("75"),"cooking-fat","chien ngap")
    assert not reasonable_peer("ml",Decimal("125"),"acid-or-cooking-liquid","")


def test_daily_multiple_soups_sum_only_compatible_original_servings():
    catalog = fixture_catalog((1, 5))
    revisions = {rid: replace(rev, role="soup", base_servings="4", data_status="verified", serving_basis="source_servings") for rid, rev in catalog.revisions.items()}
    catalog = replace(catalog, trust_admin_catalog=True, revisions=revisions)
    for people in (2, 4, 6, 8, 12):
        data = calculate(validate({"recipe_ids": [1, 5], "people": people}), catalog)
        assert data["service_assessment"]["groups"][0]["source_capacity"] == "8"
        assert all(r["target_servings"] == "4" for r in data["recipes"])
        assert (data["status"] == "COMPLETE") == (people <= 1)
        assert data["known_ingredients"][0]["quantity_value"] == "150"
        CalculationData.model_validate({"dataset_version":"TEST_ONLY", **data})
    mixed = change_recipe(catalog, 5, serving_basis="adult_equivalent")
    data = calculate(validate({"recipe_ids": [1,5], "people":8}), mixed)
    assert data["service_assessment"]["groups"][0]["source_capacity"] is None
    assert data["status"] == "INCOMPLETE"


def test_custom_daily_keeps_previous_scaling_behavior():
    catalog = fixture_catalog((1,))
    revision = replace(catalog.revisions[1], role="main", data_status="verified", base_servings="4")
    catalog = replace(catalog, trust_admin_catalog=True, revisions={1: revision})
    data = calculate(validate({"recipe_ids":[1], "people":8, "layout_mode":"custom"}), catalog)
    assert data["recipes"][0]["target_servings"] == "8"
    assert data["known_ingredients"][0]["quantity_value"] == "200"


@pytest.mark.parametrize("people", [2,4,6,8,11,12])
@pytest.mark.parametrize("roles", [("main","main","main","vegetable","vegetable","soup"),
                                   ("main","main","main","main","vegetable","soup")])
def test_custom_six_dishes_keep_shared_group_allocation_when_people_change(people, roles):
    ids=(1,5,6,7,8,9)
    catalog=fixture_catalog(ids)
    revisions={rid:replace(catalog.revisions[rid], role=role,base_servings="4",data_status="verified",
        lines=(replace(catalog.revisions[rid].lines[0],amount_kind="exact",amount_min="400",amount_max="400"),))
        for rid,role in zip(ids,roles)}
    catalog=replace(catalog,trust_admin_catalog=True,revisions=revisions)
    data=calculate(validate({"recipe_ids":list(ids),"people":people,"layout_mode":"custom"}),catalog)
    for role in set(roles):
        members=[r for r in data["recipes"] if revisions[r["recipe_id"]].role==role]
        assert abs(sum(Fraction(r["target_servings"]) for r in members)-people) <= Fraction(3,10**6)
        low=sum(Fraction(r["lines"][0]["quantity_min"]) for r in members)
        high=sum(Fraction(r["lines"][0]["quantity_max"]) for r in members)
        assert low <= 100*people <= high
        assert high-low <= Fraction(6,10**6)
    assert data["recipe_ids"] == list(ids)
    CalculationData.model_validate({"dataset_version":"TEST_ONLY",**data})


def test_daily_weighted_average_does_not_prove_adequacy_when_main_is_short():
    from source.server.meal_plan_calculation import daily_service_verdict, daily_meal_capacity
    groups = [{"role":role,"source_capacity":value} for role,value in
              (("main","4"),("vegetable","8"),("soup","4"))]
    capacity = daily_meal_capacity({g["role"]:g["source_capacity"] for g in groups})
    assert capacity == Fraction(26,5)
    status, limitations = daily_service_verdict(groups,Fraction(5),capacity)
    assert status == "risk"
    assert any("Món chính" in reason for reason in limitations)
    assert daily_service_verdict(groups,Fraction(5),capacity,False)[0] == "unknown"
    assert daily_service_verdict(groups,Fraction(2),capacity)[0] == "surplus"


def test_daily_service_verdict_is_exposed_without_changing_original_ingredients():
    ids=(1,5,6)
    catalog=fixture_catalog(ids)
    revisions={rid:replace(catalog.revisions[rid],role=role,base_servings=servings,
                         serving_basis="source_servings",data_status="estimated")
               for rid,role,servings in ((1,"main","4"),(5,"vegetable","8"),(6,"soup","4"))}
    catalog=replace(catalog,trust_admin_catalog=True,revisions=revisions)
    result=calculate(validate({"recipe_ids":list(ids),"people":5}),catalog)
    assert result["service_assessment"]["meal_capacity"] == "5.2"
    assert result["service_assessment"]["assessment_status"] == "risk"
    assert [r["target_servings"] for r in result["recipes"]] == ["4","8","4"]
    CalculationData.model_validate({"dataset_version":"TEST_ONLY",**result})


def test_daily_eight_people_does_not_require_soup_to_feed_everyone():
    ids=(1,5,6,7,8)
    catalog=fixture_catalog(ids)
    roles=("main","main","main","vegetable","soup")
    revisions={rid:replace(catalog.revisions[rid],role=role,base_servings="4",serving_basis="source_servings",data_status="verified") for rid,role in zip(ids,roles)}
    catalog=replace(catalog,trust_admin_catalog=True,revisions=revisions)
    data=calculate(validate({"recipe_ids":list(ids),"people":8}),catalog)
    assert data["service_assessment"]["meal_capacity"] == "8.4"
    assert data["status"] == "COMPLETE"
    assert all(r["target_servings"]=="4" for r in data["recipes"])
    CalculationData.model_validate({"dataset_version":"TEST_ONLY",**data})
