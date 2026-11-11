"""Additive TEST_ONLY upgrade for existing unified-v3 databases."""
from __future__ import annotations


class UnifiedV3MigrationError(RuntimeError):
    pass


_COLUMNS = {
    "ingredient_form": "VARCHAR(120) NULL",
    "measurement_basis": "ENUM('gross','edible','prepared','unknown') NOT NULL DEFAULT 'unknown'",
    "scaling_mode": "ENUM('linear','fixed','unknown') NOT NULL DEFAULT 'unknown'",
}


def apply_structured_portions(connection) -> dict:
    """Add explicit line metadata; idempotent and fail-closed outside *_test."""
    cursor = connection.cursor()
    try:
        cursor.execute("SELECT DATABASE()")
        row = cursor.fetchone()
        database = row[0] if row else None
        if not isinstance(database, str) or not database.endswith("_test"):
            raise UnifiedV3MigrationError("unified-v3 additive migration is TEST_ONLY; database name must end in _test")
        cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s AND table_name='recipe_ingredients'", (database,))
        if int(cursor.fetchone()[0]) != 1:
            raise UnifiedV3MigrationError("unified-v3 recipe_ingredients table is unavailable")
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name='recipe_ingredients'", (database,))
        actual = {r[0] for r in cursor.fetchall()}
        applied = []
        for name, ddl in _COLUMNS.items():
            if name not in actual:
                cursor.execute(f"ALTER TABLE recipe_ingredients ADD COLUMN {name} {ddl}")
                applied.append(name)
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s AND table_name='recipe_ingredients'", (database,))
        final = {r[0] for r in cursor.fetchall()}
        if not set(_COLUMNS) <= final:
            raise UnifiedV3MigrationError("structured portion columns did not validate after migration")
        return {"database": database, "added_columns": applied,
                "status": "APPLIED" if applied else "NOOP_ALREADY_APPLIED"}
    finally:
        cursor.close()
