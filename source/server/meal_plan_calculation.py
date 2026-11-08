"""Pure, read-only portion calculator. Inputs are server catalog objects, never HTTP data.

An adapter must supply an approved active revision, its complete ingredient set,
approved units and a revision-bound portion policy for the exact selected meal.
No legacy quantity parsing, proposal-file loading, unit conversions or defaults.
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


MESSAGES = {
    "APPROVED_DATA_UNAVAILABLE": "Chưa kết nối kho revision và định lượng đã duyệt; không dùng dữ liệu đề xuất hoặc lượng legacy.",
    "REVISION_NOT_APPROVED": "Chưa có revision được duyệt kèm bằng chứng.",
    "INVALID_REVISION": "Revision không khớp món hoặc có cấu trúc không hợp lệ.",
    "SERVINGS_NOT_APPROVED": "Khẩu phần gốc hoặc cơ sở khẩu phần chưa được duyệt.",
    "INVALID_BASE_SERVINGS": "Khẩu phần gốc thiếu hoặc không hợp lệ.",
    "INGREDIENTS_INCOMPLETE": "Bộ thành phần của revision chưa được xác nhận đầy đủ.",
    "PORTION_POLICY_UNAVAILABLE": "Chưa có quy tắc khẩu phần/phân bổ được duyệt cho đúng bộ món.",
    "PORTION_POLICY_MISMATCH": "Quy tắc khẩu phần không khớp revision hoặc cơ sở khẩu phần.",
    "INVALID_PORTION_ALLOCATION": "Khẩu phần phân bổ cho món thiếu hoặc không hợp lệ.",
    "LINE_NOT_APPROVED": "Danh tính, dạng hoặc định lượng dòng nguyên liệu chưa được duyệt.",
    "INVALID_INGREDIENT": "Danh tính, dạng, cơ sở đo hoặc mục đích sử dụng còn thiếu.",
    "UNKNOWN_QUANTITY": "Lượng chưa có số hoặc chỉ ghi nêm/tùy nhu cầu; không coi bằng 0.",
    "INVALID_QUANTITY": "Lượng số hoặc khoảng lượng không hợp lệ.",
    "UNIT_NOT_APPROVED": "Đơn vị thiếu định nghĩa hoặc chưa được duyệt.",
    "SCALING_NOT_APPROVED": "Chưa có quy tắc tăng lượng được duyệt cho dòng nguyên liệu.",
    "UNSUPPORTED_SCALING": "Quy tắc tăng lượng này chưa được hỗ trợ.",
    "RESULT_TOO_LARGE": "Kết quả vượt giới hạn frame TCP; giảm số món để tính lại.",
}


def _text(value, limit=80):
    return isinstance(value, str) and 1 <= len(value) <= limit and bool(value.strip())


def _id(value):
    return type(value) is int and 1 <= value <= MAX_ID


def _approved(review):
    return (isinstance(review, Review) and review.status == "APPROVED"
            and _text(review.decision_ref, 255) and _text(review.evidence_ref, 255))


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
        return unavailable(options)
    result = unavailable(options)
    result["recipes"] = []
    grouped = {}
    policy = catalog.portion_policy
    policy_ok = (isinstance(policy, PortionPolicy) and isinstance(policy.allocations, Mapping) and _approved(policy.review)
                 and _text(policy.version) and all(_id(k) for k in policy.allocations)
                 and set(policy.allocations) == set(options.recipe_ids))
    if policy_ok:
        result["portion_policy_version"] = policy.version
    for recipe_id in options.recipe_ids:
        item = _recipe(recipe_id)
        result["recipes"].append(item)
        revision = catalog.revisions.get(recipe_id)
        if not isinstance(revision, Revision) or not _approved(revision.review):
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
        if not _approved(revision.servings_review) or revision.serving_basis not in {"source_servings", "adult_equivalent"}:
            item["reasons"].append(_reason("SERVINGS_NOT_APPROVED"))
        base = _number(revision.base_servings)
        if base is None:
            item["reasons"].append(_reason("INVALID_BASE_SERVINGS"))
        if not policy_ok:
            item["reasons"].append(_reason("PORTION_POLICY_UNAVAILABLE"))
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
        target = _number(policy.allocations[recipe_id].servings_per_person) * options.people
        item["base_servings"], item["target_servings"] = _finite_decimal(base), _finite_decimal(target)
        for line in revision.lines:
            code = None
            unit = catalog.units.get(line.unit) if isinstance(line.unit, str) else None
            if not _approved(line.review):
                code = "LINE_NOT_APPROVED"
            elif (not _id(line.ingredient_id) or not _text(line.name, 255) or not _text(line.ingredient_form)
                  or line.measurement_basis not in {"gross", "edible", "prepared"}
                  or line.purpose not in {"consumed", "cooking_medium", "garnish"}):
                code = "INVALID_INGREDIENT"
            elif line.amount_kind not in {"exact", "range"}:
                code = "UNKNOWN_QUANTITY"
            elif (not isinstance(unit, Unit) or unit.code != line.unit or not _text(unit.code, 40)
                  or unit.dimension not in {"mass", "volume", "count", "source_defined"}
                  or not _text(unit.definition, 255) or not _approved(unit.review)):
                code = "UNIT_NOT_APPROVED"
            elif not _approved(line.scaling_review):
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
                                  "unit": line.unit, **quantity})
            key = (line.ingredient_id, line.ingredient_form, line.measurement_basis, line.purpose, line.unit)
            group = grouped.setdefault(key, {"ingredient_id": line.ingredient_id, "name": line.name,
                "ingredient_form": line.ingredient_form, "measurement_basis": line.measurement_basis,
                "purpose": line.purpose, "unit": line.unit, "low": Fraction(0), "high": Fraction(0), "uses": []})
            group["low"] += low
            group["high"] += high
            group["uses"].append({"recipe_id": recipe_id, "revision_id": revision.revision_id,
                                  "line_id": line.line_id, **quantity})
        item["status"] = "INCOMPLETE" if item["reasons"] else "COMPLETE"
    result["known_ingredients"] = [
        {**{k: v for k, v in group.items() if k not in {"low", "high"}},
         **_quantity(group["low"], group["high"])} for group in grouped.values()]
    result["totals_complete"] = all(item["status"] == "COMPLETE" for item in result["recipes"])
    result["status"] = "COMPLETE" if result["totals_complete"] else "INCOMPLETE"
    return result
