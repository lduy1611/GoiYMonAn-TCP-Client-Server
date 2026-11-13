"""Stateless meal planning, independent of the unchanged B0/P1 ranker."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from source.common.protocol import ProtocolError

SLOTS = ("main", "vegetable", "soup")
CATEGORY_COUNTS = {"main": 23, "vegetable": 4, "soup": 6, "starch": 15, "other": 2}
CATEGORY_PATH = Path(__file__).resolve().parents[2] / "data/recipe_categories.json"
ALGORITHM = "meal-plan-v1"


@dataclass(frozen=True)
class Classification:
    version: str
    categories: Mapping[int, str]


def load_classification(path: Path = CATEGORY_PATH) -> Classification:
    """Validate the approved 50-recipe catalog without connecting to a database."""
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate classification JSON key")
            result[key] = value
        return result

    catalog = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    if (not isinstance(catalog, dict) or set(catalog) != {"classification_version", "recipes"}
            or not isinstance(catalog["classification_version"], str)
            or not catalog["classification_version"].strip() or len(catalog["classification_version"]) > 80
            or not isinstance(catalog["recipes"], list)):
        raise ValueError("invalid classification catalog")
    categories = {}
    for item in catalog["recipes"]:
        if (not isinstance(item, dict) or not {"recipe_id", "title", "category"} <= set(item)
                or set(item) - {"recipe_id", "title", "category", "note"}
                or type(item["recipe_id"]) is not int or item["recipe_id"] <= 0
                or item["recipe_id"] in categories
                or not isinstance(item["title"], str) or not item["title"].strip()
                or not isinstance(item["category"], str) or item["category"] not in CATEGORY_COUNTS
                or "note" in item and not isinstance(item["note"], str)):
            raise ValueError("invalid or duplicate recipe classification")
        categories[item["recipe_id"]] = item["category"]
    if set(categories) != set(range(1, 51)) or Counter(categories.values()) != CATEGORY_COUNTS:
        raise ValueError("classification must contain the approved 50 IDs and category counts")
    return Classification(catalog["classification_version"], MappingProxyType(categories))


@lru_cache(maxsize=1)
def default_classification() -> Classification:
    return load_classification()


@dataclass(frozen=True)
class MealPlanOptions:
    selected: frozenset[int]
    excluded: frozenset[int]
    max_minutes: int | None
    max_total_minutes: int | None
    max_missing: int | None
    current_plan: tuple[int, int, int] | None
    locked_slots: frozenset[str]
    avoid_recipe_ids: tuple[frozenset[int], frozenset[int], frozenset[int]]


def validate_meal_plan(payload: dict[str, Any], request_id: str) -> MealPlanOptions:
    allowed = {"ingredient_ids", "excluded_ids", "max_minutes", "max_total_minutes",
               "max_missing", "current_plan", "locked_slots", "avoid_recipe_ids"}

    def integer(value, low, high=None):
        return type(value) is int and value >= low and (high is None or value <= high)

    def ids(value):
        return isinstance(value, list) and len(value) <= 30 and all(integer(i, 1) for i in value)

    def reject(message="invalid GENERATE_MEAL_PLAN payload"):
        raise ProtocolError("INVALID_PAYLOAD", message, request_id)

    if not isinstance(payload, dict) or set(payload) - allowed:
        reject()
    selected, excluded = payload.get("ingredient_ids", []), payload.get("excluded_ids", [])
    if not ids(selected) or not ids(excluded) or set(selected) & set(excluded):
        reject("ingredient ids are invalid")
    for name, upper in (("max_minutes", 240), ("max_total_minutes", 720), ("max_missing", 50)):
        value = payload.get(name)
        if value is not None and not integer(value, 0 if name == "max_missing" else 1, upper):
            reject()
    current = payload.get("current_plan")
    if current is not None:
        if (not isinstance(current, dict) or set(current) != set(SLOTS)
                or not all(integer(i, 1) for i in current.values()) or len(set(current.values())) != 3):
            reject("current_plan must contain three distinct recipe ids and exactly three slots")
        current = tuple(current[slot] for slot in SLOTS)
    locked = payload.get("locked_slots", [])
    if (not isinstance(locked, list) or len(locked) > 2
            or not all(isinstance(slot, str) and slot in SLOTS for slot in locked)
            or len(set(locked)) != len(locked) or locked and current is None):
        reject("locked_slots requires a current plan and at most two distinct valid slots")
    avoid = payload.get("avoid_recipe_ids", {})
    if not isinstance(avoid, dict) or set(avoid) - set(SLOTS):
        reject("avoid_recipe_ids must map meal slots to recipe id lists")
    for history in avoid.values():
        if (not isinstance(history, list) or len(history) > 50
                or not all(integer(i, 1) for i in history) or len(set(history)) != len(history)):
            reject("recipe history must contain distinct positive integer ids")
    if sum(len(history) for history in avoid.values()) > 50 or any(avoid.values()) and current is None:
        reject("recipe history requires current_plan and at most 50 ids overall")
    return MealPlanOptions(frozenset(selected), frozenset(excluded), payload.get("max_minutes"),
                           payload.get("max_total_minutes"), payload.get("max_missing"),
                           current, frozenset(locked), tuple(frozenset(avoid.get(slot, [])) for slot in SLOTS))


def generate_meal_plan(recipes: Iterable[dict[str, Any]], options: MealPlanOptions,
                       classification: Classification, request_id: str) -> dict[str, Any]:
    """Enumerate the small catalog once; never relax hard constraints to change a dish."""
    recipes = list(recipes)
    by_id = {recipe["id"]: recipe for recipe in recipes}
    current = dict(zip(SLOTS, options.current_plan)) if options.current_plan else {}
    for slot, recipe_id in current.items():
        if recipe_id not in by_id or classification.categories.get(recipe_id) != slot:
            raise ProtocolError("INVALID_PAYLOAD", "current_plan recipe does not exist or has the wrong category", request_id)

    history = dict(zip(SLOTS, options.avoid_recipe_ids))
    for slot in SLOTS:
        if any(recipe_id not in by_id or classification.categories.get(recipe_id) != slot for recipe_id in history[slot]):
            raise ProtocolError("INVALID_PAYLOAD", "recipe history id does not exist or has the wrong category", request_id)

    result = {"classification_version": classification.version, "algorithm": ALGORITHM,
              "plan": None, "changed_slots": [], "warnings": [], "reason": None}

    def empty(code, message, slots=()):
        return {**result, "warnings": ["NO_COMPLETE_MEAL_PLAN"],
                "reason": {"code": code, "message": message, "slots": list(slots)}}

    pools = {slot: [] for slot in SLOTS}
    for recipe in recipes:
        slot = classification.categories.get(recipe["id"])
        if slot not in pools or set(recipe["all_ids"]) & options.excluded:
            continue
        if options.max_minutes is not None and recipe["minutes"] > options.max_minutes:
            continue
        if slot in options.locked_slots and recipe["id"] != current[slot]:
            continue
        pools[slot].append(recipe)
    incompatible = [slot for slot in SLOTS if slot in options.locked_slots and not pools[slot]]
    if incompatible:
        return empty("LOCKED_RECIPE_INCOMPATIBLE", "Món đã khóa không đáp ứng bộ lọc hiện tại.", incompatible)
    absent = [slot for slot in SLOTS if not pools[slot]]
    if absent:
        return empty("MISSING_CATEGORY", "Không đủ món mặn, rau và canh đáp ứng bộ lọc.", absent)

    best = None
    best_key = None
    for combination in product(*(pools[slot] for slot in SLOTS)):
        recipe_ids = tuple(recipe["id"] for recipe in combination)
        if len(set(recipe_ids)) != 3:
            continue
        changed = [slot for slot, recipe in zip(SLOTS, combination) if current and recipe["id"] != current[slot]]
        if current and not changed:
            continue
        minutes = sum(recipe["minutes"] for recipe in combination)
        if options.max_total_minutes is not None and minutes > options.max_total_minutes:
            continue
        required = set().union(*(recipe["required_ids"] for recipe in combination))
        missing = required - options.selected
        if options.max_missing is not None and len(missing) > options.max_missing:
            continue
        matched = required & options.selected
        per_dish_missing = sum(len(set(recipe["required_ids"]) - options.selected) for recipe in combination)
        # Hard filters always win. Prefer unseen dishes, then changed slots and the existing ranking.
        unseen = sum(recipe["id"] not in history[slot] for slot, recipe in zip(SLOTS, combination) if slot in changed)
        key = (-unseen, -len(changed), len(missing), -len(matched), per_dish_missing, minutes, recipe_ids)
        if best_key is None or key < best_key:
            best_key = key
            best = (combination, changed, required, missing, matched, minutes)
    if best is None:
        return empty("NO_ALTERNATIVE" if current else "CONSTRAINTS_UNSATISFIED",
                     "Không có mâm khác đáp ứng điều kiện; hãy điều chỉnh bộ lọc hoặc món khóa."
                     if current else "Không có mâm đáp ứng giới hạn thời gian và nguyên liệu thiếu.")

    combination, changed, required, missing, matched, minutes = best
    items = []
    for slot, recipe in zip(SLOTS, combination):
        required_ids = set(recipe["required_ids"])
        item_missing = sorted(required_ids - options.selected)
        items.append({"slot": slot, "recipe_id": recipe["id"], "title": recipe["title"],
                      "minutes": recipe["minutes"], "matched_ids": sorted(required_ids & options.selected),
                      "missing_ids": item_missing, "missing_count": len(item_missing)})
    warnings = ["PARTIAL_REGENERATION"] if current and len(changed) < len(SLOTS) - len(options.locked_slots) else []
    if any(recipe["id"] in history[slot] for slot, recipe in zip(SLOTS, combination) if slot in changed):
        warnings.append("HISTORY_RECYCLED")
    return {**result, "changed_slots": changed, "warnings": warnings,
            "plan": {"items": items, "required_ids": sorted(required), "matched_ids": sorted(matched),
                     "missing_ids": sorted(missing), "missing_count": len(missing), "total_minutes": minutes,
                     "time_basis": "sum_of_recipe_minutes"}}


def build_shopping_lists(details: Iterable[dict[str, Any]], selected: frozenset[int]) -> dict[str, Any]:
    """Group actual recipe relations, retaining each quantity string and its requirement."""
    grouped = {}
    for recipe in details:
        for ingredient in recipe["ingredients"]:
            ingredient_id = ingredient["id"]
            if ingredient_id in selected:
                continue
            entry = grouped.setdefault(ingredient_id, {"ingredient_id": ingredient_id,
                                                       "name": ingredient["name"], "uses_by_recipe": {}})
            use = entry["uses_by_recipe"].setdefault(recipe["id"], {"recipe_id": recipe["id"],
                "quantities": [], "is_required": False})
            quantity = ingredient.get("quantity")
            if isinstance(quantity, str) and quantity.strip() and quantity not in use["quantities"]:
                use["quantities"].append(quantity)
            use["is_required"] = use["is_required"] or bool(ingredient["is_required"])
    required, optional = [], []
    for ingredient_id in sorted(grouped):
        entry = grouped[ingredient_id]
        entry["uses"] = [{"recipe_id": use["recipe_id"],
            # Text amounts are not parsed or added; keep multiple lines readable.
            "quantity": " + ".join(use["quantities"]) or None,
            "is_required": use["is_required"]}
            for use in sorted(entry.pop("uses_by_recipe").values(), key=lambda use: use["recipe_id"])]
        (required if any(use["is_required"] for use in entry["uses"]) else optional).append(entry)
    return {"shopping_list": required, "optional_shopping_list": optional,
            "optional_missing_ids": [entry["ingredient_id"] for entry in optional]}
