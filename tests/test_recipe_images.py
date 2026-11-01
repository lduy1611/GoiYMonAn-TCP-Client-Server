from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
from PIL import Image

from source.web.main import app

ROOT = Path(__file__).parents[1]
STATIC = ROOT / "source/web/static"
PROJECT_IDS = {1, 2, 3, 7, 8, 9, 10, 20, 21, 32, 38, 41, 45, 47, 48}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, f"Duplicate JSON key: {key}"
        result[key] = value
    return result


def image_catalog():
    return json.loads((STATIC / "recipe-images.json").read_text(encoding="utf-8"), object_pairs_hook=unique_object)


def test_image_catalog_covers_database_recipe_ids_without_changing_recipe_data():
    catalog = image_catalog()
    audit = json.loads((ROOT / "statics/results/phase4_dataset_audit.json").read_text(encoding="utf-8"))
    assert {int(key) for key in catalog["recipes"]} == {row["recipe_id"] for row in audit["recipe_rows"]}
    assert len(catalog["recipes"]) == 50
    assert catalog["placeholder_path"] == "/static/images/recipes/placeholder.svg"
    assert {int(key) for key, entry in catalog["recipes"].items() if entry.get("source_type") == "project_ai"} == PROJECT_IDS
    assert len({entry["image_path"] for entry in catalog["recipes"].values()}) == 50
    assert len({entry["source_sha256"] for entry in catalog["recipes"].values()}) == 50
    for key, entry in catalog["recipes"].items():
        assert entry["recipe_id"] == int(key)
        assert entry["image_path"].startswith("/static/images/recipes/")
        assert ".." not in entry["image_path"]
        assert isinstance(entry["alt"], str) and entry["alt"].strip()
        assert isinstance(entry["license_note"], str) and entry["license_note"].strip()
        path = STATIC / entry["image_path"].removeprefix("/static/")
        assert path.is_file()
        assert entry["is_placeholder"] is False
        assert re.fullmatch(r"[0-9a-f]{64}", entry["source_sha256"])
        assert entry["generated_ai"] is True
        assert "AI" in entry["alt"]
        if int(key) in PROJECT_IDS:
            assert entry["source_name"] == "Minh họa AI tạo riêng cho project"
            assert entry["source_url"] is None and entry["source_image_url"] is None
            assert entry["source_original_filename"] == f"recipe-{int(key):02d}.png"
        else:
            assert urlsplit(entry["source_url"]).hostname == "agni.vn"
            assert urlsplit(entry["source_image_url"]).hostname == "img.agni.vn"
            assert entry["source_owner"] == "veasy"
            assert urlsplit(entry["source_url"]).scheme in {"http", "https"}
        assert path.suffix.lower() in {".webp", ".jpg", ".jpeg", ".png"}
        assert entry["source_name"].strip()
        with Image.open(path) as photo:
            assert photo.width > 0 and photo.height > 0
            photo.verify()
        for width, variant in entry.get("variants", {}).items():
            variant_path = STATIC / variant.removeprefix("/static/")
            assert variant.startswith("/static/images/recipes/") and ".." not in variant
            with Image.open(variant_path) as photo:
                assert photo.width == int(width)
                if int(key) in PROJECT_IDS:
                    original_width, original_height = entry["source_dimensions"]
                    assert photo.height == round(int(width) * original_height / original_width)
                photo.verify()
            assert variant_path.stat().st_size < 200_000
        assert set(entry["variants"]) == {"320", "640", "960"}


def test_all_150_webp_variants_are_mapped_once_without_orphan_assets():
    catalog = image_catalog()
    paths = [path for entry in catalog["recipes"].values() for path in entry["variants"].values()]
    assert len(paths) == len(set(paths)) == 150
    actual = {"/static/images/recipes/" + path.name for path in (STATIC / "images/recipes").glob("*.webp")}
    assert set(paths) == actual


def test_placeholder_is_local_neutral_svg_without_remote_resources():
    raw = (STATIC / "images/recipes/placeholder.svg").read_text(encoding="utf-8")
    root = ET.fromstring(raw)
    assert root.tag.endswith("svg")
    assert "viewBox" in root.attrib
    assert "<image" not in raw and "<script" not in raw
    assert 'href="http' not in raw


def test_image_assets_are_served_without_database_access(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("Static image assets must not invoke TCP")
    monkeypatch.setattr("source.web.main.TCPClient.request", unexpected)
    with TestClient(app) as client:
        manifest = client.get("/static/recipe-images.json?v=ui-1.2.3")
        assert manifest.status_code == 200 and len(manifest.json()["recipes"]) == 50
        placeholder = client.get(manifest.json()["placeholder_path"])
        assert placeholder.status_code == 200
        assert "image/svg+xml" in placeholder.headers["content-type"]
        assert client.get("/static/recipe-images.js?v=ui-1.2.3").status_code == 200
        for entry in manifest.json()["recipes"].values():
            for path in entry["variants"].values():
                response = client.get(path)
                assert response.status_code == 200
                assert "image/webp" in response.headers["content-type"]
