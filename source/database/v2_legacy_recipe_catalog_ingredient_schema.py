"""Additive migration 010 for shared-catalog ingredients in legacy overlays."""
from hashlib import sha256
from pathlib import Path
import re

VERSION = "010_legacy_recipe_catalog_ingredients"
SQL_PATH = Path(__file__).with_name("migrations") / f"{VERSION}.sql"


def checksum():
    return sha256(SQL_PATH.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def statements():
    text = re.sub(r"(?m)^\s*--.*$", "", SQL_PATH.read_text(encoding="utf-8"))
    return [part.strip() for part in text.split(";") if part.strip()]


def schema_hash(connection):
    definitions=[]
    for table in ("v2_admin_legacy_recipe_overrides", "v2_admin_legacy_recipe_override_ingredients"):
        cursor = connection.cursor()
        try:
            cursor.execute(f"SHOW CREATE TABLE {table}")
            row = cursor.fetchone()
            if not row:return None
            definitions.append(row[1])
        finally:
            cursor.close()
    return sha256("\n".join(definitions).encode("utf-8")).hexdigest()


def schema_hash_matches(connection, expected):
    return expected is not None and schema_hash(connection) == expected


def schema_ready(connection):
    import mysql.connector
    cursor = connection.cursor()
    try:
        try:
            cursor.execute("SHOW COLUMNS FROM v2_admin_legacy_recipe_override_ingredients")
        except mysql.connector.Error as exc:
            if exc.errno==1146:return False
            raise
        columns = {row[0]: (str(row[1]).casefold(),str(row[2]).casefold()) for row in cursor.fetchall()}
        if columns.get("ingredient_id") not in {
                ("int unsigned","yes"),("int(10) unsigned","yes")}:
            return False
        if columns.get("v2_ingredient_id") not in {
                ("bigint unsigned","yes"),("bigint(20) unsigned","yes")}:
            return False
        cursor.execute("""SELECT CONSTRAINT_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='v2_admin_legacy_recipe_override_ingredients'
              AND CONSTRAINT_NAME='fk_v2_admin_legacy_override_v2_ingredient'""")
        if cursor.fetchone() is None:
            return False
        cursor.execute("""SELECT CONSTRAINT_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='v2_admin_legacy_recipe_override_ingredients'
              AND CONSTRAINT_NAME='fk_v2_admin_legacy_override_ingredient'""")
        if cursor.fetchone() is None:
            return False
        cursor.execute("""SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS
            WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='v2_admin_legacy_recipe_override_ingredients'
              AND CONSTRAINT_NAME='ck_v2_admin_legacy_override_one_ingredient' AND CONSTRAINT_TYPE='CHECK'""")
        if cursor.fetchone() is None:return False
        cursor.execute("""SELECT COUNT(DISTINCT INDEX_NAME) FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='v2_admin_legacy_recipe_override_ingredients'
              AND INDEX_NAME IN ('uq_v2_admin_legacy_override_v2_ingredient','uq_v2_admin_legacy_override_ingredient')""")
        return int(cursor.fetchone()[0])==2
    finally:
        cursor.close()
