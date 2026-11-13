"""Daily-only evidence gate and bounded combo selection. Never writes data."""
from dataclasses import replace
from fractions import Fraction
import re

from source.server.meal_plan_calculation import calculate, daily_meal_capacity, validate


def required_counts(people):
    return {"main": 1 if people <= 3 else 2 if people <= 6 else 3 if people <= 9 else 4 if people <= 11 else 5,
            "vegetable": 1, "soup": 1}


def serving_evidence(revision):
    """Quantity/measurement review alone does not establish recipe servings.

    A dedicated approved servings review, or a matching base_servings claim
    AND a serving-specific source, is required. A recipe-wide verification
    status alone can concern ingredient amounts rather than source servings.
    Legacy imported four-serving defaults fail closed, including notes about
    peer ingredient amounts or input measurement basis.
    """
    if revision is None or revision.serving_basis not in {"source_servings", "adult_equivalent"}:
        return False
    try:
        base = Fraction(str(revision.base_servings))
    except (ValueError, ZeroDivisionError):
        return False
    if base <= 0 or not revision.data_evidence.strip():
        return False
    if revision.data_status not in {"verified", "estimated"}:
        return False
    review = revision.servings_review
    if revision.data_status == "verified" and review.status == "APPROVED" and review.decision_ref and review.evidence_ref:
        return True
    note = revision.data_evidence
    claim = re.search(r"\bbase_servings\s*=\s*(\d+(?:\.\d+)?)\b", note, re.I)
    source = re.search(r"\bservings_source\s*:\s*([^;\n]{12,})", note, re.I)
    return bool(claim and source and Fraction(claim[1]) == base)


def ready(revision, catalog):
    if (not serving_evidence(revision) or not revision.content_complete or not revision.lines
            or any(line.measurement_basis not in {"gross", "edible", "prepared"} for line in revision.lines)):
        return False
    result = calculate(validate({"recipe_ids": [revision.recipe_id], "people": 1}), catalog)
    # A single dish need not be a whole meal. Every ingredient still needs a
    # known quantity/unit/basis; the whole combo is checked separately below.
    return all(not any(reason["code"] != "MEAL_ALLOCATION_UNAVAILABLE" for reason in item["reasons"])
               for item in result["recipes"])


def generate(recipes, options, classification, request_id, metadata, tags, catalog):
    from source.server import meal_plan_v2 as planner
    counts = required_counts(options.people or 4)
    fixed = replace(options, counts=counts)
    revisions = catalog.revisions if catalog and catalog.available and catalog.trust_admin_catalog else {}
    approved = {rid for rid, rev in revisions.items() if ready(rev, catalog)}
    target_payload = {"recipe_ids": [recipes[0]["id"]], "people": options.people or 4}
    if options.adults is not None:
        target_payload.update(adults=options.adults, children=options.children)
    target = validate(target_payload, request_id).equivalent_people if recipes else Fraction(options.people or 4)
    history = set(options.combo_history)
    if options.regenerate and options.current:
        history.add(planner._daily_combo_id(options.current.values()))
    search = {"combos": set(), "complete": True}
    private = [dict(r, portion_ready=r["id"] in approved,
                    service_capacity=str(revisions[r["id"]].base_servings) if r["id"] in approved else None,
                    service_capacity_status=revisions[r["id"]].data_status if r["id"] in approved else "unknown")
               for r in recipes]

    def qualifies(ids):
        if any(rid not in approved for rid in ids):
            return False
        capacities = {}
        for role in planner.SLOTS:
            members = [revisions[rid] for rid in ids if classification.categories.get(rid) == role]
            if not members or len({r.serving_basis for r in members}) != 1:
                return False
            capacities[role] = sum((Fraction(str(r.base_servings)) for r in members), Fraction())
        # Independent main guard prevents vegetables masking a main shortfall.
        # Q is only an experimental screening index, not proof of nutrition.
        q = daily_meal_capacity(capacities)
        if capacities["main"] < target or not target <= q <= target * Fraction(13, 10):
            return False
        search["combos"].add(planner._daily_combo_id(ids))
        return planner._daily_combo_id(ids) not in history

    tags = {rid: dict(values) for rid, values in (tags or {}).items()}
    adjuncts = {"garlic", "onion", "shallot", "scallion", "salt", "sugar", "fish_sauce", "water", "oil", "pepper", "ginger"}
    for r in private:
        t = tags.setdefault(r["id"], {})
        t["main_ingredient"] = (set(t.get("main_ingredient", ())) - adjuncts) | {
            f"ingredient:{iid}" for iid in r.get("daily_prominent_ids", ())}
    result = planner._generate_fixed(private, fixed, classification, request_id, metadata,
        pairing_metadata=tags, _daily_search_state=search,
        _daily_qualification=qualifies, _daily_approved=approved)
    result.update(adaptive_daily=True, daily_selection_policy="qualified-servings-v1", daily_combo_search={"found": len(search["combos"]), "complete": search["complete"]},
        daily_layout_reason="Chỉ đề xuất khi nguồn số suất và định lượng có căn cứ; tổng suất chính ≥ nhu cầu, chỉ số tham khảo toàn mâm trong 100–130% nhu cầu. Không scale công thức. Đây là sàng lọc thử nghiệm, không chứng minh đủ ăn hay đủ dinh dưỡng.")
    if result["plan"]:
        ids = [i["recipe_id"] for i in result["plan"]["items"]]
        check = calculate(validate({**target_payload, "recipe_ids": ids}), catalog)
        if not check["totals_complete"] or check["service_assessment"]["assessment_status"] != "conditional":
            result = planner.no_plan(result, "PORTION_DATA_UNCONFIRMED", "Chưa xác định được combo có định lượng và nguồn số suất phù hợp.")
        else:
            result["daily_combo_id"] = planner._daily_combo_id(ids)
            if options.regenerate:
                pins = {options.current[k] for k in options.locked}
                overlap = len((set(ids) & set(options.current.values())) - pins)
                result["daily_combo_note"] = (f"Combo khác còn trùng {overlap} món chưa ghim trong phạm vi tìm kiếm an toàn." if overlap
                    else "Combo mới không trùng món chưa ghim; nguyên liệu được lấy lại từ công thức gốc.")
    if not result["plan"]:
        if result["reason"]["code"] == "LOCKED_RECIPE_INCOMPATIBLE" and any(
                options.current[key] not in approved for key in options.locked):
            result = planner.no_plan(result, "PINNED_PORTION_UNCONFIRMED",
                "Món ghim chưa có đủ căn cứ số suất/định lượng để xác nhận combo; giữ mâm trước và món ghim.",
                slots=sorted(options.locked), suggestions=["Kiểm tra căn cứ khẩu phần trong Admin hoặc tự bỏ ghim; hệ thống không tự bỏ món ghim."])
        reason = result["reason"]["code"]
        if reason in {"INSUFFICIENT_GROUP", "INSUFFICIENT_CHOICES", "NO_COMPLETE_MEAL_PLAN", "SEARCH_LIMIT_REACHED", "CONSTRAINTS_UNSATISFIED"}:
            result = planner.no_plan(result, "NO_ALTERNATIVE" if history else "PORTION_DATA_UNCONFIRMED",
                "Chưa tìm được combo khác đạt điều kiện trong phạm vi tìm kiếm; giữ mâm trước." if history else
                "Chưa xác định được combo đạt: thiếu nguồn số suất/định lượng đáng tin cậy hoặc khẩu phần không nằm trong ngưỡng cho phép.",
                suggestions=["Admin cần kiểm tra riêng căn cứ số suất gốc; ghi chú ước tính lượng nguyên liệu không xác minh số suất."])
    return result
