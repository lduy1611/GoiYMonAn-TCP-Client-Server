"""Import the shipped catalog into a private mysqld and exercise the portable stack."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
import uuid

import httpx
import mysql.connector

from tests.mysql_v2_fixtures import private_mysql, sql

ROOT = Path(__file__).resolve().parents[1]


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_public_package_import_and_real_portable_http_tcp_mysql(private_mysql, tmp_path):
    database = "public_demo_" + uuid.uuid4().hex[:12] + "_test"
    admin = mysql.connector.connect(**private_mysql)
    sql(admin, f"CREATE DATABASE `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    connection = mysql.connector.connect(**{**private_mysql, "database": database})
    # No existing database or credentials are read: the fixture owns a new datadir.
    assert not sql(connection, "SHOW TABLES")
    package = ROOT / "data/demo"
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    text = (package / "catalog.sql").read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode()).hexdigest() == manifest["catalog_sha256"]
    for statement in re.sub(r"(?m)^\s*--[^\n]*", "", text).split(";"):
        if statement.strip():
            sql(connection, statement)
    for table, count in manifest["counts"].items():
        assert sql(connection, f"SELECT COUNT(*) n FROM `{table}`")[0]["n"] == count
    for table in ("users", "recipe_edit_history", "achievement_posts", "achievement_images",
                  "achievement_comments", "feedback_submissions", "recipe_id_map", "unified_import_runs"):
        assert sql(connection, f"SELECT COUNT(*) n FROM `{table}`")[0]["n"] == 0
    assert sql(connection, "SELECT COUNT(*) n FROM recipes WHERE role='drink'")[0]["n"] == 10
    assert sql(connection, "SELECT COUNT(*) n FROM recipes WHERE created_by IS NOT NULL OR updated_by IS NOT NULL")[0]["n"] == 0
    for table in ("recipe_images", "recipe_steps", "recipe_ingredients", "recipe_tag_links"):
        assert sql(connection, f"SELECT COUNT(*) n FROM {table} x LEFT JOIN recipes r USING(recipe_id) WHERE r.recipe_id IS NULL")[0]["n"] == 0
    assert sql(connection, "SELECT COUNT(*) n FROM recipe_ingredients x LEFT JOIN ingredients i USING(ingredient_id) WHERE i.ingredient_id IS NULL")[0]["n"] == 0
    assert sql(connection, "SELECT COUNT(*) n FROM recipe_tag_links x LEFT JOIN recipe_tags t USING(tag_id) WHERE t.tag_id IS NULL")[0]["n"] == 0
    image_ids = [row["recipe_id"] for row in sql(connection, "SELECT recipe_id FROM recipe_images ORDER BY recipe_id")]
    fallbacks = sql(connection, "SELECT fallback_image_url FROM recipes WHERE fallback_image_url IS NOT NULL")
    assert len(fallbacks) == 49
    for row in fallbacks:
        path = ROOT / "source/web/static" / row["fallback_image_url"].removeprefix("/static/")
        assert path.is_file()
    connection.close()

    # DML-only account for the running app; DDL/import rights are not inherited.
    username = "demo_" + uuid.uuid4().hex[:12]
    password = secrets.token_urlsafe(32)
    sql(admin, f"CREATE USER '{username}'@'127.0.0.1' IDENTIFIED BY %s", (password,))
    sql(admin, f"GRANT SELECT,INSERT,UPDATE,DELETE ON `{database}`.* TO '{username}'@'127.0.0.1'")
    admin.close()
    web_port, tcp_port = free_port(), free_port()
    while tcp_port == web_port:
        tcp_port = free_port()
    runtime = tmp_path / "public-runtime"
    config = {"UNIFIED_MYSQL_HOST": "127.0.0.1", "UNIFIED_MYSQL_PORT": str(private_mysql["port"]),
              "UNIFIED_MYSQL_USER": username, "UNIFIED_MYSQL_PASSWORD": password,
              "UNIFIED_MYSQL_DATABASE": database, "WEB_PORT": str(web_port), "TCP_PORT": str(tcp_port),
              "ADMIN_USERNAME": "TEST_ONLY_admin", "ADMIN_PASSWORD": secrets.token_urlsafe(24),
              "GOIY_DEMO_RUNTIME_DIR": str(runtime)}
    env_file = tmp_path / "demo.env"
    env_file.write_text("\n".join(f"{k}='{v}'" for k, v in config.items()) + "\n", encoding="utf-8")
    before = env_file.read_bytes()
    child_env = {k: v for k, v in os.environ.items() if not k.startswith(
        ("MYSQL_", "UNIFIED_", "TCP_", "WEB_", "ADMIN_", "USER_", "GOIY_DEMO_"))}
    child_env.update(PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    log = (tmp_path / "portable-stack.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "scripts/run_public_demo.py", "--env-file", str(env_file)],
                               cwd=ROOT, env=child_env, stdout=log, stderr=subprocess.STDOUT,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{web_port}", timeout=15) as client:
            for _ in range(200):
                assert process.poll() is None, "Portable launcher stopped; inspect portable-stack.log"
                try:
                    if client.get("/api/health").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("Portable launcher did not become ready")
            assert client.get("/api/health").json()["data"]["dataset_version"].startswith("unified:")
            assert client.get("/").status_code == 200
            result = client.post("/api/search", json={"query": "ca", "limit": 20})
            assert result.status_code == 200, result.text
            assert result.json()["data"]["total"] > 0
            for recipe_id in image_ids:
                response = client.get(f"/media/recipes/{recipe_id}")
                assert response.status_code == 200, recipe_id
                assert response.headers["content-type"].startswith("image/")
            for row in fallbacks:
                assert client.get(row["fallback_image_url"]).status_code == 200
            for season in ("SPRING", "SUMMER", "AUTUMN", "WINTER"):
                response = client.post("/api/meal-plan/v2", json={"people": 4, "adaptive_daily": True,
                    "season": season, "preferences": {"occasion": "daily"}})
                assert response.status_code == 200, response.text
                meal = response.json()["data"]
                assert meal["plan"] is not None and meal["season"] == season
                assert meal["seasonal_assessment"] is not None
            response = client.post("/api/meal-plan/calculate", json={"recipe_ids": image_ids[:2], "people": 4})
            assert response.status_code == 200, response.text
            response = client.post("/api/admin/login", json={"username": config["ADMIN_USERNAME"], "password": config["ADMIN_PASSWORD"]})
            assert response.status_code == 200
            assert client.get("/api/admin/dashboard").status_code == 200
            assert client.get("/api/admin/recipes", params={"limit": 50}).json()["data"]["total"] == 226
            assert client.get("/api/admin/taxonomies", params={"kind": "dish_type"}).status_code == 200
            drinks = client.get("/api/admin/recipes", params={"role": "drink", "limit": 50})
            assert drinks.status_code == 200 and drinks.json()["data"]["total"] == 10
        assert env_file.read_bytes() == before
        for image in manifest["images"]:
            assert hashlib.sha256((runtime / image["path"]).read_bytes()).hexdigest() == image["sha256"]
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=15)
        log.close()
