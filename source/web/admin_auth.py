"""Environment-configured Admin credentials; passwords never enter TCP/DB logs."""
import hashlib
import hmac
import os
import secrets


def configured():
    return bool(os.getenv("ADMIN_USERNAME") and os.getenv("ADMIN_PASSWORD_HASH")
                and len(os.getenv("ADMIN_SESSION_SECRET", "").encode("utf-8")) >= 32)


def password_matches(password):
    stored=os.getenv("ADMIN_PASSWORD_HASH", "")
    try:
        scheme,iterations,salt,digest=stored.split("$",3)
        rounds=int(iterations)
        if scheme!="pbkdf2_sha256" or not 300_000<=rounds<=2_000_000:
            return False
        salt_bytes=bytes.fromhex(salt)
        expected=bytes.fromhex(digest)
        if len(salt_bytes)<16 or len(expected)!=32:
            return False
        actual=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),salt_bytes,rounds,dklen=32)
        return hmac.compare_digest(actual,expected)
    except (ValueError,TypeError,UnicodeError):
        # Keep an unknown user and an invalid hash on a comparable code path.
        hashlib.pbkdf2_hmac("sha256",str(password).encode("utf-8"),secrets.token_bytes(16),300_000,dklen=32)
        return False


def username_matches(username):
    configured_name=os.getenv("ADMIN_USERNAME", "")
    return bool(configured_name) and hmac.compare_digest(username.encode("utf-8"),configured_name.encode("utf-8"))
