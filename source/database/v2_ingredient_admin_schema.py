"""Checksummed additive schema for Admin ingredient activation state."""
from hashlib import sha256
from pathlib import Path
import re

VERSION = "004_admin_ingredient_state"
TABLES = {"v2_ingredient_admin_state"}
SQL_PATH = Path(__file__).with_name("migrations") / f"{VERSION}.sql"


def checksum():
    return sha256(SQL_PATH.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def statements():
    text = re.sub(r"(?m)^\s*--.*$", "", SQL_PATH.read_text(encoding="utf-8"))
    return [part.strip() for part in text.split(";") if part.strip()]


def schema_hash(connection):
    import json
    cursor = connection.cursor()
    try:
        cursor.execute("SHOW CREATE TABLE v2_ingredient_admin_state")
        return sha256(json.dumps(cursor.fetchone()[1], ensure_ascii=True).encode()).hexdigest()
    finally:
        cursor.close()
