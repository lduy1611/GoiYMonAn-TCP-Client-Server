"""Context filtering tests use TEST_ONLY labels; they are not production evidence."""
from source.server.meal_plan import default_classification
from source.server.meal_plan_v2 import generate, validate
from source.server.meal_preferences import Catalog
from tests.meal_plan_fixtures import full_dataset, REQUEST_ID


def test_test_only_region_and_daily_context_filter_candidates_and_allow_swap():
    recipes, _ = full_dataset()
    roles = default_classification().categories
    selected = frozenset(rid for rid in (1, 3, 4, 5, 6, 9, 29, 30, 31, 32)
                         if rid in roles and roles[rid] in {"main", "vegetable", "soup"})
    metadata = Catalog("TEST_ONLY", {}, roles, contexts={
        "region": {"south": selected},
        "occasion": {"daily": selected},
    })
    result = generate(recipes, validate({"people": 4, "preferences": {"region": "south", "occasion": "daily"}}, REQUEST_ID),
                      default_classification(), REQUEST_ID, metadata)
    ids = {row["recipe_id"] for row in result["plan"]["items"]}
    assert len(ids) == 3 and ids <= selected
    south = next(row for row in metadata.capabilities(layout_support=True)["choices"]["region"] if row["code"] == "south")
    assert south["enabled"] and south["role_counts"]["main"] >= 2
    alternate = generate(recipes, validate({"people": 4, "preferences": {"region": "south", "occasion": "daily"},
        "current_plan": {i["slot"]: i["recipe_id"] for i in result["plan"]["items"]},
        "replace_slot": "main:1"}, REQUEST_ID), default_classification(), REQUEST_ID, metadata)
    assert alternate["plan"] and alternate["changed_slots"] == ["main:1"]
    assert {row["recipe_id"] for row in alternate["plan"]["items"]} <= selected


def test_incomplete_intersection_returns_group_shortage_and_never_relaxes_context():
    recipes, _ = full_dataset()
    roles = default_classification().categories
    mains = sorted(rid for rid, role in roles.items() if role == "main")
    sides = {rid for rid, role in roles.items() if role in ("vegetable", "soup")}
    region_ids = frozenset({mains[0], *sides})
    occasion_ids = frozenset({*mains[1:], *sides})
    metadata = Catalog("TEST_ONLY", {}, roles, contexts={
        "region": {"south": region_ids}, "occasion": {"daily": occasion_ids}})
    result = generate(recipes, validate({"people": 4, "preferences": {"region": "south", "occasion": "daily"}}, REQUEST_ID),
                      default_classification(), REQUEST_ID, metadata)
    assert result["plan"] is None and result["reason"]["code"] == "INSUFFICIENT_GROUP"
    assert result["preferences"] == {"region": "south", "occasion": "daily"}
    assert result["reason"]["groups"]


def test_region_with_partial_roles_remains_selectable_and_reports_exact_shortages():
    recipes, _ = full_dataset()
    roles = default_classification().categories
    mains = frozenset(rid for rid, role in roles.items() if role == "main")
    metadata = Catalog("TEST_ONLY", {}, roles, contexts={
        "region": {"central": mains}, "occasion": {"daily": mains}})

    capabilities = metadata.capabilities(layout_support=True)
    central = next(row for row in capabilities["choices"]["region"] if row["code"] == "central")
    assert central["enabled"]
    assert metadata.unsupported({"region": "central", "occasion": "daily"}) == []

    result = generate(recipes, validate({"people": 4,
        "preferences": {"region": "central", "occasion": "daily"}}, REQUEST_ID),
        default_classification(), REQUEST_ID, metadata)
    assert result["plan"] is None
    assert result["reason"]["code"] == "INSUFFICIENT_GROUP"
    assert {row["group"] for row in result["reason"]["groups"]} == {"vegetable", "soup"}


def test_unapproved_or_missing_context_stays_disabled():
    roles = default_classification().categories
    metadata = Catalog("TEST_ONLY", {}, roles)
    result = metadata.capabilities(layout_support=True)
    assert all(not c["enabled"] for group in ("region", "occasion") for c in result["choices"][group])
    options = validate({"preferences": {"region": "south"}}, REQUEST_ID)
    assert "region" in metadata.unsupported(options.preferences)
