"""Additive Admin-owned overlay for legacy recipe edits and visibility."""
from hashlib import sha256
from pathlib import Path
import re

VERSION = "006_legacy_recipe_overlays"
SQL_PATH = Path(__file__).with_name("migrations") / f"{VERSION}.sql"
TABLES = ("v2_admin_legacy_recipe_overrides", "v2_admin_legacy_recipe_override_ingredients")


def checksum():
    return sha256(SQL_PATH.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def statements():
    text = re.sub(r"(?m)^\s*--.*$", "", SQL_PATH.read_text(encoding="utf-8"))
    return [part.strip() for part in text.split(";") if part.strip()]


def schema_hash(connection):
    definitions=[]
    for table in TABLES:
        cursor=connection.cursor()
        try:
            cursor.execute(f"SHOW CREATE TABLE {table}")
            row=cursor.fetchone()
            if not row:
                return None
            definitions.append(row[1])
        finally:
            cursor.close()
    return sha256("\n".join(definitions).encode("utf-8")).hexdigest()


def schema_hash_matches(connection, expected):
    return expected is not None and schema_hash(connection)==expected
