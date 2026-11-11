"""Focused user-account tests; every database row uses private TEST_ONLY MySQL."""
import json
import socket
import threading
import time
import uuid

import pytest
import mysql.connector
from fastapi.testclient import TestClient

from source.client.tcp_client import TCPClient
from source.common.protocol import ProtocolError
from source.common.user_tokens import issue, verify
from source.database import migrate_v2, v2_admin_schema, v2_schema, v2_user_account_schema
from source.database.setup_user_account_writer import _grant_statements, _validate_account_separation
from source.server import user_accounts
from source.server.handler import dispatch
from source.server.main import TCPServer
from source.server.repository import MySQLRepository, UserAccountConflict, UserAccountUnauthorized
from source.web.main import app
from tests.mysql_v2_fixtures import legacy_hashes, mysql_db, private_mysql, sql


def _install_base(connection):
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


def test_account_passwords_and_session_tokens_are_safe(monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "TEST_ONLY session secret more than 32 chars")
    encoded=user_accounts.hash_password("TEST_ONLY password 1234")
    assert encoded.startswith("pbkdf2_sha256$600000$")
    assert user_accounts.verify_password("TEST_ONLY password 1234",encoded)
    assert not user_accounts.verify_password("wrong password value",encoded)
    token,claims=issue(4294967297,"TEST_ONLY_user")
    assert verify(token)["uid"]==claims["uid"]
    assert verify(token,now=claims["exp"]) is None


def test_registration_payload_is_strict_and_never_accepts_role():
    valid={"username":"TEST_ONLY_User","password":"TEST_ONLY password 1234","password_confirmation":"TEST_ONLY password 1234"}
    normalized=user_accounts.validate_register(valid,"TEST_ONLY")
    assert normalized["normalized_username"]=="test_only_user"
    for invalid in ({**valid,"role":"ADMIN"},{**valid,"password_confirmation":"different"},
                    {**valid,"username":"x"}):
        with pytest.raises(ProtocolError):user_accounts.validate_register(invalid,"TEST_ONLY")


def test_account_writer_grants_are_limited_to_account_table_and_migration_history():
    grants=["GRANT USAGE ON *.* TO 'writer'@'localhost'",
            "GRANT SELECT ON `goiy_mon_an`.`v2_user_accounts` TO 'writer'@'localhost'",
            "GRANT INSERT (`username`, `normalized_username`, `password_hash`) ON `goiy_mon_an`.`v2_user_accounts` TO 'writer'@'localhost'",
            "GRANT UPDATE (`account_status`, `role`, `last_login_at`) ON `goiy_mon_an`.`v2_user_accounts` TO 'writer'@'localhost'",
            "GRANT SELECT ON `goiy_mon_an`.`v2_migration_history` TO 'writer'@'localhost'"]
    MySQLRepository._validate_account_writer_grants(grants,"goiy_mon_an")
    with pytest.raises(Exception):
        MySQLRepository._validate_account_writer_grants(grants+["GRANT SELECT ON `goiy_mon_an`.* TO 'writer'@'localhost'"],"goiy_mon_an")
    with pytest.raises(Exception):
        MySQLRepository._validate_account_writer_grants(grants+["GRANT UPDATE ON `goiy_mon_an`.`v2_user_accounts` TO 'writer'@'localhost'"],"goiy_mon_an")
    with pytest.raises(Exception):
        MySQLRepository._validate_account_writer_grants(grants+["GRANT 'admin_role'@'%' TO 'writer'@'localhost'"],"goiy_mon_an")


def test_writer_bootstrap_grants_touch_only_account_and_migration_metadata():
    statements=_grant_statements()
    assert len(statements)==4
    assert all("v2_user_accounts" in value or "v2_migration_history" in value for value in statements)
    assert all("goiy_user_writer" in value for value in statements)
    assert not any("DELETE" in value or "goiy_app" in value for value in statements)
    _validate_account_separation("goiy_app")
    _validate_account_separation("goiy_admin_writer")
    _validate_account_separation("goiy_migrator")
    with pytest.raises(RuntimeError,match="separate dedicated MySQL account"):
        _validate_account_separation("goiy_user_writer")


def test_user_account_migration_is_additive_and_checked(mysql_db, monkeypatch):
    connection,config=mysql_db
    _install_base(connection)
    original_legacy=legacy_hashes(connection)
    before={next(iter(row.values())) for row in sql(connection,"SHOW TABLES")}
    result=migrate_v2.run_user_account_migration(connection,"apply")
    assert result["user_account_state"]=="APPLIED"
    assert result["context_state"]=="NOT_APPLIED"
    assert result["admin_ingredient_state"]=="NOT_APPLIED"
    assert sql(connection,"SELECT version,checksum,execution_result FROM v2_migration_history WHERE version=%s",
               (v2_user_account_schema.VERSION,))[0]=={
                   "version":v2_user_account_schema.VERSION,"checksum":v2_user_account_schema.checksum(),"execution_result":"APPLIED"}
    after={next(iter(row.values())) for row in sql(connection,"SHOW TABLES")}
    assert after-before=={"v2_user_accounts"}
    assert migrate_v2.check(connection)["user_account_state"]=="APPLIED"
    history=sql(connection,"SELECT version,checksum,schema_hash,execution_result,applied_at FROM v2_migration_history")
    for row in history:row["applied_at"]="TEST_ONLY"
    assert v2_schema.history_is_compatible(history)
    assert legacy_hashes(connection)==original_legacy

    repository=MySQLRepository(config,pool_size=1)
    def writer():return mysql.connector.connect(**{**config,"autocommit":False})
    monkeypatch.setattr(repository,"_account_writer",writer)
    monkeypatch.setattr(repository,"user_account_writer_ready",lambda:True)
    created=repository.user_register(user_accounts.validate_register({
        "username":"TEST_ONLY_person","password":"TEST_ONLY secure passphrase 24","password_confirmation":"TEST_ONLY secure passphrase 24"},"TEST_ONLY"))
    assert created["role"]=="USER" and created["user_id"].isdigit()
    assert "session_token" in created and "password" not in created
    login=repository.user_login(user_accounts.validate_login({"username":"test_only_PERSON","password":"TEST_ONLY secure passphrase 24"},"TEST_ONLY"))
    claims=verify(login["session_token"])
    assert claims["role"]=="USER" and claims["uid"]==int(created["user_id"])
    assert repository.user_session(claims)["username"]=="TEST_ONLY_person"
    with pytest.raises(UserAccountConflict):
        repository.user_register(user_accounts.validate_register({
            "username":"TEST_ONLY_person","password":"TEST_ONLY secure passphrase 24","password_confirmation":"TEST_ONLY secure passphrase 24"},"TEST_ONLY"))
    with pytest.raises(UserAccountUnauthorized):
        repository.user_login(user_accounts.validate_login({"username":"TEST_ONLY_person","password":"incorrect password"},"TEST_ONLY"))
    repository.admin_set_user_status({"user_id":int(created["user_id"]),"account_status":"LOCKED"})
    with pytest.raises(UserAccountUnauthorized):repository.user_session(claims)
    listed=repository.admin_list_users(connection,"TEST_ONLY",20,0)
    assert listed["total"]==1 and listed["items"][0]["account_status"]=="LOCKED"


def test_account_writer_column_grants_allow_registration_and_login(mysql_db,monkeypatch):
    connection,config=mysql_db
    _install_base(connection)
    migrate_v2.run_user_account_migration(connection,"apply")
    writer="test_only_writer_"+uuid.uuid4().hex[:12]
    password="TEST_ONLY_"+uuid.uuid4().hex
    account=f"'{writer}'@'localhost'"
    database=config["database"]
    table=f"`{database}`.`v2_user_accounts`"
    history=f"`{database}`.`v2_migration_history`"
    sql(connection,f"CREATE USER {account} IDENTIFIED BY '{password}'")
    sql(connection,f"GRANT SELECT ON {table} TO {account}")
    sql(connection,f"GRANT INSERT (`username`,`normalized_username`,`password_hash`) ON {table} TO {account}")
    sql(connection,f"GRANT UPDATE (`account_status`,`role`,`last_login_at`) ON {table} TO {account}")
    sql(connection,f"GRANT SELECT ON {history} TO {account}")
    restricted=mysql.connector.connect(**{**config,"user":writer,"password":password,"autocommit":False})
    try:
        cur=restricted.cursor()
        with pytest.raises(mysql.connector.Error) as denied:
            cur.execute("INSERT INTO v2_user_accounts(username,normalized_username,password_hash,role,account_status) VALUES(%s,%s,%s,'USER','ACTIVE')",
                        ("TEST_ONLY_old_insert","test_only_old_insert","TEST_ONLY hash"))
        assert denied.value.errno==1143
        restricted.rollback()
        cur.close()
    finally:restricted.close()
    monkeypatch.setenv("MYSQL_USER_ACCOUNT_WRITER_USER",writer)
    monkeypatch.setenv("MYSQL_USER_ACCOUNT_WRITER_PASSWORD",password)
    repository=MySQLRepository(config,pool_size=1)
    try:
        assert repository.user_account_writer_ready()
        username="TEST_ONLY_"+uuid.uuid4().hex[:12]
        plain_password="TEST_ONLY secure passphrase 24"
        normalized=user_accounts.validate_register({"username":username,"password":plain_password,
            "password_confirmation":plain_password},"TEST_ONLY")
        registered=repository.user_register(normalized)
        assert registered["role"]=="USER"
        stored=sql(connection,"SELECT role,account_status,password_hash FROM v2_user_accounts WHERE user_id=%s",
                   (int(registered["user_id"]),))[0]
        assert stored["role"]=="USER" and stored["account_status"]=="ACTIVE"
        assert user_accounts.verify_password(plain_password,stored["password_hash"])
        assert repository.user_account_writer_ready()
        assert migrate_v2.check(connection)["user_account_state"]=="APPLIED"
        login=repository.user_login(user_accounts.validate_login({"username":username,"password":plain_password},"TEST_ONLY"))
        assert login["user_id"]==registered["user_id"] and login["role"]=="USER"
    finally:
        sql(connection,f"DROP USER IF EXISTS {account}")


def test_user_and_admin_account_flow_through_gateway_and_tcp(mysql_db,monkeypatch):
    connection,config=mysql_db
    _install_base(connection)
    migrate_v2.run_user_account_migration(connection,"apply")
    writer="test_writer_"+uuid.uuid4().hex[:12]
    writer_password="TEST_ONLY_"+uuid.uuid4().hex
    writer_account=f"'{writer}'@'localhost'"
    account_table=f"`{config['database']}`.`v2_user_accounts`"
    history_table=f"`{config['database']}`.`v2_migration_history`"
    sql(connection,f"CREATE USER {writer_account} IDENTIFIED BY '{writer_password}'")
    sql(connection,f"GRANT SELECT ON {account_table} TO {writer_account}")
    sql(connection,f"GRANT INSERT (`username`,`normalized_username`,`password_hash`) ON {account_table} TO {writer_account}")
    sql(connection,f"GRANT UPDATE (`account_status`,`role`,`last_login_at`) ON {account_table} TO {writer_account}")
    sql(connection,f"GRANT SELECT ON {history_table} TO {writer_account}")
    monkeypatch.setenv("MYSQL_USER_ACCOUNT_WRITER_USER",writer)
    monkeypatch.setenv("MYSQL_USER_ACCOUNT_WRITER_PASSWORD",writer_password)
    repository=MySQLRepository(config,pool_size=2)
    monkeypatch.setenv("ADMIN_USERNAME","TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH","pbkdf2_sha256$600000$"+"00"*16+"$"+"00"*32)
    monkeypatch.setenv("ADMIN_SESSION_SECRET","TEST_ONLY account flow signing secret at least 32")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE","false")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0));port=probe.getsockname()[1]
    server=TCPServer("127.0.0.1",port,repository=repository)
    monkeypatch.setattr(server,"_log",lambda **_data:None)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv("TCP_HOST","127.0.0.1");monkeypatch.setenv("TCP_PORT",str(port))
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        try:
            TCPClient("127.0.0.1",port).request("PING",{})
            break
        except Exception:time.sleep(.05)
    else:pytest.fail("TEST_ONLY TCP Server did not start")
    try:
        with TestClient(app) as client:
            assert client.get("/").status_code==200
            assert client.get("/meal-plan").status_code==200
            assert client.get("/account/login").status_code==200
            assert client.get("/account/register").status_code==200
            assert client.get("/account/profile",follow_redirects=False).status_code==303
            assert "Georgia,serif" in client.get("/static/account.css").text
            assert "@media(max-width:520px)" in client.get("/static/account.css").text
            admin_css=client.get("/static/admin.css").text
            assert "@media(max-width:680px)" in admin_css
            assert "@media(max-width:390px)" in admin_css
            assert ".admin-sidebar" in admin_css and ".drawer-open" in admin_css
            assert client.get("/api/admin/users").status_code==401
            registered=client.post("/api/auth/register",json={"username":"TEST_ONLY_flow","password":"TEST_ONLY good password 24","password_confirmation":"TEST_ONLY good password 24"})
            assert registered.status_code==200 and registered.json()["data"]["role"]=="USER"
            assert "session_token" not in registered.text and "password" not in registered.text
            dashboard=repository.admin_dashboard(connection)
            assert dashboard["users_total"]==1 and dashboard["published_total"]==2
            stored=sql(connection,"SELECT password_hash,role,account_status FROM v2_user_accounts WHERE username=%s",("TEST_ONLY_flow",))[0]
            assert stored["password_hash"].startswith("pbkdf2_sha256$") and stored["role"]=="USER" and stored["account_status"]=="ACTIVE"
            assert client.cookies.get("goiy_user_session")
            session=client.get("/api/auth/session").json()["data"]
            assert session["authenticated"] is True and session["username"]=="TEST_ONLY_flow"
            profile=client.get("/account/profile")
            assert profile.status_code==200 and 'id="profile-username"' in profile.text
            assert 'aria-current="page"' in profile.text
            assert client.post("/api/auth/logout",headers={"X-CSRF-Token":"wrong"}).status_code==403
            assert client.post("/api/auth/logout",headers={"X-CSRF-Token":session["csrf_token"]}).status_code==200
            assert not client.cookies.get("goiy_user_session")
            login=client.post("/api/auth/login",json={"username":"TEST_ONLY_flow","password":"TEST_ONLY good password 24"})
            assert login.status_code==200
            user_session=client.get("/api/auth/session").json()["data"]

            # Existing environment-configured Admin authentication stays independent of user accounts.
            from tests.test_admin import hash_for
            monkeypatch.setenv("ADMIN_PASSWORD_HASH",hash_for("TEST_ONLY admin pass"))
            assert client.post("/api/admin/login",json={"username":"TEST_ONLY_ADMIN","password":"TEST_ONLY admin pass"}).status_code==200
            admin_session=client.get("/api/admin/session").json()["data"]
            assert admin_session["username"]=="TEST_ONLY_ADMIN" and admin_session["csrf_token"]
            assert client.post("/api/auth/logout",headers={"X-CSRF-Token":user_session["csrf_token"]}).status_code==200
            assert client.get("/api/auth/session").json()["data"]["authenticated"] is False
            admin_after_user_logout=client.get("/api/admin/session").json()["data"]
            assert admin_after_user_logout["username"]=="TEST_ONLY_ADMIN"
            user_login=client.post("/api/auth/login",json={"username":"TEST_ONLY_flow","password":"TEST_ONLY good password 24"})
            assert user_login.status_code==200
            user_session=client.get("/api/auth/session").json()["data"]
            assert client.get("/api/admin/session").json()["data"]["username"]=="TEST_ONLY_ADMIN"
            assert client.get("/admin").status_code==200
            admin_page=client.get("/admin").text
            for marker in ('data-admin-view="overview"','data-admin-view="recipes"',
                           'data-admin-view="ingredients"','data-admin-view="users"',
                           'id="admin-sidebar-toggle"','id="stat-published"',
                           'Quản lý món ăn','id="admin-recipe-role"','id="admin-recipe-visibility"',
                           'id="admin-recipe-max-minutes"','id="draft-image-file"'):
                assert marker in admin_page
            assert 'data-admin-view="review"' not in admin_page
            csrf=client.get("/api/admin/session").json()["data"]["csrf_token"]
            listed=client.get("/api/admin/users?query=TEST_ONLY&limit=10&offset=0").json()
            assert listed["data"]["total"]==1 and listed["data"]["account_admin_ready"] is True
            uid=listed["data"]["items"][0]["user_id"]
            promoted=client.patch(f"/api/admin/users/{uid}/role",json={"role":"ADMIN"},headers={"X-CSRF-Token":csrf})
            assert promoted.status_code==200
            client.post("/api/auth/logout",headers={"X-CSRF-Token":user_session["csrf_token"]})
            login=client.post("/api/auth/login",json={"username":"TEST_ONLY_flow","password":"TEST_ONLY good password 24"})
            assert login.json()["data"]["role"]=="ADMIN"
            assert client.get("/admin").status_code==200
            try:
                dispatch(repository,{"version":1,"request_id":str(uuid.uuid4()),"op":"ADMIN_LIST_USERS",
                    "payload":{"query":"TEST_ONLY","limit":20,"offset":0,"admin_token":client.cookies.get("goiy_admin_session")}})
            except Exception as exc:
                pytest.fail(f"TEST_ONLY account-admin TCP dispatch raised {type(exc).__name__}: {exc}")
            admin_list=client.get("/api/admin/users?query=TEST_ONLY")
            assert admin_list.status_code==200,admin_list.text

            # Static environment-configured Admin remains available to lock the promoted account.
            client.post("/api/admin/logout",headers={"X-CSRF-Token":client.get("/api/admin/session").json()["data"]["csrf_token"]})
            assert client.post("/api/admin/login",json={"username":"TEST_ONLY_ADMIN","password":"TEST_ONLY admin pass"}).status_code==200
            csrf=client.get("/api/admin/session").json()["data"]["csrf_token"]
            locked=client.patch(f"/api/admin/users/{uid}/status",json={"account_status":"LOCKED"},headers={"X-CSRF-Token":csrf})
            assert locked.status_code==200
            assert client.get("/api/auth/session").status_code==401
    finally:
        server.shutdown();thread.join(timeout=5)
        sql(connection,f"DROP USER IF EXISTS {writer_account}")

