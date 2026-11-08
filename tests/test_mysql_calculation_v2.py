"""Actual MySQL integration on a private instance, TEST_ONLY fabricated approvals."""
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import re
import shutil
import subprocess

from fastapi.testclient import TestClient
import mysql.connector
import pytest

from source.client.tcp_client import TCPClient
from source.database import migrate_v2
from source.server import mysql_calculation_catalog as adapter
from source.server.meal_plan_calculation import calculate, validate
from source.server.repository import MySQLRepository
from source.web.main import app
from source.web.meal_plan_calculation_contract import CalculationData
from tests.meal_plan_fixtures import running_repository
from tests.mysql_v2_fixtures import (
    approve_test_claims, database, fixture_release, legacy_hashes, mysql_db, private_mysql, sql,
)


def calculation(connection, ids=(1, 2), people=4):
    catalog = adapter.load_catalog(connection, ids)
    data = calculate(validate({"recipe_ids": list(ids), "people": people}), catalog)
    CalculationData.model_validate({"dataset_version": "TEST_ONLY_BASE", **data})
    assert not connection.in_transaction
    return data


def reasons(data):
    return {reason["code"] for recipe in data["recipes"] for reason in recipe["reasons"]}


def test_migration_is_additive_versioned_and_repeatable(mysql_db):
    connection, _ = mysql_db
    baseline = legacy_hashes(connection)
    tables = ("metadata", "recipes", "ingredients", "ingredient_aliases", "recipe_ingredients")
    ddl = {table: sql(connection, f"SHOW CREATE TABLE {table}") for table in tables}
    assert migrate_v2.run(connection)["state"] == "NOT_APPLIED"
    assert not sql(connection, "SHOW TABLES LIKE 'v2_%'")
    first = migrate_v2.run(connection, "apply")
    assert first["changed"] and first["state"] == "APPLIED"
    assert migrate_v2.run(connection, "apply")["changed"] is False
    assert legacy_hashes(connection) == baseline
    assert {table: sql(connection, f"SHOW CREATE TABLE {table}") for table in tables} == ddl
    for table in migrate_v2.v2_schema.tables():
        assert sql(connection, f"SELECT COUNT(*) AS n FROM {table}")[0]["n"] == 0


def test_admin_description_migration_isolated_from_context_002(mysql_db):
    connection, _ = mysql_db
    baseline = legacy_hashes(connection)
    sql(connection, migrate_v2.HISTORY_DDL)
    sql(connection, f"INSERT INTO {migrate_v2.HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
        (migrate_v2.v2_schema.VERSION,migrate_v2.v2_schema.checksum()))
    for statement in migrate_v2.v2_schema.statements():
        sql(connection,statement)
    schema_hash=migrate_v2._schema_hash(connection)
    sql(connection,f"UPDATE {migrate_v2.HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
        (schema_hash,migrate_v2.v2_schema.VERSION))

    before=migrate_v2.check(connection)
    assert before["state"]=="APPLIED" and before["context_state"]=="NOT_APPLIED"
    assert before["admin_draft_state"]=="NOT_APPLIED"
    result=migrate_v2.run_admin_draft_migration(connection,"apply")
    assert result["changed"] and result["context_state"]=="NOT_APPLIED"
    assert result["admin_draft_state"]=="APPLIED"
    assert migrate_v2.run_admin_draft_migration(connection,"apply")["changed"] is False
    assert legacy_hashes(connection)==baseline
    versions={row["version"] for row in sql(connection,f"SELECT version FROM {migrate_v2.HISTORY}")}
    assert versions=={migrate_v2.v2_schema.VERSION,migrate_v2.v2_admin_schema.VERSION}
    column=sql(connection,"SHOW COLUMNS FROM v2_recipe_revisions LIKE 'description'")[0]
    assert column["Type"]=="varchar(1000)" and column["Null"]=="NO" and column["Default"]==""


def test_unmigrated_empty_and_migrated_unreleased_databases_are_incomplete(mysql_db):
    connection, _ = mysql_db
    assert reasons(calculation(connection)) == {"APPROVED_DATA_UNAVAILABLE"}
    migrate_v2.run(connection, "apply")
    assert reasons(calculation(connection)) == {"APPROVED_DATA_UNAVAILABLE"}


def test_complete_actual_mysql_catalog_preserves_namespaces_and_ranges(mysql_db):
    connection, _ = mysql_db
    baseline = legacy_hashes(connection)
    fixture_release(connection)
    data = calculation(connection)
    assert data["status"] == "COMPLETE" and data["totals_complete"]
    assert data["recipe_ids"] == [1, 2]
    assert [r["revision_id"] for r in data["recipes"]] == [201, 202]
    assert data["known_ingredients"][0]["ingredient_id"] == 1001  # v2 namespace, not legacy ingredient 1
    assert data["known_ingredients"][0]["quantity_value"] == "250"
    assert (data["known_ingredients"][1]["quantity_min"], data["known_ingredients"][1]["quantity_max"]) == ("400", "600")
    assert legacy_hashes(connection) == baseline


@pytest.mark.parametrize("statement", [
    "UPDATE v2_recipe_revisions SET status='NEEDS_VERIFICATION' WHERE id=201",
    "UPDATE v2_recipe_revisions SET status='DRAFT' WHERE id=201",
    "UPDATE v2_recipe_ingredient_lines SET status='NEEDS_VERIFICATION' WHERE revision_id=201 AND line_no=1",
    "UPDATE v2_ingredients SET identity_status='NEEDS_VERIFICATION' WHERE id=1001",
    "UPDATE v2_ingredient_forms SET status='NEEDS_VERIFICATION' WHERE id=1011",
    "UPDATE v2_units SET status='NEEDS_VERIFICATION' WHERE id=1",
    "UPDATE v2_portion_policy_versions SET status='DRAFT' WHERE id=301",
    "UPDATE v2_portion_policy_rules SET status='DRAFT' WHERE rule_no=1",
    "UPDATE v2_sources SET verification_status='NEEDS_VERIFICATION' WHERE id=1",
    "UPDATE v2_data_releases SET status='DRAFT' WHERE id=401",
])
def test_unapproved_dependency_never_produces_complete_totals(mysql_db, statement):
    connection, _ = mysql_db
    fixture_release(connection)
    sql(connection, statement)
    data = calculation(connection)
    assert data["status"] == "INCOMPLETE" and not data["totals_complete"]
    assert reasons(data)


@pytest.mark.parametrize("statement,expected", [
    ("UPDATE v2_recipe_ingredient_lines SET amount_min=999 WHERE revision_id=201 AND line_no=1", "LINE_NOT_APPROVED"),
    ("UPDATE v2_recipe_revisions SET base_servings=99 WHERE id=201", "SERVINGS_NOT_APPROVED"),
    ("UPDATE v2_recipe_revisions SET instructions='EDITED_AFTER_REVIEW' WHERE id=201", "REVISION_NOT_APPROVED"),
    ("UPDATE v2_units SET definition='EDITED_AFTER_REVIEW' WHERE id=1", "UNIT_NOT_APPROVED"),
    ("UPDATE v2_portion_policy_rules SET equivalent_servings=99 WHERE rule_no=1", "PORTION_POLICY_UNAVAILABLE"),
    ("DELETE FROM v2_recipe_ingredient_lines WHERE revision_id=201 AND line_no=2", "REVISION_NOT_APPROVED"),
])
def test_editing_approved_values_invalidates_their_review(mysql_db, statement, expected):
    connection, _ = mysql_db
    fixture_release(connection)
    sql(connection, statement)
    data = calculation(connection)
    assert data["status"] == "INCOMPLETE" and expected in reasons(data)


def test_missing_revision_and_newer_unpinned_revision_are_not_substituted(mysql_db):
    connection, _ = mysql_db
    fixture_release(connection)
    # A deliberately reviewed incomplete TEST release, with no mapping for recipe 2.
    sql(connection, "DELETE FROM v2_release_recipes WHERE recipe_id=102")
    approve_test_claims(connection)
    assert "REVISION_NOT_APPROVED" in reasons(calculation(connection))
    # A new, unpinned revision is not automatically chosen.
    sql(connection, """INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,instructions,status)
        VALUES(203,101,2,'TEST_ONLY new revision','TEST_ONLY steps','APPROVED')""")
    assert calculation(connection)["recipes"][0]["revision_id"] == 201


def test_approved_but_invalid_or_unknown_quantities_are_still_incomplete(mysql_db):
    connection, _ = mysql_db
    fixture_release(connection)
    sql(connection, "UPDATE v2_recipe_ingredient_lines SET amount_min=NULL WHERE revision_id=201 AND line_no=1")
    approve_test_claims(connection)  # Simulates a bad TEST review, never a real decision.
    assert "INVALID_QUANTITY" in reasons(calculation(connection))
    sql(connection, "UPDATE v2_recipe_ingredient_lines SET amount_kind='to_taste' WHERE revision_id=201 AND line_no=1")
    approve_test_claims(connection)
    assert "UNKNOWN_QUANTITY" in reasons(calculation(connection))


def test_wrong_scope_or_another_claims_approval_cannot_be_reused(mysql_db):
    connection, _ = mysql_db
    fixture_release(connection)
    sql(connection, """UPDATE v2_recipe_revisions r JOIN v2_units u ON u.id=1
        SET r.servings_review_id=u.review_decision_id,r.servings_evidence_set_id=u.evidence_set_id WHERE r.id=201""")
    assert "SERVINGS_NOT_APPROVED" in reasons(calculation(connection))


def test_legacy_version_mismatch_and_reviewed_membership_edits_are_blocked(mysql_db):
    connection, _ = mysql_db
    fixture_release(connection)
    sql(connection, "UPDATE metadata SET value='TEST_ONLY_CHANGED' WHERE `key`='dataset_version'")
    assert reasons(calculation(connection)) == {"APPROVED_DATA_UNAVAILABLE"}
    sql(connection, "UPDATE metadata SET value='TEST_ONLY_BASE' WHERE `key`='dataset_version'")
    sql(connection, "DELETE FROM v2_release_portion_policies WHERE release_id=401")
    assert reasons(calculation(connection)) == {"APPROVED_DATA_UNAVAILABLE"}


def test_checks_foreign_keys_and_immutable_decisions_are_enforced(mysql_db):
    connection, _ = mysql_db
    fixture_release(connection)
    for statement in [
        "UPDATE v2_recipe_revisions SET base_servings=0 WHERE id=201",
        "UPDATE v2_recipe_ingredient_lines SET amount_min=-1 WHERE revision_id=201 AND line_no=1",
        "UPDATE v2_recipe_ingredient_lines SET amount_max=1 WHERE revision_id=201 AND line_no=2",
        "UPDATE v2_recipe_ingredient_lines SET form_id=1012 WHERE revision_id=201 AND line_no=1",
        "UPDATE v2_release_recipes SET revision_id=202 WHERE recipe_id=101",
        "UPDATE v2_review_decisions SET reviewer_ref='CHANGED' WHERE id=5001",
        "DELETE FROM v2_review_decisions WHERE id=5001",
    ]:
        with pytest.raises(mysql.connector.Error):
            sql(connection, statement)


@pytest.mark.parametrize("change", ["checksum", "version", "schema"])
def test_migration_drift_stops_runner_and_version_drift_disables_adapter(mysql_db, change):
    connection, _ = mysql_db
    fixture_release(connection)
    if change == "checksum":
        sql(connection, "UPDATE v2_migration_history SET checksum=REPEAT('0',64)")
    elif change == "version":
        sql(connection, "UPDATE v2_migration_history SET version='UNKNOWN_TEST_VERSION' WHERE version='001_portion_catalog'")
    else:
        sql(connection, "ALTER TABLE v2_units ADD COLUMN test_drift INT NULL")
    with pytest.raises(migrate_v2.MigrationError):
        migrate_v2.run(connection, "apply")
    if change != "schema":
        assert reasons(calculation(connection)) == {"APPROVED_DATA_UNAVAILABLE"}


def test_partial_ddl_records_failed_and_never_auto_retries(mysql_db, monkeypatch):
    connection, _ = mysql_db
    original = migrate_v2._rows
    def interrupted(c, statement, params=()):
        if statement.startswith("CREATE TABLE v2_units"):
            raise RuntimeError("TEST_ONLY simulated interrupted DDL")
        return original(c, statement, params)
    with monkeypatch.context() as local:
        local.setattr(migrate_v2, "_rows", interrupted)
        with pytest.raises(RuntimeError):
            migrate_v2.run(connection, "apply")
    assert sql(connection, "SELECT execution_result FROM v2_migration_history")[0]["execution_result"] == "FAILED"
    with pytest.raises(migrate_v2.MigrationError):
        migrate_v2.run(connection, "apply")
    assert reasons(calculation(connection)) == {"APPROVED_DATA_UNAVAILABLE"}


def test_disable_rolls_back_activation_without_deleting_data(mysql_db):
    connection, _ = mysql_db
    fixture_release(connection)
    baseline = legacy_hashes(connection)
    before = {t: sql(connection, f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in migrate_v2.v2_schema.tables()}
    assert calculation(connection)["status"] == "COMPLETE"
    outcome = migrate_v2.run(connection, "disable")
    assert outcome["calculation"] == "DISABLED" and outcome["data_deleted"] is False
    assert reasons(calculation(connection)) == {"APPROVED_DATA_UNAVAILABLE"}
    assert {t: sql(connection, f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in before} == before
    assert legacy_hashes(connection) == baseline


def test_adapter_uses_consistent_snapshot_even_if_writer_changes_data(mysql_db, monkeypatch):
    connection, config = mysql_db
    fixture_release(connection)
    original, changed = adapter._query, []
    def interleave(c, statement, params=()):
        if "SELECT * FROM v2_recipe_revisions" in statement and not changed:
            writer = mysql.connector.connect(**config)
            try:
                sql(writer, "UPDATE v2_recipe_ingredient_lines SET amount_min=999 WHERE revision_id=201 AND line_no=1")
                changed.append(True)
            finally:
                writer.close()
        return original(c, statement, params)
    with monkeypatch.context() as local:
        local.setattr(adapter, "_query", interleave)
        data = calculation(connection)
    assert changed and data["status"] == "COMPLETE"
    assert data["known_ingredients"][0]["quantity_value"] == "250"
    assert "LINE_NOT_APPROVED" in reasons(calculation(connection))


@contextmanager
def readonly_repository(connection, config, omit=None):
    import uuid
    user = "v2_test_" + uuid.uuid4().hex[:12]
    database = config["database"]
    sql(connection, f"CREATE USER '{user}'@'127.0.0.1' IDENTIFIED BY 'TEST_ONLY_local_fixture_123!'")
    for row in sql(connection, "SHOW TABLES"):
        table = next(iter(row.values()))
        if table != omit:
            sql(connection, f"GRANT SELECT ON `{database}`.`{table}` TO '{user}'@'127.0.0.1'")
    try:
        yield MySQLRepository({**config, "user": user, "password": "TEST_ONLY_local_fixture_123!"}, pool_size=2)
    finally:
        sql(connection, f"DROP USER '{user}'@'127.0.0.1'")


def test_real_mysql_tcp_http_with_select_only_runtime_and_database_error(mysql_db, monkeypatch, tmp_path):
    connection, config = mysql_db
    fixture_release(connection)
    import source.server.main as server_main
    monkeypatch.setattr(server_main, "LOG_PATH", tmp_path / "TEST_ONLY-tcp.jsonl")
    for omitted in (None, "v2_units"):
        with readonly_repository(connection, config, omitted) as repository:
            with running_repository(repository) as (_, port):
                monkeypatch.setenv("TCP_HOST", "127.0.0.1")
                monkeypatch.setenv("TCP_PORT", str(port))
                client = TCPClient(port=port)
                before = deepcopy(client.request("GET_RECIPE", {"recipe_id": 1}, "e35954bb-19f1-40a6-a8d2-77288ead8050"))
                with TestClient(app) as web:
                    response = web.post('/api/meal-plan/calculate', json={"recipe_ids": [1, 2], "people": 4})
                if omitted is None:
                    assert response.status_code == 200 and response.json()["data"]["status"] == "COMPLETE"
                    assert response.json()["data"]["known_ingredients"][0]["quantity_value"] == "250"
                else:
                    assert response.status_code == 503 and response.json()["error"]["code"] == "DB_ERROR"
                assert client.request("GET_RECIPE", {"recipe_id": 1}, before["request_id"]) == before


def test_migration_checksum_is_portable_across_line_endings(tmp_path, monkeypatch):
    original = migrate_v2.v2_schema.SQL_PATH
    expected = migrate_v2.v2_schema.checksum()
    candidate = tmp_path / 'migration.sql'
    candidate.write_bytes(original.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    monkeypatch.setattr(migrate_v2.v2_schema, 'SQL_PATH', candidate)
    assert migrate_v2.v2_schema.checksum() == expected
    with candidate.open('ab') as stream:
        stream.write(b'\r\n-- changed migration content\r\n')
    assert migrate_v2.v2_schema.checksum() != expected


def test_backup_restore_to_another_private_schema_retains_approved_release(mysql_db, private_mysql, tmp_path):
    connection, config = mysql_db
    fixture_release(connection)
    baseline = legacy_hashes(connection)
    binary = Path(os.getenv('MYSQL_V2_MYSQLD') or shutil.which('mysqld')).parent
    common = ['--no-defaults', '--host=127.0.0.1', f"--port={config['port']}", '--user=root', '--password=']
    backup = tmp_path / 'backup.sql'
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    dumped = subprocess.run([str(binary / 'mysqldump.exe' if os.name == 'nt' else binary / 'mysqldump'),
        *common, '--single-transaction', '--triggers', '--no-tablespaces', '--set-gtid-purged=OFF',
        f'--result-file={backup}', config['database']], cwd=tmp_path, capture_output=True, timeout=30, creationflags=flags)
    assert dumped.returncode == 0, dumped.stderr.decode(errors='replace')
    assert not re.search(r'^USE\s', backup.read_text(encoding='utf-8'), re.M)
    with database(private_mysql) as (clone, clone_config):
        restored = subprocess.run([str(binary / 'mysql.exe' if os.name == 'nt' else binary / 'mysql'),
            *common, f"--database={clone_config['database']}", '--execute=SOURCE backup.sql'],
            cwd=tmp_path, capture_output=True, timeout=30, creationflags=flags)
        assert restored.returncode == 0, restored.stderr.decode(errors='replace')
        assert legacy_hashes(clone) == baseline
        assert migrate_v2.run(clone)['state'] == 'APPLIED'
        assert calculation(clone)['status'] == 'COMPLETE'
