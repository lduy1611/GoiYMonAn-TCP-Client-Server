"""Run the verified unified-v3 quality_final database in an isolated local stack.

Start with ``.venv\\Scripts\\python.exe scripts\\run_v3_quality_test.py``.
Press Ctrl+C in that terminal to stop the owned API/TCP/MySQL processes.
No production connection is configured or attempted.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

import mysql.connector
import uvicorn
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATABASE = "goiy_v3_quality_final_20261110_test"
BASELINE_DATABASE = "goiy_v3_quality_baseline_20261110_test"
MYSQL_PORT = 63900
FASTAPI_PORT = int(os.getenv("GOIY_QUALITY_FASTAPI_PORT", "8010"))
TCP_PORT = int(os.getenv("GOIY_QUALITY_TCP_PORT", "9010"))
if not 1 <= FASTAPI_PORT <= 65535 or not 1 <= TCP_PORT <= 65535 or FASTAPI_PORT == TCP_PORT:
    raise RuntimeError("TEST_ONLY FastAPI/TCP ports must be distinct valid TCP ports")
DATADIR = ROOT / "statics/runtime/mysql-v3-quality-final-20261110"
MYSQLD = Path(r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe")
IMAGE_ROOT = ROOT / "statics/runtime/recipe-images"
RUNTIME = ROOT / "statics/runtime/quality-v3-test"
SNAPSHOT = ROOT / "statics/runtime/backups/goiy_v3_quality_final_20261110_test-repair-snapshot-20261110.json"
SNAPSHOT_SHA256 = "F91F6BA7B5263B902580BAD517D824F36C930676DE1030EA0F14F569B098B6B7"

EXPECTED_MAP = {
    8517681007: 8517680860, 8517681011: 30, 8517681012: 10,
    8517681013: 8517680877, 8517681014: 23, 8517681015: 7,
    8517681016: 8517680934, 8517681017: 8517680879, 8517681018: 24,
    8517681019: 6401932070, 8517681020: 8517680870,
    8517681021: 6351803760, 8517681022: 8026383130,
    8517681023: 7160223533, 8517681024: 8517680895,
    8517681025: 35, 8517681026: 8517680960,
    8517681027: 8517680883, 8517681028: 1, 8517681029: 8517680857,
    8517681030: 34, 8517681031: 8517680859,
    8517681032: 8517680856, 8517681033: 7626328944,
    8517681035: 8517680868, 8517681036: 8517680913,
}
TEST_RECIPE_ID = 7980672321


def port_available(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def connect(database: str | None = None):
    return mysql.connector.connect(
        host="127.0.0.1", port=MYSQL_PORT, user="root", password="",
        database=database, charset="utf8mb4", connection_timeout=3,
    )


def wait_for_mysql(process: subprocess.Popen | None) -> None:
    for _ in range(120):
        if process is not None and process.poll() is not None:
            raise RuntimeError("Isolated MySQL exited during startup; inspect its private error log")
        try:
            connection = connect()
            connection.close()
            return
        except mysql.connector.Error:
            time.sleep(0.25)
    raise RuntimeError("Isolated MySQL did not become ready on 127.0.0.1:63900")


def db_preflight() -> dict:
    if not SNAPSHOT.is_file() or hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest().upper() != SNAPSHOT_SHA256:
        raise RuntimeError("Verified repair snapshot is missing or its SHA-256 changed")
    manifest = json.loads(SNAPSHOT.read_text(encoding="utf-8-sig"))
    if manifest.get("database") != DATABASE or manifest.get("TEST_ONLY") is not True:
        raise RuntimeError("Repair manifest does not identify this TEST_ONLY database")
    mapping = {int(old): int(new) for old, new in manifest["mapping"].items()}
    quantity_repairs = {tuple(map(int, key.split(":"))): value
                        for key, value in manifest["quantity_repair"].items()}
    planned_names = {int(i): name for i, name in manifest["planned_names"].items()}
    moved_rows = [row for row in manifest["recipe_lines"] if int(row["ingredient_id"]) in mapping]
    if (mapping != EXPECTED_MAP or len(mapping) != 26 or len(quantity_repairs) != 37
            or len(planned_names) != 29 or len(moved_rows) != 40):
        raise RuntimeError("Repair manifest differs from the verified mapping/line change set")
    connection = connect(DATABASE)
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT DATABASE() AS db,@@port AS port,@@datadir AS datadir,CURRENT_USER() AS principal")
        identity = cursor.fetchone()
        if (identity["db"] != DATABASE or int(identity["port"]) != MYSQL_PORT
                or Path(identity["datadir"]).resolve() != DATADIR.resolve()
                or not str(identity["principal"]).startswith("root@127.0.0.1")):
            raise RuntimeError("Connected MySQL identity differs from the isolated quality_final instance")
        cursor.execute("SELECT COUNT(*) total,SUM(is_public=1 AND deleted_at IS NULL) public_count,"
                       "SUM(deleted_at IS NOT NULL) deleted_count FROM recipes")
        recipes = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) total,SUM(is_active=1) active_count FROM ingredients")
        ingredients = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) total FROM recipe_ingredients")
        line_count = int(cursor.fetchone()["total"])
        if (int(recipes["total"]) != 150 or int(recipes["public_count"]) != 146
                or int(recipes["deleted_count"]) != 4 or int(ingredients["total"]) != 270
                or int(ingredients["active_count"]) != 219 or line_count != 1384):
            raise RuntimeError("quality_final data counts differ from the verified baseline")

        marks = ",".join(["%s"] * len(mapping))
        old_ids = tuple(mapping)
        cursor.execute(f"SELECT COUNT(*) n FROM ingredients WHERE ingredient_id IN ({marks}) AND is_active=1", old_ids)
        if int(cursor.fetchone()["n"]) != 0:
            raise RuntimeError("One or more mapped legacy ingredient IDs are still active")
        cursor.execute(f"SELECT COUNT(*) n FROM recipe_ingredients WHERE ingredient_id IN ({marks})", old_ids)
        if int(cursor.fetchone()["n"]) != 0:
            raise RuntimeError("One or more recipe links still use a mapped old ingredient ID")
        target_ids = tuple(sorted(set(mapping.values())))
        target_marks = ",".join(["%s"] * len(target_ids))
        cursor.execute(f"SELECT COUNT(DISTINCT ingredient_id) n FROM ingredients WHERE is_active=1 AND ingredient_id IN ({target_marks})", target_ids)
        if int(cursor.fetchone()["n"]) != len(target_ids):
            raise RuntimeError("A canonical ingredient target is missing or inactive")
        ingredient_ids = tuple(sorted(planned_names))
        ingredient_marks = ",".join(["%s"] * len(ingredient_ids))
        cursor.execute(f"SELECT ingredient_id,name,normalized_name,is_active FROM ingredients WHERE ingredient_id IN ({ingredient_marks})", ingredient_ids)
        current_ingredients = {int(row["ingredient_id"]): row for row in cursor.fetchall()}
        if set(current_ingredients) != set(planned_names):
            raise RuntimeError("A repaired ingredient from the verified 29-row set is missing")
        for ingredient_id, expected_name in planned_names.items():
            current = current_ingredients[ingredient_id]
            expected_active = ingredient_id not in mapping
            if (current["name"] != expected_name or current["normalized_name"] != expected_name.casefold()
                    or bool(current["is_active"]) != expected_active):
                raise RuntimeError(f"Repaired ingredient state differs from the manifest at ID {ingredient_id}")
        moved_verified = 0
        for row in moved_rows:
            recipe_id, line_no = int(row["recipe_id"]), int(row["line_no"])
            cursor.execute("SELECT ingredient_id,quantity_text FROM recipe_ingredients WHERE recipe_id=%s AND line_no=%s",
                           (recipe_id, line_no))
            current = cursor.fetchone()
            expected_quantity = quantity_repairs.get((recipe_id, line_no), row["quantity_text"])
            if (current and int(current["ingredient_id"]) == mapping[int(row["ingredient_id"])]
                    and current["quantity_text"] == expected_quantity):
                moved_verified += 1
        if moved_verified != 40:
            raise RuntimeError("One or more of the 40 remapped recipe lines differ from the manifest")
        quantity_verified = 0
        for (recipe_id, line_no), expected_quantity in quantity_repairs.items():
            cursor.execute("SELECT quantity_text FROM recipe_ingredients WHERE recipe_id=%s AND line_no=%s",
                           (recipe_id, line_no))
            current = cursor.fetchone()
            if current and current["quantity_text"] == expected_quantity:
                quantity_verified += 1
        if quantity_verified != 37:
            raise RuntimeError("One or more of the 37 corrected quantity rows differ from the manifest")
        cursor.execute("SELECT COUNT(*) n FROM ingredients WHERE is_active=1 AND name LIKE '%?%'")
        if int(cursor.fetchone()["n"]) != 0:
            raise RuntimeError("Active ingredient catalog still contains a question-mark corruption")
        cursor.execute("SELECT COUNT(*) n FROM recipe_ingredients WHERE quantity_text LIKE '%?%'")
        if int(cursor.fetchone()["n"]) != 1:
            raise RuntimeError("Unresolved quantity count differs from the verified one-row baseline")
        cursor.execute("SELECT quantity_text FROM recipe_ingredients WHERE recipe_id=7980672409 AND line_no=18")
        unresolved = cursor.fetchone()
        if not unresolved or unresolved["quantity_text"] != "rang, m?t ?t":
            raise RuntimeError("The unresolved peanut quantity changed from the reviewed value")
        cursor.execute("SELECT deleted_at FROM recipes WHERE recipe_id=%s", (TEST_RECIPE_ID,))
        test_recipe = cursor.fetchone()
        if not test_recipe or test_recipe["deleted_at"] is None:
            raise RuntimeError("The TEST_ONLY recipe expected to remain soft-deleted is not deleted")

        cursor.execute("SELECT COUNT(*) n FROM recipe_ingredients ri LEFT JOIN recipes r USING(recipe_id) "
                       "LEFT JOIN ingredients i USING(ingredient_id) LEFT JOIN units u USING(unit_id) "
                       "WHERE r.recipe_id IS NULL OR i.ingredient_id IS NULL OR (ri.unit_id IS NOT NULL AND u.unit_id IS NULL)")
        recipe_line_orphans = int(cursor.fetchone()["n"])
        cursor.execute("SELECT COUNT(*) n FROM recipe_steps s LEFT JOIN recipes r USING(recipe_id) WHERE r.recipe_id IS NULL")
        step_orphans = int(cursor.fetchone()["n"])
        cursor.execute("SELECT COUNT(*) n FROM recipe_tag_links l LEFT JOIN recipes r USING(recipe_id) "
                       "LEFT JOIN recipe_tags t USING(tag_id) WHERE r.recipe_id IS NULL OR t.tag_id IS NULL")
        tag_orphans = int(cursor.fetchone()["n"])
        cursor.execute("SELECT COUNT(*) n FROM recipe_images i LEFT JOIN recipes r USING(recipe_id) WHERE r.recipe_id IS NULL")
        image_orphans = int(cursor.fetchone()["n"])
        cursor.execute("SELECT COUNT(*) total,SUM(role='ADMIN' AND status='ACTIVE') active_admins,"
                       "SUM(role='USER' AND status='ACTIVE') active_users FROM users")
        accounts = cursor.fetchone()
        cursor.execute("SELECT recipe_id,storage_key,media_type,byte_size,sha256 FROM recipe_images ORDER BY recipe_id")
        images = cursor.fetchall()
        cursor.close()
        if recipe_line_orphans or step_orphans or tag_orphans or image_orphans:
            raise RuntimeError("Unified schema contains orphaned recipe relations")
        missing_images = []
        for image in images:
            path = IMAGE_ROOT / image["storage_key"]
            if not path.is_file():
                missing_images.append(int(image["recipe_id"]))
                continue
            content = path.read_bytes()
            if len(content) != int(image["byte_size"]) or hashlib.sha256(content).hexdigest() != image["sha256"]:
                missing_images.append(int(image["recipe_id"]))
        if missing_images:
            raise RuntimeError(f"Stored image bytes are missing or fail integrity checks for recipe IDs {missing_images}")
        return {
            "database": DATABASE, "mysql_port": MYSQL_PORT,
            "recipes": {"total": int(recipes["total"]), "public": int(recipes["public_count"]),
                        "soft_deleted": int(recipes["deleted_count"])},
            "ingredients": {"total": int(ingredients["total"]), "active": int(ingredients["active_count"])},
            "recipe_ingredient_links": line_count, "mapped_old_ids_inactive_and_unreferenced": len(mapping),
            "mapped_recipe_links_verified": moved_verified, "repaired_quantity_rows_verified": quantity_verified,
            "ingredient_records_verified": len(planned_names),
            "orphan_counts": {"recipe_lines": recipe_line_orphans, "steps": step_orphans,
                              "tag_links": tag_orphans, "images": image_orphans},
            "images": {"metadata_rows": len(images), "integrity_checked": len(images), "missing_or_bad": 0},
            "accounts": {key: (int(value) if value is not None else 0) for key, value in accounts.items()},
            "test_recipe_soft_deleted": True,
            "unresolved_quantity": {"recipe_id": 7980672409, "line_no": 18, "value": "rang, m?t ?t"},
        }
    finally:
        connection.close()


def make_admin_env() -> dict[str, str]:
    credentials = dotenv_values(ROOT / ".env.admin.local", interpolate=False)
    username = credentials.get("ADMIN_USERNAME")
    password = credentials.get("ADMIN_PASSWORD")
    if not username or not password:
        raise RuntimeError("Local TEST_ONLY Admin credential is unavailable in .env.admin.local")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000, dklen=32)
    env = os.environ.copy()
    env.update({
        "UNIFIED_SCHEMA_MODE": "1", "TCP_DB_SCHEMA": "unified_v3",
        "UNIFIED_MYSQL_HOST": "127.0.0.1", "UNIFIED_MYSQL_PORT": str(MYSQL_PORT),
        "UNIFIED_MYSQL_USER": "root", "UNIFIED_MYSQL_PASSWORD": "",
        "UNIFIED_MYSQL_DATABASE": DATABASE, "UNIFIED_TCP_DB_POOL_SIZE": "4",
        "TCP_HOST": "127.0.0.1", "TCP_PORT": str(TCP_PORT), "TCP_MAX_CONNECTIONS": "4",
        "TCP_LOG_PATH": str(RUNTIME / "tcp.jsonl"),
        "FASTAPI_GATEWAY_LOG_PATH": str(RUNTIME / "fastapi.jsonl"),
        "ADMIN_USERNAME": username,
        "ADMIN_PASSWORD_HASH": f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}",
        "ADMIN_SESSION_SECRET": secrets.token_urlsafe(48),
        "ADMIN_COOKIE_SECURE": "false", "USER_COOKIE_SECURE": "false",
        "RECIPE_IMAGE_STORAGE_DIR": str(IMAGE_ROOT),
        "MEAL_PLAN_STATE_DIR": str(ROOT / ".test_runtime/quality-final/meal-state"),
    })
    return env


def start_mysql() -> tuple[subprocess.Popen | None, bool]:
    if not DATADIR.is_dir() or not (DATADIR / DATABASE).is_dir() or not (DATADIR / BASELINE_DATABASE).is_dir():
        raise RuntimeError("Expected isolated quality_final and rollback baseline schemas are not present")
    if not MYSQLD.is_file():
        raise RuntimeError("Local MySQL 8 server executable was not found")
    if not port_available(MYSQL_PORT):
        # Do not assume an occupied port is ours; accept it only after verifying its exact identity.
        wait_for_mysql(None)
        con = connect(DATABASE)
        try:
            cur = con.cursor()
            cur.execute("SELECT @@datadir,@@port,CURRENT_USER()")
            row = cur.fetchone()
            if Path(row[0]).resolve() != DATADIR.resolve() or int(row[1]) != MYSQL_PORT or not str(row[2]).startswith("root@127.0.0.1"):
                raise RuntimeError("Port 63900 belongs to a different MySQL instance; refusing to attach")
        finally:
            con.close()
        return None, False
    RUNTIME.mkdir(parents=True, exist_ok=True)
    pid_file = DATADIR / "quality-final.pid"
    error_log = RUNTIME / "mysqld.err"
    args = [
        str(MYSQLD), "--no-defaults", f"--datadir={DATADIR}",
        f"--port={MYSQL_PORT}", "--bind-address=127.0.0.1", "--mysqlx=0",
        "--skip-name-resolve", "--lower_case_table_names=1",
        f"--pid-file={pid_file}", f"--log-error={error_log}",
    ]
    log = (RUNTIME / "mysqld.stdout.log").open("ab")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    try:
        wait_for_mysql(process)
        return process, True
    except Exception:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        raise


def wait_http(url: str, tcp_thread: threading.Thread, api_thread: threading.Thread) -> None:
    for _ in range(100):
        if not tcp_thread.is_alive() or not api_thread.is_alive():
            raise RuntimeError("A TEST_ONLY service exited during startup; inspect statics/runtime/quality-v3-test")
        try:
            with urlopen(url, timeout=1) as response:
                data = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and (data.get("data") or {}).get("dataset_version", "").startswith("unified:"):
                    return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("FastAPI/TCP health check failed for the unified TEST_ONLY database")


def main() -> int:
    if not all(port_available(port) for port in (FASTAPI_PORT, TCP_PORT)):
        raise RuntimeError("Fixed TEST_ONLY API/TCP port 8010 or 9010 is occupied; no process was stopped")
    mysql_process = None
    owns_mysql = False
    tcp_server = None
    api_server = None
    tcp_thread = api_thread = None
    env = make_admin_env()
    try:
        mysql_process, owns_mysql = start_mysql()
        preflight = db_preflight()
        os.environ.update(env)
        from source.server.main import TCPServer, configured_tcp_max_connections
        from source.server.unified_repository import UnifiedMySQLRepository
        from source.web.main import app

        repository = UnifiedMySQLRepository.from_env()
        tcp_server = TCPServer("127.0.0.1", TCP_PORT,
                               max_connections=configured_tcp_max_connections(), repository=repository)
        tcp_thread = threading.Thread(target=tcp_server.serve_forever, name="quality-v3-tcp", daemon=True)
        tcp_thread.start()
        for _ in range(100):
            if not tcp_thread.is_alive():
                raise RuntimeError("TEST_ONLY TCP Server exited during startup")
            try:
                with socket.create_connection(("127.0.0.1", TCP_PORT), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("TEST_ONLY TCP Server did not bind to 9010")

        api_server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=FASTAPI_PORT,
                                                   log_level="warning", access_log=False))
        api_thread = threading.Thread(target=api_server.run, name="quality-v3-fastapi", daemon=True)
        api_thread.start()
        wait_http(f"http://127.0.0.1:{FASTAPI_PORT}/api/health", tcp_thread, api_thread)
        print(json.dumps({
            "status": "ready", "database_preflight": preflight,
            "mysql": f"127.0.0.1:{MYSQL_PORT}", "tcp": f"127.0.0.1:{TCP_PORT}",
            "fastapi": f"http://127.0.0.1:{FASTAPI_PORT}",
            "admin": f"http://127.0.0.1:{FASTAPI_PORT}/admin/login",
            "owns_mysql_process": owns_mysql,
            "logs": str(RUNTIME), "stop": "Ctrl+C stops this TEST_ONLY stack",
        }, ensure_ascii=False), flush=True)
        while api_thread.is_alive() and tcp_thread.is_alive():
            time.sleep(1)
        raise RuntimeError("A TEST_ONLY service stopped unexpectedly")
    except KeyboardInterrupt:
        print("Stopping the owned TEST_ONLY services.")
        return 0
    finally:
        if api_server is not None:
            api_server.should_exit = True
        if tcp_server is not None:
            tcp_server.shutdown()
        if api_thread is not None:
            api_thread.join(timeout=8)
        if tcp_thread is not None:
            tcp_thread.join(timeout=8)
        if owns_mysql:
            try:
                con = connect(DATABASE)
                con.cursor().execute("SHUTDOWN")
                con.close()
            except Exception:
                pass
            if mysql_process is not None:
                try:
                    mysql_process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    mysql_process.terminate()
                    mysql_process.wait(timeout=10)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"TEST_ONLY startup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
