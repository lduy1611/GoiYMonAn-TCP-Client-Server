"""HTTP -> real TCP socket -> isolated unified-schema MySQL integration.

All rows and image bytes in this test are synthetic TEST_ONLY data. The test
creates and drops its own *_test schema on the private mysqld fixture.
"""
from __future__ import annotations

import hashlib
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
        calculate = client.post("/api/meal-plan/calculate", json={"recipe_ids": [recipe_id], "people": 4})
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
        updated_calculation = client.post("/api/meal-plan/calculate",json={"recipe_ids":[recipe_id],"people":3}).json()["data"]
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

            page.goto(base + "/", wait_until="domcontentloaded")
            page.locator('[data-user-tab="explore"]').click()
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


def test_meal_plan_v2_does_not_restore_retired_ids_as_catalog_options(unified_http_stack):
    """Saved labels cannot repopulate the live selectable ingredient catalog."""
    import json
    import uvicorn
    from playwright.sync_api import sync_playwright

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
    from playwright.sync_api import sync_playwright

    app, _repo, _tcp, _tcp_thread, config, _password = unified_http_stack
    connection = mysql.connector.connect(**config)
    try:
        unit_id = _sql(connection, "SELECT unit_id FROM units WHERE code='g'")[0][0]
        _sql(connection, "UPDATE ingredients SET name='TEST_ONLY salt',normalized_name='test_only salt' WHERE ingredient_id=1")
        _sql(connection, "UPDATE ingredients SET name='TEST_ONLY vegetable',normalized_name='test_only vegetable' WHERE ingredient_id=2")
        _sql(connection, "UPDATE ingredients SET name='TEST_ONLY meat',normalized_name='test_only meat' WHERE ingredient_id=3")
        _sql(connection, "INSERT INTO ingredients(ingredient_id,name,normalized_name,is_active) VALUES(4,'TEST_ONLY tofu','test_only tofu',1),(5,'TEST_ONLY pepper','test_only pepper',1)")
        _sql(connection, "UPDATE recipes SET servings=4 WHERE recipe_id IN (1,2)")
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
                    if page.locator("[data-meal-slot]").count() == 0:
                        page.locator("#meal-generate").click()
                    page.wait_for_function("document.querySelectorAll('[data-meal-slot]').length===3 && document.getElementById('meal-results').getAttribute('aria-busy')==='false'")
                    assert page.locator('#meal-portions').count() == 0
                    assert page.locator('#meal-shopping-title').inner_text() == 'Danh sách đi chợ'
                    assert page.locator('#meal-copy-list').is_visible()
                    page.locator('[data-meal-type="custom"]').click()
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
                        page.wait_for_function("!document.getElementById('meal-shopping-note').textContent.startsWith('Đang tính lượng')")
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
                        assert "Danh sách giữ cả lượng đã tính và thành phần chưa xác định." in page.locator("#meal-shopping-note").inner_text()
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
        blocked_visible = client.delete(f"/api/admin/catalog-recipes/{recipe_id}/permanent",
                                        headers={"X-CSRF-Token": csrf})
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

        purged_recipe = client.delete(f"/api/admin/catalog-recipes/{recipe_id}/permanent",
                                      headers={"X-CSRF-Token": csrf})
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

        # Legacy identities remain protected even after soft-delete; restore the fixture row afterward.
        legacy_deleted = client.patch("/api/admin/catalog-recipes/1/state", headers={"X-CSRF-Token": csrf},
                                      json={"is_visible": True, "is_deleted": True})
        assert legacy_deleted.status_code == 200
        blocked_legacy = client.delete("/api/admin/catalog-recipes/1/permanent", headers={"X-CSRF-Token": csrf})
        assert blocked_legacy.status_code == 409
        restored = client.patch("/api/admin/catalog-recipes/1/state", headers={"X-CSRF-Token": csrf},
                                json={"is_visible": True, "is_deleted": False})
        assert restored.status_code == 200
