"""Pure, read-only portion calculator. Inputs are server catalog objects, never HTTP data.

An adapter supplies active public recipe content, base servings, structured lines,
units and scaling modes. Non-v3 adapters retain their review gates; the isolated
unified-v3 adapter marks its Admin-managed catalog as trusted. No legacy quantity
parsing, proposal-file loading, unit conversions or invented defaults.
Quantities use exact fractions internally; nonterminating decimal results are
reported as outward bounds at six decimal places, including after aggregation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
import re
from typing import Mapping

from source.common.protocol import ProtocolError
from source.common.catalog_ids import valid_public_id

MAX_RECIPES = 6
MAX_PEOPLE = 100
MAX_LINES = 50
MAX_ID = 4294967295
_NUMBER = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?\Z")


@dataclass(frozen=True)
class Options:
    recipe_ids: tuple[int, ...]
    people: int


def validate(payload: dict, request_id: str | None = None) -> Options:
    ids, people = payload.get("recipe_ids"), payload.get("people")
    if (set(payload) != {"recipe_ids", "people"} or not isinstance(ids, list)
            or not 1 <= len(ids) <= MAX_RECIPES
            or any(not valid_public_id(i) for i in ids)
            or len(set(ids)) != len(ids) or type(people) is not int
            or not 1 <= people <= MAX_PEOPLE):
        raise ProtocolError("INVALID_PAYLOAD", "expected distinct recipe_ids (1..6) and people (1..100)", request_id)
    return Options(tuple(ids), people)


@dataclass(frozen=True)
class Review:
    status: str = "NEEDS_VERIFICATION"
    decision_ref: str | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True)
class Unit:
    code: str
    dimension: str
    definition: str
    review: Review = Review()


@dataclass(frozen=True)
class IngredientLine:
    line_id: int
    ingredient_id: int | None = None
    name: str | None = None
    ingredient_form: str | None = None
    amount_kind: str = "unknown"
    amount_min: Decimal | str | None = None
    amount_max: Decimal | str | None = None
    unit: str | None = None
    measurement_basis: str | None = None
    purpose: str | None = None
    requirement: str = "required"
    review: Review = Review()  # identity/form, quantity and measurement claims
    scaling_mode: str | None = None
    scaling_review: Review = Review()


@dataclass(frozen=True)
class Revision:
    recipe_id: int  # public recipe identity, explicitly mapped by server adapter
    revision_id: int
    base_servings: Decimal | str | None = None
    serving_basis: str | None = None
    lines: tuple[IngredientLine, ...] = ()  # complete active ingredient set
    content_complete: bool = False
    review: Review = Review()
    servings_review: Review = Review()


@dataclass(frozen=True)
class Allocation:
    revision_id: int
    serving_basis: str
    servings_per_person: Decimal | str


@dataclass(frozen=True)
class PortionPolicy:
    version: str
    allocations: Mapping[int, Allocation]
    review: Review = Review()


@dataclass(frozen=True)
class Catalog:
    revisions: Mapping[int, Revision] = field(default_factory=dict)
    units: Mapping[str, Unit] = field(default_factory=dict)
    portion_policy: PortionPolicy | None = None
    available: bool = True
    unavailable_reason: str | None = None
    trust_admin_catalog: bool = False


MESSAGES = {
    "STRUCTURED_PORTION_DATA_UNAVAILABLE": "Ch\u01b0a \u0111\u1ee7 d\u1eef li\u1ec7u kh\u1ea9u ph\u1ea7n g\u1ed1c, \u0111\u1ecbnh l\u01b0\u1ee3ng s\u1ed1 v\u00e0 \u0111\u01a1n v\u1ecb \u0111\u1ec3 t\u00ednh.",
    "APPROVED_DATA_UNAVAILABLE": "Ch\u01b0a k\u1ebft n\u1ed1i \u0111\u01b0\u1ee3c d\u1eef li\u1ec7u kh\u1ea9u ph\u1ea7n \u0111\u00e3 duy\u1ec7t.",
    "REVISION_NOT_APPROVED": "C\u00f4ng th\u1ee9c ch\u01b0a s\u1eb5n s\u00e0ng \u0111\u1ec3 t\u00ednh kh\u1ea9u ph\u1ea7n.",
    "INVALID_REVISION": "D\u1eef li\u1ec7u c\u00f4ng th\u1ee9c kh\u00f4ng h\u1ee3p l\u1ec7.",
    "SERVINGS_NOT_APPROVED": "Kh\u1ea9u ph\u1ea7n g\u1ed1c ho\u1eb7c c\u01a1 s\u1edf kh\u1ea9u ph\u1ea7n ch\u01b0a h\u1ee3p l\u1ec7.",
    "INVALID_BASE_SERVINGS": "Thi\u1ebfu kh\u1ea9u ph\u1ea7n g\u1ed1c h\u1ee3p l\u1ec7.",
    "INGREDIENTS_INCOMPLETE": "Danh s\u00e1ch nguy\u00ean li\u1ec7u c\u00f2n thi\u1ebfu th\u00e0nh ph\u1ea7n.",
    "PORTION_POLICY_UNAVAILABLE": "Ch\u01b0a c\u00f3 quy t\u1eafc kh\u1ea9u ph\u1ea7n ph\u00f9 h\u1ee3p cho m\u00e2m n\u00e0y.",
    "PORTION_POLICY_MISMATCH": "Quy t\u1eafc kh\u1ea9u ph\u1ea7n kh\u00f4ng kh\u1edbp c\u00f4ng th\u1ee9c.",
    "INVALID_PORTION_ALLOCATION": "Ph\u00e2n b\u1ed5 kh\u1ea9u ph\u1ea7n kh\u00f4ng h\u1ee3p l\u1ec7.",
    "LINE_NOT_APPROVED": "D\u1eef li\u1ec7u d\u00f2ng nguy\u00ean li\u1ec7u ch\u01b0a h\u1ee3p l\u1ec7.",
    "INVALID_INGREDIENT": "M\u00e3 ho\u1eb7c t\u00ean nguy\u00ean li\u1ec7u hay y\u00eau c\u1ea7u th\u00e0nh ph\u1ea7n kh\u00f4ng h\u1ee3p l\u1ec7.",
    "INVALID_PURPOSE": "M\u1ee5c \u0111\u00edch nguy\u00ean li\u1ec7u kh\u00f4ng thu\u1ed9c c\u00e1c gi\u00e1 tr\u1ecb catalog h\u1ed7 tr\u1ee3.",
    "INVALID_MEASUREMENT_BASIS": "C\u01a1 s\u1edf \u0111o kh\u00f4ng thu\u1ed9c c\u00e1c gi\u00e1 tr\u1ecb catalog h\u1ed7 tr\u1ee3.",
    "UNKNOWN_QUANTITY": "Ch\u01b0a c\u00f3 l\u01b0\u1ee3ng s\u1ed1 c\u1ee5 th\u1ec3; kh\u00f4ng t\u1ef1 coi l\u00e0 0.",
    "INVALID_QUANTITY": "L\u01b0\u1ee3ng s\u1ed1 ho\u1eb7c kho\u1ea3ng l\u01b0\u1ee3ng kh\u00f4ng h\u1ee3p l\u1ec7.",
    "UNIT_NOT_APPROVED": "Thi\u1ebfu \u0111\u01a1n v\u1ecb ho\u1eb7c \u0111\u1ecbnh ngh\u0129a \u0111\u01a1n v\u1ecb.",
    "SCALING_NOT_APPROVED": "C\u01a1 s\u1edf t\u00ednh kh\u1ea9u ph\u1ea7n cho d\u00f2ng nguy\u00ean li\u1ec7u ch\u01b0a h\u1ee3p l\u1ec7.",
    "UNSUPPORTED_SCALING": "Ch\u01b0a c\u00f3 c\u00e1ch t\u00ednh kh\u1ea9u ph\u1ea7n ph\u00f9 h\u1ee3p cho d\u00f2ng n\u00e0y.",
    "RESULT_TOO_LARGE": "K\u1ebft qu\u1ea3 v\u01b0\u1ee3t gi\u1edbi h\u1ea1n TCP; h\u00e3y t\u00ednh v\u1edbi m\u00e2m nh\u1ecf h\u01a1n.",
}


def _text(value, limit=80):
    return isinstance(value, str) and 1 <= len(value) <= limit and bool(value.strip())


def _id(value):
    return type(value) is int and 1 <= value <= MAX_ID


def _approved(review):
    return (isinstance(review, Review) and review.status == "APPROVED"
            and _text(review.decision_ref, 255) and _text(review.evidence_ref, 255))


def _accepted(review, catalog: Catalog):
    # Unified v3 is an Admin-managed catalog, not a review/release workflow.
    # Only its TEST_ONLY repository adapter may enable this path.
    return catalog.trust_admin_catalog is True or _approved(review)


def _number(value):
    if isinstance(value, Decimal):
        value = (format(value, "f") if value.is_finite() and value.adjusted() <= 11
                 and value.as_tuple().exponent >= -6 else "")
    if not isinstance(value, str) or not _NUMBER.fullmatch(value):
        return None
    number = Fraction(value)
    return number if number > 0 else None


def _finite_decimal(value: Fraction):
    denominator, twos, fives = value.denominator, 0, 0
    while denominator % 2 == 0:
        denominator //= 2
        twos += 1
    while denominator % 5 == 0:
        denominator //= 5
        fives += 1
    if denominator != 1:
        return None
    places = max(twos, fives)
    digits = str(value.numerator * 2 ** (places - twos) * 5 ** (places - fives))
    if not places:
        return digits
    digits = digits.zfill(places + 1)
    return (digits[:-places] + "." + digits[-places:]).rstrip("0").rstrip(".")


def _quantity(low: Fraction, high: Fraction):
    minimum, maximum = _finite_decimal(low), _finite_decimal(high)
    bounded = minimum is None or maximum is None
    if minimum is None:
        minimum = _finite_decimal(Fraction(low.numerator * 10**6 // low.denominator, 10**6))
    if maximum is None:
        maximum = _finite_decimal(Fraction(-(-high.numerator * 10**6 // high.denominator), 10**6))
    return {"amount_kind": "exact" if minimum == maximum else "range",
            "quantity_value": minimum if minimum == maximum else None,
            "quantity_min": minimum, "quantity_max": maximum,
            "precision": "outward_6dp" if bounded else "exact"}


def _reason(code, line_id=None):
    return {"code": code, "message": MESSAGES[code], "line_id": line_id}


def _recipe(recipe_id):
    return {"recipe_id": recipe_id, "revision_id": None, "status": "INCOMPLETE",
            "base_servings": None, "target_servings": None, "lines": [], "reasons": []}


def unavailable(options: Options, code="APPROVED_DATA_UNAVAILABLE"):
    return {"calculation_version": "portion-v1", "recipe_ids": list(options.recipe_ids),
            "people": options.people, "status": "INCOMPLETE", "totals_complete": False,
            "portion_policy_version": None,
            "recipes": [{**_recipe(i), "reasons": [_reason(code)]} for i in options.recipe_ids],
            "known_ingredients": []}


def calculate(options: Options, catalog: Catalog) -> dict:
    """Return known requirements, not purchases: no stock amount is inferred.

    Unknown/unapproved lines stay in reasons; known totals are explicitly partial.
    Units are merged only by identical approved code; there is no implicit kg/g,
    spoon/ml or piece/gram conversion. No inputs or meal-plan state are mutated.
    """
    if catalog.available is not True:
        return unavailable(options, catalog.unavailable_reason or "APPROVED_DATA_UNAVAILABLE")
    result = unavailable(options)
    result["recipes"] = []
    grouped = {}
    policy = catalog.portion_policy
    policy_ok = (catalog.trust_admin_catalog is True or
                 isinstance(policy, PortionPolicy) and isinstance(policy.allocations, Mapping) and _accepted(policy.review, catalog)
                 and _text(policy.version) and all(_id(k) for k in policy.allocations)
                 and set(policy.allocations) == set(options.recipe_ids))
    if policy_ok:
        result["portion_policy_version"] = policy.version if isinstance(policy, PortionPolicy) else "v3-base-servings"
    for recipe_id in options.recipe_ids:
        item = _recipe(recipe_id)
        result["recipes"].append(item)
        revision = catalog.revisions.get(recipe_id)
        if not isinstance(revision, Revision) or not _accepted(revision.review, catalog):
            item["reasons"].append(_reason("REVISION_NOT_APPROVED"))
            continue
        if (not valid_public_id(revision.recipe_id) or revision.recipe_id != recipe_id or not _id(revision.revision_id)
                or not isinstance(revision.lines, (tuple, list)) or not 1 <= len(revision.lines) <= MAX_LINES
                or any(not isinstance(l, IngredientLine) or not _id(l.line_id) for l in revision.lines)
                or len({l.line_id for l in revision.lines}) != len(revision.lines)):
            item["reasons"].append(_reason("INVALID_REVISION"))
            continue
        item["revision_id"] = revision.revision_id
        if revision.content_complete is not True:
            item["reasons"].append(_reason("INGREDIENTS_INCOMPLETE"))
        if not _accepted(revision.servings_review, catalog) or revision.serving_basis not in {"source_servings", "adult_equivalent"}:
            item["reasons"].append(_reason("SERVINGS_NOT_APPROVED"))
        base = _number(revision.base_servings)
        if base is None:
            item["reasons"].append(_reason("INVALID_BASE_SERVINGS"))
        if not policy_ok:
            item["reasons"].append(_reason("PORTION_POLICY_UNAVAILABLE"))
        elif catalog.trust_admin_catalog is True and policy is None:
            allocation = Allocation(revision.revision_id, revision.serving_basis or "source_servings", "1")
        else:
            allocation = policy.allocations[recipe_id]
            if (not isinstance(allocation, Allocation) or not _id(allocation.revision_id)
                    or allocation.revision_id != revision.revision_id
                    or allocation.serving_basis != revision.serving_basis):
                item["reasons"].append(_reason("PORTION_POLICY_MISMATCH"))
            elif _number(allocation.servings_per_person) is None:
                item["reasons"].append(_reason("INVALID_PORTION_ALLOCATION"))
        # Never scale an incomplete/unapproved recipe basis or a mismatched policy.
        if item["reasons"]:
            continue
        allocation = (policy.allocations[recipe_id] if isinstance(policy, PortionPolicy)
                      else Allocation(revision.revision_id, revision.serving_basis or "source_servings", "1"))
        target = _number(allocation.servings_per_person) * options.people
        item["base_servings"], item["target_servings"] = _finite_decimal(base), _finite_decimal(target)
        for line in revision.lines:
            code = None
            unit = catalog.units.get(line.unit) if isinstance(line.unit, str) else None
            if not _accepted(line.review, catalog):
                code = "LINE_NOT_APPROVED"
            elif (not valid_public_id(line.ingredient_id) or not _text(line.name, 255)
                  or line.requirement not in {"required", "optional", "unknown"}):
                code = "INVALID_INGREDIENT"
            elif line.purpose not in {"main", "seasoning", "cooking_medium", "garnish", "unknown", "consumed"}:
                code = "INVALID_PURPOSE"
            elif line.measurement_basis not in {None, "gross", "edible", "prepared", "unknown"}:
                code = "INVALID_MEASUREMENT_BASIS"
            elif line.amount_kind not in {"exact", "range"}:
                code = "UNKNOWN_QUANTITY"
            elif (not isinstance(unit, Unit) or unit.code != line.unit or not _text(unit.code, 40)
                  or unit.dimension not in {"mass", "volume", "count", "source_defined", "other"}
                  or not _text(unit.definition, 255) or not _accepted(unit.review, catalog)):
                code = "UNIT_NOT_APPROVED"
            elif not _accepted(line.scaling_review, catalog):
                code = "SCALING_NOT_APPROVED"
            elif line.scaling_mode not in {"linear", "fixed"}:
                code = "UNSUPPORTED_SCALING"
            low = _number(line.amount_min)
            high = _number(line.amount_max) if line.amount_max is not None else low
            if code is None and (low is None or high is None or high < low
                                 or line.amount_kind == "exact" and high != low
                                 or line.amount_kind == "range" and line.amount_max is None):
                code = "INVALID_QUANTITY"
            if code:
                item["reasons"].append(_reason(code, line.line_id))
                continue
            multiplier = target / base if line.scaling_mode == "linear" else Fraction(1)
            low, high = low * multiplier, high * multiplier
            quantity = _quantity(low, high)
            item["lines"].append({"line_id": line.line_id, "ingredient_id": line.ingredient_id,
                                  "unit": line.unit, "requirement": line.requirement, **quantity})
            mergeable = (_text(line.ingredient_form, 120)
                         and line.measurement_basis in {"gross", "edible", "prepared"}
                         and line.purpose in {"main", "seasoning", "cooking_medium", "garnish", "consumed"}
                         and line.requirement in {"required", "optional"})
            if mergeable:
                key = ("group", line.ingredient_id, line.ingredient_form, line.measurement_basis,
                       line.purpose, line.unit, line.requirement)
            else:
                # A known amount is still useful on its own. Missing compatibility
                # metadata prevents aggregation, never independent scaling.
                key = ("line", recipe_id, line.line_id)
            group = grouped.setdefault(key, {"ingredient_id": line.ingredient_id, "name": line.name,
                "ingredient_form": line.ingredient_form if _text(line.ingredient_form, 120) else None,
                "measurement_basis": line.measurement_basis if line.measurement_basis in {"gross", "edible", "prepared"} else "unknown",
                "purpose": line.purpose, "unit": line.unit, "requirement": line.requirement,
                "mergeable": bool(mergeable), "low": Fraction(0), "high": Fraction(0), "uses": []})
            group["low"] += low
            group["high"] += high
            # Keep the per-recipe requirement alongside the grouped shopping
            # total. Consumers validate each use against the source line, and
            # optional lines must not be inferred as required by a client.
            group["uses"].append({"recipe_id": recipe_id, "revision_id": revision.revision_id,
                                  "line_id": line.line_id, "requirement": line.requirement, **quantity})
        item["status"] = "INCOMPLETE" if item["reasons"] else "COMPLETE"
    result["known_ingredients"] = [
        {**{k: v for k, v in group.items() if k not in {"low", "high"}},
         **_quantity(group["low"], group["high"])} for group in grouped.values()]
    result["totals_complete"] = all(item["status"] == "COMPLETE" for item in result["recipes"])
    result["status"] = "COMPLETE" if result["totals_complete"] else "INCOMPLETE"
    return result
