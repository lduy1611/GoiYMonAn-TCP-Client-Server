"""Admin v2 ingredient lifecycle; all database rows are TEST_ONLY and isolated."""
import socket
import threading
import time
import mysql.connector
import pytest
from fastapi.testclient import TestClient

from source.database import migrate_v2, v2_admin_schema, v2_schema
from source.server import admin_ingredients
from source.server.main import TCPServer
from source.server.repository import AdminIngredientConflict, MySQLRepository
from source.web.setup_admin import INGREDIENT_ADMIN_GRANTS, REQUIRED_GRANTS, validate_writer_grants
from tests.mysql_v2_fixtures import mysql_db, private_mysql, sql, legacy_hashes
from tests.test_admin import hash_for
from source.web.main import app


def _install_001_and_003(connection):
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


def test_vietnamese_name_validation_normalizes_unicode_and_rejects_controls():
    name, normalized = admin_ingredients.normalize_name("  Hành   Lá  ")
    assert name == "Hành Lá"
    assert normalized == "hành lá"
    with pytest.raises(Exception):
        admin_ingredients.validate_create({"name": "\x00"}, "TEST_ONLY")


def test_admin_ingredient_migration_and_lifecycle_are_additive(mysql_db, monkeypatch):
    connection, config = mysql_db
    sql(connection,"UPDATE ingredients SET name='Ớt đỏ',normalized_name='ớt đỏ' WHERE id=1")
    sql(connection,"UPDATE ingredients SET name='Hành lá',normalized_name='hành lá' WHERE id=2")
    legacy_before = legacy_hashes(connection)
    _install_001_and_003(connection)
    assert migrate_v2.check(connection)["context_state"] == "NOT_APPLIED"
    sql(connection,"INSERT INTO v2_evidence_sets(id,description) VALUES(1,'TEST_ONLY identity evidence')")
    sql(connection, """INSERT INTO v2_ingredients
        (id,legacy_ingredient_id,canonical_name,normalized_name,identity_status,evidence_set_id)
        VALUES(50001,1,'Ớt đỏ','ớt đỏ','DRAFT',NULL),(50002,2,'Hành lá','hành lá','NEEDS_VERIFICATION',1),
              (50004,NULL,'TEST_ONLY reviewed ingredient','test_only reviewed ingredient','NEEDS_VERIFICATION',1)""")
    applied = migrate_v2.run_admin_ingredient_migration(connection, "apply")
    assert applied["admin_ingredient_state"] == "APPLIED"
    assert applied["context_state"] == "NOT_APPLIED"
    assert sql(connection, "SELECT ingredient_id,is_active FROM v2_ingredient_admin_state ORDER BY ingredient_id") == [
        {"ingredient_id":50001,"is_active":1},{"ingredient_id":50002,"is_active":1},
        {"ingredient_id":50004,"is_active":1}]

    repository = MySQLRepository(config, pool_size=1)
    def test_writer():
        return mysql.connector.connect(**{**config,"autocommit":False})
    monkeypatch.setattr(repository, "_admin_writer", test_writer)
    monkeypatch.setattr(repository, "admin_ingredient_writer_ready", lambda: True)

    listed = repository.admin_list_ingredients(connection, "ot do", limit=10)
    assert listed["total"] == 1
    assert listed["items"][0]["ingredient_id"] == 1
    assert listed["items"][0]["usage_count"] == 1
    assert listed["items"][0]["can_edit"] is False

    created = repository.admin_create_ingredient(admin_ingredients.validate_create({"name":"  Rau   cải  "}, "TEST_ONLY"))
    assert created["name"] == "Rau cải"
    assert created["identity_status"] == "DRAFT"
    assert created["is_active"] is True
    with pytest.raises(AdminIngredientConflict, match="normalized"):
        repository.admin_create_ingredient(admin_ingredients.validate_create({"name":"RAU CAI"}, "TEST_ONLY"))

    renamed = repository.admin_update_ingredient(admin_ingredients.validate_update(
        {"ingredient_id":created["ingredient_id"],"name":"  Cải   thìa "}, "TEST_ONLY"))
    assert renamed["name"] == "Cải thìa"
    from source.common.catalog_ids import V2_OFFSET
    with pytest.raises(AdminIngredientConflict, match="evidence"):
        repository.admin_update_ingredient(admin_ingredients.validate_update(
            {"ingredient_id":V2_OFFSET+50004,"name":"Hành hoa"}, "TEST_ONLY"))

    repository.admin_set_ingredient_active({"ingredient_id":created["ingredient_id"],"is_active":False})
    inactive = repository.admin_list_ingredients(connection, "cai thia", limit=10, catalog="v2")
    assert inactive["items"][0]["is_active"] is False
    active_only = repository.admin_list_ingredients(connection, "cai thia", limit=10, active_only=True, catalog="v2")
    assert active_only["total"] == 0
    repository.admin_set_ingredient_active({"ingredient_id":created["ingredient_id"],"is_active":True})
    assert repository.admin_list_ingredients(connection, "cai thia", limit=10, catalog="v2")["items"][0]["is_active"] is True

    assert legacy_hashes(connection) == legacy_before
    assert migrate_v2.check(connection)["context_state"] == "NOT_APPLIED"


def test_admin_ingredient_tcp_validation_contract():
    assert admin_ingredients.validate_list({"query":"hành","limit":20,"offset":20,"active_only":True},"TEST_ONLY")["offset"] == 20
    for payload in ({"name":""},{"name":"hành","is_active":True},{"name":"\n"}):
        with pytest.raises(Exception):
            admin_ingredients.validate_create(payload,"TEST_ONLY")


def test_writer_allowlist_accepts_existing_recipe_overlay_and_only_new_ingredient_overlay():
    grants=[f"GRANT {', '.join(privileges)} ON {scope} TO 'goiy_admin_writer'@'localhost'"
            for scope,privileges in REQUIRED_GRANTS.items()]
    grants.extend([
        *INGREDIENT_ADMIN_GRANTS,
        "GRANT SELECT, INSERT, UPDATE ON goiy_mon_an.v2_admin_legacy_recipe_overrides TO 'goiy_admin_writer'@'localhost'",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON goiy_mon_an.v2_admin_legacy_recipe_override_ingredients TO 'goiy_admin_writer'@'localhost'",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON goiy_mon_an.v2_recipe_image_overrides TO 'goiy_admin_writer'@'localhost'",
        "GRANT SELECT, INSERT (ingredient_id, name_override, normalized_name, is_active, updated_by), UPDATE (name_override, normalized_name, is_active, updated_by) ON goiy_mon_an.v2_admin_legacy_ingredient_overrides TO 'goiy_admin_writer'@'localhost'",
    ])
    validate_writer_grants(grants,ingredient_admin=True,legacy_ingredient_admin=True)
    with pytest.raises(RuntimeError,match="unapproved grant"):
        validate_writer_grants(grants+["GRANT ALL PRIVILEGES ON goiy_mon_an.ingredients TO 'goiy_admin_writer'@'localhost'"],
                               legacy_ingredient_admin=True)


def test_admin_ingredient_api_to_tcp_to_test_mysql(mysql_db, monkeypatch, tmp_path):
    connection, config = mysql_db
    _install_001_and_003(connection)
    migrate_v2.run_admin_ingredient_migration(connection,"apply")
    # Historical, unverified English-only imports stay in storage but must not
    # leak into either side of the shared public/Admin catalog.
    sql(connection,"INSERT INTO v2_ingredients(id,canonical_name,normalized_name,identity_status) "
        "VALUES(50001,'black pepper','black pepper','NEEDS_VERIFICATION')")
    repository=MySQLRepository(config,pool_size=1)
    monkeypatch.setattr(repository,"_admin_writer",lambda:mysql.connector.connect(**{**config,"autocommit":False}))
    monkeypatch.setattr(repository,"admin_ingredient_writer_ready",lambda:True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0));port=probe.getsockname()[1]
    server=TCPServer("127.0.0.1",port,repository=repository)
    from source.server import main as server_main
    monkeypatch.setattr(server_main,"LOG_PATH",tmp_path/"TEST_ONLY-ingredient-admin.jsonl")
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        try:
            with socket.create_connection(("127.0.0.1",port),timeout=.1):break
        except OSError:time.sleep(.02)
    else:pytest.fail("TEST_ONLY TCP Server did not start")
    monkeypatch.setenv("TCP_HOST","127.0.0.1");monkeypatch.setenv("TCP_PORT",str(port))
    monkeypatch.setenv("ADMIN_USERNAME","TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH",hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET","TEST_ONLY ingredient admin session secret")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE","false")
    try:
        with TestClient(app) as client:
            login=client.post("/api/admin/login",json={"username":"TEST_ONLY_ADMIN","password":"TEST_ONLY_PASSWORD"})
            assert login.status_code==200
            csrf=client.get("/api/admin/session").json()["data"]["csrf_token"]
            headers={"X-CSRF-Token":csrf}
            user_catalog=client.get("/api/ingredients?limit=50")
            admin_catalog=client.get("/api/admin/ingredients?limit=50")
            assert user_catalog.status_code==admin_catalog.status_code==200
            assert user_catalog.headers.get("cache-control")==admin_catalog.headers.get("cache-control")=="no-store"
            user_items=user_catalog.json()["data"]["items"]
            admin_items=admin_catalog.json()["data"]["items"]
            assert [(item["id"],item["name"]) for item in user_items]==[
                (item["ingredient_id"],item["name"]) for item in admin_items]
            assert len({item["ingredient_id"] for item in admin_items})==len(admin_items)==2
            assert not any(item["name"]=="black pepper" for item in user_items+admin_items)
            created=client.post("/api/admin/ingredients",json={"name":"  B\u00e1nh   m\u00ec "},headers=headers)
            assert created.status_code==200,created.text
            ingredient=created.json()["data"]
            assert ingredient["identity_status"]=="DRAFT"
            user_created=client.get("/api/ingredients?query=banh&limit=50").json()["data"]["items"]
            admin_created=client.get("/api/admin/ingredients?catalog=shared&query=banh&limit=50").json()["data"]["items"]
            assert any(row["id"]==ingredient["ingredient_id"] for row in user_created)
            assert [(row["id"],row["name"]) for row in user_created]==[
                (row["ingredient_id"],row["name"]) for row in admin_created]
            duplicate=client.post("/api/admin/ingredients",json={"name":"BANH MI"},headers=headers)
            assert duplicate.status_code==409
            listed=client.get("/api/admin/ingredients?catalog=v2&query=banh&limit=1&offset=0")
            assert listed.status_code==200 and listed.json()["data"]["total"]==1
            iid=ingredient["ingredient_id"]
            renamed=client.patch(f"/api/admin/ingredients/{iid}",json={"name":"B\u00e1nh m\u00ec m\u1edbi"},headers=headers)
            assert renamed.status_code==200
            deactivated=client.patch(f"/api/admin/ingredients/{iid}/active",json={"is_active":False},headers=headers)
            assert deactivated.status_code==200
            assert client.get(f"/api/admin/ingredients?query=banh&active_only=true").json()["data"]["total"]==0
            assert all(row["id"]!=iid for row in client.get("/api/ingredients?query=banh&limit=50").json()["data"]["items"])
            reactivated=client.patch(f"/api/admin/ingredients/{iid}/active",json={"is_active":True},headers=headers)
            assert reactivated.status_code==200
            user_reactivated=client.get("/api/ingredients?query=banh&limit=50").json()["data"]["items"]
            admin_reactivated=client.get("/api/admin/ingredients?catalog=shared&query=banh&limit=50").json()["data"]["items"]
            assert any(row["id"]==iid for row in user_reactivated)
            assert [(row["id"],row["name"]) for row in user_reactivated]==[
                (row["ingredient_id"],row["name"]) for row in admin_reactivated]
            assert client.delete(f"/api/admin/ingredients/{iid}").status_code==405
    finally:
        server.shutdown();thread.join(timeout=5)


def test_legacy_and_v2_ingredient_union_overlay_and_utf8_pipeline(mysql_db, monkeypatch):
    connection, config = mysql_db
    sql(connection,"UPDATE ingredients SET name='Hành lá',normalized_name='hành lá' WHERE id=2")
    legacy_before = legacy_hashes(connection)
    _install_001_and_003(connection)
    migrate_v2.run_admin_ingredient_migration(connection, "apply")
    assert migrate_v2.check(connection)["legacy_ingredient_admin_state"] == "NOT_APPLIED"
    migrated=migrate_v2.run_legacy_ingredient_admin_migration(connection, "apply")
    assert migrated["legacy_ingredient_admin_state"] == "APPLIED"
    assert migrated["context_state"] == "NOT_APPLIED"
    sql(connection,"""INSERT INTO v2_ingredients(id,legacy_ingredient_id,canonical_name,normalized_name,identity_status)
        VALUES(50001,1,'TEST_ONLY ingredient 1','test_only ingredient 1','DRAFT'),
              (50002,NULL,'Hành lá','hành lá','DRAFT'),
              (50003,NULL,'black pepper','black pepper','NEEDS_VERIFICATION')""")

    # Legacy collision checks use the runtime SELECT-only connection while the
    # writer transaction is open, so this repository needs two pooled sessions.
    repository=MySQLRepository(config,pool_size=2)
    monkeypatch.setattr(repository,"_admin_writer",lambda:mysql.connector.connect(**{**config,"autocommit":False}))
    monkeypatch.setattr(repository,"admin_ingredient_writer_ready",lambda:True)
    monkeypatch.setattr(repository,"legacy_ingredient_admin_writer_ready",lambda _connection=None:True)

    listed=repository.admin_list_ingredients(connection,"HANH",limit=10)
    assert listed["total"]==1
    ingredient=listed["items"][0]
    assert ingredient["name"]=="Hành lá"
    assert ingredient["ingredient_id"]==2
    shared=repository.admin_list_ingredients(connection,"",limit=50,catalog="shared")
    user_repository=repository.request_view(connection,"LIST_INGREDIENTS")
    user_catalog=user_repository.list_ingredients(connection,"",50)
    assert shared["total"]==len(user_catalog)==2
    assert [(row["ingredient_id"],row["name"]) for row in shared["items"]]==[
        (row["id"],row["name"]) for row in user_catalog]
    assert repository.admin_list_ingredients(connection,"black",limit=10,catalog="shared")["total"]==0
    v2_only=repository.admin_list_ingredients(connection,"black",limit=10,catalog="v2")
    from source.common.catalog_ids import V2_OFFSET
    assert v2_only["total"]==0
    assert user_repository.ingredient_ids_exist(connection,{V2_OFFSET+50003}) is False
    assert repository.ingredient_ids_exist(connection,{50003}) is False

    from source.common.admin_tokens import issue
    from source.server.handler import dispatch
    monkeypatch.setenv("ADMIN_SESSION_SECRET","TEST_ONLY legacy ingredient session secret 32 bytes")
    token,_=issue("TEST_ONLY_ADMIN")
    response,_=dispatch(repository,{"version":1,"request_id":"90a91ca7-a54c-4fb8-8c9c-8d7d82f101a8",
        "op":"ADMIN_UPDATE_LEGACY_INGREDIENT","payload":{"ingredient_id":2,"name":"Hành hoa","admin_token":token}})
    assert response["ok"] is True
    from source.server.admin_ingredients import validate_legacy_update
    with pytest.raises(AdminIngredientConflict,match="normalized"):
        repository.admin_update_legacy_ingredient(validate_legacy_update(
            {"ingredient_id":2,"name":"black pepper"},"TEST_ONLY"),"TEST_ONLY_ADMIN")
    assert repository.get_recipe(connection,2)["ingredients"][0]["name"]=="Hành hoa"
    assert repository.list_ingredients(connection,"HANH",50)==[{"id":2,"name":"Hành hoa"}]

    response,_=dispatch(repository,{"version":1,"request_id":"90a91ca7-a54c-4fb8-8c9c-8d7d82f101a9",
        "op":"ADMIN_SET_LEGACY_INGREDIENT_ACTIVE","payload":{"ingredient_id":2,"is_active":False,"admin_token":token}})
    assert response["ok"] is True
    assert repository.admin_list_ingredients(connection,"hanh",limit=10)["items"][0]["is_active"] is False
    assert repository.list_ingredients(connection,"hanh",50)==[]
    admin_inactive=repository.admin_list_ingredients(connection,"hanh",limit=10,catalog="shared")
    assert admin_inactive["total"]==1 and admin_inactive["items"][0]["is_active"] is False
    assert repository.ingredient_ids_exist(connection,{2}) is False
    # Existing recipe rows remain intact and render the current overlay name.
    assert repository.get_recipe(connection,2)["ingredients"][0]["name"]=="Hành hoa"
    repository.admin_set_legacy_ingredient_active({"ingredient_id":2,"is_active":True},"TEST_ONLY_ADMIN")
    assert repository.list_ingredients(connection,"hanh",50)==[{"id":2,"name":"Hành hoa"}]
    assert legacy_hashes(connection)==legacy_before


def test_shared_catalog_uses_one_stable_id_for_linked_or_exact_legacy_identity():
    from source.common.catalog_ids import V2_OFFSET
    from source.server.ingredient_catalog import merge_catalog
    legacy=[{"id":2,"name":"Hành lá","normalized_name":"hành lá","is_active":True,"usage_count":1,
             "can_edit":True,"can_manage":True,"aliases":["hành"]}]
    v2=[{"id":91,"legacy_ingredient_id":2,"name":"Hành lá","normalized_name":"hành lá",
         "is_active":True,"usage_count":2},
        {"id":92,"legacy_ingredient_id":None,"name":"Hành lá","normalized_name":"hành lá",
         "is_active":True,"usage_count":4},
        {"id":93,"legacy_ingredient_id":None,"name":"Nấm TEST_ONLY","normalized_name":"nấm test_only",
         "is_active":True,"usage_count":0}]
    rows=merge_catalog(legacy,v2,active_only=True)
    assert [(row["ingredient_id"],row["name"],row["usage_count"]) for row in rows]==[
        (2,"Hành lá",7),(V2_OFFSET+93,"Nấm TEST_ONLY",0)]


def test_legacy_ingredient_gateway_routes_keep_admin_csrf(monkeypatch):
    from source.web.main import app
    monkeypatch.setenv("ADMIN_USERNAME","TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH",hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET","TEST_ONLY legacy ingredient gateway secret 32 bytes")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE","false")
    calls=[]
    def tcp(_self,op,payload,request_id=None):
        calls.append((op,payload))
        return {"version":1,"request_id":request_id,"ok":True,
                "data":{"dataset_version":"TEST_ONLY","ingredient_id":2},"error":None}
    monkeypatch.setattr("source.web.main.TCPClient.request",tcp)
    with TestClient(app) as client:
        assert client.patch("/api/admin/legacy-ingredients/2",json={"name":"Hành hoa"}).status_code==401
        assert client.post("/api/admin/login",json={"username":"TEST_ONLY_ADMIN","password":"TEST_ONLY_PASSWORD"}).status_code==200
        csrf=client.get("/api/admin/session").json()["data"]["csrf_token"]
        assert client.patch("/api/admin/legacy-ingredients/2",json={"name":"Hành hoa"},headers={"X-CSRF-Token":csrf}).status_code==200
        assert client.patch("/api/admin/legacy-ingredients/2/active",json={"is_active":False},headers={"X-CSRF-Token":csrf}).status_code==200
    assert [operation for operation,_ in calls]==["ADMIN_UPDATE_LEGACY_INGREDIENT","ADMIN_SET_LEGACY_INGREDIENT_ACTIVE"]
