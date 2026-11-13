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
import os
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
    adults: int
    children: int
    occasion: str
    child_equivalent: Fraction
    layout_mode: str = "automatic"

    @property
    def equivalent_people(self):
        return Fraction(self.adults) + self.child_equivalent * self.children


def validate(payload: dict, request_id: str | None = None) -> Options:
    allowed = {"recipe_ids", "people", "adults", "children", "occasion", "layout_mode"}
    ids, people = payload.get("recipe_ids"), payload.get("people")
    adults, children = payload.get("adults"), payload.get("children")
    occasion = payload.get("occasion", "daily")
    counts_supplied = "adults" in payload or "children" in payload
    if (payload.get("layout_mode", "automatic") not in {"automatic", "custom"} or set(payload) - allowed or not {"recipe_ids", "people"} <= set(payload) or not isinstance(ids, list)
            or not 1 <= len(ids) <= (7 if occasion == "daily" and payload.get("layout_mode", "automatic") == "automatic" else MAX_RECIPES)
            or any(not valid_public_id(i) for i in ids)
            or len(set(ids)) != len(ids) or type(people) is not int
            or not 1 <= people <= MAX_PEOPLE
            or counts_supplied and (type(adults) is not int or type(children) is not int
                                    or adults < 0 or children < 0 or adults + children != people)
            or not isinstance(occasion, str) or occasion not in {"daily", "weekend", "guests", "drinking", "snack"}):
        raise ProtocolError("INVALID_PAYLOAD", "invalid recipe, people, adult/child counts, or occasion", request_id)
    if not counts_supplied:
        adults, children = people, 0
    raw_factor = os.getenv("MEAL_CHILD_EQUIVALENT", "0.6").strip()
    try:
        factor = Fraction(raw_factor)
    except (ValueError, ZeroDivisionError):
        factor = Fraction(0)
    if not 0 < factor <= 1:
        raise ProtocolError("PORTION_CONFIG_INVALID", "MEAL_CHILD_EQUIVALENT must be greater than 0 and at most 1", request_id)
    return Options(tuple(ids), people, adults, children, occasion, factor, payload.get("layout_mode", "automatic"))


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
    role: str = "main"
    data_status: str = "needs_review"
    data_evidence: str = ""


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
MESSAGES["MEAL_ALLOCATION_UNAVAILABLE"] = (
    "Ch\u01b0a \u0111\u1ee7 \u0111\u1ecbnh l\u01b0\u1ee3ng nguy\u00ean li\u1ec7u ch\u00ednh "
    "\u0111\u1ec3 ph\u00e2n b\u1ed5 t\u1ed5ng l\u01b0\u1ee3ng cho nh\u00f3m m\u00f3n n\u00e0y.")

# Trial references per adult-equivalent for the whole meal, never per recipe.
# Values are adjustable assumptions for product testing, not nutrition advice.
TRIAL_POLICY_VERSION = "meal-v3-trial-1"
TRIAL_REFERENCES = {
    "daily": {
        "main": ("M\u00f3n ch\u00ednh / \u0111\u1ea1m", "150", "g", "mass", "gross"),
        "vegetable": ("Rau", "180", "g", "mass", "gross"),
        "starch": ("Tinh b\u1ed9t", "90", "g", "mass", "gross"),
        "soup": ("N\u01b0\u1edbc canh / l\u1ea9u", "250", "ml", "volume", "gross"),
        "side": ("M\u00f3n \u0103n k\u00e8m", "80", "g", "mass", "gross"),
        "drink": ("\u0110\u1ed3 u\u1ed1ng", "250", "ml", "volume", "prepared"),
    },
    "guests": {
        "main": ("M\u00f3n ch\u00ednh / \u0111\u1ea1m", "180", "g", "mass", "gross"),
        "vegetable": ("Rau", "180", "g", "mass", "gross"),
        "starch": ("Tinh b\u1ed9t", "100", "g", "mass", "gross"),
        "soup": ("N\u01b0\u1edbc canh / l\u1ea9u", "300", "ml", "volume", "gross"),
        "side": ("M\u00f3n \u0103n k\u00e8m", "100", "g", "mass", "gross"),
        "drink": ("\u0110\u1ed3 u\u1ed1ng", "250", "ml", "volume", "prepared"),
    },
    "drinking": {
        "main": ("M\u00f3n ch\u00ednh / \u0111\u1ea1m", "220", "g", "mass", "gross"),
        "vegetable": ("Rau", "100", "g", "mass", "gross"),
        "starch": ("Tinh b\u1ed9t", "40", "g", "mass", "gross"),
        "soup": ("N\u01b0\u1edbc canh / l\u1ea9u", "0", "ml", "volume", "gross"),
        "side": ("M\u00f3n chia s\u1ebb / \u0103n k\u00e8m", "180", "g", "mass", "gross"),
        "drink": ("\u0110\u1ed3 u\u1ed1ng", "350", "ml", "volume", "prepared"),
    },
}
_SAFE_UNIT_FACTORS = {"g": ("g", Fraction(1)), "kg": ("g", Fraction(1000)),
                      "ml": ("ml", Fraction(1)), "l": ("ml", Fraction(1000))}


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


def _display_decimal(value: Fraction):
    exact = _finite_decimal(value)
    if exact is not None:
        return exact
    scaled = -(-value.numerator * 10**6 // value.denominator)
    return _finite_decimal(Fraction(scaled, 10**6))


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


def _policy_note(options: Options):
    return (f"Định mức thử nghiệm; trẻ em tính k={_finite_decimal(options.child_equivalent)} suất tương đương "
            "mỗi trẻ. Đây là giả định cấu hình được, không phải khuyến nghị dinh dưỡng.")


def _recipe(recipe_id):
    return {"recipe_id": recipe_id, "revision_id": None, "status": "INCOMPLETE",
            "base_servings": None, "target_servings": None, "lines": [], "reasons": []}


def unavailable(options: Options, code="APPROVED_DATA_UNAVAILABLE"):
    return {**({"layout_mode":"automatic"} if len(options.recipe_ids) > MAX_RECIPES else {}),
            "calculation_version": "portion-v1", "recipe_ids": list(options.recipe_ids),
            "people": options.people, "adults": options.adults, "children": options.children,
            "child_equivalent": _finite_decimal(options.child_equivalent),
            "equivalent_people": _finite_decimal(options.equivalent_people), "occasion": options.occasion,
            "status": "INCOMPLETE", "totals_complete": False,
            "portion_policy_version": None,
            "recipes": [{**_recipe(i), "reasons": [_reason(code)]} for i in options.recipe_ids],
            "known_ingredients": [], "portion_groups": [], "policy_note": _policy_note(options)}


# Experimental meal contributions, not nutrition or conversions between food units.
DAILY_CONTRIBUTIONS = {"main": Fraction(55, 100), "vegetable": Fraction(30, 100), "soup": Fraction(15, 100)}


def daily_meal_capacity(capacities):
    return sum((Fraction(str(value)) * DAILY_CONTRIBUTIONS.get(role, 0)
                for role, value in capacities.items() if value is not None), Fraction(0))


def daily_service_verdict(groups, target, capacity, quantities_complete=True):
    """Describe uncertainty; the experimental weighted index is not people fed."""
    by_role = {g["role"]: g for g in groups}
    limitations = []
    if capacity is None or not quantities_complete:
        return "unknown", ["Thiếu số suất hoặc định lượng đáng tin cậy để đánh giá cả mâm."]
    for role, label in (("main", "Món chính"), ("vegetable", "Món rau"), ("soup", "Canh")):
        value = by_role.get(role, {}).get("source_capacity")
        if value is None:
            limitations.append(f"{label}: chưa xác định được đóng góp.")
        elif Fraction(value) < target:
            limitations.append(f"{label} có số suất gốc thấp hơn nhu cầu; cần chia phần nhỏ hơn.")
    main = by_role.get("main", {}).get("source_capacity")
    if capacity < target or main is None or Fraction(main) < target:
        return "risk", limitations
    if capacity > target * Fraction(13, 10):
        return "surplus", limitations
    return "conditional", limitations


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
    result["portion_groups"] = []
    grouped = {}
    policy = catalog.portion_policy
    policy_ok = (catalog.trust_admin_catalog is True or
                 isinstance(policy, PortionPolicy) and isinstance(policy.allocations, Mapping) and _accepted(policy.review, catalog)
                 and _text(policy.version) and all(_id(k) for k in policy.allocations)
                 and set(policy.allocations) == set(options.recipe_ids))
    if policy_ok:
        result["portion_policy_version"] = TRIAL_POLICY_VERSION if catalog.trust_admin_catalog else (policy.version if isinstance(policy, PortionPolicy) else "v3-base-servings")
    trusted = catalog.trust_admin_catalog is True
    factors = {}
    group_results = []
    if trusted:
        occasion = {"weekend": "daily", "snack": "drinking"}.get(options.occasion, options.occasion)
        by_role = {}
        for recipe_id in options.recipe_ids:
            revision = catalog.revisions.get(recipe_id)
            if isinstance(revision, Revision):
                by_role.setdefault(revision.role, []).append((recipe_id, revision))
        if occasion == "daily":
            service_groups = []
            labels = {"main":"M\u00f3n ch\u00ednh", "vegetable":"M\u00f3n rau", "soup":"Canh/L\u1ea9u",
                      "side":"M\u00f3n \u0103n k\u00e8m", "starch":"Tinh b\u1ed9t", "other":"Nh\u00f3m m\u00f3n kh\u00e1c"}
            for role, members in by_role.items():
                capacities = []
                valid = True
                for recipe_id, revision in members:
                    base = _number(revision.base_servings)
                    if (base is None or revision.data_status not in {"verified", "estimated"}
                            or revision.serving_basis not in {"source_servings", "adult_equivalent"}):
                        valid = False
                        break
                    capacities.append((recipe_id, revision, base))
                valid = valid and len({revision.serving_basis for _, revision in members}) == 1
                source_capacity = sum((base for _, _, base in capacities), Fraction(0)) if valid else None
                scale = ((options.equivalent_people / source_capacity if options.layout_mode == "custom" else Fraction(1)) if source_capacity else None)
                status = ("unknown" if scale is None else
                          "estimated" if any(revision.data_status == "estimated" for _, revision, _ in capacities)
                          else "verified")
                recipe_capacity = []
                for recipe_id, revision in members:
                    base = _number(revision.base_servings)
                    if scale is None or base is None:
                        factors[recipe_id] = Fraction(1)
                        base_ok = (base is not None and revision.data_status in {"verified", "estimated"}
                                   and revision.serving_basis in {"source_servings", "adult_equivalent"})
                        recipe_capacity.append({"recipe_id":recipe_id,
                            "source_servings":_finite_decimal(base) if base_ok else None,
                            "target_servings":None,
                            "status":revision.data_status if base_ok else "unknown"})
                    else:
                        factors[recipe_id] = scale
                        recipe_capacity.append({"recipe_id":recipe_id,
                            "source_servings":_finite_decimal(base),
                            "target_servings":_display_decimal(base*scale),
                            "status":revision.data_status})
                service_groups.append({"role":role, "label":labels.get(role,"Nh\u00f3m m\u00f3n kh\u00e1c"),
                    "requested_servings":_finite_decimal(options.equivalent_people),
                    "source_capacity":_finite_decimal(source_capacity) if source_capacity is not None else None,
                    "adjustment_factor":_display_decimal(scale) if scale is not None else None,
                    "status":status, "recipes":recipe_capacity})
            meal_known = all(g["source_capacity"] is not None and g["role"] in DAILY_CONTRIBUTIONS for g in service_groups)
            meal_capacity = daily_meal_capacity({g["role"]:g["source_capacity"] for g in service_groups}) if meal_known else None
            result["service_assessment"]={"method":"source_servings_by_role",
                "requested_servings":_finite_decimal(options.equivalent_people),
                "meal_capacity":_finite_decimal(meal_capacity) if meal_capacity is not None and options.layout_mode != "custom" else None,
                "groups":service_groups,
                "note":'Quy uoc thu nghiem: chinh 55%, rau 30%, canh 15% cua mot bua; quy doi suat goc theo vai tro, khong cong truc tiep cac nhom. Khong phai danh gia du dinh duong; khong suy ra gam thanh pham khi thieu hao hut.'}
            result["portion_policy_version"]="daily-source-servings-v1"
        else:
            references = TRIAL_REFERENCES[occasion]
            by_role = {}
            for recipe_id in options.recipe_ids:
                revision = catalog.revisions.get(recipe_id)
                if isinstance(revision, Revision): by_role.setdefault(revision.role, []).append((recipe_id, revision))
            for role, members in by_role.items():
                if role not in references:
                    for recipe_id, _ in members: factors[recipe_id] = None
                    group_results.append({"role": role, "label": "Nhóm món chưa có định mức",
                        "target": None, "unit": "g", "measurement_basis": "gross", "status": "INCOMPLETE",
                        "reason": "Chưa có định mức thử nghiệm cho nhóm món này."})
                    continue
                label, ref_amount, target_unit, dimension, basis = references[role]
                drivers = []
                reason = None
                for recipe_id, revision in members:
                    base = _number(revision.base_servings)
                    if base is None: reason = "Thiếu số suất gốc."; break
                    if revision.content_complete is not True: reason = "Danh sách nguyên liệu chưa đầy đủ."; break
                    if role == "soup":
                        # A soup's measured broth is a separate volume budget. Solid
                        # ingredients stay in that recipe and share its scaling factor.
                        lines = [line for line in revision.lines
                                 if line.purpose == "main"
                                 and line.requirement == "required" and line.unit in {"ml", "l"}]
                    else:
                        lines = [line for line in revision.lines if line.purpose == "main" and line.requirement == "required"]
                    if not lines: reason = "Không có nguyên liệu chính bắt buộc được xác định."; break
                    for line in lines:
                        unit = line.unit
                        unit_record = catalog.units.get(unit) if isinstance(unit, str) else None
                        if (line.amount_kind != "exact" or line.measurement_basis != basis
                            or line.scaling_mode != "linear" or unit not in _SAFE_UNIT_FACTORS
                            or _SAFE_UNIT_FACTORS[unit][0] != target_unit
                            or not isinstance(unit_record, Unit) or unit_record.dimension != dimension):
                            reason = "Nguyên liệu chính thiếu định lượng/đơn vị/cơ sở đo tương thích."; break
                        amount = _number(line.amount_min)
                        if amount is None or _number(line.amount_max) not in {None, amount}:
                            reason = "Định lượng nguyên liệu chính không phải số chính xác."; break
                        drivers.append((recipe_id, line, base, amount * _SAFE_UNIT_FACTORS[unit][1]))
                    if reason: break
                baseline = sum((amount / base for _, _, base, amount in drivers), Fraction(0))
                if reason or not drivers or baseline <= 0 or Fraction(ref_amount) == 0:
                    for recipe_id, _ in members: factors[recipe_id] = None
                    group_results.append({"role": role, "label": label, "target": "0" if Fraction(ref_amount)==0 else None,
                        "unit": target_unit, "measurement_basis": basis, "status": "INCOMPLETE",
                        "reason": reason or "Không có định lượng chính đủ căn cứ."})
                    continue
                target = Fraction(ref_amount) * options.equivalent_people
                shared_factor = target / baseline
                for recipe_id, revision in members:
                    base = _number(revision.base_servings)
                    factors[recipe_id] = shared_factor / base
                q = _quantity(target, target)
                group_results.append({"role": role, "label": label, "target": q["quantity_value"], "unit": target_unit,
                    "measurement_basis": basis, "status": "COMPLETE", "reason": None})
            result["portion_groups"] = group_results
            result["portion_policy_version"] = TRIAL_POLICY_VERSION
    for recipe_id in options.recipe_ids:
        item = _recipe(recipe_id)
        revision = catalog.revisions.get(recipe_id)
        if revision is not None:
            item["data_status"] = revision.data_status
            item["data_evidence"] = revision.data_evidence
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
        if trusted and recipe_id in factors and factors[recipe_id] is None and not item["reasons"]:
            item["reasons"].append(_reason("MEAL_ALLOCATION_UNAVAILABLE"))
        # Never scale an incomplete/unapproved recipe basis or a mismatched policy.
        if item["reasons"]:
            continue
        allocation = (policy.allocations[recipe_id] if isinstance(policy, PortionPolicy)
                      else Allocation(revision.revision_id, revision.serving_basis or "source_servings", "1"))
        target = (_number(allocation.servings_per_person) * options.people if not trusted
                  else base * factors.get(recipe_id, Fraction(1)))
        if trusted and factors.get(recipe_id) is None:
            item["reasons"].append(_reason("MEAL_ALLOCATION_UNAVAILABLE"))
            continue
        item["base_servings"], item["target_servings"] = _finite_decimal(base), _display_decimal(target)
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
        if trusted and occasion == "daily" and options.layout_mode != "custom":
            if meal_capacity is None or meal_capacity < options.equivalent_people:
                item["reasons"].append(_reason("MEAL_ALLOCATION_UNAVAILABLE"))
        item["status"] = "INCOMPLETE" if item["reasons"] else "COMPLETE"
    result["known_ingredients"] = [
        {**{k: v for k, v in group.items() if k not in {"low", "high"}},
         **_quantity(group["low"], group["high"])} for group in grouped.values()]
    result["totals_complete"] = all(item["status"] == "COMPLETE" for item in result["recipes"])
    result["status"] = "COMPLETE" if result["totals_complete"] else "INCOMPLETE"
    if trusted and occasion == "daily" and options.layout_mode != "custom":
        assessment = result["service_assessment"]
        # Ingredient completeness and meal suitability are separate assessments.
        quantities_complete = all(not any(r["code"] != "MEAL_ALLOCATION_UNAVAILABLE"
            for r in item["reasons"]) for item in result["recipes"])
        verdict, limitations = daily_service_verdict(assessment["groups"], options.equivalent_people,
            Fraction(assessment["meal_capacity"]) if assessment["meal_capacity"] is not None else None,
            quantities_complete)
        assessment.update(assessment_status=verdict, limitations=limitations)
        assessment["note"] = "Chỉ số thử nghiệm = 55% suất chính + 30% suất rau + 15% suất canh. Phần rau nhiều có thể nâng chỉ số dù món chính hoặc canh ít. Đây không phải số người chắc chắn ăn đủ hay đánh giá dinh dưỡng."
    result["adults"], result["children"] = options.adults, options.children
    result["child_equivalent"] = _finite_decimal(options.child_equivalent)
    result["equivalent_people"] = _finite_decimal(options.equivalent_people)
    result["occasion"] = options.occasion
    result["policy_note"] = ("Gi? nguy?n m?t c?ng th?c m?i m?n; thi?u s?c ph?c v? th? c?n th?m ho?c thay m?n." if trusted and occasion == "daily" and options.layout_mode != "custom" else _policy_note(options))
    return result
