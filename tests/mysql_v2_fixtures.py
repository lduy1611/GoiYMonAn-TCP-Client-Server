"""PRIVATE MYSQL INSTANCE + TEST_ONLY synthetic data. Never uses MYSQL_* credentials.

The instance is initialized under pytest's temp root, bound to loopback on a random
port. All databases are created here and names are checked before teardown. No
real recipe/approval is imported and no original SQL seed is executed.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import uuid

import mysql.connector
import pytest

from source.database.migrate_v2 import run
from source.server.mysql_calculation_catalog import claims, read_snapshot, subject_hash


def sql(connection, statement, params=()):
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(statement, params)
        return cursor.fetchall() if cursor.with_rows else []
    finally:
        cursor.close()


@pytest.fixture(scope="module")
def private_mysql(tmp_path_factory):
    executable = os.getenv("MYSQL_V2_MYSQLD") or shutil.which("mysqld")
    if not executable:
        pytest.skip("Set MYSQL_V2_MYSQLD to run private-instance MySQL integration tests")
    executable = Path(executable).resolve(strict=True)
    root = tmp_path_factory.mktemp("private-mysql-v2").resolve()
    data, temp = root / "data", root / "tmp"
    temp.mkdir()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    common = [str(executable), "--no-defaults", f"--basedir={executable.parent.parent}",
              f"--datadir={data}", f"--tmpdir={temp}"]
    initialized = subprocess.run([*common, "--initialize-insecure", f"--log-error={root / 'initialize.err'}"],
        cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, creationflags=flags)
    assert initialized.returncode == 0, "Private MySQL initialization failed; inspect its test-only log"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = dict(host="127.0.0.1", port=port, user="root", password="", charset="utf8mb4",
                  collation="utf8mb4_unicode_ci", connection_timeout=2, autocommit=True)
    process = subprocess.Popen([*common, f"--port={port}", "--bind-address=127.0.0.1", "--skip-mysqlx",
        "--skip-log-bin", f"--pid-file={root / 'server.pid'}", f"--log-error={root / 'server.err'}"],
        cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    try:
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and process.poll() is None:
            try:
                connection = mysql.connector.connect(**config)
                sql(connection, "SET GLOBAL sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'")
                connection.close()
                break
            except mysql.connector.Error:
                time.sleep(0.1)
        else:
            pytest.fail("Private MySQL did not start; inspect the isolated server.err")
        yield config
    finally:
        if process.poll() is None:
            try:
                connection = mysql.connector.connect(**config)
                try:
                    sql(connection, "SHUTDOWN")
                finally:
                    connection.close()
            except mysql.connector.Error:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=10)


@contextmanager
def database(private_config):
    name = "goiy_v2_test_" + uuid.uuid4().hex[:16]
    assert re.fullmatch(r"goiy_v2_test_[a-f0-9]{16}", name)
    admin = mysql.connector.connect(**private_config)
    connection = None
    try:
        sql(admin, f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        config = {**private_config, "database": name}
        connection = mysql.connector.connect(**config)
        assert sql(connection, "SELECT DATABASE() AS name")[0]["name"] == name
        # Only table DDL, never CREATE DATABASE/USE from the legacy schema file.
        text = (Path(__file__).resolve().parents[1] / "source/database/database.sql").read_text(encoding="utf-8")
        for statement in text.split(";"):
            if statement.strip().startswith("CREATE TABLE"):
                sql(connection, statement)
        sql(connection, "INSERT INTO metadata VALUES('dataset_version','TEST_ONLY_BASE')")
        for i in (1, 2):
            sql(connection, "INSERT INTO ingredients VALUES(%s,%s,%s)", (i, f"TEST_ONLY ingredient {i}", f"test_only_{i}"))
            sql(connection, "INSERT INTO recipes VALUES(%s,%s,%s,10,NULL,%s)",
                (i, f"TEST_ONLY recipe {i}", "TEST_ONLY fabricated steps", "TEST_ONLY DO NOT IMPORT"))
            sql(connection, "INSERT INTO recipe_ingredients VALUES(%s,%s,'TEST_ONLY unstructured',1)", (i, i))
        yield connection, config
    finally:
        if connection:
            connection.close()
        # This name was generated and created above, on our own instance only.
        assert re.fullmatch(r"goiy_v2_test_[a-f0-9]{16}", name)
        sql(admin, f"DROP DATABASE `{name}`")
        admin.close()


@pytest.fixture
def mysql_db(private_mysql):
    with database(private_mysql) as pair:
        yield pair


def legacy_hashes(connection):
    return {table: sha256(json.dumps(sql(connection, f"SELECT * FROM {table} ORDER BY {order}"),
        sort_keys=True, ensure_ascii=True, default=str).encode()).hexdigest()
        for table, order in [("metadata", "`key`"), ("recipes", "id"), ("ingredients", "id"),
                             ("ingredient_aliases", "alias_norm"), ("recipe_ingredients", "recipe_id,ingredient_id")]}


def approve_test_claims(connection):
    """SIMULATES reviews in this fixture DB only, not human approval or an importer."""
    assert sql(connection, "SELECT DATABASE() AS name")[0]["name"].startswith("goiy_v2_test_")
    snapshot = read_snapshot(connection, (1, 2))
    subjects = claims(snapshot)
    owners = {
        "release": ("v2_data_releases", "id", "review_decision_id", "evidence_set_id"),
        "recipe_content": ("v2_recipe_revisions", "id", "content_review_id", "content_evidence_set_id"),
        "servings": ("v2_recipe_revisions", "id", "servings_review_id", "servings_evidence_set_id"),
        "ingredient_identity": ("v2_ingredients", "id", "review_decision_id", "evidence_set_id"),
        "ingredient_form": ("v2_ingredient_forms", "id", "review_decision_id", "evidence_set_id"),
        "unit": ("v2_units", "id", "review_decision_id", "evidence_set_id"),
        "portion_policy": ("v2_portion_policy_versions", "id", "review_decision_id", "evidence_set_id"),
    }
    sql(connection, """INSERT IGNORE INTO v2_sources(id,source_kind,title,document_ref,accessed_at,verification_status)
        VALUES(1,'TEST_ONLY','TEST_ONLY synthetic fixture','TEST_ONLY_NOT_A_REAL_SOURCE',UTC_TIMESTAMP(6),'APPROVED')""")
    start = sql(connection, "SELECT COALESCE(MAX(id),5000)+1 AS next_id FROM v2_review_decisions")[0]["next_id"]
    for number, claim in enumerate(subjects.values(), int(start)):
        sql(connection, "INSERT INTO v2_evidence_sets VALUES(%s,'TEST_ONLY_NOT_REAL_EVIDENCE')", (number,))
        sql(connection, """INSERT INTO v2_evidence(id,source_id,locator,excerpt_or_observation,claim_scope,entity_ref,captured_at)
            VALUES(%s,1,'TEST_ONLY fixture','TEST_ONLY fabricated facts, DO NOT IMPORT',%s,%s,UTC_TIMESTAMP(6))""",
            (number, claim.scope, claim.entity_ref))
        sql(connection, "INSERT INTO v2_evidence_set_members VALUES(%s,%s)", (number, number))
        digest = subject_hash(claim.scope, claim.payload)
        sql(connection, """INSERT INTO v2_review_decisions VALUES(%s,'APPROVED','TEST_ONLY_SIMULATED_REVIEWER',
            UTC_TIMESTAMP(6),'TEST_ONLY_NOT_HUMAN_APPROVAL',%s,%s,%s,%s)""", (number, claim.scope, claim.entity_ref, digest, number))
        if claim.scope in {"quantity", "scaling"}:
            _, revision_id, line_no = claim.entity_ref.split(":")
            prefix = "quantity" if claim.scope == "quantity" else "scaling"
            sql(connection, f"UPDATE v2_recipe_ingredient_lines SET {prefix}_review_id=%s,{prefix}_evidence_set_id=%s WHERE revision_id=%s AND line_no=%s",
                (number, number, revision_id, line_no))
        elif claim.scope == "portion_allocation":
            _, policy_id, rule_no = claim.entity_ref.split(":")
            sql(connection, "UPDATE v2_portion_policy_rules SET review_decision_id=%s,evidence_set_id=%s WHERE policy_version_id=%s AND rule_no=%s",
                (number, number, policy_id, rule_no))
        else:
            table, key, review, evidence = owners[claim.scope]
            entity_id = claim.entity_ref.split(":")[-1]
            sql(connection, f"UPDATE {table} SET {review}=%s,{evidence}=%s WHERE {key}=%s", (number, number, entity_id))
        if claim.scope == "release":
            sql(connection, "UPDATE v2_data_releases SET manifest_hash=%s WHERE id=401", (digest,))


def fixture_release(connection):
    run(connection, "apply")
    for i, name in [(1001, "TEST_ONLY plant"), (1002, "TEST_ONLY liquid")]:
        sql(connection, "INSERT INTO v2_ingredients(id,canonical_name,normalized_name,identity_status) VALUES(%s,%s,%s,'APPROVED')", (i, name, name))
        sql(connection, "INSERT INTO v2_ingredient_forms(id,ingredient_id,form_code,description,status) VALUES(%s,%s,'test_raw','TEST_ONLY raw form','APPROVED')", (i+10, i))
    for i, code, dimension in [(1, "g", "mass"), (2, "ml", "volume")]:
        sql(connection, "INSERT INTO v2_units(id,code,dimension,symbol,definition,status) VALUES(%s,%s,%s,%s,'TEST_ONLY unit','APPROVED')", (i, code, dimension, code))
    for i, base in [(1, 2), (2, 4)]:
        sql(connection, "INSERT INTO v2_recipes(id,legacy_recipe_id,origin_kind) VALUES(%s,%s,'curated_variant')", (100+i, i))
        sql(connection, """INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,instructions,minutes,
            base_servings,serving_basis,content_complete,status)
            VALUES(%s,%s,1,'TEST_ONLY recipe','TEST_ONLY invented steps',10,%s,'source_servings',1,'APPROVED')""", (200+i, 100+i, base))
        sql(connection, """INSERT INTO v2_recipe_ingredient_lines(revision_id,line_no,ingredient_id,form_id,quantity_raw,
            amount_kind,amount_min,unit_id,requirement,purpose,measurement_basis,scaling_mode,status)
            VALUES(%s,1,1001,1011,'TEST_ONLY','exact',%s,1,'required','consumed','edible','linear','APPROVED')""", (200+i, 100 if i==1 else 50))
    sql(connection, """INSERT INTO v2_recipe_ingredient_lines(revision_id,line_no,ingredient_id,form_id,quantity_raw,
        amount_kind,amount_min,amount_max,unit_id,requirement,purpose,measurement_basis,scaling_mode,status)
        VALUES(201,2,1002,1012,'TEST_ONLY','range',200,300,2,'required','consumed','edible','linear','APPROVED')""")
    sql(connection, "INSERT INTO v2_portion_policy_versions(id,policy_code,version,description,status) VALUES(301,'TEST_ONLY','1','TEST_ONLY allocation','APPROVED')")
    for i in (1, 2):
        sql(connection, """INSERT INTO v2_portion_policy_rules(policy_version_id,rule_no,recipe_id,revision_id,
            serving_basis,equivalent_servings,status) VALUES(301,%s,%s,%s,'source_servings',1,'APPROVED')""", (i, 100+i, 200+i))
    sql(connection, """INSERT INTO v2_data_releases(id,code,legacy_dataset_version,status,approved_at)
        VALUES(401,'TEST_ONLY_NOT_REAL_DATA','TEST_ONLY_BASE','PUBLISHED',UTC_TIMESTAMP(6))""")
    for i in (1, 2):
        sql(connection, "INSERT INTO v2_release_recipes VALUES(401,%s,%s)", (100+i, 200+i))
    sql(connection, "INSERT INTO v2_release_portion_policies VALUES(401,'1,2',301)")
    sql(connection, "INSERT INTO v2_calculation_settings VALUES(1,401)")
    approve_test_claims(connection)
