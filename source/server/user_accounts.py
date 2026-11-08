"""Server-side account validation and password hashing for TCP account operations."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata

from source.common.protocol import ProtocolError

PBKDF2_ROUNDS = 600_000
_USERNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$", re.ASCII)
_DUMMY_SALT = bytes.fromhex("a4d580f6e3a41be80d589a3e0e66d3a9")
_DUMMY_HASH = hashlib.pbkdf2_hmac("sha256", b"TEST_ONLY dummy password", _DUMMY_SALT, PBKDF2_ROUNDS)


def _username(value, request_id):
    if not isinstance(value, str) or not _USERNAME.fullmatch(value):
        raise ProtocolError("INVALID_PAYLOAD", "username must be 3-32 ASCII letters, digits, dot, dash or underscore", request_id)
    normalized = unicodedata.normalize("NFC", value).casefold()
    return value, normalized


def validate_register(payload, request_id):
    if set(payload) != {"username", "password", "password_confirmation"}:
        raise ProtocolError("INVALID_PAYLOAD", "invalid registration fields", request_id)
    username, normalized = _username(payload["username"], request_id)
    password = payload["password"]
    confirmation = payload["password_confirmation"]
    if not isinstance(password, str) or not isinstance(confirmation, str) or password != confirmation:
        raise ProtocolError("INVALID_PAYLOAD", "password confirmation does not match", request_id)
    if not 12 <= len(password) <= 256 or len(password.encode("utf-8")) > 1024:
        raise ProtocolError("INVALID_PAYLOAD", "password must contain 12-256 characters", request_id)
    return {"username": username, "normalized_username": normalized, "password": password}


def validate_login(payload, request_id):
    if set(payload) != {"username", "password"}:
        raise ProtocolError("INVALID_PAYLOAD", "invalid login fields", request_id)
    username, normalized = _username(payload["username"], request_id)
    password = payload["password"]
    if not isinstance(password, str) or not 1 <= len(password) <= 256 or len(password.encode("utf-8")) > 1024:
        raise ProtocolError("INVALID_PAYLOAD", "invalid credentials", request_id)
    return {"username": username, "normalized_username": normalized, "password": password}


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS, dklen=32)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password, encoded):
    try:
        scheme, rounds_text, salt_text, digest_text = encoded.split("$", 3)
        rounds = int(rounds_text)
        salt, expected = bytes.fromhex(salt_text), bytes.fromhex(digest_text)
        if scheme != "pbkdf2_sha256" or not 300_000 <= rounds <= 2_000_000 or len(salt) < 16 or len(expected) != 32:
            raise ValueError
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds, dklen=32)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError, AttributeError):
        # Equalize the unknown/malformed hash path with a bounded PBKDF2 operation.
        actual = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), _DUMMY_SALT,
                                     PBKDF2_ROUNDS, dklen=32)
        hmac.compare_digest(actual, _DUMMY_HASH)
        return False


def validate_session(payload, request_id):
    if set(payload) != {"session_token"} or not isinstance(payload["session_token"], str) or len(payload["session_token"]) > 2048:
        raise ProtocolError("INVALID_PAYLOAD", "invalid user session", request_id)
    from source.common.user_tokens import verify
    claims = verify(payload["session_token"])
    if claims is None:
        raise ProtocolError("USER_UNAUTHORIZED", "user session is missing or expired", request_id)
    return claims


def validate_admin_list(payload, request_id):
    query = payload.get("query", "")
    limit, offset = payload.get("limit", 20), payload.get("offset", 0)
    if (set(payload) - {"query", "limit", "offset"} or not isinstance(query, str) or len(query) > 80
            or type(limit) is not int or not 1 <= limit <= 50
            or type(offset) is not int or not 0 <= offset <= 1_000_000):
        raise ProtocolError("INVALID_PAYLOAD", "invalid user list query", request_id)
    return {"query": query.strip(), "limit": limit, "offset": offset}


def validate_admin_status(payload, request_id):
    if set(payload) != {"user_id", "account_status"}:
        raise ProtocolError("INVALID_PAYLOAD", "invalid user status fields", request_id)
    value, status = payload["user_id"], payload["account_status"]
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 20 or not 1 <= int(value) < 2**64:
        raise ProtocolError("INVALID_PAYLOAD", "invalid user ID", request_id)
    if status not in {"ACTIVE", "LOCKED"}:
        raise ProtocolError("INVALID_PAYLOAD", "invalid account status", request_id)
    return {"user_id": int(value), "account_status": status}


def validate_admin_role(payload, request_id):
    if set(payload) != {"user_id", "role"}:
        raise ProtocolError("INVALID_PAYLOAD", "invalid user role fields", request_id)
    value, role = payload["user_id"], payload["role"]
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 20 or not 1 <= int(value) < 2**64:
        raise ProtocolError("INVALID_PAYLOAD", "invalid user ID", request_id)
    if role not in {"USER", "ADMIN"}:
        raise ProtocolError("INVALID_PAYLOAD", "invalid account role", request_id)
    return {"user_id": int(value), "role": role}
