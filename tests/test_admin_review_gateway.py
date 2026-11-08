from fastapi.testclient import TestClient

from tests.test_admin import hash_for
from source.web.main import app


def test_review_and_release_gateway_requires_session_csrf_and_validates_payload(monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME","TEST_ONLY_ADMIN")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH",hash_for("TEST_ONLY_PASSWORD"))
    monkeypatch.setenv("ADMIN_SESSION_SECRET","TEST_ONLY secret long enough for session signing")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE","false")
    calls=[]
    def tcp(self,op,payload,request_id=None):
        calls.append((op,payload))
        result={"status":"TEST_ONLY"}
        return {"version":1,"request_id":request_id,"ok":True,"data":result,"error":None}
    monkeypatch.setattr("source.web.main.TCPClient.request",tcp)
    body={"revision_id":2001,"source_kind":"TEST_ONLY","source_title":"TEST_ONLY source",
        "source_url":"https://example.test/TEST_ONLY","publisher":"TEST_ONLY",
        "usage_note":"TEST_ONLY","accessed_on":"2026-11-05","content_locator":"TEST_ONLY section 1",
        "content_evidence":"TEST_ONLY evidence","publication_locator":"TEST_ONLY section 2",
        "publication_evidence":"TEST_ONLY publication","role":"main","role_locator":"TEST_ONLY heading",
        "role_evidence":"TEST_ONLY role"}
    with TestClient(app) as client:
        assert client.post("/api/admin/reviews",json=body).status_code==401
        assert client.post("/api/admin/login",json={"username":"TEST_ONLY_ADMIN","password":"TEST_ONLY_PASSWORD"}).status_code==200
        csrf=client.get("/api/admin/session").json()["data"]["csrf_token"]
        assert client.post("/api/admin/reviews",json=body).status_code==403
        assert client.post("/api/admin/reviews",json={**body,"source_url":"file:///bad"},headers={"X-CSRF-Token":csrf}).status_code==422
        assert calls==[]
        assert client.post("/api/admin/reviews",json=body,headers={"X-CSRF-Token":csrf}).status_code==200
        source={"source_id":7,"evidence_set_id":8,"decision":"APPROVED","rationale":"TEST_ONLY reviewed against source"}
        assert client.post("/api/admin/reviews/source",json=source,headers={"X-CSRF-Token":csrf}).status_code==200
        assert client.post("/api/admin/reviews/approve",json={"revision_id":2001,"rationale":"TEST_ONLY content reviewed"},headers={"X-CSRF-Token":csrf}).status_code==200
        assert client.post("/api/admin/reviews/reject",json={"revision_id":2001,"rationale":"TEST_ONLY rejection reason"},headers={"X-CSRF-Token":csrf}).status_code==200
        assert client.post("/api/admin/releases/publish",json={"release_id":9,"rationale":"TEST_ONLY publish reason"},headers={"X-CSRF-Token":csrf}).status_code==200
        assert client.post("/api/admin/releases/unpublish",json={"recipe_id":4294968297,"rationale":"TEST_ONLY unpublish reason"},headers={"X-CSRF-Token":csrf}).status_code==200
    assert [call[0] for call in calls]==["ADMIN_SUBMIT_REVIEW","ADMIN_REVIEW_SOURCE","ADMIN_APPROVE_RECIPE",
        "ADMIN_REJECT_RECIPE","ADMIN_PUBLISH_RELEASE","ADMIN_UNPUBLISH_RECIPE"]
    assert all("admin_token" in payload for _,payload in calls)
