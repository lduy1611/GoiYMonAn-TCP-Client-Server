"""TEST_ONLY checks for the additive legacy recipe overlay and public filtering."""
import mysql.connector
import pytest

from source.common.protocol import ProtocolError
from source.database import migrate_v2, v2_admin_schema, v2_schema
from source.database.migrate_v2 import run, run_legacy_recipe_overlay_migration
from source.server.handler import dispatch
from source.server.legacy_recipe_overlays import validate_update
from source.server.repository import MySQLRepository
from tests.meal_plan_fixtures import REQUEST_ID
from tests.mysql_v2_fixtures import legacy_hashes, mysql_db, private_mysql, sql


def test_overlay_edit_and_visibility_cover_admin_and_public_paths(mysql_db, monkeypatch):
    connection, config = mysql_db
    run(connection, "apply")
    baseline = legacy_hashes(connection)
    assert run_legacy_recipe_overlay_migration(connection, "check")["legacy_recipe_overlay_state"] == "NOT_APPLIED"
    assert run_legacy_recipe_overlay_migration(connection, "apply")["legacy_recipe_overlay_state"] == "APPLIED"
    repo = MySQLRepository(config, pool_size=1)
    monkeypatch.setattr(repo, "connect", lambda: mysql.connector.connect(**config))
    monkeypatch.setattr(repo, "_admin_writer", lambda: mysql.connector.connect(**config))

    before = dispatch(repo, {"version": 1, "request_id": REQUEST_ID, "op": "GET_RECIPE", "payload": {"recipe_id": 1}})[0]
    assert before["data"]["title"] == "TEST_ONLY recipe 1"
    repo.admin_set_legacy_recipe_visibility({"recipe_id": 1, "is_visible": False}, "TEST_ONLY admin")
    with pytest.raises(ProtocolError) as hidden:
        dispatch(repo, {"version": 1, "request_id": REQUEST_ID, "op": "GET_RECIPE", "payload": {"recipe_id": 1}})
    assert hidden.value.code == "NOT_FOUND"
    ranking_connection=repo.connect()
    try:
        assert all(item["id"] != 1 for item in repo.recipes_for_ranking(ranking_connection))
    finally:
        ranking_connection.close()
    for operation, payload in (
        ("SEARCH_RECIPES", {"query": "TEST_ONLY recipe 1"}),
        ("RECOMMEND", {"ingredient_ids": [1], "algorithm": "baseline"}),
        ("RECOMMEND", {"ingredient_ids": [1], "algorithm": "proposed"}),
        ("GENERATE_MEAL_PLAN", {"ingredient_ids": [1], "max_missing": 1, "max_total_minutes": 60}),
    ):
        response = dispatch(repo, {"version": 1, "request_id": REQUEST_ID, "op": operation, "payload": payload})[0]
        assert all(item.get("recipe_id") != 1 for item in response["data"].get("items", []))
        if operation == "SEARCH_RECIPES":
            assert response["data"]["items"] == []

    repo.admin_set_legacy_recipe_visibility({"recipe_id": 1, "is_visible": True}, "TEST_ONLY admin")
    update = {"recipe_id": 1, "title": "TEST_ONLY overlay title", "description": "TEST_ONLY description",
        "instructions": "TEST_ONLY updated steps", "minutes": 25, "is_visible": True,
        "ingredients": [{"ingredient_id": 2, "quantity": "TEST_ONLY 2 units", "is_required": False}]}
    update=validate_update(update,REQUEST_ID)
    repo.admin_update_legacy_recipe(update, "TEST_ONLY admin")
    detail = dispatch(repo, {"version": 1, "request_id": REQUEST_ID, "op": "GET_RECIPE", "payload": {"recipe_id": 1}})[0]
    assert detail["data"]["title"] == "TEST_ONLY overlay title"
    assert detail["data"]["instructions"] == "TEST_ONLY updated steps"
    assert detail["data"]["minutes"] == 25
    assert detail["data"]["ingredients"] == [{"id": 2, "name": "TEST_ONLY ingredient 2", "quantity": "TEST_ONLY 2 units", "is_required": True}]
    search = dispatch(repo, {"version": 1, "request_id": REQUEST_ID, "op": "SEARCH_RECIPES", "payload": {"query": "TEST_ONLY overlay title"}})[0]
    assert [row["recipe_id"] for row in search["data"]["items"]] == [1]
    assert legacy_hashes(connection) == baseline


def test_invalid_legacy_overlay_is_rejected_without_writes(mysql_db, monkeypatch):
    connection, config = mysql_db
    run(connection, "apply")
    run_legacy_recipe_overlay_migration(connection, "apply")
    repo = MySQLRepository(config, pool_size=1)
    monkeypatch.setattr(repo, "_admin_writer", lambda: mysql.connector.connect(**config))
    payload = {"recipe_id": 1, "title": "TEST_ONLY invalid", "description": "", "instructions": "TEST_ONLY steps",
        "minutes": 10, "is_visible": True,
        "ingredients": [{"ingredient_id": 999, "quantity": "TEST_ONLY", "is_required": True}]}
    with pytest.raises(ValueError, match="ingredient IDs"):
        repo.admin_update_legacy_recipe(payload, "TEST_ONLY admin")
    assert sql(connection, "SELECT COUNT(*) AS n FROM v2_admin_legacy_recipe_overrides")[0]["n"] == 0


def test_migration_hash_check_reports_invisible_triggers_not_schema_drift(mysql_db):
    connection, config = mysql_db
    assert sql(connection, "SELECT DATABASE() AS n")[0]["n"].startswith("goiy_v2_test_")
    sql(connection, migrate_v2.HISTORY_DDL)
    sql(connection, f"INSERT INTO {migrate_v2.HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
        (v2_schema.VERSION, v2_schema.checksum()))
    for statement in v2_schema.statements():
        sql(connection, statement)
    sql(connection, f"UPDATE {migrate_v2.HISTORY} SET execution_result='APPLIED',schema_hash=%s WHERE version=%s",
        (migrate_v2._schema_hash(connection), v2_schema.VERSION))
    sql(connection, f"INSERT INTO {migrate_v2.HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
        (v2_admin_schema.VERSION, v2_admin_schema.checksum()))
    for statement in v2_admin_schema.statements():
        sql(connection, statement)
    sql(connection, f"UPDATE {migrate_v2.HISTORY} SET execution_result='APPLIED',schema_hash=%s WHERE version=%s",
        (migrate_v2._schema_hash(connection), v2_admin_schema.VERSION))

    state = migrate_v2.check(connection)
    assert state["context_state"] == "NOT_APPLIED"  # This regression does not apply migration 002.
    db_name = config["database"]
    user = "test_reader_" + db_name[-8:]
    sql(connection, f"CREATE USER '{user}'@'%' IDENTIFIED BY 'TEST_ONLY_reader_password'")
    sql(connection, f"GRANT SELECT ON `{db_name}`.* TO '{user}'@'%'")
    reader = mysql.connector.connect(**{**config, "user": user, "password": "TEST_ONLY_reader_password"})
    try:
        with pytest.raises(migrate_v2.MigrationError, match="lacks TRIGGER visibility"):
            migrate_v2.check(reader)
    finally:
        reader.close()
