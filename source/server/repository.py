from __future__ import annotations

import os
import sqlite3
import threading
import unicodedata
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import mysql.connector
from mysql.connector import pooling


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def mysql_config_from_env() -> dict[str, Any]:
    load_dotenv()
    required = ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE")
    missing = [key for key in required if os.getenv(key) is None]
    if missing:
        raise RuntimeError("Missing MySQL configuration: " + ", ".join(missing))
    return {
        "host": os.environ["MYSQL_HOST"],
        "port": int(os.environ["MYSQL_PORT"]),
        "user": os.environ["MYSQL_USER"],
        "password": os.environ["MYSQL_PASSWORD"],
        "database": os.environ["MYSQL_DATABASE"],
        "charset": "utf8mb4",
        "collation": "utf8mb4_unicode_ci",
        "connection_timeout": 5,
    }


class Repository:
    """Legacy read-only SQLite repository retained for regression comparison."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.db_path.resolve()}?mode=ro", uri=True)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def dataset_version(self, connection: sqlite3.Connection) -> str:
        row = connection.execute("SELECT value FROM metadata WHERE key='dataset_version'").fetchone()
        if row is None:
            raise sqlite3.DatabaseError("missing dataset_version")
        return str(row[0])

    def list_ingredients(self, connection: sqlite3.Connection, query: str, limit: int) -> list[dict[str, Any]]:
        normalized = normalize(query.strip())
        escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        rows = connection.execute("SELECT DISTINCT i.id, i.name FROM ingredients i LEFT JOIN ingredient_aliases a ON a.ingredient_id=i.id WHERE i.normalized_name LIKE ? ESCAPE '\\' OR a.alias_norm LIKE ? ESCAPE '\\' ORDER BY i.id LIMIT ?", (pattern, pattern, limit)).fetchall()
        return [{"id": row[0], "name": row[1]} for row in rows]

    def recipes_for_ranking(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute("SELECT id,title,minutes FROM recipes ORDER BY id").fetchall()
        relations = connection.execute("SELECT recipe_id,ingredient_id,is_required FROM recipe_ingredients ORDER BY recipe_id,ingredient_id").fetchall()
        grouped: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for recipe_id, ingredient_id, is_required in relations:
            grouped[recipe_id].append((ingredient_id, is_required))
        return [{"id": recipe_id, "title": title, "minutes": minutes, "required_ids": {x[0] for x in grouped[recipe_id] if x[1]}, "all_ids": {x[0] for x in grouped[recipe_id]}} for recipe_id, title, minutes in rows]

    def ingredient_ids_exist(self, connection: sqlite3.Connection, ids: set[int]) -> bool:
        if not ids:
            return True
        marks = ",".join("?" for _ in ids)
        row = connection.execute(f"SELECT COUNT(*) FROM ingredients WHERE id IN ({marks})", tuple(ids)).fetchone()
        return row[0] == len(ids)

    def get_recipe(self, connection: sqlite3.Connection, recipe_id: int) -> dict[str, Any] | None:
        row = connection.execute("SELECT id,title,instructions,minutes,source_url FROM recipes WHERE id=?", (recipe_id,)).fetchone()
        if row is None:
            return None
        ingredients = connection.execute("SELECT i.id,i.name,ri.quantity,ri.is_required FROM recipe_ingredients ri JOIN ingredients i ON i.id=ri.ingredient_id WHERE ri.recipe_id=? ORDER BY i.id", (recipe_id,)).fetchall()
        return {"id": row[0], "title": row[1], "instructions": row[2], "minutes": row[3], "source_url": row[4], "ingredients": [{"id": x[0], "name": x[1], "quantity": x[2], "is_required": bool(x[3])} for x in ingredients]}


class MySQLRepository:
    """Thread-safe MySQL repository; only the TCP server constructs this class."""

    def __init__(self, config: dict[str, Any] | None = None, pool_size: int = 32):
        self.config = config or mysql_config_from_env()
        self._pool = pooling.MySQLConnectionPool(
            pool_name=f"goiy_mon_an_{uuid.uuid4().hex[:10]}",
            pool_size=pool_size,
            pool_reset_session=True,
            **self.config,
        )
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "MySQLRepository":
        return cls()

    def connect(self):
        """Return a private pooled connection; caller must close it."""
        connection = self._pool.get_connection()
        connection.autocommit = True
        return connection

    @staticmethod
    def _fetchall(connection, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            cursor.close()

    @staticmethod
    def _fetchone(connection, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
            return cursor.fetchone()
        finally:
            cursor.close()

    def dataset_version(self, connection) -> str:
        row = self._fetchone(connection, "SELECT value FROM metadata WHERE `key`=%s", ("dataset_version",))
        if row is None:
            raise mysql.connector.errors.DatabaseError("missing dataset_version")
        return str(row[0])

    def list_ingredients(self, connection, query: str, limit: int) -> list[dict[str, Any]]:
        normalized = normalize(query.strip())
        escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        rows = self._fetchall(connection, "SELECT DISTINCT i.id,i.name FROM ingredients i LEFT JOIN ingredient_aliases a ON a.ingredient_id=i.id WHERE i.normalized_name LIKE %s ESCAPE '\\\\' OR a.alias_norm LIKE %s ESCAPE '\\\\' ORDER BY i.id LIMIT %s", (pattern, pattern, limit))
        return [{"id": row[0], "name": row[1]} for row in rows]

    def recipes_for_ranking(self, connection) -> list[dict[str, Any]]:
        recipes = self._fetchall(connection, "SELECT id,title,minutes FROM recipes ORDER BY id")
        relations = self._fetchall(connection, "SELECT recipe_id,ingredient_id,is_required FROM recipe_ingredients ORDER BY recipe_id,ingredient_id")
        grouped: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for recipe_id, ingredient_id, is_required in relations:
            grouped[int(recipe_id)].append((int(ingredient_id), int(is_required)))
        return [{"id": int(recipe_id), "title": title, "minutes": int(minutes), "required_ids": {x[0] for x in grouped[int(recipe_id)] if x[1]}, "all_ids": {x[0] for x in grouped[int(recipe_id)]}} for recipe_id, title, minutes in recipes]

    def ingredient_ids_exist(self, connection, ids: set[int]) -> bool:
        if not ids:
            return True
        marks = ",".join("%s" for _ in ids)
        row = self._fetchone(connection, f"SELECT COUNT(*) FROM ingredients WHERE id IN ({marks})", tuple(ids))
        return int(row[0]) == len(ids)

    def get_recipe(self, connection, recipe_id: int) -> dict[str, Any] | None:
        row = self._fetchone(connection, "SELECT id,title,instructions,minutes,source_url FROM recipes WHERE id=%s", (recipe_id,))
        if row is None:
            return None
        ingredients = self._fetchall(connection, "SELECT i.id,i.name,ri.quantity,ri.is_required FROM recipe_ingredients ri JOIN ingredients i ON i.id=ri.ingredient_id WHERE ri.recipe_id=%s ORDER BY i.id", (recipe_id,))
        return {"id": int(row[0]), "title": row[1], "instructions": row[2], "minutes": int(row[3]), "source_url": row[4], "ingredients": [{"id": int(x[0]), "name": x[1], "quantity": x[2], "is_required": bool(x[3])} for x in ingredients]}
