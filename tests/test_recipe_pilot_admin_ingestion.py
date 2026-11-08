"""TEST_ONLY Admin HTTP -> TCP -> MySQL checks for the five-recipe pilot boundary.

Uses the private mysqld fixture; the primary project database is never opened.
"""
from __future__ import annotations

import re
import socket
import threading
import time

import mysql.connector
from fastapi.testclient import TestClient

from source.common.catalog_ids import V2_OFFSET
from source.database import migrate_v2, v2_schema, v2_admin_schema
from source.database.migrate_v2 import (
    run_admin_draft_migration,
    run_admin_ingredient_migration,
    run_legacy_recipe_overlay_migration,
    run_legacy_ingredient_admin_migration,
    run_admin_recipe_catalog_migration,
    run_legacy_recipe_catalog_ingredient_migration,
)
from source.server.main import TCPServer
from source.server.repository import MySQLRepository
from source.web.main import app
from tests.mysql_v2_fixtures import mysql_db, private_mysql, sql, legacy_hashes
from tests.test_admin import hash_for


def _seed_legacy_insert_statements(connection):
    """Seed only INSERT statements in the disposable DB; skip USE/DELETE/SET."""
    for table in ("recipe_ingredients", "recipes", "ingredient_aliases", "ingredients", "metadata"):
        sql(connection, f"DELETE FROM {table}")
    root = __import__("pathlib").Path(__file__).resolve().parents[1] / "source" / "database"
    for name in ("mysql_seed.sql", "mysql_expanded_seed.sql"):
        text = (root / name).read_text(encoding="utf-8")
        for part in text.split(";"):
            statement = re.sub(r"(?m)^\s*--.*$", "", part).strip()
            if statement.upper().startswith("INSERT "):
                sql(connection, statement)
    assert sql(connection, "SELECT COUNT(*) AS n FROM recipes")[0]["n"] == 50
    assert sql(connection, "SELECT COUNT(*) AS n FROM ingredients")[0]["n"] == 50
    assert sql(connection, "SELECT COUNT(*) AS n FROM recipe_ingredients")[0]["n"] == 252


def _install_needed_migrations(connection):
    """Apply only already existing migrations needed by this Admin flow; skip 002."""
    sql(connection, migrate_v2.HISTORY_DDL)
    sql(connection,
        f"INSERT INTO {migrate_v2.HISTORY}(version,checksum,execution_result) VALUES(%s,%s,'APPLYING')",
        (v2_schema.VERSION, v2_schema.checksum()))
    for statement in v2_schema.statements():
        sql(connection, statement)
    sql(connection,
        f"UPDATE {migrate_v2.HISTORY} SET execution_result='APPLIED',schema_hash=%s,applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
        (migrate_v2._schema_hash(connection), v2_schema.VERSION))
    run_admin_draft_migration(connection, "apply")
    run_admin_ingredient_migration(connection, "apply")
    run_legacy_recipe_overlay_migration(connection, "apply")
    run_legacy_ingredient_admin_migration(connection, "apply")
    run_admin_recipe_catalog_migration(connection, "apply")
    history = {row["version"] for row in sql(connection, f"SELECT version FROM {migrate_v2.HISTORY}")}
    assert v2_schema.VERSION in history and v2_admin_schema.VERSION in history
    assert "002_context_metadata" not in history


def test_pilot_ingredients_and_recipe_routes_are_truthfully_bounded_to_supported_ids(
    mysql_db, monkeypatch, tmp_path
):
    connection, config = mysql_db
    assert connection.database.startswith("goiy_v2_test_")
    _seed_legacy_insert_statements(connection)
    legacy_before = legacy_hashes(connection)
    _install_needed_migrations(connection)
    assert migrate_v2.check(connection)["legacy_recipe_catalog_ingredient_state"] == "NOT_APPLIED"
    # Existing legacy-only overlay rows survive ALTER unchanged.
    sql(connection, "INSERT INTO v2_admin_legacy_recipe_overrides(recipe_id,title,updated_by,ingredients_overridden) VALUES(8,'TEST_ONLY old overlay','TEST_ONLY',1)")
    sql(connection, "INSERT INTO v2_admin_legacy_recipe_override_ingredients(recipe_id,line_no,ingredient_id,quantity,is_required) VALUES(8,1,3,'1 bunch',1)")
    shared_migration = run_legacy_recipe_catalog_ingredient_migration(connection, "apply")
    assert shared_migration["legacy_recipe_catalog_ingredient_state"] == "APPLIED"
    assert sql(connection, "SELECT recipe_id,line_no,ingredient_id,v2_ingredient_id,quantity,is_required FROM v2_admin_legacy_recipe_override_ingredients WHERE recipe_id=8")[0] == {
        "recipe_id": 8, "line_no": 1, "ingredient_id": 3, "v2_ingredient_id": None,
        "quantity": "1 bunch", "is_required": 1,
    }

    # Fixture the already-existing Admin v2 "trứng kho" row at its stable
    # public ID so this test exercises UPDATE rather than creating a duplicate.
    public_recipe_id = 7980672317
    storage_recipe_id = public_recipe_id - V2_OFFSET
    sql(connection, "INSERT INTO v2_ingredients(id,legacy_ingredient_id,canonical_name,normalized_name) "
                    "VALUES(50001,26,'Mắm ruốc','mắm ruốc')")
    sql(connection, "INSERT INTO v2_recipes(id,origin_kind,author_ref) VALUES(%s,'curated_new','TEST_ONLY existing row')",
        (storage_recipe_id,))
    sql(connection, "INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,description,instructions,minutes,status) "
                    "VALUES(9001,%s,1,'trứng kho','','sơ chế',30,'DRAFT')", (storage_recipe_id,))
    sql(connection, "INSERT INTO v2_recipe_ingredient_lines(revision_id,line_no,ingredient_id,quantity_raw,requirement) "
                    "VALUES(9001,1,50001,NULL,'required')")
    sql(connection, "INSERT INTO v2_admin_recipe_catalog_overrides "
                    "(v2_recipe_id,revision_id,role_code,direct_publication,is_visible,is_deleted,updated_by) "
                    "VALUES(%s,9001,'main',1,1,0,'TEST_ONLY fixture')", (storage_recipe_id,))

    repo = MySQLRepository(config, pool_size=2)
    monkeypatch.setattr(repo, "_admin_writer", lambda: mysql.connector.connect(**{**config, "autocommit": False}))
    monkeypatch.setattr(repo, "admin_ingredient_writer_ready", lambda: True)
    monkeypatch.setattr(repo, "legacy_ingredient_admin_writer_ready", lambda _connection=None: True)
    assert repo.legacy_recipe_shared_ingredient_ready()

    from source.server import main as server_main
    from source.web import main as web_main
    monkeypatch.setattr(server_main, "LOG_PATH", tmp_path / "TEST_ONLY-pilot-tcp.jsonl")
    monkeypatch.setattr(web_main, "_GATEWAY_LOG_PATH", tmp_path / "TEST_ONLY-pilot-http.jsonl")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = TCPServer("127.0.0.1", port, repository=repo)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    monkeypatch.setenv("TCP_HOST", "127.0.0.1")
    monkeypatch.setenv("TCP_PORT", str(port))
    monkeypatch.setenv("ADMIN_USERNAME", "TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "TEST_ONLY recipe pilot session secret")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=.1):
                break
        except OSError:
            time.sleep(.02)
    else:
        raise AssertionError("TEST_ONLY TCP Server did not start")

    try:
        with TestClient(app) as client:
            login = client.post("/api/admin/login", json={"username": "TEST_ONLY_ADMIN", "password": "TEST_ONLY_PASSWORD"})
            assert login.status_code == 200, login.text
            csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]
            headers = {"X-CSRF-Token": csrf}

            # Confirm the existing Hành ID is preserved and add the four
            # requested ingredients using the real Admin create endpoint.
            user_before = client.get("/api/ingredients?limit=50").json()["data"]["items"]
            assert len(user_before) == 50
            assert next(row for row in user_before if row["id"] == 3)["name"] == "Hành"
            new_ids = {}
            for name in ("Dầu ăn", "Muối", "Đường", "Tiêu"):
                created = client.post("/api/admin/ingredients", json={"name": name}, headers=headers)
                assert created.status_code == 200, created.text
                new_ids[name] = created.json()["data"]["ingredient_id"]
                user_rows = client.get(f"/api/ingredients?query={name}&limit=50").json()["data"]["items"]
                admin_rows = client.get(f"/api/admin/ingredients?query={name}&limit=50").json()["data"]["items"]
                assert any(row["id"] == new_ids[name] and row["name"] == name for row in user_rows)
                assert any(row["ingredient_id"] == new_ids[name] and row["name"] == name for row in admin_rows)
            catalog_after = client.get("/api/admin/ingredients?limit=50").json()["data"]
            assert catalog_after["total"] == 54 and len(catalog_after["items"]) == 50

            # Legacy overlays now accept mixed IDs from the shared catalog.
            oil_id = list(new_ids.values())[0]
            legacy_payload = {
                "title": "TEST_ONLY mixed-catalog legacy recipe",
                "description": "TEST_ONLY overlay description",
                "instructions": "1. TEST_ONLY prepare ingredients.\n2. TEST_ONLY cook until done.",
                "minutes": 50,
                "is_visible": True,
                "ingredients": [
                    {"ingredient_id": 13, "quantity": "600 g", "is_required": True},
                    {"ingredient_id": oil_id, "quantity": "15 ml", "is_required": True},
                ],
            }
            legacy_payload["expected_version"] = client.get("/api/admin/legacy-recipes/7").json()["data"]["edit_version"]
            saved_legacy = client.patch("/api/admin/legacy-recipes/7", json=legacy_payload, headers=headers)
            assert saved_legacy.status_code == 200, saved_legacy.text
            legacy_detail = client.get("/api/recipes/7")
            assert legacy_detail.status_code == 200, legacy_detail.text
            detail_data = legacy_detail.json()["data"]
            assert detail_data["title"] == legacy_payload["title"]
            assert detail_data["instructions"] == legacy_payload["instructions"]
            assert {line["id"] for line in detail_data["ingredients"]} == {13, oil_id}
            assert next(line for line in detail_data["ingredients"] if line["id"] == oil_id)["quantity"] == "15 ml"
            stored_lines = sql(connection, "SELECT ingredient_id,v2_ingredient_id,quantity FROM v2_admin_legacy_recipe_override_ingredients WHERE recipe_id=7 ORDER BY line_no")
            assert stored_lines == [
                {"ingredient_id": 13, "v2_ingredient_id": None, "quantity": "600 g"},
                {"ingredient_id": None, "v2_ingredient_id": oil_id - V2_OFFSET, "quantity": "15 ml"},
            ]
            search = client.post("/api/search", json={"query": "TEST_ONLY mixed-catalog legacy recipe"})
            assert search.status_code == 200, search.text
            assert any(item["recipe_id"] == 7 for item in search.json()["data"]["items"])
            recommend = client.post("/api/recommend", json={"ingredient_ids": [oil_id], "top_k": 20})
            assert recommend.status_code == 200, recommend.text
            assert any(item["recipe_id"] == 7 for item in recommend.json()["data"]["items"])
            meal = client.post("/api/meal-plan", json={})
            assert meal.status_code == 200, meal.text
            assert meal.json()["data"]["plan"] is not None

            # An injected child-row failure rolls back both old lines and header.
            before_failure = detail_data
            sql(connection, """CREATE TRIGGER TEST_ONLY_fail_legacy_line BEFORE INSERT
                ON v2_admin_legacy_recipe_override_ingredients FOR EACH ROW
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='TEST_ONLY forced line failure'""")
            latest_version = client.get("/api/admin/legacy-recipes/7").json()["data"]["edit_version"]
            failed_payload = {**legacy_payload, "title": "TEST_ONLY must roll back", "expected_version":latest_version}
            failed_save = client.patch("/api/admin/legacy-recipes/7", json=failed_payload, headers=headers)
            assert failed_save.status_code >= 400
            sql(connection, "DROP TRIGGER TEST_ONLY_fail_legacy_line")
            rollback_detail = client.get("/api/recipes/7").json()["data"]
            assert rollback_detail["title"] == before_failure["title"]
            assert rollback_detail["ingredients"] == before_failure["ingredients"]

            # Delete/restore affects the same legacy identity and public catalog.
            deleted = client.patch("/api/admin/catalog-recipes/7/state",
                                   json={"is_visible": False, "is_deleted": True}, headers=headers)
            assert deleted.status_code == 200, deleted.text
            assert client.get("/api/recipes/7").status_code == 404
            hidden_search = client.post("/api/search", json={"query": "TEST_ONLY mixed-catalog legacy recipe"})
            assert hidden_search.status_code == 200
            assert all(item["recipe_id"] != 7 for item in hidden_search.json()["data"]["items"])
            restored = client.patch("/api/admin/catalog-recipes/7/state",
                                    json={"is_visible": True, "is_deleted": False}, headers=headers)
            assert restored.status_code == 200, restored.text
            assert client.get("/api/recipes/7").status_code == 200

            # The direct v2 recipe path accepts the same shared IDs. Read the
            # existing version and update it through the Admin HTTP endpoint.
            before = client.post("/api/recommend", json={"ingredient_ids": [1, 26], "algorithm": "proposed", "top_k": 20})
            assert before.status_code == 200, before.text
            before_b0 = client.post("/api/recommend", json={"ingredient_ids": [1, 26], "algorithm": "baseline", "top_k": 20})
            assert before_b0.status_code == 200, before_b0.text
            detail = client.get("/api/admin/revisions/9001")
            assert detail.status_code == 200, detail.text
            current = detail.json()["data"]
            steps = "\n".join([
                "Khẩu phần demo: 4 người. Chuẩn bị 15 phút, nấu 25 phút (tổng 40 phút).",
                "1. Luộc 6 trứng 9–10 phút, ngâm nguội rồi bóc vỏ.",
                "2. Hòa 20 g mắm ruốc với 120 ml nước; băm 8 g tỏi, thái 3 g ớt.",
                "3. Phi thơm với 15 ml dầu, cho mắm ruốc và 10 g đường vào.",
                "4. Thêm trứng, kho nhỏ lửa 12–15 phút đến khi sốt bám mặt trứng.",
                "5. Nêm theo vị mắm ruốc, tắt bếp và dùng nóng.",
            ])
            recipe_payload = {
                "title": "Trứng kho mắm ruốc",
                "description": "Trứng kho lửa nhỏ với mắm ruốc, tỏi và ớt; đậm đà, hợp cơm nóng.",
                "instructions": steps,
                "minutes": 40,
                "role": "main",
                "ingredients": [
                    {"ingredient_id": 1, "quantity_raw": "6 quả", "requirement": "required"},
                    {"ingredient_id": 26, "quantity_raw": "20 g", "requirement": "required"},
                    {"ingredient_id": 7, "quantity_raw": "8 g", "requirement": "required"},
                    {"ingredient_id": 23, "quantity_raw": "3 g", "requirement": "required"},
                    {"ingredient_id": new_ids["Đường"], "quantity_raw": "10 g", "requirement": "required"},
                    {"ingredient_id": new_ids["Dầu ăn"], "quantity_raw": "15 ml", "requirement": "required"},
                ],
                "expected_version": current["edit_version"],
            }
            saved = client.patch(f"/api/admin/catalog-recipes/{public_recipe_id}?revision_id=9001",
                                 json=recipe_payload, headers=headers)
            assert saved.status_code == 200, saved.text
            public = client.get(f"/api/recipes/{public_recipe_id}")
            assert public.status_code == 200, public.text
            public_recipe = public.json()["data"]
            assert public_recipe["title"] == recipe_payload["title"]
            assert public_recipe["minutes"] == 40
            assert {row["id"] for row in public_recipe["ingredients"]} >= {
                1, 26, 7, 23, list(new_ids.values())[0], list(new_ids.values())[2]
            }
            assert "Khẩu phần demo: 4 người" in public_recipe["instructions"]
            assert {row["name"] for row in public_recipe["ingredients"]} >= {"Dầu ăn", "Đường"}
            assert sql(connection, "SELECT base_servings FROM v2_recipe_revisions WHERE id=9001")[0]["base_servings"] is None
            after = client.post("/api/recommend", json={"ingredient_ids": [1, 26], "algorithm": "proposed", "top_k": 20})
            assert after.status_code == 200, after.text
            after_b0 = client.post("/api/recommend", json={"ingredient_ids": [1, 26], "algorithm": "baseline", "top_k": 20})
            assert after_b0.status_code == 200, after_b0.text
            score_before = next(item["score"] for item in before.json()["data"]["items"] if item["recipe_id"] == public_recipe_id)
            score_after = next(item["score"] for item in after.json()["data"]["items"] if item["recipe_id"] == public_recipe_id)
            b0_before = next(item["score"] for item in before_b0.json()["data"]["items"] if item["recipe_id"] == public_recipe_id)
            b0_after = next(item["score"] for item in after_b0.json()["data"]["items"] if item["recipe_id"] == public_recipe_id)
            assert score_after < score_before and b0_after > b0_before
            portion = sql(connection, "SELECT base_servings FROM v2_recipe_revisions WHERE id=9001")[0]
            assert portion["base_servings"] is None  # Ordinary Admin save has no structured servings field.

    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert legacy_hashes(connection) == legacy_before
    migration = sql(connection,
        "SELECT checksum,execution_result FROM v2_migration_history WHERE version='010_legacy_recipe_catalog_ingredients'")[0]
    assert migration["checksum"] == migrate_v2.v2_legacy_recipe_catalog_ingredient_schema.checksum()
    assert migration["execution_result"] == "APPLIED"
    assert sql(connection, "SELECT COUNT(*) AS n FROM v2_migration_history WHERE version='002_context_metadata'")[0]["n"] == 0
    final_schema = migrate_v2.check(connection)
    assert final_schema["legacy_recipe_overlay_state"] == "APPLIED"
    assert final_schema["legacy_recipe_catalog_ingredient_state"] == "APPLIED"
    assert final_schema["context_state"] == "NOT_APPLIED"
    assert sql(connection, "SELECT COUNT(*) AS n FROM recipes")[0]["n"] == 50
    assert sql(connection, "SELECT COUNT(*) AS n FROM v2_recipes")[0]["n"] == 1


def test_five_pilot_recipes_round_trip_through_admin_tcp_mysql_and_user(
    mysql_db, monkeypatch, tmp_path
):
    """Import the five reviewed demo profiles only into the private TEST_ONLY DB."""
    from pathlib import Path

    connection, config = mysql_db
    assert connection.database.startswith("goiy_v2_test_")
    fallback_image_catalog = Path(__file__).resolve().parents[1] / "source" / "web" / "static" / "recipe-images.json"
    original_fallback_images = fallback_image_catalog.read_bytes()
    _seed_legacy_insert_statements(connection)
    legacy_before = legacy_hashes(connection)
    _install_needed_migrations(connection)

    # Keep an existing overlay line while applying the already deployed 010
    # migration, so this test also confirms that an old legacy ID remains intact.
    sql(connection, "INSERT INTO v2_admin_legacy_recipe_overrides(recipe_id,title,updated_by,ingredients_overridden) VALUES(8,'TEST_ONLY pre-existing overlay','TEST_ONLY',1)")
    sql(connection, "INSERT INTO v2_admin_legacy_recipe_override_ingredients(recipe_id,line_no,ingredient_id,quantity,is_required) VALUES(8,1,3,'1 bunch',1)")
    run_legacy_recipe_catalog_ingredient_migration(connection, "apply")
    assert sql(connection, "SELECT ingredient_id,v2_ingredient_id,quantity FROM v2_admin_legacy_recipe_override_ingredients WHERE recipe_id=8")[0] == {
        "ingredient_id": 3, "v2_ingredient_id": None, "quantity": "1 bunch"
    }

    # The existing Admin-authored recipe is fixture data in TEST_ONLY. Its
    # stable public ID comes from the pilot dossier; the test updates it rather
    # than creating a second recipe.
    public_v2_recipe_id = 7980672317
    storage_recipe_id = public_v2_recipe_id - V2_OFFSET
    sql(connection, "INSERT INTO v2_ingredients(id,legacy_ingredient_id,canonical_name,normalized_name) VALUES(50001,26,'Mắm ruốc','mắm ruốc')")
    sql(connection, "INSERT INTO v2_recipes(id,origin_kind,author_ref) VALUES(%s,'curated_new','TEST_ONLY existing catalog recipe')", (storage_recipe_id,))
    sql(connection, "INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,description,instructions,minutes,status) VALUES(9001,%s,1,'Trứng kho','','Sơ chế',30,'DRAFT')", (storage_recipe_id,))
    sql(connection, "INSERT INTO v2_recipe_ingredient_lines(revision_id,line_no,ingredient_id,quantity_raw,requirement) VALUES(9001,1,50001,'20 g','required')")
    sql(connection, "INSERT INTO v2_admin_recipe_catalog_overrides(v2_recipe_id,revision_id,role_code,direct_publication,is_visible,is_deleted,updated_by) VALUES(%s,9001,'main',1,1,0,'TEST_ONLY fixture')", (storage_recipe_id,))

    repo = MySQLRepository(config, pool_size=2)
    monkeypatch.setattr(repo, "_admin_writer", lambda: mysql.connector.connect(**{**config, "autocommit": False}))
    monkeypatch.setattr(repo, "admin_ingredient_writer_ready", lambda: True)
    monkeypatch.setattr(repo, "legacy_ingredient_admin_writer_ready", lambda _connection=None: True)
    assert repo.legacy_recipe_shared_ingredient_ready()

    from source.server import main as server_main
    from source.web import main as web_main
    monkeypatch.setattr(server_main, "LOG_PATH", tmp_path / "TEST_ONLY-pilot-five-tcp.jsonl")
    monkeypatch.setattr(web_main, "_GATEWAY_LOG_PATH", tmp_path / "TEST_ONLY-pilot-five-http.jsonl")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = TCPServer("127.0.0.1", port, repository=repo)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    monkeypatch.setenv("TCP_HOST", "127.0.0.1")
    monkeypatch.setenv("TCP_PORT", str(port))
    monkeypatch.setenv("ADMIN_USERNAME", "TEST_ONLY_PILOT_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_for("TEST_ONLY_PILOT_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "TEST_ONLY five-recipe pilot session secret")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    thread.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=.1):
                break
        except OSError:
            time.sleep(.02)
    else:
        raise AssertionError("TEST_ONLY TCP Server did not start")

    try:
        with TestClient(app) as client:
            login = client.post("/api/admin/login", json={"username": "TEST_ONLY_PILOT_ADMIN", "password": "TEST_ONLY_PILOT_PASSWORD"})
            assert login.status_code == 200, login.text
            csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]
            headers = {"X-CSRF-Token": csrf}

            user_catalog = client.get("/api/ingredients?limit=50")
            assert user_catalog.status_code == 200, user_catalog.text
            catalog_rows = user_catalog.json()["data"]["items"]
            assert len(catalog_rows) == 50
            catalog_by_id = {row["id"]: row["name"] for row in catalog_rows}
            assert catalog_by_id[3] == "Hành"
            assert catalog_by_id[26] == "Mắm ruốc"

            # Each missing name is checked first, then added through the Admin
            # HTTP -> TCP -> MySQL operation. Hành tím is a distinct new catalog
            # identity; it is never aliased to or substituted for Hành (ID 3).
            new_names = ("Dầu ăn", "Muối", "Đường", "Tiêu", "Hành tím")
            new_ids = {}
            for name in new_names:
                found = client.get("/api/ingredients", params={"query": name, "limit": 50})
                assert found.status_code == 200, found.text
                exact = [row for row in found.json()["data"]["items"] if row["name"].casefold() == name.casefold()]
                assert exact == [], f"TEST_ONLY seed already contains {name!r}; avoid a duplicate"
                created = client.post("/api/admin/ingredients", json={"name": name}, headers=headers)
                assert created.status_code == 200, created.text
                ingredient_id = created.json()["data"]["ingredient_id"]
                assert ingredient_id > 2**32 - 1 and ingredient_id != 3
                new_ids[name] = ingredient_id
                user_after = client.get("/api/ingredients", params={"query": name, "limit": 50}).json()["data"]["items"]
                admin_after = client.get("/api/admin/ingredients", params={"query": name, "limit": 50}).json()["data"]["items"]
                assert any(row["id"] == ingredient_id and row["name"] == name for row in user_after)
                assert any(row["ingredient_id"] == ingredient_id and row["name"] == name for row in admin_after)
            assert len(set(new_ids.values())) == len(new_names)
            assert new_ids["Hành tím"] != 3

            dossier = Path(__file__).resolve().parents[1] / "docs" / "data-normalization-pilot-5-admin-ready.md"
            text = dossier.read_text(encoding="utf-8")
            headings = list(re.finditer(r"(?m)^## ([1-5])\. (.+?) — (legacy ID|Admin ID hiện tại) (\d+)\s*$", text))
            assert len(headings) == 5, "pilot dossier must contain exactly the five selected recipe identities"
            parsed = []
            role_map = {"Món chính": "main", "Món rau": "vegetable", "Canh": "soup"}
            for index, heading in enumerate(headings):
                section = text[heading.end(): headings[index + 1].start() if index + 1 < len(headings) else len(text)]
                title = heading.group(2).strip()
                kind, recipe_id = heading.group(3), int(heading.group(4))
                description_match = re.search(r"\*\*Mô tả:\*\*\s*(.+?)\s{2,}", section)
                time_match = re.search(r"\*\*Khẩu phần:\*\*\s*(\d+)\.\s*\*\*Chuẩn bị:\*\*\s*(\d+) phút\.\s*\*\*Nấu:\*\*\s*(\d+) phút\.\s*\*\*Tổng nhập Admin:\*\*\s*(\d+) phút\.", section)
                role_match = re.search(r"\*\*Vai trò:\*\*\s*(Món chính|Món rau|Canh)\.", section)
                context_match = re.search(r"\*\*Chế độ:\*\*\s*(.*?)\.\s*\*\*Vùng:\*\*\s*(.*?)\.\s*\*\*Mùa:\*\*\s*(.*?)\.\s*\*\*Dịp:\*\*\s*(.*?)\.\s*$", section, re.S)
                assert description_match and time_match and role_match and context_match, f"metadata parsing failed for {title}"
                servings, prep_minutes, cook_minutes, total_minutes = map(int, time_match.groups())
                assert servings == 4 and prep_minutes + cook_minutes == total_minutes
                table_match = re.search(r"\| Nguyên liệu bắt buộc \|.*?\n\|---.*?\n(.*?)(?=\n\*\*Cách làm\*\*)", section, re.S)
                assert table_match, f"ingredient table missing for {title}"
                lines = []
                water_notes = []
                for row in table_match.group(1).splitlines():
                    if not row.startswith("|"):
                        continue
                    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
                    if len(cells) != 3:
                        continue
                    name, quantity, catalog_note = cells
                    if name == "Nước lọc":
                        # Water remains in the instruction text because the
                        # User ingredient picker intentionally has no water ID.
                        water_notes.append(f"Nước chế biến (không phải dòng catalog): {quantity} nước lọc.")
                        continue
                    id_match = re.search(r"\bID (\d+)\b", catalog_note)
                    if id_match:
                        ingredient_id = int(id_match.group(1))
                        assert ingredient_id in catalog_by_id and catalog_by_id[ingredient_id], (title, name, ingredient_id)
                    else:
                        normalized = "Tiêu" if name == "Tiêu xay" else name
                        ingredient_id = new_ids.get(normalized)
                        assert ingredient_id is not None, f"no separate catalog ID was created for {name}"
                    lines.append({"ingredient_id": ingredient_id, "quantity": quantity, "is_required": True})
                assert len(lines) >= 4
                steps_match = re.search(r"\*\*Cách làm\*\*\s*\n(.*?)(?=\n\*\*(?:Mẹo|Nhận biết hoàn thành|Nguồn tham khảo|Tách phiên bản))", section, re.S)
                assert steps_match, f"instructions missing for {title}"
                steps = steps_match.group(1).strip()
                assert len(re.findall(r"(?m)^\d+\.", steps)) >= 4
                instructions = "\n".join(water_notes + ([""] if water_notes else []) + [steps]).strip()
                parsed.append({"kind": kind, "recipe_id": recipe_id, "title": title,
                    "description": description_match.group(1).strip(), "instructions": instructions,
                    "minutes": total_minutes, "role": role_map[role_match.group(1)],
                    "servings": servings, "prep_minutes": prep_minutes, "cook_minutes": cook_minutes,
                    "context_metadata": {"diet": context_match.group(1).strip(), "region": context_match.group(2).strip(),
                        "season": context_match.group(3).strip(), "occasion": context_match.group(4).strip()},
                    "ingredients": lines})

            # Verify all source ingredient IDs against User's original catalog.
            assert [item["recipe_id"] for item in parsed if item["kind"] == "legacy ID"] == [7, 6, 5, 4]
            assert [item["recipe_id"] for item in parsed if item["kind"] == "Admin ID hiện tại"] == [public_v2_recipe_id]
            for recipe in parsed:
                if recipe["kind"] == "legacy ID":
                    legacy_id = recipe["recipe_id"]
                    before = client.get(f"/api/recipes/{legacy_id}")
                    assert before.status_code == 200, before.text
                    old = before.json()["data"]
                    admin_before=client.get(f"/api/admin/legacy-recipes/{legacy_id}")
                    assert admin_before.status_code==200,admin_before.text
                    saved = client.patch(f"/api/admin/legacy-recipes/{legacy_id}", json={
                        "title": recipe["title"], "description": recipe["description"],
                        "instructions": recipe["instructions"], "minutes": recipe["minutes"],
                        "is_visible": True,"expected_version":admin_before.json()["data"]["edit_version"],
                        "ingredients": recipe["ingredients"]}, headers=headers)
                    assert saved.status_code == 200, saved.text
                    detail = client.get(f"/api/recipes/{legacy_id}")
                    assert detail.status_code == 200, detail.text
                    actual = detail.json()["data"]
                    assert actual["title"] == recipe["title"]
                    assert actual["description"] == recipe["description"]
                    assert actual["instructions"] == recipe["instructions"]
                    assert actual["minutes"] == recipe["minutes"]
                    assert len(actual["ingredients"]) == len(recipe["ingredients"])
                    assert all(row["is_required"] for row in actual["ingredients"])
                    assert {row["id"] for row in actual["ingredients"]} == {line["ingredient_id"] for line in recipe["ingredients"]}
                    admin_detail = client.get(f"/api/admin/legacy-recipes/{legacy_id}")
                    assert admin_detail.status_code == 200, admin_detail.text
                    assert admin_detail.json()["data"]["role"] == recipe["role"]
                else:
                    detail = client.get("/api/admin/revisions/9001")
                    assert detail.status_code == 200, detail.text
                    version = detail.json()["data"]["edit_version"]
                    saved = client.patch(f"/api/admin/catalog-recipes/{public_v2_recipe_id}?revision_id=9001", json={
                        "title": recipe["title"], "description": recipe["description"],
                        "instructions": recipe["instructions"], "minutes": recipe["minutes"],
                        "role": recipe["role"], "ingredients":[
                            {"ingredient_id": line["ingredient_id"], "quantity_raw": line["quantity"], "requirement":"required"}
                            for line in recipe["ingredients"]], "expected_version": version}, headers=headers)
                    assert saved.status_code == 200, saved.text
                    public = client.get(f"/api/recipes/{public_v2_recipe_id}")
                    assert public.status_code == 200, public.text
                    actual = public.json()["data"]
                    assert actual["title"] == recipe["title"]
                    assert actual["description"] == recipe["description"]
                    assert actual["instructions"] == recipe["instructions"]
                    assert actual["minutes"] == recipe["minutes"]
                    assert {row["id"] for row in actual["ingredients"]} == {line["ingredient_id"] for line in recipe["ingredients"]}
                    assert all(row["is_required"] for row in actual["ingredients"])
                    assert sql(connection, "SELECT base_servings FROM v2_recipe_revisions WHERE id=9001")[0]["base_servings"] is None

                # User search/detail, both recommendation algorithms, and both
                # meal-plan APIs see the same saved catalog identity.
                found = client.post("/api/search", json={"query": recipe["title"], "limit": 20})
                assert found.status_code == 200, found.text
                assert any(row["recipe_id"] == recipe["recipe_id"] for row in found.json()["data"]["items"])
                for algorithm in ("baseline", "proposed"):
                    recommendation = client.post("/api/recommend", json={
                        "ingredient_ids": [line["ingredient_id"] for line in recipe["ingredients"]],
                        "algorithm": algorithm, "top_k": 20})
                    assert recommendation.status_code == 200, recommendation.text
                    assert any(row["recipe_id"] == recipe["recipe_id"] for row in recommendation.json()["data"]["items"])

            meal_v1 = client.post("/api/meal-plan", json={})
            assert meal_v1.status_code == 200, meal_v1.text
            assert meal_v1.json()["data"]["plan"] is not None
            meal_v2 = client.post("/api/meal-plan/v2", json={"people": 4})
            assert meal_v2.status_code == 200, meal_v2.text
            assert meal_v2.json()["data"]["plan"] is not None

            admin_ids = []
            for offset in (0, 50):
                admin_list = client.get(f"/api/admin/recipes?limit=50&offset={offset}")
                assert admin_list.status_code == 200, admin_list.text
                admin_ids.extend(row["recipe_id"] for row in admin_list.json()["data"]["items"])
            assert len(admin_ids) == len(set(admin_ids))
            assert all(recipe["recipe_id"] in admin_ids for recipe in parsed)
            ingredient_ids = []
            for offset in (0, 50):
                admin_ingredients = client.get(f"/api/admin/ingredients?limit=50&offset={offset}")
                assert admin_ingredients.status_code == 200, admin_ingredients.text
                assert admin_ingredients.json()["data"]["total"] == 55
                ingredient_ids.extend(row["ingredient_id"] for row in admin_ingredients.json()["data"]["items"])
            assert len(ingredient_ids) == 55 and len(ingredient_ids) == len(set(ingredient_ids))
            assert all(any(row["id"] == new_ids[name] and row["name"] == name
                           for row in client.get("/api/ingredients", params={"query": name, "limit": 50}).json()["data"]["items"])
                       for name in new_names)

            # The structured servings/prep/cook/region/season/occasion fields
            # remain in the dossier only; standard Admin save supports one total
            # minutes field and does not expose those metadata fields.
            assert all((recipe["servings"], recipe["prep_minutes"], recipe["cook_minutes"]) == (4, prep, cook)
                       for recipe, prep, cook in zip(parsed, (20, 15, 10, 15, 15), (30, 40, 10, 20, 25)))
            assert all(all(recipe["context_metadata"].values()) for recipe in parsed)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert legacy_hashes(connection) == legacy_before
    assert sql(connection, "SELECT COUNT(*) AS n FROM recipes")[0]["n"] == 50
    assert sql(connection, "SELECT COUNT(*) AS n FROM ingredients")[0]["n"] == 50
    assert sql(connection, "SELECT COUNT(*) AS n FROM recipe_ingredients")[0]["n"] == 252
    assert sql(connection, "SELECT COUNT(*) AS n FROM v2_recipes")[0]["n"] == 1
    assert sql(connection, "SELECT COUNT(*) AS n FROM v2_ingredient_admin_state WHERE is_active=1")[0]["n"] == 5
    assert sql(connection, "SELECT COUNT(*) AS n FROM v2_admin_legacy_recipe_overrides WHERE recipe_id IN (4,5,6,7)")[0]["n"] == 4
    assert sql(connection, "SELECT COUNT(*) AS n FROM v2_admin_legacy_recipe_override_ingredients WHERE recipe_id IN (4,5,6,7)")[0]["n"] == sum(
        len(recipe["ingredients"]) for recipe in parsed if recipe["kind"] == "legacy ID"
    )
    v2_recipe_storage_id = 7980672317 - V2_OFFSET
    assert sql(connection, "SELECT COUNT(*) AS n FROM v2_recipe_revisions WHERE recipe_id=%s", (v2_recipe_storage_id,))[0]["n"] == 1
    assert sql(connection, "SELECT COUNT(*) AS n FROM v2_recipe_ingredient_lines WHERE revision_id=9001")[0]["n"] == next(
        len(recipe["ingredients"]) for recipe in parsed if recipe["kind"] == "Admin ID hiện tại"
    )
    assert sql(connection, "SELECT COUNT(*) AS n FROM v2_admin_recipe_catalog_overrides WHERE v2_recipe_id=%s", (v2_recipe_storage_id,))[0]["n"] == 1
    assert fallback_image_catalog.read_bytes() == original_fallback_images
