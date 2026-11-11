"""Real connector/pool regression on a PRIVATE MySQL instance, TEST_ONLY parents.

No production connection, migration, approval or release activation is performed.
"""
import json

import mysql.connector
import pytest

from source.client.tcp_client import TCPClient
from source.server.repository import MySQLRepository
import source.server.main as server_main
from tests.meal_plan_fixtures import running_repository
from tests.mysql_v2_fixtures import legacy_hashes, mysql_db, private_mysql
from source.web.main import app
import source.web.main as web_main
from fastapi.testclient import TestClient
from tests.test_admin import hash_for


@pytest.mark.parametrize('explicit_false', [False, True])
def test_pool_configures_actual_sessions_and_calculation_has_no_implicit_transaction(mysql_db, monkeypatch, tmp_path, explicit_false):
    _, config = mysql_db
    runtime_config = {key: value for key, value in config.items() if key != 'autocommit'}
    if explicit_false:
        runtime_config['autocommit'] = False
    original = dict(runtime_config)
    repository = MySQLRepository(runtime_config, pool_size=1)
    assert runtime_config == original  # Caller/.env settings are not edited.
    for _ in range(2):
        connection = repository.connect()
        try:
            cursor = connection.cursor()
            cursor.execute('SELECT @@SESSION.autocommit')
            assert cursor.fetchone()[0] == 1
            cursor.close()
            assert repository.dataset_version(connection) == 'TEST_ONLY_BASE'
            assert repository.recipe_ids_exist(connection, (1, 2))
            assert not connection.in_transaction
            assert not repository.calculation_catalog(connection, (1, 2)).available
            assert not connection.in_transaction
        finally:
            connection.close()
    monkeypatch.setattr(server_main, 'LOG_PATH', tmp_path / 'TEST_ONLY-tcp.jsonl')
    with running_repository(repository) as (_, port):
        client = TCPClient(port=port, persistent=True)
        try:
            for people in (2, 4):
                response = client.request('CALCULATE_MEAL_PLAN', {'recipe_ids': [1, 2], 'people': people})
                assert response['ok'] and response['data']['status'] == 'INCOMPLETE'
                assert response['data']['known_ingredients'] == []
            assert client.request('PING', {})['ok']
        finally:
            client.close()


def test_adapter_keeps_guard_against_rolling_back_a_callers_open_transaction(mysql_db):
    _, config = mysql_db
    repository = MySQLRepository(config, pool_size=1)
    connection = repository.connect()
    try:
        connection.start_transaction()
        repository.dataset_version(connection)
        assert connection.in_transaction
        with pytest.raises(mysql.connector.InternalError, match='idle private connection'):
            repository.calculation_catalog(connection, (1, 2))
        assert connection.in_transaction
    finally:
        connection.rollback()
        connection.close()


def test_admin_draft_create_edit_runs_through_tcp_on_private_test_database(mysql_db, monkeypatch, tmp_path):
    from source.common.admin_tokens import issue
    from source.common.catalog_ids import V2_OFFSET
    from source.database.migrate_v2 import (run, run_admin_draft_migration,
        run_admin_ingredient_migration, run_legacy_recipe_overlay_migration,
        run_legacy_ingredient_admin_migration)

    connection, config = mysql_db
    assert connection.database.startswith("goiy_v2_test_")
    run(connection, "apply")
    run_admin_draft_migration(connection, "apply")
    run_admin_ingredient_migration(connection, "apply")
    run_legacy_recipe_overlay_migration(connection, "apply")
    run_legacy_ingredient_admin_migration(connection, "apply")
    cursor = connection.cursor()
    try:
        # Exercise the real Vietnamese names only inside this isolated TEST_ONLY
        # MySQL database; the primary catalog is never modified by this test.
        cursor.execute("UPDATE ingredients SET name=%s,normalized_name=%s WHERE id=1",
                       ("C\u00e1 basa", "ca basa"))
        cursor.execute("UPDATE ingredients SET name=%s,normalized_name=%s WHERE id=2",
                       ("G\u1eebng", "gung"))
        cursor.execute("INSERT INTO ingredients(id,name,normalized_name) VALUES(3,'TEST_ONLY rollback herb','test_only rollback herb')")
        cursor.execute("INSERT INTO v2_ingredients(id,canonical_name,normalized_name,identity_status) "
                       "VALUES(11,'TEST_ONLY ingredient','test_only ingredient','NEEDS_VERIFICATION')")
    finally:
        cursor.close()
    repo = MySQLRepository(config, pool_size=1)
    repo._admin_writer = lambda: mysql.connector.connect(**{**config, "autocommit": False})
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "TEST_ONLY local tcp admin secret for signing")
    token, _ = issue("TEST_ONLY_ADMIN")
    monkeypatch.setattr(server_main, "LOG_PATH", tmp_path / "TEST_ONLY-admin-draft.jsonl")
    with running_repository(repo) as (_, port):
        client = TCPClient(host="127.0.0.1", port=port, persistent=True)
        try:
            created = client.request("ADMIN_CREATE_DRAFT", {
                "admin_token": token, "title": "TEST_ONLY admin recipe", "description": "TEST_ONLY",
                "instructions": "TEST_ONLY steps", "minutes": 12,
                "ingredients": [
                    {"ingredient_id": V2_OFFSET + 11, "quantity_raw": "TEST_ONLY amount", "requirement": "unknown"},
                    {"ingredient_id": 1, "quantity_raw": "TEST_ONLY legacy catalog amount", "requirement": "unknown"},
                    {"ingredient_id": 2, "quantity_raw": "TEST_ONLY ginger amount", "requirement": "unknown"},
                ],
            })
            assert created["ok"] and created["data"]["status"] == "DRAFT"
            revision_id = created["data"]["revision_id"]
            updated = client.request("ADMIN_UPDATE_DRAFT", {
                "admin_token": token, "revision_id": revision_id, "title": "TEST_ONLY edited recipe",
                "description": "TEST_ONLY edited", "instructions": "TEST_ONLY revised steps", "minutes": 18,
                "ingredients": [
                    {"ingredient_id": V2_OFFSET + 11, "quantity_raw": "TEST_ONLY revised amount", "requirement": "unknown"},
                    {"ingredient_id": 1, "quantity_raw": "TEST_ONLY revised legacy amount", "requirement": "unknown"},
                    {"ingredient_id": 2, "quantity_raw": "TEST_ONLY revised ginger amount", "requirement": "unknown"},
                ],
            })
            assert updated["ok"] and updated["data"]["status"] == "DRAFT"
            reopened = client.request("ADMIN_GET_RECIPE", {"admin_token": token, "revision_id": revision_id})
            assert reopened["ok"]
            assert {line["ingredient_id"] for line in reopened["data"]["ingredients"]} == {1, 2, V2_OFFSET + 11}
            user_catalog = client.request("LIST_INGREDIENTS", {"query": "", "limit": 50})["data"]["items"]
            assert {row["id"]: row["name"] for row in user_catalog}[1] == "C\u00e1 basa"
            assert {row["id"]: row["name"] for row in user_catalog}[2] == "G\u1eebng"
            # Imported NEEDS_VERIFICATION identities may be referenced by an
            # Admin draft, but they stay out of the public ingredient picker.
            assert not any(row["id"] == V2_OFFSET + 11 for row in user_catalog)
            hidden_search = client.request("SEARCH_RECIPES", {"query": "TEST_ONLY admin recipe", "limit": 20})
            assert hidden_search["ok"] and hidden_search["data"]["total"] == 0
            by_legacy_ingredient = client.request("SEARCH_RECIPES", {"ingredient_ids": [1], "limit": 20})
            assert by_legacy_ingredient["ok"]
            assert any(item["recipe_id"] == 1 for item in by_legacy_ingredient["data"]["items"])
            assert all(item["recipe_id"] != V2_OFFSET + 1 for item in by_legacy_ingredient["data"]["items"])
            recommendations = client.request("RECOMMEND", {"ingredient_ids": [1, 2], "top_k": 20})
            assert recommendations["ok"]
            assert {1, 2} <= {item["recipe_id"] for item in recommendations["data"]["items"]}
            assert all(item["recipe_id"] != V2_OFFSET + 1 for item in recommendations["data"]["items"])

            # A SQL failure after the legacy-to-v2 crosswalk insert must roll
            # back both the new draft and that crosswalk in the same transaction.
            cursor = connection.cursor()
            try:
                cursor.execute("""CREATE TRIGGER TEST_ONLY_reject_recipe_line
                    BEFORE INSERT ON v2_recipe_ingredient_lines FOR EACH ROW
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='TEST_ONLY injected line failure'""")
            finally:
                cursor.close()
            failed = client.request("ADMIN_CREATE_DRAFT", {
                "admin_token": token, "title": "TEST_ONLY rollback recipe", "description": "TEST_ONLY",
                "instructions": "TEST_ONLY steps", "minutes": 8,
                "ingredients": [{"ingredient_id": 3, "quantity_raw": "TEST_ONLY", "requirement": "unknown"}],
            })
            assert not failed["ok"]
            cursor = connection.cursor()
            try:
                cursor.execute("DROP TRIGGER TEST_ONLY_reject_recipe_line")
            finally:
                cursor.close()
        finally:
            client.close()
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT title,description,instructions,minutes,status FROM v2_recipe_revisions WHERE id=%s",
                       (revision_id,))
        row = cursor.fetchone()
        assert row == {"title": "TEST_ONLY edited recipe", "description": "TEST_ONLY edited",
                       "instructions": "TEST_ONLY revised steps", "minutes": 18, "status": "DRAFT"}
        cursor.execute("SELECT COUNT(*) AS line_count FROM v2_recipe_ingredient_lines WHERE revision_id=%s", (revision_id,))
        assert cursor.fetchone()["line_count"] == 3
        cursor.execute("SELECT legacy_ingredient_id,identity_status FROM v2_ingredients WHERE legacy_ingredient_id=1")
        assert cursor.fetchone() == {"legacy_ingredient_id": 1, "identity_status": "NEEDS_VERIFICATION"}
        cursor.execute("SELECT legacy_ingredient_id,identity_status FROM v2_ingredients WHERE legacy_ingredient_id=2")
        assert cursor.fetchone() == {"legacy_ingredient_id": 2, "identity_status": "NEEDS_VERIFICATION"}
        cursor.execute("SELECT COUNT(*) AS invalid FROM v2_recipe_ingredient_lines WHERE revision_id=%s AND ingredient_id NOT IN (11,12,13)", (revision_id,))
        assert cursor.fetchone()["invalid"] == 0
        cursor.execute("SELECT COUNT(*) AS count FROM v2_recipes r JOIN v2_recipe_revisions v ON v.recipe_id=r.id WHERE v.title='TEST_ONLY rollback recipe'")
        assert cursor.fetchone()["count"] == 0
        cursor.execute("SELECT COUNT(*) AS count FROM v2_ingredients WHERE legacy_ingredient_id=3")
        assert cursor.fetchone()["count"] == 0
    finally:
        cursor.close()


def test_draft_crosswalk_uses_schema_default_without_extra_status_grant_test_only(mysql_db, monkeypatch, tmp_path):
    """Exercise least-privilege legacy/v2 ingredients over HTTP→TCP→MySQL TEST_ONLY."""
    from source.common.catalog_ids import V2_OFFSET
    from source.database.migrate_v2 import (run, run_admin_draft_migration,
        run_admin_ingredient_migration, run_legacy_recipe_overlay_migration,
        run_legacy_ingredient_admin_migration, run_admin_recipe_catalog_migration)

    connection, config = mysql_db
    assert connection.database.startswith("goiy_v2_test_")
    run(connection, "apply")
    run_admin_draft_migration(connection, "apply")
    run_admin_ingredient_migration(connection, "apply")
    run_legacy_recipe_overlay_migration(connection, "apply")
    run_legacy_ingredient_admin_migration(connection, "apply")
    run_admin_recipe_catalog_migration(connection, "apply")
    writer_user = "TEST_ONLY_draft_writer"
    writer_password = "TEST_ONLY_writer_password_42!"
    principal = f"'{writer_user}'@'127.0.0.1'"
    grants = [
            f"GRANT SELECT (id,name) ON `{connection.database}`.`ingredients` TO {principal}",
        f"GRANT SELECT, INSERT, UPDATE ON `{connection.database}`.`v2_admin_recipe_catalog_overrides` TO {principal}",
        f"GRANT SELECT ON `{connection.database}`.`v2_admin_legacy_ingredient_overrides` TO {principal}",
        f"GRANT SELECT ON `{connection.database}`.`v2_ingredient_admin_state` TO {principal}",
        f"GRANT SELECT ON `{connection.database}`.`v2_ingredients` TO {principal}",
        f"GRANT INSERT (id, legacy_ingredient_id, canonical_name, normalized_name) ON `{connection.database}`.`v2_ingredients` TO {principal}",
        f"GRANT SELECT (id) ON `{connection.database}`.`v2_recipes` TO {principal}",
        f"GRANT INSERT (id, origin_kind, author_ref) ON `{connection.database}`.`v2_recipes` TO {principal}",
        f"GRANT SELECT (id, status, content_review_id, servings_review_id) ON `{connection.database}`.`v2_recipe_revisions` TO {principal}",
        f"GRANT INSERT (id, recipe_id, revision_no, title, description, instructions, minutes) ON `{connection.database}`.`v2_recipe_revisions` TO {principal}",
        f"GRANT UPDATE (title, description, instructions, minutes) ON `{connection.database}`.`v2_recipe_revisions` TO {principal}",
        f"GRANT SELECT (revision_id) ON `{connection.database}`.`v2_release_recipes` TO {principal}",
        f"GRANT SELECT (revision_id, status, quantity_review_id, scaling_review_id) ON `{connection.database}`.`v2_recipe_ingredient_lines` TO {principal}",
        f"GRANT INSERT (revision_id, line_no, ingredient_id, quantity_raw, amount_kind, requirement, purpose, measurement_basis) ON `{connection.database}`.`v2_recipe_ingredient_lines` TO {principal}",
        f"GRANT DELETE ON `{connection.database}`.`v2_recipe_ingredient_lines` TO {principal}",
    ]
    cursor = connection.cursor()
    try:
        cursor.execute(f"CREATE USER {principal} IDENTIFIED BY '{writer_password}'")
        for statement in grants:
            cursor.execute(statement)
        cursor.execute("SHOW GRANTS FOR 'TEST_ONLY_draft_writer'@'127.0.0.1'")
        actual_grants = [str(row[0]) for row in cursor.fetchall()]
        assert not any("INSERT (identity_status)" in grant for grant in actual_grants)
        cursor.execute("INSERT INTO v2_ingredients(id,canonical_name,normalized_name,identity_status) "
                       "VALUES(11,'TEST_ONLY v2 ingredient','test_only v2 ingredient','NEEDS_VERIFICATION')")
    finally:
        cursor.close()


    repo = MySQLRepository(config, pool_size=1)
    monkeypatch.setenv("MYSQL_DRAFT_WRITER_USER", writer_user)
    monkeypatch.setenv("MYSQL_DRAFT_WRITER_PASSWORD", writer_password)
    monkeypatch.setenv("ADMIN_USERNAME", "TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "TEST_ONLY HTTP TCP MySQL session secret")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    monkeypatch.setattr(server_main, "LOG_PATH", tmp_path / "TEST_ONLY-crosswalk-grant.jsonl")

    payload = {"title": "TEST_ONLY grant-gap draft", "description": "TEST_ONLY",
               "instructions": "TEST_ONLY steps", "minutes": 12,
               "ingredients": [{"ingredient_id": 1, "quantity_raw": "TEST_ONLY legacy", "requirement": "unknown"},
                               {"ingredient_id": V2_OFFSET + 11, "quantity_raw": "TEST_ONLY v2", "requirement": "unknown"}]}
    with running_repository(repo) as (_, port):
        monkeypatch.setenv("TCP_HOST", "127.0.0.1")
        monkeypatch.setenv("TCP_PORT", str(port))
        with TestClient(app) as client:
            assert client.post("/api/admin/login", json={"username": "TEST_ONLY_ADMIN", "password": "TEST_ONLY_PASSWORD"}).status_code == 200
            csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]
            from source.web.setup_admin import validate_writer_grants
            validate_writer_grants(actual_grants, draft_only=True, database=connection.database)
            assert repo.admin_draft_writer_ready() is True
            saved = client.post("/api/admin/revisions", json=payload, headers={"X-CSRF-Token": csrf})
            assert saved.status_code == 200, saved.json()
            revision_id = saved.json()["data"]["revision_id"]
            reopened = client.get(f"/api/admin/revisions/{revision_id}")
            assert reopened.status_code == 200
            assert reopened.json()["data"]["title"] == payload["title"]
            assert {line["ingredient_id"] for line in reopened.json()["data"]["ingredients"]} == {1, V2_OFFSET + 11}
            public_search = client.post("/api/search", json={"query": "TEST_ONLY grant-gap draft"})
            assert public_search.status_code == 200
            assert payload["title"] not in str(public_search.json())

    cursor = connection.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM v2_ingredients WHERE legacy_ingredient_id=1")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT COUNT(*) FROM v2_recipe_revisions WHERE title=%s AND status='DRAFT'", (payload["title"],))
        assert cursor.fetchone()[0] == 1
    finally:
        cursor.close()
def test_admin_catalog_recipe_save_edit_hide_soft_delete_restore_test_only(mysql_db, monkeypatch, tmp_path):
    """Full Admin → FastAPI → TCP → private MySQL → public catalog lifecycle."""
    from source.common.catalog_ids import V2_OFFSET
    from source.database.migrate_v2 import (run, run_admin_draft_migration,
        run_admin_ingredient_migration, run_legacy_recipe_overlay_migration,
        run_legacy_ingredient_admin_migration, run_admin_recipe_catalog_migration)

    connection, config = mysql_db
    assert connection.database.startswith("goiy_v2_test_")
    legacy_before=legacy_hashes(connection)
    run(connection, "apply")
    run_admin_draft_migration(connection, "apply")
    run_admin_ingredient_migration(connection, "apply")
    run_legacy_recipe_overlay_migration(connection, "apply")
    run_legacy_ingredient_admin_migration(connection, "apply")
    run_admin_recipe_catalog_migration(connection, "apply")
    from source.server.mysql_calculation_catalog import _query
    from source.database.v2_schema import history_is_compatible
    history=_query(connection,"SELECT version,checksum,execution_result,applied_at FROM v2_migration_history")
    assert history_is_compatible(history),history
    cursor = connection.cursor()
    try:
        cursor.execute("INSERT INTO v2_ingredients(id,canonical_name,normalized_name,identity_status) "
                       "VALUES(11,'TEST_ONLY catalog herb','test_only catalog herb','NEEDS_VERIFICATION')")
        cursor.execute("INSERT INTO v2_recipes(id,origin_kind,author_ref) VALUES(99,'curated_new','TEST_ONLY legacy review')")
        cursor.execute("INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,description,instructions,minutes,status) "
                       "VALUES(199,99,1,'TEST_ONLY old unverified','TEST_ONLY','TEST_ONLY',15,'NEEDS_VERIFICATION')")
        cursor.execute("INSERT INTO v2_recipe_ingredient_lines(revision_id,line_no,ingredient_id,quantity_raw,requirement) "
                       "VALUES(199,1,11,'TEST_ONLY','required')")
    finally:
        cursor.close()


    repo = MySQLRepository(config, pool_size=1)
    # This repository connects only to the private mysql_db fixture.
    repo._admin_writer = lambda: mysql.connector.connect(**{**config, "autocommit": False})
    repo.admin_recipe_catalog_ready = lambda: True
    repo.admin_draft_writer_ready = lambda: True
    monkeypatch.setenv("ADMIN_USERNAME", "TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "TEST_ONLY direct recipe session secret")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    monkeypatch.setattr(server_main, "LOG_PATH", tmp_path / "TEST_ONLY-direct-recipe.jsonl")

    with running_repository(repo) as (_, port):
        monkeypatch.setenv("TCP_HOST", "127.0.0.1")
        monkeypatch.setenv("TCP_PORT", str(port))
        with TestClient(app) as client:
            assert client.post("/api/admin/login", json={"username":"TEST_ONLY_ADMIN","password":"TEST_ONLY_PASSWORD"}).status_code == 200
            csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]
            headers = {"X-CSRF-Token":csrf}
            payload = {"title":"TEST_ONLY fish stew","description":"TEST_ONLY description",
                "instructions":"TEST_ONLY steps","minutes":20,"role":"main",
                "idempotency_key":"456789ab-cdef-4123-8456-789abcdef012",
                "ingredients":[{"ingredient_id":1,"quantity_raw":"TEST_ONLY one","requirement":"optional"},
                               {"ingredient_id":V2_OFFSET+11,"quantity_raw":None}]}
            denied = client.post("/api/admin/catalog-recipes", json=payload)
            assert denied.status_code == 403 and denied.json()["error"]["code"] == "ADMIN_CSRF"
            saved = client.post("/api/admin/catalog-recipes", json=payload, headers=headers)
            assert saved.status_code == 200, saved.json().get("error")
            recipe_id = saved.json()["data"]["recipe_id"]
            revision_id = saved.json()["data"]["revision_id"]
            replay = client.post("/api/admin/catalog-recipes", json=payload, headers=headers)
            assert replay.status_code == 200 and replay.json()["data"]["recipe_id"] == recipe_id
            admin_list=client.get("/api/admin/recipes?query=TEST_ONLY%20fish%20stew")
            assert admin_list.status_code==200 and admin_list.json()["data"]["total"]==1
            cursor=connection.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM v2_recipes r JOIN v2_recipe_revisions v ON v.recipe_id=r.id WHERE v.title=%s",(payload["title"],))
                assert cursor.fetchone()[0]==1
            finally:cursor.close()
            check_connection=repo.connect()
            try:
                from source.server.mysql_recipe_catalog import load_catalog
                catalog=load_catalog(check_connection)
                assert recipe_id in catalog.details, (catalog.details,catalog.hidden_ids,catalog.deleted_ids)
                assert V2_OFFSET+99 not in catalog.details
            finally:check_connection.close()

            public_search = client.post("/api/search", json={"query":"TEST_ONLY fish stew"})
            assert public_search.status_code == 200
            assert any(item["recipe_id"] == recipe_id for item in public_search.json()["data"]["items"]), public_search.json()
            detail = client.get(f"/api/recipes/{recipe_id}")
            assert detail.status_code == 200 and detail.json()["data"]["title"] == payload["title"]
            assert {line["id"] for line in detail.json()["data"]["ingredients"]} == {1,V2_OFFSET+11}
            assert all(line["is_required"] is True for line in detail.json()["data"]["ingredients"])
            assert {line["quantity"] for line in detail.json()["data"]["ingredients"]} == {"TEST_ONLY one", None}
            recommendation = client.post("/api/recommend", json={"ingredient_ids":[1],"top_k":20})
            assert recommendation.status_code == 200
            recommended=next(item for item in recommendation.json()["data"]["items"] if item["recipe_id"]==recipe_id)
            assert recommended["matched_ids"]==[1] and recommended["missing_ids"]==[V2_OFFSET+11]
            v2_plan = client.post("/api/meal-plan/v2", json={"counts":{"main":1,"vegetable":0,"soup":0},"ingredient_ids":[1]})
            assert v2_plan.status_code == 200 and v2_plan.json()["ok"] is True
            # Meal planning is allowed to choose any valid candidate for the
            # requested role; it must not depend on this TEST_ONLY recipe
            # winning a tie against the legacy catalog.
            if v2_plan.json()["data"]["plan"]:
                for item in v2_plan.json()["data"]["plan"]["items"]:
                    assert client.get(f"/api/recipes/{item['recipe_id']}").status_code == 200
            legacy_plan = client.post("/api/meal-plan", json={})
            assert legacy_plan.status_code == 200 and legacy_plan.json()["ok"] is True

            opened=client.get(f"/api/admin/revisions/{revision_id}").json()["data"]
            assert len(opened["edit_version"])==64
            ingredient_only={"title":payload["title"],"description":payload["description"],
                "instructions":payload["instructions"],"minutes":payload["minutes"],"role":payload["role"],
                "ingredients":[{"ingredient_id":1,"quantity_raw":"TEST_ONLY ingredient-only change"},
                                {"ingredient_id":V2_OFFSET+11,"quantity_raw":None}],
                "expected_version":opened["edit_version"]}
            ingredient_update=client.patch(f"/api/admin/catalog-recipes/{recipe_id}?revision_id={revision_id}",
                                           json=ingredient_only,headers=headers)
            assert ingredient_update.status_code==200,ingredient_update.json()
            after_ingredient=client.get(f"/api/admin/revisions/{revision_id}").json()["data"]
            assert after_ingredient["edit_version"]!=opened["edit_version"]
            unchanged_fields=client.get(f"/api/recipes/{recipe_id}").json()["data"]
            assert unchanged_fields["title"]==payload["title"]
            assert unchanged_fields["ingredients"][0]["quantity"]=="TEST_ONLY ingredient-only change"
            stale={**ingredient_only,"title":"TEST_ONLY stale overwrite","expected_version":opened["edit_version"]}
            stale_response=client.patch(f"/api/admin/catalog-recipes/{recipe_id}?revision_id={revision_id}",
                                        json=stale,headers=headers)
            assert stale_response.status_code==409 and stale_response.json()["error"]["code"]=="ADMIN_RECIPE_CONFLICT"
            assert client.get(f"/api/recipes/{recipe_id}").json()["data"]["title"]==payload["title"]
            tcp_events=[json.loads(line) for line in (tmp_path/"TEST_ONLY-direct-recipe.jsonl").read_text(encoding="utf-8").splitlines()]
            stale_id=stale_response.headers["x-request-id"]
            stale_event=next(event for event in tcp_events if event.get("request_id")==stale_id and event.get("outcome")=="error")
            sent_event=next(event for event in tcp_events if event.get("request_id")==stale_id and event.get("outcome")=="error_response_sent")
            assert stale_event["diagnostic_code"]=="stale_version" and stale_event["mysql_errno"] is None
            assert sent_event["bytes_out"]>0

            edited = {**payload,"title":"TEST_ONLY fish stew edited","description":"TEST_ONLY changed",
                      "instructions":"TEST_ONLY changed steps","minutes":24,
                      "ingredients":[{"ingredient_id":1,"quantity_raw":"TEST_ONLY changed legacy amount"},
                                     {"ingredient_id":V2_OFFSET+11,"quantity_raw":"TEST_ONLY changed amount"}]}
            edited.pop("idempotency_key")
            edited["expected_version"]=after_ingredient["edit_version"]
            update = client.patch(f"/api/admin/catalog-recipes/{recipe_id}?revision_id={revision_id}",json=edited,headers=headers)
            assert update.status_code == 200, update.json()
            updated_detail=client.get(f"/api/recipes/{recipe_id}").json()["data"]
            assert updated_detail["title"] == edited["title"]
            assert all(line["is_required"] is True for line in updated_detail["ingredients"])
            assert {line["quantity"] for line in updated_detail["ingredients"]} == {
                "TEST_ONLY changed legacy amount", "TEST_ONLY changed amount"}
            assert client.post("/api/search",json={"query":"TEST_ONLY fish stew edited"}).json()["data"]["total"] == 1
            edited_recommend=client.post("/api/recommend",json={"ingredient_ids":[1],"top_k":20}).json()["data"]["items"]
            assert any(item["recipe_id"]==recipe_id for item in edited_recommend)
            edited_plan=client.post("/api/meal-plan/v2",json={"counts":{"main":1,"vegetable":0,"soup":0},
                "ingredient_ids":[1]}).json()["data"]["plan"]
            assert edited_plan is not None
            for item in edited_plan["items"]:
                assert client.get(f"/api/recipes/{item['recipe_id']}").status_code==200

            state_url=f"/api/admin/catalog-recipes/{recipe_id}/state"
            hidden=client.patch(state_url,json={"is_visible":False,"is_deleted":False},headers=headers)
            assert hidden.status_code == 200,hidden.json()
            assert client.get(f"/api/recipes/{recipe_id}").status_code == 404
            assert client.post("/api/search",json={"query":"TEST_ONLY fish stew edited"}).json()["data"]["total"] == 0
            assert all(item["recipe_id"]!=recipe_id for item in client.post("/api/recommend",json={"ingredient_ids":[1]}).json()["data"]["items"])
            hidden_catalog=repo.request_view(connection,"GENERATE_MEAL_PLAN_V2")
            assert all(item["id"]!=recipe_id for item in hidden_catalog.recipes_for_ranking(connection))
            hidden_plan=client.post("/api/meal-plan/v2",json={"counts":{"main":1,"vegetable":0,"soup":0}}).json()["data"]
            assert hidden_plan["plan"] is None or all(item["recipe_id"]!=recipe_id for item in hidden_plan["plan"]["items"])

            assert client.patch(state_url,json={"is_visible":True,"is_deleted":False},headers=headers).status_code == 200
            assert client.get(f"/api/recipes/{recipe_id}").status_code == 200
            assert client.patch(state_url,json={"is_visible":True,"is_deleted":True},headers=headers).status_code == 200
            assert client.get(f"/api/recipes/{recipe_id}").status_code == 404
            assert client.get("/api/admin/recipes?query=TEST_ONLY%20fish%20stew%20edited").json()["data"]["total"] == 0
            deleted=client.get("/api/admin/recipes?query=TEST_ONLY%20fish%20stew%20edited&visibility=deleted")
            assert deleted.status_code == 200 and deleted.json()["data"]["total"] == 1
            restored=client.patch(state_url,json={"is_visible":True,"is_deleted":False},headers=headers)
            assert restored.status_code == 200 and client.get(f"/api/recipes/{recipe_id}").status_code == 200

            # The same soft-delete lifecycle applies to legacy IDs, without
            # mutating the legacy recipe row or its ingredient relations.
            legacy_state_url="/api/admin/catalog-recipes/1/state"
            legacy_deleted=client.patch(legacy_state_url,json={"is_visible":True,"is_deleted":True},headers=headers)
            assert legacy_deleted.status_code==200,legacy_deleted.json()
            assert client.get("/api/recipes/1").status_code==404
            assert client.post("/api/search",json={"query":"TEST_ONLY recipe 1"}).json()["data"]["total"]==0
            assert all(item["recipe_id"]!=1 for item in client.post(
                "/api/recommend",json={"ingredient_ids":[1],"top_k":20}).json()["data"]["items"])
            deleted_catalog=repo.request_view(connection,"GENERATE_MEAL_PLAN")
            assert all(item["id"]!=1 for item in deleted_catalog.recipes_for_ranking(connection))
            legacy_plan=client.post("/api/meal-plan",json={}).json()["data"]["plan"]
            assert legacy_plan is None or all(item["recipe_id"]!=1 for item in legacy_plan["items"])
            assert client.get("/api/admin/recipes?query=TEST_ONLY%20recipe%201").json()["data"]["total"]==0
            legacy_deleted_list=client.get(
                "/api/admin/recipes?query=TEST_ONLY%20recipe%201&visibility=deleted")
            assert legacy_deleted_list.status_code==200 and legacy_deleted_list.json()["data"]["total"]==1
            legacy_restored=client.patch(legacy_state_url,json={"is_visible":True,"is_deleted":False},headers=headers)
            assert legacy_restored.status_code==200 and client.get("/api/recipes/1").status_code==200
            assert client.post("/api/search",json={"query":"TEST_ONLY recipe 1"}).json()["data"]["total"]==1

            cursor=connection.cursor()
            try:
                cursor.execute("CREATE TRIGGER TEST_ONLY_reject_catalog_line BEFORE INSERT ON v2_recipe_ingredient_lines "
                               "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='TEST_ONLY rollback'")
            finally:cursor.close()
            failed=client.post("/api/admin/catalog-recipes",json={**payload,"title":"TEST_ONLY rollback dish",
                "idempotency_key":"abcdefab-cdef-4123-8456-789abcdef012"},headers=headers)
            assert failed.status_code >= 400
            cursor=connection.cursor()
            try:cursor.execute("DROP TRIGGER TEST_ONLY_reject_catalog_line")
            finally:cursor.close()

    cursor=connection.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM v2_recipe_revisions WHERE title='TEST_ONLY rollback dish'")
        assert cursor.fetchone()[0]==0
        cursor.execute("SELECT COUNT(*) FROM v2_admin_recipe_catalog_overrides WHERE v2_recipe_id=%s AND is_visible=1 AND is_deleted=0",(recipe_id-V2_OFFSET,))
        assert cursor.fetchone()[0]==1
    finally:cursor.close()
    assert legacy_hashes(connection)==legacy_before


def test_admin_legacy_recipe_edit_http_tcp_mysql_test_only(mysql_db, monkeypatch, tmp_path):
    """Trace a real legacy overlay edit through authenticated HTTP and framed TCP."""
    from source.database.migrate_v2 import run, run_legacy_recipe_overlay_migration

    connection, config = mysql_db
    assert connection.database.startswith("goiy_v2_test_")
    run(connection, "apply")
    run_legacy_recipe_overlay_migration(connection, "apply")
    baseline = legacy_hashes(connection)
    repo = MySQLRepository(config, pool_size=1)
    repo._admin_writer = lambda: mysql.connector.connect(**{**config, "autocommit": False})
    monkeypatch.setenv("ADMIN_USERNAME", "TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "TEST_ONLY admin edit session secret")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    log_path = tmp_path / "TEST_ONLY-http-tcp-legacy-edit.jsonl"
    monkeypatch.setattr(server_main, "LOG_PATH", log_path)
    gateway_log = tmp_path / "TEST_ONLY-http-tcp-legacy-edit-web.jsonl"
    monkeypatch.setattr(web_main, "_GATEWAY_LOG_PATH", gateway_log)

    with running_repository(repo) as (_, port):
        monkeypatch.setenv("TCP_HOST", "127.0.0.1")
        monkeypatch.setenv("TCP_PORT", str(port))
        with TestClient(app) as client:
            login = client.post("/api/admin/login", json={"username": "TEST_ONLY_ADMIN", "password": "TEST_ONLY_PASSWORD"})
            assert login.status_code == 200
            csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]
            current=client.get("/api/admin/legacy-recipes/1")
            assert current.status_code==200
            body = {
                "title": "TEST_ONLY legacy edit via gateway",
                "description": "TEST_ONLY edit description",
                "instructions": "TEST_ONLY changed cooking steps",
                "minutes": 23,
                "is_visible": True,
                "expected_version":current.json()["data"]["edit_version"],
                "ingredients": [{"ingredient_id": 2, "quantity": "TEST_ONLY 2 units", "is_required": True}],
            }
            response = client.patch("/api/admin/legacy-recipes/1", json=body, headers={"X-CSRF-Token": csrf})
            assert response.status_code == 200, response.json()
            request_id = response.headers["x-request-id"]
            public = client.get("/api/recipes/1")
            assert public.status_code == 200
            assert public.json()["data"]["title"] == body["title"]
            assert public.json()["data"]["instructions"] == body["instructions"]
            assert public.json()["data"]["minutes"] == body["minutes"]
            assert public.json()["data"]["ingredients"][0]["id"] == 2
            assert legacy_hashes(connection) == baseline

    events = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    edit_event = next(event for event in events if event.get("request_id") == request_id)
    assert edit_event["op"] == "ADMIN_UPDATE_LEGACY_RECIPE"
    assert edit_event["outcome"] == "ok"
    assert edit_event["receive_ms"] >= 0
    assert edit_event["dispatch_ms"] >= 0
    assert edit_event["send_ms"] >= 0
    gateway_events = [json.loads(line) for line in gateway_log.read_text(encoding="utf-8").splitlines()]
    gateway_event = next(event for event in gateway_events
                         if event.get("request_id") == request_id and event.get("layer") == "tcp_client")
    assert gateway_event["op"] == "ADMIN_UPDATE_LEGACY_RECIPE"
    assert gateway_event["outcome"] == "response" and gateway_event["elapsed_ms"] >= 0



def test_admin_catalog_schema_hash_is_stable_after_recipe_insert(mysql_db):
    """AUTO_INCREMENT growth is data state, not catalog schema drift."""
    from tests.mysql_v2_fixtures import sql
    from source.database import migrate_v2, v2_admin_recipe_catalog_schema as catalog_schema
    from source.database.migrate_v2 import (run, run_admin_draft_migration,
        run_admin_ingredient_migration, run_legacy_recipe_overlay_migration,
        run_legacy_ingredient_admin_migration, run_admin_recipe_catalog_migration)

    connection, _ = mysql_db
    sql(connection, f"ALTER DATABASE `{connection.database}` COLLATE utf8mb4_0900_ai_ci")
    run(connection, "apply")
    run_admin_draft_migration(connection, "apply")
    run_admin_ingredient_migration(connection, "apply")
    run_legacy_recipe_overlay_migration(connection, "apply")
    run_legacy_ingredient_admin_migration(connection, "apply")
    run_admin_recipe_catalog_migration(connection, "apply")
    marker=sql(connection,"SELECT schema_hash FROM v2_migration_history WHERE version=%s",
                (catalog_schema.VERSION,))[0]["schema_hash"]
    assert catalog_schema.schema_hash(connection)==marker
    sql(connection,"INSERT INTO v2_recipes(id,origin_kind,author_ref) VALUES(77,'curated_new','TEST_ONLY schema hash')")
    sql(connection,"INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,instructions,minutes) "
        "VALUES(770,77,1,'TEST_ONLY schema hash','TEST_ONLY',10)")
    sql(connection,"INSERT INTO v2_admin_recipe_catalog_overrides "
        "(v2_recipe_id,revision_id,role_code,direct_publication,updated_by) "
        "VALUES(77,770,'main',1,'TEST_ONLY')")
    assert catalog_schema.schema_hash(connection)==marker
    state=migrate_v2.check(connection)
    assert state["admin_recipe_catalog_state"]=="APPLIED"

