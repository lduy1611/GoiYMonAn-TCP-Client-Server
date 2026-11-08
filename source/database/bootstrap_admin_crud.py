"""One-time local bootstrap for project-scoped MySQL and Admin access.

Prompts only for the local MySQL root password. Random database/Admin secrets
are stored in Windows Credential Manager; the draft writer secret, Admin hash,
and session secret are stored in the ignored project .env.
"""
from __future__ import annotations

import getpass
import hashlib
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

import mysql.connector
from dotenv import load_dotenv

from source.database import v2_admin_schema, v2_schema
from source.database.codex_mysql import (
    ADMIN_TARGET, CODEX_TARGET, CODEX_USER, connect_codex, store_secret, verify_credential_store,
)
from source.server.repository import mysql_config_from_env
from source.web.setup_admin import REVIEW_GRANTS, WRITER, _write_env, validate_writer_grants, _writer_connection

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "statics/runtime/backups/goiy_mon_an-before-admin-003-20261105-154519-5f588139062143d99a9a8116a8a37316.sql"
BACKUP_SHA256 = "5502c1a3fcd8f5211553c5e25ad3bc4195ed8757323f7f02f0c68a6162915603"
ROUNDS = 600_000


def _mysql_literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _check_env_writable():
    fd,path=tempfile.mkstemp(prefix=".admin-bootstrap-check-",dir=ROOT)
    os.close(fd)
    os.unlink(path)


def _grants():
    return [
        "GRANT SELECT (id) ON goiy_mon_an.v2_ingredients TO 'goiy_admin_writer'@'localhost'",
        "GRANT INSERT (id, canonical_name, normalized_name) ON goiy_mon_an.v2_ingredients TO 'goiy_admin_writer'@'localhost'",
        "GRANT INSERT (legacy_ingredient_id) ON goiy_mon_an.v2_ingredients TO 'goiy_admin_writer'@'localhost'",
        "GRANT SELECT (id), INSERT (id, origin_kind, author_ref) ON goiy_mon_an.v2_recipes TO 'goiy_admin_writer'@'localhost'",
        "GRANT SELECT (id, status, content_review_id, servings_review_id), INSERT (id, recipe_id, revision_no, title, description, instructions, minutes), UPDATE (title, description, instructions, minutes) ON goiy_mon_an.v2_recipe_revisions TO 'goiy_admin_writer'@'localhost'",
        "GRANT SELECT (revision_id) ON goiy_mon_an.v2_release_recipes TO 'goiy_admin_writer'@'localhost'",
        "GRANT SELECT (revision_id, status, quantity_review_id, scaling_review_id), INSERT (revision_id, line_no, ingredient_id, quantity_raw, amount_kind, requirement, purpose, measurement_basis), DELETE ON goiy_mon_an.v2_recipe_ingredient_lines TO 'goiy_admin_writer'@'localhost'",
    ] + REVIEW_GRANTS


def _preflight(connection):
    cursor=connection.cursor()
    try:
        cursor.execute("SELECT DATABASE(),CURRENT_USER(),VERSION()")
        database,principal,version=cursor.fetchone()
        if database!="goiy_mon_an" or str(principal).split("@",1)[0]!="root":
            raise RuntimeError("Root login did not resolve to the expected local target")
        if not str(version).startswith("8."):
            raise RuntimeError("Bootstrap expects the configured local MySQL 8 instance")
        cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
        grants=[row[0] for row in cursor.fetchall()]
        grant_text=" ".join(grants).upper()
        if not ("ALL PRIVILEGES" in grant_text or "CREATE USER" in grant_text):
            raise RuntimeError("Root account lacks CREATE USER")
        if not ("WITH GRANT OPTION" in grant_text or "ALL PRIVILEGES" in grant_text):
            raise RuntimeError("Root account lacks GRANT OPTION")
        cursor.execute("SELECT version,checksum,execution_result FROM v2_migration_history")
        history={row[0]:row[1:] for row in cursor.fetchall()}
        if set(history)!={v2_schema.VERSION,v2_admin_schema.VERSION}:
            raise RuntimeError("Expected migration 001 and 003 only; 002 must remain unapplied")
        if history[v2_schema.VERSION]!=(v2_schema.checksum(),"APPLIED"):
            raise RuntimeError("Migration 001 is not valid and APPLIED")
        if history[v2_admin_schema.VERSION]!=(v2_admin_schema.checksum(),"APPLIED"):
            raise RuntimeError("Migration 003 is not valid and APPLIED")
        cursor.execute("SHOW COLUMNS FROM v2_recipe_revisions LIKE 'description'")
        column=cursor.fetchone()
        if not column or str(column[1]).lower()!="varchar(1000)" or column[2]!="NO" or column[4]!="":
            raise RuntimeError("Description column does not match migration 003")
        expected=(('recipes','SELECT COUNT(*) FROM recipes',50),
                  ('ingredients','SELECT COUNT(*) FROM ingredients',50),
                  ('recipe_ingredients','SELECT COUNT(*) FROM recipe_ingredients',252))
        for _,query,count in expected:
            cursor.execute(query)
            if int(cursor.fetchone()[0])!=count:
                raise RuntimeError("Legacy row counts differ from the protected baseline")
        cursor.execute("SELECT COUNT(*) FROM v2_recipe_revisions")
        if int(cursor.fetchone()[0])!=9:
            raise RuntimeError("Revision count differs from the protected baseline")
        cursor.execute("SELECT COUNT(*) FROM information_schema.triggers WHERE trigger_schema=DATABASE()")
        if int(cursor.fetchone()[0])!=2:
            raise RuntimeError("Trigger count differs from the protected baseline")
        cursor.execute("SELECT COUNT(*) FROM mysql.user WHERE user=%s AND host='localhost'",(WRITER,))
        writer_exists=bool(cursor.fetchone()[0])
        cursor.execute("SELECT COUNT(*) FROM mysql.role_edges WHERE TO_USER=%s AND TO_HOST='localhost'",(WRITER,))
        if int(cursor.fetchone()[0]):
            raise RuntimeError("Writer has role memberships; refusing to leave unreviewed inherited privileges")
        return principal,writer_exists
    finally:
        cursor.close()


def _set_writer(connection,password,exists):
    cursor=connection.cursor()
    account="'goiy_admin_writer'@'localhost'"
    try:
        if exists:
            cursor.execute(f"REVOKE ALL PRIVILEGES, GRANT OPTION FROM {account}")
            cursor.execute(f"ALTER USER {account} IDENTIFIED BY {_mysql_literal(password)}")
        else:
            cursor.execute(f"CREATE USER {account} IDENTIFIED BY {_mysql_literal(password)}")
        for statement in _grants():
            cursor.execute(statement)
    finally:
        cursor.close()


def _set_codex_admin(connection,password,exists):
    cursor=connection.cursor()
    account="'goiy_codex_admin'@'localhost'"
    try:
        if exists:
            cursor.execute("SELECT COUNT(*) FROM mysql.role_edges WHERE TO_USER='goiy_codex_admin' AND TO_HOST='localhost'")
            if int(cursor.fetchone()[0]):
                raise RuntimeError("Codex MySQL account has role memberships; refusing inherited privileges")
            cursor.execute(f"REVOKE ALL PRIVILEGES, GRANT OPTION FROM {account}")
            cursor.execute(f"ALTER USER {account} IDENTIFIED BY {_mysql_literal(password)}")
        else:
            cursor.execute(f"CREATE USER {account} IDENTIFIED BY {_mysql_literal(password)}")
        cursor.execute(f"GRANT CREATE USER ON *.* TO {account}")
        cursor.execute(f"GRANT ALL PRIVILEGES ON goiy_mon_an.* TO {account} WITH GRANT OPTION")
    finally:
        cursor.close()


def _port_open(port):
    import socket
    with socket.socket() as sock:
        sock.settimeout(.25)
        return sock.connect_ex(("127.0.0.1",port))==0


def _owned_listener(port,expected_role):
    """Return a listener PID only after verifying this repository owns it."""
    root_text=str(ROOT).replace("'","''")
    command=(
        "$ErrorActionPreference='Stop'; "
        f"$c=Get-NetTCPConnection -State Listen -LocalPort {int(port)} -ErrorAction SilentlyContinue; "
        "$rows=@(foreach($x in $c){$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$x.OwningProcess); "
        "$r=if($p.CommandLine -match 'source\\.server\\.main'){'TCP'} "
        "elseif($p.CommandLine -match 'uvicorn source\\.web\\.main:app'){'FASTAPI'} else {'OTHER'}; "
        f"$owned=($p.Name -in @('python.exe','pythonw.exe') -and $p.CommandLine.Contains('{root_text}')); "
        "[pscustomobject]@{pid=$x.OwningProcess;role=$r;owned=$owned}}); $rows | ConvertTo-Json -Compress"
    )
    result=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",command],
                          capture_output=True,text=True,timeout=10)
    if result.returncode:raise RuntimeError("Could not safely identify local service port owners")
    output=result.stdout.strip()
    if not output:return None
    try:
        rows=json.loads(output)
        if isinstance(rows,dict):rows=[rows]
    except json.JSONDecodeError:
        raise RuntimeError("Could not safely parse local service ownership") from None
    if len(rows)!=1 or rows[0].get("role")!=expected_role or not rows[0].get("owned"):
        raise RuntimeError(f"Port {port} is occupied by a process not verified as this project's {expected_role} service")
    return int(rows[0]["pid"])


def _restart_project_services():
    listeners=[]
    for port,role in ((9000,"TCP"),(8000,"FASTAPI")):
        if _port_open(port):listeners.append((port,role,_owned_listener(port,role)))
    # Verify both owners before terminating either service.
    if any(pid is None for _,_,pid in listeners):
        raise RuntimeError("A project service listener could not be identified safely")
    for _,_,pid in listeners:
        subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",
                        f"Stop-Process -Id {pid} -Force"],check=True,capture_output=True,timeout=10)
    deadline=time.monotonic()+10
    while any(_port_open(port) for port,_,_ in listeners) and time.monotonic()<deadline:time.sleep(.2)
    if any(_port_open(port) for port,_,_ in listeners):
        raise RuntimeError("Previous project service did not release its port")


def _http(opener,method,path,payload=None,headers=None,allow_error=False):
    body=None if payload is None else json.dumps(payload,ensure_ascii=False).encode("utf-8")
    request=Request("http://127.0.0.1:8000"+path,data=body,method=method,headers={
        "Content-Type":"application/json",**(headers or {})})
    try:
        with opener.open(request,timeout=8) as response:
            return response.status,json.loads(response.read())
    except HTTPError as exc:
        data=json.loads(exc.read())
        if allow_error:return exc.code,data
        error=data.get("error") if isinstance(data,dict) else None
        code=error.get("code") if isinstance(error,dict) else None
        message=error.get("message") if isinstance(error,dict) else None
        detail=f"{code}: {message}" if code and message else str(code or "unexpected error")
        raise RuntimeError(f"Admin HTTP smoke test failed at {path}: {exc.code} ({detail})") from None
    except (URLError,TimeoutError) as exc:
        raise RuntimeError(f"Admin HTTP service unavailable at {path}: {type(exc).__name__}") from None


def _wait_tcp(client,process):
    from source.client.tcp_client import TCPClientError
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        if process.poll() is not None: raise RuntimeError("TCP Server exited during startup")
        try:
            response=client.request("PING",{})
            if response.get("ok"):return
        except TCPClientError:
            time.sleep(.2)
    raise RuntimeError("TCP Server did not become ready")


def _start_services_and_smoke(admin_username,admin_password,writer_password,invalid_ingredient_id):
    _restart_project_services()
    runtime=ROOT/"statics/runtime"/("admin-crud-bootstrap-"+time.strftime("%Y%m%dT%H%M%S",time.gmtime()))
    runtime.mkdir(parents=True,exist_ok=True)
    child_env=os.environ.copy()
    child_env.update({"TCP_HOST":"127.0.0.1","TCP_PORT":"9000",
                      "TCP_LOG_PATH":str(runtime.relative_to(ROOT)/"tcp_server.jsonl"),
                      "ADMIN_COOKIE_SECURE":"false",
                      "MYSQL_DRAFT_WRITER_USER":WRITER,"MYSQL_DRAFT_WRITER_PASSWORD":writer_password,
                      "ADMIN_USERNAME":admin_username})
    flags=getattr(subprocess,"DETACHED_PROCESS",0)|getattr(subprocess,"CREATE_NO_WINDOW",0)
    tcp_log=(runtime/"tcp-process.log").open("a",encoding="utf-8")
    tcp=subprocess.Popen([sys.executable,"-m","source.server.main"],cwd=ROOT,env=child_env,
                         stdin=subprocess.DEVNULL,stdout=tcp_log,stderr=subprocess.STDOUT,creationflags=flags)
    web=None;web_log=None
    try:
        from source.client.tcp_client import TCPClient
        _wait_tcp(TCPClient("127.0.0.1",9000),tcp)
        web_log=(runtime/"web-process.log").open("a",encoding="utf-8")
        web=subprocess.Popen([sys.executable,"-m","uvicorn","source.web.main:app","--host","127.0.0.1","--port","8000"],
                             cwd=ROOT,env=child_env,stdin=subprocess.DEVNULL,stdout=web_log,
                             stderr=subprocess.STDOUT,creationflags=flags)
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            if web.poll() is not None:raise RuntimeError("FastAPI exited during startup")
            try:
                status,_=_http(build_opener(),"GET","/api/health")
                if status==200:break
            except Exception:time.sleep(.2)
        else:raise RuntimeError("FastAPI did not become ready")
        opener=build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))
        status,_=_http(opener,"POST","/api/admin/login",{"username":admin_username,"password":admin_password})
        if status!=200:raise RuntimeError("Admin login smoke test failed")
        _,session=_http(opener,"GET","/api/admin/session")
        csrf=session["data"]["csrf_token"]
        _,dashboard=_http(opener,"GET","/api/admin/dashboard")
        if dashboard["data"].get("draft_write_ready") is not True:
            raise RuntimeError("Admin dashboard does not report draft writes ready")
        _,ingredients=_http(opener,"GET","/api/admin/ingredients?limit=1")
        if not ingredients["data"]["items"]:raise RuntimeError("No v2 ingredient available for a TEST_ONLY draft")
        iid=int(ingredients["data"]["items"][0]["ingredient_id"])
        stamp=time.strftime("%Y%m%dT%H%M%SZ",time.gmtime())+"_"+secrets.token_hex(3)
        title="TEST_ONLY_ADMIN_CRUD_"+stamp
        payload={"title":title,"description":"TEST_ONLY Admin CRUD smoke record; not a verified recipe.",
                 "instructions":"TEST_ONLY smoke test only. Do not cook or publish.","minutes":1,
                 "ingredients":[{"ingredient_id":iid,"quantity_raw":"TEST_ONLY no verified amount","requirement":"unknown"}]}
        _,prior=_http(opener,"GET","/api/admin/recipes?query=TEST_ONLY_ADMIN_CRUD_&limit=50&offset=0")
        reusable=next((item for item in prior["data"]["items"]
                       if str(item.get("title","")).startswith("TEST_ONLY_ADMIN_CRUD_")
                       and item.get("status")=="DRAFT"),None)
        if reusable:
            revision_id=int(reusable["revision_id"])
            _,created=_http(opener,"GET",f"/api/admin/revisions/{revision_id}")
            if created["data"].get("status")!="DRAFT":
                raise RuntimeError("Existing TEST_ONLY record is not a DRAFT; refusing to overwrite")
            _,updated=_http(opener,"PATCH",f"/api/admin/revisions/{revision_id}",payload,{"X-CSRF-Token":csrf})
        else:
            _,created=_http(opener,"POST","/api/admin/revisions",payload,{"X-CSRF-Token":csrf})
            revision_id=int(created["data"]["revision_id"])
        _,readback=_http(opener,"GET",f"/api/admin/revisions/{revision_id}")
        if readback["data"]["title"]!=title or readback["data"]["status"]!="DRAFT":
            raise RuntimeError("Created DRAFT did not survive detail reload")
        updated_title=title+"_EDITED"
        payload["title"]=updated_title
        payload["description"]+=" Updated once."
        _,updated=_http(opener,"PATCH",f"/api/admin/revisions/{revision_id}",payload,{"X-CSRF-Token":csrf})
        if updated["data"]["status"]!="DRAFT":raise RuntimeError("Edit response was not DRAFT")
        _,readback=_http(opener,"GET",f"/api/admin/revisions/{revision_id}")
        if readback["data"]["title"]!=updated_title or readback["data"]["status"]!="DRAFT":
            raise RuntimeError("Edited DRAFT did not survive reload")
        _,search=_http(opener,"POST","/api/search",{"query":updated_title,"ingredient_ids":[],"excluded_ids":[],"limit":20,"offset":0})
        if any(item.get("title")==updated_title for item in search["data"]["items"]):
            raise RuntimeError("DRAFT unexpectedly appeared in public search")
        from source.common.catalog_ids import v2_public_id
        public_id=(int(reusable["recipe_id"]) if reusable
                   else v2_public_id(int(created["data"]["recipe_id"])))
        status,_=_http(opener,"GET",f"/api/recipes/{public_id}",allow_error=True)
        if status!=404:raise RuntimeError("DRAFT was unexpectedly visible through public recipe detail")
        _,plan=_http(opener,"POST","/api/meal-plan/v2",{"people":4})
        items=((plan.get("data") or {}).get("plan") or {}).get("items") or []
        if any(int(item["recipe_id"])==public_id for item in items):
            raise RuntimeError("DRAFT unexpectedly appeared in a public meal plan")
        # Verify the SQL transaction rolls back when an ingredient ID is invalid.
        bad={**payload,"title":"TEST_ONLY_ROLLBACK_"+stamp,
             "ingredients":[{"ingredient_id":invalid_ingredient_id,"quantity_raw":None,"requirement":"unknown"}]}
        status,_=_http(opener,"POST","/api/admin/revisions",bad,{"X-CSRF-Token":csrf},allow_error=True)
        if status!=422:
            body_error=_["error"] if isinstance(_,dict) else None
            code=body_error.get("code") if isinstance(body_error,dict) else "unknown"
            raise RuntimeError(f"Invalid ingredient was rejected with unexpected status {status} ({code})")
        _,rollback_list=_http(opener,"GET","/api/admin/recipes?query="+bad["title"])
        if int(rollback_list["data"]["total"])!=0:
            raise RuntimeError("Failed create left a partial revision behind")
        bad_edit={**bad,"title":"TEST_ONLY_FAILED_EDIT_"+stamp}
        status,_=_http(opener,"PATCH",f"/api/admin/revisions/{revision_id}",bad_edit,
                       {"X-CSRF-Token":csrf},allow_error=True)
        if status!=422:raise RuntimeError("Invalid edit did not fail with 422")
        _,after_failed_edit=_http(opener,"GET",f"/api/admin/revisions/{revision_id}")
        if after_failed_edit["data"]["title"]!=updated_title:
            raise RuntimeError("Failed edit did not roll back the existing DRAFT")
        print("TCP PING, Admin login, create/edit/reload, invalid-input rollback, public search/detail/meal-plan checks passed.")
        print("TEST_ONLY draft:",updated_title,"revision:",revision_id)
        print("Services remain running on 127.0.0.1:9000 and 127.0.0.1:8000.")
        return tcp,web
    except Exception:
        for process in (web,tcp):
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill()
        raise
    finally:
        tcp_log.close()
        if web_log:web_log.close()


_CURRENT_STEP = "not started"


def main():
    global _CURRENT_STEP
    _CURRENT_STEP="local preflight and verified backup"
    load_dotenv(ROOT/".env")
    _check_env_writable()
    verify_credential_store()
    if not BACKUP.is_file():
        raise RuntimeError("Verified pre-migration backup is missing")
    from hashlib import sha256
    if sha256(BACKUP.read_bytes()).hexdigest()!=BACKUP_SHA256:
        raise RuntimeError("Verified backup checksum changed; refusing account/schema changes")

    _CURRENT_STEP="hidden root authentication"
    root_password=getpass.getpass("Nhap mat khau MySQL root (an): ")
    if not root_password:
        raise RuntimeError("Empty root password; no changes were made")
    db_config=mysql_config_from_env()
    if (db_config["host"],int(db_config["port"]),db_config["database"])!=("127.0.0.1",3306,"goiy_mon_an"):
        raise RuntimeError("Configured database target differs from the approved local database")
    root_config={**db_config,"user":"root","password":root_password,"autocommit":True}
    connection=mysql.connector.connect(**root_config)
    writer_password=secrets.token_urlsafe(36)
    codex_password=secrets.token_urlsafe(48)
    new_admin_password=secrets.token_urlsafe(24)
    admin_username=os.getenv("ADMIN_USERNAME") or "admin"
    salt=secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac("sha256",new_admin_password.encode("utf-8"),salt,ROUNDS,dklen=32)
    password_hash=f"pbkdf2_sha256${ROUNDS}${salt.hex()}${digest.hex()}"
    session_secret=secrets.token_urlsafe(48)
    try:
        _CURRENT_STEP="root grants, schema version, and protected row-count preflight"
        principal,writer_exists=_preflight(connection)
        cursor=connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM mysql.user WHERE user=%s AND host='localhost'",(CODEX_USER,))
        codex_exists=bool(cursor.fetchone()[0])
        if codex_exists:
            cursor.execute("SELECT COUNT(*) FROM mysql.role_edges WHERE TO_USER=%s AND TO_HOST='localhost'",(CODEX_USER,))
            if int(cursor.fetchone()[0]):
                raise RuntimeError("Codex account has role memberships; no MySQL accounts were changed")
        cursor.execute("SELECT VERSION()")
        mysql_version=str(cursor.fetchone()[0])
        cursor.execute("SHOW DATABASES")
        databases=[str(row[0]) for row in cursor.fetchall()]
        cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
        root_grants=[str(row[0]) for row in cursor.fetchall()]
        cursor.close()

        _CURRENT_STEP="creating or updating the project-scoped Codex and Admin writer accounts"
        _set_writer(connection,writer_password,writer_exists)
        _set_codex_admin(connection,codex_password,codex_exists)
    finally:
        connection.close()

    # Persist generated credentials before post-create checks, so a failed check
    # can be diagnosed/retried without losing the only generated passwords.
    _CURRENT_STEP="storing generated credentials locally"
    store_secret(CODEX_TARGET,codex_password,CODEX_USER)
    store_secret(ADMIN_TARGET,new_admin_password,admin_username)
    _write_env({
        "MYSQL_DRAFT_WRITER_USER":WRITER,
        "MYSQL_DRAFT_WRITER_PASSWORD":writer_password,
        "ADMIN_USERNAME":admin_username,
        "ADMIN_PASSWORD_HASH":password_hash,
        "ADMIN_SESSION_SECRET":session_secret,
        "ADMIN_COOKIE_SECURE":"false",
    })

    _CURRENT_STEP="verifying writer authentication and least-privilege grants"
    verified,writer_principal=_writer_connection(writer_password)
    cursor=verified.cursor()
    cursor.execute("SELECT COALESCE(MAX(id),0)+1 FROM v2_ingredients")
    invalid_ingredient_id=int(cursor.fetchone()[0])
    cursor.close()
    verified.close()

    _CURRENT_STEP="verifying Codex credential and grant scope"
    codex_connection=connect_codex()
    codex_cursor=codex_connection.cursor()
    codex_cursor.execute("SELECT CURRENT_USER(),DATABASE(),VERSION()")
    codex_principal,codex_database,codex_version=codex_cursor.fetchone()
    codex_cursor.execute("SHOW DATABASES")
    codex_databases=[str(row[0]) for row in codex_cursor.fetchall()]
    codex_cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
    codex_grants=[str(row[0]) for row in codex_cursor.fetchall()]
    codex_cursor.close()
    codex_connection.close()
    if str(codex_principal).split("@",1)[0]!=CODEX_USER or codex_database!="goiy_mon_an":
        raise RuntimeError("Codex account authenticated against an unexpected principal or database")
    from source.database.codex_mysql import validate_codex_grants
    validate_codex_grants(codex_grants)

    print("MySQL version:",mysql_version)
    print("Databases visible to root:",", ".join(databases))
    print("Root grants:")
    for grant in root_grants:print(" ",grant)
    print("Databases visible to Codex account:",", ".join(codex_databases))
    print("Codex grants:")
    for grant in codex_grants:print(" ",grant)
    print("Root authenticated as:",principal)
    print("Codex account verified as:",codex_principal)
    print("Writer verified as:",writer_principal)
    print("Admin username:",admin_username)
    print("Generated credentials persisted locally; no password was printed.")
    print("Retrieve Admin password locally with: python -m source.database.codex_mysql show-admin-password")
    print("Migration 002 was not run; protected legacy counts were checked before account changes.")
    for key,value in {"MYSQL_DRAFT_WRITER_USER":WRITER,"MYSQL_DRAFT_WRITER_PASSWORD":writer_password,
                      "ADMIN_USERNAME":admin_username,"ADMIN_PASSWORD_HASH":password_hash,
                      "ADMIN_SESSION_SECRET":session_secret,"ADMIN_COOKIE_SECURE":"false"}.items():
        os.environ[key]=value
    load_dotenv(ROOT/".env",override=True)
    _CURRENT_STEP="restarting project services and running Admin CRUD/publication smoke tests"
    _start_services_and_smoke(admin_username,new_admin_password,writer_password,invalid_ingredient_id)
    return 0


if __name__=="__main__":
    try:
        raise SystemExit(main())
    except mysql.connector.Error as exc:
        print(f"Bootstrap stopped at {_CURRENT_STEP}: MySQL connector error code {exc.errno}; no password was logged.")
        raise SystemExit(1)
    except (RuntimeError,OSError,ValueError) as exc:
        # Our RuntimeError messages are deliberately credential-free; OSError
        # details are reduced to type/code to avoid leaking process context.
        detail = str(exc) if isinstance(exc, RuntimeError) else f"{type(exc).__name__} code {getattr(exc,'winerror',None) or getattr(exc,'errno',None)}"
        print(f"Bootstrap stopped at {_CURRENT_STEP}: {detail}")
        raise SystemExit(1)
