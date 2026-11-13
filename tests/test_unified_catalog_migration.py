from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

import mysql.connector
import pytest

from source.database.unified_catalog_migration import (
    STANDARD_UNITS, UnifiedMigrationError, UnifiedRepository, _legacy_roles, _source_snapshot, create_schema, migrate,
    seed_standard_units,
)
from source.server.meal_plan import generate_meal_plan, validate_meal_plan
from source.server.ranking import rank_recipes
from tests.mysql_v2_fixtures import legacy_hashes, private_mysql, sql

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "statics/runtime/backups/goiy_mon_an-before-pilot5-20261108-214250-49dfe9a7e9464a35a02014a3ba6397c5.sql"
BACKUP_SHA256 = "89D91CC7C9A04C59891EF0A088789EE251C5F985B64A4188CB5E53605076698C"


def _new_db(config, name):
    assert re.fullmatch(r"unified_[a-z]+_test", name)
    admin = mysql.connector.connect(**config)
    try:
        sql(admin, f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    finally:
        admin.close()
    return mysql.connector.connect(**{**config, "database": name})


def _restore_backup(config, name, mysql_cli):
    source = _new_db(config, name)
    source.close()
    command = [str(mysql_cli), "--no-defaults", "--host=127.0.0.1", f"--port={config['port']}",
               "--user=root", "--default-character-set=utf8mb4", f"--database={name}"]
    with BACKUP.open("rb") as dump:
        result = subprocess.run(command, stdin=dump, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")[-1000:]
    return mysql.connector.connect(**{**config, "database": name})


def test_unified_schema_preserves_multiple_lines_duplicate_names_and_role_types(private_mysql):
    db = _new_db(private_mysql, "unified_schema_test")
    try:
        assert create_schema(db) >= 14
        assert int(sql(db, "SELECT COUNT(*) n FROM units")[0]["n"]) == len(STANDARD_UNITS)
        assert seed_standard_units(db) == len(STANDARD_UNITS)
        assert int(sql(db, "SELECT COUNT(*) n FROM units")[0]["n"]) == len(STANDARD_UNITS)
        sql(db, "INSERT INTO ingredients(ingredient_id,name,normalized_name) VALUES(1,'TEST_ONLY A','test_only a'),(2,'TEST_ONLY A','test_only a')")
        sql(db, "INSERT INTO recipes(recipe_id,title,normalized_title,description,role,minutes_total,is_public) VALUES(1,'TEST_ONLY','test_only','','starch',25,1)")
        sql(db, "INSERT INTO recipe_ingredients(recipe_id,line_no,ingredient_id,quantity_text) VALUES(1,1,1,'1 muỗng'),(1,2,1,'ướp riêng'),(1,3,2,'trang trí')")
        assert sql(db, "SELECT COUNT(*) n FROM recipe_ingredients WHERE recipe_id=1 AND ingredient_id=1")[0]["n"] == 2
        assert sql(db, "SELECT role FROM recipes WHERE recipe_id=1")[0]["role"] == "starch"
        assert _legacy_roles()[1] == "main"
        assert _legacy_roles()[5] == "vegetable"
        assert _legacy_roles()[6] == "soup"
        assert int(sql(db, "SELECT COUNT(*) n FROM information_schema.tables WHERE table_schema=DATABASE()")[0]["n"]) >= 14
        with pytest.raises(mysql.connector.IntegrityError):
            sql(db, "INSERT INTO recipe_ingredients(recipe_id,line_no,ingredient_id) VALUES(1,1,2)")
    finally:
        db.close()
        admin = mysql.connector.connect(**private_mysql)
        sql(admin, "DROP DATABASE `unified_schema_test`")
        admin.close()


def test_backup_import_is_repeatable_and_keeps_effective_public_catalog_test_only(private_mysql, tmp_path):
    assert BACKUP.is_file()
    assert sha256(BACKUP.read_bytes()).hexdigest().upper() == BACKUP_SHA256
    with BACKUP.open("r", encoding="utf-8", errors="replace") as dump:
        assert not any(re.search(r"(?im)^\s*(?:CREATE\s+DATABASE|USE)\s+[`\"]?goiy_mon_an\b", line)
                       for line in dump)

    mysqld = Path(os.getenv("MYSQL_V2_MYSQLD") or r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe")
    mysql_cli = mysqld.with_name("mysql.exe")
    if not mysql_cli.is_file():
        pytest.skip("MySQL CLI unavailable for isolated backup restore")

    config = private_mysql
    source = _restore_backup(config, "unified_source_test", mysql_cli)
    target = _new_db(config, "unified_target_test")
    admin = mysql.connector.connect(**config)
    image_target = tmp_path / "unified-target-images"
    try:
        legacy_before = {
            table: int(sql(source, f"SELECT COUNT(*) n FROM {table}")[0]["n"])
            for table in ("recipes", "ingredients", "recipe_ingredients")
        }
        assert legacy_before == {"recipes": 50, "ingredients": 50, "recipe_ingredients": 252}
        legacy_hashes_before = legacy_hashes(source)
        assert int(sql(source, "SELECT COUNT(*) n FROM information_schema.triggers WHERE trigger_schema=DATABASE()")[0]["n"]) == 2
        migrations = {r["version"]: r["execution_result"] for r in sql(source, "SELECT version,execution_result FROM v2_migration_history")}
        assert migrations.get("001_portion_catalog") == "APPLIED"
        assert migrations.get("010_legacy_recipe_catalog_ingredients") == "APPLIED"
        # SQL backups do not contain runtime image bytes. Assert fail-closed
        # first, then explicitly use synthetic PNGs in the restored TEST_ONLY
        # source. Never edit/read-as-valid missing real uploaded images.
        from PIL import Image
        source_images=tmp_path/'TEST_ONLY-source-images';source_images.mkdir()
        create_schema(target)
        with pytest.raises(UnifiedMigrationError,match='unavailable'):
            migrate(source,target,test_only=True,source_image_root=source_images,target_image_root=image_target)
        for row in sql(source,'SELECT recipe_id FROM v2_recipe_image_overrides'):
            key=f"{int(row['recipe_id']):032x}.png"
            path=source_images/key
            Image.new('RGB',(32,32),(30,80,120)).save(path)
            raw=path.read_bytes()
            sql(source,"UPDATE v2_recipe_image_overrides SET storage_key=%s,media_type='image/png',byte_size=%s,width=32,height=32,sha256=%s WHERE recipe_id=%s",
                (key,len(raw),sha256(raw).hexdigest(),row['recipe_id']))
        source_snapshot = _source_snapshot(source)

        assert create_schema(target) == 20
        assert {next(iter(row.values())) for row in sql(target,'SHOW TABLES')} == {
            'users','recipes','ingredients','ingredient_aliases','units','recipe_ingredients',
            'recipe_steps','recipe_tags','recipe_tag_links','recipe_images','recipe_edit_history',
            'recipe_id_map','ingredient_id_map','unified_import_runs','achievement_posts',
            'achievement_images','achievement_comments','feedback_submissions'}
        first = migrate(source, target, test_only=True, source_image_root=source_images,target_image_root=image_target)
        assert first["status"] == "APPLIED_TEST_ONLY"
        assert first["report"]["TEST_ONLY"] is True
        assert first["report"]["legacy_counts"] == {"recipes": 50, "ingredients": 50, "recipe_ingredients": 252}
        assert int(sql(target, "SELECT COUNT(*) n FROM recipes")[0]["n"]) == first["report"]["recipe_count"]
        assert int(sql(target, "SELECT COUNT(*) n FROM ingredients")[0]["n"]) == first["report"]["ingredient_count"]
        assert int(sql(target, "SELECT COUNT(*) n FROM users")[0]["n"]) == first["report"]["account_count"]
        target_accounts = sql(target, "SELECT user_id,username,normalized_username,password_hash,role,status,created_at,updated_at,last_login_at FROM users ORDER BY user_id")
        expected_accounts = sorted(source_snapshot["accounts"], key=lambda row: int(row["user_id"]))
        assert len(target_accounts) == len(expected_accounts)
        for actual, expected in zip(target_accounts, expected_accounts):
            assert (int(actual["user_id"]), actual["username"], actual["normalized_username"], actual["password_hash"],
                    actual["role"], actual["status"]) == (
                    int(expected["user_id"]), expected["username"], expected["normalized_username"],
                    expected["password_hash"], expected["role"], expected["account_status"])

        repo = UnifiedRepository()
        visible = repo.recipes_for_ranking(target)
        names = repo.list_ingredients(target, limit=10000)
        assert {int(r["id"]) for r in visible} == set(source_snapshot["public_recipe_ids"])
        assert {int(row["id"]) for row in names} == set(source_snapshot["public_ingredient_ids"])
        assert all(r["id"] <= 2**53 - 1 for r in visible)
        assert all(row["id"] <= 2**53 - 1 for row in names)
        for recipe_id in source_snapshot["public_recipe_ids"]:
            assert repo.get_recipe(target, recipe_id) is not None
            actual_lines = sql(target, """SELECT line_no,ingredient_id,quantity_text,requirement
                FROM recipe_ingredients WHERE recipe_id=%s ORDER BY line_no""", (recipe_id,))
            expected_lines = source_snapshot["recipe_lines"].get(recipe_id, [])
            assert [(int(r["line_no"]), int(r["ingredient_id"]), r["quantity_text"], r["requirement"])
                    for r in actual_lines] == [(int(r["line_no"]), int(r["ingredient_id"]), r["quantity_text"], r["requirement"])
                                               for r in expected_lines]
        assert int(sql(target, "SELECT COUNT(*) n FROM recipes WHERE deleted_at IS NOT NULL AND is_public=0")[0]["n"]) == sum(
            row["deleted_at"] is not None for row in source_snapshot["recipes"].values())
        assert int(sql(target, "SELECT COUNT(*) n FROM recipe_images")[0]["n"]) == first["report"]["image_metadata_count"]
        assert int(sql(target, """SELECT COUNT(*) n FROM recipe_ingredients ri
            LEFT JOIN recipes r ON r.recipe_id=ri.recipe_id LEFT JOIN ingredients i ON i.ingredient_id=ri.ingredient_id
            WHERE r.recipe_id IS NULL OR i.ingredient_id IS NULL""")[0]["n"]) == 0
        for image in source_snapshot["images"]:
            destination = image_target / image["storage_key"]
            assert destination.is_file()
            assert sha256(destination.read_bytes()).hexdigest() == image["sha256"].lower()
        selected = {int(row["id"]) for row in names[:30]}
        assert isinstance(rank_recipes(visible, selected, set(), None, 5, "proposed"), list)

        roles = repo.meal_classification(target)
        options = validate_meal_plan({"ingredient_ids": [], "excluded_ids": [], "max_minutes": 240,
                                      "max_total_minutes": 720, "max_missing": 50}, "TEST_ONLY")
        plan = generate_meal_plan(visible, options, roles, "TEST_ONLY")
        assert plan["plan"] is None or len({item["recipe_id"] for item in plan["plan"]["items"]}) == 3

        first_ids = {int(r["id"]) for r in visible}
        second = migrate(source, target, test_only=True, source_image_root=source_images,target_image_root=image_target)
        assert second["status"] == "NOOP_ALREADY_APPLIED"
        assert {int(r["id"]) for r in repo.recipes_for_ranking(target)} == first_ids
        legacy_after = {
            table: int(sql(source, f"SELECT COUNT(*) n FROM {table}")[0]["n"])
            for table in ("recipes", "ingredients", "recipe_ingredients")
        }
        assert legacy_after == legacy_before
        assert legacy_hashes(source) == legacy_hashes_before

        partial = _new_db(config, "unified_partial_test")
        try:
            create_schema(partial)
            sql(partial, "INSERT INTO ingredients(ingredient_id,name,normalized_name) VALUES(1,'TEST_ONLY partial','test_only partial')")
            with pytest.raises(UnifiedMigrationError, match="no matching import marker"):
                migrate(source, partial, test_only=True, target_image_root=tmp_path / "partial-images")
            assert int(sql(partial, "SELECT COUNT(*) n FROM recipes")[0]["n"]) == 0
            assert int(sql(partial, "SELECT COUNT(*) n FROM unified_import_runs")[0]["n"]) == 0
        finally:
            partial.close()
            sql(admin, "DROP DATABASE `unified_partial_test`")
    finally:
        source.close()
        target.close()
        sql(admin, "DROP DATABASE `unified_source_test`")
        sql(admin, "DROP DATABASE `unified_target_test`")
        admin.close()
