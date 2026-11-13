"""HTTP -> real TCP socket -> isolated unified-schema MySQL integration.

All rows and image bytes in this test are synthetic TEST_ONLY data. The test
creates and drops its own *_test schema on the private mysqld fixture.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import socket
import threading
import time
import uuid

import mysql.connector
import pytest

from source.database.unified_catalog_migration import create_schema
from source.server.main import TCPServer
from source.server.unified_repository import UnifiedMySQLRepository
from tests.mysql_v2_fixtures import private_mysql


def _sql(connection, statement, params=()):
    cursor = connection.cursor()
    try:
        cursor.execute(statement, params)
        if cursor.with_rows:
            return cursor.fetchall()
        return cursor.lastrowid
    finally:
        cursor.close()


def _port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_unified_admin_ingredient_status_filter_filters_before_pagination(monkeypatch):
    import source.server.unified_repository as unified_repository

    rows = [
        {"ingredient_id": 1, "name": "TEST_ONLY active a", "normalized_name": "active a", "is_active": 1},
        {"ingredient_id": 2, "name": "TEST_ONLY inactive", "normalized_name": "inactive", "is_active": 0},
        {"ingredient_id": 3, "name": "TEST_ONLY active b", "normalized_name": "active b", "is_active": 1},
    ]

    def query(_connection, sql, _args=()):
        if "COUNT(DISTINCT recipe_id)" in sql:
            return [{"n": 0}]
        selected = rows
        if "is_active=1" in sql:
            selected = [row for row in rows if row["is_active"] == 1]
        elif "is_active=0" in sql:
            selected = [row for row in rows if row["is_active"] == 0]
        return selected

    monkeypatch.setattr(unified_repository, "_query", query)
    repo = object.__new__(UnifiedMySQLRepository)
    all_rows = repo.admin_list_ingredients(None, "", limit=1, offset=0, status="all")
    active = repo.admin_list_ingredients(None, "", limit=20, offset=0, status="active")
    inactive = repo.admin_list_ingredients(None, "", limit=20, offset=0, status="inactive")
    assert all_rows["total"] == 3 and len(all_rows["items"]) == 1
    assert active["total"] == 2 and all(row["is_active"] for row in active["items"])
    assert inactive["total"] == 1 and inactive["items"][0]["ingredient_id"] == 2


def test_unified_repository_refuses_non_test_or_remote_mysql(private_mysql):
    with pytest.raises(RuntimeError, match="TEST_ONLY database"):
        UnifiedMySQLRepository({**private_mysql, "database": "goiy_mon_an"})
    with pytest.raises(RuntimeError, match="loopback MySQL TEST_ONLY"):
        UnifiedMySQLRepository({**private_mysql, "database": "catalog_test", "host": "192.0.2.10"})


def test_unified_taxonomy_migration_is_additive_and_backfills_core_roles(private_mysql):
    database = "taxonomy_migration_" + uuid.uuid4().hex[:12] + "_test"
    admin = mysql.connector.connect(**private_mysql)
    connection = None
    try:
        _sql(admin, f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        connection = mysql.connector.connect(**{**private_mysql,"database":database})
        _sql(connection,"""CREATE TABLE recipes(recipe_id BIGINT UNSIGNED PRIMARY KEY,
            role ENUM('main','vegetable','soup','side','drink','starch','other') NOT NULL) ENGINE=InnoDB""")
        _sql(connection,"""CREATE TABLE recipe_tags(tag_id SMALLINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            tag_type ENUM('diet','region','season','occasion') NOT NULL,code VARCHAR(48) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
            label VARCHAR(100) NOT NULL,normalized_label VARCHAR(100) NOT NULL,
            UNIQUE KEY uq_recipe_tag_code(tag_type,code),KEY ix_recipe_tag_label(tag_type,normalized_label)) ENGINE=InnoDB""")
        _sql(connection,"""CREATE TABLE recipe_tag_links(recipe_id BIGINT UNSIGNED NOT NULL,tag_id SMALLINT UNSIGNED NOT NULL,
            PRIMARY KEY(recipe_id,tag_id),KEY ix_tag_recipes(tag_id,recipe_id),
            CONSTRAINT fk_test_taxonomy_recipe FOREIGN KEY(recipe_id) REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
            CONSTRAINT fk_test_taxonomy_tag FOREIGN KEY(tag_id) REFERENCES recipe_tags(tag_id) ON DELETE RESTRICT) ENGINE=InnoDB""")
        _sql(connection,"INSERT INTO recipes VALUES(1,'main'),(2,'soup')")
        _sql(connection,"INSERT INTO recipe_tags(tag_type,code,label,normalized_label) VALUES('diet','vegetarian','Chay','chay')")
        sql = (Path(__file__).resolve().parents[1] / "source/database/migrations/unified_v3_004_admin_taxonomies.sql").read_text(encoding="utf-8")
        sql = "\n".join(line for line in sql.splitlines() if not line.lstrip().startswith("--"))
        for statement in sql.split(";"):
            if statement:
                _sql(connection,statement)
        columns = {row[0] for row in _sql(connection,"SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='recipe_tags'",(database,))}
        assert {"description","is_core","deleted_at"} <= columns
        core = _sql(connection,"SELECT code,is_core FROM recipe_tags WHERE tag_type='dish_type' ORDER BY code")
        assert len(core)==7 and all(row[1] for row in core)
        linked = _sql(connection,"""SELECT r.recipe_id,t.code FROM recipe_tag_links l
            JOIN recipes r USING(recipe_id) JOIN recipe_tags t USING(tag_id) WHERE t.tag_type='dish_type' ORDER BY r.recipe_id""")
        assert linked==[(1,"main"),(2,"soup")]
        assert _sql(connection,"SELECT COUNT(*) FROM recipes")[0][0]==2
    finally:
        if connection is not None:connection.close()
        try:_sql(admin,f"DROP DATABASE IF EXISTS `{database}`")
        finally:admin.close()


@pytest.fixture
def unified_http_stack(private_mysql, tmp_path, monkeypatch):
    database = "unified_http_" + uuid.uuid4().hex[:12] + "_test"
    admin = mysql.connector.connect(**private_mysql)
    _sql(admin, f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    config = {**private_mysql, "database": database, "autocommit": True}
    connection = mysql.connector.connect(**config)
    create_schema(connection)
    for ingredient_id, name in ((1, "TEST_ONLY c\u00e0 chua"), (2, "TEST_ONLY rau"), (3, "TEST_ONLY g\u00e0")):
        _sql(connection, "INSERT INTO ingredients(ingredient_id,name,normalized_name,is_active) VALUES(%s,%s,%s,1)",
             (ingredient_id, name, name.casefold()))
    unit_id = _sql(connection, "INSERT INTO units(code,name,dimension) VALUES('test_unit','TEST_ONLY unit','count')")
    other_unit_id = _sql(connection, "INSERT INTO units(code,name,dimension) VALUES('test_unit_other','TEST_ONLY other unit','count')")
    recipes = ((1, "TEST_ONLY m\u00f3n ch\u00ednh", "main", 1),
               (2, "TEST_ONLY m\u00f3n rau", "vegetable", 2),
               (3, "TEST_ONLY m\u00f3n canh", "soup", 3))
    for recipe_id, title, role, ingredient_id in recipes:
        _sql(connection, """INSERT INTO recipes(recipe_id,title,normalized_title,description,role,minutes_total,
            instructions_legacy,is_public,edit_version) VALUES(%s,%s,%s,'TEST_ONLY description',%s,20,
            'TEST_ONLY instructions',1,1)""", (recipe_id, title, title.casefold(), role))
        _sql(connection, """INSERT INTO recipe_ingredients(recipe_id,line_no,ingredient_id,quantity_text,
            amount_kind,amount_min,unit_id,requirement,purpose) VALUES(%s,1,%s,'TEST_ONLY quantity',%s,%s,%s,'required','main')""",
             (recipe_id, ingredient_id, "exact" if recipe_id == 1 else "unknown",
              2 if recipe_id == 1 else None, unit_id if recipe_id == 1 else None))
        _sql(connection, "INSERT INTO recipe_steps(recipe_id,step_no,instruction) VALUES(%s,1,'TEST_ONLY old structured step')", (recipe_id,))
    connection.close()

    secret = "test-only-unified-schema-session-secret-000000000000"
    password = "TEST_ONLY_Admin_Password_2026!"
    salt = b"test-only-admin-salt"
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 300_000, dklen=32)
    monkeypatch.setenv("ADMIN_USERNAME", "TEST_ONLY_admin")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", f"pbkdf2_sha256$300000${salt.hex()}${digest.hex()}")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", secret)
    monkeypatch.setenv("UNIFIED_SCHEMA_MODE", "1")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    monkeypatch.setenv("USER_COOKIE_SECURE", "false")
    monkeypatch.setenv("RECIPE_IMAGE_STORAGE_DIR", str(tmp_path / "images"))
    monkeypatch.setenv("ACHIEVEMENT_IMAGE_STORAGE_DIR", str(tmp_path / "achievement-images"))
    monkeypatch.setenv("FEEDBACK_IMAGE_STORAGE_DIR", str(tmp_path / "feedback-images"))
    repo = UnifiedMySQLRepository(config, pool_size=4)
    tcp_port = _port()
    tcp = TCPServer("127.0.0.1", tcp_port, repository=repo, max_connections=4)
    thread = threading.Thread(target=tcp.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", tcp_port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.02)
    else:
        pytest.fail("TEST_ONLY TCP server did not start")

    monkeypatch.setenv("TCP_HOST", "127.0.0.1")
    monkeypatch.setenv("TCP_PORT", str(tcp_port))
    import source.web.main as web_main
    web_main._GATEWAY_LOG_PATH = tmp_path / "fastapi-test.jsonl"
    import source.server.main as tcp_main
    tcp_main.LOG_PATH = tmp_path / "tcp-test.jsonl"
    try:
        yield web_main.app, repo, tcp, thread, config, password
    finally:
        tcp.shutdown()
        thread.join(timeout=2)
        repo._pool._remove_connections()
        connection = mysql.connector.connect(**private_mysql)
        try:
            _sql(connection, f"DROP DATABASE `{database}`")
        finally:
            connection.close()
            admin.close()


def test_daily_combo_history_roundtrips_http_tcp_mysql_test_only(unified_http_stack):
    from fastapi.testclient import TestClient

    app, _repo, _tcp, _thread, _config, _password = unified_http_stack
    # Four-person Daily now requires two mains and original quantified food,
    # rather than three unquantified role placeholders. One synthetic combo.
    from decimal import Decimal, ROUND_CEILING
    c=mysql.connector.connect(**_config)
    try:
        unit=_sql(c,"SELECT unit_id FROM units WHERE code='g'")[0][0]
        for iid,name in ((1,'thit heo xay'),(2,'cai thao'),(3,'dau phu')):
            _sql(c,'UPDATE ingredients SET name=%s,normalized_name=%s WHERE ingredient_id=%s',(name,name,iid))
        _sql(c,"INSERT INTO recipes(recipe_id,title,normalized_title,description,role,minutes_total,instructions_legacy,is_public) VALUES(4,'TEST_ONLY main 2','test only main 2','TEST_ONLY','main',20,'TEST_ONLY',1)")
        _sql(c,"INSERT INTO recipe_ingredients(recipe_id,line_no,ingredient_id,quantity_text,amount_kind,amount_min,unit_id,requirement,purpose,measurement_basis) VALUES(4,1,1,'TEST_ONLY','exact',1,%s,'required','main','gross')",(unit,))
        for rid,share,factor in ((1,'.3','.735'),(4,'.3','.735'),(2,'.25','.765'),(3,'.15','.931')):
            amount=(Decimal(4)*350*Decimal(share)/Decimal(factor)).quantize(Decimal('.000001'),rounding=ROUND_CEILING)
            _sql(c,"UPDATE recipe_ingredients SET amount_kind='exact',amount_min=%s,unit_id=%s,measurement_basis='gross' WHERE recipe_id=%s",(amount,unit,rid))
    finally:c.close()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        payload = {"adaptive_daily": True, "people": 4,
                   "counts": {"main": 2, "vegetable": 1, "soup": 1}}
        first_response = client.post("/api/meal-plan/v2", json=payload)
        assert first_response.status_code == 200, first_response.text
        first = first_response.json()["data"]
        assert first["plan"] is not None
        assert len(first["daily_combo_id"]) == 32
        assert first["daily_combo_search"] == {"found": 1, "complete": True}

        payload.update(action="regenerate", current_plan={
            item["slot"]: item["recipe_id"] for item in first["plan"]["items"]},
            combo_history=[first["daily_combo_id"]])
        next_response = client.post("/api/meal-plan/v2", json=payload)
        assert next_response.status_code == 200, next_response.text
        next_data = next_response.json()["data"]
        assert next_data["plan"] is None
        assert next_data["reason"]["code"] == "NO_ALTERNATIVE"
        # An unchanged current assignment is rejected before qualification:
        # found counts alternatives visited during this search, not history.
        assert next_data["daily_combo_search"] == {"found": 0, "complete": True}


def test_beverage_admin_draft_metadata_publish_and_hide_http_tcp(unified_http_stack):
    from fastapi.testclient import TestClient
    app,repo,tcp,thread,config,password=unified_http_stack
    payload={'title':'TEST_ONLY seasonal tea','description':'TEST_ONLY estimated preparation',
             'instructions':'TEST_ONLY brew and cool','minutes':10,'role':'drink',
             'ingredients':[{'ingredient_id':1,'quantity_raw':'TEST_ONLY'}],
             'idempotency_key':str(uuid.uuid4()),'beverage_temperature':'both',
             'beverage_light':True,'is_non_alcoholic':True,'is_visible':False,
             'tags':[{'tag_type':'season','code':'spring'},{'tag_type':'season','code':'autumn'},
                     {'tag_type':'occasion','code':'daily'}]}
    with TestClient(app,base_url='http://127.0.0.1') as c:
        assert c.post('/api/admin/catalog-recipes',json=payload).status_code==401
        assert c.post('/api/admin/login',json={'username':'TEST_ONLY_admin','password':password}).status_code==200
        csrf=c.get('/api/admin/session').json()['data']['csrf_token'];headers={'X-CSRF-Token':csrf}
        assert c.post('/api/admin/catalog-recipes',json=payload).status_code==403
        bad=c.post('/api/admin/catalog-recipes',json={**payload,'beverage_temperature':'warm'},headers=headers)
        assert bad.status_code==422
        created=c.post('/api/admin/catalog-recipes',json=payload,headers=headers)
        assert created.status_code==200,created.text
        rid=created.json()['data']['recipe_id']
        assert c.post('/api/admin/catalog-recipes',json=payload,headers=headers).json()['data']['recipe_id']==rid
        assert c.get(f'/api/recipes/{rid}').status_code==404
        detail=c.get(f'/api/admin/revisions/{rid}').json()['data']
        assert not detail['is_visible']
        tags={(t['tag_type'],t['code']) for t in detail['tags']}
        assert {('season','spring'),('season','autumn'),('dish_type','serve_hot'),('dish_type','serve_cold'),('dish_type','non_alcoholic')}<=tags
        assert c.patch(f'/api/admin/catalog-recipes/{rid}/state',json={'is_visible':True,'is_deleted':False},headers=headers).status_code==200
        assert c.get(f'/api/recipes/{rid}').status_code==200
        update={k:v for k,v in payload.items() if k!='idempotency_key'}
        detail=c.get(f'/api/admin/revisions/{rid}').json()['data']
        update.update(expected_version=detail['edit_version'],beverage_temperature='cold',is_visible=True)
        saved=c.patch(f'/api/admin/catalog-recipes/{rid}?revision_id={rid}',json=update,headers=headers)
        assert saved.status_code==200,saved.text
        fresh=c.get(f'/api/admin/revisions/{rid}').json()['data']
        flags={t['code'] for t in fresh['tags'] if t['tag_type']=='dish_type'}
        assert 'serve_cold' in flags and 'serve_hot' not in flags
        conn=mysql.connector.connect(**config)
        try:
            meta=repo.beverage_metadata(conn,[rid])
            assert meta[rid]['season']=={'spring','autumn'}
        finally:conn.close()
        assert c.patch(f'/api/admin/catalog-recipes/{rid}/state',json={'is_visible':False,'is_deleted':False},headers=headers).status_code==200
        assert c.get(f'/api/recipes/{rid}').status_code==404


def test_unified_http_tcp_admin_user_and_meal_flows(unified_http_stack, tmp_path):
    from fastapi.testclient import TestClient

    app, _repo, _tcp, _thread, _config, admin_password = unified_http_stack
    with TestClient(app, base_url="http://127.0.0.1") as client:
        # Admin auth and CSRF are exercised through the real HTTP gateway.
        login = client.post("/api/admin/login", json={"username": "TEST_ONLY_admin", "password": admin_password})
        assert login.status_code == 200
        session = client.get("/api/admin/session")
        assert session.status_code == 200
        csrf = session.json()["data"]["csrf_token"]
        old_draft = client.post("/api/admin/revisions", headers={"X-CSRF-Token": csrf}, json={
            "title": "TEST_ONLY legacy draft route", "description": "", "instructions": "TEST_ONLY",
            "minutes": 10, "ingredients": [{"ingredient_id": 1, "quantity_raw": "TEST_ONLY"}],
        })
        assert old_draft.json()["error"]["code"] == "UNSUPPORTED_OPERATION"

        assert client.get("/api/admin/dashboard").json()["data"]["recipe_catalog_ready"] is True
        units = client.get("/api/admin/units")
        assert units.status_code == 200 and units.json()["data"]["items"]
        unit_ids = {row["code"]: row["unit_id"] for row in units.json()["data"]["items"]}
        test_unit_id = unit_ids["test_unit"]
        other_unit_id = unit_ids["test_unit_other"]
        before = client.get("/api/ingredients?limit=100").json()["data"]["items"]
        assert {row["name"] for row in before} == {"TEST_ONLY c\u00e0 chua", "TEST_ONLY rau", "TEST_ONLY g\u00e0"}
        denied = client.post("/api/admin/ingredients", json={"name": "TEST_ONLY d\u1ea7u"})
        assert denied.status_code == 403
        ingredient = client.post("/api/admin/ingredients", headers={"X-CSRF-Token": csrf},
                                 json={"name": "TEST_ONLY d\u1ea7u"})
        assert ingredient.status_code == 200, ingredient.text
        ingredient_id = ingredient.json()["data"]["ingredient_id"]
        user_catalog = client.get("/api/ingredients?limit=100").json()["data"]["items"]
        admin_catalog = client.get("/api/admin/ingredients?limit=50").json()["data"]
        assert any(row["id"] == ingredient_id and row["name"] == "TEST_ONLY d\u1ea7u" for row in user_catalog)
        assert admin_catalog["total"] == 4
        renamed = client.patch(f"/api/admin/ingredients/{ingredient_id}", headers={"X-CSRF-Token": csrf},
                                json={"name": "TEST_ONLY d\u1ea7u \u0103n"})
        assert renamed.status_code == 200, renamed.text
        user_catalog = client.get("/api/ingredients?limit=100").json()["data"]["items"]
        assert any(row["id"] == ingredient_id and row["name"] == "TEST_ONLY d\u1ea7u \u0103n" for row in user_catalog)

        # Editing a legacy identity can now use the same high/low shared IDs.
        legacy = client.get("/api/admin/legacy-recipes/1").json()["data"]
        updated = client.patch("/api/admin/legacy-recipes/1", headers={"X-CSRF-Token": csrf}, json={
            "title": "TEST_ONLY m\u00f3n ch\u00ednh \u0111\u00e3 s\u1eeda", "description": legacy["description"],
            "instructions": "1. TEST_ONLY step 1", "minutes": 25, "is_visible": True,
            "expected_version": legacy["edit_version"],
                "ingredients": [{"ingredient_id": 1, "quantity": "TEST_ONLY quantity", "is_required": True},
                            {"ingredient_id": ingredient_id, "quantity": "TEST_ONLY 2 ml", "is_required": True}],
        })
        assert updated.status_code == 200, updated.text
        legacy_public = client.get("/api/recipes/1").json()["data"]
        assert [line["id"] for line in legacy_public["ingredients"]] == [1, ingredient_id]
        assert legacy_public["instructions"] == "B\u01b0\u1edbc 1: TEST_ONLY step 1"
        check = mysql.connector.connect(**_config)
        try:
            line = _sql(check, """SELECT ri.amount_kind,ri.amount_min,u.code
                FROM recipe_ingredients ri LEFT JOIN units u ON u.unit_id=ri.unit_id
                WHERE ri.recipe_id=1 AND ri.line_no=1""")[0]
            assert line == ("exact", 2, "test_unit")
            assert _sql(check, "SELECT COUNT(*) FROM recipe_edit_history WHERE recipe_id=1")[0][0] == 1
        finally:
            check.close()

        # A new Admin save is public immediately and is readable/searchable.
        create_key = str(uuid.uuid4())
        create_payload = {
            "title": "TEST_ONLY m\u00f3n m\u1edbi", "description": "TEST_ONLY m\u00f4 t\u1ea3", "instructions": "TEST_ONLY c\u00e1ch n\u1ea5u",
            "minutes": 15, "minutes_prep": 5, "minutes_cook": 10, "servings": "2",
            "steps": [{"instruction":"TEST_ONLY n\u1ea5u", "duration_minutes":10,"heat_level":"low"}],
            "source_url": None, "tags": [],
            "role": "main", "ingredients": [
                {"ingredient_id": ingredient_id,"quantity_raw":"TEST_ONLY 3 g","requirement":"required",
                 "amount_kind":"exact","amount_min":"3","amount_max":"3","unit_id":test_unit_id,
                 "ingredient_form":"TEST_ONLY diced","measurement_basis":"prepared","purpose":"main","scaling_mode":"linear"},
                {"ingredient_id": ingredient_id,"quantity_raw":"TEST_ONLY 2 g","requirement":"required",
                 "amount_kind":"exact","amount_min":"2","amount_max":"2","unit_id":test_unit_id,
                 "ingredient_form":"TEST_ONLY diced","measurement_basis":"prepared","purpose":"main","scaling_mode":"linear"},
                {"ingredient_id": ingredient_id,"quantity_raw":"TEST_ONLY 5 unit","requirement":"required",
                 "amount_kind":"exact","amount_min":"5","amount_max":"5","unit_id":other_unit_id,
                 "ingredient_form":"TEST_ONLY diced","measurement_basis":"prepared","purpose":"main","scaling_mode":"fixed"},
                {"ingredient_id": ingredient_id,"quantity_raw":"TEST_ONLY 1 g","requirement":"optional",
                 "amount_kind":"exact","amount_min":"1","amount_max":"1","unit_id":test_unit_id,
                 "ingredient_form":"TEST_ONLY diced","measurement_basis":"prepared","purpose":"main","scaling_mode":"fixed"}],
            "idempotency_key": create_key,
            "portion_data_status":"estimated", "portion_data_evidence":"TEST_ONLY synthetic base servings=2",
        }
        create = client.post("/api/admin/catalog-recipes", headers={"X-CSRF-Token": csrf}, json=create_payload)
        assert create.status_code == 200, create.text
        recipe_id = create.json()["data"]["recipe_id"]
        repeated = client.post("/api/admin/catalog-recipes", headers={"X-CSRF-Token": csrf}, json=create_payload)
        assert repeated.status_code == 200 and repeated.json()["data"]["recipe_id"] == recipe_id
        admin_rows = client.get("/api/admin/recipes?limit=50").json()["data"]
        assert sum(row["title"] == create_payload["title"] for row in admin_rows["items"]) == 1
        invalid_payload = {**create_payload, "title": "TEST_ONLY invalid ingredient", "idempotency_key": str(uuid.uuid4()),
                           "ingredients": [{"ingredient_id": 999999, "quantity_raw": "TEST_ONLY"}]}
        invalid = client.post("/api/admin/catalog-recipes", headers={"X-CSRF-Token": csrf}, json=invalid_payload)
        assert invalid.status_code in (400, 422), invalid.text
        assert client.get("/api/admin/recipes?limit=50").json()["data"]["total"] == admin_rows["total"]
        detail = client.get(f"/api/recipes/{recipe_id}")
        assert detail.status_code == 200


        assert detail.json()["data"]["title"] == create_payload["title"]
        assert detail.json()["data"]["servings"] == "2.000"
        assert len(detail.json()["data"]["steps"]) == 1
        assert detail.json()["data"]["ingredients"][0]["amount_min"] == "3.000000"
        assert client.post("/api/search", json={"query": create_payload["title"]}).json()["data"]["items"]
        assert client.post("/api/recommend", json={"ingredient_ids": [ingredient_id], "algorithm": "proposed"}).status_code == 200

        v1 = client.post("/api/meal-plan", json={})
        assert v1.status_code == 200, v1.text
        assert v1.json()["data"]["plan"] is not None, v1.json()["data"]
        v2 = client.post("/api/meal-plan/v2", json={"people": 4})
        assert v2.status_code == 200, v2.text
        assert v2.json()["data"]["plan"] is not None
        assert client.get("/api/meal-plan/filters").status_code == 200
        calculate = client.post("/api/meal-plan/calculate", json={"recipe_ids": [recipe_id], "people": 4,"layout_mode":"custom"})
        assert calculate.status_code == 200
        calculated = calculate.json()["data"]
        assert calculated["status"] == "COMPLETE", calculated
        assert len(calculated["known_ingredients"]) == 3
        required = next(item for item in calculated["known_ingredients"] if item["requirement"] == "required" and item["unit"] == "test_unit")
        other_unit = next(item for item in calculated["known_ingredients"] if item["unit"] == "test_unit_other")
        optional = next(item for item in calculated["known_ingredients"] if item["requirement"] == "optional")
        assert required["quantity_value"] == "10" and other_unit["quantity_value"] == "5" and optional["quantity_value"] == "1"
        assert detail.json()["data"]["ingredients"][3]["is_required"] is False

        # Unknown text is never parsed into a number or treated as zero.
        unknown_payload = {"title":"TEST_ONLY unknown portion", "description":"TEST_ONLY", "instructions":"TEST_ONLY",
            "minutes":10,"servings":"2","role":"side","idempotency_key":str(uuid.uuid4()),
            "ingredients":[{"ingredient_id":ingredient_id,"quantity_raw":"vá»«a Ä‘á»§","requirement":"required",
                "amount_kind":"to_taste","ingredient_form":"TEST_ONLY chopped","measurement_basis":"prepared",
                "purpose":"seasoning","scaling_mode":"unknown"}]}
        unknown_save = client.post("/api/admin/catalog-recipes",headers={"X-CSRF-Token":csrf},json=unknown_payload)
        assert unknown_save.status_code == 200, unknown_save.text
        unknown_id = unknown_save.json()["data"]["recipe_id"]
        unknown_calculation = client.post("/api/meal-plan/calculate",json={"recipe_ids":[unknown_id],"people":4}).json()["data"]
        assert unknown_calculation["status"] == "INCOMPLETE"
        assert unknown_calculation["known_ingredients"] == []
        assert {reason["code"] for reason in unknown_calculation["recipes"][0]["reasons"]} == {"UNKNOWN_QUANTITY"}

        # Invalid unit FK fails atomically; no recipe or ingredient line remains.
        rollback_payload = {**create_payload,"title":"TEST_ONLY rollback unit","idempotency_key":str(uuid.uuid4()),
            "ingredients":[{"ingredient_id":ingredient_id,"quantity_raw":"TEST_ONLY amount","requirement":"required",
                "amount_kind":"exact","amount_min":"1","amount_max":"1","unit_id":65535,
                "ingredient_form":"TEST_ONLY cut","measurement_basis":"prepared","purpose":"main","scaling_mode":"linear"}]}
        rollback = client.post("/api/admin/catalog-recipes",headers={"X-CSRF-Token":csrf},json=rollback_payload)
        assert rollback.status_code == 409, rollback.text
        assert all(item["title"] != rollback_payload["title"] for item in client.get("/api/admin/recipes?limit=50").json()["data"]["items"])

        # Image upload/replace/read/remove crosses HTTP, TCP and MySQL metadata.
        from PIL import Image
        from io import BytesIO
        image_buffer = BytesIO()
        Image.new("RGB", (2, 2), (10, 120, 80)).save(image_buffer, format="PNG")
        image_response = client.post(f"/api/admin/recipes/{recipe_id}/image",
                                     headers={"X-CSRF-Token": csrf, "Content-Type": "image/png"},
                                     content=image_buffer.getvalue())
        assert image_response.status_code == 200, image_response.text
        public_image = client.get(f"/media/recipes/{recipe_id}")
        assert public_image.status_code == 200 and public_image.headers["content-type"] == "image/png"
        first_image = client.get(f"/api/admin/recipes/{recipe_id}/image").json()["data"]["image"]
        first_image_path = tmp_path / "images" / first_image["storage_key"]
        assert first_image_path.is_file()
        second_buffer = BytesIO()
        Image.new("RGB", (3, 2), (210, 40, 30)).save(second_buffer, format="PNG")
        replacement = client.post(f"/api/admin/recipes/{recipe_id}/image",
                                   headers={"X-CSRF-Token": csrf, "Content-Type": "image/png"},
                                   content=second_buffer.getvalue())
        assert replacement.status_code == 200, replacement.text
        second_image = client.get(f"/api/admin/recipes/{recipe_id}/image").json()["data"]["image"]
        assert second_image["sha256"] != first_image["sha256"] and not first_image_path.exists()
        assert client.get(f"/media/recipes/{recipe_id}").content != public_image.content
        public_metadata = client.get(f"/api/recipes/{recipe_id}/image").json()["data"]
        assert second_image["sha256"] in public_metadata["image_url"], "public image URL must change when the image is replaced"

        updated_title = "TEST_ONLY edited v3 recipe"
        row = client.get(f"/api/admin/revisions/{recipe_id}").json()["data"]
        changed = client.patch(f"/api/admin/catalog-recipes/{recipe_id}?revision_id={recipe_id}",
                               headers={"X-CSRF-Token": csrf}, json={
            "title": updated_title, "description": create_payload["description"], "instructions": "TEST_ONLY c\u00e1ch n\u1ea5u s\u1eeda",
            "minutes": 18,"minutes_prep":6,"minutes_cook":12,"servings":"2","role":"main",
            "steps":[{"instruction":"TEST_ONLY updated step","duration_minutes":12,"heat_level":"medium"}],
            "source_url": None, "tags": [],
            "ingredients": [{"ingredient_id": ingredient_id,"quantity_raw":"TEST_ONLY 2-4 g","requirement":"required",
                "amount_kind":"range","amount_min":"2","amount_max":"4","unit_id":test_unit_id,
                "ingredient_form":"TEST_ONLY diced","measurement_basis":"prepared","purpose":"main","scaling_mode":"linear"}],
            "expected_version": row["edit_version"],
        })
        assert changed.status_code == 200, changed.text
        updated_detail = client.get(f"/api/recipes/{recipe_id}").json()["data"]
        assert updated_detail["title"] == updated_title and updated_detail["servings"] == "2.000"
        assert updated_detail["steps"][0]["duration_minutes"] == 12
        updated_calculation = client.post("/api/meal-plan/calculate",json={"recipe_ids":[recipe_id],"people":3,"layout_mode":"custom"}).json()["data"]
        assert updated_calculation["status"] == "COMPLETE"
        assert updated_calculation["known_ingredients"][0]["quantity_min"] == "3"
        assert updated_calculation["known_ingredients"][0]["quantity_max"] == "6"
        stale = client.patch(f"/api/admin/catalog-recipes/{recipe_id}?revision_id={recipe_id}",
                             headers={"X-CSRF-Token": csrf}, json={
            "title": "TEST_ONLY stale update", "description": "TEST_ONLY", "instructions": "TEST_ONLY",
            "minutes": 18, "role": "main", "ingredients": [{"ingredient_id": ingredient_id, "quantity_raw": "TEST_ONLY 2 mu\u1ed7ng"}],
            "expected_version": row["edit_version"],
        })
        assert stale.status_code == 409

        # Soft deletion removes public reads, restoration makes it public again.
        assert client.patch(f"/api/admin/catalog-recipes/{recipe_id}/state", headers={"X-CSRF-Token": csrf},
                            json={"is_visible": True, "is_deleted": True}).status_code == 200
        assert client.get(f"/api/recipes/{recipe_id}").status_code == 404
        assert client.get(f"/api/recipes/{recipe_id}/image").status_code == 404
        assert client.get(f"/media/recipes/{recipe_id}").status_code == 404
        assert all(row["id"] != recipe_id for row in client.post("/api/search", json={"query": create_payload["title"]}).json()["data"]["items"])
        assert client.patch(f"/api/admin/catalog-recipes/{recipe_id}/state", headers={"X-CSRF-Token": csrf},
                            json={"is_visible": True, "is_deleted": False}).status_code == 200
        assert client.get(f"/api/recipes/{recipe_id}").status_code == 200
        assert client.get(f"/media/recipes/{recipe_id}").status_code == 200
        removed_image = client.delete(f"/api/admin/recipes/{recipe_id}/image", headers={"X-CSRF-Token": csrf})
        assert removed_image.status_code == 200
        assert client.get(f"/media/recipes/{recipe_id}").status_code == 404
        check = mysql.connector.connect(**_config)
        try:
            assert _sql(check, "SELECT COUNT(*) FROM recipe_edit_history WHERE recipe_id=%s", (recipe_id,))[0][0] >= 3
        finally:
            check.close()

        # Existing user account flows remain on the same unified users table.
        registered = client.post("/api/auth/register", json={"username": "test_only_user", "password": "TEST_ONLY_user_password_123", "password_confirmation": "TEST_ONLY_user_password_123"})
        assert registered.status_code == 200, registered.text
        user_session = client.get("/api/auth/session").json()["data"]
        assert user_session["authenticated"] is True
        user_id = registered.json()["data"]["user_id"]
        assert client.post("/api/auth/logout", headers={"X-CSRF-Token": user_session["csrf_token"]}).status_code == 200
        assert client.post("/api/auth/login", json={"username": "test_only_user", "password": "TEST_ONLY_user_password_123"}).status_code == 200
        active_user_session = client.get("/api/auth/session").json()["data"]
        assert client.post("/api/auth/logout", headers={"X-CSRF-Token": active_user_session["csrf_token"]}).status_code == 200
        assert client.post("/api/admin/login", json={"username": "TEST_ONLY_admin", "password": admin_password}).status_code == 200
        csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]
        assert client.patch(f"/api/admin/users/{user_id}/status", headers={"X-CSRF-Token": csrf}, json={"account_status": "LOCKED"}).status_code == 200
        assert client.post("/api/auth/login", json={"username": "test_only_user", "password": "TEST_ONLY_user_password_123"}).status_code == 401


def test_unified_admin_taxonomy_lifecycle_and_recipe_links(unified_http_stack):
    from fastapi.testclient import TestClient

    app, _repo, _tcp, _thread, config, admin_password = unified_http_stack
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/admin/taxonomies?kind=dish_type").status_code == 401
        assert client.post("/api/admin/taxonomies", json={"kind":"dish_type","group":"dish_type",
            "code":"test_only_type","label":"TEST_ONLY type","description":""}).status_code == 401
        assert client.post("/api/admin/login", json={"username":"TEST_ONLY_admin","password":admin_password}).status_code == 200
        csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]
        denied = client.post("/api/admin/taxonomies", json={"kind":"dish_type","group":"dish_type",
            "code":"test_only_type","label":"TEST_ONLY type","description":""})
        assert denied.status_code == 403

        headers = {"X-CSRF-Token":csrf}
        created_type = client.post("/api/admin/taxonomies", headers=headers, json={"kind":"dish_type","group":"dish_type",
            "code":"test_only_type","label":"TEST_ONLY loại phụ","description":"TEST_ONLY mô tả"})
        assert created_type.status_code == 200, created_type.text
        type_id = created_type.json()["data"]["tag_id"]
        created_weather = client.post("/api/admin/taxonomies", headers=headers, json={"kind":"classification","group":"weather",
            "code":"test_only_hot","label":"TEST_ONLY ngày nóng","description":"TEST_ONLY khí hậu"})
        assert created_weather.status_code == 200, created_weather.text
        weather_id = created_weather.json()["data"]["tag_id"]
        created_region = client.post("/api/admin/taxonomies", headers=headers, json={"kind":"classification","group":"region",
            "code":"test_only_region","label":"TEST_ONLY miền thử","description":""})
        assert created_region.status_code == 200, created_region.text
        region_id = created_region.json()["data"]["tag_id"]

        searched = client.get("/api/admin/taxonomies?kind=classification&group=weather&query=ng%C3%A0y+n%C3%B3ng")
        assert searched.status_code == 200 and [item["tag_id"] for item in searched.json()["data"]["items"]] == [weather_id], searched.text
        renamed = client.patch(f"/api/admin/taxonomies/{type_id}", headers=headers, json={"kind":"dish_type","group":"dish_type",
            "code":"test_only_type","label":"TEST_ONLY tên mới","description":"TEST_ONLY mô tả sửa"})
        assert renamed.status_code == 200 and renamed.json()["data"]["label"] == "TEST_ONLY tên mới"
        duplicate = client.post("/api/admin/taxonomies", headers=headers, json={"kind":"dish_type","group":"dish_type",
            "code":"test_only_type","label":"TEST_ONLY trùng","description":""})
        assert duplicate.status_code == 409, duplicate.text

        core = next(item for item in client.get("/api/admin/taxonomies?kind=dish_type").json()["data"]["items"] if item["code"]=="main")
        assert core["is_core"] is True
        assert client.patch(f"/api/admin/taxonomies/{core['tag_id']}/deleted", headers=headers, json={"deleted":True}).status_code == 409
        assert client.delete(f"/api/admin/taxonomies/{core['tag_id']}/permanent", headers=headers).status_code == 409

        linked = client.put("/api/admin/recipes/1/taxonomies", headers=headers,
            json={"kind":"dish_type","tag_ids":[type_id]})
        assert linked.status_code == 200, linked.text
        linked = client.put("/api/admin/recipes/1/taxonomies", headers=headers,
            json={"kind":"classification","tag_ids":[weather_id,region_id]})
        assert linked.status_code == 200, linked.text
        assignments = client.get("/api/admin/recipes/1/taxonomies?kind=classification").json()["data"]["items"]
        assert {item["tag_id"] for item in assignments if item["selected"]} == {weather_id,region_id}
        blocked = client.delete(f"/api/admin/taxonomies/{weather_id}/permanent", headers=headers)
        assert blocked.status_code == 409
        connection = mysql.connector.connect(**config)
        try:
            assert _sql(connection,"SELECT COUNT(*) FROM recipes WHERE recipe_id=1")[0][0] == 1
        finally:
            connection.close()

        assert client.patch(f"/api/admin/taxonomies/{weather_id}/deleted", headers=headers, json={"deleted":True}).status_code == 200
        deleted_list = client.get("/api/admin/taxonomies?kind=classification&status=deleted").json()["data"]["items"]
        assert any(item["tag_id"]==weather_id for item in deleted_list)
        selected_deleted = client.get("/api/admin/recipes/1/taxonomies?kind=classification").json()["data"]["items"]
        assert any(item["tag_id"]==weather_id and item["selected"] and item["deleted"] for item in selected_deleted)
        assert client.patch(f"/api/admin/taxonomies/{weather_id}/deleted", headers=headers, json={"deleted":False}).status_code == 200
        assert client.put("/api/admin/recipes/1/taxonomies", headers=headers,
            json={"kind":"classification","tag_ids":[region_id]}).status_code == 200
        assert client.delete(f"/api/admin/taxonomies/{weather_id}/permanent", headers=headers).status_code == 200
        assert client.put("/api/admin/recipes/1/taxonomies", headers=headers,
            json={"kind":"dish_type","tag_ids":[]}).status_code == 200
        assert client.delete(f"/api/admin/taxonomies/{type_id}/permanent", headers=headers).status_code == 200
        connection = mysql.connector.connect(**config)
        try:
            assert _sql(connection,"SELECT COUNT(*) FROM recipes WHERE recipe_id=1")[0][0] == 1
            assert _sql(connection,"SELECT COUNT(*) FROM recipe_tag_links WHERE tag_id=%s",(region_id,))[0][0] == 1
        finally:
            connection.close()


def test_admin_taxonomy_ui_desktop_mobile(unified_http_stack):
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    app, _repo, _tcp, _thread, _config, admin_password = unified_http_stack
    web_port = _port()
    server = uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=web_port,log_level="critical",access_log=False))
    thread = threading.Thread(target=server.run,daemon=True)
    thread.start()
    deadline=time.monotonic()+10
    while time.monotonic()<deadline and not server.started:time.sleep(0.05)
    assert server.started,"TEST_ONLY FastAPI did not start"
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            page=browser.new_page(viewport={"width":1440,"height":960})
            page.set_default_timeout(10_000)
            errors=[];page.on("pageerror",lambda error:errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{web_port}/admin/login",wait_until="domcontentloaded")
            page.locator('input[name="username"]').fill("TEST_ONLY_admin")
            page.locator('input[name="password"]').fill(admin_password)
            page.locator("#admin-login-submit").click();page.wait_for_url("**/admin")

            page.locator('[data-admin-view="dish-types"]').click()
            expect(page.locator("#admin-view-dish-types")).to_be_visible()
            expect(page.locator("#admin-view-dish-types [data-taxonomy-rows]")).to_contain_text("Món chính")
            page.locator("#admin-view-dish-types [data-taxonomy-create]").click()
            page.locator("#admin-view-dish-types [data-taxonomy-code]").fill("test_only_browser_type")
            page.locator("#admin-view-dish-types [data-taxonomy-label]").fill("TEST_ONLY browser type")
            page.locator("#admin-view-dish-types [data-taxonomy-description]").fill("TEST_ONLY browser description")
            page.locator("#admin-view-dish-types [data-taxonomy-form] button[type=submit]").click()
            expect(page.locator("#admin-view-dish-types [data-taxonomy-rows]")).to_contain_text("TEST_ONLY browser type")

            manager=page.locator("#admin-view-dish-types")
            manager.locator("[data-taxonomy-recipe-query]").fill("món chính")
            manager.locator("[data-taxonomy-find-recipes]").click()
            recipe_option=manager.locator("[data-taxonomy-recipe] option").filter(has_text="TEST_ONLY món chính").first
            expect(recipe_option).to_have_count(1)
            selected_recipe_id=int(recipe_option.get_attribute("value"))
            manager.locator("[data-taxonomy-recipe]").select_option(value=str(selected_recipe_id))
            manager.locator("[data-taxonomy-options] label").filter(has_text="TEST_ONLY browser type").locator("input").check()
            with page.expect_response(lambda response: response.url.endswith("/taxonomies") and response.request.method=="PUT") as linked:
                manager.locator("[data-taxonomy-save-links]").click()
            assert linked.value.status==200
            stored=page.request.get(f"http://127.0.0.1:{web_port}/api/admin/recipes/{selected_recipe_id}/taxonomies?kind=dish_type").json()["data"]["items"]
            assert any(item["selected"] and item["code"]=="test_only_browser_type" for item in stored)

            page.locator('[data-admin-view="classifications"]').click()
            expect(page.locator("#admin-view-classifications")).to_be_visible()
            page.locator("#admin-view-classifications [data-taxonomy-group]").select_option(value="weather")
            page.set_viewport_size({"width":390,"height":844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), page.evaluate("({width:innerWidth,scroll:document.documentElement.scrollWidth,wide:[...document.querySelectorAll('*')].map(e=>({tag:e.tagName,id:e.id,cls:typeof e.className==='string'?e.className:'',right:Math.round(e.getBoundingClientRect().right),width:Math.round(e.getBoundingClientRect().width)})).filter(e=>e.right>innerWidth+2).slice(0,12)})")
            assert page.locator("#admin-view-classifications").is_visible()
            assert errors==[]
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=5)
        assert not thread.is_alive()


def test_unified_admin_to_user_browser_flow(unified_http_stack, tmp_path):
    """Real Chromium drives the Admin form, then searches the same User catalog."""
    import uvicorn
    from playwright.sync_api import expect, sync_playwright

    app, _repo, _tcp, _thread, _config, admin_password = unified_http_stack
    web_port = _port()
    uvicorn_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=web_port,
                                                    log_level="critical", access_log=False))
    web_thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    web_thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not uvicorn_server.started:
        time.sleep(0.05)
    assert uvicorn_server.started, "TEST_ONLY FastAPI did not start"
    base = f"http://127.0.0.1:{web_port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.set_default_timeout(10_000)
            browser_errors=[]
            meal_responses=[]
            page.on("pageerror", lambda error: browser_errors.append(str(error)))
            page.on("response", lambda response: meal_responses.append(response.json()) if response.url.endswith("/api/meal-plan/v2") else None)
            page.goto(base + "/admin/login", wait_until="domcontentloaded")
            page.locator('input[name="username"]').fill("TEST_ONLY_admin")
            page.locator('input[name="password"]').fill(admin_password)
            page.locator("#admin-login-submit").click()
            page.wait_for_url("**/admin")
            page.locator('[data-admin-view="recipes"]').click()
            create_button = page.locator("#admin-create")
            expect(create_button).to_be_enabled(timeout=10_000)
            create_button.click()
            expect(page.locator("#admin-editor")).to_have_attribute("open", "")
            page.locator("#draft-title").fill("TEST_ONLY browser m\u00f3n \u0103n")
            page.locator("#draft-description").fill("TEST_ONLY m\u00f4 t\u1ea3 qua giao di\u1ec7n Admin")
            page.locator("#draft-minutes").fill("17")
            page.locator("#draft-servings").fill("2")
            page.locator("#draft-minutes-prep").fill("5")
            page.locator("#draft-minutes-cook").fill("12")
            page.locator("#editor-tab-button-ingredients").click()
            assert page.locator("#draft-lines .admin-line").count() == 1, page.locator("#draft-message").inner_text()
            page.locator("#draft-new-ingredient-name").fill("TEST_ONLY inline ingredient")
            page.locator("#draft-new-ingredient-save").click()
            expect(page.locator("#draft-new-ingredient-message")).to_contain_text("\u0110\u00e3 t\u1ea1o v\u00e0 ch\u1ecdn", timeout=10_000)
            assert page.locator("#draft-lines .admin-line [data-line-ingredient]").input_value() not in ("", None)
            page.locator("#draft-lines .admin-line [data-quantity]").fill("TEST_ONLY one portion")
            page.locator("#draft-lines .admin-line [data-amount-kind]").select_option(value="exact")
            page.locator("#draft-lines .admin-line [data-amount-min]").fill("2")
            page.locator("#draft-lines .admin-line [data-unit]").select_option(value="1")
            page.locator('#draft-lines .admin-line-advanced > summary').click()
            page.locator("#draft-lines .admin-line [data-form]").fill("TEST_ONLY cut")
            page.locator("#draft-lines .admin-line [data-basis]").select_option(value="prepared")
            page.locator("#draft-lines .admin-line [data-purpose]").select_option(value="main")
            page.locator("#draft-lines .admin-line [data-scaling]").select_option(value="linear")
            page.locator("#editor-tab-button-instructions").click()
            page.locator("#draft-step-rows textarea").fill("TEST_ONLY step 1: cook and serve.")
            page.locator("#draft-save").click()
            try:
                expect(page.locator("#admin-editor")).not_to_have_attribute("open", "", timeout=10_000)
            except AssertionError:
                raise AssertionError({"editor_message": page.locator("#draft-message").inner_text(),
                    "editor_busy": page.locator("#admin-editor").get_attribute("aria-busy"),
                    "browser_errors": browser_errors})
            expect(page.locator("#admin-recipes")).to_contain_text("TEST_ONLY browser m\u00f3n \u0103n", timeout=10_000)
            page.screenshot(path=str(tmp_path / "unified-v3-admin.png"), full_page=True)

            page.goto(base + "/?view=explore", wait_until="domcontentloaded")
            expect(page.locator('#recommend-button')).to_be_enabled()
            page.locator("#recipe-query").fill("TEST_ONLY browser m\u00f3n \u0103n")
            page.locator("#recommend-button").click()
            expect(page.locator("#results")).to_contain_text("TEST_ONLY browser m\u00f3n \u0103n", timeout=10_000)
            page.screenshot(path=str(tmp_path / "unified-v3-user.png"), full_page=True)

            # Main navigation switches to real search modes and the meal planner.
            page.locator('[data-user-tab="fridge"]').click()
            expect(page.locator('[data-user-tab="fridge"]')).to_have_attribute("aria-current", "page")
            page.locator('[data-user-tab="lunch"]').click()
            expect(page.locator('[data-user-tab="lunch"]')).to_have_attribute("aria-current", "page")
            # Navigation reloads the User page; wait for the asynchronous
            # ingredient restore that applies the lunch time preset.
            expect(page.locator("#max-minutes")).to_have_value("30")
            page.locator('[data-user-tab="meal"]').click()
            expect(page.locator('[data-meal-type="custom"]')).to_be_enabled()
            page.locator('[data-meal-type="custom"]').click()
            page.wait_for_function("document.querySelectorAll('#meal-cards .recipe-card').length === 3", timeout=15_000)
            assert page.locator("#meal-ingredients").get_attribute("aria-busy") == "false", {"errors":browser_errors,"message":page.locator("#meal-message").inner_text(),"url":page.url}
            expect(page.locator('[data-meal-type="custom"]')).to_be_enabled()
            expect(page.locator('[data-meal-type="drinks"]')).to_be_disabled()
            expect(page.locator('[data-meal-type="snacks"]')).to_have_count(0)
            assert page.locator("#meal-cards .recipe-card").count()==3, {"message":page.locator("#meal-message").inner_text(),"data":{k:meal_responses[-1].get("data",{}).get(k) for k in ("dataset_version","classification_version","counts","people","preferences","metadata_version","warnings","reason","changed_slots","plan")} if meal_responses else None,"errors":browser_errors}
            page.screenshot(path=str(tmp_path / "unified-v3-meal-desktop.png"), full_page=True)
            original_pin=page.locator('[data-meal-slot="main:1"]').get_attribute("data-recipe-id")
            page.locator('[data-pin="main:1"]').click()
            expect(page.locator('[data-pin="main:1"]')).to_have_attribute("aria-pressed", "true")
            page.locator("#meal-children-plus").click()
            expect(page.locator("#meal-children")).to_have_text("1")
            expect(page.locator("#meal-cards .recipe-card")).to_have_count(3, timeout=10_000)
            page.locator('[data-layout-plus="main"]').click()
            expect(page.locator("#meal-cards .recipe-card")).to_have_count(4, timeout=10_000)
            assert page.locator('[data-meal-slot="main:1"]').get_attribute("data-recipe-id") == original_pin
            page.locator('[data-meal-type="custom"]').click()
            expect(page.locator("#meal-custom-layout")).to_be_visible()
            expect(page.locator('[data-meal-type="custom"]')).to_have_attribute("aria-pressed", "true")
            page.locator('[data-layout-minus="vegetable"]').click()
            expect(page.locator("#meal-count-vegetable")).to_have_text("0")
            try:
                page.wait_for_function("document.querySelectorAll('#meal-cards .recipe-card').length === 3", timeout=10_000)
            except Exception:
                assert page.locator("#meal-cards .recipe-card").count() == 3, {
                    "message": page.locator("#meal-message").inner_text(),
                    "data": {k: meal_responses[-1].get("data", {}).get(k) for k in ("layout_mode", "counts", "reason", "changed_slots", "plan")} if meal_responses else None,
                    "browser_errors": browser_errors}
            assert page.locator('[data-meal-slot="main:1"]').get_attribute("data-recipe-id") == original_pin
            assert page.locator('[data-meal-slot="vegetable:1"]').count() == 0
            assert meal_responses[-1]["data"]["layout_mode"] == "custom"
            page.locator("#meal-copy-list").click()
            expect(page.locator("#meal-copy-feedback")).to_contain_text("sao chép")
            page.set_viewport_size({"width":390,"height":844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(tmp_path / "unified-v3-meal-mobile.png"), full_page=True)
            page.goto(base + "/?view=explore", wait_until="domcontentloaded")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            for tab in ("explore", "fridge", "meal", "lunch", "account"):
                locator = page.locator("#user-account-tab") if tab == "account" else page.locator("[data-user-tab=\"" + tab + "\"]")
                expect(locator).to_be_visible()
            browser.close()
    finally:
        uvicorn_server.should_exit = True
        web_thread.join(timeout=5)


def test_meal_pairing_metadata_is_loaded_from_test_mysql_and_used_by_gateway(unified_http_stack):
    from fastapi.testclient import TestClient

    app, repo, _tcp, _thread, config, _password = unified_http_stack
    connection = repo.connect()
    try:
        before_version = repo.dataset_version(connection)
        for tag_type, code, label in (
            ("main_ingredient", "TEST_ONLY_chicken", "TEST_ONLY chicken"),
            ("cooking_method", "TEST_ONLY_grill", "TEST_ONLY grill"),
        ):
            _sql(connection, """INSERT INTO recipe_tags(tag_type,code,label,normalized_label)
                VALUES(%s,%s,%s,%s)""", (tag_type, code, label, label.casefold()))
        _sql(connection, """INSERT INTO recipe_tag_links(recipe_id,tag_id)
            SELECT 1,tag_id FROM recipe_tags WHERE tag_type='main_ingredient' AND code='TEST_ONLY_chicken'""")
        _sql(connection, """INSERT INTO recipe_tag_links(recipe_id,tag_id)
            SELECT 2,tag_id FROM recipe_tags WHERE tag_type='cooking_method' AND code='TEST_ONLY_grill'""")
        connection.commit()
        metadata = repo.meal_pairing_metadata(connection, [1, 2, 3])
        assert metadata == {
            1: {"main_ingredient": frozenset({"TEST_ONLY_chicken"})},
            2: {"cooking_method": frozenset({"TEST_ONLY_grill"})},
        }
        assert repo.dataset_version(connection) != before_version
    finally:
        connection.close()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.post("/api/meal-plan/v2", json={
            "counts": {"main": 1, "vegetable": 1, "soup": 1},
        })
        assert response.status_code == 200, response.text
        assert response.json()["data"]["plan"] is not None


def test_meal_plan_v2_does_not_restore_retired_ids_as_catalog_options(unified_http_stack):
    """Saved labels cannot repopulate the live selectable ingredient catalog."""
    import json
    import uvicorn
    from playwright.sync_api import sync_playwright, expect

    app, _repo, _tcp, _tcp_thread, _config, _password = unified_http_stack
    web_port = _port()
    uvicorn_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=web_port,
                                                    log_level="critical", access_log=False))
    web_thread = threading.Thread(target=uvicorn_server.run, daemon=True)
    web_thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not uvicorn_server.started:
        time.sleep(0.05)
    assert uvicorn_server.started, "TEST_ONLY FastAPI did not start"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            retired_id = 8_517_681_007
            saved = {
                "version": 3,
                "conditions": {
                    "ingredient_ids": [retired_id], "excluded_ids": [],
                    "max_minutes": None, "max_total_minutes": None, "max_missing": None,
                    "counts": {"main": 1, "vegetable": 1, "soup": 1}, "layout_mode": "automatic",
                },
                "pins": [], "history": {"main": [], "vegetable": [], "soup": []},
                "publishedNames": [[retired_id, "TEST_ONLY retired ingredient"]], "people": 4,
            }
            page.add_init_script("""
              const saved = JSON.parse(%s);
              sessionStorage.setItem('goiy-meal-plan-v2', JSON.stringify(saved));
              window.__mealNotices = [];
              new MutationObserver(() => {
                const message = document.getElementById('meal-message');
                if (message?.textContent) window.__mealNotices.push(message.textContent);
              }).observe(document, {subtree:true, childList:true, characterData:true});
            """ % json.dumps(json.dumps(saved)))
            page.goto(f"http://127.0.0.1:{web_port}/meal-plan", wait_until="domcontentloaded")
            page.wait_for_function("document.getElementById('meal-ingredients')?.getAttribute('aria-busy')==='false' && document.getElementById('meal-ingredients')?.children.length>0")
            assert page.locator(f'[data-select="{retired_id}"]').count() == 0
            assert page.locator(f'[data-exclude="{retired_id}"]').count() == 0
            assert page.locator("#meal-selected").inner_text().strip() == ""
            notices = page.evaluate("window.__mealNotices")
            assert any("lựa chọn cũ không còn hợp lệ" in value.lower() for value in notices), notices
            assert page.evaluate("JSON.parse(sessionStorage.getItem('goiy-meal-plan-v2')).conditions.ingredient_ids.length") == 0
            browser.close()
    finally:
        uvicorn_server.should_exit = True
        web_thread.join(timeout=3)


def test_unified_meal_tags_do_not_require_optional_source_and_exclude_known_animal_components(unified_http_stack):
    _app, repo, _tcp, _thread, config, _password = unified_http_stack
    connection = mysql.connector.connect(**config)
    try:
        # TEST_ONLY seed: a plant recipe, a complete 3-role North/daily
        # context without source URLs, and one tagged recipe with an animal line.
        _sql(connection, "INSERT INTO ingredients(ingredient_id,name,normalized_name,is_active) VALUES(4,'Thịt gà','thit ga',1)")
        _sql(connection, "INSERT INTO recipes(recipe_id,title,normalized_title,description,role,minutes_total,source_url,is_public) VALUES(4,'TEST_ONLY animal recipe','test_only animal recipe','','main',20,NULL,1)")
        _sql(connection, "INSERT INTO recipe_ingredients(recipe_id,line_no,ingredient_id,quantity_text,requirement) VALUES(4,1,4,'TEST_ONLY 100 g','required')")
        for recipe_id in (1, 2, 3):
            for tag_type, code, label in (("region", "north", "Miền Bắc"), ("occasion", "daily", "Hằng ngày")):
                _sql(connection, "INSERT INTO recipe_tags(tag_type,code,label,normalized_label) VALUES(%s,%s,%s,%s) ON DUPLICATE KEY UPDATE label=VALUES(label)", (tag_type, code, label, label.casefold()))
                _sql(connection, "INSERT INTO recipe_tag_links(recipe_id,tag_id) SELECT %s,tag_id FROM recipe_tags WHERE tag_type=%s AND code=%s", (recipe_id, tag_type, code))
        for recipe_id, code in ((1, "vegetarian"), (4, "vegetarian")):
            _sql(connection, "INSERT INTO recipe_tags(tag_type,code,label,normalized_label) VALUES('diet',%s,'Chay','chay') ON DUPLICATE KEY UPDATE label=VALUES(label)", (code,))
            _sql(connection, "INSERT INTO recipe_tag_links(recipe_id,tag_id) SELECT %s,tag_id FROM recipe_tags WHERE tag_type='diet' AND code=%s", (recipe_id, code))

        candidates = repo.unified.recipes_for_ranking(connection)
        classification = repo.unified.meal_classification(connection)
        catalog = repo.meal_preference_catalog(connection, candidates, classification)
        assert catalog.vegetarian_ids == frozenset({1})
        assert catalog.eligible_ids("region", "north") == frozenset({1, 2, 3})
        choices = catalog.capabilities(layout_support=True)["choices"]
        north = next(item for item in choices["region"] if item["code"] == "north")
        assert north["enabled"] is True
        vegetarian = next(item for item in choices["diet"] if item["code"] == "vegetarian")
        assert vegetarian["enabled"] is False
    finally:
        connection.close()


def test_unified_user_ingredient_catalog_supports_more_than_100(unified_http_stack):
    from fastapi.testclient import TestClient

    app, repo, _tcp, _thread, _config, _password = unified_http_stack
    connection = repo.connect()
    try:
        cursor = connection.cursor()
        try:
            rows = [(ingredient_id, f"TEST_ONLY extra catalog ingredient {ingredient_id}",
                     f"test_only extra catalog ingredient {ingredient_id}")
                    for ingredient_id in range(10_000, 10_105)]
            cursor.executemany(
                "INSERT INTO ingredients(ingredient_id,name,normalized_name,is_active) VALUES(%s,%s,%s,1)", rows
            )
        finally:
            cursor.close()
    finally:
        connection.close()

    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/ingredients?limit=250")
        assert response.status_code == 200, response.text
        items = response.json()["data"]["items"]
        assert len(items) == 108
        assert any(row["id"] == 10_104 for row in items)
        assert client.get("/api/ingredients?limit=251").status_code == 422


def test_tcp_worker_limit_matches_mysql_pool(monkeypatch):
    from source.server.main import configured_tcp_max_connections

    monkeypatch.setenv("TCP_DB_SCHEMA", "unified_v3")
    monkeypatch.setenv("UNIFIED_TCP_DB_POOL_SIZE", "4")
    monkeypatch.delenv("TCP_MAX_CONNECTIONS", raising=False)
    assert configured_tcp_max_connections() == 4
    monkeypatch.setenv("TCP_MAX_CONNECTIONS", "3")
    assert configured_tcp_max_connections() == 3
    monkeypatch.setenv("TCP_MAX_CONNECTIONS", "5")
    with pytest.raises(RuntimeError, match="MySQL pool size"):
        configured_tcp_max_connections()


def test_meal_plan_v1_contract_preserves_unquantified_optional_ingredient():
    from source.web.meal_plan_contract import MealPlanData

    data = {
        "dataset_version": "TEST_ONLY", "classification_version": "TEST_ONLY",
        "algorithm": "meal-plan-v1", "changed_slots": [], "warnings": [], "reason": None,
        "plan": {
            "items": [
                {"slot":"main","recipe_id":1,"title":"TEST_ONLY main","minutes":10,"matched_ids":[],"missing_ids":[],"missing_count":0},
                {"slot":"vegetable","recipe_id":2,"title":"TEST_ONLY vegetable","minutes":10,"matched_ids":[],"missing_ids":[],"missing_count":0},
                {"slot":"soup","recipe_id":3,"title":"TEST_ONLY soup","minutes":10,"matched_ids":[],"missing_ids":[],"missing_count":0},
            ],
            "required_ids":[],"matched_ids":[],"missing_ids":[],"missing_count":0,
            "total_minutes":30,"time_basis":"sum_of_recipe_minutes","shopping_list":[],
            "optional_shopping_list":[{"ingredient_id":4,"name":"TEST_ONLY unknown amount",
                "uses":[{"recipe_id":1,"quantity":None,"is_required":False}]}],
            "optional_missing_ids":[4],
        },
    }
    parsed = MealPlanData.model_validate(data)
    assert parsed.plan.optional_shopping_list[0].uses[0].quantity is None


def test_portion_display_playwright_unified_mysql(unified_http_stack, tmp_path):
    """Real browser -> FastAPI -> TCP -> isolated MySQL portion/list rehearsal."""
    import os
    import shutil
    from pathlib import Path
    import uvicorn
    from playwright.sync_api import sync_playwright, expect

    app, _repo, _tcp, _tcp_thread, config, _password = unified_http_stack
    connection = mysql.connector.connect(**config)
    try:
        unit_id = _sql(connection, "SELECT unit_id FROM units WHERE code='g'")[0][0]
        _sql(connection, "UPDATE ingredients SET name='TEST_ONLY salt',normalized_name='test_only salt' WHERE ingredient_id=1")
        _sql(connection, "UPDATE ingredients SET name='TEST_ONLY vegetable',normalized_name='test_only vegetable' WHERE ingredient_id=2")
        _sql(connection, "UPDATE ingredients SET name='TEST_ONLY meat',normalized_name='test_only meat' WHERE ingredient_id=3")
        _sql(connection, "INSERT INTO ingredients(ingredient_id,name,normalized_name,is_active) VALUES(4,'TEST_ONLY tofu','test_only tofu',1),(5,'TEST_ONLY pepper','test_only pepper',1)")
        _sql(connection, "UPDATE recipes SET servings=4,portion_data_status='estimated',portion_data_evidence='TEST_ONLY original four servings' WHERE recipe_id IN (1,2)")
        _sql(connection, "UPDATE recipes SET servings=NULL WHERE recipe_id=3")
        _sql(connection, "DELETE FROM recipe_ingredients WHERE recipe_id IN (1,2,3)")
        _sql(connection, """INSERT INTO recipe_ingredients
            (recipe_id,line_no,ingredient_id,quantity_text,amount_kind,amount_min,amount_max,unit_id,
             requirement,purpose,ingredient_form,measurement_basis,scaling_mode)
            VALUES
            (1,1,3,'400 g','exact',400,400,%s,'required','main','TEST_ONLY raw','prepared','linear'),
            (1,2,1,'n\u00eam v\u1eeba \u0103n','to_taste',NULL,NULL,NULL,'required','seasoning',NULL,'unknown','unknown'),
            (2,1,2,'200 g','exact',200,200,%s,'required','main',NULL,'unknown','linear'),
            (3,1,4,'200 g','exact',200,200,%s,'required','main','TEST_ONLY chopped','prepared','linear'),
            (3,2,5,'m\u1ed9t \u00edt','to_taste',NULL,NULL,NULL,'optional','seasoning',NULL,'unknown','unknown')""",
            (unit_id, unit_id, unit_id))
        connection.commit()
    finally:
        connection.close()

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        web_port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=web_port, log_level="error"))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not server.started:
            time.sleep(.02)
        assert server.started, "TEST_ONLY FastAPI did not start"
        browser_path = next((Path(root) / rel for root in (os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)")) if root
            for rel in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe")
            if (Path(root) / rel).is_file()), None)
        assert browser_path, "Playwright browser executable not installed"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=str(browser_path))
            try:
                for width in (1280, 390):
                    page = browser.new_page(viewport={"width": width, "height": 900}, device_scale_factor=1)
                    page_errors = []
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{web_port}/meal-plan", wait_until="domcontentloaded")
                    page.wait_for_function("document.getElementById('meal-ingredients')?.getAttribute('aria-busy')==='false'")
                    # Test Custom allocation; these TEST_ONLY names/unknown
                    # quantities intentionally cannot qualify a Daily combo.
                    page.locator('[data-meal-type="custom"]').click()
                    page.wait_for_function("document.querySelectorAll('[data-meal-slot]').length===3 && document.getElementById('meal-results').getAttribute('aria-busy')==='false'")
                    assert page.locator('#meal-portions').count() == 0
                    assert page.locator('#meal-shopping-title').inner_text() == 'Danh sách đi chợ'
                    assert page.locator('#meal-copy-list').is_visible()
                    page.wait_for_function("document.getElementById('meal-results').getAttribute('aria-busy')==='false'")
                    assert page.locator('#meal-portions').count() == 0
                    for target, meat, vegetable in ((4, "400 g", "200 g"), (2, "200 g", "100 g"), (6, "600 g", "300 g")):
                        current = int(page.locator("#meal-adults").inner_text()) + int(page.locator("#meal-children").inner_text())
                        while current > target:
                            with page.expect_response(lambda r: r.url.endswith("/api/meal-plan/calculate")):
                                page.locator("#meal-adults-minus").click()
                            current -= 1
                        while current < target:
                            with page.expect_response(lambda r: r.url.endswith("/api/meal-plan/calculate")):
                                page.locator("#meal-adults-plus").click()
                            current += 1
                        expect(page.locator('#meal-portion-summary')).to_contain_text(f'Định lượng chuẩn bị cho {target} người')
                        expect(page.locator('#meal-shopping')).to_contain_text(f'TEST_ONLY meat: {meat}')
                        shopping = " ".join(page.locator("#meal-shopping").inner_text().split())
                        assert f"TEST_ONLY meat: {meat}" in shopping
                        assert f"TEST_ONLY vegetable: {vegetable}" in shopping
                        assert "Gi\u1eef ri\u00eang t\u1eebng d\u00f2ng; kh\u00f4ng \u0111\u1ee7 c\u0103n c\u1ee9 \u0111\u1ec3 g\u1ed9p." in shopping
                        assert "TEST_ONLY salt: n\u00eam v\u1eeba \u0103n" in shopping
                        assert "TEST_ONLY tofu: 200 g" in shopping
                        assert "TEST_ONLY pepper: m\u1ed9t \u00edt" in shopping
                        assert "Kh\u00f4ng nh\u00e2n: c\u00f4ng th\u1ee9c thi\u1ebfu kh\u1ea9u ph\u1ea7n g\u1ed1c h\u1ee3p l\u1ec7." in shopping
                        assert "Ch\u01b0a c\u00f3 l\u01b0\u1ee3ng s\u1ed1 c\u1ee5 th\u1ec3; kh\u00f4ng t\u1ef1 coi l\u00e0 0." in shopping
                        assert "TEST_ONLY salt: n\u00eam v\u1eeba \u0103n" in shopping
                        assert "200 g" in shopping, "Missing-base recipe retains the original amount"
                        assert "Danh sách gồm lượng đã phân bổ và các lượng giữ nguyên khi chưa đủ cơ sở tính." in page.locator("#meal-shopping-note").inner_text()
                    assert page.locator('#meal-portions').count() == 0
                    assert page.locator('#meal-copy-list').is_visible()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                    page.screenshot(path=str(tmp_path / f"portion-display-{width}.png"), full_page=True)
                    assert page_errors == []
                    page.close()
            finally:
                browser.close()
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)
        assert not server_thread.is_alive(), "TEST_ONLY FastAPI stopped cleanly"



def test_unified_permanent_deletion_is_guarded_and_cleans_test_rows(unified_http_stack):
    """Only purpose-created TEST_ONLY rows may be purged; guards cross HTTP/TCP/MySQL."""
    from fastapi.testclient import TestClient

    app, _repo, _tcp, _thread, config, admin_password = unified_http_stack
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/api/admin/login", json={
            "username": "TEST_ONLY_admin", "password": admin_password,
        }).status_code == 200
        csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]

        # Auth and CSRF remain mandatory for permanent deletion.
        unauthorized = TestClient(app).delete("/api/admin/ingredients/4/permanent")
        assert unauthorized.status_code == 401
        no_csrf = client.delete("/api/admin/ingredients/4/permanent")
        assert no_csrf.status_code == 403

        created_ingredient = client.post("/api/admin/ingredients", headers={"X-CSRF-Token": csrf},
                                         json={"name": "TEST_ONLY permanent-delete ingredient"})
        assert created_ingredient.status_code == 200, created_ingredient.text
        ingredient_id = created_ingredient.json()["data"]["ingredient_id"]

        create = client.post("/api/admin/catalog-recipes", headers={"X-CSRF-Token": csrf}, json={
            "title": "TEST_ONLY permanent-delete recipe",
            "description": "TEST_ONLY",
            "instructions": "TEST_ONLY step",
            "minutes": 12,
            "role": "side",
            "servings": "2",
            "steps": [{"instruction": "TEST_ONLY step"}],
            "ingredients": [{"ingredient_id": ingredient_id, "quantity_raw": "TEST_ONLY 1 unit",
                             "amount_kind": "exact", "amount_min": "1", "amount_max": "1",
                             "unit_id": 1, "requirement": "required", "purpose": "main",
                             "measurement_basis": "prepared", "scaling_mode": "linear"}],
            "idempotency_key": str(uuid.uuid4()),
        })
        assert create.status_code == 200, create.text
        recipe_id = create.json()["data"]["recipe_id"]

        # Active and referenced ingredients cannot be purged; visible recipes cannot be purged.
        blocked_active = client.delete(f"/api/admin/ingredients/{ingredient_id}/permanent",
                                       headers={"X-CSRF-Token": csrf})
        assert blocked_active.status_code == 409, blocked_active.text
        deactivated = client.patch(f"/api/admin/ingredients/{ingredient_id}/active",
                                   headers={"X-CSRF-Token": csrf}, json={"is_active": False})
        assert deactivated.status_code == 200
        blocked_referenced = client.delete(f"/api/admin/ingredients/{ingredient_id}/permanent",
                                           headers={"X-CSRF-Token": csrf})
        assert blocked_referenced.status_code == 409
        blocked_visible = client.request("DELETE", f"/api/admin/catalog-recipes/{recipe_id}/permanent",
                                         headers={"X-CSRF-Token": csrf}, json={
                                             "confirm_user_content_delete": False,
                                             "expected_achievement_counts": {"posts": 0, "comments": 0, "images": 0},
                                         })
        assert blocked_visible.status_code == 409

        state = client.patch(f"/api/admin/catalog-recipes/{recipe_id}/state",
                             headers={"X-CSRF-Token": csrf}, json={"is_visible": True, "is_deleted": True})
        assert state.status_code == 200, state.text
        assert client.get(f"/api/recipes/{recipe_id}").status_code == 404
        restored_recipe = client.patch(f"/api/admin/catalog-recipes/{recipe_id}/state",
                                       headers={"X-CSRF-Token": csrf}, json={"is_visible": True, "is_deleted": False})
        assert restored_recipe.status_code == 200, restored_recipe.text
        assert client.get(f"/api/recipes/{recipe_id}").status_code == 200
        state_again = client.patch(f"/api/admin/catalog-recipes/{recipe_id}/state",
                                   headers={"X-CSRF-Token": csrf}, json={"is_visible": True, "is_deleted": True})
        assert state_again.status_code == 200, state_again.text
        assert client.get(f"/api/recipes/{recipe_id}").status_code == 404
        deleted_rows = client.get("/api/admin/recipes?visibility=deleted&limit=50").json()["data"]["items"]
        deleted_row = next(row for row in deleted_rows if row["recipe_id"] == recipe_id)
        assert deleted_row["can_permanently_delete"] is True

        purged_recipe = client.request("DELETE", f"/api/admin/catalog-recipes/{recipe_id}/permanent",
                                       headers={"X-CSRF-Token": csrf}, json={
                                           "confirm_user_content_delete": False,
                                           "expected_achievement_counts": {"posts": 0, "comments": 0, "images": 0},
                                       })
        assert purged_recipe.status_code == 200, purged_recipe.text
        check = mysql.connector.connect(**config)
        try:
            assert _sql(check, "SELECT COUNT(*) FROM recipes WHERE recipe_id=%s", (recipe_id,))[0][0] == 0
            for table in ("recipe_ingredients", "recipe_steps", "recipe_tag_links", "recipe_images", "recipe_edit_history"):
                assert _sql(check, f"SELECT COUNT(*) FROM {table} WHERE recipe_id=%s", (recipe_id,))[0][0] == 0
        finally:
            check.close()

        ingredient_rows = client.get("/api/admin/ingredients?status=inactive&limit=50").json()["data"]["items"]
        ingredient_row = next(row for row in ingredient_rows if row["ingredient_id"] == ingredient_id)
        assert ingredient_row["usage_count"] == 0 and ingredient_row["can_permanently_delete"] is True
        purged_ingredient = client.delete(f"/api/admin/ingredients/{ingredient_id}/permanent",
                                          headers={"X-CSRF-Token": csrf})
        assert purged_ingredient.status_code == 200, purged_ingredient.text
        assert not any(row["id"] == ingredient_id for row in client.get("/api/ingredients?limit=100").json()["data"]["items"])

        # Legacy identities can be purged only after soft-delete and explicit empty-content snapshot.
        legacy_deleted = client.patch("/api/admin/catalog-recipes/1/state", headers={"X-CSRF-Token": csrf},
                                      json={"is_visible": True, "is_deleted": True})
        assert legacy_deleted.status_code == 200
        blocked_legacy = client.request("DELETE", "/api/admin/catalog-recipes/1/permanent", headers={"X-CSRF-Token": csrf}, json={
            "confirm_user_content_delete": False,
            "expected_achievement_counts": {"posts": 0, "comments": 0, "images": 0},
        })
        assert blocked_legacy.status_code == 200, blocked_legacy.text
        assert client.get("/api/recipes/1").status_code == 404



def test_permanent_recipe_delete_handles_legacy_mapping_admin_content_and_rollback(
        unified_http_stack, tmp_path):
    """Exercises recipe deletion over HTTP -> real TCP -> private TEST_ONLY MySQL."""
    import base64
    import io
    from PIL import Image
    from fastapi.testclient import TestClient

    app, _repo, _tcp, _thread, config, admin_password = unified_http_stack
    connection = mysql.connector.connect(**config)
    try:
        image_stream = io.BytesIO()
        Image.new("RGB", (3, 2), (40, 100, 70)).save(image_stream, format="PNG")
        image_bytes = image_stream.getvalue()
        image_key = "a" * 32 + ".png"
        image_path = tmp_path / "images" / image_key
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image_bytes)
        image_hash = hashlib.sha256(image_bytes).hexdigest()
        for recipe_id, title, role in (
            (4, "TEST_ONLY legacy delete", "main"),
            (5, "TEST_ONLY mapped delete", "side"),
        ):
            _sql(connection, """INSERT INTO recipes(recipe_id,title,normalized_title,description,role,minutes_total,
                instructions_legacy,is_public,edit_version) VALUES(%s,%s,%s,'TEST_ONLY',%s,15,'TEST_ONLY step',1,1)""",
                (recipe_id, title, title.casefold(), role))
            _sql(connection, """INSERT INTO recipe_ingredients(recipe_id,line_no,ingredient_id,quantity_text,
                amount_kind,requirement,purpose) VALUES(%s,1,1,'TEST_ONLY amount','unknown','required','main')""",
                (recipe_id,))
            _sql(connection, "INSERT INTO recipe_steps(recipe_id,step_no,instruction) VALUES(%s,1,'TEST_ONLY step')",
                (recipe_id,))
        tag_id = _sql(connection, """INSERT INTO recipe_tags(tag_type,code,label,normalized_label)
            VALUES('region','test_only_delete','TEST_ONLY','test_only')""")
        _sql(connection, "INSERT INTO recipe_tag_links(recipe_id,tag_id) VALUES(4,%s)", (tag_id,))
        _sql(connection, """INSERT INTO recipe_images(recipe_id,storage_key,media_type,byte_size,width,height,sha256)
            VALUES(4,%s,'image/png',%s,3,2,%s)""", (image_key, len(image_bytes), image_hash))
        _sql(connection, "INSERT INTO recipe_id_map(source_kind,source_id,recipe_id) VALUES('legacy',404,4)")
        _sql(connection, "INSERT INTO recipe_id_map(source_kind,source_id,recipe_id) VALUES('v2_catalog',505,5)")
    finally:
        connection.close()

    with TestClient(app, base_url="http://127.0.0.1") as admin:
        login = admin.post("/api/admin/login", json={"username": "TEST_ONLY_admin", "password": admin_password})
        assert login.status_code == 200
        csrf = admin.get("/api/admin/session").json()["data"]["csrf_token"]
        user_unauthorized = TestClient(app).request("DELETE", "/api/admin/catalog-recipes/4/permanent", json={
            "confirm_user_content_delete": False, "expected_achievement_counts": {"posts": 0, "comments": 0, "images": 0}})
        assert user_unauthorized.status_code == 401
        no_csrf = admin.request("DELETE", "/api/admin/catalog-recipes/4/permanent", json={
            "confirm_user_content_delete": False, "expected_achievement_counts": {"posts": 0, "comments": 0, "images": 0}})
        assert no_csrf.status_code == 403

        # Create an Admin-owned recipe over HTTP, without touching fixture recipes.
        created = admin.post("/api/admin/catalog-recipes", headers={"X-CSRF-Token": csrf}, json={
            "title": "TEST_ONLY admin-created delete", "description": "TEST_ONLY", "instructions": "TEST_ONLY step",
            "minutes": 12, "role": "other", "servings": "2",
            "steps": [{"instruction": "TEST_ONLY step"}],
            "ingredients": [{"ingredient_id": 1, "quantity_raw": "TEST_ONLY amount",
                             "amount_kind": "unknown", "requirement": "required", "purpose": "main"}],
            "idempotency_key": str(uuid.uuid4()),
        })
        assert created.status_code == 200, created.text
        admin_recipe_id = int(created.json()["data"]["recipe_id"])
        assert admin_recipe_id > 2**32

        user = TestClient(app, base_url="http://127.0.0.1")
        registered = user.post("/api/auth/register", json={
            "username": "test_only_achievement_user", "password": "TEST_ONLY_user_password_123",
            "password_confirmation": "TEST_ONLY_user_password_123"})
        assert registered.status_code == 200, registered.text
        user_csrf = user.get("/api/auth/session").json()["data"]["csrf_token"]
        post = user.post("/api/achievements", headers={"X-CSRF-Token": user_csrf}, json={
            "recipe_id": 5, "description": "TEST_ONLY achievement", "changed_ingredients": "",
            "request_key": str(uuid.uuid4()),
            "images": [{"media_type": "image/png", "data_base64": base64.b64encode(image_bytes).decode("ascii")}],
        })
        assert post.status_code == 200, post.text
        post_id = int(post.json()["data"]["post_id"])
        comment = user.post(f"/api/achievements/{post_id}/comments", headers={"X-CSRF-Token": user_csrf},
                            json={"body": "TEST_ONLY comment"})
        assert comment.status_code == 200, comment.text
        connection = mysql.connector.connect(**config)
        try:
            achievement_key = _sql(connection, "SELECT storage_key FROM achievement_images WHERE post_id=%s", (post_id,))[0][0]
        finally:
            connection.close()
        achievement_path = tmp_path / "achievement-images" / achievement_key
        assert image_path.is_file() and achievement_path.is_file()

        # Soft-delete all three identity classes. User reads must hide them immediately.
        for recipe_id in (4, 5, admin_recipe_id):
            response = admin.patch(f"/api/admin/catalog-recipes/{recipe_id}/state", headers={"X-CSRF-Token": csrf},
                                   json={"is_visible": True, "is_deleted": True})
            assert response.status_code == 200, response.text
            assert admin.get(f"/api/recipes/{recipe_id}").status_code == 404
        deleted = admin.get("/api/admin/recipes?visibility=deleted&limit=50").json()["data"]["items"]
        rows = {int(row["recipe_id"]): row for row in deleted}
        assert all(rows[rid]["can_permanently_delete"] for rid in (4, 5, admin_recipe_id))
        assert rows[4]["has_identity_mapping"] is True and rows[5]["has_identity_mapping"] is True
        counts = {"posts": rows[5]["achievement_post_count"],
                  "comments": rows[5]["achievement_comment_count"],
                  "images": rows[5]["achievement_image_count"]}
        assert counts == {"posts": 1, "comments": 1, "images": 1}

        # The current content snapshot and a distinct second confirmation are mandatory.
        request_url = "/api/admin/catalog-recipes/5/permanent"
        unconfirmed = admin.request("DELETE", request_url, headers={"X-CSRF-Token": csrf}, json={
            "confirm_user_content_delete": False, "expected_achievement_counts": counts})
        assert unconfirmed.status_code == 409
        stale = admin.request("DELETE", request_url, headers={"X-CSRF-Token": csrf}, json={
            "confirm_user_content_delete": True, "expected_achievement_counts": {"posts": 1, "comments": 0, "images": 1}})
        assert stale.status_code == 409

        # A restrictive FK simulates a concurrent/protected dependent; the full transaction rolls back.
        connection = mysql.connector.connect(**config)
        try:
            _sql(connection, """CREATE TABLE test_recipe_delete_blocker (
                recipe_id BIGINT UNSIGNED NOT NULL,
                CONSTRAINT fk_test_recipe_delete_blocker FOREIGN KEY(recipe_id) REFERENCES recipes(recipe_id) ON DELETE RESTRICT
            ) ENGINE=InnoDB""")
            _sql(connection, "INSERT INTO test_recipe_delete_blocker(recipe_id) VALUES(5)")
        finally:
            connection.close()
        blocked = admin.request("DELETE", request_url, headers={"X-CSRF-Token": csrf}, json={
            "confirm_user_content_delete": True, "expected_achievement_counts": counts})
        assert blocked.status_code == 409, blocked.text
        connection = mysql.connector.connect(**config)
        try:
            for table in ("recipes", "recipe_id_map", "recipe_ingredients", "recipe_steps", "achievement_posts", "achievement_comments", "achievement_images"):
                column = "recipe_id" if table not in {"achievement_comments", "achievement_images"} else "post_id"
                key = 5 if column == "recipe_id" else post_id
                assert _sql(connection, f"SELECT COUNT(*) FROM {table} WHERE {column}=%s", (key,))[0][0] > 0
            _sql(connection, "DELETE FROM test_recipe_delete_blocker WHERE recipe_id=5")
            _sql(connection, "DROP TABLE test_recipe_delete_blocker")
        finally:
            connection.close()
        assert achievement_path.is_file()

        removed = admin.request("DELETE", request_url, headers={"X-CSRF-Token": csrf}, json={
            "confirm_user_content_delete": True, "expected_achievement_counts": counts})
        assert removed.status_code == 200, removed.text
        assert removed.json()["data"]["image_cleanup_pending"] is False
        assert removed.json()["data"]["achievement_counts"] == counts
        assert not achievement_path.exists()

        for recipe_id in (4, admin_recipe_id):
            result = admin.request("DELETE", f"/api/admin/catalog-recipes/{recipe_id}/permanent", headers={"X-CSRF-Token": csrf}, json={
                "confirm_user_content_delete": False, "expected_achievement_counts": {"posts": 0, "comments": 0, "images": 0}})
            assert result.status_code == 200, result.text
        assert not image_path.exists()
        connection = mysql.connector.connect(**config)
        try:
            for recipe_id in (4, 5, admin_recipe_id):
                assert _sql(connection, "SELECT COUNT(*) FROM recipes WHERE recipe_id=%s", (recipe_id,))[0][0] == 0
                assert _sql(connection, "SELECT COUNT(*) FROM recipe_id_map WHERE recipe_id=%s", (recipe_id,))[0][0] == 0
                for table in ("recipe_ingredients", "recipe_steps", "recipe_tag_links", "recipe_images", "recipe_edit_history"):
                    assert _sql(connection, f"SELECT COUNT(*) FROM {table} WHERE recipe_id=%s", (recipe_id,))[0][0] == 0
            assert _sql(connection, "SELECT COUNT(*) FROM achievement_posts WHERE recipe_id=5")[0][0] == 0
            assert _sql(connection, "SELECT COUNT(*) FROM achievement_comments WHERE post_id=%s", (post_id,))[0][0] == 0
            assert _sql(connection, "SELECT COUNT(*) FROM achievement_images WHERE post_id=%s", (post_id,))[0][0] == 0
        finally:
            connection.close()

        # Existing recipes remain usable after purge.
        for recipe_id in (1, 2, 3):
            assert admin.get(f"/api/recipes/{recipe_id}").status_code == 200
        assert admin.post("/api/search", json={"query": "TEST_ONLY"}).status_code == 200
        assert admin.post("/api/recommend", json={"ingredient_ids": [1], "algorithm": "proposed"}).status_code == 200
        assert admin.post("/api/meal-plan", json={}).status_code == 200
        assert admin.post("/api/meal-plan/v2", json={"people": 4}).status_code == 200
        user.close()


def test_admin_permanent_recipe_delete_playwright_desktop_and_mobile(unified_http_stack, tmp_path):
    """The Admin UI soft-deletes and purges legacy, mapped, and Admin-created TEST_ONLY recipes."""
    from fastapi.testclient import TestClient
    from playwright.sync_api import sync_playwright
    import uvicorn

    app, _repo, _tcp, _thread, config, admin_password = unified_http_stack
    connection = mysql.connector.connect(**config)
    try:
        _sql(connection, "INSERT INTO recipe_id_map(source_kind,source_id,recipe_id) VALUES('legacy',101,1)")
        _sql(connection, "INSERT INTO recipe_id_map(source_kind,source_id,recipe_id) VALUES('v2_catalog',202,2)")
    finally:
        connection.close()

    # Candidate 3 represents a recipe created through the real Admin write path.
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/api/admin/login", json={
            "username": "TEST_ONLY_admin", "password": admin_password,
        }).status_code == 200
        csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]
        created = client.post("/api/admin/catalog-recipes", headers={"X-CSRF-Token": csrf}, json={
            "title": "TEST_ONLY Playwright Admin-created recipe", "description": "TEST_ONLY",
            "instructions": "TEST_ONLY step", "minutes": 10, "role": "other", "servings": "2",
            "steps": [{"instruction": "TEST_ONLY step"}],
            "ingredients": [{"ingredient_id": 1, "quantity_raw": "TEST_ONLY amount",
                             "amount_kind": "unknown", "requirement": "required", "purpose": "main"}],
            "idempotency_key": str(uuid.uuid4()),
        })
        assert created.status_code == 200, created.text
        admin_recipe_id = int(created.json()["data"]["recipe_id"])
    candidates = (1, 2, admin_recipe_id)

    web_port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=web_port,
                                           log_level="critical", lifespan="off"))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not server.started:
        time.sleep(0.05)
    assert server.started, "TEST_ONLY FastAPI did not start for browser verification"
    browser_error = []
    delete_request_ids = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: browser_error.append(str(error)))
            page.goto(f"http://127.0.0.1:{web_port}/admin/login", wait_until="networkidle")
            page.locator('input[name="username"]').fill("TEST_ONLY_admin")
            page.locator('input[name="password"]').fill(admin_password)
            page.locator("#admin-login-submit").click()
            page.wait_for_url(f"http://127.0.0.1:{web_port}/admin")
            assert page.locator('script[src="/static/admin.js?v=meal-stage4-20261112"]').count() == 1
            page.locator('[data-admin-view="recipes"]').click()

            for index, recipe_id in enumerate(candidates):
                page.set_viewport_size({"width": 390, "height": 844} if index % 2 else {"width": 1440, "height": 1000})
                page.locator("#admin-recipe-visibility").select_option("visible")
                delete = page.locator(f'[data-delete="{recipe_id}"]')
                delete.wait_for(state="visible", timeout=10000)
                page.once("dialog", lambda dialog: dialog.accept())
                delete.click()
                page.locator(f'[data-delete="{recipe_id}"]').wait_for(state="detached", timeout=10000)

                page.locator("#admin-recipe-visibility").select_option("deleted")
                permanent = page.locator(f'[data-recipe-permanent="{recipe_id}"]')
                permanent.wait_for(state="visible", timeout=10000)
                confirmed_dialogs = []
                page.once("dialog", lambda dialog, target=confirmed_dialogs: (target.append(dialog.message), dialog.accept()))
                with page.expect_response(lambda response: f"/api/admin/catalog-recipes/{recipe_id}/permanent" in response.url) as response_info:
                    permanent.click()
                response = response_info.value
                assert response.request.method == "DELETE"
                assert response.request.post_data_json == {
                    "confirm_user_content_delete": False,
                    "expected_achievement_counts": {"posts": 0, "comments": 0, "images": 0},
                }
                assert response.status == 200
                envelope = response.json()
                request_id = envelope["request_id"]
                assert request_id == response.headers.get("x-request-id")
                assert envelope["ok"] is True and envelope["error"] is None
                delete_request_ids.append(request_id)
                assert confirmed_dialogs and str(recipe_id) in confirmed_dialogs[0]
                page.locator(f'[data-recipe-permanent="{recipe_id}"]').wait_for(state="detached", timeout=10000)

            assert browser_error == []
            browser.close()
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)
        assert not server_thread.is_alive(), "TEST_ONLY FastAPI stopped cleanly after browser verification"

    gateway_rows = [json.loads(line) for line in (tmp_path / "fastapi-test.jsonl").read_text(encoding="utf-8").splitlines()]
    tcp_rows = [json.loads(line) for line in (tmp_path / "tcp-test.jsonl").read_text(encoding="utf-8").splitlines()]
    for request_id in delete_request_ids:
        gateway = [row for row in gateway_rows if row.get("request_id") == request_id and row.get("op") == "ADMIN_DELETE_RECIPE_PERMANENT"]
        tcp = [row for row in tcp_rows if row.get("request_id") == request_id and row.get("op") == "ADMIN_DELETE_RECIPE_PERMANENT"]
        assert gateway and gateway[-1]["outcome"] == "response" and gateway[-1]["error_code"] is None
        assert tcp and tcp[-1]["outcome"] == "ok" and tcp[-1]["error_code"] is None

    connection = mysql.connector.connect(**config)
    try:
        assert _sql(connection, "SELECT COUNT(*) FROM recipes WHERE recipe_id IN (%s,%s,%s)", candidates)[0][0] == 0
        assert _sql(connection, "SELECT COUNT(*) FROM recipe_id_map WHERE recipe_id IN (%s,%s,%s)", candidates)[0][0] == 0
        assert _sql(connection, "SELECT COUNT(*) FROM recipes WHERE recipe_id NOT IN (%s,%s,%s)", candidates)[0][0] == 1
        assert _sql(connection, "SELECT COUNT(*) FROM recipes WHERE recipe_id=3")[0][0] == 1
    finally:
        connection.close()


def test_feedback_http_tcp_mysql_and_admin_ui_playwright(unified_http_stack, tmp_path):
    import base64
    import io
    from fastapi.testclient import TestClient
    from PIL import Image
    from playwright.sync_api import sync_playwright
    import uvicorn
    import source.web.main as web_main

    app, _repo, _tcp, _tcp_thread, config, admin_password = unified_http_stack
    web_main._FEEDBACK_RATE_BUCKETS.clear()
    assert all(web_main._feedback_rate_allowed("TEST_ONLY_rate", now=100 + index) for index in range(5))
    assert not web_main._feedback_rate_allowed("TEST_ONLY_rate", now=105)
    assert web_main._feedback_rate_allowed("TEST_ONLY_rate", now=1000)
    web_main._FEEDBACK_RATE_BUCKETS.clear()
    output = io.BytesIO()
    Image.new("RGB", (5, 4), (55, 110, 70)).save(output, format="PNG")
    photo = base64.b64encode(output.getvalue()).decode("ascii")
    with TestClient(app, base_url="http://127.0.0.1") as guest:
        no_photo = guest.post("/api/feedback", json={"category":"bug", "content":"TEST_ONLY guest feedback", "request_key":str(uuid.uuid4()), "image":None})
        assert no_photo.status_code == 200 and no_photo.json()["data"]["created"] is True
        assert no_photo.headers["x-request-id"] == no_photo.json()["request_id"]
        assert guest.get("/api/admin/feedback").status_code == 401
        invalid_image = guest.post("/api/feedback", json={"category":"other", "content":"TEST_ONLY invalid photo", "request_key":str(uuid.uuid4()), "image":{"media_type":"image/png", "data_base64":base64.b64encode(b"not an image").decode("ascii")}})
        assert invalid_image.status_code == 422
        user = TestClient(app, base_url="http://127.0.0.1")
        assert user.post("/api/auth/register", json={"username":"TEST_ONLY_feedback_user", "password":"TEST_ONLY_feedback_password_123", "password_confirmation":"TEST_ONLY_feedback_password_123"}).status_code == 200
        csrf = user.get("/api/auth/session").json()["data"]["csrf_token"]
        with_photo = user.post("/api/feedback", headers={"X-CSRF-Token":csrf}, json={"category":"feature", "content":"TEST_ONLY signed-in feedback", "request_key":str(uuid.uuid4()), "image":{"media_type":"image/png", "data_base64":photo}})
        assert with_photo.status_code == 200, with_photo.text
        feedback_id = with_photo.json()["data"]["feedback_id"]
        assert user.post("/api/feedback", json={"category":"other", "content":"TEST_ONLY csrf", "request_key":str(uuid.uuid4()), "image":None}).status_code == 403
        check = mysql.connector.connect(**config)
        try:
            image_key = _sql(check, "SELECT image_storage_key FROM feedback_submissions WHERE feedback_id=%s", (feedback_id,))[0][0]
        finally:
            check.close()
        feedback_image_path = tmp_path / "feedback-images" / image_key
        assert feedback_image_path.is_file()
        user.close()
        admin_api = TestClient(app, base_url="http://127.0.0.1")
        assert admin_api.post("/api/admin/login", json={"username":"TEST_ONLY_admin", "password":admin_password}).status_code == 200
        admin_session = admin_api.get("/api/admin/session").json()["data"]
        assert admin_api.patch(f"/api/admin/feedback/{feedback_id}/status", json={"status":"resolved"}).status_code == 403
        assert admin_api.delete(f"/api/admin/feedback/{feedback_id}").status_code == 403
        assert admin_api.patch(f"/api/admin/feedback/{feedback_id}/status", headers={"X-CSRF-Token":admin_session["csrf_token"]}, json={"status":"resolved"}).status_code == 200
        assert admin_api.get(f"/api/admin/feedback/{feedback_id}").status_code == 200
        admin_api.close()

    # Clear at most the two earlier local submissions so the UI can test two more.
    web_main._FEEDBACK_RATE_BUCKETS.clear()
    port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not server.started:
        time.sleep(0.05)
    assert server.started
    errors = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.set_viewport_size({"width":1440,"height":1000})
            page.goto(f"http://127.0.0.1:{port}/", wait_until="domcontentloaded")
            assert page.locator("#feedback-open").is_visible()
            page.locator("#feedback-open").click()
            page.locator("#feedback-dialog").wait_for(state="visible")
            page.locator("#feedback-content").fill("TEST_ONLY browser desktop feedback")
            with page.expect_response(lambda response: response.url.endswith("/api/feedback")) as desktop_response:
                page.locator("#feedback-submit").click()
            assert desktop_response.value.status == 200
            page.get_by_text("Cảm ơn bạn! Góp ý đã được gửi.").wait_for(state="visible")

            page.set_viewport_size({"width":390,"height":844})
            page.locator("#feedback-open").click()
            page.locator("#feedback-content").fill("TEST_ONLY browser mobile feedback")
            page.locator("#feedback-image").set_input_files({"name":"test.png", "mimeType":"image/png", "buffer":output.getvalue()})
            with page.expect_response(lambda response: response.url.endswith("/api/feedback")) as mobile_response:
                page.locator("#feedback-submit").click()
            assert mobile_response.value.status == 200
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

            page.set_viewport_size({"width":1440,"height":1000})
            page.goto(f"http://127.0.0.1:{port}/admin/login", wait_until="domcontentloaded")
            page.locator('input[name="username"]').fill("TEST_ONLY_admin")
            page.locator('input[name="password"]').fill(admin_password)
            page.locator("#admin-login-submit").click()
            page.wait_for_url(f"http://127.0.0.1:{port}/admin")
            page.locator('[data-admin-view="feedback"]').click()
            row = page.locator(f'#admin-feedback-list tr:has([data-feedback-view="{feedback_id}"])')
            row.wait_for(state="visible")
            assert row.get_by_text("Đề xuất tính năng").is_visible()
            browser_dialogs = []
            page.once("dialog", lambda dialog: (browser_dialogs.append(dialog.message), dialog.accept()))
            page.locator(f'[data-feedback-view="{feedback_id}"]').click()
            page.locator("#admin-feedback-dialog").wait_for(state="visible")
            assert browser_dialogs == []
            assert page.locator(".admin-feedback-full-image").is_visible()
            page.locator("#admin-feedback-dialog-close").click()
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator(f'[data-feedback-toggle="{feedback_id}"]').click()
            row.wait_for(state="visible")
            assert row.get_by_text("Đã xử lý").is_visible()
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator(f'[data-feedback-delete="{feedback_id}"]').click()
            row.wait_for(state="detached")
            assert errors == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()

    rows = [json.loads(line) for line in (tmp_path / "tcp-test.jsonl").read_text(encoding="utf-8").splitlines()]
    feedback_ops = {row.get("op") for row in rows if row.get("op", "").startswith("ADMIN_FEEDBACK") or row.get("op") == "FEEDBACK_CREATE"}
    assert {"FEEDBACK_CREATE", "ADMIN_FEEDBACK_LIST", "ADMIN_FEEDBACK_GET", "ADMIN_FEEDBACK_IMAGE_GET", "ADMIN_FEEDBACK_SET_STATUS", "ADMIN_FEEDBACK_DELETE"} <= feedback_ops
    assert not feedback_image_path.exists()
    connection = mysql.connector.connect(**config)
    try:
        assert _sql(connection, "SELECT COUNT(*) FROM feedback_submissions WHERE feedback_id=%s", (feedback_id,))[0][0] == 0
    finally:
        connection.close()


def test_portion_review_admin_roundtrip_and_filters(unified_http_stack):
    from fastapi.testclient import TestClient
    app, repo, tcp, thread, config, password = unified_http_stack
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/admin/recipes?portion_filter=missing").status_code == 401
        assert client.post("/api/admin/login", json={"username":"TEST_ONLY_admin","password":password}).status_code == 200
        csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]
        rid = client.get("/api/admin/recipes").json()["data"]["items"][0]["recipe_id"]
        row = client.get(f"/api/admin/revisions/{rid}").json()["data"]
        body = {k:row[k] for k in ("title","description","instructions","minutes","role","servings")}
        body["ingredients"] = [{k:line[k] for k in ("ingredient_id","quantity_raw","requirement","amount_kind","amount_min","amount_max","unit_id","ingredient_form","measurement_basis","purpose","scaling_mode")} for line in row["ingredients"]]
        body.update(expected_version=row["edit_version"], portion_data_status="estimated", portion_data_evidence="TEST_ONLY comparison recipe; amount is illustrative only")
        url=f"/api/admin/catalog-recipes/{rid}?revision_id={rid}"
        assert client.patch(url,json=body).status_code == 403
        empty={**body,"portion_data_evidence":""}
        assert client.patch(url,json=empty,headers={"X-CSRF-Token":csrf}).status_code == 422
        saved=client.patch(url,json=body,headers={"X-CSRF-Token":csrf})
        assert saved.status_code == 200, saved.text
        now=client.get(f"/api/admin/revisions/{rid}").json()["data"]
        assert now["portion_data_status"] == "estimated"
        assert now["portion_data_evidence"] == body["portion_data_evidence"]
        assert now["edit_version"] != row["edit_version"]
        assert client.patch(url,json=body,headers={"X-CSRF-Token":csrf}).status_code == 409
        filtered=client.get("/api/admin/recipes?portion_filter=estimated").json()["data"]
        assert rid in [r["recipe_id"] for r in filtered["items"]]
        for mode in ("missing","structured","needs_review","verified"):
            assert client.get("/api/admin/recipes?portion_filter="+mode).status_code == 200
        result=client.post("/api/meal-plan/calculate",json={"recipe_ids":[rid],"people":4})
        assert result.status_code == 200, result.text
        assert result.json()["data"]["recipes"][0]["data_status"] == "estimated"


def test_portion_review_editor_playwright(unified_http_stack):
    from playwright.sync_api import sync_playwright
    import uvicorn
    app, repo, tcp, thread, config, password = unified_http_stack
    port = _port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1",port=port,log_level="error"))
    web_thread = threading.Thread(target=server.run,daemon=True)
    web_thread.start()
    deadline=time.monotonic()+10
    while not server.started and time.monotonic()<deadline:
        time.sleep(0.05)
    assert server.started
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,executable_path=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
            for width in (1280,390):
                page=browser.new_page(viewport={"width":width,"height":900})
                page.goto(f"http://127.0.0.1:{port}/admin/login")
                page.locator('[name=username]').fill("TEST_ONLY_admin")
                page.locator('[name=password]').fill(password)
                page.locator('#admin-login-submit').click()
                page.wait_for_url('**/admin')
                if width < 760:
                    page.locator('#admin-sidebar-toggle').click()
                page.locator('[data-admin-view=recipes]').click()
                page.locator('#admin-recipes [data-edit-legacy], #admin-recipes [data-edit]').first.click()
                page.wait_for_function("document.getElementById('admin-editor').getAttribute('aria-busy')==='false'")
                page.locator('#draft-portion-status').select_option('estimated')
                page.locator('#draft-portion-evidence').fill('TEST_ONLY comparison; estimated quantities need review')
                with page.expect_response(lambda r: '/api/admin/catalog-recipes/' in r.url and r.request.method=='PATCH') as response:
                    page.locator('#draft-save').click()
                assert response.value.status==200,response.value.text()
                page.locator('#admin-editor').wait_for(state='hidden')
                page.locator('#admin-portion-filter').select_option('estimated')
                page.wait_for_timeout(300)
                page.locator('#admin-recipes [data-edit-legacy], #admin-recipes [data-edit]').first.click()
                page.wait_for_function("document.getElementById('admin-editor').getAttribute('aria-busy')==='false'")
                assert page.locator('#draft-portion-status').input_value()=='estimated'
                assert page.locator('#draft-portion-evidence').input_value().startswith('TEST_ONLY comparison')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.close()
            browser.close()
    finally:
        server.should_exit=True
        web_thread.join(timeout=10)


def test_explicit_quantity_transcription_preserves_unknown_basis(unified_http_stack):
    from scripts.normalize_portion_seasoning_basis import parse_explicit_missing_amounts
    app, repo, tcp, thread, config, password = unified_http_stack
    connection=repo.connect()
    try:
        rid,line_no=_sql(connection,"SELECT i.recipe_id,i.line_no FROM recipe_ingredients i JOIN recipes r USING(recipe_id) WHERE r.is_public=1 AND r.deleted_at IS NULL LIMIT 1")[0]
        _sql(connection,"INSERT IGNORE INTO units(code,name,dimension) VALUES('tsp','TEST_ONLY teaspoon','other')")
        _sql(connection,"UPDATE recipe_ingredients SET quantity_text=%s,amount_kind='unknown',amount_min=NULL,amount_max=NULL,unit_id=NULL,measurement_basis='unknown' WHERE recipe_id=%s AND line_no=%s",('1/2 mu\u1ed7ng c\u00e0 ph\u00ea',rid,line_no))
        assert (rid,line_no) in parse_explicit_missing_amounts(connection)
        row=_sql(connection,"SELECT amount_min,amount_max,u.code,measurement_basis FROM recipe_ingredients i JOIN units u USING(unit_id) WHERE recipe_id=%s AND line_no=%s",(rid,line_no))[0]
        assert str(row[0])=='0.500000' and row[0]==row[1] and row[2:] == ('tsp','unknown')
        assert parse_explicit_missing_amounts(connection)==[]
        _sql(connection,"UPDATE recipe_ingredients SET quantity_text=%s,amount_kind='unknown',amount_min=NULL,amount_max=NULL,unit_id=NULL WHERE recipe_id=%s AND line_no=%s",('1 mu\u1ed7ng',rid,line_no))
        assert parse_explicit_missing_amounts(connection)==[]
        connection.rollback()
    finally:
        connection.close()


def test_stage4_custom_assessment_filters_proposal_and_drinks(unified_http_stack):
    from fastapi.testclient import TestClient
    app,repo,tcp,thread,config,password=unified_http_stack
    connection=repo.connect()
    try:
        _sql(connection,"INSERT INTO recipes(recipe_id,title,normalized_title,description,role,minutes_total,instructions_legacy,is_public) VALUES(4,'TEST_ONLY drink','test_only drink','','drink',5,'TEST_ONLY unquantified water',1)")
        _sql(connection,"INSERT INTO recipe_ingredients(recipe_id,line_no,ingredient_id,requirement) VALUES(4,1,2,'required')")
        tag=_sql(connection,"INSERT INTO recipe_tags(tag_type,code,label,normalized_label) VALUES('dish_type','non_alcoholic','TEST_ONLY non alcoholic','test_only non alcoholic')")
        _sql(connection,"INSERT INTO recipe_tag_links(recipe_id,tag_id) VALUES(4,%s)",(tag,))
        connection.commit()
    finally:connection.close()
    with TestClient(app) as client:
        request={"layout_mode":"custom","people":4,"counts":{"main":1,"vegetable":0,"soup":0},"current_plan":{"main:1":1},"locked_slots":["main:1"],"weather":"rain"}
        response=client.post('/api/meal-plan/assess',json={"request":request,"propose":True})
        assert response.status_code==200,response.text
        data=response.json()['data']
        assert data['warnings'] and data['calculation']['totals_complete'] is False
        assert len(data['beverages'])==1 and data['beverages'][0]['amount'] is None
        assert data['proposal']['counts']=={"main":1,"vegetable":1,"soup":1}
        assert data['proposal']['plan']['items'][0]['recipe_id']==1
        assert len(data['selection']['plan']['items'])==1  # proposal is not applied
        assert client.post('/api/meal-plan/assess',json={"request":request,"remove_slot":"main:1"}).status_code==422
        blocked=client.post('/api/meal-plan/assess',json={"request":{**request,"excluded_ids":[1]}})
        assert blocked.status_code==200 and blocked.json()['data']['selection']['plan'] is None
        changed=client.post('/api/meal-plan/assess',json={"request":request,"add_recipe_id":2})
        assert changed.status_code==200,changed.text
        assert len(changed.json()['data']['selection']['plan']['items'])==2
        connection=repo.connect()
        try:assert 4 not in [r['id'] for r in repo.recipes_for_ranking(connection)]
        finally:connection.close()
