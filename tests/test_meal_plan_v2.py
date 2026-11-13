from itertools import product
import time

import pytest
import source.server.meal_plan_v2 as meal_plan_v2
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


@pytest.mark.parametrize("people",range(1,13))
def test_retained_plan_b_plan_b_uses_original_main_vegetable_bands_and_one_soup(people,monkeypatch):
    recipes,classification=daily_large_fixture(4)
    def capacity_disabled(*args,**kwargs):
        raise AssertionError("Plan B must not optimize selection by serving capacity")
    monkeypatch.setattr(meal_plan_v2,"_daily_capacity_layouts",capacity_disabled)
    monkeypatch.setattr(meal_plan_v2,"_daily_selection_quality",capacity_disabled)
    options=validate({"adaptive_daily":True,"people":people,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID)
    result=meal_plan_v2._generate_plan_b(recipes,options,classification,REQUEST_ID)
    assert result["plan"] is not None
    assert result["counts"]=={"main":1 if people<=4 else 2,
                              "vegetable":1 if people<=6 else 2,"soup":1}
    changed_servings=[dict(r,service_capacity="0.1" if r["id"]%2 else "100") for r in recipes]
    changed=meal_plan_v2._generate_plan_b(changed_servings,options,classification,REQUEST_ID)
    assert current(changed)==current(result)
    assert changed["counts"]==result["counts"]


def test_retained_plan_b_plan_b_regeneration_changes_recipe_set_and_keeps_structure_and_pins():
    recipes,classification=daily_large_fixture(4)
    first=meal_plan_v2._generate_plan_b(recipes,validate({"adaptive_daily":True,"people":8,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    previous=current(first)
    result=meal_plan_v2._generate_plan_b(recipes,validate({"adaptive_daily":True,"people":8,"action":"regenerate",
        "current_plan":previous,"locked_slots":["main:1"]},REQUEST_ID),classification,REQUEST_ID)
    assert result["plan"] is not None
    assert result["counts"]==first["counts"]
    assert set(current(result).values()) != set(previous.values())
    assert current(result)["main:1"]==previous["main:1"]


def test_retained_plan_b_plan_b_does_not_treat_permuting_the_same_main_recipes_as_a_new_meal():
    recipes,classification=daily_large_fixture(2)
    recipes=[r for r in recipes if r["id"] in (1,2,10,20)]
    first=meal_plan_v2._generate_plan_b(recipes,validate({"adaptive_daily":True,"people":5},REQUEST_ID),classification,REQUEST_ID)
    result=meal_plan_v2._generate_plan_b(recipes,validate({"adaptive_daily":True,"people":5,"action":"regenerate",
        "current_plan":current(first)},REQUEST_ID),classification,REQUEST_ID)
    assert result["plan"] is None
    assert result["reason"]["code"] in {"NO_ALTERNATIVE","NO_COMPLETE_MEAL_PLAN"}


def daily_pairing_fixture():
    from source.server.meal_plan import Classification
    roles={1:"main",2:"main",3:"vegetable",4:"vegetable",5:"soup"}
    recipes=[{"id":rid,"title":f"Fixture {rid}","minutes":10,
              "all_ids":{ingredient},"required_ids":{ingredient},
              "daily_prominent_ids":{ingredient},"service_capacity":"4",
              "service_capacity_status":"verified","portion_ready":True}
             for rid,ingredient in ((1,101),(2,102),(3,44),(4,45),(5,44))]
    return recipes,Classification("daily-pairing-fixture",roles)


def test_retained_plan_b_daily_avoids_prominent_ingredient_across_vegetable_and_soup():
    recipes,classification=daily_pairing_fixture()
    options=validate({"adaptive_daily":True,"people":4,"counts":{"main":1,"vegetable":1,"soup":1},
                      "current_plan":{"soup:1":5},"locked_slots":["soup:1"]},REQUEST_ID)
    result=meal_plan_v2._generate_plan_b(recipes,options,classification,REQUEST_ID)
    assert current(result)["vegetable:1"]==4
    assert current(result)["soup:1"]==5


def test_retained_plan_b_daily_common_seasoning_tags_do_not_count_as_prominent_repetition():
    recipes,classification=daily_pairing_fixture()
    metadata={r["id"]:{"main_ingredient":frozenset({"garlic","salt"})} for r in recipes}
    result=meal_plan_v2._generate_plan_b(recipes,validate({"adaptive_daily":True,"people":4,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID,
        pairing_metadata=metadata)
    assert "lặp nguyên liệu nổi bật" not in result["daily_layout_reason"]
    assert metadata[1]["main_ingredient"]==frozenset({"garlic","salt"})


def test_retained_capacity_engine_daily_five_people_prefers_main_contribution_without_fixed_people_layout():
    recipes,classification=daily_pairing_fixture()
    options=validate({"adaptive_daily":True,"people":5,"counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID)
    result=meal_plan_v2._generate_capacity_combos(recipes,options,classification,REQUEST_ID)
    assert result["counts"]=={"main":2,"vegetable":1,"soup":1}
    # A larger original main recipe needs no extra main at the same people count.
    recipes=[dict(r,service_capacity="12") if r["id"]==1 else r for r in recipes if r["id"]!=2]
    result=meal_plan_v2._generate_capacity_combos(recipes,options,classification,REQUEST_ID)
    assert result["counts"]=={"main":1,"vegetable":1,"soup":1}


def test_retained_capacity_engine_daily_two_vegetables_when_their_real_contribution_is_needed():
    recipes,classification=daily_pairing_fixture()
    recipes=[dict(r,service_capacity="12" if r["id"]==1 else "2" if r["id"] in (3,4) else "4")
             for r in recipes if r["id"]!=2]
    result=meal_plan_v2._generate_capacity_combos(recipes,validate({"adaptive_daily":True,"people":8,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    assert result["counts"]=={"main":1,"vegetable":2,"soup":1}


def daily_large_fixture(main_count):
    from source.server.meal_plan import Classification
    roles={rid:role for role,ids in (("main",range(1,main_count+1)),("vegetable",range(10,13)),("soup",[20])) for rid in ids}
    recipes=[{"id":rid,"title":f"Fixture {rid}","minutes":10,"all_ids":{100+rid},
        "required_ids":{100+rid},"daily_prominent_ids":{100+rid},"service_capacity":"4",
        "service_capacity_status":"verified","portion_ready":True} for rid in roles]
    return recipes,Classification("daily-main-priority",roles)


def test_retained_capacity_engine_daily_eight_prefers_an_available_main_over_a_third_vegetable():
    recipes,classification=daily_large_fixture(3)
    recipes=[dict(r,service_capacity="2" if r["id"]==20 else
                  "3" if r["id"]==11 else "4") for r in recipes]
    result=meal_plan_v2._generate_capacity_combos(recipes,validate({"adaptive_daily":True,"people":8,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    assert result["counts"]=={"main":3,"vegetable":1,"soup":1}


def test_retained_capacity_engine_adaptive_daily_uses_bounded_search_before_building_combinations(monkeypatch):
    recipes,classification=daily_large_fixture(4)
    options=validate({"adaptive_daily":True,"people":8,
        "counts":{"main":4,"vegetable":1,"soup":1}},REQUEST_ID)
    def unexpected_combinations(*args,**kwargs):
        raise AssertionError("adaptive daily must not materialize Cartesian combinations")
    monkeypatch.setattr(meal_plan_v2,"combinations",unexpected_combinations)
    result=meal_plan_v2._generate_fixed(recipes,options,classification,REQUEST_ID)
    assert result["plan"] is not None


def test_retained_capacity_engine_daily_third_vegetable_requires_less_vegetable_plans_to_fall_short():
    recipes,classification=daily_large_fixture(2)
    result=meal_plan_v2._generate_capacity_combos(recipes,validate({"adaptive_daily":True,"people":8,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    assert result["counts"]=={"main":2,"vegetable":3,"soup":1}
    assert "Chưa tìm được mâm ít rau hơn" in result["daily_layout_reason"]


def test_retained_capacity_engine_daily_rotation_returns_distinct_combos_until_history_is_exhausted():
    recipes,classification=daily_large_fixture(4)
    history=[]
    result=meal_plan_v2._generate_capacity_combos(recipes,validate({"adaptive_daily":True,"people":4,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    assert result["daily_combo_search"]["complete"] is True
    assert result["daily_combo_search"]["found"]>=11
    current_plan=current(result)
    history.append(result["daily_combo_id"])
    for _ in range(10):
        options=validate({"adaptive_daily":True,"people":4,"action":"regenerate",
            "counts":{"main":1,"vegetable":1,"soup":1},"current_plan":current_plan,
            "combo_history":history},REQUEST_ID)
        result=meal_plan_v2._generate_capacity_combos(recipes,options,classification,REQUEST_ID)
        assert result["plan"] is not None
        assert result["daily_combo_id"] not in history
        assert result["daily_combo_id"]!=meal_plan_v2._daily_combo_id(current_plan.values())
        current_plan=current(result)
        history.append(result["daily_combo_id"])
    assert len(set(history))==11


def test_retained_plan_b_daily_rotation_keeps_pinned_recipe():
    recipes,classification=daily_large_fixture(4)
    current_result=meal_plan_v2._generate_plan_b(recipes,validate({"adaptive_daily":True,"people":4,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    current_plan=current(current_result)
    pinned=current_plan["main:1"]
    options=validate({"adaptive_daily":True,"people":4,"action":"regenerate",
        "counts":{"main":1,"vegetable":1,"soup":1},"current_plan":current_plan,
        "locked_slots":["main:1"],"combo_history":[current_result["daily_combo_id"]]},REQUEST_ID)
    result=meal_plan_v2._generate_plan_b(recipes,options,classification,REQUEST_ID)
    assert result["plan"] is not None
    assert current(result)["main:1"]==pinned
    assert result["daily_combo_id"]!=current_result["daily_combo_id"]


def test_retained_plan_b_daily_single_recipe_replacement_keeps_the_current_structure_and_other_slots():
    recipes,classification=daily_large_fixture(4)
    first=meal_plan_v2._generate_plan_b(recipes,validate({"adaptive_daily":True,"people":4,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    previous=current(first)
    options=validate({"adaptive_daily":True,"people":4,"counts":first["counts"],
        "current_plan":previous,"replace_slot":"main:1"},REQUEST_ID)
    result=meal_plan_v2._generate_plan_b(recipes,options,classification,REQUEST_ID)
    assert result["plan"] is not None
    assert result["counts"]==first["counts"]
    assert result["changed_slots"]==["main:1"]
    assert current(result)["main:1"]!=previous["main:1"]
    assert all(current(result)[key]==recipe_id for key,recipe_id in previous.items() if key!="main:1")


def test_retained_capacity_engine_daily_rotation_never_repeats_seen_combos_when_search_is_incomplete(monkeypatch):
    recipes,classification=daily_large_fixture(4)
    monkeypatch.setattr(meal_plan_v2,"DAILY_LAYOUT_SEARCH_LIMIT",4)
    first=meal_plan_v2._generate_capacity_combos(recipes,validate({"adaptive_daily":True,"people":4,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    assert first["plan"] is not None
    assert first["daily_combo_search"]["complete"] is False
    assert "chưa khẳng định đã hết combo phù hợp" in first["daily_layout_reason"]
    current_plan=current(first)
    from itertools import combinations
    all_combos=[meal_plan_v2._daily_combo_id((*mains,*vegetables,20))
                for m in range(1,5) for v in range(1,4) if m+v+1<=6
                for mains in combinations((1,2,3,4),m) for vegetables in combinations((10,11,12),v)]
    options=validate({"adaptive_daily":True,"people":4,"action":"regenerate",
        "counts":first["counts"],"current_plan":current_plan,"combo_history":all_combos},REQUEST_ID)
    result=meal_plan_v2._generate_capacity_combos(recipes,options,classification,REQUEST_ID)
    assert result["plan"] is None
    assert result["reason"]["code"] == "SEARCH_LIMIT_REACHED"
    assert result["daily_combo_search"]["complete"] is False
    assert "HISTORY_RECYCLED" not in result["warnings"]


def test_retained_capacity_engine_daily_rotation_does_not_choose_a_short_meal_just_for_zero_overlap():
    recipes,classification=daily_large_fixture(4)
    first=meal_plan_v2._generate_capacity_combos(recipes,validate({"adaptive_daily":True,"people":8,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    result=meal_plan_v2._generate_capacity_combos(recipes,validate({"adaptive_daily":True,"people":8,"action":"regenerate",
        "counts":first["counts"],"current_plan":current(first),
        "combo_history":[first["daily_combo_id"]]},REQUEST_ID),classification,REQUEST_ID)
    assert result["plan"] is not None
    selected={i["recipe_id"] for i in result["plan"]["items"]}
    assert selected != set(current(first).values())
    quality=meal_plan_v2._daily_selection_quality([r for r in recipes if r["id"] in selected],8,classification,{})
    assert quality[:3] == (0,0,0)


def test_retained_capacity_engine_daily_rotation_does_not_increase_a_shortfall_when_all_meals_are_short():
    recipes,classification=daily_large_fixture(4)
    first=meal_plan_v2._generate_capacity_combos(recipes,validate({"adaptive_daily":True,"people":12,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    result=meal_plan_v2._generate_capacity_combos(recipes,validate({"adaptive_daily":True,"people":12,"action":"regenerate",
        "counts":first["counts"],"current_plan":current(first),
        "combo_history":[first["daily_combo_id"]]},REQUEST_ID),classification,REQUEST_ID)
    assert result["plan"] is not None
    assert result["counts"]["main"] == first["counts"]["main"] == 4


def test_retained_capacity_engine_daily_rotation_reports_no_alternative_when_only_one_combo_is_available():
    from source.server.meal_plan import Classification
    recipes=[{"id":rid,"title":f"Only {rid}","minutes":10,"all_ids":{rid+100},
        "required_ids":{rid+100},"daily_prominent_ids":{rid+100},"service_capacity":"4",
        "service_capacity_status":"verified","portion_ready":True}
        for rid in (1,10,20)]
    classification=Classification("daily-single-combo", {1:"main",10:"vegetable",20:"soup"})
    first=meal_plan_v2._generate_capacity_combos(recipes,validate({"adaptive_daily":True,"people":4,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    options=validate({"adaptive_daily":True,"people":4,"action":"regenerate",
        "counts":first["counts"],"current_plan":current(first),
        "combo_history":[first["daily_combo_id"]]},REQUEST_ID)
    result=meal_plan_v2._generate_capacity_combos(recipes,options,classification,REQUEST_ID)
    assert result["plan"] is None
    assert result["reason"]["code"]=="NO_ALTERNATIVE"
    assert result["daily_combo_search"]=={"found":1,"complete":True}


@pytest.mark.parametrize("people",[2,8,12])
def test_retained_capacity_engine_daily_unknown_servings_do_not_create_vegetables_from_people_bands(people):
    recipes,classification=daily_large_fixture(3)
    recipes=[dict(r,service_capacity=None,service_capacity_status="needs_review") for r in recipes]
    result=meal_plan_v2._generate_capacity_combos(recipes,validate({"adaptive_daily":True,"people":people,
        "counts":{"main":1,"vegetable":1,"soup":1}},REQUEST_ID),classification,REQUEST_ID)
    assert result["counts"]=={"main":1,"vegetable":1,"soup":1}
    assert "Thiếu số suất" in result["daily_layout_reason"]


def test_retained_plan_b_daily_relaxes_diversity_but_never_excluded_ingredients_or_pins():
    recipes,classification=daily_pairing_fixture()
    result=meal_plan_v2._generate_plan_b(recipes,validate({"adaptive_daily":True,"people":4,"excluded_ids":[45],
        "counts":{"main":1,"vegetable":1,"soup":1},"current_plan":{"main:1":1},
        "locked_slots":["main:1"]},REQUEST_ID),classification,REQUEST_ID)
    assert current(result)["main:1"]==1
    assert 4 not in current(result).values()
    assert "lặp nguyên liệu nổi bật" in result["daily_layout_reason"]


def test_daily_recipe_roles_ignore_common_seasonings_even_if_imported_as_main(monkeypatch):
    from source.server.unified_repository import UnifiedMySQLRepository
    rows=[{"recipe_id":1,"ingredient_id":iid,"name":name} for iid,name in
          ((44,"Bí đỏ"),(7,"Tỏi"),(17,"Hành lá"),(24,"Nước mắm"),(90,"Muối"),(91,"Đường"),(92,"Nước lọc"))]
    monkeypatch.setattr("source.server.unified_repository._query",lambda *args:rows)
    result=UnifiedMySQLRepository.daily_prominent_ingredients(None,None,[1])
    assert result=={1:{44}}


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


def test_retained_plan_b_adaptive_daily_layout_uses_adult_equivalent_serving_capacity_and_keeps_hard_filters():
    recipes, _ = full_dataset()
    classification = default_classification()
    roles = classification.categories
    candidates = [dict(recipe, service_capacity="3.2", service_capacity_status="estimated")
                  for recipe in recipes if roles.get(recipe["id"]) in ("main", "vegetable", "soup")]
    options = validate({"people": 12, "adults": 8, "children": 4, "adaptive_daily": True,
                        "counts": {"main": 2, "vegetable": 2, "soup": 2},
                        "excluded_ids": [1]}, REQUEST_ID)
    result = meal_plan_v2._generate_plan_b(candidates, options, classification, REQUEST_ID)
    assert result["plan"] is not None
    assert result["adaptive_daily"] is True
    assert result["counts"]["soup"] == 1
    assert sum(result["counts"].values()) <= 6
    assert all(1 not in item["matched_ids"] + item["missing_ids"] for item in result["plan"]["items"])
    assert result["counts"] != {"main": 2, "vegetable": 2, "soup": 2}


def test_retained_plan_b_adaptive_daily_keeps_pinned_slots_even_when_capacity_prefers_smaller_mam():
    recipes, _ = full_dataset()
    classification = default_classification()
    candidates = [dict(recipe, service_capacity="2", service_capacity_status="verified")
                  for recipe in recipes if classification.categories.get(recipe["id"]) in ("main", "vegetable", "soup")]
    initial_options = validate({"counts": {"main": 1, "vegetable": 1, "soup": 1}}, REQUEST_ID)
    initial = meal_plan_v2._generate_plan_b(candidates, initial_options, classification, REQUEST_ID)
    current_plan = current(initial)
    options = validate({"people": 8, "adults": 8, "children": 0, "adaptive_daily": True,
                        "counts": {"main": 2, "vegetable": 2, "soup": 1},
                        "current_plan": current_plan, "locked_slots": ["main:1"]}, REQUEST_ID)
    result = meal_plan_v2._generate_plan_b(candidates, options, classification, REQUEST_ID)
    assert result["plan"] is not None
    assert current_plan["main:1"] == next(item["recipe_id"] for item in result["plan"]["items"] if item["slot"] == "main:1")


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
    monkeypatch.setattr("source.server.meal_plan_v2._vectorized_chunked_exact_best", lambda *args, **kwargs: (None, False))
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


def test_daily_pairing_avoids_duplicate_admin_primary_ingredient_before_pantry_score():
    base = default_classification()
    roles = {1: "main", 2: "main", 3: "main", 4: "vegetable"}
    classification = type(base)("pairing-fixture", roles)
    recipes = [
        {"id": 1, "title": "A", "minutes": 10, "required_ids": {1}, "all_ids": {1}},
        {"id": 2, "title": "B", "minutes": 10, "required_ids": {2}, "all_ids": {2}},
        {"id": 3, "title": "C", "minutes": 10, "required_ids": {3, 4, 5}, "all_ids": {3, 4, 5}},
        {"id": 4, "title": "Rau", "minutes": 5, "required_ids": set(), "all_ids": set()},
    ]
    pairing = {1: {"main_ingredient": {"chicken"}},
               2: {"main_ingredient": {"chicken"}},
               3: {"main_ingredient": {"beef"}}}
    payload = {"counts": {"main": 2, "vegetable": 1, "soup": 0}}
    result = generate(recipes, validate(payload, REQUEST_ID), classification, REQUEST_ID,
                      pairing_metadata=pairing)
    assert result["plan"]
    main_ids = [item["recipe_id"] for item in result["plan"]["items"] if item["slot"].startswith("main:")]
    assert main_ids == [1, 3]


def test_equal_meals_prefer_recipes_with_verified_portion_data():
    base = default_classification()
    classification = type(base)("portion-fixture", {1: "main", 2: "main", 3: "vegetable", 4: "soup"})
    recipes = [
        {"id": rid, "title": str(rid), "minutes": 10, "required_ids": set(), "all_ids": set(),
         "portion_ready": rid != 2}
        for rid in (1, 2, 3, 4)
    ]
    options = validate({"counts": {"main": 1, "vegetable": 1, "soup": 1}}, REQUEST_ID)
    result = generate(recipes, options, classification, REQUEST_ID)
    assert result == generate(recipes, options, classification, REQUEST_ID, _force_exhaustive=True)
    assert [item["recipe_id"] for item in result["plan"]["items"]] == [1, 3, 4]


def test_large_custom_layout_prefers_portion_ready_candidates_when_available():
    base = default_classification()
    classification = type(base)("custom-portion-fixture", {
        1: "main", 2: "main", 3: "main", 4: "main", 5: "main",
        6: "vegetable", 7: "soup",
    })
    recipes = [
        {"id": rid, "title": str(rid), "minutes": 10, "required_ids": set(),
         "all_ids": set(), "portion_ready": rid != 1}
        for rid in range(1, 8)
    ]
    options = validate({"layout_mode": "custom", "people": 11,
                        "counts": {"main": 4, "vegetable": 1, "soup": 1}}, REQUEST_ID)

    result = generate(recipes, options, classification, REQUEST_ID)

    assert result["plan"] is not None
    main_ids = [item["recipe_id"] for item in result["plan"]["items"] if item["slot"].startswith("main:")]
    assert len(main_ids) == 4
    assert 1 not in main_ids
    assert all(next(recipe for recipe in recipes if recipe["id"] == rid)["portion_ready"] for rid in main_ids)


@pytest.mark.parametrize("pairing,expected", [
    ({1: {"main_ingredient": {"chicken"}, "cooking_method": {"boil"}},
      2: {"main_ingredient": {"chicken"}, "cooking_method": {"fry"}},
      3: {"main_ingredient": {"beef"}, "cooking_method": {"steam"}}}, {1, 3}),
    ({1: {"main_ingredient": {"beef"}, "cooking_method": {"stir_fry"}},
      2: {"main_ingredient": {"chicken"}, "cooking_method": {"stir_fry"}},
      3: {"main_ingredient": {"fish"}, "cooking_method": {"braise"}}}, {1, 3}),
    ({1: {"main_ingredient": {"fish"}, "cooking_method": {"steam"}},
      2: {"main_ingredient": {"fish"}, "cooking_method": {"fry"}},
      3: {"main_ingredient": {"chicken"}, "cooking_method": {"braise"}}}, {1, 3}),
])
def test_pairing_avoids_chicken_fish_and_method_repeats(pairing, expected):
    base = default_classification()
    roles = {1: "main", 2: "main", 3: "main", 4: "vegetable"}
    classification = type(base)("pairing-collision-fixture", roles)
    recipes = [{"id": rid, "title": f"TEST_ONLY {rid}", "minutes": 10,
                "required_ids": set(), "all_ids": set()} for rid in roles]
    result = generate(recipes, validate({"counts": {"main": 2, "vegetable": 1, "soup": 0}}, REQUEST_ID),
                      classification, REQUEST_ID, pairing_metadata=pairing)
    assert result["plan"], result["reason"]
    main_ids = {item["recipe_id"] for item in result["plan"]["items"]
                if item["slot"].startswith("main:")}
    assert main_ids == expected


def test_guest_mode_ignores_pantry_fit_and_missing_limit_but_keeps_exclusions():
    roles = {1: "main", 2: "main", 5: "main", 6: "main", 3: "side", 4: "vegetable"}
    classification = type(default_classification())("guest-fixture", roles)
    recipes = [
        {"id": 1, "title": "Pantry match", "minutes": 30, "required_ids": {9}, "all_ids": {9}},
        {"id": 2, "title": "Quick one", "minutes": 10, "required_ids": set(), "all_ids": set()},
        {"id": 5, "title": "Excluded", "minutes": 1, "required_ids": {99}, "all_ids": {99}},
        {"id": 6, "title": "Quick two", "minutes": 11, "required_ids": set(), "all_ids": set()},
        {"id": 3, "title": "Appetizer", "minutes": 5, "required_ids": set(), "all_ids": set()},
        {"id": 4, "title": "Vegetable", "minutes": 5, "required_ids": set(), "all_ids": set()},
    ]
    metadata = Catalog("guest-fixture-meta", {}, roles,
                       contexts={"occasion": {"guests": frozenset(roles)}})
    payload = {"people": 1, "preferences": {"occasion": "guests"},
               "ingredient_ids": [9], "max_missing": 0, "excluded_ids": [99]}
    options = validate(payload, REQUEST_ID)
    assert options.filters.max_missing is None
    result = generate(recipes, options, classification, REQUEST_ID, metadata)
    assert result["plan"], result["reason"]
    chosen = {item["recipe_id"] for item in result["plan"]["items"]}
    assert {2, 3, 4, 6} <= chosen
    assert {1, 5}.isdisjoint(chosen)


def test_large_vector_search_optimizes_admin_pairing_diversity():
    roles, recipes, pairing = {}, [], {}
    for group, start in (("main", 100), ("vegetable", 200), ("soup", 300)):
        for offset in range(12):
            recipe_id = start + offset
            roles[recipe_id] = group
            recipes.append({"id": recipe_id, "title": f"TEST_ONLY {group} {offset}", "minutes": 10,
                            "required_ids": set(), "all_ids": set()})
            code = f"family_{offset % 6}"
            pairing[recipe_id] = {"main_ingredient": {code}, "cooking_method": {f"method_{offset % 6}"}}
    classification = type(default_classification())("large-pairing-fixture", roles)
    result = generate(recipes, validate({"counts": {"main": 2, "vegetable": 2, "soup": 2}}, REQUEST_ID),
                      classification, REQUEST_ID, pairing_metadata=pairing)
    assert result["plan"], result["reason"]
    selected = [item["recipe_id"] for item in result["plan"]["items"]]
    assert len({next(iter(pairing[rid]["main_ingredient"])) for rid in selected}) == 6
    assert len({next(iter(pairing[rid]["cooking_method"])) for rid in selected}) == 6


def test_large_guest_role_search_finds_diverse_plan_without_cartesian_materialization():
    roles, recipes, pairing = {}, [], {}
    for group, start, size in (("main", 1000, 30), ("side", 2000, 8),
                               ("vegetable", 3000, 8), ("soup", 4000, 8)):
        for offset in range(size):
            recipe_id = start + offset
            roles[recipe_id] = group
            recipes.append({"id": recipe_id, "title": f"TEST_ONLY {group} {offset}", "minutes": 10,
                            "required_ids": set(), "all_ids": set()})
            pairing[recipe_id] = {"main_ingredient": {f"ingredient_{recipe_id}"},
                                  "cooking_method": {f"method_{recipe_id}"}}
    classification = type(default_classification())("large-guest-fixture", roles)
    metadata = Catalog("large-guest-meta", {}, roles,
                       contexts={"occasion": {"guests": frozenset(roles)}})
    options = validate({"people": 6, "preferences": {"occasion": "guests"}}, REQUEST_ID)

    result = generate(recipes, options, classification, REQUEST_ID, metadata,
                      pairing_metadata=pairing)

    assert result["plan"], result["reason"]
    selected = [item["recipe_id"] for item in result["plan"]["items"]]
    assert len(selected) == len(set(selected)) == 6
    assert len({next(iter(pairing[rid]["main_ingredient"])) for rid in selected}) == 6
    assert len({next(iter(pairing[rid]["cooking_method"])) for rid in selected}) == 6


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


@pytest.mark.parametrize("counts", [
    {"main": 3, "vegetable": 2, "soup": 1},
    {"main": 4, "vegetable": 1, "soup": 1},
    {"main": 3, "vegetable": 1, "soup": 2},
])
def test_custom_six_dish_layout_with_pairing_metadata_and_previous_meal(counts):
    recipes = full_dataset()[0]
    classification = default_classification()
    pairing = {recipe["id"]: {"main_ingredient": {"test-primary"}, "cooking_method": {"test-method"}}
               for recipe in recipes}
    previous = generate(recipes, validate({
        "layout_mode": "custom", "people": 11,
        "counts": {"main": 2, "vegetable": 2, "soup": 1}}, REQUEST_ID),
        classification, REQUEST_ID, pairing_metadata=pairing)
    assert previous["plan"] is not None
    current_plan = current(previous)
    history = {group: [rid for slot, rid in current_plan.items() if slot.startswith(group + ":")]
               for group in ("main", "vegetable", "soup")}
    options = validate({"layout_mode": "custom", "people": 11, "counts": counts,
                        "current_plan": current_plan, "avoid_recipe_ids": history}, REQUEST_ID)
    result = generate(recipes, options, classification, REQUEST_ID, pairing_metadata=pairing)
    assert result["plan"] is not None
    assert len(result["plan"]["items"]) == 6
    assert len(set(current(result).values())) == 6
    assert result["counts"] == counts
    pinned = generate(recipes, validate({"layout_mode": "custom", "people": 11, "counts": counts,
        "current_plan": current_plan, "locked_slots": ["main:1"], "avoid_recipe_ids": history}, REQUEST_ID),
        classification, REQUEST_ID, pairing_metadata=pairing)
    assert pinned["plan"] is not None and current(pinned)["main:1"] == current_plan["main:1"]


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
    assert 'meal-plan-v2.js?v=beverage-cards-20261113-2' in web.get('/meal-plan').text
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


@pytest.mark.parametrize("weather,expected", [("hot",1),("cold",2),("rain",2),("sunny",1)])
def test_weather_soft_score_matches_exact_search_and_keeps_exclusions(weather,expected):
    base=default_classification()
    classification=type(base)("weather-fixture",{1:"main",2:"main",3:"vegetable",4:"soup"})
    recipes=[{"id":rid,"title":str(rid),"minutes":10,"required_ids":{rid},"all_ids":{rid},"portion_ready":True} for rid in (1,2,3,4)]
    tags={1:{"cooking_method":{"boil"}},2:{"cooking_method":{"braise"}}}
    payload={"counts":{"main":1,"vegetable":1,"soup":1},"weather":weather}
    options=validate(payload,REQUEST_ID)
    result=generate(recipes,options,classification,REQUEST_ID,pairing_metadata=tags)
    assert result==generate(recipes,options,classification,REQUEST_ID,pairing_metadata=tags,_force_exhaustive=True)
    assert result["plan"]["items"][0]["recipe_id"]==expected
    excluded=validate({**payload,"excluded_ids":[expected]},REQUEST_ID)
    kept=generate(recipes,excluded,classification,REQUEST_ID,pairing_metadata=tags)
    assert expected not in [i["recipe_id"] for i in kept["plan"]["items"]]
