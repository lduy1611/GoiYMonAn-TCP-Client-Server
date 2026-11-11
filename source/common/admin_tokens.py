"""Signed short-lived admin bearer claims shared by the gateway and TCP server."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time


def _secret():
    value = os.getenv("ADMIN_SESSION_SECRET", "")
    if len(value.encode("utf-8")) < 32:
        raise RuntimeError("Admin session signing is not configured")
    return value.encode("utf-8")


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue(username, *, account_uid=None, now=None, lifetime=3600):
    issued = int(time.time() if now is None else now)
    claims = {"sub":username,"aud":"recipe-admin","iat":issued,"exp":issued+lifetime,
              "csrf":secrets.token_urlsafe(24)}
    if account_uid is not None:
        if type(account_uid) is not int or not 0 < account_uid < 2**64:
            raise ValueError("invalid account administrator ID")
        claims["account_uid"] = account_uid
    body = _b64(json.dumps(claims,separators=(",",":"),sort_keys=True).encode("utf-8"))
    signature = _b64(hmac.new(_secret(),body.encode("ascii"),hashlib.sha256).digest())
    return body + "." + signature, claims


def verify(token, *, now=None):
    if not isinstance(token,str) or len(token)>2048 or token.count(".")!=1:
        return None
    body,signature=token.split(".")
    try:
        expected=_b64(hmac.new(_secret(),body.encode("ascii"),hashlib.sha256).digest())
        if not hmac.compare_digest(signature,expected):
            return None
        claims=json.loads(_unb64(body))
        current=int(time.time() if now is None else now)
        if (not isinstance(claims,dict) or claims.get("aud")!="recipe-admin"
                or not isinstance(claims.get("sub"),str) or not claims["sub"]
                or type(claims.get("exp")) is not int or claims["exp"]<=current
                or type(claims.get("iat")) is not int or claims["iat"]>current+30
                or not isinstance(claims.get("csrf"),str) or len(claims["csrf"])<24):
            return None
        if "account_uid" in claims and (type(claims["account_uid"]) is not int or not 0 < claims["account_uid"] < 2**64):
            return None
        return claims
    except (ValueError, TypeError, UnicodeError, RuntimeError):
        return None
