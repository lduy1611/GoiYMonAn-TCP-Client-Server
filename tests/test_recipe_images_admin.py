from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json

from fastapi.testclient import TestClient
from PIL import Image

from source.common.admin_tokens import issue
from source.common.protocol import ProtocolError
from source.server.handler import dispatch
from source.web import recipe_images
from source.web.main import app
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def encoded_image(kind="PNG", size=(32, 24), color=(30, 100, 60)):
    stream = BytesIO()
    Image.new("RGB", size, color).save(stream, format=kind)
    return stream.getvalue()


def test_image_validation_checks_real_format_size_dimensions_and_normalizes_metadata():
    normalized, meta = recipe_images.validate_image(encoded_image("PNG"), "image/png")
    assert meta["media_type"] == "image/png" and meta["width"] == 32 and meta["height"] == 24
    assert meta["byte_size"] == len(normalized) and meta["sha256"] == sha256(normalized).hexdigest()
    with __import__("pytest").raises(recipe_images.RecipeImageError, match="khớp"):
        recipe_images.validate_image(encoded_image("PNG"), "image/jpeg")
    with __import__("pytest").raises(recipe_images.RecipeImageError, match="không phải ảnh"):
        recipe_images.validate_image(b"TEST_ONLY not an image", "image/png")
    with __import__("pytest").raises(recipe_images.RecipeImageError, match="8000"):
        recipe_images.validate_image(encoded_image("PNG", (5000, 5000)), "image/png")
    with __import__("pytest").raises(recipe_images.RecipeImageError, match="5 MB"):
        recipe_images.validate_image(b"x" * (recipe_images.MAX_UPLOAD_BYTES + 1), "image/png")


def test_private_storage_uses_generated_names_and_rejects_path_traversal(tmp_path):
    data, meta = recipe_images.validate_image(encoded_image("WEBP"), "image/webp")
    key, path = recipe_images.write_image(data, meta["extension"], tmp_path)
    assert recipe_images.KEY_PATTERN.fullmatch(key) and path.is_file()
    assert recipe_images.delete_image(key, tmp_path) and not path.exists()
    with __import__("pytest").raises(recipe_images.RecipeImageError):
        recipe_images.safe_image_path(tmp_path, "..\\secret.jpg")


def test_admin_image_controls_are_embedded_in_recipe_editor_and_responsive():
    template=(ROOT/"source/web/templates/admin.html").read_text(encoding="utf-8")
    script=(ROOT/"source/web/static/admin.js").read_text(encoding="utf-8")
    css=(ROOT/"source/web/static/admin.css").read_text(encoding="utf-8")
    assert 'id="draft-image-file"' in template and 'id="draft-image-title"' in template
    assert "draft-image-save" in script and "draft-image-remove" in script
    assert "@media(max-width:680px){.admin-image-prep{grid-template-columns:1fr;padding:14px}" in css
    assert 'data-admin-view-panel="recipes"' in template


def test_admin_recipe_list_uses_modal_and_tabbed_drawer_without_scroll_jumps():
    template=(ROOT/"source/web/templates/admin.html").read_text(encoding="utf-8")
    script=(ROOT/"source/web/static/admin.js").read_text(encoding="utf-8")
    css=(ROOT/"source/web/static/admin.css").read_text(encoding="utf-8")
    recipes=template[template.index('id="admin-view-recipes"'):template.index('id="admin-detail"')]
    drawer=template[template.index('<dialog id="admin-editor"'):template.index('</dialog>',template.index('<dialog id="admin-editor"'))]
    assert '<dialog id="admin-detail"' in template
    assert '<dialog id="admin-editor"' in template and 'id="admin-editor"' not in recipes
    assert 'id="admin-draft-form"' in drawer and 'id="draft-cancel"' in drawer and 'id="draft-save"' in drawer
    assert 'role="tablist"' in drawer and all(f'id="editor-tab-{tab}"' in drawer for tab in ('info','ingredients','instructions'))
    assert 'id="draft-image-file" type="file"' in drawer and 'id="draft-image-picker" class="button-secondary"' in drawer
    assert 'id="draft-image-save"' in drawer and 'id="draft-image-remove"' in drawer
    assert 'scrollIntoView' not in script
    assert "$('#admin-detail-title').textContent=row.title" in script
    assert "editorDialog.addEventListener('cancel'" in script and "event.target===editorDialog" in script
    assert '.admin-editor-drawer[open]{inset:0;width:100vw;height:100dvh' in css
    assert '.admin-editor-footer' in css


def test_tcp_image_operations_require_admin_and_public_reads_are_visibility_gated(monkeypatch):
    class TestOnlyRepo:
        def connect(self):
            class Connection:
                def close(self):
                    pass
            return Connection()
        def dataset_version(self, _):
            return "TEST_ONLY"
        def admin_set_recipe_image(self, _connection, payload, admin):
            assert "TEST_ONLY" in payload["storage_key"] or recipe_images.KEY_PATTERN.fullmatch(payload["storage_key"])
            return {"recipe_id": payload["recipe_id"], "storage_key": payload["storage_key"],
                    "previous_storage_key": None, "updated_by": admin}
        def public_recipe_image(self, _, recipe_id):
            if recipe_id == 1:
                return {"recipe_id": 1, "storage_key": "a" * 32 + ".png", "media_type": "image/png"}
            return None
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "TEST_ONLY recipe image operation secret 32 bytes")
    repo = TestOnlyRepo()
    request = {"version": 1, "request_id": "90a91ca7-a54c-4fb8-8c9c-8d7d82f101a8", "op": "ADMIN_SET_RECIPE_IMAGE",
               "payload": {"recipe_id": 1, "storage_key": "a"*32+".png", "media_type": "image/png",
                           "byte_size": 12, "width": 2, "height": 2, "sha256": "b"*64}}
    with __import__("pytest").raises(ProtocolError) as unauthenticated:
        dispatch(repo, request)
    assert unauthenticated.value.code == "ADMIN_UNAUTHORIZED"
    token, _ = issue("TEST_ONLY_ADMIN")
    result, _ = dispatch(repo, {**request, "payload": {**request["payload"], "admin_token": token}})
    assert result["ok"] and result["data"]["dataset_version"] == "TEST_ONLY"
    public, _ = dispatch(repo, {**request, "op": "GET_RECIPE_IMAGE", "payload": {"recipe_id": 1}})
    assert public["ok"] and public["data"]["image"]["storage_key"].endswith(".png")
    with __import__("pytest").raises(ProtocolError) as hidden:
        dispatch(repo, {**request, "op": "GET_RECIPE_IMAGE", "payload": {"recipe_id": 2}})
    assert hidden.value.code == "NOT_FOUND"


def test_admin_upload_csrf_normalization_public_image_serve_and_remove_are_test_only(monkeypatch, tmp_path):
    import hashlib

    monkeypatch.setenv("ADMIN_USERNAME", "TEST_ONLY_ADMIN")
    salt = b"0123456789abcdef"
    password = "TEST_ONLY_ADMIN_PASSWORD"
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 300_000, dklen=32).hex()
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", f"pbkdf2_sha256$300000${salt.hex()}${digest}")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "TEST_ONLY image gateway secret 32 bytes minimum")
    monkeypatch.setenv("ADMIN_COOKIE_SECURE", "false")
    monkeypatch.setenv("RECIPE_IMAGE_STORAGE_DIR", str(tmp_path))
    state = {"image": None}

    def tcp(_self, op, payload, request_id=None):
        if op == "ADMIN_SET_RECIPE_IMAGE":
            state["image"] = {key: payload[key] for key in ("storage_key", "media_type", "byte_size", "width", "height", "sha256")}
            data = {"dataset_version": "TEST_ONLY", "recipe_id": payload["recipe_id"],
                    "storage_key": payload["storage_key"], "previous_storage_key": None}
            ok = True
        elif op == "ADMIN_GET_RECIPE_IMAGE":
            data = {"dataset_version": "TEST_ONLY", "recipe_id": payload["recipe_id"], "ready": True,
                    "image": state["image"], "image_url": "/media/recipes/1" if state["image"] else "/static/images/recipes/placeholder.svg"}
            ok = True
        elif op == "GET_RECIPE_IMAGE":
            if payload["recipe_id"] != 1 or not state["image"]:
                return {"version": 1, "request_id": request_id, "ok": False, "data": None,
                        "error": {"code": "NOT_FOUND", "message": "not found"}}
            data = {"dataset_version": "TEST_ONLY", "image": {"recipe_id": 1, **state["image"]}}
            ok = True
        elif op == "ADMIN_REMOVE_RECIPE_IMAGE":
            old = state["image"]["storage_key"] if state["image"] else None
            state["image"] = None
            data = {"dataset_version": "TEST_ONLY", "recipe_id": 1, "removed": old is not None, "previous_storage_key": old}
            ok = True
        else:
            data, ok = {"dataset_version": "TEST_ONLY"}, True
        return {"version": 1, "request_id": request_id, "ok": ok, "data": data, "error": None}

    monkeypatch.setattr("source.web.main.TCPClient.request", tcp)
    with TestClient(app) as client:
        login = client.post("/api/admin/login", json={"username": "TEST_ONLY_ADMIN", "password": password})
        assert login.status_code == 200
        csrf = client.get("/api/admin/session").json()["data"]["csrf_token"]
        image = encoded_image("PNG")
        assert client.post("/api/admin/recipes/1/image", content=image, headers={"Content-Type": "image/png"}).status_code == 403
        uploaded = client.post("/api/admin/recipes/1/image", content=image,
            headers={"Content-Type": "image/png", "X-CSRF-Token": csrf})
        assert uploaded.status_code == 200 and uploaded.json()["data"]["dataset_version"] == "TEST_ONLY"
        key = state["image"]["storage_key"]
        assert (tmp_path / key).is_file()
        metadata = client.get("/api/recipes/1/image")
        assert metadata.status_code == 200 and metadata.json()["data"]["image_url"].startswith("/media/recipes/1?v=")
        served = client.get("/media/recipes/1")
        assert served.status_code == 200 and served.headers["content-type"] == "image/png"
        with Image.open(BytesIO(served.content)) as actual:
            assert actual.size == (32, 24)
        assert client.delete("/api/admin/recipes/1/image", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert not (tmp_path / key).exists()
        assert client.get("/media/recipes/1").status_code == 404
