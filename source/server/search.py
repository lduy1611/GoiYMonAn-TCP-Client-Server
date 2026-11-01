"""Read-only recipe name search, independent of the B0/P1 ranker."""
from __future__ import annotations

from dataclasses import dataclass
import unicodedata
from typing import Any, Iterable

from source.common.protocol import ProtocolError


def fold_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value.casefold().replace("đ", "d"))
    return " ".join("".join(ch for ch in decomposed if not unicodedata.combining(ch)).split())


@dataclass(frozen=True)
class SearchOptions:
    query: str
    selected: frozenset[int]
    excluded: frozenset[int]
    max_minutes: int | None
    max_missing: int | None
    limit: int
    offset: int


def validate_search(payload: dict[str, Any], request_id: str) -> SearchOptions:
    allowed = {"query", "ingredient_ids", "excluded_ids", "max_minutes", "max_missing", "limit", "offset"}
    query = payload.get("query", "")
    selected = payload.get("ingredient_ids", [])
    excluded = payload.get("excluded_ids", [])
    minutes = payload.get("max_minutes")
    missing = payload.get("max_missing")
    limit = payload.get("limit", 12)
    offset = payload.get("offset", 0)

    def integer(value, low, high=None):
        return type(value) is int and value >= low and (high is None or value <= high)

    def ids(value):
        return isinstance(value, list) and len(value) <= 30 and all(integer(item, 1) for item in value)

    if (set(payload) - allowed or not isinstance(query, str) or len(query) > 80 or
            not ids(selected) or not ids(excluded) or
            minutes is not None and not integer(minutes, 1, 240) or
            missing is not None and not integer(missing, 0, 50) or
            not integer(limit, 1, 20) or not integer(offset, 0)):
        raise ProtocolError("INVALID_PAYLOAD", "invalid SEARCH_RECIPES payload", request_id)
    if set(selected) & set(excluded):
        raise ProtocolError("INVALID_PAYLOAD", "ingredient ids are invalid", request_id)
    return SearchOptions(query, frozenset(selected), frozenset(excluded), minutes, missing, limit, offset)


def search_recipes(recipes: Iterable[dict[str, Any]], options: SearchOptions) -> dict[str, Any]:
    query = fold_name(options.query)
    matches = []
    for recipe in recipes:
        title = fold_name(recipe["title"])
        if query not in title or set(recipe["all_ids"]) & options.excluded:
            continue
        if options.max_minutes is not None and recipe["minutes"] > options.max_minutes:
            continue
        required = set(recipe["required_ids"])
        matched = required & options.selected
        missing = required - options.selected
        if options.max_missing is not None and len(missing) > options.max_missing:
            continue
        relevance = 0 if not query or title == query else 1 if title.startswith(query) else 2
        item = {
            "recipe_id": recipe["id"], "title": recipe["title"], "minutes": recipe["minutes"],
            "matched_ids": sorted(matched), "missing_ids": sorted(missing), "missing_count": len(missing),
        }
        matches.append(((relevance, recipe["id"]), item))
    matches.sort(key=lambda match: match[0])
    items = [item for _, item in matches[options.offset:options.offset + options.limit]]
    return {
        "items": items, "total": len(matches), "limit": options.limit, "offset": options.offset,
        "has_more": options.offset + len(items) < len(matches),
        "warnings": [] if matches else ["NO_MATCH"],
    }
