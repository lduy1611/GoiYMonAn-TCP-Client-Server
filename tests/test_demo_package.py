"""Checks that the distributable catalog keeps images and excludes private data."""
import hashlib
import json
from pathlib import Path
import re

from scripts.export_public_demo import PRIVATE_RECIPE_COLUMNS, TABLES, collect

ROOT = Path(__file__).resolve().parents[1]


def test_packaged_catalog_integrity_and_public_scope():
    base = ROOT / "data/demo"
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    data = (base / "catalog.sql").read_bytes()
    assert hashlib.sha256(data).hexdigest() == manifest["catalog_sha256"]
    sql = data.decode("utf-8")
    tables = re.findall(r"INSERT INTO `([^`]+)`", sql)
    assert set(tables) == set(TABLES)
    assert {table: tables.count(table) for table in TABLES} == manifest["counts"]
    assert manifest["counts"]["recipes"] == 226
    assert manifest["drinks"] == 10
    for image in manifest["images"]:
        path = base / image["path"]
        assert path.resolve().is_relative_to(base.resolve())
        content = path.read_bytes()
        assert len(content) == image["bytes"]
        assert hashlib.sha256(content).hexdigest() == image["sha256"]
    assert len(manifest["images"]) == manifest["counts"]["recipe_images"] == 174


def test_collect_removes_private_owners_hidden_recipes_and_unreferenced_images():
    class Cursor:
        def execute(self, sql):
            self.table = re.search(r"`([^`]+)`", sql)[1]

        def fetchall(self):
            return {
                "recipes": [dict(recipe_id=1, is_public=1, deleted_at=None,
                                 **dict.fromkeys(PRIVATE_RECIPE_COLUMNS, "PRIVATE")),
                            dict(recipe_id=2, is_public=0, deleted_at=None)],
                "recipe_images": [dict(recipe_id=1), dict(recipe_id=2)],
                "recipe_ingredients": [dict(recipe_id=1, ingredient_id=3)],
                "ingredients": [dict(ingredient_id=3), dict(ingredient_id=4)],
            }.get(self.table, [])

        def close(self):
            pass

    class Connection:
        def start_transaction(self, **kwargs):
            assert kwargs == dict(readonly=True, consistent_snapshot=True)

        def cursor(self, **kwargs):
            return Cursor()

        def rollback(self):
            self.rolled_back = True

    connection = Connection()
    rows = collect(connection)
    assert connection.rolled_back
    assert len(rows["recipes"]) == 1
    assert all(rows["recipes"][0][key] is None for key in PRIVATE_RECIPE_COLUMNS)
    assert rows["recipe_images"] == [dict(recipe_id=1)]
    assert rows["ingredients"] == [dict(ingredient_id=3)]
