"""Explicit offline DDL runner; importing or starting TCP never applies migrations.

MySQL DDL auto-commits. Failed/partial migrations stop for manual inspection.
Rollback disables the active release, retaining every legacy and v2 data row.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
import re

import mysql.connector

from source.database import v2_schema
from source.database import v2_context_schema
from source.database import v2_admin_schema
from source.database import v2_ingredient_admin_schema
from source.database import v2_user_account_schema
from source.database import v2_legacy_recipe_overlay_schema
from source.database import v2_recipe_image_schema
from source.database import v2_legacy_ingredient_admin_schema
from source.database import v2_admin_recipe_catalog_schema

HISTORY = "v2_migration_history"
HISTORY_DDL = """CREATE TABLE v2_migration_history (
 version VARCHAR(80) CHARACTER SET ascii PRIMARY KEY,
 checksum CHAR(64) CHARACTER SET ascii NOT NULL,
 schema_hash CHAR(64) CHARACTER SET ascii NULL,
 execution_result VARCHAR(16) NOT NULL,
 applied_at DATETIME(6) NULL,
 CHECK (execution_result IN ('APPLYING','APPLIED','FAILED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""


class MigrationError(RuntimeError):
    pass


def _rows(connection, query, params=()):
    cursor = connection.cursor()
    try:
        cursor.execute(query, params)
        return cursor.fetchall() if cursor.with_rows else []
    finally:
        cursor.close()


def _preflight(connection):
    database, version, mode = _rows(connection, "SELECT DATABASE(), VERSION(), @@SESSION.sql_mode")[0]
    if not database or not re.fullmatch(r"[A-Za-z0-9_]{1,64}", database):
        raise MigrationError("An explicit database with a simple identifier is required")
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match or "MariaDB" in version or tuple(map(int, match.groups())) < (8, 0, 16):
        raise MigrationError("Requires MySQL >= 8.0.16 with enforced CHECK constraints")
    if not {"STRICT_TRANS_TABLES", "STRICT_ALL_TABLES"} & set(mode.split(",")):
        raise MigrationError("Strict SQL mode is required")
    names = {row[0] for row in _rows(connection, "SHOW TABLES")}
    if not {"metadata", "recipes", "ingredients", "ingredient_aliases", "recipe_ingredients"} <= names:
        raise MigrationError("The existing legacy schema must be present; this migration never seeds it")
    for table in ("recipes", "ingredients"):
        columns = {r[0]: r[1].lower() for r in _rows(connection, f"SHOW COLUMNS FROM {table}")}
        if columns.get("id") not in {"int unsigned", "int(10) unsigned"}:
            raise MigrationError("Legacy foreign-key IDs must be INT UNSIGNED")
    return database, names


def _schema_hash(connection):
    definitions = []
    for table in sorted([HISTORY, *v2_schema.tables()]):
        definitions.append(_rows(connection, f"SHOW CREATE TABLE {table}")[0][1])
    definitions += [list(r) for r in _rows(connection, """SELECT TRIGGER_NAME, EVENT_MANIPULATION,
        ACTION_TIMING, ACTION_STATEMENT FROM information_schema.TRIGGERS
        WHERE TRIGGER_SCHEMA=DATABASE() AND TRIGGER_NAME IN ('v2_review_no_update','v2_review_no_delete')
        ORDER BY TRIGGER_NAME""")]
    return sha256(json.dumps(definitions, ensure_ascii=True).encode()).hexdigest()


def _can_inspect_review_triggers(connection, database):
    """Whether this principal can see the immutable-review triggers in I_S."""
    try:
        grants = [str(row[0]).replace("`", "").casefold() for row in _rows(connection, "SHOW GRANTS FOR CURRENT_USER()")]
    except mysql.connector.Error:
        return False
    database = database.casefold()
    for grant in grants:
        match = re.match(r"grant\s+(.*?)\s+on\s+(.*?)\s+to\s+", grant)
        if not match:
            continue
        privileges, scope = match.groups()
        tokens = {item.strip().split("(", 1)[0] for item in privileges.split(",")}
        if not ({"trigger", "all privileges"} & tokens):
            continue
        if scope in {"*.*", f"{database}.*", f"{database}.v2_review_decisions"}:
            return True
    return False


def _context_schema_hash(connection):
    definitions = [_rows(connection, f"SHOW CREATE TABLE {table}")[0][1]
                   for table in sorted(v2_context_schema.tables())]
    return sha256(json.dumps(definitions, ensure_ascii=True).encode()).hexdigest()


def check(connection):
    database, names = _preflight(connection)
    base_owned = {HISTORY, *v2_schema.tables()}
    context_owned = set(v2_context_schema.tables())
    ingredient_admin_owned = set(v2_ingredient_admin_schema.TABLES)
    user_account_owned = set(v2_user_account_schema.TABLES)
    legacy_overlay_owned = set(v2_legacy_recipe_overlay_schema.TABLES)
    recipe_image_owned = set(v2_recipe_image_schema.TABLES)
    legacy_ingredient_admin_owned = set(v2_legacy_ingredient_admin_schema.TABLES)
    admin_recipe_catalog_owned = set(v2_admin_recipe_catalog_schema.TABLES)
    owned = (base_owned | context_owned | ingredient_admin_owned | user_account_owned
             | legacy_overlay_owned | recipe_image_owned | legacy_ingredient_admin_owned | admin_recipe_catalog_owned)
    existing = {n for n in names if n.startswith("v2_")}
    if existing - owned:
        raise MigrationError("Unrecognized v2 tables: use the matching migration release")
    if HISTORY not in names:
        if existing:
            raise MigrationError("Unowned or partial v2 schema without migration history")
        return {"database": database, "version": v2_schema.VERSION, "state": "NOT_APPLIED"}
    rows = _rows(connection, f"SELECT version,checksum,schema_hash,execution_result FROM {HISTORY}")
    if not rows and existing == {HISTORY}:
        return {"database": database, "version": v2_schema.VERSION, "state": "NOT_APPLIED"}
    history = {r[0]:r[1:] for r in rows}
    if set(history) - {v2_schema.VERSION, v2_context_schema.VERSION,
                       v2_admin_schema.VERSION, v2_ingredient_admin_schema.VERSION,
                       v2_user_account_schema.VERSION, v2_legacy_recipe_overlay_schema.VERSION,
                       v2_recipe_image_schema.VERSION, v2_legacy_ingredient_admin_schema.VERSION,
                       v2_admin_recipe_catalog_schema.VERSION}:
        raise MigrationError("Unknown migration history; refusing to overwrite")
    if v2_schema.VERSION not in history:
        raise MigrationError("Context migration exists without the base portion migration")
    stored_checksum, schema_hash, state = history[v2_schema.VERSION]
    if stored_checksum != v2_schema.checksum():
        raise MigrationError("Migration checksum mismatch; do not edit an applied migration")
    if state != "APPLIED":
        raise MigrationError("Partial/failed DDL requires manual recovery on a verified backup")
    if not _can_inspect_review_triggers(connection, database):
        raise MigrationError("Cannot validate v2 schema hashes: the current MySQL account lacks TRIGGER visibility; rerun with the migration account")
    admin_state = "NOT_APPLIED"
    if v2_admin_schema.VERSION in history:
        admin_checksum, admin_hash, admin_result = history[v2_admin_schema.VERSION]
        if admin_checksum != v2_admin_schema.checksum():
            raise MigrationError("Admin draft migration checksum mismatch; do not edit an applied migration")
        if admin_result != "APPLIED" or admin_hash != _schema_hash(connection):
            raise MigrationError("Admin draft migration is partial or schema drifted; inspect a verified backup")
        admin_state = "APPLIED"
    elif schema_hash != _schema_hash(connection):
        raise MigrationError("Schema drift detected; refusing to continue")
    context_state = "NOT_APPLIED"
    if v2_context_schema.VERSION in history:
        checksum, context_hash, context_result = history[v2_context_schema.VERSION]
        if checksum != v2_context_schema.checksum():
            raise MigrationError("Context migration checksum mismatch; do not edit an applied migration")
        if context_result != "APPLIED" or not context_owned <= existing or context_hash != _context_schema_hash(connection):
            raise MigrationError("Context migration is partial or schema drifted; inspect a verified backup")
        context_state = "APPLIED"
    elif existing & context_owned:
        raise MigrationError("Context tables exist without their migration marker")
    ingredient_admin_state = "NOT_APPLIED"
    if v2_ingredient_admin_schema.VERSION in history:
        ingredient_checksum, ingredient_hash, ingredient_result = history[v2_ingredient_admin_schema.VERSION]
        if ingredient_checksum != v2_ingredient_admin_schema.checksum():
            raise MigrationError("Admin ingredient migration checksum mismatch; do not edit an applied migration")
        if ingredient_result != "APPLIED" or v2_ingredient_admin_schema.schema_hash(connection) != ingredient_hash:
            raise MigrationError("Admin ingredient migration is partial or schema drifted; inspect a verified backup")
        ingredient_admin_state = "APPLIED"
    elif existing & ingredient_admin_owned:
        raise MigrationError("Admin ingredient table exists without its migration marker")
    user_account_state = "NOT_APPLIED"
    if v2_user_account_schema.VERSION in history:
        account_checksum, account_hash, account_result = history[v2_user_account_schema.VERSION]
        if (account_checksum != v2_user_account_schema.checksum()
                or account_result != "APPLIED"
                or not user_account_owned <= existing
                or not v2_user_account_schema.schema_hash_matches(connection, account_hash)):
            raise MigrationError("User account migration is partial or schema drifted; inspect a verified backup")
        user_account_state = "APPLIED"
    elif existing & user_account_owned:
        raise MigrationError("User account table exists without its migration marker")
    legacy_overlay_state="NOT_APPLIED"
    if v2_legacy_recipe_overlay_schema.VERSION in history:
        overlay_checksum,overlay_hash,overlay_result=history[v2_legacy_recipe_overlay_schema.VERSION]
        if (overlay_checksum!=v2_legacy_recipe_overlay_schema.checksum() or overlay_result!="APPLIED"
                or not legacy_overlay_owned<=existing
                or not v2_legacy_recipe_overlay_schema.schema_hash_matches(connection,overlay_hash)):
            raise MigrationError("Legacy recipe overlay migration is partial or schema drifted")
        legacy_overlay_state="APPLIED"
    elif existing & legacy_overlay_owned:
        raise MigrationError("Legacy recipe overlay tables exist without their migration marker")
    recipe_image_state = "NOT_APPLIED"
    if v2_recipe_image_schema.VERSION in history:
        image_checksum, image_hash, image_result = history[v2_recipe_image_schema.VERSION]
        if (image_checksum != v2_recipe_image_schema.checksum() or image_result != "APPLIED"
                or not recipe_image_owned <= existing
                or not v2_recipe_image_schema.schema_hash_matches(connection, image_hash)):
            raise MigrationError("Recipe image migration is partial or schema drifted")
        recipe_image_state = "APPLIED"
    elif existing & recipe_image_owned:
        raise MigrationError("Recipe image table exists without its migration marker")
    legacy_ingredient_admin_state = "NOT_APPLIED"
    if v2_legacy_ingredient_admin_schema.VERSION in history:
        legacy_ingredient_checksum, legacy_ingredient_hash, legacy_ingredient_result = history[v2_legacy_ingredient_admin_schema.VERSION]
        if (legacy_ingredient_checksum != v2_legacy_ingredient_admin_schema.checksum()
                or legacy_ingredient_result != "APPLIED"
                or not legacy_ingredient_admin_owned <= existing
                or v2_legacy_ingredient_admin_schema.schema_hash(connection) != legacy_ingredient_hash):
            raise MigrationError("Legacy ingredient Admin migration is partial or schema drifted")
        legacy_ingredient_admin_state = "APPLIED"
    elif existing & legacy_ingredient_admin_owned:
        raise MigrationError("Legacy ingredient Admin table exists without its migration marker")
    admin_recipe_catalog_state = "NOT_APPLIED"
    if v2_admin_recipe_catalog_schema.VERSION in history:
        catalog_checksum, catalog_hash, catalog_result = history[v2_admin_recipe_catalog_schema.VERSION]
        if (catalog_checksum != v2_admin_recipe_catalog_schema.checksum() or catalog_result != "APPLIED"
                or not admin_recipe_catalog_owned <= existing
                or v2_admin_recipe_catalog_schema.schema_hash(connection) != catalog_hash):
            raise MigrationError("Admin recipe catalog migration is partial or schema drifted")
        admin_recipe_catalog_state = "APPLIED"
    elif existing & admin_recipe_catalog_owned:
        raise MigrationError("Admin recipe catalog table exists without its migration marker")
    expected_tables = base_owned
    if context_state == "APPLIED":
        expected_tables |= context_owned
    if ingredient_admin_state == "APPLIED":
        expected_tables |= ingredient_admin_owned
    if user_account_state == "APPLIED":
        expected_tables |= user_account_owned
    if legacy_overlay_state == "APPLIED":
        expected_tables |= legacy_overlay_owned
    if recipe_image_state == "APPLIED":
        expected_tables |= recipe_image_owned
    if legacy_ingredient_admin_state == "APPLIED":
        expected_tables |= legacy_ingredient_admin_owned
    if admin_recipe_catalog_state == "APPLIED":
        expected_tables |= admin_recipe_catalog_owned
    if existing != expected_tables:
        raise MigrationError("Owned v2 tables do not match migration history")
    return {"database": database, "version": v2_schema.VERSION, "state": "APPLIED",
            "context_version": v2_context_schema.VERSION, "context_state": context_state,
            "admin_draft_version": v2_admin_schema.VERSION, "admin_draft_state": admin_state,
            "admin_ingredient_version": v2_ingredient_admin_schema.VERSION,
            "admin_ingredient_state": ingredient_admin_state,
            "user_account_version": v2_user_account_schema.VERSION,
            "user_account_state": user_account_state,
            "legacy_recipe_overlay_version":v2_legacy_recipe_overlay_schema.VERSION,
            "legacy_recipe_overlay_state":legacy_overlay_state,
            "recipe_image_version":v2_recipe_image_schema.VERSION,
            "recipe_image_state":recipe_image_state,
            "legacy_ingredient_admin_version":v2_legacy_ingredient_admin_schema.VERSION,
            "legacy_ingredient_admin_state":legacy_ingredient_admin_state,
            "admin_recipe_catalog_version":v2_admin_recipe_catalog_schema.VERSION,
            "admin_recipe_catalog_state":admin_recipe_catalog_state}


def run_recipe_image_migration(connection, action="check"):
    """Apply only migration 007; never modifies recipe, ingredient, or release data."""
    if action not in {"check", "apply"}:
        raise ValueError("invalid recipe image migration action")
    if connection.in_transaction:
        raise MigrationError("A dedicated idle migration connection is required")
    original_autocommit = connection.autocommit
    connection.autocommit = True
    database = _rows(connection, "SELECT DATABASE()")[0][0]
    lock = "portion-v2-" + sha256(str(database).encode()).hexdigest()[:40]
    locked = False
    try:
        locked = _rows(connection, "SELECT GET_LOCK(%s, 5)", (lock,))[0][0] == 1
        if not locked:
            raise MigrationError("Another migration holds the database lock")
        outcome = check(connection)
        if outcome["state"] != "APPLIED":
            raise MigrationError("Base migration 001 must be APPLIED before recipe image migration 007")
        if action == "check" or outcome["recipe_image_state"] == "APPLIED":
            return {**outcome, "changed": False}
        _rows(connection, f"INSERT INTO {HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
              (v2_recipe_image_schema.VERSION, v2_recipe_image_schema.checksum()))
        try:
            for statement in v2_recipe_image_schema.statements():
                _rows(connection, statement)
            schema_hash = v2_recipe_image_schema.schema_hash(connection)
            _rows(connection, f"UPDATE {HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
                  (schema_hash, v2_recipe_image_schema.VERSION))
        except Exception:
            _rows(connection, f"UPDATE {HISTORY} SET execution_result='FAILED' WHERE version=%s",
                  (v2_recipe_image_schema.VERSION,))
            raise
        return {**check(connection), "changed": True}
    finally:
        if locked:
            _rows(connection, "SELECT RELEASE_LOCK(%s)", (lock,))
        connection.autocommit = original_autocommit


def run_user_account_migration(connection, action="check"):
    """Check/apply only migration 005; does not run migration 002 or alter legacy tables."""
    if action not in {"check", "apply"}:
        raise ValueError("invalid user account migration action")
    if connection.in_transaction:
        raise MigrationError("A dedicated idle migration connection is required")
    original_autocommit = connection.autocommit
    connection.autocommit = True
    database = _rows(connection, "SELECT DATABASE()")[0][0]
    lock = "portion-v2-" + sha256(str(database).encode()).hexdigest()[:40]
    locked = False
    try:
        locked = _rows(connection, "SELECT GET_LOCK(%s, 5)", (lock,))[0][0] == 1
        if not locked:
            raise MigrationError("Another migration holds the database lock")
        outcome = check(connection)
        if outcome["state"] != "APPLIED":
            raise MigrationError("Base migration 001 must be APPLIED before user account migration 005")
        if action == "check" or outcome["user_account_state"] == "APPLIED":
            return {**outcome, "changed": False}
        _rows(connection, f"INSERT INTO {HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
              (v2_user_account_schema.VERSION, v2_user_account_schema.checksum()))
        try:
            for statement in v2_user_account_schema.statements():
                _rows(connection, statement)
            schema_hash = v2_user_account_schema.schema_hash(connection)
            _rows(connection, f"UPDATE {HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
                  (schema_hash, v2_user_account_schema.VERSION))
        except Exception:
            _rows(connection, f"UPDATE {HISTORY} SET execution_result='FAILED' WHERE version=%s",
                  (v2_user_account_schema.VERSION,))
            raise
        return {**check(connection), "changed": True}
    finally:
        if locked:
            _rows(connection, "SELECT RELEASE_LOCK(%s)", (lock,))
        connection.autocommit = original_autocommit


def run_admin_ingredient_migration(connection, action="check"):
    """Check/apply only migration 004; never applies migration 002 or changes legacy tables."""
    if action not in {"check", "apply"}:
        raise ValueError("invalid Admin ingredient migration action")
    if connection.in_transaction:
        raise MigrationError("A dedicated idle migration connection is required")
    original_autocommit = connection.autocommit
    connection.autocommit = True
    database = _rows(connection, "SELECT DATABASE()")[0][0]
    lock = "portion-v2-" + sha256(str(database).encode()).hexdigest()[:40]
    locked = False
    try:
        locked = _rows(connection, "SELECT GET_LOCK(%s, 5)", (lock,))[0][0] == 1
        if not locked:
            raise MigrationError("Another migration holds the database lock")
        outcome = check(connection)
        if outcome["state"] != "APPLIED" or outcome["admin_draft_state"] != "APPLIED":
            raise MigrationError("Migrations 001 and 003 must be APPLIED before Admin ingredient state")
        if action == "check" or outcome["admin_ingredient_state"] == "APPLIED":
            return {**outcome, "changed": False}
        _rows(connection, f"INSERT INTO {HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
              (v2_ingredient_admin_schema.VERSION, v2_ingredient_admin_schema.checksum()))
        try:
            for statement in v2_ingredient_admin_schema.statements():
                _rows(connection, statement)
            schema_hash = v2_ingredient_admin_schema.schema_hash(connection)
            _rows(connection, f"UPDATE {HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
                  (schema_hash, v2_ingredient_admin_schema.VERSION))
        except Exception:
            _rows(connection, f"UPDATE {HISTORY} SET execution_result='FAILED' WHERE version=%s",
                  (v2_ingredient_admin_schema.VERSION,))
            raise
        return {**check(connection), "changed": True}
    finally:
        if locked:
            _rows(connection, "SELECT RELEASE_LOCK(%s)", (lock,))
        connection.autocommit = original_autocommit


def run_admin_draft_migration(connection, action="check"):
    """Check/apply only migration 003; never applies the unrelated context migration 002."""
    if action not in {"check", "apply"}:
        raise ValueError("invalid Admin draft migration action")
    if connection.in_transaction:
        raise MigrationError("A dedicated idle migration connection is required")
    original_autocommit = connection.autocommit
    connection.autocommit = True
    database = _rows(connection, "SELECT DATABASE()")[0][0]
    lock = "portion-v2-" + sha256(str(database).encode()).hexdigest()[:40]
    locked = False
    try:
        locked = _rows(connection, "SELECT GET_LOCK(%s, 5)", (lock,))[0][0] == 1
        if not locked:
            raise MigrationError("Another migration holds the database lock")
        outcome = check(connection)
        if outcome["state"] != "APPLIED":
            raise MigrationError("Base migration 001 must be APPLIED before Admin draft migration 003")
        if action == "check" or outcome["admin_draft_state"] == "APPLIED":
            return {**outcome, "changed": False}
        # check() verified the unextended schema hash against migration 001.
        _rows(connection, f"INSERT INTO {HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
              (v2_admin_schema.VERSION, v2_admin_schema.checksum()))
        try:
            for statement in v2_admin_schema.statements():
                _rows(connection, statement)
            schema_hash = _schema_hash(connection)
            _rows(connection, f"UPDATE {HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
                  (schema_hash, v2_admin_schema.VERSION))
        except Exception:
            _rows(connection, f"UPDATE {HISTORY} SET execution_result='FAILED' WHERE version=%s",
                  (v2_admin_schema.VERSION,))
            raise
        return {**check(connection), "changed": True}
    finally:
        if locked:
            _rows(connection, "SELECT RELEASE_LOCK(%s)", (lock,))
        connection.autocommit = original_autocommit


def run_legacy_recipe_overlay_migration(connection, action="check"):
    """Apply only migration 006; it creates Admin overlay tables and never edits legacy rows."""
    if action not in {"check","apply"}:
        raise ValueError("invalid legacy recipe overlay migration action")
    if connection.in_transaction:
        raise MigrationError("A dedicated idle migration connection is required")
    original_autocommit=connection.autocommit
    connection.autocommit=True
    database=_rows(connection,"SELECT DATABASE()")[0][0]
    lock="portion-v2-"+sha256(str(database).encode()).hexdigest()[:40]
    locked=False
    try:
        locked=_rows(connection,"SELECT GET_LOCK(%s,5)",(lock,))[0][0]==1
        if not locked:raise MigrationError("Another migration holds the database lock")
        outcome=check(connection)
        if outcome["state"]!="APPLIED":
            raise MigrationError("Base migration 001 must be APPLIED before legacy recipe overlay migration 006")
        if action=="check" or outcome["legacy_recipe_overlay_state"]=="APPLIED":
            return {**outcome,"changed":False}
        _rows(connection,f"INSERT INTO {HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
              (v2_legacy_recipe_overlay_schema.VERSION,v2_legacy_recipe_overlay_schema.checksum()))
        try:
            for statement in v2_legacy_recipe_overlay_schema.statements():_rows(connection,statement)
            schema_hash=v2_legacy_recipe_overlay_schema.schema_hash(connection)
            _rows(connection,f"UPDATE {HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
                  (schema_hash,v2_legacy_recipe_overlay_schema.VERSION))
        except Exception:
            _rows(connection,f"UPDATE {HISTORY} SET execution_result='FAILED' WHERE version=%s",
                  (v2_legacy_recipe_overlay_schema.VERSION,))
            raise
        return {**check(connection),"changed":True}
    finally:
        if locked:_rows(connection,"SELECT RELEASE_LOCK(%s)",(lock,))
        connection.autocommit=original_autocommit


def run_legacy_ingredient_admin_migration(connection, action="check"):
    """Apply only migration 008; legacy ingredient and recipe rows are untouched."""
    if action not in {"check", "apply"}:
        raise ValueError("invalid legacy ingredient Admin migration action")
    if connection.in_transaction:
        raise MigrationError("A dedicated idle migration connection is required")
    original_autocommit = connection.autocommit
    connection.autocommit = True
    database = _rows(connection, "SELECT DATABASE()")[0][0]
    lock = "portion-v2-" + sha256(str(database).encode()).hexdigest()[:40]
    locked = False
    try:
        locked = _rows(connection, "SELECT GET_LOCK(%s,5)", (lock,))[0][0] == 1
        if not locked:
            raise MigrationError("Another migration holds the database lock")
        outcome = check(connection)
        if outcome["state"] != "APPLIED" or outcome["admin_ingredient_state"] != "APPLIED":
            raise MigrationError("Migrations 001 and 004 must be APPLIED before migration 008")
        if action == "check" or outcome["legacy_ingredient_admin_state"] == "APPLIED":
            return {**outcome, "changed": False}
        _rows(connection, f"INSERT INTO {HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
              (v2_legacy_ingredient_admin_schema.VERSION, v2_legacy_ingredient_admin_schema.checksum()))
        try:
            for statement in v2_legacy_ingredient_admin_schema.statements():
                _rows(connection, statement)
            schema_hash = v2_legacy_ingredient_admin_schema.schema_hash(connection)
            _rows(connection, f"UPDATE {HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
                  (schema_hash, v2_legacy_ingredient_admin_schema.VERSION))
        except Exception:
            _rows(connection, f"UPDATE {HISTORY} SET execution_result='FAILED' WHERE version=%s",
                  (v2_legacy_ingredient_admin_schema.VERSION,))
            raise
        return {**check(connection), "changed": True}
    finally:
        if locked:
            _rows(connection, "SELECT RELEASE_LOCK(%s)", (lock,))
        connection.autocommit = original_autocommit


def run_admin_recipe_catalog_migration(connection, action="check"):
    """Apply only additive migration 009 for direct Admin publication/state."""
    if action not in {"check", "apply"}:
        raise ValueError("invalid Admin recipe catalog migration action")
    if connection.in_transaction:
        raise MigrationError("A dedicated idle migration connection is required")
    original_autocommit=connection.autocommit
    connection.autocommit=True
    database=_rows(connection,"SELECT DATABASE()")[0][0]
    lock="portion-v2-"+sha256(str(database).encode()).hexdigest()[:40]
    locked=False
    try:
        locked=_rows(connection,"SELECT GET_LOCK(%s,5)",(lock,))[0][0]==1
        if not locked:raise MigrationError("Another migration holds the database lock")
        outcome=check(connection)
        if outcome["state"]!="APPLIED" or outcome["admin_draft_state"]!="APPLIED":
            raise MigrationError("Migrations 001 and 003 must be APPLIED before migration 009")
        if action=="check" or outcome["admin_recipe_catalog_state"]=="APPLIED":
            return {**outcome,"changed":False}
        _rows(connection,f"INSERT INTO {HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
              (v2_admin_recipe_catalog_schema.VERSION,v2_admin_recipe_catalog_schema.checksum()))
        try:
            for statement in v2_admin_recipe_catalog_schema.statements():_rows(connection,statement)
            schema_hash=v2_admin_recipe_catalog_schema.schema_hash(connection)
            _rows(connection,f"UPDATE {HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
                  (schema_hash,v2_admin_recipe_catalog_schema.VERSION))
        except Exception:
            _rows(connection,f"UPDATE {HISTORY} SET execution_result='FAILED' WHERE version=%s",
                  (v2_admin_recipe_catalog_schema.VERSION,))
            raise
        return {**check(connection),"changed":True}
    finally:
        if locked:_rows(connection,"SELECT RELEASE_LOCK(%s)",(lock,))
        connection.autocommit=original_autocommit


def run(connection, action="check"):
    if action not in {"check", "apply", "disable"}:
        raise ValueError("invalid migration action")
    if connection.in_transaction:
        raise MigrationError("A dedicated idle migration connection is required")
    original_autocommit = connection.autocommit
    connection.autocommit = True
    database = _rows(connection, "SELECT DATABASE()")[0][0]
    lock = "portion-v2-" + sha256(str(database).encode()).hexdigest()[:40]
    locked = False
    try:
        locked = _rows(connection, "SELECT GET_LOCK(%s, 5)", (lock,))[0][0] == 1
        if not locked:
            raise MigrationError("Another migration holds the database lock")
        outcome = check(connection)
        if action == "check":
            return outcome
        if action == "disable":
            if outcome["state"] == "APPLIED":
                _rows(connection, "UPDATE v2_calculation_settings SET active_release_id=NULL WHERE id=1")
            return {**outcome, "calculation": "DISABLED", "data_deleted": False}
        if outcome["state"] == "APPLIED" and outcome.get("context_state") == "APPLIED":
            return {**outcome, "changed": False}
        changed = False
        if outcome["state"] == "NOT_APPLIED":
            if HISTORY not in {r[0] for r in _rows(connection, "SHOW TABLES")}:
                _rows(connection, HISTORY_DDL)
            _rows(connection, f"INSERT INTO {HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
                  (v2_schema.VERSION, v2_schema.checksum()))
            try:
                for statement in v2_schema.statements():
                    _rows(connection, statement)
                schema_hash = _schema_hash(connection)
                _rows(connection, f"UPDATE {HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
                      (schema_hash, v2_schema.VERSION))
            except Exception:
                _rows(connection, f"UPDATE {HISTORY} SET execution_result='FAILED' WHERE version=%s", (v2_schema.VERSION,))
                raise
            outcome = check(connection)
            changed = True
        if outcome.get("context_state") == "NOT_APPLIED":
            _rows(connection, f"INSERT INTO {HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
                  (v2_context_schema.VERSION, v2_context_schema.checksum()))
            try:
                for statement in v2_context_schema.statements():
                    _rows(connection, statement)
                schema_hash = _context_schema_hash(connection)
                _rows(connection, f"UPDATE {HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
                      (schema_hash, v2_context_schema.VERSION))
            except Exception:
                _rows(connection, f"UPDATE {HISTORY} SET execution_result='FAILED' WHERE version=%s", (v2_context_schema.VERSION,))
                raise
            outcome = check(connection)
        return {**outcome, "changed": changed}
    finally:
        if locked:
            _rows(connection, "SELECT RELEASE_LOCK(%s)", (lock,))
        connection.autocommit = original_autocommit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, help="Explicit target; no default application DB")
    parser.add_argument("--action", choices=["check", "apply", "disable"], default="check")
    parser.add_argument("--migration", choices=["core", "admin-draft-description", "admin-ingredient-state", "user-accounts", "legacy-recipe-overlays", "recipe-images", "legacy-ingredient-overrides", "admin-recipe-catalog"], default="core")
    args = parser.parse_args()
    from source.server.repository import mysql_config_from_env
    config = mysql_config_from_env()
    config["database"] = args.database
    for key in ("user", "password"):
        override = os.getenv("MYSQL_MIGRATION_" + key.upper())
        if override is not None:
            config[key] = override
    connection = mysql.connector.connect(**config)
    try:
        if args.migration == "admin-draft-description":
            if args.action == "disable":
                parser.error("--action disable is not valid for the additive Admin schema migration")
            print(json.dumps(run_admin_draft_migration(connection, args.action)))
        elif args.migration == "admin-ingredient-state":
            if args.action == "disable":
                parser.error("--action disable is not valid for the additive Admin schema migration")
            print(json.dumps(run_admin_ingredient_migration(connection, args.action)))
        elif args.migration == "user-accounts":
            if args.action == "disable":
                parser.error("--action disable is not valid for the additive user account migration")
            print(json.dumps(run_user_account_migration(connection, args.action)))
        elif args.migration == "legacy-recipe-overlays":
            if args.action == "disable":
                parser.error("--action disable is not valid for the additive legacy overlay migration")
            print(json.dumps(run_legacy_recipe_overlay_migration(connection,args.action)))
        elif args.migration == "recipe-images":
            if args.action == "disable":
                parser.error("--action disable is not valid for additive recipe image migration")
            print(json.dumps(run_recipe_image_migration(connection, args.action)))
        elif args.migration == "legacy-ingredient-overrides":
            if args.action == "disable":
                parser.error("--action disable is not valid for additive legacy ingredient migration")
            print(json.dumps(run_legacy_ingredient_admin_migration(connection, args.action)))
        elif args.migration == "admin-recipe-catalog":
            if args.action == "disable":
                parser.error("--action disable is not valid for migration 009")
            print(json.dumps(run_admin_recipe_catalog_migration(connection,args.action)))
        else:
            print(json.dumps(run(connection, args.action)))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
