"""Flexible meal slots over the approved legacy catalog. No v2 data migration."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from itertools import combinations, permutations, product
from math import comb
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
CUSTOM_LAYOUT_SEARCH_LIMIT = 10_000
DAILY_LAYOUT_SEARCH_LIMIT = 600
MAX_DAILY_COMBO_HISTORY = 1700
MAX_DAILY_COMBO_CANDIDATES = 256
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


def _vectorized_exact_best(compact_choices, options, targets, selected_mask, *, needs_meat, use_pantry=True):
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
            "missing": (np.bitwise_and(masks, np.bitwise_not(selected_words)) if use_pantry else np.zeros_like(masks)),
            "matched": (np.bitwise_and(masks, selected_words) if use_pantry else np.zeros_like(masks)),
            "missing_sum": np.asarray([choice[3] if use_pantry else 0 for choice in group], dtype=np.int64),
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


def _vectorized_chunked_exact_best(compact_choices, options, targets, selected_mask, *, needs_meat, use_pantry=True,
                                   pair_chunk_size=512):
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
            "missing": (np.bitwise_and(masks, np.bitwise_not(selected_words)) if use_pantry else np.zeros_like(masks)),
            "matched": (np.bitwise_and(masks, selected_words) if use_pantry else np.zeros_like(masks)),
            "missing_count": (np.bitwise_count(np.bitwise_and(masks, np.bitwise_not(selected_words)))
                              .sum(axis=1, dtype=np.int64) if use_pantry else np.zeros(len(group), dtype=np.int64)),
            "matched_count": (np.bitwise_count(np.bitwise_and(masks, selected_words))
                              .sum(axis=1, dtype=np.int64) if use_pantry else np.zeros(len(group), dtype=np.int64)),
            "missing_sum": np.asarray([choice[3] if use_pantry else 0 for choice in group], dtype=np.int64),
            "minutes": np.asarray([choice[4] for choice in group], dtype=np.int64),
            "meat": np.asarray([choice[5] for choice in group], dtype=np.bool_),
            "unseen": np.asarray([choice[6] for choice in group], dtype=np.int64),
            "changed": np.asarray([choice[7] for choice in group], dtype=np.int64),
            "portion_ready": np.asarray([choice[11] for choice in group], dtype=np.int64),
            "replace_same": np.asarray([choice[8] for choice in group], dtype=np.bool_),
            "primary_counts": np.asarray([choice[9] for choice in group], dtype=np.int64).reshape(
                (len(group), len(group[0][9]))),
            "method_counts": np.asarray([choice[10] for choice in group], dtype=np.int64).reshape(
                (len(group), len(group[0][10]))),
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
        pair_primary = main["primary_counts"][main_i] + veg["primary_counts"][veg_i]
        pair_methods = main["method_counts"][main_i] + veg["method_counts"][veg_i]
        # Once a feasible best plan exists, discard role pairs that cannot
        # beat it even with the most favorable soup candidate.  These are
        # conservative lexicographic lower/upper bounds; every potentially
        # better assignment still reaches the exact evaluator below.
        if best_key is not None and len(main_i):
            keep = np.ones(len(main_i), dtype=np.bool_)
            pair_unseen_bound = main["unseen"][main_i] + veg["unseen"][veg_i] + int(soup["unseen"].max())
            keep &= pair_unseen_bound >= -best_key[0]
            equal_unseen = pair_unseen_bound == -best_key[0]
            pair_changed_bound = main["changed"][main_i] + veg["changed"][veg_i] + int(soup["changed"].max())
            keep &= ~equal_unseen | (pair_changed_bound >= -best_key[1])
            equal_changed = equal_unseen & (pair_changed_bound == -best_key[1])
            pair_primary_lower = np.maximum(pair_primary - 1, 0).sum(axis=1, dtype=np.int64)
            keep &= ~equal_changed | (pair_primary_lower <= best_key[2])
            equal_primary = equal_changed & (pair_primary_lower == best_key[2])
            pair_method_lower = np.maximum(pair_methods - 1, 0).sum(axis=1, dtype=np.int64)
            keep &= ~equal_primary | (pair_method_lower <= best_key[3])
            equal_method = equal_primary & (pair_method_lower == best_key[3])
            pair_portion_upper = main["portion_ready"][main_i] + veg["portion_ready"][veg_i] + int(soup["portion_ready"].max())
            keep &= ~equal_method | (pair_portion_upper >= -best_key[4])
            equal_portion = equal_method & (pair_portion_upper == -best_key[4])
            if use_pantry:
                pair_missing_count = np.bitwise_count(pair_missing).sum(axis=1, dtype=np.int64)
                min_soup_missing = int(soup["missing_count"].min())
                missing_lower = np.maximum(pair_missing_count, min_soup_missing)
                keep &= ~equal_portion | (missing_lower <= best_key[5])
                equal_missing = equal_portion & (missing_lower == best_key[5])
                pair_matched_count = np.bitwise_count(pair_matched).sum(axis=1, dtype=np.int64)
                matched_upper = pair_matched_count + int(soup["matched_count"].max())
                keep &= ~equal_missing | (matched_upper >= -best_key[6])
                equal_matched = equal_missing & (matched_upper == -best_key[6])
                pair_missing_sum = main["missing_sum"][main_i] + veg["missing_sum"][veg_i]
                missing_sum_lower = pair_missing_sum + int(soup["missing_sum"].min())
                keep &= ~equal_matched | (missing_sum_lower <= best_key[7])
                equal_missing_sum = equal_matched & (missing_sum_lower == best_key[7])
                pair_minutes_lower = main["minutes"][main_i] + veg["minutes"][veg_i] + int(soup["minutes"].min())
                keep &= ~equal_missing_sum | (pair_minutes_lower <= best_key[8])
            else:
                pair_minutes_lower = main["minutes"][main_i] + veg["minutes"][veg_i] + int(soup["minutes"].min())
                keep &= ~equal_portion | (pair_minutes_lower <= best_key[8])
            if not keep.any():
                continue
            main_i, veg_i = main_i[keep], veg_i[keep]
            pair_missing, pair_matched = pair_missing[keep], pair_matched[keep]
            pair_primary, pair_methods = pair_primary[keep], pair_methods[keep]
        primary_repeats = np.maximum(pair_primary[:, None, :] + soup["primary_counts"][None, :, :] - 1, 0).sum(axis=2, dtype=np.int64)
        method_repeats = np.maximum(pair_methods[:, None, :] + soup["method_counts"][None, :, :] - 1, 0).sum(axis=2, dtype=np.int64)
        missing = np.bitwise_count(np.bitwise_or(pair_missing[:, None, :], soup["missing"][None, :, :])).sum(axis=2, dtype=np.int64)
        matched = np.bitwise_count(np.bitwise_or(pair_matched[:, None, :], soup["matched"][None, :, :])).sum(axis=2, dtype=np.int64)
        missing_sum = (main["missing_sum"][main_i] + veg["missing_sum"][veg_i])[:, None] + soup["missing_sum"][None, :]
        minutes = (main["minutes"][main_i] + veg["minutes"][veg_i])[:, None] + soup["minutes"][None, :]
        unseen = (main["unseen"][main_i] + veg["unseen"][veg_i])[:, None] + soup["unseen"][None, :]
        changed = (main["changed"][main_i] + veg["changed"][veg_i])[:, None] + soup["changed"][None, :]
        portion_ready = (main["portion_ready"][main_i] + veg["portion_ready"][veg_i])[:, None] + soup["portion_ready"][None, :]
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
        primary_best = primary_repeats[feasible].min(); feasible &= primary_repeats == primary_best
        method_best = method_repeats[feasible].min(); feasible &= method_repeats == method_best
        portion_ready_best = portion_ready[feasible].max(); feasible &= portion_ready == portion_ready_best
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
                   int(primary_repeats[pair_i, soup_i]), int(method_repeats[pair_i, soup_i]),
                   -int(portion_ready[pair_i, soup_i]),
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
    weather: str | None = None
    adaptive_daily: bool = False
    adults: int | None = None
    children: int | None = None
    combo_history: frozenset[str] = frozenset()
    season: str = 'ALL'


def validate(payload: dict[str, Any], request_id: str) -> Options:
    common = {"ingredient_ids", "excluded_ids", "max_minutes", "max_missing"}
    allowed = common | {"max_total_minutes", "counts", "current_plan", "locked_slots", "replace_slot", "avoid_recipe_ids", "combo_history", "action", "preferences", "people", "layout_mode", "weather", "adaptive_daily", "adults", "children", "season"}

    def reject(message):
        raise ProtocolError("INVALID_PAYLOAD", message, request_id)

    def integer(v, low, high):
        return type(v) is int and low <= v <= high

    def slot(v):
        return isinstance(v, str) and re.fullmatch(r"(main|vegetable|soup):[1-6]", v) is not None

    if not isinstance(payload, dict) or set(payload) - allowed:
        reject("invalid GENERATE_MEAL_PLAN_V2 payload")
    weather = payload.get("weather")
    if weather is not None and weather not in ("hot", "cold", "rain", "sunny"):
        reject("invalid weather preference")
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
    adults, children = payload.get("adults"), payload.get("children")
    if ("adults" in payload or "children" in payload) and (
            not integer(adults, 0, 12) or not integer(children, 0, 12) or adults + children != people):
        reject("adult and child counts must add up to people")
    preferences = meal_preferences.validate(payload.get("preferences", {}), request_id)
    occasion = preferences.get("occasion", "daily")
    if occasion in ("guests", "drinking"):
        # These modes deliberately ignore pantry fit; exclusions remain active.
        filters = replace(filters, max_missing=None)
    counts = payload.get("counts", counts_for_people(people, occasion) if people is not None else dict.fromkeys(SLOTS, 1))
    layout_mode = payload.get("layout_mode", "automatic")
    adaptive_daily = payload.get("adaptive_daily", False)
    if type(adaptive_daily) is not bool or adaptive_daily and (layout_mode != "automatic" or occasion != "daily"):
        reject("adaptive_daily is supported only for automatic daily meals")
    from source.server.daily_seasons import SEASONS
    season = payload.get('season', 'ALL')
    if not isinstance(season, str) or season not in SEASONS:
        reject('invalid season; expected ALL, SPRING, SUMMER, AUTUMN or WINTER')
    if season != 'ALL' and not adaptive_daily:
        reject('season preference is supported only for automatic daily meals')
    if layout_mode not in ("automatic", "custom"):
        reject("layout_mode must be automatic or custom")
    max_items = 7 if adaptive_daily else MAX_ITEMS
    max_per_group = MAX_ITEMS if layout_mode == "custom" else 5 if adaptive_daily else 4 if occasion in ("guests", "drinking") else MAX_PER_GROUP
    if (not isinstance(counts, dict) or set(counts) != set(SLOTS)
            or not all(integer(n, 0, max_per_group) for n in counts.values())
            or not 1 <= sum(counts.values()) <= max_items):
        reject("counts must contain main, vegetable, soup with 1..6 dishes overall")
    if layout_mode == "automatic" and people is not None and not adaptive_daily and counts != counts_for_people(people, occasion):
        reject("counts must match the automatic layout for people")
    current = payload.get("current_plan", {})
    # A twelve-person Daily result has seven source slots. Other modes may
    # receive that previous state while still requesting at most six dishes.
    # This is transport compatibility, never permission to select seven in
    # Custom. The core retains/report conflicts for pins in removed slots.
    daily_previous = isinstance(current, dict) and set(current) == {
        *(f'main:{i}' for i in range(1,6)), 'vegetable:1', 'soup:1'}
    current_limit = 7 if daily_previous else max_items
    if (not isinstance(current, dict) or len(current) > current_limit
            or not all(slot(k) and valid_public_id(v) for k, v in current.items())
            or len(set(current.values())) != len(current)
            or any(any(f"{g}:{i}" in current and f"{g}:{i-1}" not in current for i in range(2, 7)) for g in SLOTS)):
        reject("current_plan must contain distinct recipes and contiguous valid slots")
    locked = payload.get("locked_slots", [])
    if (not isinstance(locked, list) or len(locked) > current_limit
            or not all(slot(k) and k in current for k in locked) or len(set(locked)) != len(locked)):
        reject("locked_slots requires distinct slots in current_plan")
    target = payload.get("replace_slot")
    action = payload.get("action", "generate")
    if action not in ("generate", "regenerate"):
        reject("invalid action")
    if target is not None and (not slot(target) or target not in current or (not adaptive_daily and set(current) != set(slots_for(counts)))):
        reject("replace_slot requires a current plan matching the requested counts")
    history = payload.get("avoid_recipe_ids", {})
    if (not isinstance(history, dict) or set(history) - set(SLOTS)
            or not all(isinstance(v, list) and len(v) <= 50
                       and all(valid_public_id(i) for i in v)
                       and len(set(v)) == len(v) for v in history.values())
            or sum(map(len, history.values())) > 50 or any(history.values()) and not current):
        reject("invalid recipe history")
    combo_history = payload.get("combo_history", [])
    if (not adaptive_daily and combo_history
            or not isinstance(combo_history, list) or len(combo_history) > MAX_DAILY_COMBO_HISTORY
            or any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{32}", value) is None
                   for value in combo_history)
            or len(set(combo_history)) != len(combo_history)):
        reject("invalid daily combo history")
    return Options(filters, dict(counts), dict(current), frozenset(locked), target,
                   {g: frozenset(history.get(g, [])) for g in SLOTS}, action == "regenerate",
                   preferences, people, layout_mode, weather, adaptive_daily, adults, children,
                   frozenset(combo_history), season)


def no_plan(result, code, message, *, slots=(), groups=(), suggestions=()):
    return {**result, "plan": None, "changed_slots": [], "warnings": ["NO_COMPLETE_MEAL_PLAN"],
            "reason": {"code": code, "message": message, "slots": list(slots),
                       "groups": list(groups), "suggestions": list(suggestions)}}


def _daily_combo_id(recipe_ids):
    identity = ",".join(str(recipe_id) for recipe_id in sorted(recipe_ids))
    return sha256(identity.encode("ascii")).hexdigest()[:32]


def _daily_rotation_score(recipe_ids, options):
    combo_id = _daily_combo_id(recipe_ids)
    current_id = _daily_combo_id(options.current.values()) if options.current else None
    pinned_ids = {options.current[slot] for slot in options.locked}
    previous_unpinned = set(options.current.values()) - pinned_ids
    return (int(combo_id in options.combo_history or combo_id == current_id),
            int(combo_id == current_id), len(set(recipe_ids) & previous_unpinned))


def _daily_result_rank(recipe_ids, recipes_by_id, target, classification, pairing_metadata, options):
    quality = _daily_selection_quality(
        [recipes_by_id[recipe_id] for recipe_id in recipe_ids],
        target, classification, pairing_metadata)
    if options.regenerate and options.current:
        return (*_daily_suitability_band(quality, target), *_daily_rotation_score(recipe_ids, options), *quality)
    return (*_daily_suitability_band(quality, target), *quality)


def _daily_suitability_band(quality, target):
    # Rotation may trade a small surplus for variety, never an adequate meal
    # for an unknown/short meal merely to replace more recipes.
    excess = quality[7] if quality[7] > Fraction(str(target))*Fraction(3,10) else 0
    return (*quality[:3], excess, int(quality[3] > 0))


def _generate_fixed(recipes, options: Options, classification: Classification, request_id: str, metadata=None,
             *, pairing_metadata=None, _force_exhaustive: bool = False, _daily_search_state=None,
             _daily_legacy_layout=False, _daily_qualification=None, _daily_approved=None,
             _daily_rank=None, _daily_order=None, _daily_partial_ok=None, _daily_limit=None):
    from source.server.meal_context import weather_score
    daily_limit = _daily_limit or DAILY_LAYOUT_SEARCH_LIMIT
    recipes = [dict(r, context_priority=100*int(bool(r.get("portion_ready", False))) +
                    weather_score((pairing_metadata or {}).get(r["id"], {}), options.weather)[0])
               for r in sorted(recipes, key=lambda r: r["id"])]
    by_id = {r["id"]: r for r in recipes}
    f, current = options.filters, options.current
    pairing_metadata = pairing_metadata or {}
    targets = slots_for(options.counts)
    result = {"algorithm": ALGORITHM, "classification_version": classification.version,
              "counts": options.counts, "layout_mode": options.layout_mode,
              "plan": None, "changed_slots": [], "warnings": [], "reason": None}
    if options.weather is not None:
        result["weather"] = options.weather
    if options.people is not None:
        result["people"] = options.people
    if options.preferences:
        result.update(preferences=options.preferences, metadata_version=metadata.version if metadata else "unavailable")
        if metadata is None or metadata.unsupported(options.preferences):
            return no_plan(result, "METADATA_UNAVAILABLE", "Chưa đủ dữ liệu đáng tin cậy cho vùng miền, chế độ ăn hoặc dịp đã chọn.",
                           suggestions=["Chọn Không giới hạn cho lựa chọn chưa hỗ trợ; hệ thống không tự bỏ bộ lọc."])
    snack_mode = options.preferences.get("occasion") == "snack"
    occasion = options.preferences.get("occasion", "daily")
    service_target = (_daily_equivalent_target(options, recipes)
                      if options.adaptive_daily and occasion == "daily" and not _daily_legacy_layout else None)
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
        if _daily_approved is not None and r["id"] not in _daily_approved:
            continue
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
    if _daily_search_state is not None:
        _daily_search_state['eligible_ids'] = {key:tuple(ids) for key,ids in slot_eligible.items()}
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
    use_pantry = occasion not in ("guests", "drinking")
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

    if (_daily_qualification is None and service_target is not None and _daily_search_state is not None and options.regenerate
            and set(current) == set(targets)
            and all(current[key] in slot_eligible.get(key, ()) for key in targets)):
        current_recipes = [by_id[current[key]] for key in targets]
        current_required = set().union(*(set(recipe["required_ids"]) for recipe in current_recipes))
        current_minutes = sum(recipe["minutes"] for recipe in current_recipes)
        current_is_meat_eligible = not needs_meat or bool(set(current.values()) & metadata.meat_ids)
        if (current_is_meat_eligible
                and (f.max_total_minutes is None or current_minutes <= f.max_total_minutes)
                and (f.max_missing is None or len(current_required - f.selected) <= f.max_missing)):
            _daily_search_state["combos"].add(_daily_combo_id(current.values()))

    large_role_search = False
    if role_layout and not _force_exhaustive:
        estimated_role_assignments = 1
        for group in SLOTS:
            keys = [key for key in targets if key.startswith(group + ":")]
            fixed = {key: current[key] for key in keys if key in locked}
            buckets = {}
            for key in keys:
                if key in fixed:
                    continue
                pool_key = tuple(sorted(slot_eligible.get(key, ())))
                buckets.setdefault(pool_key, []).append(key)
            for pool_key, bucket_keys in buckets.items():
                available = len(set(pool_key) - set(fixed.values()))
                needed = len(bucket_keys)
                if available < needed:
                    estimated_role_assignments = 0
                    break
                estimated_role_assignments *= comb(available, needed)
                if estimated_role_assignments > 100_000:
                    break
            if estimated_role_assignments > 100_000 or estimated_role_assignments == 0:
                break
        large_role_search = estimated_role_assignments > 100_000
    if service_target is not None and not _force_exhaustive:
        # Adaptive layouts must use bounded search before materializing combinations.
        large_role_search = True

    group_choices = []
    if (not large_role_search
            and not (options.layout_mode == "custom" and max(options.counts.values()) > MAX_PER_GROUP)):
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
        if (_daily_legacy_layout and options.regenerate and current
                and set(recipe_ids) == set(current.values())):
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
        if _daily_qualification is not None and not _daily_qualification(recipe_ids):
            return None
        if _daily_qualification is None and service_target is not None and _daily_search_state is not None:
            _daily_search_state["combos"].add(_daily_combo_id(recipe_ids))
        unseen = sum(assignment[k] not in options.history[k.split(":")[0]] for k in changed if k in assignment)
        occasion = options.preferences.get("occasion", "daily")
        # Guest and drinking plans do not optimize against the pantry selection;
        # excluded ingredients and explicit dietary/role constraints remain hard.
        pantry_fit = occasion not in ("guests", "drinking")
        primary_codes = [code for rid in recipe_ids
                         for code in pairing_metadata.get(rid, {}).get("main_ingredient", ())]
        method_codes = [code for rid in recipe_ids
                        for code in pairing_metadata.get(rid, {}).get("cooking_method", ())]
        primary_repeats = len(primary_codes) - len(set(primary_codes))
        method_repeats = len(method_codes) - len(set(method_codes))
        portion_ready_count = sum(r["context_priority"] for r in chosen)
        daily_capacity_error = 0.0
        if service_target is not None and recipe_ids:
            by_capacity_role = {group: [] for group in SLOTS}
            for recipe in chosen:
                role = classification.categories.get(recipe["id"])
                if role in by_capacity_role:
                    try:
                        value = float(recipe.get("service_capacity")) if recipe.get("service_capacity_status") in ("verified", "estimated") else None
                    except (TypeError, ValueError):
                        value = None
                    by_capacity_role[role].append(value if value is not None and value > 0 else None)
            from source.server.meal_plan_calculation import daily_meal_capacity
            capacity = float(daily_meal_capacity({g:sum(v for v in values if v is not None) for g, values in by_capacity_role.items()}))
            unknown = sum(v is None for values in by_capacity_role.values() for v in values)
            daily_capacity_error = max(0.0, service_target-capacity)*10 + max(0.0, capacity-service_target) + unknown*service_target*2
        key = (-unseen, -len(changed), primary_repeats, method_repeats, -portion_ready_count,
               daily_capacity_error,
               len(missing) if pantry_fit else 0, -len(matched) if pantry_fit else 0,
               sum(len(set(r["required_ids"]) - f.selected) for r in chosen) if pantry_fit else 0,
               minutes, recipe_ids)
        if _daily_rank is not None:
            key = (*_daily_rank(recipe_ids), *key)
        elif _daily_qualification is not None:
            from source.server.meal_plan_calculation import daily_meal_capacity
            totals = {g:sum(float(by_id[rid]["service_capacity"]) for rid in recipe_ids if classification.categories.get(rid) == g) for g in SLOTS}
            pins = {current[k] for k in locked}
            overlap = len((set(recipe_ids) & set(current.values())) - pins) if options.regenerate else 0
            key = (overlap, abs(float(daily_meal_capacity(totals))-service_target), primary_repeats, method_repeats, -portion_ready_count, len(missing), minutes, recipe_ids)
        elif service_target is not None:
            key = (*_daily_result_rank(recipe_ids, by_id, service_target, classification,
                                       pairing_metadata, options), *key)
        return key, (assignment, changed, chosen, required, missing, matched, minutes)

    pairing_codes_present = any(
        groups.get("main_ingredient") or groups.get("cooking_method")
        for groups in pairing_metadata.values())
    estimated_assignments = 1
    for choices in group_choices:
        estimated_assignments *= max(1, len(choices))
        if estimated_assignments > 100_000:
            break
    if large_role_search:
        # Avoid materializing millions of equivalent role assignments for
        # large guest/drinking layouts. Search at most the existing safety
        # budget, dynamically preferring unseen pairing tags, while evaluate()
        # remains the authority for every hard constraint and final score.
        chosen_ids = set()
        assignment = {key: current[key] for key in targets if key in locked}
        chosen_ids.update(assignment.values())
        primary_used = set()
        method_used = set()
        for rid in chosen_ids:
            primary_used.update(pairing_metadata.get(rid, {}).get("main_ingredient", ()))
            method_used.update(pairing_metadata.get(rid, {}).get("cooking_method", ()))
        previous_unpinned = set(current.values()) - {current[key] for key in locked}
        visited = 0

        def search_large_roles(index, total_minutes):
            nonlocal visited, best, best_key
            if _daily_partial_ok is not None and not _daily_partial_ok(assignment):
                return False
            if index == len(targets):
                evaluated = evaluate(dict(assignment))
                if evaluated is not None and (best_key is None or evaluated[0] < best_key):
                    best_key, best = evaluated
                    if (service_target is None and not options.weather and not current and best_key[2] == 0 and best_key[3] == 0
                            and (not any(r.get("portion_ready", False) for r in recipes)
                                 or -best_key[4] == 100*len(targets))):
                        return True
                return False
            if visited >= (daily_limit if service_target is not None else CUSTOM_SEARCH_LIMIT):
                return False
            key = targets[index]
            if key in assignment:
                return search_large_roles(index + 1, total_minutes)
            group = key.split(":", 1)[0]
            candidates = [rid for rid in slot_eligible.get(key, ()) if rid not in chosen_ids]
            candidates.sort(key=lambda rid: (
                int(service_target is not None and (
                    by_id[rid].get("service_capacity_status") not in ("verified", "estimated")
                    or by_id[rid].get("portion_ready") is not True)),
                int(service_target is not None and rid in previous_unpinned),
                (_daily_order(rid, key, assignment) if _daily_order else 0),
                0 if current and current.get(key) != rid and rid not in options.history[group] else 1,
                len(set(pairing_metadata.get(rid, {}).get("main_ingredient", ())) & primary_used),
                len(set(pairing_metadata.get(rid, {}).get("cooking_method", ())) & method_used),
                -by_id[rid]["context_priority"],
                len(set(by_id[rid]["required_ids"]) - f.selected) if use_pantry else 0,
                by_id[rid]["minutes"], rid))
            for rid in candidates:
                if _daily_qualification is not None and any(
                        other_key not in locked and other_key.startswith(group+":") and other_key < key and other_id >= rid
                        for other_key, other_id in assignment.items()):
                    continue
                visited += 1
                next_minutes = total_minutes + by_id[rid]["minutes"]
                if f.max_total_minutes is not None and next_minutes > f.max_total_minutes:
                    continue
                assignment[key] = rid
                chosen_ids.add(rid)
                primary = set(pairing_metadata.get(rid, {}).get("main_ingredient", ()))
                methods = set(pairing_metadata.get(rid, {}).get("cooking_method", ()))
                primary_used.update(primary)
                method_used.update(methods)
                done = search_large_roles(index + 1, next_minutes)
                for code in primary:
                    if not any(code in pairing_metadata.get(other, {}).get("main_ingredient", ())
                               for other in chosen_ids - {rid}):
                        primary_used.discard(code)
                for code in methods:
                    if not any(code in pairing_metadata.get(other, {}).get("cooking_method", ())
                               for other in chosen_ids - {rid}):
                        method_used.discard(code)
                chosen_ids.remove(rid)
                assignment.pop(key, None)
                if done:
                    return True
                if visited >= (daily_limit if service_target is not None else CUSTOM_SEARCH_LIMIT):
                    break
            return False

        fixed_minutes = sum(by_id[rid]["minutes"] for rid in chosen_ids)
        search_large_roles(0, fixed_minutes)
        if (_daily_search_state is not None and service_target is not None
                and visited >= daily_limit):
            _daily_search_state["complete"] = False
        if best is None and visited >= (daily_limit if service_target is not None else CUSTOM_SEARCH_LIMIT):
            return no_plan(result, "SEARCH_LIMIT_REACHED", "KhÃ´ng thá»ƒ xÃ¡c Ä‘á»‹nh mÃ¢m trong giá»›i háº¡n tÃ¬m kiáº¿m an toÃ n.",
                           suggestions=["Giáº£m sá»‘ mÃ³n tÃ¹y chá»n hoáº·c ná»›i thá»i gian/nguyÃªn liá»‡u thiáº¿u; cÃ¡c bá»™ lá»c báº¯t buá»™c váº«n Ä‘Æ°á»£c giá»¯."])
    elif (not _force_exhaustive
          and not (options.layout_mode == "custom" and max(options.counts.values()) > MAX_PER_GROUP)
          and (pairing_codes_present or occasion in ("guests", "drinking"))
            and estimated_assignments <= 100_000):
        # The bounded, ordinary layouts stay exact while applying pairing and
        # occasion-specific ranking. Larger searches retain the optimized exact
        # legacy selector; hard ingredient/diet/role constraints are unchanged.
        for groups in product(*group_choices):
            assignment = {k: v for group in groups for k, v in group.items()}
            evaluated = evaluate(assignment)
            if evaluated is not None and (best_key is None or evaluated[0] < best_key):
                best_key, best = evaluated
    elif options.layout_mode == "custom" and max(options.counts.values()) > MAX_PER_GROUP:
        # Custom layouts can have many combinations. Walk a deterministic,
        # relevance- and diversity-sorted search space and stop at its first
        # feasible plan so six-dish requests stay within the TCP budget.
        # evaluate() remains authoritative for every hard constraint.
        candidate_order = {}
        for group in SLOTS:
            candidate_order[group] = sorted(eligible[group], key=lambda rid: (
                0 if by_id[rid].get("portion_ready", False) else 1,
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
            nonlocal visited, exhausted, best, best_key
            if index == len(free_targets):
                evaluated = evaluate(dict(assignment))
                if evaluated is not None:
                    best_key, best = evaluated
                    exhausted = False
                    return True
                return False
            key = free_targets[index]
            group = key.split(":")[0]
            for rid in candidate_order[group]:
                visited += 1
                if visited >= CUSTOM_LAYOUT_SEARCH_LIMIT:
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
        if best is None and visited >= CUSTOM_LAYOUT_SEARCH_LIMIT:
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
        for ingredient_id in (f.selected if use_pantry else ()):
            selected_mask |= 1 << ingredient_index[ingredient_id]
        required_masks = {}
        missing_masks = {}
        for r in recipes:
            mask = 0
            for ingredient_id in r["required_ids"]:
                mask |= 1 << ingredient_index[ingredient_id]
            required_masks[r["id"]] = mask
            missing_masks[r["id"]] = mask & ~selected_mask if use_pantry else 0

        # Materialize compact per-role combinations once. Then merge the first
        # two role groups by exact ingredient-mask state. Recipe pairs with the
        # same union can be collapsed to a Pareto frontier over missing-line
        # count and minutes; the final recipe-ID tie-break remains explicit.
        recipe_bit = {rid: 1 << index for index, rid in enumerate(sorted(by_id))}
        primary_codes = sorted({code for rid in by_id
                                for code in pairing_metadata.get(rid, {}).get("main_ingredient", ())})
        method_codes = sorted({code for rid in by_id
                               for code in pairing_metadata.get(rid, {}).get("cooking_method", ())})
        primary_index = {code: index for index, code in enumerate(primary_codes)}
        method_index = {code: index for index, code in enumerate(method_codes)}
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
                primary_counts = [0] * len(primary_codes)
                method_counts = [0] * len(method_codes)
                portion_ready_count = 0
                for rid in ids:
                    id_mask |= recipe_bit[rid]
                    required_mask |= required_masks[rid]
                    missing_sum += missing_masks[rid].bit_count()
                    minutes += by_id[rid]["minutes"]
                    portion_ready_count += by_id[rid]["context_priority"]
                    has_meat = has_meat or rid in meat_ids
                    for code in pairing_metadata.get(rid, {}).get("main_ingredient", ()):
                        primary_counts[primary_index[code]] += 1
                    for code in pairing_metadata.get(rid, {}).get("cooking_method", ()):
                        method_counts[method_index[code]] += 1
                changes = (sum(group_current.get(key) != assignment.get(key)
                               for key in set(group_current) | set(group_keys)) if current else 0)
                unseen = (sum(assignment[key] not in options.history[group]
                              for key in group_keys if current and group_current.get(key) != assignment[key]))
                replace_same = bool(options.replace and options.replace in assignment
                                    and assignment[options.replace] == current[options.replace])
                compact.append((ids, id_mask, required_mask, missing_sum, minutes, has_meat,
                                unseen, changes, replace_same, tuple(primary_counts), tuple(method_counts),
                                portion_ready_count))
            compact_choices.append(compact)

        main_choices, vegetable_choices, soup_choices = compact_choices

        if not cross_role_ids:
            best_key, best_assignment = _vectorized_chunked_exact_best(
                compact_choices, options, targets, selected_mask, needs_meat=needs_meat,
                use_pantry=use_pantry)
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


def _daily_selection_quality(recipes, target, classification, pairing_metadata):
    """Daily only: adequacy, main contribution, excess vegetables, diversity.

    The weighted serving policy is unchanged. A tiny reduction in surplus must
    not justify a third vegetable when a less vegetable-heavy plan also works.
    """
    from source.server.meal_plan_calculation import daily_meal_capacity
    target = Fraction(str(target))
    capacities = {group: Fraction(0) for group in SLOTS}
    counts = {group: 0 for group in SLOTS}
    unknown = 0
    for recipe in recipes:
        role = classification.categories.get(recipe["id"])
        if role not in capacities:
            unknown += 1
            continue
        counts[role] += 1
        try:
            value = Fraction(str(recipe.get("service_capacity")))
            known = (recipe.get("portion_ready") is True
                     and recipe.get("service_capacity_status") in ("verified", "estimated")
                     and 0 < value < 10000)
        except (ValueError, ZeroDivisionError):
            known = False
        if known:
            capacities[role] += value
        else:
            unknown += 1
    total = daily_meal_capacity(capacities)
    primary = [code for recipe in recipes for code in pairing_metadata.get(recipe["id"], {}).get("main_ingredient", ())]
    methods = [code for recipe in recipes for code in pairing_metadata.get(recipe["id"], {}).get("cooking_method", ())]
    return (unknown, max(0, target-total), max(0, target-capacities["main"]),
            max(0, counts["vegetable"]-2), len(primary)-len(set(primary)),
            len(methods)-len(set(methods)), max(0, counts["vegetable"]-1),
            max(0, total-target), len(recipes))


def _daily_eligible(recipe, options, metadata):
    f = options.filters
    rid = recipe["id"]
    if set(recipe["all_ids"]) & f.excluded or f.max_minutes is not None and recipe["minutes"] > f.max_minutes:
        return False
    if options.preferences.get("diet") == "vegetarian" and (metadata is None or rid not in metadata.vegetarian_ids):
        return False
    return metadata is None or not any(rid not in metadata.eligible_ids(group, code)
        for group, code in options.preferences.items() if group in ("region", "occasion"))


def _daily_minimum_counts(options):
    required = set(options.locked)
    if options.replace:
        required.update(options.current)
    return {group:max((int(key.split(":")[1]) for key in required if key.startswith(group+":")), default=0)
            for group in SLOTS}


def _daily_capacity_layouts(recipes, options, classification, metadata, search_state=None):
    """Rank daily layouts by reliable servings while keeping role groups separate."""
    target = Fraction(str(_daily_equivalent_target(options, recipes)))
    if target <= 0:
        return []
    f = options.filters
    pools = {group: [] for group in SLOTS}
    eligible_counts = {group: 0 for group in SLOTS}
    for recipe in recipes:
        rid = recipe["id"]
        role = classification.categories.get(rid)
        capacity = recipe.get("service_capacity")
        status = recipe.get("service_capacity_status")
        if role not in pools or not _daily_eligible(recipe, options, metadata):
            continue
        eligible_counts[role] += 1
        if (status not in ("verified", "estimated") or capacity is None
                or recipe.get("portion_ready") is not True):
            continue
        try:
            capacity = Fraction(str(capacity))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if not (capacity > 0 and capacity < 10000):
            continue
        pools[role].append((rid, capacity))
    for group in pools:
        pools[group].sort(key=lambda item: (item[1], item[0]))

    from functools import lru_cache

    @lru_cache(maxsize=64)
    def best_capacity(group, count, min_count):
        pool = pools[group]
        if count < min_count or len(pool) < count:
            return None
        # Public catalog is small; cap to nearest capacities around the target to
        # bound combinations while retaining both under- and over-serving choices.
        if len(pool) > 36 and search_state is not None:
            search_state["complete"] = False
        pool = sorted(pool, key=lambda item: (abs(item[1] - target / max(1, count)), item[0]))[:36]
        best = None
        for combo in combinations(pool, count):
            total = sum(value for _, value in combo)
            # Slightly prefer avoiding surplus when two layouts are equally close.
            score = max(0, target-total)*10 + max(0, total-target)*Fraction(2,25)
            tie = (score, count, tuple(sorted(rid for rid, _ in combo)))
            if best is None or tie < best[:3]:
                best = (*tie, total)
        return best

    min_counts = _daily_minimum_counts(options)
    ranked = []
    for main_count in range(max(1, min_counts["main"]), 5):
        for veg_count in range(max(1, min_counts["vegetable"]), 5):
            for soup_count in (max(1 if eligible_counts["soup"] else 0, min_counts["soup"]),):
                total_count = main_count + veg_count + soup_count
                if total_count > MAX_ITEMS:
                    continue
                parts = [best_capacity("main", main_count, min_counts["main"]),
                         best_capacity("vegetable", veg_count, min_counts["vegetable"])]
                if soup_count:
                    parts.append(best_capacity("soup", soup_count, min_counts["soup"]))
                if any(part is None for part in parts):
                    continue
                from source.server.meal_plan_calculation import daily_meal_capacity
                capacity = daily_meal_capacity(dict(zip(("main", "vegetable", "soup"), (part[3] for part in parts))))
                # Coverage first, then protect the main contribution. Surplus
                # vegetables must not win just by bringing the mean nearer N.
                score = (max(0.0, target-capacity), max(0.0, target-parts[0][3]),
                         max(0, veg_count-2), max(0, veg_count-1),
                         max(0.0, capacity-target), total_count)
                counts = {"main": main_count, "vegetable": veg_count, "soup": soup_count}
                ranked.append((score, total_count, tuple(counts[g] for g in SLOTS), counts, capacity))
    ranked.sort(key=lambda row: row[:3])
    # Compare every bounded layout, including lower-vegetable alternatives.
    unique = []
    for _, _, _, counts, _capacity in ranked:
        if counts not in unique:
            unique.append(counts)
    return unique


def _daily_equivalent_target(options, recipes):
    target = float(options.people or 0)
    if options.adults is None or options.children is None:
        return target
    sample_id = next((recipe.get("id") for recipe in recipes if type(recipe.get("id")) is int), None)
    if sample_id is None:
        return target
    from source.server.meal_plan_calculation import validate as validate_portion_request
    return float(validate_portion_request({"recipe_ids": [sample_id], "people": options.people,
        "adults": options.adults, "children": options.children}).equivalent_people)


def daily_classic_counts(people):
    """Original main/vegetable bands; Plan B explicitly requires one soup.

    counts_for_people is retained unchanged for custom and older API callers.
    """
    counts = counts_for_people(people, "daily")
    return {**counts, "soup": 1}


def generate(recipes, options: Options, classification: Classification, request_id: str, metadata=None,
             *, pairing_metadata=None, _force_exhaustive: bool = False, daily_catalog=None):
    if options.adaptive_daily:
        from source.server.daily_demo_portions import generate as recommend
        return recommend(recipes, options, classification, request_id, metadata, pairing_metadata, daily_catalog)
    return _generate_fixed(recipes, options, classification, request_id, metadata,
        pairing_metadata=pairing_metadata, _force_exhaustive=_force_exhaustive)


def _generate_plan_b(recipes, options: Options, classification: Classification, request_id: str, metadata=None,
             *, pairing_metadata=None, _force_exhaustive: bool = False):
    if not options.adaptive_daily:
        return _generate_fixed(recipes, options, classification, request_id, metadata,
            pairing_metadata=pairing_metadata, _force_exhaustive=_force_exhaustive)
    from dataclasses import replace
    tags = {rid:dict(values) for rid,values in (pairing_metadata or {}).items()}
    adjuncts = {"garlic","onion","shallot","scallion","salt","sugar","fish_sauce","water","oil","pepper","ginger"}
    for recipe in recipes:
        values = tags.setdefault(recipe["id"], {})
        values["main_ingredient"] = (frozenset(values.get("main_ingredient", ())) - adjuncts) | {
            f"ingredient:{iid}" for iid in recipe.get("daily_prominent_ids", ())}
    history = {group:options.history[group] | frozenset(rid for slot,rid in options.current.items()
        if slot.startswith(group+":")) for group in SLOTS}
    fixed = replace(options, counts=daily_classic_counts(options.people or 4), history=history)
    result = _generate_fixed(recipes, fixed, classification, request_id, metadata,
        pairing_metadata=tags, _force_exhaustive=_force_exhaustive, _daily_legacy_layout=True)
    result["adaptive_daily"] = True  # Existing browser transport flag; selection is now fixed-policy.
    result["daily_combo_search"] = {"found":int(result["plan"] is not None), "complete":False}
    result["daily_layout_reason"] = (
        "Cơ cấu món chính và rau theo chính sách Hằng ngày cũ, mặc định một canh theo phương án B. "
        "Khả năng phục vụ được đánh giá sau khi chọn mâm, không dùng để tự thêm hoặc giảm món. "
        "Số suất gốc lấy từ công thức MySQL; dữ liệu ước tính không chứng minh chắc chắn đủ ăn.")
    if result["plan"] is not None:
        selected = {item["recipe_id"] for item in result["plan"]["items"]}
        result["daily_combo_id"] = _daily_combo_id(selected)
        primary = [code for rid in selected for code in tags.get(rid, {}).get("main_ingredient", ())]
        if len(primary) != len(set(primary)):
            result["daily_layout_reason"] += " Mâm còn lặp nguyên liệu nổi bật do món ghim hoặc giới hạn ứng viên/bộ lọc."
        if options.regenerate and options.current:
            pinned = {options.current[slot] for slot in options.locked}
            overlap = len((selected & set(options.current.values())) - pinned)
            result["daily_combo_note"] = (f"Mâm mới còn trùng {overlap} món chưa ghim do giới hạn ứng viên/bộ lọc; giữ nguyên cơ cấu và món ghim."
                if overlap else "Mâm mới không trùng món chưa ghim; giữ nguyên cơ cấu Hằng ngày.")
    elif options.regenerate and result.get("reason", {}).get("code") == "NO_COMPLETE_MEAL_PLAN":
        result["reason"].update(code="NO_ALTERNATIVE",message="Chưa tìm được mâm khác với cơ cấu hiện tại và các món ghim/bộ lọc đang chọn.")
    return result


def _generate_capacity_combos(recipes, options: Options, classification: Classification, request_id: str, metadata=None,
             *, pairing_metadata=None, _force_exhaustive: bool = False):
    if not options.adaptive_daily:
        return _generate_fixed(recipes, options, classification, request_id, metadata,
                               pairing_metadata=pairing_metadata, _force_exhaustive=_force_exhaustive)
    from dataclasses import replace
    # A private copy is used only by adaptive daily plans. Custom, guest and
    # drinking calls return above with their exact original metadata/policy.
    pairing_metadata = {rid:dict(tags) for rid,tags in (pairing_metadata or {}).items()}
    for recipe in recipes:
        tags = pairing_metadata.setdefault(recipe["id"], {})
        common_tags = {"garlic","onion","shallot","scallion","salt","sugar","fish_sauce","water","oil","pepper","ginger"}
        tags["main_ingredient"] = (frozenset(tags.get("main_ingredient", ())) - common_tags) | frozenset(
            f"ingredient:{iid}" for iid in recipe.get("daily_prominent_ids", ()))
    search_state = {"combos": set(), "complete": True}
    if options.replace and options.current:
        layouts = [{group:sum(slot_name.startswith(group + ":") for slot_name in options.current)
                    for group in SLOTS}]
    else:
        layouts = _daily_capacity_layouts(recipes, options, classification, metadata, search_state)
    if not layouts:
        minimum = _daily_minimum_counts(options)
        # Unknown servings cannot justify extra dishes at fixed people bands.
        soup = any(classification.categories.get(r["id"]) == "soup" and _daily_eligible(r, options, metadata)
                   for r in recipes)
        layouts = [{"main":max(1,minimum["main"]), "vegetable":max(1,minimum["vegetable"]),
                    "soup":max(int(soup),minimum["soup"])}]
        if sum(layouts[0].values()) > MAX_ITEMS:
            # Let the existing pin conflict response keep the previous meal.
            layouts = [{"main":1,"vegetable":1,"soup":1}]
    first = None
    candidates = []
    by_id = {r["id"]:r for r in recipes}
    target = _daily_equivalent_target(options, recipes)
    for counts in layouts:
        result = _generate_fixed(recipes, replace(options, counts=counts),
                                 classification, request_id, metadata,
                                 pairing_metadata=pairing_metadata, _force_exhaustive=_force_exhaustive,
                                 _daily_search_state=search_state)
        if first is None:
            first = result
        if result["plan"] is not None:
            result["adaptive_daily"] = True
            recipe_ids = [item["recipe_id"] for item in result["plan"]["items"]]
            candidates.append((_daily_result_rank(recipe_ids, by_id, target, classification,
                                                  pairing_metadata, options), result))
    search_summary = {"found": len(search_state["combos"]), "complete": search_state["complete"]}
    if candidates:
        selected = candidates
        best_band = min(_daily_suitability_band(_daily_selection_quality(
            [by_id[item["recipe_id"]] for item in candidate["plan"]["items"]], target,
            classification, pairing_metadata), target) for _,candidate in candidates)
        if options.regenerate and options.current:
            selected = [(rank,candidate) for rank,candidate in candidates
                        if _daily_suitability_band(_daily_selection_quality(
                            [by_id[item["recipe_id"]] for item in candidate["plan"]["items"]], target,
                            classification, pairing_metadata), target) == best_band]
        current_id = _daily_combo_id(options.current.values()) if options.current else None
        if options.regenerate and options.current:
            suitable = selected
            selected = [(rank, candidate) for rank, candidate in suitable
                        if _daily_combo_id(item["recipe_id"] for item in candidate["plan"]["items"])
                        not in options.combo_history
                        and _daily_combo_id(item["recipe_id"] for item in candidate["plan"]["items"]) != current_id]
            if not selected:
                if not search_state["complete"]:
                    result = no_plan(
                        {"algorithm":ALGORITHM,"classification_version":classification.version,
                         "counts":layouts[0],"layout_mode":options.layout_mode,"plan":None,
                         "changed_slots":[],"warnings":[],"reason":None,"adaptive_daily":True},
                        "SEARCH_LIMIT_REACHED", "Chưa tìm được combo phù hợp chưa xem trong giới hạn tìm kiếm; giữ nguyên mâm hiện tại.",
                        suggestions=["Thử lại hoặc thay đổi bộ lọc; không lặp combo cũ để báo đã đổi mâm."])
                    result["daily_combo_search"] = search_summary
                    return result
                current_alternatives = [(rank, candidate) for rank, candidate in suitable
                                        if _daily_combo_id(item["recipe_id"] for item in candidate["plan"]["items"]) != current_id]
                if not current_alternatives:
                    if not search_state["complete"]:
                        result = no_plan(
                            {"algorithm": ALGORITHM, "classification_version": classification.version,
                             "counts": layouts[0], "layout_mode": options.layout_mode, "plan": None,
                             "changed_slots": [], "warnings": [], "reason": None, "adaptive_daily": True},
                            "SEARCH_LIMIT_REACHED", "Chưa thể xác định combo khác trong giới hạn tìm kiếm an toàn.",
                            suggestions=["Thử lại hoặc nới điều kiện; mâm hiện tại được giữ nguyên."])
                        result["daily_combo_search"] = search_summary
                        return result
                    result = no_plan(
                        {"algorithm": ALGORITHM, "classification_version": classification.version,
                         "counts": layouts[0], "layout_mode": options.layout_mode, "plan": None,
                         "changed_slots": [], "warnings": [], "reason": None, "adaptive_daily": True},
                        "NO_ALTERNATIVE", "Không còn combo mâm cơm khác phù hợp; mâm hiện tại được giữ nguyên.",
                        suggestions=["Thay đổi số người hoặc bộ lọc để tìm lại các combo phù hợp."])
                    result["daily_combo_search"] = search_summary
                    return result
                selected = current_alternatives
                recycled = search_state["complete"]
            else:
                recycled = False
        else:
            recycled = False
        rank, result = min(selected, key=lambda candidate: candidate[0])
        counts = result["counts"]
        rows = [by_id[item["recipe_id"]] for item in result["plan"]["items"]]
        quality = _daily_selection_quality(rows, target, classification, pairing_metadata)
        notes = []
        if any(row.get("service_capacity_status") == "estimated" for row in rows):
            notes.append("Sức phục vụ dựa trên dữ liệu ước tính có căn cứ tham khảo, không bảo đảm chắc chắn mọi người ăn đủ.")
        if not search_state["complete"]:
            notes.append("Phạm vi tìm kiếm bị giới hạn; đánh giá phản ánh các combo đã tìm thấy, chưa khẳng định đã hết combo phù hợp.")
        if quality[0]:
            notes.append("Thiếu số suất đáng tin cậy ở một số món; chưa xác định được khả năng phục vụ cả mâm.")
        elif quality[1]:
            notes.append("Đóng góp ước tính còn thấp hơn nhu cầu; chưa khẳng định mâm đủ ăn.")
        if counts["vegetable"] >= 3:
            notes.append("Chưa tìm được mâm ít rau hơn đáp ứng tốt trong phạm vi bộ lọc, món cố định và giới hạn tìm kiếm.")
        elif counts["vegetable"] == 2:
            lower = [_daily_selection_quality([by_id[item["recipe_id"]] for item in plan["plan"]["items"]],
                     target, classification, pairing_metadata)
                     for _,plan in candidates if plan["counts"]["vegetable"] < 2]
            lower_key = min(lower) if lower else None
            if lower_key is None or lower_key[:3] > quality[:3]:
                notes.append("Giữ rau thứ hai để bổ sung đóng góp của mâm khi phương án ít rau hơn còn hạn chế hoặc không hợp lệ.")
            else:
                notes.append("Giữ rau thứ hai vì phương án này giảm trùng nguyên liệu hoặc cách chế biến trong các mâm đã so sánh.")
        if counts["main"] > 1:
            notes.append(f"Ưu tiên {counts['main']} món chính để tăng phần đóng góp, giữ nguyên lượng mỗi công thức.")
        else:
            notes.append("Giữ một món chính theo đóng góp từ công thức gốc, không cố định cơ cấu theo số người.")
        if quality[4]:
            notes.append("Mâm còn lặp nguyên liệu nổi bật do món cố định, bộ lọc hoặc giới hạn tìm kiếm; có thể thử đổi món.")
        if not counts["soup"]:
            notes.append("Không có món canh hợp lệ trong các ứng viên hiện có.")
        recipe_ids = [item["recipe_id"] for item in result["plan"]["items"]]
        result["daily_combo_id"] = _daily_combo_id(recipe_ids)
        result["daily_combo_search"] = search_summary
        rotation_notes = []
        if options.regenerate and options.current:
            overlap = _daily_rotation_score(recipe_ids, options)[2]
            if recycled:
                if "HISTORY_RECYCLED" not in result["warnings"]:
                    result["warnings"].append("HISTORY_RECYCLED")
                notes.append("Đã dùng hết combo chưa xem; bắt đầu chu kỳ mới.")
                rotation_notes.append("Đã xem hết combo trong tập tìm kiếm đầy đủ; bắt đầu chu kỳ mới.")
            elif not search_state["complete"]:
                notes.append("Đã chọn combo khác ít trùng nhất trong các phương án đã tìm thấy.")
            if overlap:
                scope = "trong phạm vi tìm kiếm" if not search_state["complete"] else "trong các combo phù hợp"
                notes.append(f"Không tìm thấy combo chưa xem nào ít trùng hơn {scope}; mâm mới trùng {overlap} món chưa ghim.")
                rotation_notes.append(f"Combo mới còn trùng {overlap} món chưa ghim; đây là mức trùng ít nhất tìm được.")
            elif recycled:
                notes.append("Combo mới không trùng món chưa ghim với mâm đang xem.")
            else:
                rotation_notes.append("Đã chuyển combo khác, không trùng món chưa ghim với mâm đang xem.")
        if rotation_notes:
            result["daily_combo_note"] = " ".join(rotation_notes)[:500]
        result["daily_layout_reason"] = " ".join(notes)[:500]
        return result
    if not search_state["complete"]:
        result = no_plan(
            {"algorithm": ALGORITHM, "classification_version": classification.version,
             "counts": layouts[0], "layout_mode": options.layout_mode, "plan": None,
             "changed_slots": [], "warnings": [], "reason": None, "adaptive_daily": True},
            "SEARCH_LIMIT_REACHED", "Chưa thể xác định mâm phù hợp trong giới hạn tìm kiếm an toàn.",
            suggestions=["Thử lại hoặc nới điều kiện; hệ thống không khẳng định đã hết combo."])
        result["daily_combo_search"] = search_summary
        return result
    if first is not None:
        first["adaptive_daily"] = True
        first["daily_combo_search"] = search_summary
        return first
    result = no_plan({"algorithm": ALGORITHM, "classification_version": classification.version,
                      "counts": layouts[0], "layout_mode": options.layout_mode, "plan": None,
                      "changed_slots": [], "warnings": [], "reason": None, "adaptive_daily": True},
                     "NO_COMPLETE_MEAL_PLAN", "Không tìm được mâm Hằng ngày phù hợp với sức phục vụ và các điều kiện đã chọn.")
    result["daily_combo_search"] = search_summary
    return result
