"""Local MySQL access through Windows Credential Manager.

The root password is never stored. Codex receives project-schema administration
plus CREATE USER (MySQL requires that privilege globally); it has no global data
privileges. Local commands need no repeated prompt.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import getpass
import os
from pathlib import Path
import re
import sys

import mysql.connector
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"
CODEX_TARGET = "GoiyMonAn/MySQL/CodexAdmin"
ADMIN_TARGET = "GoiyMonAn/Web/AdminPassword"
CODEX_USER = "goiy_codex_admin"
DATABASE = "goiy_mon_an"


class CredentialStoreError(RuntimeError):
    pass


class CredentialNotFoundError(CredentialStoreError):
    pass


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR), ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
    ]


def _credential_api():
    if os.name != "nt":
        raise CredentialStoreError("Windows Credential Manager is available only on Windows")
    try:
        api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    except OSError as exc:
        raise CredentialStoreError(f"Could not load Windows Credential Manager (winerror {exc.winerror})") from None
    api.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api


def store_secret(target: str, secret: str, username: str = "") -> None:
    if not secret:
        raise ValueError("Refusing to store an empty credential")
    api = _credential_api()
    blob = secret.encode("utf-8")
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    entry = _CREDENTIALW(
        Flags=0, Type=1, TargetName=target, Comment="Local Hôm nay ăn gì? development credential",
        LastWritten=_FILETIME(), CredentialBlobSize=len(blob), CredentialBlob=buffer,
        Persist=2, AttributeCount=0, Attributes=None, TargetAlias=None, UserName=username,
    )
    if not api.CredWriteW(ctypes.byref(entry), 0):
        raise CredentialStoreError(f"CredWriteW failed (winerror {ctypes.get_last_error()})")


def read_secret(target: str) -> str:
    api = _credential_api()
    pointer = ctypes.POINTER(_CREDENTIALW)()
    if not api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == 1168:
            raise CredentialNotFoundError(f"Credential target is missing: {target} (winerror {error})")
        raise CredentialStoreError(f"CredReadW failed for {target} (winerror {error})")
    try:
        entry = pointer.contents
        return ctypes.string_at(entry.CredentialBlob, entry.CredentialBlobSize).decode("utf-8")
    finally:
        api.CredFree(pointer)


def delete_secret(target: str) -> None:
    api = _credential_api()
    if not api.CredDeleteW(target, 1) and ctypes.get_last_error() != 1168:
        raise ctypes.WinError(ctypes.get_last_error())


def verify_credential_store() -> None:
    """Check local vault access with a temporary, immediately deleted value."""
    import secrets
    target = "GoiyMonAn/BootstrapProbe/" + secrets.token_hex(8)
    probe = secrets.token_urlsafe(24)
    try:
        store_secret(target, probe, "probe")
        if read_secret(target) != probe:
            raise RuntimeError("Windows Credential Manager round-trip failed")
    finally:
        delete_secret(target)


def connect_codex():
    """Connect as goiy_codex_admin; privileges are confined to goiy_mon_an."""
    return mysql.connector.connect(host="127.0.0.1", port=3306, database=DATABASE,
                                   user=CODEX_USER, password=read_secret(CODEX_TARGET),
                                   connection_timeout=5, charset="utf8mb4")


def validate_codex_grants(grants: list[str]) -> None:
    """Allow project-schema administration and user creation, never global DBA grants."""
    if not grants:
        raise RuntimeError("SHOW GRANTS returned no privileges")
    seen_usage = False
    seen_create_user = False
    seen_project_admin = False
    for grant in grants:
        normalized = " ".join(grant.replace("`", "").casefold().split())
        match = re.fullmatch(r"grant (.*?) on (.*?) to .+", normalized)
        if not match:
            raise RuntimeError("Unexpected Codex grant format; refusing unknown privileges")
        privilege, scope = match.groups()
        if scope == "*.*" and privilege == "usage":
            seen_usage = True
        elif scope == "*.*" and privilege == "create user":
            seen_create_user = True
        elif (scope == f"{DATABASE}.*" and privilege == "all privileges"
              and normalized.endswith(" with grant option")):
            seen_project_admin = True
        else:
            raise RuntimeError(f"Codex has an unapproved grant on {scope}")
    # MySQL omits the implicit USAGE row whenever the account has other grants.
    if not (seen_create_user and seen_project_admin):
        raise RuntimeError("Codex account is missing required project administration grants")


def check_connection() -> None:
    try:
        password = read_secret(CODEX_TARGET)
    except CredentialStoreError as exc:
        raise CredentialStoreError(f"Credential lookup failed: {exc}") from None
    try:
        connection = mysql.connector.connect(host="127.0.0.1", port=3306, database=DATABASE,
                                             user=CODEX_USER, password=password,
                                             connection_timeout=5, charset="utf8mb4")
    except mysql.connector.Error as exc:
        raise RuntimeError(f"MySQL connection failed (connector errno {exc.errno})") from None
    try:
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT VERSION()")
            print("MySQL version:", cursor.fetchone()[0])
            cursor.execute("SHOW DATABASES")
            print("Databases:", ", ".join(str(row[0]) for row in cursor.fetchall()))
            cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
            print("Grants:")
            for row in cursor.fetchall():
                print(" ", row[0])
        except mysql.connector.Error as exc:
            raise RuntimeError(f"MySQL verification query failed (connector errno {exc.errno})") from None
        finally:
            cursor.close()
    finally:
        connection.close()


def _sql_literal(value: str) -> str:
    """Quote a MySQL string literal for the account DDL statement."""
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def bootstrap_review_grants() -> None:
    """Recreate the local Codex admin credential and grant review rights to the writer.

    Root is prompted once and is never persisted. The project-scoped Codex account
    follows the existing bootstrap policy; only REVIEW_GRANTS are applied to the
    application writer. No recipe/review/release rows are written by this command.
    """
    import secrets
    from dotenv import load_dotenv
    from source.database import v2_admin_schema, v2_schema
    from source.server.repository import mysql_config_from_env
    from source.web.setup_admin import REVIEW_GRANTS, _writer_connection, validate_writer_grants

    load_dotenv(ENV_FILE, override=True)
    verify_credential_store()
    config = mysql_config_from_env()
    if (config["host"], int(config["port"]), config["database"]) != ("127.0.0.1", 3306, DATABASE):
        raise RuntimeError("Configured database target differs from the approved local database")
    root_password = getpass.getpass("MySQL root password (hidden; not saved): ")
    if not root_password:
        raise RuntimeError("Empty root password; no changes were made")
    root_config = {**config, "user": "root", "password": root_password, "autocommit": True}
    codex_password = secrets.token_urlsafe(48)
    connection = None
    try:
        connection = mysql.connector.connect(**root_config)
        cursor = connection.cursor()
        cursor.execute("SELECT DATABASE(), CURRENT_USER(), VERSION()")
        database, principal, version = cursor.fetchone()
        if database != DATABASE or str(principal).split("@", 1)[0] != "root" or not str(version).startswith("8."):
            raise RuntimeError("Root login did not resolve to the expected local MySQL 8 target")

        cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
        root_grants = [str(row[0]).upper() for row in cursor.fetchall()]
        if not any("CREATE USER" in grant for grant in root_grants):
            raise RuntimeError("Root account lacks CREATE USER")
        if not any("GRANT OPTION" in grant or "ALL PRIVILEGES" in grant for grant in root_grants):
            raise RuntimeError("Root account lacks GRANT OPTION")

        cursor.execute("SELECT version, checksum, execution_result FROM v2_migration_history")
        history = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        expected_history = {
            v2_schema.VERSION: (v2_schema.checksum(), "APPLIED"),
            v2_admin_schema.VERSION: (v2_admin_schema.checksum(), "APPLIED"),
        }
        if history != expected_history:
            raise RuntimeError("Migration history differs from 001 and 003 APPLIED; migration 002 must remain unapplied")

        protected_counts = (
            ("recipes", "SELECT COUNT(*) FROM recipes", 50),
            ("ingredients", "SELECT COUNT(*) FROM ingredients", 50),
            ("recipe_ingredients", "SELECT COUNT(*) FROM recipe_ingredients", 252),
        )
        protected_before = {}
        for label, query, expected in protected_counts:
            cursor.execute(query)
            protected_before[label] = int(cursor.fetchone()[0])
            if protected_before[label] != expected:
                raise RuntimeError(f"Protected legacy count differs for {label}; no account changes were made")
        cursor.execute("SELECT status, COUNT(*) FROM v2_recipe_revisions GROUP BY status")
        statuses = {str(row[0]): int(row[1]) for row in cursor.fetchall()}
        if statuses.get("NEEDS_VERIFICATION", 0) != 9 or set(statuses) - {"DRAFT", "NEEDS_VERIFICATION"}:
            raise RuntimeError("Expected only DRAFT and 9 NEEDS_VERIFICATION revisions; no account changes were made")
        cursor.execute("SELECT COUNT(*) FROM v2_data_releases WHERE status='ACTIVE'")
        if int(cursor.fetchone()[0]) != 0:
            raise RuntimeError("An active release exists; refusing the review-permission bootstrap")
        cursor.execute("SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE()")
        if int(cursor.fetchone()[0]) != 2:
            raise RuntimeError("Trigger count differs from the protected baseline")

        for account in (CODEX_USER, "goiy_admin_writer"):
            cursor.execute("SELECT COUNT(*) FROM mysql.role_edges WHERE TO_USER=%s AND TO_HOST='localhost'", (account,))
            if int(cursor.fetchone()[0]):
                raise RuntimeError(f"{account} has role memberships; refusing inherited privileges")
        cursor.execute("SELECT COUNT(*) FROM mysql.user WHERE user=%s AND host='localhost'", (CODEX_USER,))
        codex_exists = bool(cursor.fetchone()[0])

        account = f"'{CODEX_USER}'@'localhost'"
        if codex_exists:
            cursor.execute(f"REVOKE ALL PRIVILEGES, GRANT OPTION FROM {account}")
            cursor.execute(f"ALTER USER {account} IDENTIFIED BY {_sql_literal(codex_password)}")
        else:
            cursor.execute(f"CREATE USER {account} IDENTIFIED BY {_sql_literal(codex_password)}")
        cursor.execute(f"GRANT CREATE USER ON *.* TO {account}")
        cursor.execute(f"GRANT ALL PRIVILEGES ON {DATABASE}.* TO {account} WITH GRANT OPTION")
        cursor.close()
    except mysql.connector.Error as exc:
        raise RuntimeError(f"MySQL bootstrap failed (connector errno {exc.errno}); no password was logged") from None
    finally:
        if connection is not None:
            connection.close()
        root_password = ""

    # Keep root out of the vault. Only the existing project-scoped Codex account
    # credential is persisted, under the established target name.
    store_secret(CODEX_TARGET, codex_password, CODEX_USER)
    check_connection()
    codex = connect_codex()
    try:
        cursor = codex.cursor()
        for statement in REVIEW_GRANTS:
            cursor.execute(statement)
        cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
        validate_codex_grants([str(row[0]) for row in cursor.fetchall()])
        for label, query, _ in protected_counts:
            cursor.execute(query)
            if int(cursor.fetchone()[0]) != protected_before[label]:
                raise RuntimeError(f"Protected legacy count changed while applying review grants: {label}")
        cursor.execute("SELECT status, COUNT(*) FROM v2_recipe_revisions GROUP BY status")
        if {str(row[0]): int(row[1]) for row in cursor.fetchall()} != statuses:
            raise RuntimeError("Revision statuses changed while applying review grants")
        cursor.execute("SELECT COUNT(*) FROM v2_data_releases WHERE status='ACTIVE'")
        if int(cursor.fetchone()[0]) != 0:
            raise RuntimeError("An active release appeared while applying review grants")
        cursor.close()
    except mysql.connector.Error as exc:
        raise RuntimeError(f"Applying writer review grants failed (connector errno {exc.errno})") from None
    finally:
        codex.close()

    writer, principal = _writer_connection(os.environ.get("MYSQL_DRAFT_WRITER_PASSWORD", ""))
    try:
        cursor = writer.cursor()
        cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
        validate_writer_grants([str(row[0]) for row in cursor.fetchall()])
        cursor.execute("SELECT COUNT(*) FROM v2_recipe_revisions WHERE status='NEEDS_VERIFICATION'")
        if int(cursor.fetchone()[0]) != 9:
            raise RuntimeError("Real NEEDS_VERIFICATION revision count changed unexpectedly")
        cursor.close()
    finally:
        writer.close()
    print("Codex local credential stored and verified; root password was not saved.")
    print("Review/release grants applied to goiy_admin_writer and validated.")
    print("Real revision states were not changed; 9 NEEDS_VERIFICATION revisions remain untouched.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Use local MySQL credentials stored in Windows Credential Manager")
    parser.add_argument("command", choices=("check", "show-admin-password", "bootstrap-review-grants"))
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            check_connection()
        elif args.command == "show-admin-password":
            values = dotenv_values(ENV_FILE, interpolate=False)
            print("Admin username:", values.get("ADMIN_USERNAME") or "(not configured)")
            print(read_secret(ADMIN_TARGET))
        else:
            bootstrap_review_grants()
        return 0
    except (mysql.connector.Error, CredentialStoreError, RuntimeError, OSError) as exc:
        if isinstance(exc, mysql.connector.Error):
            detail = f"MySQL operation failed (connector errno {exc.errno})"
        elif isinstance(exc, CredentialStoreError):
            detail = str(exc)
        else:
            detail = str(exc)
        print(detail, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
