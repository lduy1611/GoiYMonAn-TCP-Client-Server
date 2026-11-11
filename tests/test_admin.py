import hashlib

import pytest
from fastapi.testclient import TestClient

from source.client.tcp_client import TCPClientError
from source.common.admin_tokens import issue, verify
from source.common.protocol import ProtocolError
from source.database.seed import seed
from source.server.handler import dispatch
from source.server.repository import Repository
from tests.meal_plan_fixtures import running_repository, sqlite_repository
from source.web.main import app


def hash_for(password,salt=b"0123456789abcdef"):
    digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,300_000,dklen=32).hex()
    return f"pbkdf2_sha256$300000${salt.hex()}${digest}"


def test_admin_token_is_signed_expiring_and_audience_bound(monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET","test-only-secret-value-with-at-least-32-bytes")
    token,claims=issue("TEST_ONLY_ADMIN",now=1000,lifetime=60)
    assert verify(token,now=1020)["sub"]=="TEST_ONLY_ADMIN"
    assert verify(token,now=1060) is None
    assert verify(token+"x",now=1020) is None
    assert claims["aud"]=="recipe-admin"


def test_tcp_server_rejects_admin_operations_without_token(tmp_path,monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET","test-only-secret-value-with-at-least-32-bytes")
    path=tmp_path/"admin-test.db";seed(path);repo=Repository(path)
    with pytest.raises(ProtocolError) as exc:
        dispatch(repo,{"version":1,"request_id":"90a91ca7-a54c-4fb8-8c9c-8d7d82f101a8",
                       "op":"ADMIN_DASHBOARD","payload":{}})
    assert exc.value.code=="ADMIN_UNAUTHORIZED"
    token,_=issue("TEST_ONLY_ADMIN")
    reply,_=dispatch(repo,{"version":1,"request_id":"90a91ca7-a54c-4fb8-8c9c-8d7d82f101a8",
        "op":"ADMIN_DASHBOARD","payload":{"admin_token":token}})
    assert reply["ok"] and reply["data"]["recipes_total"]==10


def test_tcp_repository_pool_size_can_be_reduced_for_local_service_slots(monkeypatch):
    from source.server.repository import MySQLRepository
    seen={}
    def capture(self,config=None,pool_size=32):seen["size"]=pool_size
    monkeypatch.setattr(MySQLRepository,"__init__",capture)
    monkeypatch.delenv("TCP_DB_POOL_SIZE",raising=False)
    MySQLRepository.from_env()
    assert seen["size"]==4
    monkeypatch.setenv("TCP_DB_POOL_SIZE","3")
    MySQLRepository.from_env()
    assert seen["size"]==3
    monkeypatch.setenv("TCP_DB_POOL_SIZE","65")
    with pytest.raises(RuntimeError,match="between 1 and 64"):
        MySQLRepository.from_env()


def test_tcp_admin_recipe_list_accepts_valid_publication_filters(tmp_path,monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET","test-only-secret-value-with-at-least-32-bytes")
    repo=Repository(tmp_path/"admin-recipe-filters.db");seed(repo.db_path);token,_=issue("TEST_ONLY_ADMIN")
    payload={"admin_token":token,"query":"TEST_ONLY","limit":10,"offset":0,
             "role":"main","visibility":"hidden","max_minutes":30}
    reply,_=dispatch(repo,{"version":1,"request_id":"90a91ca7-a54c-4fb8-8c9c-8d7d82f101a8",
        "op":"ADMIN_LIST_RECIPES","payload":payload})
    assert reply["ok"] and reply["data"]["total"]==0
    with pytest.raises(ProtocolError) as exc:
        dispatch(repo,{"version":1,"request_id":"90a91ca7-a54c-4fb8-8c9c-8d7d82f101a8",
            "op":"ADMIN_LIST_RECIPES","payload":{**payload,"role":"unverified"}})
    assert exc.value.code=="INVALID_PAYLOAD"


def test_admin_gateway_auth_session_dashboard_and_csrf(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME","TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH",hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET","test-only-secret-value-with-at-least-32-bytes")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE","false")
    calls=[]
    def tcp(self,op,payload,request_id=None):
        calls.append((op,payload))
        if op=="ADMIN_DASHBOARD":
            return {"version":1,"request_id":request_id,"ok":True,"data":{"dataset_version":"TEST_ONLY",
                "recipes_total":50,"ingredients_total":50,"revisions_total":3,"draft_revisions":3,
                "approved_revisions":0,"draft_write_ready":False},"error":None}
        return {"version":1,"request_id":request_id,"ok":True,"data":{"dataset_version":"TEST_ONLY","items":[],"total":0,"limit":20,"offset":0},"error":None}
    monkeypatch.setattr("source.web.main.TCPClient.request",tcp)
    with TestClient(app) as client:
        assert client.get("/api/admin/dashboard").status_code==401
        login=client.post("/api/admin/login",json={"username":"TEST_ONLY_ADMIN","password":"TEST_ONLY_PASSWORD"})
        assert login.status_code==200 and "httponly" in login.headers["set-cookie"].lower()
        session=client.get("/api/admin/session").json()["data"]
        dashboard=client.get("/api/admin/dashboard")
        assert dashboard.status_code==200 and dashboard.json()["data"]["revisions_total"]==3
        assert calls[-1][0]=="ADMIN_DASHBOARD" and verify(calls[-1][1]["admin_token"])["sub"]=="TEST_ONLY_ADMIN"
        filtered=client.get("/api/admin/recipes?query=TEST_ONLY&role=main&visibility=hidden&max_minutes=30")
        assert filtered.status_code==200
        assert calls[-1][0]=="ADMIN_LIST_RECIPES"
        assert {key:calls[-1][1][key] for key in ("role","visibility","max_minutes")}=={
            "role":"main","visibility":"hidden","max_minutes":30}
        assert client.get("/api/admin/recipes?role=unknown").status_code==422
        assert client.post("/api/admin/logout").status_code==403
        assert client.post("/api/admin/logout",headers={"X-CSRF-Token":session["csrf_token"]}).status_code==200


def test_admin_login_fails_closed_when_unconfigured_or_password_is_wrong(monkeypatch):
    for key in ("ADMIN_USERNAME","ADMIN_PASSWORD_HASH","ADMIN_SESSION_SECRET"):
        monkeypatch.delenv(key,raising=False)
    with TestClient(app) as client:
        assert client.post("/api/admin/login",json={"username":"x","password":"y"}).status_code==503
        monkeypatch.setenv("ADMIN_USERNAME","TEST_ONLY_ADMIN")
        monkeypatch.setenv("ADMIN_PASSWORD_HASH",hash_for("TEST_ONLY_PASSWORD"))
        monkeypatch.setenv("ADMIN_SESSION_SECRET","test-only-secret-value-with-at-least-32-bytes")
        assert client.post("/api/admin/login",json={"username":"TEST_ONLY_ADMIN","password":"wrong"}).status_code==401


def test_admin_gateway_reports_tcp_timeout(monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET","test-only-secret-value-with-at-least-32-bytes")
    token,_=issue("TEST_ONLY_ADMIN")
    monkeypatch.setattr("source.web.main.TCPClient.request",lambda *a,**k:(_ for _ in ()).throw(TCPClientError("TIMEOUT")))
    with TestClient(app) as client:
        client.cookies.set("goiy_admin_session",token)
        response=client.get("/api/admin/dashboard")
        assert response.status_code==504 and response.json()["error"]["code"]=="TIMEOUT"


def test_admin_draft_gateway_requires_csrf_and_validates_before_tcp(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME","TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH",hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET","test-only-secret-value-with-at-least-32-bytes")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE","false")
    calls=[]
    monkeypatch.setattr("source.web.main.TCPClient.request",lambda self,op,payload,request_id=None:
        calls.append((op,payload)) or {"version":1,"request_id":request_id,"ok":True,"data":{"status":"DRAFT"},"error":None})
    body={"title":"TEST_ONLY","description":"","instructions":"TEST_ONLY steps","minutes":None,
          "ingredients":[{"ingredient_id":1,"quantity_raw":None,"requirement":"unknown"}]}
    with TestClient(app) as client:
        assert client.post("/api/admin/login",json={"username":"TEST_ONLY_ADMIN","password":"TEST_ONLY_PASSWORD"}).status_code==200
        assert client.post("/api/admin/revisions",json=body).status_code==403
        assert calls==[]
        csrf=client.get("/api/admin/session").json()["data"]["csrf_token"]
        bad={**body,"ingredients":[]}
        assert client.post("/api/admin/revisions",json=bad,headers={"X-CSRF-Token":csrf}).status_code==422
        assert calls==[]
        assert client.post("/api/admin/revisions",json=body,headers={"X-CSRF-Token":csrf}).status_code==200
        assert calls[-1][0]=="ADMIN_CREATE_DRAFT"
        assert calls[-1][1]["admin_token"]


def test_admin_create_distinguishes_expired_session_csrf_and_writer_denial(monkeypatch):
    from source.web.main import http_status_for_error

    monkeypatch.setenv("ADMIN_USERNAME", "TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-only-secret-value-with-at-least-32-bytes")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    body = {"title": "TEST_ONLY auth mapping", "description": "", "instructions": "TEST_ONLY steps",
            "minutes": None, "ingredients": [{"ingredient_id": 1, "quantity_raw": None, "requirement": "unknown"}]}
    calls = []

    def denied_tcp(self, op, payload, request_id=None):
        calls.append((op, payload))
        return {"version": 1, "request_id": request_id, "ok": False, "data": None,
                "error": {"code": "ADMIN_WRITE_DENIED", "message": "TEST_ONLY writer denied"}}

    monkeypatch.setattr("source.web.main.TCPClient.request", denied_tcp)
    assert http_status_for_error("ADMIN_UNAUTHORIZED") == 401
    assert http_status_for_error("ADMIN_CSRF") == 403
    assert http_status_for_error("ADMIN_WRITE_DENIED") == 403
    assert http_status_for_error("ADMIN_WRITE_UNAVAILABLE") == 503
    assert http_status_for_error("DB_ERROR") == 503
    with TestClient(app) as client:
        expired = client.post("/api/admin/revisions", json=body)
        assert expired.status_code == 401 and expired.json()["error"]["code"] == "ADMIN_UNAUTHORIZED"
        assert client.post("/api/admin/login", json={"username": "TEST_ONLY_ADMIN", "password": "TEST_ONLY_PASSWORD"}).status_code == 200
        csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]
        bad_csrf = client.post("/api/admin/revisions", json=body, headers={"X-CSRF-Token": "TEST_ONLY-invalid"})
        assert bad_csrf.status_code == 403 and bad_csrf.json()["error"]["code"] == "ADMIN_CSRF"
        assert calls == []
        denied = client.post("/api/admin/revisions", json=body, headers={"X-CSRF-Token": csrf})
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "ADMIN_WRITE_DENIED"
        assert calls[-1][0] == "ADMIN_CREATE_DRAFT"
        assert calls[-1][1]["admin_token"]


def test_admin_legacy_recipe_gateway_requires_session_csrf_and_valid_payload(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "test-only-secret-value-with-at-least-32-bytes")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    calls=[]
    monkeypatch.setattr("source.web.main.TCPClient.request", lambda self,op,payload,request_id=None:
        calls.append((op,payload)) or {"version":1,"request_id":request_id,"ok":True,
        "data":{"recipe_id":1,"status":"SAVED"},"error":None})
    body={"title":"TEST_ONLY overlay","description":"TEST_ONLY description","instructions":"TEST_ONLY steps",
        "minutes":20,"is_visible":True,"expected_version":"a"*64,
        "ingredients":[{"ingredient_id":1,"quantity":"TEST_ONLY 1","is_required":True}]}
    with TestClient(app) as client:
        assert client.patch("/api/admin/legacy-recipes/1",json=body).status_code==401
        client.post("/api/admin/login",json={"username":"TEST_ONLY_ADMIN","password":"TEST_ONLY_PASSWORD"})
        assert client.patch("/api/admin/legacy-recipes/1",json=body).status_code==403
        csrf=client.get("/api/admin/session").json()["data"]["csrf_token"]
        assert client.patch("/api/admin/legacy-recipes/1",json={**body,"minutes":999},headers={"X-CSRF-Token":csrf}).status_code==422
        assert calls==[]
        response=client.patch("/api/admin/legacy-recipes/1",json=body,headers={"X-CSRF-Token":csrf})
        assert response.status_code==200
        assert calls[-1][0]=="ADMIN_UPDATE_LEGACY_RECIPE"
        assert calls[-1][1]["admin_token"] and calls[-1][1]["recipe_id"]==1


def test_tcp_server_draft_write_stays_unavailable_without_writer(tmp_path,monkeypatch):
    monkeypatch.setenv("ADMIN_SESSION_SECRET","test-only-secret-value-with-at-least-32-bytes")
    monkeypatch.delenv("MYSQL_DRAFT_WRITER_USER",raising=False)
    monkeypatch.delenv("MYSQL_DRAFT_WRITER_PASSWORD",raising=False)
    path=tmp_path/"admin-write-disabled.db";seed(path);repo=Repository(path)
    token,_=issue("TEST_ONLY_ADMIN")
    request={"version":1,"request_id":"90a91ca7-a54c-4fb8-8c9c-8d7d82f101a8","op":"ADMIN_CREATE_DRAFT",
             "payload":{"admin_token":token,"title":"TEST_ONLY","description":"","instructions":"TEST_ONLY",
                        "minutes":None,"ingredients":[{"ingredient_id":1,"quantity_raw":None,"requirement":"unknown"}]}}
    with pytest.raises(ProtocolError) as exc:
        dispatch(repo,request)
    assert exc.value.code=="ADMIN_WRITE_UNAVAILABLE"


def test_tcp_server_maps_missing_writer_privilege_to_denied(tmp_path,monkeypatch):
    import mysql.connector
    monkeypatch.setenv("ADMIN_SESSION_SECRET","test-only-secret-value-with-at-least-32-bytes")
    path=tmp_path/"admin-write-denied.db";seed(path);repo=Repository(path)
    repo.admin_create_draft=lambda *args,**kwargs:(_ for _ in ()).throw(mysql.connector.Error(msg="TEST_ONLY denied",errno=1142))
    token,_=issue("TEST_ONLY_ADMIN")
    request={"version":1,"request_id":"90a91ca7-a54c-4fb8-8c9c-8d7d82f101a8","op":"ADMIN_CREATE_DRAFT",
             "payload":{"admin_token":token,"title":"TEST_ONLY","description":"","instructions":"TEST_ONLY",
                        "minutes":None,"ingredients":[{"ingredient_id":1,"quantity_raw":None,"requirement":"unknown"}]}}
    with pytest.raises(ProtocolError) as exc:
        dispatch(repo,request)
    assert exc.value.code=="ADMIN_WRITE_DENIED"


def test_admin_dashboard_uses_gateway_tcp_server_and_checks_token(tmp_path,monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME","TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH",hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET","test-only-secret-value-with-at-least-32-bytes")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE","false")
    repository=sqlite_repository(tmp_path/"admin-e2e.db")
    with running_repository(repository) as (_,port):
        monkeypatch.setenv("TCP_HOST","127.0.0.1");monkeypatch.setenv("TCP_PORT",str(port))
        with TestClient(app,follow_redirects=False) as client:
            assert client.get("/admin").status_code==303
            assert client.post("/api/admin/login",json={"username":"TEST_ONLY_ADMIN","password":"TEST_ONLY_PASSWORD"}).status_code==200
            page=client.get("/admin")
            assert page.status_code==200 and "admin.js" in page.text
            dashboard=client.get("/api/admin/dashboard")
            assert dashboard.status_code==200 and dashboard.json()["data"]["dataset_version"]=="meal-test-50"
            assert dashboard.json()["data"]["recipes_total"]==50
            listings=client.get("/api/admin/recipes")
            assert listings.status_code==200 and listings.json()["data"]["total"]==0
