"""Start the fixed local demo stack on the existing unified-v3 TEST_ONLY data."""
from __future__ import annotations

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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATABASE = "goiy_v3_quality_final_20261110_test"
MYSQL_PORT = 63900
TCP_PORT = 9000
WEB_PORT = 8000
WEB_HOST = "0.0.0.0"
TCP_HOST = "127.0.0.1"
DATADIR = ROOT / "statics/runtime/mysql-v3-quality-final-20261110"
MYSQLD = Path(r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqld.exe")
RUNTIME = ROOT / "statics/runtime/demo-fixed"
RECIPE_IMAGES = ROOT / "statics/runtime/recipe-images"
ACHIEVEMENT_IMAGES = ROOT / "statics/runtime/achievement-images"


def port_available(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def port_owner(port: int) -> str:
    # netstat remains available in restricted Windows sessions where the
    # CIM-based Get-NetTCPConnection/Win32_Process queries may be denied.
    try:
        result = subprocess.run(["netstat.exe", "-ano"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        pids = set()
        for line in result.stdout.splitlines():
            fields = line.split()
            if (len(fields) >= 5 and fields[0].upper() == "TCP"
                    and fields[3].upper() == "LISTENING"
                    and fields[1].rsplit(":", 1)[-1] == str(port)):
                pids.add(fields[-1])
        if not pids:
            return "listener PID unavailable"
        pid_list = ",".join(sorted(pids, key=int))
        command = (
            "$ids=@(" + ",".join(pids) + "); "
            "foreach($id in $ids){$p=Get-Process -Id $id -ErrorAction SilentlyContinue; "
            "if($p){Write-Output ('PID '+$id+' ('+$p.ProcessName+'; command line unavailable)')} "
            "else{Write-Output ('PID '+$id+' (process name unavailable)')}}"
        )
        details = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
        return details or ", ".join(f"PID {pid} (process details unavailable)" for pid in pid_list.split(","))
    except Exception:
        return "owner details unavailable"


def ensure_demo_ports_free() -> None:
    busy = [port for port in (WEB_PORT, TCP_PORT) if not port_available(port)]
    if busy:
        details = "; ".join(f"{port}: {port_owner(port)}" for port in busy)
        raise RuntimeError(
            "Fixed demo port is already occupied; no process was stopped. " + details
        )


def mysql_connect(database: str | None = None):
    return mysql.connector.connect(
        host="127.0.0.1", port=MYSQL_PORT, user="root", password="",
        database=database, charset="utf8mb4", connection_timeout=3,
    )


def verify_existing_mysql() -> None:
    connection = mysql_connect()
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT @@datadir AS datadir,@@port AS port,CURRENT_USER() AS principal")
        identity = cursor.fetchone()
        if (Path(identity["datadir"]).resolve() != DATADIR.resolve()
                or int(identity["port"]) != MYSQL_PORT
                or not str(identity["principal"]).startswith("root@127.0.0.1")):
            raise RuntimeError("127.0.0.1:63900 is not the configured isolated demo MySQL instance")
        cursor.execute("SHOW DATABASES LIKE %s", (DATABASE,))
        if cursor.fetchone() is None:
            raise RuntimeError(f"The existing TEST_ONLY database {DATABASE} is missing")
    finally:
        connection.close()


def start_mysql() -> tuple[subprocess.Popen | None, bool]:
    if not DATADIR.is_dir() or not (DATADIR / DATABASE).is_dir():
        raise RuntimeError("The existing unified-v3 TEST_ONLY datadir was not found; no database was created")
    if not MYSQLD.is_file():
        raise RuntimeError("MySQL 8 mysqld.exe was not found at the configured local installation")
    if not port_available(MYSQL_PORT):
        verify_existing_mysql()
        return None, False

    RUNTIME.mkdir(parents=True, exist_ok=True)
    error_log = RUNTIME / "mysqld.err"
    stdout_log = (RUNTIME / "mysqld.stdout.log").open("ab")
    args = [
        str(MYSQLD), "--no-defaults", f"--datadir={DATADIR}",
        f"--port={MYSQL_PORT}", "--bind-address=127.0.0.1", "--mysqlx=0",
        "--skip-name-resolve", "--lower_case_table_names=1",
        f"--pid-file={DATADIR / 'demo-fixed.pid'}", f"--log-error={error_log}",
    ]
    process = subprocess.Popen(
        args, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=stdout_log,
        stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError(f"Isolated MySQL stopped during startup; inspect {error_log}")
        try:
            verify_existing_mysql()
            return process, True
        except mysql.connector.Error:
            time.sleep(0.25)
    process.terminate()
    process.wait(timeout=10)
    raise RuntimeError("The existing MySQL TEST_ONLY instance did not start on 127.0.0.1:63900")


def inspect_demo_data() -> dict[str, int | str]:
    connection = mysql_connect(DATABASE)
    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS total,SUM(is_public=1 AND deleted_at IS NULL) AS public "
                       "FROM recipes")
        recipes = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) AS total,SUM(is_active=1) AS active FROM ingredients")
        ingredients = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) AS total FROM recipe_ingredients")
        links = cursor.fetchone()["total"]
        cursor.execute("SHOW TABLES LIKE 'achievement_posts'")
        if cursor.fetchone() is None:
            raise RuntimeError("Achievement tables are missing from the existing TEST_ONLY database")
        return {
            "database": DATABASE,
            "recipes_total": int(recipes["total"]),
            "recipes_public": int(recipes["public"] or 0),
            "ingredients_total": int(ingredients["total"]),
            "ingredients_active": int(ingredients["active"] or 0),
            "recipe_ingredient_links": int(links),
        }
    finally:
        connection.close()


def make_demo_env() -> dict[str, str]:
    from scripts.run_v3_quality_test import make_admin_env

    env = make_admin_env()
    env.update({
        "TCP_HOST": TCP_HOST,
        "TCP_PORT": str(TCP_PORT),
        "TCP_DB_SCHEMA": "unified_v3",
        "TCP_MAX_CONNECTIONS": "4",
        "UNIFIED_SCHEMA_MODE": "1",
        "UNIFIED_MYSQL_HOST": "127.0.0.1",
        "UNIFIED_MYSQL_PORT": str(MYSQL_PORT),
        "UNIFIED_MYSQL_USER": "root",
        "UNIFIED_MYSQL_PASSWORD": "",
        "UNIFIED_MYSQL_DATABASE": DATABASE,
        "UNIFIED_TCP_DB_POOL_SIZE": "4",
        "ADMIN_SESSION_SECRET": secrets.token_urlsafe(48),
        "ADMIN_COOKIE_SECURE": "false",
        "USER_COOKIE_SECURE": "false",
        "RECIPE_IMAGE_STORAGE_DIR": str(RECIPE_IMAGES),
        "ACHIEVEMENT_IMAGE_STORAGE_DIR": str(ACHIEVEMENT_IMAGES),
        "TCP_LOG_PATH": str(RUNTIME / "tcp.jsonl"),
        "FASTAPI_GATEWAY_LOG_PATH": str(RUNTIME / "fastapi.jsonl"),
        "MEAL_PLAN_STATE_DIR": str(RUNTIME / "meal-state"),
    })
    return env


def lan_ipv4_address() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            address = probe.getsockname()[0]
            return address if not address.startswith("127.") else None
    except OSError:
        return None


def main() -> int:
    ensure_demo_ports_free()
    mysql_process = None
    owns_mysql = False
    tcp_server = api_server = None
    tcp_thread = api_thread = None
    try:
        mysql_process, owns_mysql = start_mysql()
        data = inspect_demo_data()
        os.environ.update(make_demo_env())

        from source.server.main import TCPServer, configured_tcp_max_connections
        from source.server.unified_repository import UnifiedMySQLRepository
        from source.web.main import app

        tcp_server = TCPServer(
            TCP_HOST, TCP_PORT, max_connections=configured_tcp_max_connections(),
            repository=UnifiedMySQLRepository.from_env(),
        )
        tcp_thread = threading.Thread(target=tcp_server.serve_forever, name="demo-tcp", daemon=True)
        tcp_thread.start()
        for _ in range(100):
            if not tcp_thread.is_alive():
                raise RuntimeError("TCP Server stopped during startup")
            try:
                with socket.create_connection((TCP_HOST, TCP_PORT), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("TCP Server failed to listen on localhost:9000")

        api_server = uvicorn.Server(uvicorn.Config(
            app, host=WEB_HOST, port=WEB_PORT, log_level="info", access_log=False,
        ))
        api_thread = threading.Thread(target=api_server.run, name="demo-fastapi", daemon=True)
        api_thread.start()
        for _ in range(100):
            if not api_thread.is_alive() or not tcp_thread.is_alive():
                raise RuntimeError("FastAPI or TCP Server exited during startup")
            try:
                with urlopen(f"http://127.0.0.1:{WEB_PORT}/api/health", timeout=1) as response:
                    health = json.loads(response.read().decode("utf-8"))
                    if response.status == 200 and (health.get("data") or {}).get("dataset_version", "").startswith("unified:"):
                        break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("FastAPI health check did not confirm unified-v3 through TCP")

        lan_address = lan_ipv4_address()
        print(json.dumps({
            "status": "ready",
            "database": data,
            "mysql": "127.0.0.1:63900 (loopback)",
            "tcp": "127.0.0.1:9000 (loopback)",
            "web_bind": "0.0.0.0:8000",
            "user_url": "http://127.0.0.1:8000/",
            "admin_url": "http://127.0.0.1:8000/admin",
            "admin_login_url": "http://127.0.0.1:8000/admin/login",
            "lan_ipv4": lan_address,
            "lan_user_url": (f"http://{lan_address}:{WEB_PORT}/" if lan_address else None),
            "lan_admin_url": (f"http://{lan_address}:{WEB_PORT}/admin" if lan_address else None),
            "owns_mysql_process": owns_mysql,
            "stop": "Press Ctrl+C in this window to stop this demo stack",
        }, ensure_ascii=False), flush=True)

        while api_thread.is_alive() and tcp_thread.is_alive():
            time.sleep(1)
        raise RuntimeError("A demo service stopped unexpectedly")
    except KeyboardInterrupt:
        print("Stopping the demo services started by this launcher.", flush=True)
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
        if owns_mysql and mysql_process is not None and mysql_process.poll() is None:
            try:
                connection = mysql_connect(DATABASE)
                connection.cursor().execute("SHUTDOWN")
                connection.close()
                mysql_process.wait(timeout=15)
            except Exception:
                mysql_process.terminate()
                mysql_process.wait(timeout=10)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Demo startup failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
