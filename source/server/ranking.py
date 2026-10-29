from __future__ import annotations

from typing import Any, Iterable


def rank_recipes(recipes: Iterable[dict[str, Any]], selected: set[int], excluded: set[int], max_minutes: int | None, top_k: int, algorithm: str) -> list[dict[str, Any]]:
    ranked: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for recipe in recipes:
        all_ids = set(recipe["all_ids"])
        required = set(recipe["required_ids"])
        if all_ids & excluded or (max_minutes is not None and recipe["minutes"] > max_minutes):
            continue
        matched = selected & required
        if not matched:
            continue
        missing = required - selected
        coverage = len(matched) / len(required)
        input_use = len(matched) / len(selected)
        if algorithm == "baseline":
            score = float(len(matched))
            sort_key = (-score, recipe["id"])
        else:
            score = 0.7 * coverage + 0.3 * input_use
            sort_key = (-score, len(missing), recipe["minutes"], recipe["id"])
        item = {"recipe_id": recipe["id"], "title": recipe["title"], "minutes": recipe["minutes"], "score": round(score, 6), "matched_ids": sorted(matched), "missing_ids": sorted(missing), "coverage": round(coverage, 6), "input_use": round(input_use, 6), "missing_count": len(missing)}
        ranked.append((sort_key, item))
    ranked.sort(key=lambda pair: pair[0])
    return [item for _, item in ranked[:top_k]]
