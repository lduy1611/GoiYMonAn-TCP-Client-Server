"""Direct Admin publication and lifecycle state, separate from reviewed releases."""
from hashlib import sha256
from pathlib import Path
import json
import re

VERSION = "009_admin_recipe_catalog"
TABLES = {"v2_admin_recipe_catalog_overrides"}
SQL_PATH = Path(__file__).with_name("migrations") / f"{VERSION}.sql"

def checksum():
    return sha256(SQL_PATH.read_text(encoding="utf-8").encode("utf-8")).hexdigest()

def statements():
    text = re.sub(r"(?m)^\s*--.*$", "", SQL_PATH.read_text(encoding="utf-8"))
    return [part.strip() for part in text.split(";") if part.strip()]

def schema_hash(connection):
    cursor = connection.cursor()
    try:
        cursor.execute("SHOW CREATE TABLE v2_admin_recipe_catalog_overrides")
        row = cursor.fetchone()
        if not row:
            return None
        # MySQL adds AUTO_INCREMENT=N to SHOW CREATE TABLE after rows are
        # inserted. That counter is table data state, not a schema change.
        definition = re.sub(r"\s+AUTO_INCREMENT=\d+", "", row[1], flags=re.IGNORECASE)
        return sha256(json.dumps(definition, ensure_ascii=True).encode()).hexdigest()
    finally:
        cursor.close()
