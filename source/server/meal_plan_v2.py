"""Flexible meal slots over the approved legacy catalog. No v2 data migration."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, permutations, product
import re
from typing import Any

from source.common.protocol import ProtocolError
from source.common.catalog_ids import valid_public_id
from source.server.meal_plan import Classification, MealPlanOptions, SLOTS, validate_meal_plan
from source.server import meal_preferences

ALGORITHM = "meal-plan-v2"
MAX_PER_GROUP = 2
MAX_ITEMS = 6
CUSTOM_SEARCH_LIMIT = 100_000
LABELS = {"main": "món chính", "vegetable": "món rau", "soup": "món canh"}


def counts_for_people(people, occasion="daily"):
    if type(people) is not int or not 1 <= people <= 12:
        raise ValueError("people must be an integer from 1 to 12")
    if occasion == "guests":
        main = 3 if people <= 5 else 4  # one appetizer plus two or three mains
        return {"main": main, "vegetable": 1, "soup": int(people >= 4)}
    if occasion == "drinking":
        main = 2 if people <= 3 else 3 if people <= 5 else 4
        sides = 2 if people >= 9 else 1
        return {"main": main, "vegetable": sides, "soup": 0}
    amounts = ((1, 1, 0) if people <= 2 else (1, 1, 1) if people <= 4 else
               (2, 1, 1) if people <= 6 else (2, 2, 1) if people <= 8 else (2, 2, 2))
    return dict(zip(SLOTS, amounts))


def slots_for(counts):
    return tuple(f"{group}:{i}" for group in SLOTS for i in range(1, counts[group] + 1))


def _vectorized_exact_best(compact_choices, options, targets, selected_mask, *, needs_meat):
    """Exact chunk-free branch-and-bound over compact role-combination masks.

    Main/vegetable pairs provide a monotone lower bound for the final missing
    ingredient union. Pair ordering and pruning also respect the higher-priority
    novelty/change terms in the existing lexicographic ranking. Each surviving
    pair evaluates its soup choices with vectorized bit counts.
    """
    try:
        import numpy as np
    except ImportError:
        return None, False
    if not hasattr(np, "bitwise_count"):
        return None, False

    all_masks = [choice[2] for group in compact_choices for choice in group]
    highest = max([selected_mask, *all_masks], default=0).bit_length()
    words = max(1, (highest + 63) // 64)
    word_mask = (1 << 64) - 1
    selected_words = np.asarray([(selected_mask >> (64 * i)) & word_mask for i in range(words)], dtype=np.uint64)

    def arrays(group):
        masks = np.asarray([[(choice[2] >> (64 * i)) & word_mask for i in range(words)]
                            for choice in group], dtype=np.uint64)
        return {
            "missing": np.bitwise_and(masks, np.bitwise_not(selected_words)),
            "matched": np.bitwise_and(masks, selected_words),
            "missing_sum": np.asarray([choice[3] for choice in group], dtype=np.int64),
            "minutes": np.asarray([choice[4] for choice in group], dtype=np.int64),
            "meat": np.asarray([choice[5] for choice in group], dtype=np.bool_),
            "unseen": np.asarray([choice[6] for choice in group], dtype=np.int64),
            "changed": np.asarray([choice[7] for choice in group], dtype=np.int64),
            "replace_same": np.asarray([choice[8] for choice in group], dtype=np.bool_),
        }

    main, veg, soup = (arrays(group) for group in compact_choices)
    main_i = np.repeat(np.arange(len(compact_choices[0]), dtype=np.int32), len(compact_choices[1]))
    veg_i = np.tile(np.arange(len(compact_choices[1]), dtype=np.int32), len(compact_choices[0]))
    if not len(main_i) or not len(compact_choices[2]):
        return None, None
    pair_missing = np.bitwise_or(main["missing"][main_i], veg["missing"][veg_i])
    pair_matched = np.bitwise_or(main["matched"][main_i], veg["matched"][veg_i])
    pair_base_missing = np.bitwise_count(pair_missing).sum(axis=1, dtype=np.int64)
    pair_missing_sum = main["missing_sum"][main_i] + veg["missing_sum"][veg_i]
    pair_minutes = main["minutes"][main_i] + veg["minutes"][veg_i]
    pair_meat = np.logical_or(main["meat"][main_i], veg["meat"][veg_i])
    pair_unseen = main["unseen"][main_i] + veg["unseen"][veg_i]
    pair_changed = main["changed"][main_i] + veg["changed"][veg_i]
    pair_replace_same = np.logical_or(main["replace_same"][main_i], veg["replace_same"][veg_i])
    best_key = None
    best_assignment = None
    order = np.lexsort((pair_base_missing, -pair_changed, -pair_unseen))
    for pair_i in order:
        pair_i = int(pair_i)
        lower_bound = int(pair_base_missing[pair_i])
        if best_key is not None:
            best_unseen, best_changed = -best_key[0], -best_key[1]
            upper_unseen = int(pair_unseen[pair_i]) + int(soup["unseen"].max())
            if upper_unseen < best_unseen:
                # Pairs are sorted by this safe upper bound.
                break
            upper_changed = int(pair_changed[pair_i]) + int(soup["changed"].max())
            if upper_unseen == best_unseen and upper_changed < best_changed:
                continue
            if (upper_unseen == best_unseen and upper_changed == best_changed
                    and lower_bound > best_key[2]):
                continue
        if options.filters.max_missing is not None and lower_bound > options.filters.max_missing:
            continue
        if (options.filters.max_total_minutes is not None
                and pair_minutes[pair_i] + int(soup["minutes"].min()) > options.filters.max_total_minutes):
            continue

        missing_count = np.bitwise_count(np.bitwise_or(pair_missing[pair_i], soup["missing"])).sum(axis=1, dtype=np.int64)
        matched_count = np.bitwise_count(np.bitwise_or(pair_matched[pair_i], soup["matched"])).sum(axis=1, dtype=np.int64)
        minutes = pair_minutes[pair_i] + soup["minutes"]
        missing_sum = pair_missing_sum[pair_i] + soup["missing_sum"]
        unseen = pair_unseen[pair_i] + soup["unseen"]
        changed = pair_changed[pair_i] + soup["changed"]
        feasible = np.ones(len(compact_choices[2]), dtype=np.bool_)
        if options.filters.max_total_minutes is not None:
            feasible &= minutes <= options.filters.max_total_minutes
        if options.filters.max_missing is not None:
            feasible &= missing_count <= options.filters.max_missing
        if needs_meat:
            feasible &= np.logical_or(pair_meat[pair_i], soup["meat"])
        if options.replace:
            feasible &= ~np.logical_or(pair_replace_same[pair_i], soup["replace_same"])
        if options.regenerate and options.current:
            feasible &= changed != 0
        if not feasible.any():
            continue

        if best_key is not None:
            best_unseen, best_changed = -best_key[0], -best_key[1]
            best_missing, best_matched = best_key[2], -best_key[3]
            best_missing_sum, best_minutes = best_key[4], best_key[5]
            equal_unseen = unseen == best_unseen
            equal_changed = changed == best_changed
            equal_missing = missing_count == best_missing
            equal_matched = matched_count == best_matched
            equal_missing_sum = missing_sum == best_missing_sum
            feasible &= (
                (unseen > best_unseen)
                | (equal_unseen & (changed > best_changed))
                | (equal_unseen & equal_changed & (missing_count < best_missing))
                | (equal_unseen & equal_changed & equal_missing & (matched_count > best_matched))
                | (equal_unseen & equal_changed & equal_missing & equal_matched
                   & (missing_sum < best_missing_sum))
                | (equal_unseen & equal_changed & equal_missing & equal_matched
                   & equal_missing_sum & (minutes <= best_minutes))
            )
            if not feasible.any():
                continue

        max_unseen = unseen[feasible].max()
        feasible &= unseen == max_unseen
        max_changed = changed[feasible].max()
        feasible &= changed == max_changed
        min_missing = missing_count[feasible].min()
        feasible &= missing_count == min_missing
        max_matched = matched_count[feasible].max()
        feasible &= matched_count == max_matched
        min_missing_sum = missing_sum[feasible].min()
        feasible &= missing_sum == min_missing_sum
        min_minutes = minutes[feasible].min()
        feasible &= minutes == min_minutes

        main_choice = compact_choices[0][int(main_i[pair_i])]
        vegetable_choice = compact_choices[1][int(veg_i[pair_i])]
        pair_ids = main_choice[0] + vegetable_choice[0]
        for soup_i in np.flatnonzero(feasible):
            recipe_ids = pair_ids + compact_choices[2][int(soup_i)][0]
            key = (-int(max_unseen), -int(max_changed), int(min_missing), -int(max_matched),
                   int(min_missing_sum), int(min_minutes), recipe_ids)
            if best_key is None or key < best_key:
                best_key = key
                best_assignment = dict(zip(targets, recipe_ids))
    return best_key, best_assignment


def _vectorized_chunked_exact_best(compact_choices, options, targets, selected_mask, *, needs_meat,
                                   pair_chunk_size=8192):
    """Exact special-layout search, evaluating role pairs in vectorized chunks.

    A guest/drinking role can have hundreds of thousands of valid first-two-group
    assignments. Evaluating each pair in Python against every soup choice is
    needlessly slow; chunking preserves the same lexicographic objective while
    bounding temporary arrays independently of catalog size.
    """
    try:
        import numpy as np
    except ImportError:
        return None, False
    if not hasattr(np, "bitwise_count"):
        return None, False

    all_masks = [choice[2] for group in compact_choices for choice in group]
    highest = max([selected_mask, *all_masks], default=0).bit_length()
    words = max(1, (highest + 63) // 64)
    word_mask = (1 << 64) - 1
    selected_words = np.asarray([(selected_mask >> (64 * i)) & word_mask for i in range(words)], dtype=np.uint64)

    def arrays(group):
        masks = np.asarray([[(choice[2] >> (64 * i)) & word_mask for i in range(words)]
                            for choice in group], dtype=np.uint64).reshape((len(group), words))
        return {
            "missing": np.bitwise_and(masks, np.bitwise_not(selected_words)),
            "matched": np.bitwise_and(masks, selected_words),
            "missing_sum": np.asarray([choice[3] for choice in group], dtype=np.int64),
            "minutes": np.asarray([choice[4] for choice in group], dtype=np.int64),
            "meat": np.asarray([choice[5] for choice in group], dtype=np.bool_),
            "unseen": np.asarray([choice[6] for choice in group], dtype=np.int64),
            "changed": np.asarray([choice[7] for choice in group], dtype=np.int64),
            "replace_same": np.asarray([choice[8] for choice in group], dtype=np.bool_),
        }

    main, veg, soup = (arrays(group) for group in compact_choices)
    if not len(main["minutes"]) or not len(veg["minutes"]) or not len(soup["minutes"]):
        return None, None
    total_pairs = len(main["minutes"]) * len(veg["minutes"])
    main_i_all = np.repeat(np.arange(len(main["minutes"]), dtype=np.int64), len(veg["minutes"]))
    veg_i_all = np.tile(np.arange(len(veg["minutes"]), dtype=np.int64), len(main["minutes"]))
    group_index = {"main": 0, "vegetable": 1, "soup": 2}
    id_columns = [
        [np.asarray([choice[0][column] for choice in group], dtype=np.int64)
         for column in range(len(group[0][0]))]
        for group in compact_choices
    ]
    best_key = None
    best_assignment = None
    for start in range(0, total_pairs, pair_chunk_size):
        flat = np.arange(start, min(start + pair_chunk_size, total_pairs), dtype=np.int64)
        main_i, veg_i = main_i_all[start:start + len(flat)], veg_i_all[start:start + len(flat)]
        pair_missing = np.bitwise_or(main["missing"][main_i], veg["missing"][veg_i])
        pair_matched = np.bitwise_or(main["matched"][main_i], veg["matched"][veg_i])
        missing = np.bitwise_count(np.bitwise_or(pair_missing[:, None, :], soup["missing"][None, :, :])).sum(axis=2, dtype=np.int64)
        matched = np.bitwise_count(np.bitwise_or(pair_matched[:, None, :], soup["matched"][None, :, :])).sum(axis=2, dtype=np.int64)
        missing_sum = (main["missing_sum"][main_i] + veg["missing_sum"][veg_i])[:, None] + soup["missing_sum"][None, :]
        minutes = (main["minutes"][main_i] + veg["minutes"][veg_i])[:, None] + soup["minutes"][None, :]
        unseen = (main["unseen"][main_i] + veg["unseen"][veg_i])[:, None] + soup["unseen"][None, :]
        changed = (main["changed"][main_i] + veg["changed"][veg_i])[:, None] + soup["changed"][None, :]
        feasible = np.ones(missing.shape, dtype=np.bool_)
        if options.filters.max_missing is not None:
            feasible &= missing <= options.filters.max_missing
        if options.filters.max_total_minutes is not None:
            feasible &= minutes <= options.filters.max_total_minutes
        if needs_meat:
            feasible &= (main["meat"][main_i] | veg["meat"][veg_i])[:, None] | soup["meat"][None, :]
        if options.replace:
            feasible &= ~(main["replace_same"][main_i] | veg["replace_same"][veg_i])[:, None] & ~soup["replace_same"][None, :]
        if options.regenerate and options.current:
            feasible &= changed != 0
        if not feasible.any():
            continue
        unseen_best = unseen[feasible].max(); feasible &= unseen == unseen_best
        changed_best = changed[feasible].max(); feasible &= changed == changed_best
        missing_best = missing[feasible].min(); feasible &= missing == missing_best
        matched_best = matched[feasible].max(); feasible &= matched == matched_best
        missing_sum_best = missing_sum[feasible].min(); feasible &= missing_sum == missing_sum_best
        minutes_best = minutes[feasible].min(); feasible &= minutes == minutes_best
        # Resolve the final recipe-ID tuple tie-break in NumPy. Without this,
        # catalogs with many equal-scoring recipes spend most of their time
        # iterating every tie in Python despite only one candidate winning.
        for target in targets:
            group, index = target.split(":", 1)
            ids = id_columns[group_index[group]][int(index) - 1]
            if group == "main":
                id_matrix = ids[main_i][:, None]
            elif group == "vegetable":
                id_matrix = ids[veg_i][:, None]
            else:
                id_matrix = ids[None, :]
            best_id = np.min(np.where(feasible, id_matrix, np.iinfo(np.int64).max))
            feasible &= id_matrix == best_id
        for pair_i, soup_i in np.argwhere(feasible):
            main_choice = compact_choices[0][int(main_i[pair_i])]
            veg_choice = compact_choices[1][int(veg_i[pair_i])]
            soup_choice = compact_choices[2][int(soup_i)]
            recipe_ids = main_choice[0] + veg_choice[0] + soup_choice[0]
            key = (-int(unseen[pair_i, soup_i]), -int(changed[pair_i, soup_i]),
                   int(missing[pair_i, soup_i]), -int(matched[pair_i, soup_i]),
                   int(missing_sum[pair_i, soup_i]), int(minutes[pair_i, soup_i]), recipe_ids)
            if best_key is None or key < best_key:
                best_key = key
                best_assignment = dict(zip(targets, recipe_ids))
    return best_key, best_assignment


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
    layout_mode: str


def validate(payload: dict[str, Any], request_id: str) -> Options:
    common = {"ingredient_ids", "excluded_ids", "max_minutes", "max_missing"}
    allowed = common | {"max_total_minutes", "counts", "current_plan", "locked_slots", "replace_slot", "avoid_recipe_ids", "action", "preferences", "people", "layout_mode"}

    def reject(message):
        raise ProtocolError("INVALID_PAYLOAD", message, request_id)

    def integer(v, low, high):
        return type(v) is int and low <= v <= high

    def slot(v):
        return isinstance(v, str) and re.fullmatch(r"(main|vegetable|soup):[1-6]", v) is not None

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
    preferences = meal_preferences.validate(payload.get("preferences", {}), request_id)
    occasion = preferences.get("occasion", "daily")
    counts = payload.get("counts", counts_for_people(people, occasion) if people is not None else dict.fromkeys(SLOTS, 1))
    layout_mode = payload.get("layout_mode", "automatic")
    if layout_mode not in ("automatic", "custom"):
        reject("layout_mode must be automatic or custom")
    max_per_group = MAX_ITEMS if layout_mode == "custom" else 4 if occasion in ("guests", "drinking") else MAX_PER_GROUP
    if (not isinstance(counts, dict) or set(counts) != set(SLOTS)
            or not all(integer(n, 0, max_per_group) for n in counts.values())
            or not 1 <= sum(counts.values()) <= MAX_ITEMS):
        reject("counts must contain main, vegetable, soup with 1..6 dishes overall")
    if layout_mode == "automatic" and people is not None and counts != counts_for_people(people, occasion):
        reject("counts must match the automatic layout for people")
    current = payload.get("current_plan", {})
    if (not isinstance(current, dict) or len(current) > MAX_ITEMS
            or not all(slot(k) and valid_public_id(v) for k, v in current.items())
            or len(set(current.values())) != len(current)
            or any(any(f"{g}:{i}" in current and f"{g}:{i-1}" not in current for i in range(2, 7)) for g in SLOTS)):
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
                   preferences, people, layout_mode)


def no_plan(result, code, message, *, slots=(), groups=(), suggestions=()):
    return {**result, "plan": None, "changed_slots": [], "warnings": ["NO_COMPLETE_MEAL_PLAN"],
            "reason": {"code": code, "message": message, "slots": list(slots),
                       "groups": list(groups), "suggestions": list(suggestions)}}


def generate(recipes, options: Options, classification: Classification, request_id: str, metadata=None,
             *, _force_exhaustive: bool = False):
    recipes = sorted(recipes, key=lambda r: r["id"])
    by_id = {r["id"]: r for r in recipes}
    f, current = options.filters, options.current
    targets = slots_for(options.counts)
    result = {"algorithm": ALGORITHM, "classification_version": classification.version,
              "counts": options.counts, "layout_mode": options.layout_mode,
              "plan": None, "changed_slots": [], "warnings": [], "reason": None}
    if options.people is not None:
        result["people"] = options.people
    if options.preferences:
        result.update(preferences=options.preferences, metadata_version=metadata.version if metadata else "unavailable")
        if metadata is None or metadata.unsupported(options.preferences):
            return no_plan(result, "METADATA_UNAVAILABLE", "Chưa đủ dữ liệu đáng tin cậy cho vùng miền, chế độ ăn hoặc dịp đã chọn.",
                           suggestions=["Chọn Không giới hạn cho lựa chọn chưa hỗ trợ; hệ thống không tự bỏ bộ lọc."])
    snack_mode = options.preferences.get("occasion") == "snack"
    occasion = options.preferences.get("occasion", "daily")
    role_layout = occasion if options.layout_mode == "automatic" and occasion in ("guests", "drinking") else None
    snack_ids = (metadata.eligible_ids("occasion", "snack") if snack_mode and metadata else frozenset())
    for _key, rid in current.items():
        # Current slots are transport positions. A previous meal type can have
        # different recipe roles; eligibility below decides whether a locked
        # item may remain, while unpinned items can be replaced safely.
        if rid not in by_id:
            raise ProtocolError("INVALID_PAYLOAD", "current recipe does not exist", request_id)
    for group, ids in options.history.items():
        if any(i not in by_id for i in ids):
            raise ProtocolError("INVALID_PAYLOAD", "recipe history has an unknown id", request_id)

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
        group = "snack" if snack_mode and r["id"] in snack_ids else classification.categories.get(r["id"])
        if needs_vegetarian and r["id"] not in metadata.vegetarian_ids:
            continue
        if any(r["id"] not in metadata.eligible_ids(pref_group, code)
               for pref_group, code in options.preferences.items() if pref_group in ("region", "occasion")):
            continue
        if group == "snack" and not set(r["all_ids"]) & f.excluded and (f.max_minutes is None or r["minutes"] <= f.max_minutes):
            for slot_group in SLOTS:
                eligible[slot_group].append(r["id"])
        elif role_layout == "guests" and group in ("main", "side") and not set(r["all_ids"]) & f.excluded and (f.max_minutes is None or r["minutes"] <= f.max_minutes):
            eligible["main"].append(r["id"])
        elif role_layout == "drinking" and group == "side" and not set(r["all_ids"]) & f.excluded and (f.max_minutes is None or r["minutes"] <= f.max_minutes):
            eligible["vegetable"].append(r["id"])
        elif group in eligible and not set(r["all_ids"]) & f.excluded and (f.max_minutes is None or r["minutes"] <= f.max_minutes):
            eligible[group].append(r["id"])
    if role_layout == "guests":
        # `main` remains the wire slot group. Its first slot is an appetizer;
        # later slots are mains. This keeps TCP framing and response shape stable.
        slot_eligible = {key: (eligible["main"] if key == "main:1" else []) for key in targets}
        slot_eligible.update({key: list(eligible["vegetable"]) for key in targets if key.startswith("vegetable:")})
        slot_eligible.update({key: list(eligible["soup"]) for key in targets if key.startswith("soup:")})
        for key in targets:
            if key.startswith("main:"):
                wanted = "side" if key == "main:1" else "main"
                slot_eligible[key] = [rid["id"] for rid in recipes
                    if classification.categories.get(rid["id"]) == wanted
                    and rid["id"] in eligible["main"]]
    elif role_layout == "drinking":
        slot_eligible = {}
        for key in targets:
            group = key.split(":", 1)[0]
            wanted = "main" if group == "main" else "side" if group == "vegetable" else None
            slot_eligible[key] = ([rid["id"] for rid in recipes
                if classification.categories.get(rid["id"]) == wanted and rid["id"] in eligible.get(group, [])]
                if wanted else [])
    else:
        slot_eligible = {key: list(eligible[key.split(":", 1)[0]]) for key in targets}
    incompatible = sorted(k for k in locked if current[k] not in slot_eligible.get(k, []))
    if incompatible:
        return no_plan(result, "LOCKED_RECIPE_INCOMPATIBLE", "Món cần giữ không đáp ứng bộ lọc hiện tại.", slots=incompatible,
                       suggestions=["Món cần giữ chưa đủ bằng chứng chay hoặc không đáp ứng nguyên liệu/thời gian. Hãy tự bỏ ghim món xung đột hoặc điều chỉnh bộ lọc." if needs_vegetarian else
                                    "Điều chỉnh nguyên liệu loại trừ/thời gian hoặc tự bỏ ghim món xung đột."])
    shortages = []
    for group in SLOTS:
        keys = [key for key in targets if key.startswith(group + ":")]
        if not keys:
            continue
        if role_layout == "guests" and group == "main":
            available = min(1, len(slot_eligible.get("main:1", []))) + min(
                max(0, len(keys) - 1), len(slot_eligible.get("main:2", [])))
        elif role_layout == "drinking" and group == "vegetable":
            available = min(len(keys), len(slot_eligible.get(keys[0], [])))
        else:
            available = len(eligible[group])
        if available < len(keys):
            shortages.append({"group": group, "requested": len(keys), "available": available})
    if shortages:
        if snack_mode:
            available = min((len(eligible[g]) for g in SLOTS), default=0)
            required = sum(options.counts.values())
            return no_plan(result, "INSUFFICIENT_SNACK_CHOICES",
                           f"Không đủ món ăn vặt khác nhau cho cấu trúc này: cần {required}, còn {available} sau khi áp dụng bộ lọc.",
                           groups=shortages,
                           suggestions=["Giảm số người hoặc điều chỉnh nguyên liệu loại trừ/thời gian; hệ thống không thay bằng món chưa gắn nhãn Ăn vặt."])
        detail = "; ".join(f"{LABELS[x['group']]}: cần {x['requested']}, còn {x['available']}" for x in shortages)
        if role_layout == "guests":
            detail += (f". Vai trò cần: 1 khai vị ({len(slot_eligible.get('main:1', []))} có), "
                       f"{max(0, options.counts['main']-1)} món chính "
                       f"({len(slot_eligible.get('main:2', []))} có), 1 rau"
                       + (", 1 canh/lẩu" if options.counts["soup"] else ""))
        elif role_layout == "drinking":
            detail += (f". Vai trò cần: {options.counts['main']} món nhậu "
                       f"({len(slot_eligible.get('main:1', []))} có), "
                       f"{options.counts['vegetable']} món ăn kèm "
                       f"({len(slot_eligible.get('vegetable:1', []))} có)")
        if needs_vegetarian:
            return no_plan(result, "INSUFFICIENT_VEGETARIAN_GROUP", "Không đủ món chay được xác minh: " + detail + ".", groups=shortages,
                           suggestions=["Giảm số người nếu cấu trúc nhỏ hơn đủ món; kiểm tra giới hạn thời gian và nguyên liệu loại trừ.",
                                        "Cần bổ sung/xác minh công thức chay cho nhóm còn thiếu; hệ thống không thay bằng món chưa xác minh."])
        return no_plan(result, "INSUFFICIENT_GROUP", "Không đủ " + detail + ".", groups=shortages,
                       suggestions=["Giảm số món ở nhóm thiếu, tăng giới hạn thời gian hoặc kiểm tra nguyên liệu loại trừ." if options.layout_mode == "custom" else
                                    "Giảm số người, tăng thời gian mỗi món hoặc kiểm tra nguyên liệu loại trừ." if options.people is not None else
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
    if not (options.layout_mode == "custom" and max(options.counts.values()) > MAX_PER_GROUP):
        for group in SLOTS:
            keys = [k for k in targets if k.startswith(group + ":")]
            fixed = {k: current[k] for k in keys if k in locked}
            assignments = []
            if role_layout and not _force_exhaustive:
                # Slots with the same required role are interchangeable for
                # recipe ingredients/minutes. Enumerate candidate *sets* once,
                # then retain the exact best slot assignment for history,
                # changed-slot, replacement, and recipe-ID tie-break terms.
                # This avoids enumerating every permutation in a large guest
                # main group while preserving the exhaustive ranking.
                buckets = {}
                for key in keys:
                    pool_key = tuple(sorted(slot_eligible.get(key, ())))
                    buckets.setdefault(pool_key, []).append(key)
                partials = [dict(fixed)]
                for pool_key, bucket_keys in buckets.items():
                    free_keys = [key for key in bucket_keys if key not in fixed]
                    fixed_ids = {fixed[key] for key in bucket_keys if key in fixed}
                    pool = [rid for rid in pool_key if rid not in fixed_ids]
                    candidates = []
                    for candidate_set in combinations(pool, len(free_keys)):
                        best_mapping = None
                        best_mapping_key = None
                        for ordered_ids in permutations(candidate_set):
                            mapping = dict(zip(free_keys, ordered_ids))
                            if (options.replace in mapping and current.get(options.replace) == mapping[options.replace]):
                                continue
                            changed_count = sum(bool(current) and current.get(key) != rid
                                                for key, rid in mapping.items())
                            unseen_count = sum(bool(current) and current.get(key) != rid
                                               and rid not in options.history[key.split(":")[0]]
                                               for key, rid in mapping.items())
                            mapping_key = (-unseen_count, -changed_count, tuple(ordered_ids))
                            if best_mapping_key is None or mapping_key < best_mapping_key:
                                best_mapping_key = mapping_key
                                best_mapping = mapping
                        if best_mapping is not None:
                            candidates.append(best_mapping)
                    next_partials = []
                    for partial in partials:
                        for candidate in candidates:
                            next_partials.append({**partial, **candidate})
                    partials = next_partials
                    if not partials:
                        break
                assignments = partials
            elif role_layout:
                free_keys = [key for key in keys if key not in fixed]
                def assign_roles(index, assignment, used):
                    if index == len(free_keys):
                        assignments.append(dict(assignment)); return
                    key = free_keys[index]
                    pool = sorted(slot_eligible.get(key, ()))
                    prior = current.get(key)
                    if prior in pool:
                        pool.remove(prior); pool.insert(0, prior)
                    for rid in pool:
                        if rid in used:
                            continue
                        assignment[key] = rid; used.add(rid)
                        assign_roles(index + 1, assignment, used)
                        used.remove(rid); assignment.pop(key, None)
                assign_roles(0, dict(fixed), set(fixed.values()))
            else:
                pool = [i for i in eligible[group] if i not in fixed.values()]
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

    def evaluate(assignment):
        recipe_ids = tuple(assignment[k] for k in targets)
        if len(set(recipe_ids)) != len(recipe_ids):
            return None
        if needs_meat and not set(recipe_ids) & metadata.meat_ids:
            return None
        changed = sorted(k for k in set(current) | set(targets) if current.get(k) != assignment.get(k)) if current else []
        if options.regenerate and current and not changed or options.replace and assignment[options.replace] == current[options.replace]:
            return None
        chosen = [by_id[i] for i in recipe_ids]
        minutes = sum(r["minutes"] for r in chosen)
        if f.max_total_minutes is not None and minutes > f.max_total_minutes:
            return None
        required = set().union(*(set(r["required_ids"]) for r in chosen))
        missing, matched = required - f.selected, required & f.selected
        if f.max_missing is not None and len(missing) > f.max_missing:
            return None
        unseen = sum(assignment[k] not in options.history[k.split(":")[0]] for k in changed if k in assignment)
        key = (-unseen, -len(changed), len(missing), -len(matched),
               sum(len(set(r["required_ids"]) - f.selected) for r in chosen), minutes, recipe_ids)
        return key, (assignment, changed, chosen, required, missing, matched, minutes)

    if options.layout_mode == "custom" and max(options.counts.values()) > MAX_PER_GROUP:
        # Custom layouts can have many combinations. Walk a deterministic, relevance-sorted
        # search space and stop at the first feasible plan; never relax any hard filter.
        candidate_order = {}
        for group in SLOTS:
            candidate_order[group] = sorted(eligible[group], key=lambda rid: (
                0 if current.get(f"{group}:1") == rid else 1,
                0 if rid not in options.history[group] else 1,
                len(set(by_id[rid]["required_ids"]) - f.selected),
                by_id[rid]["minutes"], rid))
        assignment = {}
        chosen_ids = set()
        visited = 0
        exhausted = True
        for key in targets:
            if key in locked:
                assignment[key] = current[key]
                chosen_ids.add(current[key])

        free_targets = [key for key in targets if key not in assignment]

        def visit(index, total_minutes):
            nonlocal visited, exhausted, best
            if index == len(free_targets):
                evaluated = evaluate(dict(assignment))
                if evaluated is not None:
                    best = evaluated[1]
                    exhausted = False
                    return True
                return False
            key = free_targets[index]
            group = key.split(":")[0]
            for rid in candidate_order[group]:
                visited += 1
                if visited > CUSTOM_SEARCH_LIMIT:
                    exhausted = False
                    return False
                if rid in chosen_ids:
                    continue
                next_minutes = total_minutes + by_id[rid]["minutes"]
                if f.max_total_minutes is not None and next_minutes > f.max_total_minutes:
                    continue
                assignment[key] = rid
                chosen_ids.add(rid)
                if visit(index + 1, next_minutes):
                    return True
                chosen_ids.remove(rid)
                assignment.pop(key, None)
            return False

        fixed_minutes = sum(by_id[rid]["minutes"] for rid in chosen_ids)
        visit(0, fixed_minutes)
        if best is None and visited > CUSTOM_SEARCH_LIMIT:
            return no_plan(result, "SEARCH_LIMIT_REACHED", "Không thể xác định mâm trong giới hạn tìm kiếm an toàn.",
                           suggestions=["Giảm số món tùy chọn hoặc nới thời gian/nguyên liệu thiếu; các bộ lọc bắt buộc vẫn được giữ."])
    elif (not _force_exhaustive and snack_mode
          and all(set(eligible[group]) == set(eligible[SLOTS[0]]) for group in SLOTS[1:])):
        # Snack tags intentionally allow the same candidates in every slot.
        # The Cartesian search repeats each selected set in every role
        # permutation (19P6 for the current 12-person catalog). Keep one
        # exact best partial assignment per selected-recipe mask and whether
        # a requested replacement slot changed. For a fixed mask, union
        # ingredients, missing counts, minutes, and meat feasibility are
        # invariant; only the first two ranking terms and the final slot-ID
        # tuple depend on assignment. Those terms are additive by slot, so
        # this DP preserves the exhaustive ranking and all hard constraints.
        pool = sorted(eligible[SLOTS[0]])
        bit_for = {rid: 1 << index for index, rid in enumerate(pool)}
        # state: (recipe mask, replacement changed) -> (unseen, changed, IDs)
        states = {(0, False): (0, 0, ())}
        for key in targets:
            group = key.split(":", 1)[0]
            candidates = [current[key]] if key in locked else pool
            next_states = {}
            for (mask, replacement_changed), (unseen, changed_count, chosen) in states.items():
                for rid in candidates:
                    bit = bit_for[rid]
                    if mask & bit:
                        continue
                    slot_changed = bool(current) and current.get(key) != rid
                    candidate = (unseen + int(slot_changed and rid not in options.history[group]),
                                 changed_count + int(slot_changed), chosen + (rid,))
                    new_key = (mask | bit, replacement_changed or bool(options.replace == key and slot_changed))
                    previous = next_states.get(new_key)
                    if previous is None or (-candidate[0], -candidate[1], candidate[2]) < (-previous[0], -previous[1], previous[2]):
                        next_states[new_key] = candidate
            states = next_states
            if not states:
                break
        for (_mask, replacement_changed), (_unseen, _changed, recipe_ids) in states.items():
            if options.replace and not replacement_changed:
                continue
            assignment = dict(zip(targets, recipe_ids))
            evaluated = evaluate(assignment)
            if evaluated is not None and (best_key is None or evaluated[0] < best_key):
                best_key, best = evaluated
    elif not _force_exhaustive:
        # Preserve the exact exhaustive ranking for a new plan while making the
        # common no-current case cheap enough for larger public catalogs.  The
        # old evaluator rebuilt several Python sets for every Cartesian
        # assignment; compact ingredient bitsets retain the same objective and
        # hard filters without changing B0/P1 or meal-plan selection semantics.
        all_ingredient_ids = set(f.selected)
        for r in recipes:
            all_ingredient_ids.update(r["required_ids"])
        ingredient_index = {ingredient_id: index for index, ingredient_id in enumerate(sorted(all_ingredient_ids))}
        selected_mask = 0
        for ingredient_id in f.selected:
            selected_mask |= 1 << ingredient_index[ingredient_id]
        required_masks = {}
        missing_masks = {}
        for r in recipes:
            mask = 0
            for ingredient_id in r["required_ids"]:
                mask |= 1 << ingredient_index[ingredient_id]
            required_masks[r["id"]] = mask
            missing_masks[r["id"]] = mask & ~selected_mask

        # Materialize compact per-role combinations once. Then merge the first
        # two role groups by exact ingredient-mask state. Recipe pairs with the
        # same union can be collapsed to a Pareto frontier over missing-line
        # count and minutes; the final recipe-ID tie-break remains explicit.
        recipe_bit = {rid: 1 << index for index, rid in enumerate(sorted(by_id))}
        meat_ids = metadata.meat_ids if needs_meat else frozenset()
        group_pools = [set(eligible[group]) for group in SLOTS]
        cross_role_ids = any(group_pools[a] & group_pools[b]
                             for a in range(len(group_pools)) for b in range(a + 1, len(group_pools)))
        compact_choices = []
        for group, assignments in zip(SLOTS, group_choices):
            group_keys = [key for key in targets if key.startswith(group + ":")]
            compact = []
            group_current = {key: value for key, value in current.items()
                             if key.startswith(group + ":")}
            for assignment in assignments:
                ids = tuple(assignment[key] for key in group_keys)
                id_mask = 0
                required_mask = 0
                missing_sum = 0
                minutes = 0
                has_meat = False
                for rid in ids:
                    id_mask |= recipe_bit[rid]
                    required_mask |= required_masks[rid]
                    missing_sum += missing_masks[rid].bit_count()
                    minutes += by_id[rid]["minutes"]
                    has_meat = has_meat or rid in meat_ids
                changes = (sum(group_current.get(key) != assignment.get(key)
                               for key in set(group_current) | set(group_keys)) if current else 0)
                unseen = (sum(assignment[key] not in options.history[group]
                              for key in group_keys if current and group_current.get(key) != assignment[key]))
                replace_same = bool(options.replace and options.replace in assignment
                                    and assignment[options.replace] == current[options.replace])
                compact.append((ids, id_mask, required_mask, missing_sum, minutes, has_meat,
                                unseen, changes, replace_same))
            compact_choices.append(compact)

        main_choices, vegetable_choices, soup_choices = compact_choices

        if not cross_role_ids:
            exact_search = (_vectorized_chunked_exact_best if role_layout
                            else _vectorized_exact_best)
            best_key, best_assignment = exact_search(
                compact_choices, options, targets, selected_mask, needs_meat=needs_meat)
            if best_assignment is not False and best_assignment is not None:
                best = evaluate(best_assignment)[1]
            elif best_assignment is False:
                # NumPy 2's vector bit-count is an optimization, not a runtime
                # requirement. Keep exact behavior on older deployments.
                for groups in product(*group_choices):
                    assignment = {k: v for group in groups for k, v in group.items()}
                    evaluated = evaluate(assignment)
                    if evaluated is not None and (best_key is None or evaluated[0] < best_key):
                        best_key, best = evaluated
        else:
            # Snack candidates may be eligible in multiple role pools. Keep the
            # original exhaustive distinct-ID check for this overlapping case.
            for groups in product(*group_choices):
                assignment = {k: v for group in groups for k, v in group.items()}
                evaluated = evaluate(assignment)
                if evaluated is not None and (best_key is None or evaluated[0] < best_key):
                    best_key, best = evaluated
    else:
        for groups in product(*group_choices):
            assignment = {k: v for group in groups for k, v in group.items()}
            evaluated = evaluate(assignment)
            if evaluated is not None and (best_key is None or evaluated[0] < best_key):
                best_key, best = evaluated
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
