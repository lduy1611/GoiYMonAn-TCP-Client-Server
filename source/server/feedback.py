"""Validation for public feedback submissions."""
from __future__ import annotations

import uuid

CATEGORIES = {"bug", "feature", "other"}


def validate_create(payload):
    allowed = {"category", "content", "request_key", "image", "user_id"}
    if set(payload) - allowed or not {"category", "content", "request_key", "image"} <= set(payload):
        raise ValueError("invalid feedback fields")
    category, content, key, image = (payload["category"], payload["content"], payload["request_key"], payload["image"])
    if not isinstance(category, str) or category not in CATEGORIES:
        raise ValueError("invalid feedback category")
    if not isinstance(content, str) or not 1 <= len(content.strip()) <= 3000:
        raise ValueError("feedback content must contain 1 to 3000 characters")
    if not isinstance(key, str):
        raise ValueError("invalid feedback request key")
    try:
        uuid.UUID(key)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("invalid feedback request key") from None
    if image is not None:
        required = {"storage_key", "media_type", "byte_size", "width", "height", "sha256"}
        if not isinstance(image, dict) or set(image) != required:
            raise ValueError("invalid feedback image metadata")
        if not isinstance(image["storage_key"], str) or len(image["storage_key"]) != 36:
            raise ValueError("invalid feedback image key")
        if image["media_type"] not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("unsupported feedback image type")
        if type(image["byte_size"]) is not int or not 1 <= image["byte_size"] <= 5 * 1024 * 1024:
            raise ValueError("invalid feedback image size")
        if type(image["width"]) is not int or type(image["height"]) is not int or not 1 <= image["width"] <= 8000 or not 1 <= image["height"] <= 8000 or image["width"] * image["height"] > 20_000_000:
            raise ValueError("invalid feedback image dimensions")
        if not isinstance(image["sha256"], str) or len(image["sha256"]) != 64:
            raise ValueError("invalid feedback image checksum")
    if "user_id" in payload and (type(payload["user_id"]) is not int or payload["user_id"] <= 0):
        raise ValueError("invalid feedback user")
    return {"category": category, "content": content.strip(), "request_key": key, "image": image, **({"user_id":payload["user_id"]} if "user_id" in payload else {})}


def validate_admin_list(payload):
    if set(payload) != {"status", "limit", "offset"}:
        raise ValueError("invalid feedback query")
    if not isinstance(payload["status"], str) or payload["status"] not in {"all", "open", "resolved"} or type(payload["limit"]) is not int or not 1 <= payload["limit"] <= 100 or type(payload["offset"]) is not int or payload["offset"] < 0:
        raise ValueError("invalid feedback query")
    return payload["status"], payload["limit"], payload["offset"]
