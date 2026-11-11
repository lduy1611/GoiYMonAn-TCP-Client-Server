"""One-time local setup for the least-privilege account-table writer.

Run from a local Terminal. The MySQL root password is prompted with hidden input,
used in memory only, and never printed or saved. No account rows are inserted.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path
import secrets
import sys

import mysql.connector
from dotenv import dotenv_values, set_key

from source.database import v2_user_account_schema
from source.server.repository import MySQLRepository, mysql_config_from_env
from source.database.codex_mysql import _sql_literal

ROOT=Path(__file__).resolve().parents[2]
ENV_FILE=ROOT/".env"
DATABASE="goiy_mon_an"
WRITER="goiy_user_writer"
HOST="127.0.0.1"
PORT=3306


def _query(connection,statement,params=()):
    cursor=connection.cursor()
    try:
        cursor.execute(statement,params)
        return cursor.fetchall() if cursor.with_rows else []
    finally:
        cursor.close()


def _check_legacy(connection):
    expected={"recipes":50,"ingredients":50,"recipe_ingredients":252}
    for table,count in expected.items():
        actual=int(_query(connection,f"SELECT COUNT(*) FROM {table}")[0][0])
        if actual!=count:
            raise RuntimeError(f"Protected legacy count mismatch for {table}; no account changes were made")


def _validate_migration(connection):
    row=_query(connection,"SELECT checksum,schema_hash,execution_result FROM v2_migration_history WHERE version=%s",
               (v2_user_account_schema.VERSION,))
    if (not row or row[0][0]!=v2_user_account_schema.checksum() or row[0][2]!="APPLIED"
            or not v2_user_account_schema.schema_hash_matches(connection,row[0][1])):
        raise RuntimeError("Migration 005 is missing or its checksum/schema is not valid")


def _grant_statements():
    account=f"'{WRITER}'@'localhost'"
    table=f"`{DATABASE}`.`v2_user_accounts`"
    history=f"`{DATABASE}`.`v2_migration_history`"
    return [
        f"GRANT SELECT ON {table} TO {account}",
        f"GRANT INSERT (`username`, `normalized_username`, `password_hash`) ON {table} TO {account}",
        f"GRANT UPDATE (`account_status`, `role`, `last_login_at`) ON {table} TO {account}",
        f"GRANT SELECT ON {history} TO {account}",
    ]


def _validate_account_separation(runtime_user):
    # The runtime account is normally goiy_app; it is supposed to differ from
    # this writer, so its being goiy_app is not an error.
    if runtime_user==WRITER:
        raise RuntimeError("The account writer must remain a separate dedicated MySQL account")


def main():
    values=dotenv_values(ENV_FILE,interpolate=False)
    config=mysql_config_from_env()
    if (config.get("host"),int(config.get("port",0)),config.get("database"))!=(HOST,PORT,DATABASE):
        raise RuntimeError("Configured runtime target is not the approved local MySQL database")
    configured_writer=values.get("MYSQL_USER_ACCOUNT_WRITER_USER")
    if configured_writer and configured_writer!=WRITER:
        raise RuntimeError("A different account writer is already configured; refusing to replace it")
    _validate_account_separation(values.get("MYSQL_USER"))
    root_password=getpass.getpass("MySQL root password for local 127.0.0.1:3306 (hidden; not saved): ")
    if not root_password:
        raise RuntimeError("Empty root password; no changes were made")
    connection=None
    writer_password=secrets.token_urlsafe(40)
    account=f"'{WRITER}'@'localhost'"
    try:
        root_config={**config,"user":"root","password":root_password,"autocommit":True}
        connection=mysql.connector.connect(**root_config)
        identity=_query(connection,"SELECT DATABASE(),CURRENT_USER(),VERSION()")[0]
        if identity[0]!=DATABASE or str(identity[1]).split("@",1)[0]!="root" or not str(identity[2]).startswith("8."):
            raise RuntimeError("Root connection did not resolve to the expected local MySQL 8 target")
        grants=[str(row[0]).casefold() for row in _query(connection,"SHOW GRANTS FOR CURRENT_USER()")]
        if not any("create user" in value for value in grants) or not any("grant option" in value or "all privileges" in value for value in grants):
            raise RuntimeError("Root login lacks CREATE USER or GRANT OPTION; no account changes were made")
        _validate_migration(connection)
        _check_legacy(connection)

        existing=bool(_query(connection,"SELECT 1 FROM mysql.user WHERE user=%s AND host='localhost' LIMIT 1",(WRITER,)))
        if existing:
            raise RuntimeError(
                f"MySQL account {WRITER}@localhost already exists but this .env has no verified matching writer credential; "
                "refusing to change its password or grants."
            )
        _query(connection,f"CREATE USER {account} IDENTIFIED BY {_sql_literal(writer_password)}")
        for statement in _grant_statements():
            _query(connection,statement)
        connection.close();connection=None

        test_config={**config,"user":WRITER,"password":writer_password,"autocommit":False}
        writer=mysql.connector.connect(**test_config)
        try:
            _validate_migration(writer)
            actual_grants=[str(row[0]) for row in _query(writer,"SHOW GRANTS FOR CURRENT_USER()")]
            MySQLRepository._validate_account_writer_grants(actual_grants,DATABASE)
            _query(writer,"SELECT COUNT(*) FROM v2_user_accounts")
        finally:
            writer.close()

        set_key(str(ENV_FILE),"MYSQL_USER_ACCOUNT_WRITER_USER",WRITER,quote_mode="always")
        set_key(str(ENV_FILE),"MYSQL_USER_ACCOUNT_WRITER_PASSWORD",writer_password,quote_mode="always")
        print("User-account writer created and verified. Password was stored in the project .env and was not displayed.")
        print("No account rows were written; goiy_app permissions were not changed.")
        return 0
    except mysql.connector.Error as exc:
        print(f"MySQL setup stopped (connector errno {exc.errno}); no password was printed.",file=sys.stderr)
        return 1
    finally:
        root_password=""
        writer_password=""
        if connection is not None:
            connection.close()


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError,OSError,ValueError) as exc:
        print(str(exc),file=sys.stderr)
        raise SystemExit(1)
