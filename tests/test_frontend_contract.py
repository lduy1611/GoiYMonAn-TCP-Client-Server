from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).parents[1]


class PageElements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []
        self.ids = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        if "id" in attributes:
            self.ids.append(attributes["id"])


def page(name):
    parser = PageElements()
    parser.feed((ROOT / "source/web/templates" / name).read_text(encoding="utf-8"))
    return parser


def test_home_controls_are_labeled_and_script_targets_exist():
    home = page("index.html")
    assert len(home.ids) == len(set(home.ids)), "Duplicate element IDs"
    labels = {attrs.get("for") for tag, attrs in home.elements if tag == "label"}
    assert {"ingredient-search", "max-minutes", "top-k"} <= labels
    assert any(tag == "form" and attrs.get("id") == "recommend-form" for tag, attrs in home.elements)
    script = (ROOT / "source/web/static/app.js").read_text(encoding="utf-8")
    targets = set(re.findall(r"\$\('([a-z-]+)'\)", script))
    # This button is created only after an ingredient fetch failure.
    assert targets - {"retry-ingredients"} <= set(home.ids)


def test_pages_expose_loading_errors_and_keyboard_navigation():
    home, detail = page("index.html"), page("detail.html")
    assert any(attrs.get("role") == "alert" for _, attrs in home.elements)
    assert any(attrs.get("aria-busy") == "true" for _, attrs in detail.elements)
    for parsed in (home, detail):
        assert any(tag == "a" and attrs.get("class") == "skip-link" for tag, attrs in parsed.elements)
        assert any(tag == "meta" and attrs.get("name") == "viewport" for tag, attrs in parsed.elements)
        assert any(tag == "script" and "defer" in attrs for tag, attrs in parsed.elements)


def test_both_pages_use_matching_versioned_assets_and_focusable_skip_targets():
    versions = set()
    for name, target in (("index.html", "recommend-form"), ("detail.html", "detail")):
        parsed = page(name)
        assets = [attrs.get("href") if tag == "link" else attrs.get("src")
                  for tag, attrs in parsed.elements if tag in {"link", "script"}]
        assert len(assets) == 3
        for asset in assets:
            version = parse_qs(urlsplit(asset).query).get("v")
            assert version and version[0], "CSS/JS need release URLs to avoid mixed cached versions"
            versions.add(version[0])
        assert any(attrs.get("id") == target and attrs.get("tabindex") == "-1" for _, attrs in parsed.elements)
    assert len(versions) == 1


def test_shared_image_loader_precedes_page_script():
    for name, consumer in (("index.html", "/static/app.js"), ("detail.html", "/static/detail.js")):
        parsed = page(name)
        scripts = [urlsplit(attrs["src"]).path for tag, attrs in parsed.elements if tag == "script" and "src" in attrs]
        assert scripts.index("/static/recipe-images.js") < scripts.index(consumer)


def test_advanced_filter_disclosure_has_a_single_labeled_target():
    home = page("index.html")
    toggle = next(attrs for tag, attrs in home.elements if attrs.get("id") == "advanced-toggle")
    assert toggle["type"] == "button"
    assert toggle["aria-expanded"] in {"false", "true"}
    assert toggle["aria-controls"] == "ingredient-panel"
    assert home.ids.count(toggle["aria-controls"]) == 1
    region = next(attrs for _, attrs in home.elements if attrs.get("id") == "ingredient-panel")
    assert region["role"] == "region" and region["aria-labelledby"] in home.ids
