"""Interactively configure local Admin and verify the dedicated draft writer."""
from __future__ import annotations

import getpass
import hashlib
import os
from pathlib import Path
import re
import secrets
import tempfile

import mysql.connector
from dotenv import dotenv_values

from source.server.repository import mysql_config_from_env

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"
WRITER = "goiy_admin_writer"
ROUNDS = 600_000

REVIEW_GRANTS = [
    "GRANT SELECT ON goiy_mon_an.metadata TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_migration_history TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_sources TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT (id, source_kind, title, url, author_or_publisher, accessed_at, usage_note, verification_status), UPDATE (verification_status) ON goiy_mon_an.v2_sources TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_evidence_sets TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT (id, description) ON goiy_mon_an.v2_evidence_sets TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_evidence TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT (id, source_id, locator, excerpt_or_observation, claim_scope, entity_ref, captured_at, content_hash) ON goiy_mon_an.v2_evidence TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_evidence_set_members TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT (evidence_set_id, evidence_id) ON goiy_mon_an.v2_evidence_set_members TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_review_decisions TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT (id, decision, reviewer_ref, decided_at, rationale, claim_scope, entity_ref, subject_hash, evidence_set_id) ON goiy_mon_an.v2_review_decisions TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_ingredient_forms TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_units TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_portion_policy_versions TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_portion_policy_rules TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_release_portion_policies TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_calculation_settings TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT (id, active_release_id), UPDATE (active_release_id) ON goiy_mon_an.v2_calculation_settings TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_data_releases TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT (id, code, legacy_dataset_version, status), UPDATE (approved_at, evidence_set_id, manifest_hash, review_decision_id, status) ON goiy_mon_an.v2_data_releases TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_ingredients TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_recipes TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_recipe_revisions TO 'goiy_admin_writer'@'localhost'",
    "GRANT UPDATE (status, content_complete, content_evidence_set_id, content_review_id) ON goiy_mon_an.v2_recipe_revisions TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_recipe_ingredient_lines TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_recipes TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_release_recipes TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT ON goiy_mon_an.v2_release_recipes TO 'goiy_admin_writer'@'localhost'",
]

INGREDIENT_ADMIN_GRANTS = [
    "GRANT INSERT (id, canonical_name, normalized_name) ON goiy_mon_an.v2_ingredients TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT (identity_status) ON goiy_mon_an.v2_ingredients TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT (legacy_ingredient_id) ON goiy_mon_an.v2_ingredients TO 'goiy_admin_writer'@'localhost'",
    "GRANT UPDATE (canonical_name, normalized_name) ON goiy_mon_an.v2_ingredients TO 'goiy_admin_writer'@'localhost'",
    "GRANT UPDATE (identity_status) ON goiy_mon_an.v2_ingredients TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_ingredient_admin_state TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT (ingredient_id, is_active) ON goiy_mon_an.v2_ingredient_admin_state TO 'goiy_admin_writer'@'localhost'",
    "GRANT UPDATE (is_active) ON goiy_mon_an.v2_ingredient_admin_state TO 'goiy_admin_writer'@'localhost'",
]

LEGACY_INGREDIENT_ADMIN_GRANTS = [
    "GRANT SELECT ON goiy_mon_an.ingredients TO 'goiy_admin_writer'@'localhost'",
    "GRANT SELECT ON goiy_mon_an.v2_admin_legacy_ingredient_overrides TO 'goiy_admin_writer'@'localhost'",
    "GRANT INSERT (ingredient_id, name_override, normalized_name, is_active, updated_by), UPDATE (name_override, normalized_name, is_active, updated_by) ON goiy_mon_an.v2_admin_legacy_ingredient_overrides TO 'goiy_admin_writer'@'localhost'",
]

ALLOWED_GRANTS = {
    "*.*": {"usage"},
    "goiy_mon_an.v2_ingredients": {"select (id)", "select",
        "insert (id, canonical_name, normalized_name)",
        "insert (legacy_ingredient_id)",
        "insert (identity_status)",
        "update (canonical_name, normalized_name)", "update (identity_status)"},
    "goiy_mon_an.v2_ingredient_admin_state": {"select", "insert (ingredient_id, is_active)", "update (is_active)"},
    "goiy_mon_an.ingredients": {"select", "select (id, name, normalized_name)"},
    "goiy_mon_an.v2_admin_legacy_ingredient_overrides": {
        "select", "insert (ingredient_id, name_override, normalized_name, is_active, updated_by)",
        "update (name_override, normalized_name, is_active, updated_by)"},
    # These are the already-installed legacy recipe overlay permissions. The
    # validator must recognize them so unrelated Admin features remain usable.
    "goiy_mon_an.v2_admin_legacy_recipe_overrides": {"select", "insert", "update"},
    "goiy_mon_an.v2_admin_legacy_recipe_override_ingredients": {"select", "insert", "update", "delete"},
    # Existing Admin image lifecycle table; recognize its already-granted CRUD.
    "goiy_mon_an.v2_recipe_image_overrides": {"select", "insert", "update", "delete"},
    "goiy_mon_an.v2_recipes": {"select (id)", "select", "insert (id, origin_kind, author_ref)"},
    "goiy_mon_an.v2_recipe_revisions": {
        "select",
        "select (id, status, content_review_id, servings_review_id)",
        "insert (id, recipe_id, revision_no, title, description, instructions, minutes)",
        "update (title, description, instructions, minutes)",
        "update (status, content_complete, content_evidence_set_id, content_review_id)",
    },
    "goiy_mon_an.v2_release_recipes": {"select (revision_id)", "select", "insert"},
    "goiy_mon_an.v2_recipe_ingredient_lines": {
        "select",
        "select (revision_id, status, quantity_review_id, scaling_review_id)",
        "insert (revision_id, line_no, ingredient_id, quantity_raw, amount_kind, requirement, purpose, measurement_basis)",
        "delete",
    },
    "goiy_mon_an.metadata": {"select"},
    "goiy_mon_an.v2_migration_history": {"select"},
    "goiy_mon_an.v2_sources": {"select", "insert (id, source_kind, title, url, author_or_publisher, accessed_at, usage_note, verification_status)", "update (verification_status)"},
    "goiy_mon_an.v2_evidence_sets": {"select", "insert (id, description)"},
    "goiy_mon_an.v2_evidence": {"select", "insert (id, source_id, locator, excerpt_or_observation, claim_scope, entity_ref, captured_at, content_hash)"},
    "goiy_mon_an.v2_evidence_set_members": {"select", "insert (evidence_set_id, evidence_id)"},
    "goiy_mon_an.v2_review_decisions": {"select", "insert (id, decision, reviewer_ref, decided_at, rationale, claim_scope, entity_ref, subject_hash, evidence_set_id)"},
    "goiy_mon_an.v2_ingredient_forms": {"select"},
    "goiy_mon_an.v2_units": {"select"},
    "goiy_mon_an.v2_portion_policy_versions": {"select"},
    "goiy_mon_an.v2_portion_policy_rules": {"select"},
    "goiy_mon_an.v2_release_portion_policies": {"select"},
    "goiy_mon_an.v2_calculation_settings": {"select", "insert (id, active_release_id)", "update (active_release_id)"},
    "goiy_mon_an.v2_data_releases": {"select", "insert (id, code, legacy_dataset_version, status)",
        "update (approved_at, evidence_set_id, manifest_hash, review_decision_id, status)"},
    # The direct Admin catalog keeps its own public/hidden/deleted state while
    # the underlying recipe content remains a DRAFT revision. These scoped
    # privileges are required by the single-save catalog flow.
    "goiy_mon_an.v2_admin_recipe_catalog_overrides": {"select", "insert", "update"},
}

REQUIRED_GRANTS = {
    "*.*": {"usage"},
    "goiy_mon_an.v2_ingredients": {"select (id)", "select",
        "insert (id, canonical_name, normalized_name)", "insert (legacy_ingredient_id)"},
    "goiy_mon_an.v2_recipes": {"select (id)", "select", "insert (id, origin_kind, author_ref)"},
    "goiy_mon_an.v2_recipe_revisions": {
        "select",
        "select (id, status, content_review_id, servings_review_id)",
        "insert (id, recipe_id, revision_no, title, description, instructions, minutes)",
        "update (title, description, instructions, minutes)",
        "update (status, content_complete, content_evidence_set_id, content_review_id)",
    },
    "goiy_mon_an.v2_release_recipes": {"select (revision_id)", "select", "insert"},
    "goiy_mon_an.v2_recipe_ingredient_lines": {
        "select",
        "select (revision_id, status, quantity_review_id, scaling_review_id)",
        "insert (revision_id, line_no, ingredient_id, quantity_raw, amount_kind, requirement, purpose, measurement_basis)",
        "delete",
    },
    "goiy_mon_an.metadata": {"select"},
    "goiy_mon_an.v2_migration_history": {"select"},
    "goiy_mon_an.v2_sources": {"select", "insert (id, source_kind, title, url, author_or_publisher, accessed_at, usage_note, verification_status)", "update (verification_status)"},
    "goiy_mon_an.v2_evidence_sets": {"select", "insert (id, description)"},
    "goiy_mon_an.v2_evidence": {"select", "insert (id, source_id, locator, excerpt_or_observation, claim_scope, entity_ref, captured_at, content_hash)"},
    "goiy_mon_an.v2_evidence_set_members": {"select", "insert (evidence_set_id, evidence_id)"},
    "goiy_mon_an.v2_review_decisions": {"select", "insert (id, decision, reviewer_ref, decided_at, rationale, claim_scope, entity_ref, subject_hash, evidence_set_id)"},
    "goiy_mon_an.v2_ingredient_forms": {"select"},
    "goiy_mon_an.v2_units": {"select"},
    "goiy_mon_an.v2_portion_policy_versions": {"select"},
    "goiy_mon_an.v2_portion_policy_rules": {"select"},
    "goiy_mon_an.v2_release_portion_policies": {"select"},
    "goiy_mon_an.v2_calculation_settings": {"select", "insert (id, active_release_id)", "update (active_release_id)"},
    "goiy_mon_an.v2_data_releases": {"select", "insert (id, code, legacy_dataset_version, status)",
        "update (approved_at, evidence_set_id, manifest_hash, review_decision_id, status)"},
}

DRAFT_REQUIRED_GRANTS = {
    "*.*": {"usage"},
    "goiy_mon_an.v2_admin_recipe_catalog_overrides": {"select", "insert", "update"},
    # Draft creation only reads the identifier/name to validate a selected
    # legacy catalog item; keep the writer grant column-scoped.
    "goiy_mon_an.ingredients": {"select (id, name)"},
    "goiy_mon_an.v2_admin_legacy_ingredient_overrides": {"select"},
    "goiy_mon_an.v2_ingredient_admin_state": {"select"},
    "goiy_mon_an.v2_ingredients": {
        "select", "insert (id, legacy_ingredient_id, canonical_name, normalized_name)"},
    "goiy_mon_an.v2_recipes": {"select (id)", "insert (id, origin_kind, author_ref)"},
    "goiy_mon_an.v2_recipe_revisions": {
        "select (id, status, content_review_id, servings_review_id)",
        "insert (id, recipe_id, revision_no, title, description, instructions, minutes)",
        "update (title, description, instructions, minutes)"},
    "goiy_mon_an.v2_recipe_ingredient_lines": {
        "select (revision_id, status, quantity_review_id, scaling_review_id)",
        "insert (revision_id, line_no, ingredient_id, quantity_raw, amount_kind, requirement, purpose, measurement_basis)",
        "delete"},
    "goiy_mon_an.v2_release_recipes": {"select (revision_id)"},
}


def _normal(value: str) -> str:
    return " ".join(value.replace("`", "").casefold().split())


INGREDIENT_REQUIRED_GRANTS = {
    "goiy_mon_an.v2_ingredients": {
        "insert (id, canonical_name, normalized_name)",
        "insert (legacy_ingredient_id)",
        "insert (identity_status)",
        "update (canonical_name, normalized_name)",
        "update (identity_status)",
    },
    "goiy_mon_an.v2_ingredient_admin_state": {
        "select", "insert (ingredient_id, is_active)", "update (is_active)",
    },
}

LEGACY_INGREDIENT_REQUIRED_GRANTS = {
    "goiy_mon_an.v2_admin_legacy_ingredient_overrides": {
        "select", "insert (ingredient_id, name_override, normalized_name, is_active, updated_by)",
        "update (name_override, normalized_name, is_active, updated_by)"},
}


def validate_writer_grants(grants: list[str], *, ingredient_admin: bool = False,
                           legacy_ingredient_admin: bool = False, draft_only: bool = False,
                           database: str = "goiy_mon_an") -> None:
    if not grants:
        raise RuntimeError("SHOW GRANTS returned no privileges")
    observed: dict[str, dict[str, set[str] | None]] = {}

    def split_privileges(value: str) -> list[str]:
        result=[]; depth=0; start=0
        for index,char in enumerate(value):
            if char=="(": depth+=1
            elif char==")": depth-=1
            elif char=="," and depth==0:
                result.append(value[start:index].strip());start=index+1
        result.append(value[start:].strip())
        return result

    def parse_privilege(value: str) -> tuple[str, set[str] | None]:
        match = re.fullmatch(r"([a-z ]+)\s*\((.*?)\)", value)
        if not match:
            return value, None
        privilege, columns = match.groups()
        return privilege.strip(), {column.strip() for column in columns.split(",")}

    def allowed_map(privileges: set[str]) -> dict[str, set[str] | None]:
        result: dict[str, set[str] | None] = {}
        for token in privileges:
            privilege, columns = parse_privilege(_normal(token))
            if columns is None or privilege in result and result[privilege] is None:
                result[privilege] = None
            elif privilege not in result:
                result[privilege] = columns
            else:
                result[privilege] |= columns
        return result

    def satisfies(actual: dict[str, set[str] | None], required: dict[str, set[str] | None]) -> bool:
        for privilege, columns in required.items():
            granted = actual.get(privilege, set())
            if columns is None:
                if granted is not None:
                    return False
            elif granted is not None and not columns <= granted:
                return False
        return True

    database = str(database).casefold()
    def database_scope(scope: str) -> str:
        prefix = "goiy_mon_an."
        return database + "." + scope[len(prefix):] if scope.startswith(prefix) else scope

    allowed_by_scope = {database_scope(scope): privileges for scope, privileges in ALLOWED_GRANTS.items()}
    required_grants = DRAFT_REQUIRED_GRANTS if draft_only else REQUIRED_GRANTS
    required_by_scope = {database_scope(scope): privileges for scope, privileges in required_grants.items()}

    for grant in grants:
        normalized = _normal(grant)
        match = re.fullmatch(r"grant (.*?) on (.*?) to .+", normalized)
        if not match:
            raise RuntimeError("Writer grant format is unexpected; refusing broad or unknown privileges")
        privileges, scope = match.groups()
        allowed = allowed_by_scope.get(scope)
        tokens = [parse_privilege(token) for token in split_privileges(privileges)]
        if allowed is None or not tokens:
            raise RuntimeError(f"Writer has an unapproved grant on {scope}; no .env values were changed")
        granted = observed.setdefault(scope, {})
        allowed_privileges = allowed_map(allowed)
        for privilege, columns in tokens:
            if privilege not in allowed_privileges:
                raise RuntimeError(f"Writer has an unapproved grant on {scope}; no .env values were changed")
            allowed_for_privilege = allowed_privileges[privilege]
            if columns is None:
                if allowed_for_privilege is not None:
                    raise RuntimeError(f"Writer has an unapproved grant on {scope}; no .env values were changed")
                granted[privilege] = None
            elif allowed_for_privilege is not None and not columns <= allowed_for_privilege:
                raise RuntimeError(f"Writer has an unapproved grant on {scope}; no .env values were changed")
            elif granted.get(privilege, set()) is not None:
                granted.setdefault(privilege, set()).update(columns)
    for scope, required in required_by_scope.items():
        if not satisfies(observed.get(scope, {}), allowed_map(required)):
            raise RuntimeError(f"Writer is missing required minimum privileges on {scope}")
    if ingredient_admin:
        for scope, required in INGREDIENT_REQUIRED_GRANTS.items():
            if not satisfies(observed.get(scope, {}), allowed_map(required)):
                raise RuntimeError(f"Writer is missing minimum ingredient-admin privileges on {scope}")
    if legacy_ingredient_admin:
        for scope, required in LEGACY_INGREDIENT_REQUIRED_GRANTS.items():
            if not satisfies(observed.get(scope, {}), allowed_map(required)):
                raise RuntimeError(f"Writer is missing minimum legacy ingredient-admin privileges on {scope}")


def _writer_connection(password: str):
    config = mysql_config_from_env()
    connection = mysql.connector.connect(**{**config, "user": WRITER, "password": password})
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT CURRENT_USER(), DATABASE()")
        principal, database = cursor.fetchone()
        if str(principal).split("@", 1)[0] != WRITER or database != "goiy_mon_an":
            raise RuntimeError("Writer authenticated as the wrong MySQL account or database")
        cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
        grants = [row[0] for row in cursor.fetchall()]
        validate_writer_grants(grants)
        cursor.execute("SHOW COLUMNS FROM v2_recipe_revisions LIKE 'description'")
        column = cursor.fetchone()
        if not column or str(column[1]).lower() != "varchar(1000)" or column[2] != "NO" or column[4] != "":
            raise RuntimeError("Migration 003 description column is missing or has an unexpected definition")
        cursor.execute("SELECT COUNT(*) FROM v2_ingredients")
        if int(cursor.fetchone()[0]) < 1:
            raise RuntimeError("No v2 ingredients are available for draft lines")
        cursor.close()
    except Exception:
        connection.close()
        raise
    return connection, principal


def _quote_env(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'").replace("\r", "").replace("\n", "") + "'"


def _write_env(updates: dict[str, str]) -> None:
    old = ENV_FILE.read_text(encoding="utf-8") if ENV_FILE.exists() else ""
    lines = old.splitlines()
    pending = dict(updates)
    seen=set()
    output = []
    key_pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
    for line in lines:
        match = key_pattern.match(line)
        key = match.group(1) if match else None
        if key in pending and key not in seen:
            output.append(f"{key}={_quote_env(pending[key])}")
            seen.add(key)
            pending.pop(key)
        elif key in updates:
            continue
        else:
            output.append(line)
    output.extend(f"{key}={_quote_env(value)}" for key, value in pending.items())
    content = "\n".join(output).rstrip() + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=".env-admin-", suffix=".tmp", dir=ROOT)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, ENV_FILE)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def main() -> int:
    existing = dotenv_values(ENV_FILE, interpolate=False)
    writer_password = existing.get("MYSQL_DRAFT_WRITER_PASSWORD") or os.getenv("MYSQL_DRAFT_WRITER_PASSWORD")
    if writer_password:
        print("Writer password found in configuration; value will not be displayed.")
    else:
        first = getpass.getpass("Nhập mật khẩu MySQL goiy_admin_writer (ẩn): ")
        second = getpass.getpass("Nhập lại mật khẩu writer (ẩn): ")
        if not first or first != second:
            print("Mật khẩu rỗng hoặc không khớp; .env chưa được thay đổi.")
            return 2
        writer_password = first

    connection, principal = _writer_connection(writer_password)
    connection.close()
    username = input("Tên đăng nhập Admin: ").strip()
    if not username or len(username) > 100:
        print("Tên Admin không hợp lệ; .env chưa được thay đổi.")
        return 2
    password = getpass.getpass("Nhập mật khẩu Admin mới (ẩn): ")
    confirmation = getpass.getpass("Nhập lại mật khẩu Admin (ẩn): ")
    if len(password) < 12 or password != confirmation:
        print("Mật khẩu Admin phải khớp và có ít nhất 12 ký tự; .env chưa được thay đổi.")
        return 2
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ROUNDS, dklen=32)
    password_hash = f"pbkdf2_sha256${ROUNDS}${salt.hex()}${digest.hex()}"
    session_secret = secrets.token_urlsafe(48)
    _write_env({
        "MYSQL_DRAFT_WRITER_USER": WRITER,
        "MYSQL_DRAFT_WRITER_PASSWORD": writer_password,
        "ADMIN_USERNAME": username,
        "ADMIN_PASSWORD_HASH": password_hash,
        "ADMIN_SESSION_SECRET": session_secret,
        "ADMIN_COOKIE_SECURE": "false",
    })
    print(f"Writer verified as {principal}; least-privilege grants and migration 003 verified.")
    print("Admin hash and random session secret saved to .env; password values were not printed.")
    print("For local HTTP, bind the web gateway to 127.0.0.1 and restart TCP + FastAPI after setup.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (mysql.connector.Error, RuntimeError, OSError) as exc:
        # Connector diagnostics can contain usernames/hosts; never display credential values.
        print(f"Setup stopped safely: {type(exc).__name__}. .env was not changed unless setup had completed.")
        raise SystemExit(1)
