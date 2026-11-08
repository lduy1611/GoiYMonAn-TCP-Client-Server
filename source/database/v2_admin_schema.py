"""Checksummed additive schema change required by Admin draft editing."""
from hashlib import sha256
from pathlib import Path
import re

VERSION = "003_admin_draft_description"
SQL_PATH = Path(__file__).with_name("migrations") / f"{VERSION}.sql"


def checksum():
    return sha256(SQL_PATH.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def statements():
    text = re.sub(r"(?m)^\s*--.*$", "", SQL_PATH.read_text(encoding="utf-8"))
    return [part.strip() for part in text.split(";") if part.strip()]
