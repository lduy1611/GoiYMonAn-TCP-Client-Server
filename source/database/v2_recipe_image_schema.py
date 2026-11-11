"""Additive recipe image metadata migration; image files stay outside the web static root."""
from hashlib import sha256
from pathlib import Path
import re
import json

VERSION = "007_recipe_images"
SQL_PATH = Path(__file__).with_name("migrations") / f"{VERSION}.sql"
TABLES = ("v2_recipe_image_overrides",)


def checksum():
    return sha256(SQL_PATH.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def statements():
    text = re.sub(r"(?m)^\s*--.*$", "", SQL_PATH.read_text(encoding="utf-8"))
    return [part.strip() for part in text.split(";") if part.strip()]


def schema_hash(connection):
    cursor = connection.cursor()
    try:
        cursor.execute("SHOW CREATE TABLE v2_recipe_image_overrides")
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("recipe image table is missing")
        return sha256(json.dumps([row[1]], ensure_ascii=True).encode()).hexdigest()
    finally:
        cursor.close()


def schema_hash_matches(connection, expected):
    try:
        return schema_hash(connection) == expected
    except Exception:
        return False
