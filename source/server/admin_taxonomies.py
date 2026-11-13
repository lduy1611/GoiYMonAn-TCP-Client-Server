"""Validation for Admin-managed recipe types and classifications."""
from __future__ import annotations

import re
import unicodedata

from source.common.protocol import ProtocolError

GROUPS = {
    "dish_type": {"dish_type"},
    "classification": {"region", "diet", "occasion", "weather", "cooking_method", "main_ingredient"},
}
ALL_GROUPS = set().union(*GROUPS.values())
CORE_DISH_TYPES = {
    "main": "Món chính",
    "vegetable": "Món rau",
    "soup": "Món canh",
    "side": "Món ăn kèm",
    "drink": "Đồ uống",
    "starch": "Món tinh bột",
    "other": "Khác",
}


def _norm(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _valid_code(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{1,47}", value) is not None


def validate_list(payload: dict, request_id: str) -> dict:
    if (set(payload) != {"kind", "query", "group", "status", "limit", "offset"}
            or not isinstance(payload.get("kind"), str) or payload["kind"] not in GROUPS or not isinstance(payload["query"], str)
            or len(payload["query"]) > 80
            or (payload["group"] is not None and (not isinstance(payload["group"], str) or payload["group"] not in GROUPS[payload["kind"]]))
            or payload["status"] not in ("active", "deleted", "all")
            or type(payload["limit"]) is not int or not 1 <= payload["limit"] <= 100
            or type(payload["offset"]) is not int or not 0 <= payload["offset"] <= 10000):
        raise ProtocolError("INVALID_PAYLOAD", "invalid taxonomy list request", request_id)
    return payload


def validate_save(payload: dict, request_id: str) -> dict:
    allowed = {"tag_id", "kind", "group", "code", "label", "description"}
    if (set(payload) - allowed or not {"kind", "group", "code", "label", "description"} <= set(payload)
            or not isinstance(payload.get("kind"), str) or payload["kind"] not in GROUPS
            or not isinstance(payload.get("group"), str) or payload["group"] not in GROUPS[payload["kind"]]
            or not _valid_code(payload["code"]) or not isinstance(payload["label"], str)
            or not 1 <= len(payload["label"].strip()) <= 100
            or not isinstance(payload["description"], str) or len(payload["description"]) > 2000
            or ("tag_id" in payload and (type(payload["tag_id"]) is not int or payload["tag_id"] < 1))):
        raise ProtocolError("INVALID_PAYLOAD", "invalid taxonomy values", request_id)
    if payload["kind"] == "dish_type" and payload["code"] in CORE_DISH_TYPES and "tag_id" not in payload:
        raise ProtocolError("ADMIN_TAXONOMY_CONFLICT", "core dish type codes are reserved", request_id)
    return {**payload, "label": payload["label"].strip(), "description": payload["description"].strip()}


def validate_deleted(payload: dict, request_id: str) -> dict:
    if (set(payload) != {"tag_id", "deleted"} or type(payload.get("tag_id")) is not int
            or payload["tag_id"] < 1 or type(payload.get("deleted")) is not bool):
        raise ProtocolError("INVALID_PAYLOAD", "invalid taxonomy status request", request_id)
    return payload


def validate_delete(payload: dict, request_id: str) -> dict:
    if set(payload) != {"tag_id"} or type(payload.get("tag_id")) is not int or payload["tag_id"] < 1:
        raise ProtocolError("INVALID_PAYLOAD", "invalid taxonomy ID", request_id)
    return payload


def validate_recipe_tags(payload: dict, request_id: str) -> dict:
    if (set(payload) != {"recipe_id", "kind", "tag_ids"} or type(payload.get("recipe_id")) is not int
            or payload["recipe_id"] < 1 or not isinstance(payload.get("kind"), str) or payload["kind"] not in GROUPS
            or not isinstance(payload["tag_ids"], list) or len(payload["tag_ids"]) > 100
            or any(type(tag_id) is not int or tag_id < 1 for tag_id in payload["tag_ids"])
            or len(set(payload["tag_ids"])) != len(payload["tag_ids"])
            or payload["kind"] == "dish_type" and len(payload["tag_ids"]) > 20):
        raise ProtocolError("INVALID_PAYLOAD", "invalid recipe taxonomy request", request_id)
    return payload
