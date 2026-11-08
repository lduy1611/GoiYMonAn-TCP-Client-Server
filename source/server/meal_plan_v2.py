"""Flexible meal slots over the approved legacy catalog. No v2 data migration."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
import re
from typing import Any

from source.common.protocol import ProtocolError
from source.common.catalog_ids import valid_public_id
from source.server.meal_plan import Classification, MealPlanOptions, SLOTS, validate_meal_plan
from source.server import meal_preferences

ALGORITHM = "meal-plan-v2"
MAX_PER_GROUP = 2
MAX_ITEMS = 6
LABELS = {"main": "món chính", "vegetable": "món rau", "soup": "món canh"}


def counts_for_people(people):
    if type(people) is not int or not 1 <= people <= 12:
        raise ValueError("people must be an integer from 1 to 12")
    amounts = ((1, 1, 0) if people <= 2 else (1, 1, 1) if people <= 4 else
               (2, 1, 1) if people <= 6 else (2, 2, 1) if people <= 8 else (2, 2, 2))
    return dict(zip(SLOTS, amounts))


def slots_for(counts):
    return tuple(f"{group}:{i}" for group in SLOTS for i in range(1, counts[group] + 1))


@dataclass(frozen=True)
class Options:
    filters: MealPlanOptions
    counts: dict[str, int]
    current: dict[str, int]
    locked: frozenset[str]
    replace: str | None
    history: dict[str, frozenset[int]]
    regenerate: bool
    preferences: dict[str, str]
    people: int | None


def validate(payload: dict[str, Any], request_id: str) -> Options:
    common = {"ingredient_ids", "excluded_ids", "max_minutes", "max_missing"}
    allowed = common | {"max_total_minutes", "counts", "current_plan", "locked_slots", "replace_slot", "avoid_recipe_ids", "action", "preferences", "people"}

    def reject(message):
        raise ProtocolError("INVALID_PAYLOAD", message, request_id)

    def integer(v, low, high):
        return type(v) is int and low <= v <= high

    def slot(v):
        return isinstance(v, str) and re.fullmatch(r"(main|vegetable|soup):[12]", v) is not None

    if not isinstance(payload, dict) or set(payload) - allowed:
        reject("invalid GENERATE_MEAL_PLAN_V2 payload")
    # Reuse v1 filter validation without changing its limits or behavior.
    filters = validate_meal_plan({k: v for k, v in payload.items() if k in common}, request_id)
    total = payload.get("max_total_minutes")
    if total is not None and not integer(total, 1, MAX_ITEMS * 240):
        reject("invalid max_total_minutes")
    from dataclasses import replace
    filters = replace(filters, max_total_minutes=total)
    people = payload.get("people")
    if "people" in payload and not integer(people, 1, 12):
        reject("people must be an integer from 1 to 12")
    counts = payload.get("counts", counts_for_people(people) if people is not None else dict.fromkeys(SLOTS, 1))
    if (not isinstance(counts, dict) or set(counts) != set(SLOTS)
            or not all(integer(n, 0, MAX_PER_GROUP) for n in counts.values())
            or not 1 <= sum(counts.values()) <= MAX_ITEMS):
        reject("counts must contain main, vegetable, soup (0..2), with 1..6 dishes overall")
    if people is not None and counts != counts_for_people(people):
        reject("counts must match the automatic layout for people")
    current = payload.get("current_plan", {})
    if (not isinstance(current, dict) or len(current) > MAX_ITEMS
            or not all(slot(k) and valid_public_id(v) for k, v in current.items())
            or len(set(current.values())) != len(current)
            or any(f"{g}:2" in current and f"{g}:1" not in current for g in SLOTS)):
        reject("current_plan must contain distinct recipes and contiguous valid slots")
    locked = payload.get("locked_slots", [])
    if (not isinstance(locked, list) or len(locked) > MAX_ITEMS
            or not all(slot(k) and k in current for k in locked) or len(set(locked)) != len(locked)):
        reject("locked_slots requires distinct slots in current_plan")
    target = payload.get("replace_slot")
    action = payload.get("action", "generate")
    if action not in ("generate", "regenerate"):
        reject("invalid action")
    if target is not None and (not slot(target) or target not in current or set(current) != set(slots_for(counts))):
        reject("replace_slot requires a current plan matching the requested counts")
    history = payload.get("avoid_recipe_ids", {})
    if (not isinstance(history, dict) or set(history) - set(SLOTS)
            or not all(isinstance(v, list) and len(v) <= 50
                       and all(valid_public_id(i) for i in v)
                       and len(set(v)) == len(v) for v in history.values())
            or sum(map(len, history.values())) > 50 or any(history.values()) and not current):
        reject("invalid recipe history")
    return Options(filters, dict(counts), dict(current), frozenset(locked), target,
                   {g: frozenset(history.get(g, [])) for g in SLOTS}, action == "regenerate",
                   meal_preferences.validate(payload.get("preferences", {}), request_id), people)


def no_plan(result, code, message, *, slots=(), groups=(), suggestions=()):
    return {**result, "plan": None, "changed_slots": [], "warnings": ["NO_COMPLETE_MEAL_PLAN"],
            "reason": {"code": code, "message": message, "slots": list(slots),
                       "groups": list(groups), "suggestions": list(suggestions)}}


def generate(recipes, options: Options, classification: Classification, request_id: str, metadata=None):
    recipes = sorted(recipes, key=lambda r: r["id"])
    by_id = {r["id"]: r for r in recipes}
    f, current = options.filters, options.current
    targets = slots_for(options.counts)
    result = {"algorithm": ALGORITHM, "classification_version": classification.version,
              "counts": options.counts, "plan": None, "changed_slots": [], "warnings": [], "reason": None}
    if options.people is not None:
        result["people"] = options.people
    if options.preferences:
        result.update(preferences=options.preferences, metadata_version=metadata.version if metadata else "unavailable")
        if metadata is None or metadata.unsupported(options.preferences):
            return no_plan(result, "METADATA_UNAVAILABLE", "Chưa đủ dữ liệu đáng tin cậy cho vùng miền, chế độ ăn hoặc dịp đã chọn.",
                           suggestions=["Chọn Không giới hạn cho lựa chọn chưa hỗ trợ; hệ thống không tự bỏ bộ lọc."])
    for key, rid in current.items():
        if rid not in by_id or classification.categories.get(rid) != key.split(":")[0]:
            raise ProtocolError("INVALID_PAYLOAD", "current recipe does not exist or has the wrong group", request_id)
    for group, ids in options.history.items():
        if any(i not in by_id or classification.categories.get(i) != group for i in ids):
            raise ProtocolError("INVALID_PAYLOAD", "recipe history has an unknown id or wrong group", request_id)

    removed = sorted(options.locked - set(targets))
    if removed:
        return no_plan(result, "PINNED_SLOT_REMOVED", "Cấu trúc mới sẽ bỏ vị trí đang ghim.", slots=removed,
                       suggestions=["Tăng lại số người hoặc tự bỏ ghim món ở vị trí bị giảm; mâm hiện tại được giữ nguyên." if options.people is not None else
                                    "Tăng lại số món của nhóm đó hoặc tự bỏ ghim trước khi giảm số món."])
    if options.replace in options.locked:
        return no_plan(result, "PINNED_TARGET", "Món đang ghim không thể được đổi.", slots=[options.replace],
                       suggestions=["Bỏ ghim món này nếu bạn muốn đổi."])
    # Same locking semantics as v1: replacing one slot implicitly locks the others.
    locked = options.locked | (set(current) - {options.replace} if options.replace else set())
    eligible = {g: [] for g in SLOTS}
    needs_vegetarian = options.preferences.get("diet") == "vegetarian"
    for r in recipes:
        group = classification.categories.get(r["id"])
        if needs_vegetarian and r["id"] not in metadata.vegetarian_ids:
            continue
        if any(r["id"] not in metadata.eligible_ids(pref_group, code)
               for pref_group, code in options.preferences.items() if pref_group in ("region", "occasion")):
            continue
        if group in eligible and not set(r["all_ids"]) & f.excluded and (f.max_minutes is None or r["minutes"] <= f.max_minutes):
            eligible[group].append(r["id"])
    incompatible = sorted(k for k in locked if current[k] not in eligible[k.split(":")[0]])
    if incompatible:
        return no_plan(result, "LOCKED_RECIPE_INCOMPATIBLE", "Món cần giữ không đáp ứng bộ lọc hiện tại.", slots=incompatible,
                       suggestions=["Món cần giữ chưa đủ bằng chứng chay hoặc không đáp ứng nguyên liệu/thời gian. Hãy tự bỏ ghim món xung đột hoặc điều chỉnh bộ lọc." if needs_vegetarian else
                                    "Điều chỉnh nguyên liệu loại trừ/thời gian hoặc tự bỏ ghim món xung đột."])
    shortages = [{"group": g, "requested": options.counts[g], "available": len(eligible[g])}
                 for g in SLOTS if len(eligible[g]) < options.counts[g]]
    if shortages:
        detail = "; ".join(f"{LABELS[x['group']]}: cần {x['requested']}, còn {x['available']}" for x in shortages)
        if needs_vegetarian:
            return no_plan(result, "INSUFFICIENT_VEGETARIAN_GROUP", "Không đủ món chay được xác minh: " + detail + ".", groups=shortages,
                           suggestions=["Giảm số người nếu cấu trúc nhỏ hơn đủ món; kiểm tra giới hạn thời gian và nguyên liệu loại trừ.",
                                        "Cần bổ sung/xác minh công thức chay cho nhóm còn thiếu; hệ thống không thay bằng món chưa xác minh."])
        return no_plan(result, "INSUFFICIENT_GROUP", "Không đủ " + detail + ".", groups=shortages,
                       suggestions=["Giảm số người, tăng thời gian mỗi món hoặc kiểm tra nguyên liệu loại trừ." if options.people is not None else
                                    "Giảm số món trong nhóm thiếu, tăng thời gian mỗi món hoặc kiểm tra nguyên liệu loại trừ."])
    if options.regenerate and set(targets) <= locked:
        return no_plan(result, "ALL_LOCKED", "Tất cả món đều đang được giữ; không có vị trí để đổi.", slots=targets,
                       suggestions=["Bỏ ghim ít nhất một món để đổi cả mâm."])

    needs_meat = options.preferences.get("diet") == "non_vegetarian"
    if needs_meat:
        # Candidate feasibility before combination search. Plant side dishes remain eligible.
        reachable = {current[k] for k in locked} | {
            rid for g in SLOTS if options.counts[g] > sum(k.startswith(g + ":") for k in locked)
            for rid in eligible[g]}
        if not reachable & metadata.meat_ids:
            return no_plan(result, "NO_VERIFIED_MEAT", "Không còn món thịt/cá/hải sản có bằng chứng phù hợp với các vị trí và bộ lọc hiện tại.",
                           suggestions=["Tăng số người hoặc thời gian; kiểm tra nguyên liệu loại trừ và món ghim." if options.people is not None else
                                        "Tăng số món chính/canh hoặc thời gian; kiểm tra nguyên liệu loại trừ và món ghim.",
                                        "Bạn có thể tự chọn Không giới hạn chế độ ăn."])

    group_choices = []
    for group in SLOTS:
        keys = [k for k in targets if k.startswith(group + ":")]
        fixed = {k: current[k] for k in keys if k in locked}
        pool = [i for i in eligible[group] if i not in fixed.values()]
        assignments = []
        for combo in combinations(pool, len(keys) - len(fixed)):
            assignment, remaining = dict(fixed), set(combo)
            # Retain surviving recipes in their original slots: reordering is not a change.
            for key in keys:
                if key not in assignment and current.get(key) in remaining:
                    assignment[key] = current[key]
                    remaining.remove(current[key])
            for key, rid in zip((k for k in keys if k not in assignment), sorted(remaining)):
                assignment[key] = rid
            assignments.append(assignment)
        group_choices.append(assignments)

    best, best_key = None, None
    for groups in product(*group_choices):
        assignment = {k: v for group in groups for k, v in group.items()}
        recipe_ids = tuple(assignment[k] for k in targets)
        if len(set(recipe_ids)) != len(recipe_ids):
            continue
        if needs_meat and not set(recipe_ids) & metadata.meat_ids:
            continue
        changed = sorted(k for k in set(current) | set(targets) if current.get(k) != assignment.get(k)) if current else []
        if options.regenerate and current and not changed or options.replace and assignment[options.replace] == current[options.replace]:
            continue
        chosen = [by_id[i] for i in recipe_ids]
        minutes = sum(r["minutes"] for r in chosen)
        if f.max_total_minutes is not None and minutes > f.max_total_minutes:
            continue
        required = set().union(*(set(r["required_ids"]) for r in chosen))
        missing, matched = required - f.selected, required & f.selected
        if f.max_missing is not None and len(missing) > f.max_missing:
            continue
        unseen = sum(assignment[k] not in options.history[k.split(":")[0]] for k in changed if k in assignment)
        key = (-unseen, -len(changed), len(missing), -len(matched),
               sum(len(set(r["required_ids"]) - f.selected) for r in chosen), minutes, recipe_ids)
        if best_key is None or key < best_key:
            best_key = key
            best = (assignment, changed, chosen, required, missing, matched, minutes)
    if best is None:
        if needs_meat:
            return no_plan(result, "PREFERENCES_UNSATISFIED", "Không ghép được mâm có ít nhất một món thịt/cá/hải sản và đồng thời thỏa mọi điều kiện.",
                           suggestions=["Kiểm tra món ghim; tăng giới hạn thời gian/số loại thiếu hoặc điều chỉnh số người." if options.people is not None else
                                        "Kiểm tra món ghim; tăng giới hạn thời gian/số loại thiếu hoặc điều chỉnh số món.",
                                        "Bạn có thể tự chọn Không giới hạn chế độ ăn."])
        return no_plan(result, "NO_ALTERNATIVE" if current else "CONSTRAINTS_UNSATISFIED",
                       "Không có mâm khác thỏa điều kiện." if current else "Không có mâm thỏa tổng thời gian và số loại nguyên liệu thiếu.",
                       suggestions=["Tăng giới hạn tổng thời gian/số loại thiếu, giảm số người hoặc tự điều chỉnh món ghim." if options.people is not None else
                                    "Tăng giới hạn tổng thời gian/số loại thiếu, giảm số món hoặc tự điều chỉnh món ghim."])
    assignment, changed, chosen, required, missing, matched, minutes = best
    warnings = []
    if current and len([k for k in changed if k in targets]) < len(set(targets) - locked):
        warnings.append("PARTIAL_REGENERATION")
    if any(assignment[k] in options.history[k.split(":")[0]] for k in changed if k in assignment):
        warnings.append("HISTORY_RECYCLED")
    items = [{"slot": k, "recipe_id": assignment[k], "title": by_id[assignment[k]]["title"],
              "minutes": by_id[assignment[k]]["minutes"],
              "matched_ids": sorted(set(by_id[assignment[k]]["required_ids"]) & f.selected),
              "missing_ids": sorted(set(by_id[assignment[k]]["required_ids"]) - f.selected),
              "missing_count": len(set(by_id[assignment[k]]["required_ids"]) - f.selected)} for k in targets]
    return {**result, "changed_slots": changed, "warnings": warnings,
            "plan": {"items": items, "required_ids": sorted(required), "matched_ids": sorted(matched),
                     "missing_ids": sorted(missing), "missing_count": len(missing), "total_minutes": minutes,
                     "time_basis": "sum_of_recipe_minutes"}}
