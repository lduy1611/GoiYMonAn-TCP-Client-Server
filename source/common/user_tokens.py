"""Signed short-lived account sessions, separate from existing Admin sessions."""
from source.common.admin_tokens import _b64, _unb64, _secret
import hashlib
import hmac
import json
import secrets
import time


def issue(user_id: int, username: str, role: str = "USER", *, now=None, lifetime=43200):
    issued = int(time.time() if now is None else now)
    claims = {"sub": username, "uid": user_id, "role": role, "aud": "recipe-user",
              "iat": issued, "exp": issued + lifetime, "csrf": secrets.token_urlsafe(24)}
    body = _b64(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return body + "." + signature, claims


def verify(token, *, now=None):
    if not isinstance(token, str) or len(token) > 2048 or token.count(".") != 1:
        return None
    body, signature = token.split(".")
    try:
        expected = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        claims = json.loads(_unb64(body))
        current = int(time.time() if now is None else now)
        if (not isinstance(claims, dict) or claims.get("aud") != "recipe-user"
                or not isinstance(claims.get("sub"), str) or not claims["sub"]
                or type(claims.get("uid")) is not int or not 0 < claims["uid"] < 2**64
                or claims.get("role") not in {"USER", "ADMIN"}
                or type(claims.get("exp")) is not int or claims["exp"] <= current
                or type(claims.get("iat")) is not int or claims["iat"] > current + 30
                or not isinstance(claims.get("csrf"), str) or len(claims["csrf"]) < 24):
            return None
        return claims
    except (ValueError, TypeError, UnicodeError, RuntimeError):
        return None
