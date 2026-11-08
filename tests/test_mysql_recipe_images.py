"""Private MySQL TEST_ONLY integration for the additive recipe image catalog."""
from hashlib import sha256
import uuid

import mysql.connector
import pytest

from source.common.catalog_ids import v2_public_id
from source.database import migrate_v2
from source.database import v2_context_schema, v2_schema
from source.server.repository import MySQLRepository
from tests.mysql_v2_fixtures import legacy_hashes, mysql_db, private_mysql, sql


def apply_base_migration_only(connection):
    """Set up only 001 for regression coverage; deliberately leave 002 absent."""
    sql(connection, migrate_v2.HISTORY_DDL)
    sql(connection, f"INSERT INTO {migrate_v2.HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
        (v2_schema.VERSION, v2_schema.checksum()))
    for statement in v2_schema.statements():
        sql(connection, statement)
    schema_hash = migrate_v2._schema_hash(connection)
    sql(connection, f"UPDATE {migrate_v2.HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
        (schema_hash, v2_schema.VERSION))


def test_recipe_image_migration_and_writer_round_trip_on_private_test_mysql(mysql_db):
    connection, config = mysql_db
    assert connection.database.startswith("goiy_v2_test_")
    apply_base_migration_only(connection)
    before = legacy_hashes(connection)
    migration = migrate_v2.run_recipe_image_migration(connection, "apply")
    assert migration["recipe_image_state"] == "APPLIED" and migration["changed"] is True
    checked = migrate_v2.run_recipe_image_migration(connection, "check")
    assert checked["changed"] is False
    assert checked["context_state"] == "NOT_APPLIED"
    foreign_keys=sql(connection,"""SELECT COUNT(*) AS n FROM information_schema.KEY_COLUMN_USAGE
        WHERE CONSTRAINT_SCHEMA=DATABASE() AND TABLE_NAME='v2_recipe_image_overrides' AND REFERENCED_TABLE_NAME IS NOT NULL""")[0]["n"]
    assert foreign_keys==2

    private_user = "image_writer_" + uuid.uuid4().hex[:12]
    private_password = "TEST_ONLY_private_image_writer_password"
    sql(connection, f"CREATE USER '{private_user}'@'127.0.0.1' IDENTIFIED BY '{private_password}'")
    database = connection.database
    sql(connection, f"GRANT SELECT,INSERT,UPDATE,DELETE ON `{database}`.v2_recipe_image_overrides TO '{private_user}'@'127.0.0.1'")
    sql(connection, "INSERT INTO v2_recipes(id,origin_kind,author_ref) VALUES(77,'curated_new','TEST_ONLY image fixture')")
    writer_config = {**config, "user": private_user, "password": private_password, "autocommit": False}
    repo = MySQLRepository(config, pool_size=1)
    repo._admin_writer = lambda: mysql.connector.connect(**writer_config)
    try:
        grant_connection = repo._admin_writer()
        try:
            assert repo._image_writer_grants(grant_connection, database)
        finally:
            grant_connection.close()
        image_id = v2_public_id(77)
        one = {"recipe_id": image_id, "storage_key": uuid.uuid4().hex + ".png", "media_type": "image/png",
               "byte_size": 24, "width": 3, "height": 2, "sha256": sha256(b"TEST_ONLY image one").hexdigest()}
        saved = repo.admin_set_recipe_image(connection, one, "TEST_ONLY_ADMIN")
        assert saved["previous_storage_key"] is None
        assert repo.public_recipe_image(connection, 1) is None
        with pytest.raises(mysql.connector.IntegrityError):
            repo.admin_set_recipe_image(connection,{**one,"recipe_id":1},"TEST_ONLY_ADMIN")
        assert sql(connection,"SELECT recipe_id,storage_key FROM v2_recipe_image_overrides")[0]=={
            "recipe_id":image_id,"storage_key":one["storage_key"]}
        two = {**one, "storage_key": uuid.uuid4().hex + ".webp", "media_type": "image/webp",
               "sha256": sha256(b"TEST_ONLY image two").hexdigest()}
        replaced = repo.admin_set_recipe_image(connection,two,"TEST_ONLY_ADMIN")
        assert replaced["previous_storage_key"] == one["storage_key"]
        stored = sql(connection, "SELECT storage_key,catalog_kind,updated_by FROM v2_recipe_image_overrides WHERE recipe_id=%s", (image_id,))[0]
        assert stored == {"storage_key": two["storage_key"], "catalog_kind": "v2", "updated_by": "TEST_ONLY_ADMIN"}
        removed = repo.admin_remove_recipe_image(image_id)
        assert removed["removed"] is True and removed["previous_storage_key"] == two["storage_key"]
        assert sql(connection, "SELECT COUNT(*) AS n FROM v2_recipe_image_overrides")[0]["n"] == 0
        assert legacy_hashes(connection) == before
    finally:
        sql(connection, f"DROP USER '{private_user}'@'127.0.0.1'")


def test_unmarked_context_table_is_still_rejected_after_recipe_image_migration(mysql_db):
    connection, _ = mysql_db
    apply_base_migration_only(connection)
    migrate_v2.run_recipe_image_migration(connection, "apply")
    sql(connection, v2_context_schema.statements()[0])

    with pytest.raises(migrate_v2.MigrationError, match="Context tables exist without their migration marker"):
        migrate_v2.check(connection)
