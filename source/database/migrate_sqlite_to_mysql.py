"""Copy the legacy SQLite dataset into an already-created MySQL schema.

The SQLite file is opened read-only and is never deleted or modified.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import mysql.connector

from source.server.repository import mysql_config_from_env


def migrate(sqlite_path: str | Path) -> dict[str, int]:
    source = sqlite3.connect(f"file:{Path(sqlite_path).resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    target = mysql.connector.connect(**mysql_config_from_env())
    try:
        cursor = target.cursor()
        try:
            cursor.execute("DELETE FROM recipe_ingredients")
            cursor.execute("DELETE FROM recipes")
            cursor.execute("DELETE FROM ingredient_aliases")
            cursor.execute("DELETE FROM ingredients")
            cursor.execute("DELETE FROM metadata")
            cursor.executemany("INSERT INTO metadata (`key`,value) VALUES (%s,%s)", source.execute("SELECT key,value FROM metadata").fetchall())
            cursor.executemany("INSERT INTO ingredients (id,name,normalized_name) VALUES (%s,%s,%s)", [tuple(row) for row in source.execute("SELECT id,name,normalized_name FROM ingredients")])
            cursor.executemany("INSERT INTO ingredient_aliases (alias_norm,ingredient_id) VALUES (%s,%s)", [tuple(row) for row in source.execute("SELECT alias_norm,ingredient_id FROM ingredient_aliases")])
            cursor.executemany("INSERT INTO recipes (id,title,instructions,minutes,source_url,source_note) VALUES (%s,%s,%s,%s,%s,%s)", [tuple(row) for row in source.execute("SELECT id,title,instructions,minutes,source_url,source_note FROM recipes")])
            cursor.executemany("INSERT INTO recipe_ingredients (recipe_id,ingredient_id,quantity,is_required) VALUES (%s,%s,%s,%s)", [tuple(row) for row in source.execute("SELECT recipe_id,ingredient_id,quantity,is_required FROM recipe_ingredients")])
            target.commit()
        finally:
            cursor.close()
        return {table: int(source.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in ("metadata", "ingredients", "ingredient_aliases", "recipes", "recipe_ingredients")}
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()
        source.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate legacy SQLite data to MySQL")
    parser.add_argument("--sqlite", default="data/recipes.db")
    args = parser.parse_args()
    print(migrate(args.sqlite))
