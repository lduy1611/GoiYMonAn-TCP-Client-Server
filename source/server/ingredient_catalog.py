"""Stable business IDs and shared legacy/v2 ingredient catalog helpers."""
import unicodedata

from source.common.catalog_ids import UINT32_MAX, V2_OFFSET, v2_public_id


def normalized_key(value):
    return " ".join(unicodedata.normalize("NFC", str(value)).casefold().split())


def internal_id(business_id):
    """Translate a public v2 ingredient ID to its storage identity."""
    if type(business_id) is not int:
        return None
    if V2_OFFSET < business_id <= V2_OFFSET + UINT32_MAX:
        return business_id - V2_OFFSET
    return None


def business_id(v2_id, legacy_id=None, canonical_name=None, legacy_names=None):
    """Prefer the legacy business ID for an explicitly or exactly linked identity."""
    if legacy_id is not None:
        return int(legacy_id)
    if canonical_name and legacy_names:
        return legacy_names.get(normalized_key(canonical_name), v2_public_id(int(v2_id)))
    return v2_public_id(int(v2_id))


def merge_catalog(legacy_rows, v2_rows, *, active_only=False, query=""):
    """Merge rows without exposing storage IDs or duplicate linked names.

    Legacy IDs keep their existing public identity. A v2 identity with a
    legacy link or an exact normalized-name match represents the same business
    ingredient; unlinked v2 ingredients use the versioned public ID range.
    """
    legacy_by_id = {int(row["id"]): row for row in legacy_rows}
    legacy_by_name = {}
    for row in legacy_rows:
        for name in (row["name"], *row.get("aliases", [])):
            legacy_by_name[normalized_key(name)] = int(row["id"])
    merged = []
    seen = set()
    for row in legacy_rows:
        item = {"ingredient_id": int(row["id"]), "name": row["name"],
                "normalized_name": row.get("normalized_name", normalized_key(row["name"])),
                "is_active": bool(row["is_active"]), "usage_count": int(row.get("usage_count", 0)),
                "can_edit": bool(row.get("can_edit", False)),
                "can_manage": bool(row.get("can_manage", False)), "aliases": row.get("aliases", [])}
        if not active_only or item["is_active"]:
            merged.append(item)
        seen.add(item["ingredient_id"])

    for row in v2_rows:
        v2id = int(row["id"])
        legacy_id = int(row["legacy_ingredient_id"]) if row.get("legacy_ingredient_id") is not None else None
        matched_id = legacy_id
        if matched_id is None:
            matched_id = legacy_by_name.get(normalized_key(row["name"]))
        if matched_id is not None:
            # The legacy row is the shared display/selection identity. Include
            # v2 usage without creating a second visible ingredient.
            for item in merged:
                if item["ingredient_id"] == matched_id:
                    item["usage_count"] += int(row.get("usage_count", 0))
                    if legacy_id is not None:
                        item["is_active"] = item["is_active"] and bool(row["is_active"])
                    break
            continue
        try:
            public_id = v2_public_id(v2id)
        except ValueError:
            continue
        if public_id in seen:
            continue
        seen.add(public_id)
        item = {"ingredient_id": public_id, "name": row["name"],
                "normalized_name": row.get("normalized_name", normalized_key(row["name"])),
                "is_active": bool(row["is_active"]), "usage_count": int(row.get("usage_count", 0)),
                "can_edit": bool(row.get("can_edit", False)),
                "can_manage": bool(row.get("can_manage", False)), "aliases": []}
        if not active_only or item["is_active"]:
            merged.append(item)

    from source.server.repository import ingredient_search_normalize
    needle = ingredient_search_normalize(query) if query else ""
    if needle:
        merged = [row for row in merged if needle in ingredient_search_normalize(row["name"])
                  or any(needle in ingredient_search_normalize(alias) for alias in row["aliases"])]
    merged.sort(key=lambda row: (normalized_key(row["name"]), row["ingredient_id"]))
    return merged
