"""End-to-end Admin UI rehearsal against a private TEST_ONLY MySQL clone.

Usage: .venv/Scripts/python.exe tests/admin_pilot5_playwright.py --test-only
The script never writes to the configured/production MySQL instance. All recipe
and ingredient changes are made by Chromium clicks in the Admin interface.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid
from urllib.parse import parse_qs, urlparse

from dotenv import dotenv_values
import mysql.connector
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BACKUP = ROOT / "statics/runtime/backups/goiy_mon_an-before-pilot5-20261108-214250-49dfe9a7e9464a35a02014a3ba6397c5.sql"
BACKUP_SHA256 = "89D91CC7C9A04C59891EF0A088789EE251C5F985B64A4188CB5E53605076698C"
PILOT_DOC = ROOT / "docs/data-normalization-pilot-5-admin-ready.md"
V2_OFFSET = 4_294_967_296
TARGET_INGREDIENTS = [
    (891047879, "oil", "Dầu ăn"),
    (2865256237, "salt", "Muối"),
    (3731415834, "sugar", "Đường"),
    (2056836464, "black pepper", "Tiêu đen"),
    (3331361648, "shallot", "Hành tím"),
]
INGREDIENT_PUBLIC_IDS = {
    1: 1, 2: 2, 3: 3, 5: 5, 6: 6, 7: 7, 8: 8, 9: 9, 10: 10,
    13: 13, 14: 14, 17: 17, 23: 23, 24: 24, 26: 26,
    891047879: V2_OFFSET + 891047879,
    2865256237: V2_OFFSET + 2865256237,
    3731415834: V2_OFFSET + 3731415834,
    2056836464: V2_OFFSET + 2056836464,
    3331361648: V2_OFFSET + 3331361648,
}
INGREDIENT_NAMES = {
    "Cá basa": (13, "Cá basa"), "Gừng tươi": (8, "Gừng"), "Gừng": (8, "Gừng"),
    "Tỏi": (7, "Tỏi"), "Hành tím": (3331361648, "Hành tím"),
    "Nước mắm": (24, "Nước mắm"), "Dầu ăn": (891047879, "Dầu ăn"),
    "Đường": (3731415834, "Đường"), "Tiêu xay": (2056836464, "Tiêu đen"),
    "Ớt tươi": (23, "Ớt"), "Thịt gà có xương": (14, "Thịt gà"),
    "Nấm hương tươi": (9, "Nấm hương"), "Cà rốt": (10, "Cà rốt"),
    "Hành lá": (17, "Hành lá"), "Muối": (2865256237, "Muối"),
    "Rau muống": (6, "Rau muống"), "Đậu phụ trắng": (5, "Đậu phụ"),
    "Cà chua": (2, "Cà chua"), "Trứng gà": (1, "Trứng"),
    "Mắm ruốc": (26, "Mắm ruốc"),
}
EXPECTED_RECIPE_VERSIONS = {
    4: "2ca1e97d1b20640a40cfdea503dc6e54574204e72880a7ebeead61503183476b",
    5: "ac734c0ba901a8722e6f141c91ae06425fef8fe6245882cf6ce050547c1f6bb5",
    6: "2c3ea05604960e70494ef5ec956b50bf5eabfd7930781980df73cbcc2c25a378",
    7: "2ce437d0ed7d951532058782b8116ef1307f13fcee5fc7c113e9326bb5dac5a5",
    7980672317: "1a0fd014a32e28ddaa89a8f62f40717910eeb85ad3607d1ef9a77e2f470601f1",
}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def load_admin_credentials() -> tuple[str, str]:
    values = dotenv_values(ROOT / ".env.admin.local", interpolate=False)
    username = values.get("ADMIN_USERNAME") or values.get("ADMIN_USER") or values.get("username") or values.get("USERNAME")
    password = values.get("ADMIN_PASSWORD") or values.get("password") or values.get("PASSWORD")
    if not username or not password:
        raise RuntimeError(".env.admin.local must provide Admin username and password; values were not displayed")
    return str(username), str(password)


def parse_pilot_document() -> list[dict]:
    text = PILOT_DOC.read_text(encoding="utf-8")
    headers = list(re.finditer(r"^##\s+(\d+)\.\s+(.*?)\s+\u2014\s+(.*?)\s+(\d+)\s*$", text, re.M))
    recipes = []
    for i, match in enumerate(headers):
        start = match.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else text.find("\n## ", start)
        if end < 0:
            end = len(text)
        section = text[start:end]
        title, identity_kind, id_text = match.group(2).strip(), match.group(3).strip(), match.group(4)
        recipe_id = int(id_text)
        description_line = next((line for line in section.splitlines() if line.startswith("**Mô tả:**")), None)
        role_line = next((line for line in section.splitlines() if line.startswith("**Vai trò:**")), None)
        minutes_line = next((line for line in section.splitlines() if "**Tổng nhập Admin:**" in line), None)
        if not description_line or not role_line or not minutes_line:
            raise RuntimeError(f"Pilot recipe fields are incomplete for ID {recipe_id}")
        description = description_line.split("**Mô tả:**", 1)[1].strip().rstrip()
        role_label = role_line.split("**Vai trò:**", 1)[1].split(".", 1)[0].strip()
        role = {"Món chính": "main", "Món rau": "vegetable", "Canh": "soup"}.get(role_label)
        if not role:
            raise RuntimeError(f"Unknown recipe role in pilot document for ID {recipe_id}")
        minutes_match = re.search(r"\*\*Tổng nhập Admin:\*\*\s*(\d+)\s+phút", minutes_line)
        if not minutes_match:
            raise RuntimeError(f"Missing total time in pilot document for ID {recipe_id}")
        instructions_match = re.search(r"\*\*Cách làm\*\*\s*\n(.*?)(?=\n\*\*(?:Mẹo|Nhận biết|Nguồn|Tách phiên bản)|\Z)", section, re.S)
        if not instructions_match:
            raise RuntimeError(f"Missing cooking steps in pilot document for ID {recipe_id}")
        instructions = "\n".join(line.strip() for line in instructions_match.group(1).splitlines() if re.match(r"\s*\d+[.)]\s+", line))
        lines = []
        before_steps = section.split("**Cách làm**", 1)[0]
        for line in before_steps.splitlines():
            if not line.strip().startswith("|") or line.lstrip().startswith("| Nguyên liệu") or re.match(r"\s*\|\s*[-: ]+\|", line):
                continue
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 2 or cells[0] in {"Nước lọc", "Nước"}:
                continue
            resolved = INGREDIENT_NAMES.get(cells[0])
            if not resolved:
                raise RuntimeError(f"Ingredient {cells[0]!r} has no approved catalog mapping in the UI test script")
            internal_id, display_name = resolved
            lines.append({"ingredient_id": INGREDIENT_PUBLIC_IDS[internal_id], "name": display_name, "quantity": cells[1]})
        recipes.append({"id": recipe_id, "identity_kind": identity_kind, "title": title,
            "description": description, "role": role, "minutes": int(minutes_match.group(1)),
            "instructions": instructions, "ingredients": lines})
    if len(recipes) != 5 or sum(len(r["ingredients"]) for r in recipes) != 37:
        raise RuntimeError(f"Pilot document did not parse to 5 recipes/37 ingredient rows: {len(recipes)} recipes, {sum(len(r['ingredients']) for r in recipes)} rows")
    return recipes


def backup_preflight() -> None:
    if not BACKUP.is_file():
        raise RuntimeError("Specified post-migration-010 backup is missing")
    actual = sha256_file(BACKUP)
    if actual != BACKUP_SHA256:
        raise RuntimeError("Specified backup SHA-256 does not match")
    with BACKUP.open("r", encoding="utf-8", errors="replace") as dump:
        for line in dump:
            if re.search(r"(?im)^\s*(?:CREATE\s+DATABASE|USE)\s+[`\"]?goiy_mon_an\b", line):
                raise RuntimeError("Backup contains a fixed production database directive; refusing restore")
    print("backup_sha256_verified", actual)


def sql_rows(connection, statement, params=()):
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(statement, params)
        return cursor.fetchall() if cursor.with_rows else []
    finally:
        cursor.close()


def start_private_mysql(workdir: Path):
    mysqld = Path(os.getenv("MYSQL_V2_MYSQLD") or r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe")
    mysql_cli = mysqld.with_name("mysql.exe")
    if not mysqld.is_file() or not mysql_cli.is_file():
        raise RuntimeError("Private TEST_ONLY MySQL binaries are unavailable")
    basedir = mysqld.parent.parent
    data_dir, tmp_dir = workdir / "data", workdir / "tmp"
    tmp_dir.mkdir(parents=True)
    common = [str(mysqld), "--no-defaults", f"--basedir={basedir}", f"--datadir={data_dir}", f"--tmpdir={tmp_dir}"]
    init_log = workdir / "mysql-initialize.err"
    initialized = subprocess.run([*common, "--initialize-insecure", f"--log-error={init_log}"],
        cwd=workdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if initialized.returncode:
        raise RuntimeError("Private TEST_ONLY MySQL initialization failed")
    port = free_port()
    process = subprocess.Popen([*common, f"--port={port}", "--bind-address=127.0.0.1", "--skip-mysqlx",
        "--skip-log-bin", f"--pid-file={workdir / 'mysql.pid'}", f"--log-error={workdir / 'mysql-server.err'}"],
        cwd=workdir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    config = {"host":"127.0.0.1","port":port,"user":"root","password":"","charset":"utf8mb4",
              "collation":"utf8mb4_unicode_ci","connection_timeout":3,"autocommit":True}
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and process.poll() is None:
        try:
            conn = mysql.connector.connect(**config)
            sql_rows(conn, "SET GLOBAL sql_mode='STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'")
            conn.close()
            return process, config, mysql_cli
        except mysql.connector.Error:
            time.sleep(.25)
    if process.poll() is None:
        process.terminate()
        try:process.wait(timeout=10)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    raise RuntimeError("Private TEST_ONLY MySQL did not start; inspect its isolated runtime log")


def stop_private_mysql(process, artifacts: Path) -> None:
    """Stop only the isolated server whose PID was recorded in this run's private datadir."""
    if process is not None and process.poll() is None:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    pid_file=artifacts/"mysql.pid"
    log_file=artifacts/"mysql-server.err"
    if not pid_file.is_file() or not log_file.is_file():return
    try:server_pid=int(pid_file.read_text(encoding="ascii").strip())
    except (OSError,ValueError):return
    if server_pid<=0:return
    # The startup record binds this PID to the unique TEST_ONLY artifact folder.
    log_text=log_file.read_text(encoding="utf-8",errors="replace")
    if f"starting as process {server_pid}" not in log_text:return
    if os.name=="nt":
        subprocess.run(["taskkill.exe","/PID",str(server_pid),"/T","/F"],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=8,check=False)
    else:
        try:os.kill(server_pid,15)
        except ProcessLookupError:pass


def restore_backup(config: dict, mysql_cli: Path, artifacts: Path) -> dict:
    admin = mysql.connector.connect(**config)
    try:
        sql_rows(admin, "CREATE DATABASE goiy_mon_an CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    finally:
        admin.close()
    command = [str(mysql_cli), "--no-defaults", "--host=127.0.0.1", f"--port={config['port']}",
        "--user=root", "--default-character-set=utf8mb4", "--database=goiy_mon_an"]
    with BACKUP.open("rb") as dump:
        completed = subprocess.run(command, stdin=dump, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", "replace")[:800]
        raise RuntimeError("Backup restore into private TEST_ONLY database failed: " + detail)
    dbconfig = {**config, "database":"goiy_mon_an"}
    connection = mysql.connector.connect(**dbconfig)
    try:
        counts = {name:int(sql_rows(connection, f"SELECT COUNT(*) AS n FROM {name}")[0]["n"])
                  for name in ("recipes","ingredients","recipe_ingredients")}
        trigger_count = int(sql_rows(connection, "SELECT COUNT(*) AS n FROM information_schema.triggers WHERE trigger_schema=DATABASE()")[0]["n"])
        migration_rows = sql_rows(connection, "SELECT version,execution_result FROM v2_migration_history ORDER BY version")
        migrations = {str(r["version"]):r["execution_result"] for r in migration_rows}
        if counts != {"recipes":50,"ingredients":50,"recipe_ingredients":252} or trigger_count != 2:
            raise RuntimeError(f"Restored baseline mismatch: counts={counts}, triggers={trigger_count}")
        expected_migrations = (
            "001_portion_catalog", "003_admin_draft_description", "004_admin_ingredient_state",
            "005_user_accounts", "006_legacy_recipe_overlays", "007_recipe_images",
            "008_admin_legacy_ingredient_overrides", "009_admin_recipe_catalog",
            "010_legacy_recipe_catalog_ingredients",
        )
        for version in expected_migrations:
            if migrations.get(version) != "APPLIED":
                raise RuntimeError(f"Backup migration {version} is not APPLIED")
        if "002_recipe_context" in migrations:
            raise RuntimeError("Backup unexpectedly has migration 002")
        # Expected target identity/status and recipe versions are verified later through Admin UI.
        return {"counts":counts,"triggers":trigger_count,"migrations":migrations}
    finally:
        connection.close()


def configure_test_accounts(config: dict) -> tuple[str, str, str, str, str, str]:
    reader_user, writer_user, account_writer = "goiy_app", "goiy_admin_writer", "goiy_user_writer"
    reader_password, writer_password, account_password = (secrets.token_urlsafe(30), secrets.token_urlsafe(30), secrets.token_urlsafe(30))
    connection = mysql.connector.connect(**{**config,"database":"goiy_mon_an"})
    try:
        cur = connection.cursor()
        for username,password,hosts in ((reader_user,reader_password,("localhost","127.0.0.1")),
                                        (writer_user,writer_password,("localhost","127.0.0.1")),
                                        (account_writer,account_password,("127.0.0.1",))):
            for host in hosts:
                cur.execute(f"CREATE USER '{username}'@'{host}' IDENTIFIED BY %s", (password,))
                cur.execute(f"GRANT SELECT ON goiy_mon_an.* TO '{username}'@'{host}'") if username==reader_user else None
        from source.web.setup_admin import (DRAFT_REQUIRED_GRANTS, INGREDIENT_ADMIN_GRANTS,
            LEGACY_INGREDIENT_ADMIN_GRANTS, REVIEW_GRANTS)
        grant_statements = [*REVIEW_GRANTS,*INGREDIENT_ADMIN_GRANTS,*LEGACY_INGREDIENT_ADMIN_GRANTS]
        for host in ("localhost","127.0.0.1"):
            for statement in grant_statements:
                statement=statement.replace("goiy_mon_an.","goiy_mon_an.")
                statement=statement.replace("'goiy_admin_writer'@'localhost'",f"'{writer_user}'@'{host}'")
                if "'goiy_admin_writer'@'" not in statement:
                    continue
                cur.execute(statement)
            for scope,privileges in DRAFT_REQUIRED_GRANTS.items():
                if scope=="*.*":continue
                table=scope.split(".",1)[1]
                for privilege in sorted(privileges):
                    cur.execute(f"GRANT {privilege.upper()} ON goiy_mon_an.{table} TO '{writer_user}'@'{host}'")
            for table, privileges in (
                ("v2_admin_legacy_recipe_overrides", "SELECT, INSERT, UPDATE"),
                ("v2_admin_legacy_recipe_override_ingredients", "SELECT, INSERT, UPDATE, DELETE"),
                ("v2_admin_recipe_catalog_overrides", "SELECT, INSERT, UPDATE"),
                ("v2_recipe_image_overrides", "SELECT"),
            ):
                cur.execute(f"GRANT {privileges} ON goiy_mon_an.{table} TO '{writer_user}'@'{host}'")
        account_host="127.0.0.1"
        account=f"'{account_writer}'@'{account_host}'"
        for statement in (
            f"GRANT SELECT ON goiy_mon_an.v2_user_accounts TO {account}",
            f"GRANT INSERT (username, normalized_username, password_hash) ON goiy_mon_an.v2_user_accounts TO {account}",
            f"GRANT UPDATE (account_status, role, last_login_at) ON goiy_mon_an.v2_user_accounts TO {account}",
            f"GRANT SELECT ON goiy_mon_an.v2_migration_history TO {account}",
        ):
            cur.execute(statement)
        cur.close()
    finally:
        connection.close()
    return reader_user,reader_password,writer_user,writer_password,account_writer,account_password


def launch_services(reader_user,reader_password,writer_user,writer_password,account_writer,account_password,admin_username,admin_password,artifacts):
    from dotenv import dotenv_values
    source_env = dotenv_values(ROOT / ".env", interpolate=False)
    admin_hash = source_env.get("ADMIN_PASSWORD_HASH")
    if not admin_hash:
        raise RuntimeError("Admin PBKDF2 hash is not configured in the local environment")
    web_port,tcp_port=free_port(),free_port()
    while tcp_port==web_port:tcp_port=free_port()
    child_env=os.environ.copy()
    child_env.update({
        "MYSQL_HOST":"127.0.0.1","MYSQL_PORT":str(os.environ["PILOT5_PRIVATE_MYSQL_PORT"]),
        "MYSQL_DATABASE":"goiy_mon_an","MYSQL_USER":reader_user,"MYSQL_PASSWORD":reader_password,
        "MYSQL_DRAFT_WRITER_USER":writer_user,"MYSQL_DRAFT_WRITER_PASSWORD":writer_password,
        "MYSQL_USER_ACCOUNT_WRITER_USER":account_writer,"MYSQL_USER_ACCOUNT_WRITER_PASSWORD":account_password,
        "TCP_HOST":"127.0.0.1","TCP_PORT":str(tcp_port),"TCP_DB_POOL_SIZE":"4",
        "TCP_LOG_PATH":str(artifacts/"tcp-testonly.jsonl"),
        "ADMIN_USERNAME":admin_username,"ADMIN_PASSWORD_HASH":admin_hash,
        "ADMIN_SESSION_SECRET":secrets.token_urlsafe(48),"ADMIN_COOKIE_SECURE":"false",
        "PYTHONPATH":str(ROOT),"APP_ENV":"TEST_ONLY",
    })
    server_log=(artifacts/"tcp-process.log").open("w",encoding="utf-8")
    web_log=(artifacts/"fastapi-process.log").open("w",encoding="utf-8")
    python=str(Path(sys.executable).resolve())
    tcp=subprocess.Popen([python,"-m","source.server.main"],cwd=ROOT,env=child_env,stdout=server_log,stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    web=subprocess.Popen([python,"-m","uvicorn","source.web.main:app","--host","127.0.0.1","--port",str(web_port)],
                         cwd=ROOT,env=child_env,stdout=web_log,stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    return tcp,web,tcp_port,web_port,server_log,web_log


def wait_http(base: str, process, timeout=40):
    import urllib.request
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline and process.poll() is None:
        try:
            with urllib.request.urlopen(base+"/api/health",timeout=2) as response:
                if response.status==200:return
        except Exception:time.sleep(.25)
    raise RuntimeError("TEST_ONLY FastAPI did not become ready")


def do_login(page, base: str, username: str, password: str, require_write: bool = True):
    page.goto(base+"/admin/login",wait_until="domcontentloaded")
    page.locator('input[name="username"]').fill(username)
    page.locator('input[name="password"]').fill(password)
    page.locator("#admin-login-submit").click()
    page.wait_for_url(re.compile(re.escape(base)+r"/admin(?:[#?].*)?$"),timeout=15000)
    expect(page.locator("#admin-app")).to_be_visible()
    if require_write:
        expect(page.locator("#admin-create")).to_be_enabled(timeout=20000)


def verify_production_admin_ui(username: str, password: str, artifacts: Path) -> dict:
    """Read-only browser check on the requested running site; never submits writes."""
    status = {"url": "http://127.0.0.1:8003", "login": False, "ingredient_view": False}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 900})
        try:
            do_login(page, status["url"], username, password, require_write=False)
            status["login"] = True
            page.locator('[data-admin-view="ingredients"]').click()
            expect(page.locator("#admin-ingredients")).to_be_visible(timeout=10000)
            status["ingredient_readiness"] = page.locator("#admin-ingredient-readiness").inner_text()
            status["ingredient_admin_enabled"] = page.locator("#admin-ingredient-create").is_enabled()
            status["ingredient_view"] = True
            page.screenshot(path=str(artifacts / "production-admin-readonly-8003.png"), full_page=True)
            status["screenshot"] = "production-admin-readonly-8003.png"
        except Exception as exc:
            # Keep diagnostics non-sensitive; do not serialize page content, cookies, or headers.
            status["error_type"] = type(exc).__name__
        finally:
            browser.close()
    return status


@contextmanager
def managed_chromium(playwright):
    browser=playwright.chromium.launch(headless=True)
    try:
        yield browser
    finally:
        browser.close()


def user_ingredient_present(page, base: str, display_name: str, artifacts: Path):
    page.goto(base+"/",wait_until="domcontentloaded")
    page.locator("#ingredient-results[aria-busy='false']").wait_for(timeout=15000)
    page.locator("#ingredient-search").fill(display_name)
    row=page.locator("#ingredient-results .ingredient-row").filter(has_text=display_name).first
    expect(row).to_be_visible(timeout=8000)
    return row


def run_browser_flow(base: str, username: str, password: str, recipes: list[dict], artifacts: Path):
    result={"ingredient_saves":0,"recipe_saves":0,"ingredient_ids":[],"recipe_ids":[],"screenshots":[],"preflight":{}}
    with sync_playwright() as playwright, managed_chromium(playwright) as browser:
        context=browser.new_context(viewport={"width":1440,"height":1000},device_scale_factor=1)
        page=context.new_page()
        page_errors=[]
        allow_admin_images={"value":False}
        def admin_image_route(route):
            if allow_admin_images["value"]:
                route.continue_()
            else:
                route.abort()
        page.route(re.compile(r".*/api/admin/recipes/\d+/image(?:\?.*)?$"),admin_image_route)
        page.on("pageerror",lambda error: page_errors.append(type(error).__name__))
        do_login(page,base,username,password)
        # The direct catalog and ingredient writer readiness gates must be active in the UI.
        page.locator('[data-admin-view="ingredients"]').click()
        expect(page.locator("#admin-ingredient-readiness")).to_be_visible(timeout=10000)
        page.locator("#admin-ingredient-catalog-mode").select_option("shared")
        page.locator("#admin-ingredient-query").fill("")
        page.locator('#admin-ingredient-search button[type="submit"]').click()
        expect(page.locator("#admin-ingredient-page-status")).to_contain_text("/ 50", timeout=10000)
        result["preflight"]["admin_shared_total"] = page.locator("#admin-ingredient-page-status").inner_text()
        page.goto(base+"/",wait_until="domcontentloaded")
        page.locator("#ingredient-results[aria-busy='false']").wait_for(timeout=15000)
        user_count=page.locator("#ingredient-results .ingredient-row").count()
        if user_count != 50:
            raise RuntimeError(f"TEST_ONLY User ingredient baseline expected 50, observed {user_count}; no writes performed")
        result["preflight"]["user_ingredient_count"] = user_count

        # Verify all five exact internal IDs, English source names, status and edit versions
        # through the Admin interface before any save. Record each recipe snapshot first.
        page.goto(base+"/admin",wait_until="domcontentloaded")
        page.locator('[data-admin-view="ingredients"]').click()
        page.locator("#admin-ingredient-catalog-mode").select_option("v2")
        with page.expect_response(lambda response: "/api/admin/ingredients?catalog=v2" in response.url and response.request.method=="GET",timeout=12000) as catalog_event:
            page.locator("#admin-ingredient-query").fill("")
            page.locator('#admin-ingredient-search button[type="submit"]').click()
        catalog_data=catalog_event.value.json()
        catalog_by_id={}
        for internal_id,old_name,new_name in TARGET_INGREDIENTS:
            page.locator("#admin-ingredient-query").fill(old_name)
            with page.expect_response(lambda response: "/api/admin/ingredients?" in response.url and
                parse_qs(urlparse(response.url).query).get("catalog")==["v2"] and
                parse_qs(urlparse(response.url).query).get("query")==[old_name] and response.request.method=="GET",timeout=12000) as target_event:
                page.locator('#admin-ingredient-search button[type="submit"]').click()
            target_payload=target_event.value.json()
            target_data=target_payload.get("data") or {}
            found=[item for item in target_data.get("items",[]) if int(item["ingredient_id"])==V2_OFFSET+internal_id]
            item=found[0] if len(found)==1 else None
            if not item or item.get("name")!=old_name or item.get("identity_status")!="NEEDS_VERIFICATION" or item.get("can_edit") is not True:
                observed=[{key:value for key,value in candidate.items() if key in {"ingredient_id","name","identity_status","can_edit","can_manage"}}
                          for candidate in target_data.get("items",[])]
                error=target_payload.get("error") or {}
                raise RuntimeError(f"TEST_ONLY ingredient {internal_id} differs from expected unverified baseline "
                    f"(HTTP={target_event.value.status}, error_code={error.get('code')}, observed={observed[:5]}); no writes performed")
            catalog_by_id[V2_OFFSET+internal_id]=item
        result["preflight"]["target_ingredients"]="5 exact IDs in NEEDS_VERIFICATION"
        result["preflight"]["v2_admin_total"]=(catalog_data.get("data") or {}).get("total")

        for recipe in recipes:
            page.goto(base+"/admin",wait_until="domcontentloaded")
            page.locator('[data-admin-view="recipes"]').click()
            query = ("Đậu phụ sốt cà chua" if recipe["id"]==4 else
                     recipe["title"] if recipe["id"]!=7980672317 else "trứng kho")
            page.locator("#admin-query").fill(query)
            page.locator('#admin-search button[type="submit"]').click()
            row=page.locator("#admin-recipes tr").filter(has_text=query).first
            expect(row).to_be_visible(timeout=12000)
            if recipe["id"]<=0xFFFFFFFF:
                button=row.locator(f'button[data-edit-legacy="{recipe["id"]}"]')
                path_suffix=f"/api/admin/legacy-recipes/{recipe['id']}"
            else:
                button=row.locator("button[data-edit]")
                path_suffix="/api/admin/revisions/"
            allow_admin_images["value"]=True
            with page.expect_response(lambda response: path_suffix in response.url and response.request.method=="GET",timeout=12000) as detail_event:
                button.click()
            detail_envelope=detail_event.value.json()
            detail=detail_envelope.get("data") or {}
            if detail.get("edit_version")!=EXPECTED_RECIPE_VERSIONS[recipe["id"]]:
                raise RuntimeError(f"TEST_ONLY recipe {recipe['id']} edit_version differs from verified baseline; no writes performed")
            if recipe["id"]>0xFFFFFFFF and int(detail.get("recipe_id",0))!=recipe["id"]:
                raise RuntimeError("V2 recipe identity changed before editing; no writes performed")
            snapshot={"TEST_ONLY":True,"recipe_id":recipe["id"],"captured_edit_version":detail["edit_version"],
                      "detail":detail,"image_preview":None}
            expect(page.locator("#admin-editor")).to_be_visible(timeout=8000)
            preview=page.locator("#draft-image-preview img")
            if preview.count():snapshot["image_preview"]=preview.first.get_attribute("src")
            (artifacts/f"preflight-recipe-{recipe['id']}.json").write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding="utf-8")
            page.locator("#draft-cancel").click()
            expect(page.locator("#admin-editor")).not_to_be_visible(timeout=8000)
            allow_admin_images["value"]=False
        result["preflight"]["recipe_versions"]="5 exact edit_version values verified; snapshots saved"

        page.goto(base+"/admin",wait_until="domcontentloaded")
        page.locator('[data-admin-view="ingredients"]').click()
        page.locator("#admin-ingredient-catalog-mode").select_option("v2")
        for internal_id,old_name,new_name in TARGET_INGREDIENTS:
            page.locator("#admin-ingredient-query").fill(old_name)
            page.locator('#admin-ingredient-search button[type="submit"]').click()
            row=page.locator("#admin-ingredients tr").filter(has_text=old_name).first
            expect(row).to_be_visible(timeout=8000)
            row.locator("button[data-ingredient-edit]").click()
            expect(page.locator("#admin-ingredient-availability-option")).to_be_visible()
            expect(page.locator("#admin-ingredient-make-available")).not_to_be_checked()
            page.locator("#admin-ingredient-name").fill(new_name)
            page.locator("#admin-ingredient-make-available").check()
            page.screenshot(path=str(artifacts/f"admin-ingredient-before-{internal_id}.png"),full_page=True)
            result["screenshots"].append(f"admin-ingredient-before-{internal_id}.png")
            page.locator("#admin-ingredient-save").click()
            expect(page.locator("#admin-ingredient-form")).to_have_class(re.compile("hidden"),timeout=12000)
            result["ingredient_saves"]+=1
            result["ingredient_ids"].append(V2_OFFSET+internal_id)
            user_ingredient_present(page,base,new_name,artifacts)
            page.screenshot(path=str(artifacts/f"user-ingredient-{internal_id}.png"),full_page=True)
            result["screenshots"].append(f"user-ingredient-{internal_id}.png")
            page.goto(base+"/admin",wait_until="domcontentloaded")
            page.locator('[data-admin-view="ingredients"]').click()
            page.locator("#admin-ingredient-catalog-mode").select_option("shared")
            expect(page.locator("#admin-ingredient-page-status")).to_contain_text(f"/ {50+result['ingredient_saves']}",timeout=8000)
            page.locator("#admin-ingredient-query").fill(new_name)
            page.locator('#admin-ingredient-search button[type="submit"]').click()
            expect(page.locator("#admin-ingredients")).to_contain_text(new_name)
            # Go back to the isolated unverified-management view for the next target.
            page.locator("#admin-ingredient-catalog-mode").select_option("v2")

        # Search the public-facing list in the UI: all five are available and no untranslated v2 item is public.
        # Capture the read-only source rows behind the shared IDs so duplicate-name
        # projection issues can be distinguished from a missing UI option.
        diagnostic_connection=mysql.connector.connect(host="127.0.0.1",port=int(os.environ["PILOT5_PRIVATE_MYSQL_PORT"]),
            user="root",password="",database="goiy_mon_an",charset="utf8mb4",collation="utf8mb4_unicode_ci")
        try:
            diagnostic=[]
            for internal_id,_,display_name in TARGET_INGREDIENTS:
                matches=sql_rows(diagnostic_connection,"""SELECT i.id,i.canonical_name,i.normalized_name,i.identity_status,
                    i.legacy_ingredient_id,i.review_decision_id,i.evidence_set_id,COALESCE(s.is_active,1) is_active
                    FROM v2_ingredients i LEFT JOIN v2_ingredient_admin_state s ON s.ingredient_id=i.id
                    WHERE i.id=%s OR i.canonical_name=%s ORDER BY i.id""",(internal_id,display_name))
                diagnostic.extend(matches)
            (artifacts/"ingredient-identity-diagnostic.json").write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding="utf-8")
        finally:
            diagnostic_connection.close()
        page.goto(base+"/",wait_until="domcontentloaded")
        page.locator("#ingredient-results[aria-busy='false']").wait_for(timeout=15000)
        page.locator("#ingredient-search").fill("")
        expect(page.locator("#ingredient-results .ingredient-row")).to_have_count(55,timeout=10000)
        for _,_,name in TARGET_INGREDIENTS:
            expect(page.locator("#ingredient-results")).to_contain_text(name)
        expect(page.locator("#ingredient-results")).not_to_contain_text("black pepper")
        page.screenshot(path=str(artifacts/"user-ingredients-55.png"),full_page=True)
        result["screenshots"].append("user-ingredients-55.png")

        for recipe in recipes:
            page.goto(base+"/admin",wait_until="domcontentloaded")
            page.locator('[data-admin-view="recipes"]').click()
            page.locator("#admin-query").fill(recipe["title"] if recipe["id"]!=7980672317 else "trứng kho")
            page.locator('#admin-search button[type="submit"]').click()
            row=page.locator("#admin-recipes tr").filter(has_text=recipe["title"] if recipe["id"]!=7980672317 else "trứng kho").first
            expect(row).to_be_visible(timeout=12000)
            if recipe["id"]<=0xFFFFFFFF:
                button=row.locator(f'button[data-edit-legacy="{recipe["id"]}"]')
                path_suffix=f"/api/admin/legacy-recipes/{recipe['id']}"
            else:
                button=row.locator("button[data-edit]")
                path_suffix=f"/api/admin/revisions/"
            allow_admin_images["value"]=True
            with page.expect_response(lambda response: path_suffix in response.url and response.request.method=="GET",timeout=12000) as detail_event:
                button.click()
            detail_response=detail_event.value
            detail_envelope=detail_response.json()
            detail=detail_envelope.get("data") or {}
            if detail.get("edit_version")!=EXPECTED_RECIPE_VERSIONS[recipe["id"]]:
                raise RuntimeError(f"TEST_ONLY recipe {recipe['id']} edit_version differs from verified baseline")
            if recipe["id"]>0xFFFFFFFF and int(detail.get("recipe_id",0))!=recipe["id"]:
                raise RuntimeError("V2 recipe identity changed before editing")
            snapshot={"TEST_ONLY":True,"recipe_id":recipe["id"],"captured_edit_version":detail["edit_version"],
                      "detail":detail,"image_preview":None}
            editor=page.locator("#admin-editor")
            expect(editor).to_be_visible(timeout=8000)
            preview=page.locator("#draft-image-preview img")
            if preview.count():snapshot["image_preview"]=preview.first.get_attribute("src")
            snap_path=artifacts/f"snapshot-before-recipe-{recipe['id']}.json"
            snap_path.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding="utf-8")
            page.screenshot(path=str(artifacts/f"admin-recipe-before-{recipe['id']}.png"),full_page=True)
            result["screenshots"].append(f"admin-recipe-before-{recipe['id']}.png")
            page.locator("#draft-title").fill(recipe["title"])
            page.locator("#draft-description").fill(recipe["description"])
            page.locator("#draft-role").select_option(recipe["role"])
            page.locator("#draft-minutes").fill(str(recipe["minutes"]))
            page.locator("#editor-tab-button-ingredients").click()
            existing=page.locator("#draft-lines .admin-line button")
            while existing.count():
                existing.first.click()
            for line in recipe["ingredients"]:
                page.locator("#draft-add-line").click()
                current=page.locator("#draft-lines .admin-line").last
                try:
                    current.locator("select").select_option(str(line["ingredient_id"]))
                except Exception as exc:
                    options=current.locator("select option").evaluate_all("items => items.map(o => ({id:o.value,name:o.textContent}))")
                    matching_options=[option for option in options if option["id"]==str(line["ingredient_id"])
                                      or line["name"].casefold() in option["name"].casefold()]
                    raise RuntimeError(f"Ingredient option missing for recipe {recipe['id']}: {line['name']} id={line['ingredient_id']}; option_count={len(options)-1}; matching_options={matching_options}; visible_options={options}") from exc
                current.locator("[data-quantity]").fill(line["quantity"])
            page.locator("#editor-tab-button-instructions").click()
            page.locator("#draft-instructions").fill(recipe["instructions"])
            page.screenshot(path=str(artifacts/f"admin-recipe-ready-{recipe['id']}.png"),full_page=True)
            result["screenshots"].append(f"admin-recipe-ready-{recipe['id']}.png")
            with page.expect_response(lambda response: response.request.method=="PATCH" and
                (f"/api/admin/legacy-recipes/{recipe['id']}" in response.url or
                 f"/api/admin/catalog-recipes/{recipe['id']}" in response.url),timeout=30000) as save_event:
                page.locator("#draft-save").click()
            save_response=save_event.value
            if not save_response.ok:
                raise RuntimeError(f"Admin UI save failed for recipe {recipe['id']} (HTTP {save_response.status})")
            expect(editor).not_to_be_visible(timeout=20000)
            allow_admin_images["value"]=False
            result["recipe_saves"]+=1
            result["recipe_ids"].append(recipe["id"])

            # Confirm the published User detail page rendered from the shared catalog, including every line.
            page.goto(f"{base}/recipes/{recipe['id']}",wait_until="domcontentloaded")
            expect(page.locator("#detail[aria-busy='false']")).to_be_visible(timeout=15000)
            expect(page.locator("#detail h1")).to_have_text(recipe["title"])
            expect(page.locator("#detail .ingredient-list li")).to_have_count(len(recipe["ingredients"]),timeout=10000)
            detail_text=page.locator("#detail").inner_text()
            user_images=page.locator("#detail img")
            if snapshot.get("image_preview") and user_images.count()==0:
                raise RuntimeError(f"User detail lost the existing image for recipe {recipe['id']}")
            for image_index in range(user_images.count()):
                loaded=user_images.nth(image_index).evaluate("img => img.complete && img.naturalWidth > 0")
                if not loaded:
                    raise RuntimeError(f"User image did not load for recipe {recipe['id']}")
            for line in recipe["ingredients"]:
                if line["name"] not in detail_text or line["quantity"] not in detail_text:
                    raise RuntimeError(f"User detail missing ingredient/quantity for recipe {recipe['id']}")
            for step in recipe["instructions"].splitlines():
                step_text=re.sub(r"^\d+[.)]\s*","",step)
                if step_text[:40] not in detail_text:
                    raise RuntimeError(f"User detail missing a cooking step for recipe {recipe['id']}")
            page.screenshot(path=str(artifacts/f"user-recipe-{recipe['id']}.png"),full_page=True)
            result["screenshots"].append(f"user-recipe-{recipe['id']}.png")

        # User search and B0/P1 recommendation are performed through the website controls.
        page.goto(base+"/",wait_until="domcontentloaded")
        page.locator("#ingredient-results[aria-busy='false']").wait_for(timeout=15000)
        page.get_by_role("link", name="Kh?m ph?").click()
        page.locator("#recipe-query").fill("Cá basa kho gừng")
        page.locator("#recommend-button").click()
        expect(page.locator(f'a[href="/recipes/7"]')).to_be_visible(timeout=15000)
        page.screenshot(path=str(artifacts/"user-search-cabasakho.png"),full_page=True)
        result["screenshots"].append("user-search-cabasakho.png")
        page.goto(base+"/",wait_until="domcontentloaded")
        page.locator("#ingredient-results[aria-busy='false']").wait_for(timeout=15000)
        page.locator("#ingredient-search").fill("Cá basa")
        page.locator('#ingredient-results [data-select="13"]').click()
        expect(page.locator('a[href="/recipes/7"]')).to_be_visible(timeout=20000)
        expect(page.locator("#results")).to_contain_text("P1")
        page.screenshot(path=str(artifacts/"user-recommend-b0-p1.png"),full_page=True)
        result["screenshots"].append("user-recommend-b0-p1.png")

        # The current meal-plan UI is also exercised via its own form.
        page.goto(base+"/meal-plan",wait_until="domcontentloaded")
        expect(page.locator("#meal-generate")).to_be_enabled(timeout=15000)
        page.locator("#meal-generate").click()
        expect(page.locator("#meal-cards .meal-card")).to_have_count(3,timeout=25000)
        page.screenshot(path=str(artifacts/"user-meal-plan-v2.png"),full_page=True)
        result["screenshots"].append("user-meal-plan-v2.png")
        page.goto(base+"/meal-plan/v1",wait_until="domcontentloaded")
        expect(page.locator("#meal-generate")).to_be_enabled(timeout=15000)
        page.locator("#meal-generate").click()
        expect(page.locator("#meal-cards .meal-card")).to_have_count(3,timeout=25000)
        page.screenshot(path=str(artifacts/"user-meal-plan-v1.png"),full_page=True)
        result["screenshots"].append("user-meal-plan-v1.png")
        result["page_errors"]=page_errors
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser=argparse.ArgumentParser()
    parser.add_argument("--test-only",action="store_true",help="required safety acknowledgment; all writes go to private restored TEST_ONLY MySQL")
    args=parser.parse_args()
    if not args.test_only:
        print("Refusing to run without --test-only; no production updates are supported by this script.")
        return 2
    artifacts=ROOT/"statics/runtime"/f"admin-pilot5-playwright-TEST_ONLY-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    artifacts.mkdir(parents=True,exist_ok=False)
    mysql_process=tcp_process=web_process=None
    log_handles=[]
    try:
        backup_preflight()
        recipes=parse_pilot_document()
        username,password=load_admin_credentials()
        production_ui=verify_production_admin_ui(username,password,artifacts)
        (artifacts/"production-ui-readonly.json").write_text(json.dumps(production_ui,ensure_ascii=False,indent=2),encoding="utf-8")
        mysql_process,root_config,mysql_cli=start_private_mysql(artifacts)
        restore_status=restore_backup(root_config,mysql_cli,artifacts)
        reader_user,reader_pass,writer_user,writer_pass,account_writer,account_pass=configure_test_accounts(root_config)
        mysql_port=root_config["port"]
        os.environ["PILOT5_PRIVATE_MYSQL_PORT"]=str(mysql_port)
        tcp_process,web_process,tcp_port,web_port,tcp_log,web_log=launch_services(
            reader_user,reader_pass,writer_user,writer_pass,account_writer,account_pass,username,password,artifacts)
        log_handles.extend([tcp_log,web_log])
        base=f"http://127.0.0.1:{web_port}"
        wait_http(base,web_process)
        result=run_browser_flow(base,username,password,recipes,artifacts)
        connection=mysql.connector.connect(**{**root_config,"database":"goiy_mon_an"})
        try:
            final_counts={name:int(sql_rows(connection,f"SELECT COUNT(*) AS n FROM {name}")[0]["n"])
                          for name in ("recipes","ingredients","recipe_ingredients")}
            remaining=int(sql_rows(connection,"SELECT COUNT(*) AS n FROM v2_ingredients WHERE identity_status='NEEDS_VERIFICATION'")[0]["n"])
            newly_direct=int(sql_rows(connection,"SELECT COUNT(*) AS n FROM v2_ingredients WHERE identity_status='DRAFT' AND canonical_name IN ('Dầu ăn','Muối','Đường','Tiêu đen','Hành tím')")[0]["n"])
            triggers=int(sql_rows(connection,"SELECT COUNT(*) AS n FROM information_schema.triggers WHERE trigger_schema=DATABASE()")[0]["n"])
        finally:connection.close()
        if final_counts!={"recipes":50,"ingredients":50,"recipe_ingredients":252} or triggers!=2 or newly_direct!=5 or remaining!=36:
            raise RuntimeError(f"TEST_ONLY final data integrity mismatch: {final_counts}, triggers={triggers}, enabled_targets={newly_direct}")
        result.update({"backup_restore":"passed","production_ui_readonly":production_ui,
            "baseline":restore_status["counts"],"final_legacy":final_counts,
            "triggers":triggers,"public_ingredients_expected":55,"remaining_unverified_v2":remaining,
            "enabled_targets":newly_direct,"test_url":base,"artifacts":str(artifacts)})
        (artifacts/"result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except Exception as exc:
        message=str(exc).encode("ascii","backslashreplace").decode("ascii")
        print("TEST_ONLY browser run stopped:",type(exc).__name__,message)
        print("artifacts:",str(artifacts))
        return 1
    finally:
        for process in (web_process,tcp_process):
            if process is not None and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        stop_private_mysql(mysql_process,artifacts)
        for stream in log_handles:
            try:stream.close()
            except Exception:pass


if __name__=="__main__":
    raise SystemExit(main())
