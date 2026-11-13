"""Export a public catalog snapshot without users or private runtime data.

Only SELECT is issued against the source. Output must be a new directory.
The SQL is for an empty database; it contains no database/user/grant commands.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

import mysql.connector

ROOT = Path(__file__).resolve().parents[1]
TABLES = ("units", "ingredients", "ingredient_aliases", "recipes",
          "recipe_ingredients", "recipe_steps", "recipe_tags", "recipe_tag_links", "recipe_images")
PRIVATE_RECIPE_COLUMNS = {"created_by", "updated_by", "create_request_key", "create_payload_hash"}


def sql_value(value):
    if value is None:
        return "NULL"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, (date, datetime)):
        value = value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if not isinstance(value, str):
        raise ValueError("Unsupported catalog value type")
    # Hex strings are independent of SQL escaping and NO_BACKSLASH_ESCAPES.
    return "CONVERT(X'" + value.encode("utf-8").hex() + "' USING utf8mb4)"


def collect(connection):
    connection.start_transaction(readonly=True, consistent_snapshot=True)
    cursor = connection.cursor(dictionary=True)
    try:
        rows = {}
        for table in TABLES:
            cursor.execute(f"SELECT * FROM `{table}`")
            rows[table] = cursor.fetchall()
        rows["recipes"] = [r for r in rows["recipes"] if r["is_public"] and r["deleted_at"] is None]
        recipe_ids = {r["recipe_id"] for r in rows["recipes"]}
        for table in ("recipe_ingredients", "recipe_steps", "recipe_tag_links", "recipe_images"):
            rows[table] = [r for r in rows[table] if r["recipe_id"] in recipe_ids]
        ingredient_ids = {r["ingredient_id"] for r in rows["recipe_ingredients"]}
        for table in ("ingredients", "ingredient_aliases"):
            rows[table] = [r for r in rows[table] if r["ingredient_id"] in ingredient_ids]
        tag_ids = {r["tag_id"] for r in rows["recipe_tag_links"]}
        rows["recipe_tags"] = [r for r in rows["recipe_tags"] if r["tag_id"] in tag_ids or r["is_core"]]
        for row in rows["recipes"]:
            for column in PRIVATE_RECIPE_COLUMNS:
                row[column] = None
        for table in rows:
            rows[table].sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
        return rows
    finally:
        cursor.close()
        connection.rollback()


def export(connection, destination: Path, image_root: Path):
    if destination.exists():
        raise ValueError("Output directory already exists; refusing to overwrite")
    rows = collect(connection)
    images = []
    for row in rows["recipe_images"]:
        key = row["storage_key"]
        if not re.fullmatch(r"[A-Za-z0-9_-]+\.(?:webp|png|jpg|jpeg)", key):
            raise ValueError("Invalid image storage key")
        path = image_root / key
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != row["sha256"] or path.stat().st_size != row["byte_size"]:
            raise ValueError("Recipe image integrity mismatch")
        images.append({"path": "recipe-images/" + key, "sha256": digest, "bytes": path.stat().st_size})
    schema = (ROOT / "source/database/unified_schema.sql").read_text(encoding="utf-8")
    ddl = re.findall(r"CREATE TABLE IF NOT EXISTS .*?;", schema, re.DOTALL)
    if len(ddl) != 18:
        raise ValueError("Review schema changes before exporting")
    statements = ["-- Public demo only. Import into a NEW EMPTY database ending in _test.",
                  "SET NAMES utf8mb4;", "SET FOREIGN_KEY_CHECKS=0;", *ddl, "START TRANSACTION;"]
    for table, records in rows.items():
        for row in records:
            columns = ",".join(f"`{c}`" for c in row)
            values = ",".join(sql_value(value) for value in row.values())
            statements.append(f"INSERT INTO `{table}` ({columns}) VALUES ({values});")
    statements.extend(["COMMIT;", "SET FOREIGN_KEY_CHECKS=1;"])
    sql = "\n\n".join(statements) + "\n"
    destination.mkdir(parents=True)
    (destination / "recipe-images").mkdir()
    for item in images:
        shutil.copyfile(image_root / Path(item["path"]).name, destination / item["path"])
    (destination / "catalog.sql").write_bytes(sql.encode("utf-8"))
    manifest = {"format": 1, "counts": {table: len(values) for table, values in rows.items()},
                "drinks": sum(r["role"] == "drink" for r in rows["recipes"]),
                "excluded": ["users", "recipe_edit_history", "achievement_posts", "achievement_comments",
                             "achievement_images", "feedback_submissions", "id_maps", "unified_import_runs"],
                "catalog_sha256": hashlib.sha256(sql.encode("utf-8")).hexdigest(), "images": images}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1", "localhost", "::1"))
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, default=ROOT / "statics/runtime/recipe-images")
    args = parser.parse_args()
    password = os.environ.get("DEMO_EXPORT_PASSWORD")
    if password is None:
        password = getpass.getpass("Source MySQL password: ")
    connection = mysql.connector.connect(host=args.host, port=args.port, database=args.database,
                                         user=args.user, password=password, charset="utf8mb4")
    try:
        manifest = export(connection, args.output, args.image_root)
        print(json.dumps({"counts": manifest["counts"], "drinks": manifest["drinks"]}))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
