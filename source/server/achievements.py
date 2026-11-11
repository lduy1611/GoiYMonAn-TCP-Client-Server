from __future__ import annotations

import re
import uuid


class AchievementError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_KEY = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|webp)$")
_MEDIA = {"image/jpeg", "image/png", "image/webp"}


def validate_list(payload):
    if set(payload) - {"query", "limit", "offset"}:
        raise AchievementError("INVALID_PAYLOAD", "invalid achievement list fields")
    query = payload.get("query", "")
    limit, offset = payload.get("limit", 12), payload.get("offset", 0)
    if not isinstance(query, str) or len(query) > 80:
        raise AchievementError("INVALID_PAYLOAD", "invalid achievement search query")
    if type(limit) is not int or not 1 <= limit <= 30 or type(offset) is not int or not 0 <= offset <= 100000:
        raise AchievementError("INVALID_PAYLOAD", "invalid achievement pagination")
    return query, limit, offset


def validate_post(payload):
    allowed = {"recipe_id", "description", "changed_ingredients", "request_key", "images", "user_id"}
    if set(payload) - allowed:
        raise AchievementError("INVALID_PAYLOAD", "invalid achievement post fields")
    recipe_id = payload.get("recipe_id")
    description = payload.get("description")
    changed = payload.get("changed_ingredients")
    request_key = payload.get("request_key")
    images = payload.get("images")
    user_id = payload.get("user_id")
    if type(recipe_id) is not int or not 1 <= recipe_id < 2**64:
        raise AchievementError("INVALID_PAYLOAD", "invalid recipe ID")
    if not isinstance(description, str) or not description.strip() or len(description.strip()) > 3000:
        raise AchievementError("INVALID_PAYLOAD", "description must contain 1 to 3000 characters")
    if changed is not None and (not isinstance(changed, str) or len(changed) > 1000):
        raise AchievementError("INVALID_PAYLOAD", "changed ingredients must be at most 1000 characters")
    try:
        uuid.UUID(request_key)
    except (ValueError, TypeError, AttributeError):
        raise AchievementError("INVALID_PAYLOAD", "a valid idempotency key is required") from None
    if not isinstance(images, list) or not 1 <= len(images) <= 3:
        raise AchievementError("INVALID_PAYLOAD", "choose between 1 and 3 photos")
    if type(user_id) is not int or not 1 <= user_id < 2**64:
        raise AchievementError("USER_UNAUTHORIZED", "a signed-in user is required")
    for image in images:
        if (not isinstance(image, dict) or set(image) != {"storage_key", "media_type", "byte_size", "width", "height", "sha256"}
                or not isinstance(image["storage_key"], str) or not _KEY.fullmatch(image["storage_key"])
                or image["media_type"] not in _MEDIA or type(image["byte_size"]) is not int or not 1 <= image["byte_size"] <= 5*1024*1024
                or type(image["width"]) is not int or type(image["height"]) is not int or not 1 <= image["width"] <= 8000
                or not 1 <= image["height"] <= 8000 or image["width"]*image["height"] > 20_000_000
                or not isinstance(image["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", image["sha256"])):
            raise AchievementError("INVALID_PAYLOAD", "photo metadata is invalid")
    return {**payload, "description": description.strip(), "changed_ingredients": (changed or "").strip() or None}


def validate_comment(payload):
    if set(payload) != {"post_id", "body", "user_id"}:
        raise AchievementError("INVALID_PAYLOAD", "invalid comment fields")
    post_id, body, user_id = payload["post_id"], payload["body"], payload["user_id"]
    if type(post_id) is not int or not 1 <= post_id < 2**64:
        raise AchievementError("INVALID_PAYLOAD", "invalid achievement ID")
    if not isinstance(body, str) or not body.strip() or len(body.strip()) > 2000:
        raise AchievementError("INVALID_PAYLOAD", "comment must contain 1 to 2000 characters")
    if type(user_id) is not int or not 1 <= user_id < 2**64:
        raise AchievementError("USER_UNAUTHORIZED", "a signed-in user is required")
    return {**payload, "body": body.strip()}


def validate_owned_delete(payload, *, comment=False):
    expected = {"comment_id", "user_id"} if comment else {"post_id", "user_id"}
    if set(payload) != expected:
        raise AchievementError("INVALID_PAYLOAD", "invalid delete fields")
    id_key = "comment_id" if comment else "post_id"
    value = payload[id_key]
    if type(value) is not int or not 1 <= value < 2**64 or type(payload["user_id"]) is not int:
        raise AchievementError("INVALID_PAYLOAD", "invalid delete identity")
    return payload
