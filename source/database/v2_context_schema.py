"""Checksummed additive migration for release-pinned region/occasion metadata."""
from hashlib import sha256
from pathlib import Path
import re

VERSION = "002_recipe_context"
SQL_PATH = Path(__file__).with_name("migrations") / f"{VERSION}.sql"


def checksum():
    return sha256(SQL_PATH.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def statements():
    text = re.sub(r"(?m)^\s*--.*$", "", SQL_PATH.read_text(encoding="utf-8"))
    return [part.strip() for part in text.split(";") if part.strip()]


def tables():
    return re.findall(r"CREATE TABLE (v2_[a-z_]+)", SQL_PATH.read_text(encoding="utf-8"))
