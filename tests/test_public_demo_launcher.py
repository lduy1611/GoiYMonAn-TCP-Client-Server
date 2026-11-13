"""Portable launcher must preserve local configuration and existing uploads."""
import hashlib
import json

import pytest

from scripts import run_public_demo as launcher


def test_public_images_are_verified_and_existing_uploads_are_not_overwritten(tmp_path, monkeypatch):
    package = tmp_path / "data/demo"
    images = package / "recipe-images"
    images.mkdir(parents=True)
    key = "a" * 32 + ".webp"
    content = b"TEST_ONLY public fixture"
    (images / key).write_bytes(content)
    (package / "catalog.sql").write_bytes(b"TEST_ONLY SQL")
    manifest = {"catalog_sha256": hashlib.sha256(b"TEST_ONLY SQL").hexdigest(), "images": [
        {"path": "recipe-images/" + key, "sha256": hashlib.sha256(content).hexdigest()}]}
    (package / "manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    runtime = tmp_path / "runtime"
    env = {"RECIPE_IMAGE_STORAGE_DIR": str(runtime)}
    launcher.prepare_images(env)
    assert (runtime / key).read_bytes() == content
    (runtime / key).write_bytes(b"TEST_ONLY existing local upload")
    launcher.prepare_images(env)
    assert (runtime / key).read_bytes() == b"TEST_ONLY existing local upload"
    (images / key).write_bytes(b"TEST_ONLY corrupt package")
    with pytest.raises(RuntimeError, match="checksum"):
        launcher.prepare_images(env)
    assert (runtime / key).read_bytes() == b"TEST_ONLY existing local upload"
