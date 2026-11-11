"""SYNTHETIC TEST DATA ONLY. Simulated APPROVED objects are never production data.

These recipes/amounts/reviews are invented test cases, NOT verified food recipes,
not the pilot dossier, not approved by a person, and must never be imported.
"""
from source.server.meal_plan_calculation import (
    Allocation, Catalog, IngredientLine, PortionPolicy, Review, Revision, Unit,
)

TEST_REVIEW = Review("APPROVED", "TEST_ONLY_SIMULATED_DECISION_DO_NOT_IMPORT",
                     "TEST_ONLY_SYNTHETIC_EVIDENCE_DO_NOT_IMPORT")


def test_line(line_id=1, **changes):
    values = dict(line_id=line_id, ingredient_id=1001, name="TEST_ONLY ingredient",
                  ingredient_form="test_raw", amount_kind="exact", amount_min="100",
                  unit="g", measurement_basis="edible", purpose="main",
                  review=TEST_REVIEW, scaling_mode="linear", scaling_review=TEST_REVIEW)
    return IngredientLine(**{**values, **changes})


test_line.__test__ = False


def fixture_catalog(recipe_ids=(1, 5)):
    revisions = {}
    for index, recipe_id in enumerate(recipe_ids):
        lines = (test_line(amount_min="100" if index == 0 else "50"),)
        if index == 0:
            lines += (test_line(2, ingredient_id=1002, name="TEST_ONLY liquid",
                               amount_kind="range", amount_min="200", amount_max="300", unit="ml"),)
        else:
            lines += (test_line(2, ingredient_id=1003, name="TEST_ONLY countable",
                               ingredient_form="test_whole", amount_min="1", unit="piece"),)
        revisions[recipe_id] = Revision(recipe_id, 100 + recipe_id,
            base_servings="2" if index == 0 else "4", serving_basis="source_servings",
            lines=lines, content_complete=True, review=TEST_REVIEW, servings_review=TEST_REVIEW)
    units = {code: Unit(code, dimension, "TEST_ONLY explicit unit definition", TEST_REVIEW)
             for code, dimension in [("g", "mass"), ("ml", "volume"), ("piece", "count"), ("kg", "mass")]}
    policy = PortionPolicy("TEST_ONLY_ALLOCATION_NOT_A_REAL_POLICY", {
        rid: Allocation(r.revision_id, r.serving_basis, "1") for rid, r in revisions.items()
    }, TEST_REVIEW)
    return Catalog(revisions, units, policy)
