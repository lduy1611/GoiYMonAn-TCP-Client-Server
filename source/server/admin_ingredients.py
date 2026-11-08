"""Validation for Admin-only v2 ingredient catalog operations."""
import unicodedata

from source.common.protocol import ProtocolError

MAX_ID = 2**64 - 1


def _invalid(request_id):
    raise ProtocolError("INVALID_PAYLOAD", "invalid Admin ingredient payload", request_id)


def normalize_name(value, request_id=None):
    if not isinstance(value, str):
        _invalid(request_id)
    name = " ".join(unicodedata.normalize("NFC", value).split())
    if (not 2 <= len(name) <= 255 or not any(char.isalnum() for char in name)
            or any(unicodedata.category(char) == "Cc" for char in name)):
        _invalid(request_id)
    return name, name.casefold()


def validate_list(payload, request_id):
    if not isinstance(payload, dict) or set(payload) - {"query", "limit", "offset", "active_only", "catalog"}:
        _invalid(request_id)
    query = payload.get("query", "")
    limit = payload.get("limit", 20)
    offset = payload.get("offset", 0)
    active_only = payload.get("active_only", False)
    catalog = payload.get("catalog", "shared")
    if (not isinstance(query, str) or len(query) > 80 or type(limit) is not int or not 1 <= limit <= 50
            or type(offset) is not int or not 0 <= offset <= 1_000_000 or type(active_only) is not bool
            or not isinstance(catalog, str) or catalog not in {"shared", "v2"}):
        _invalid(request_id)
    query = " ".join(unicodedata.normalize("NFC", query).split())
    return {"query": query, "limit": limit, "offset": offset, "active_only": active_only, "catalog": catalog}


def validate_create(payload, request_id):
    if not isinstance(payload, dict) or set(payload) != {"name"}:
        _invalid(request_id)
    name, normalized = normalize_name(payload["name"], request_id)
    return {"name": name, "normalized_name": normalized}


def validate_update(payload, request_id):
    if (not isinstance(payload, dict) or set(payload) != {"ingredient_id", "name"}
            or type(payload.get("ingredient_id")) is not int
            or not 1 <= payload["ingredient_id"] <= MAX_ID):
        _invalid(request_id)
    name, normalized = normalize_name(payload["name"], request_id)
    return {"ingredient_id": payload["ingredient_id"], "name": name, "normalized_name": normalized}


def validate_active(payload, request_id):
    if (not isinstance(payload, dict) or set(payload) != {"ingredient_id", "is_active"}
            or type(payload.get("ingredient_id")) is not int
            or not 1 <= payload["ingredient_id"] <= MAX_ID or type(payload.get("is_active")) is not bool):
        _invalid(request_id)
    return payload


def validate_legacy_update(payload, request_id):
    if (not isinstance(payload, dict) or set(payload) != {"ingredient_id", "name"}
            or type(payload.get("ingredient_id")) is not int
            or not 1 <= payload["ingredient_id"] <= 2**32 - 1):
        _invalid(request_id)
    name, normalized = normalize_name(payload["name"], request_id)
    return {"ingredient_id": payload["ingredient_id"], "name": name, "normalized_name": normalized}


def validate_legacy_active(payload, request_id):
    if (not isinstance(payload, dict) or set(payload) != {"ingredient_id", "is_active"}
            or type(payload.get("ingredient_id")) is not int
            or not 1 <= payload["ingredient_id"] <= 2**32 - 1
            or type(payload.get("is_active")) is not bool):
        _invalid(request_id)
    return payload
