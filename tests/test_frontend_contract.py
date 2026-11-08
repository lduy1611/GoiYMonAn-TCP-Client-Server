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


def test_meal_plan_v2_keeps_unquantified_items_without_fabricating_amounts():
    script=(ROOT/"source/web/static/meal-plan-v2.js").read_text(encoding="utf-8")
    template=(ROOT/"source/web/templates/meal_plan_v2.html").read_text(encoding="utf-8")
    assert "u.quantity===null||typeof u.quantity==='string'" in script
    assert "u.quantity||'" in script
    assert "validClassificationVersion(d?.classification_version,baseVersion)" in script
    assert "^:v2:[a-f0-9]{16}:admin:[a-f0-9]{12}$" in script
    assert "^::admin:[a-f0-9]{12}$" in script
    assert "Mã yêu cầu: '+e.request_id" in script
    assert "meal-plan-v2.js?v=meal-classification-admin-1" in template


def test_pages_expose_loading_errors_and_keyboard_navigation():
    home, detail = page("index.html"), page("detail.html")
    assert any(attrs.get("role") == "alert" for _, attrs in home.elements)
    assert any(attrs.get("aria-busy") == "true" for _, attrs in detail.elements)
    for parsed in (home, detail):
        assert any(tag == "a" and attrs.get("class") == "skip-link" for tag, attrs in parsed.elements)
        assert any(tag == "meta" and attrs.get("name") == "viewport" for tag, attrs in parsed.elements)
        assert any(tag == "script" and "defer" in attrs for tag, attrs in parsed.elements)


def test_both_pages_use_matching_versioned_assets_and_focusable_skip_targets():
    for name, target in (("index.html", "recommend-form"), ("detail.html", "detail")):
        parsed = page(name)
        assets = [attrs.get("href") if tag == "link" else attrs.get("src")
                  for tag, attrs in parsed.elements if tag in {"link", "script"}]
        assert len(assets) >= 3
        versions = {}
        for asset in assets:
            parsed_asset = urlsplit(asset)
            version = parse_qs(parsed_asset.query).get("v")
            assert version and version[0], "CSS/JS need release URLs to avoid stale cached assets"
            versions[parsed_asset.path] = version[0]
        assert len(versions) == len(set(urlsplit(asset).path for asset in assets))
        assert any(attrs.get("id") == target and attrs.get("tabindex") == "-1" for _, attrs in parsed.elements)


def test_shared_image_loader_precedes_page_script():
    for name, consumer in (("index.html", "/static/app.js"), ("detail.html", "/static/detail.js")):
        parsed = page(name)
        scripts = [urlsplit(attrs["src"]).path for tag, attrs in parsed.elements if tag == "script" and "src" in attrs]
        assert scripts.index("/static/recipe-images.js") < scripts.index(consumer)


def test_admin_recipe_ingredient_editor_has_no_requirement_selector():
    script = (ROOT / "source/web/static/admin.js").read_text(encoding="utf-8")
    styles = (ROOT / "source/web/static/admin.css").read_text(encoding="utf-8")
    assert "data-requirement" not in script
    assert "requirementLabel" not in script
    assert "requirement:line.requirement" not in script
    assert "requirement:'required'" not in script  # Backend owns the fixed rule.
    assert "quantity_raw:row.querySelector('[data-quantity]').value.trim()||null" in script
    assert "is_required:true" in script
    assert ".admin-line{display:grid;grid-template-columns:minmax(180px,1.2fr) minmax(120px,.8fr) 40px" in styles
    assert "@media(max-width:680px)" in styles
    assert ".admin-line{grid-template-columns:minmax(0,1fr) 40px}" in styles


def test_advanced_filter_disclosure_has_a_single_labeled_target():
    home = page("index.html")
    toggle = next(attrs for tag, attrs in home.elements if attrs.get("id") == "advanced-toggle")
    assert toggle["type"] == "button"
    assert toggle["aria-expanded"] in {"false", "true"}
    assert toggle["aria-controls"] == "ingredient-panel"
    assert home.ids.count(toggle["aria-controls"]) == 1
    region = next(attrs for _, attrs in home.elements if attrs.get("id") == "ingredient-panel")
    assert region["role"] == "region" and region["aria-labelledby"] in home.ids


def test_admin_recipe_view_hides_storage_provenance_and_refreshes_confirmed_changes():
    script = (ROOT / "source/web/static/admin.js").read_text(encoding="utf-8")
    template = (ROOT / "source/web/templates/admin.html").read_text(encoding="utf-8")
    assert "const errorCopy={" in script
    assert "ADMIN_LEGACY_RECIPE_CONFLICT:" in script and "DB_ERROR:" in script
    assert "H\u00e3y t\u1ea3i l\u1ea1i d\u1eef li\u1ec7u tr\u01b0\u1edbc khi th\u1eed l\u1ea1i." in script
    simple_view = script[script.index("async function showRevision(id)"):script.index("async function showLegacyRecipe(id)")]
    legacy_view = script[script.index("async function showLegacyRecipe(id)"):script.index("$('#admin-search')")]
    assert "Ngu?n c?ng th?c" not in legacy_view and "source_url" not in legacy_view and "has_override" not in legacy_view
    assert "Ngu?n v? b?ng ch?ng" not in simple_view and "overlay" not in simple_view.lower() and "legacy" not in simple_view.lower()
    assert "Nguy\\u00ean li\\u1ec7u" in simple_view and "H\\u01b0\\u1edbng d\\u1eabn ch\\u1ebf bi\\u1ebfn" in simple_view
    assert "revisionId||legacyRecipeId!==null?" in script and "S?a m?n legacy" not in script and "S?a c?ng th?c" not in script
    assert "cache:'no-store'" in script
    users_script = (ROOT / "source/web/static/admin-users.js").read_text(encoding="utf-8")
    assert "cache:'no-store'" in users_script and "await load()" in users_script
    assert "await search()" in script[script.index("async function uploadSelectedImage"):script.index("async function removeEditorImage")]
    assert "await search()" in script[script.index("async function removeEditorImage"):script.index("function populateOptions")]
    ingredient_table = template[template.index('class="admin-table-wrap admin-ingredient-table-wrap"'):template.index('</table>', template.index('class="admin-table-wrap admin-ingredient-table-wrap"'))]
    assert "Ngu?n</th>" not in ingredient_table and "H? s?</th>" not in ingredient_table
    assert "Th&#234;m m&#243;n &#259;n" in template
    assert "Hoàn thiện hiển thị" not in script
    assert "/api/admin/catalog-recipes" in script and "idempotency_key" in script
    assert "data-delete" in script and "data-restore" in script
    recipe_rows = script[script.index("function renderRows(rows)"):script.index("async function hydrateRecipeThumbnails")]
    assert "data-lifecycle" not in recipe_rows and "data-next-visible" not in recipe_rows
    assert "data-view" in recipe_rows and "data-edit" in recipe_rows
    assert "data-delete" in recipe_rows and "data-restore" in recipe_rows
    lifecycle = script[script.index("async function setRecipeLifecycle(event)"):script.index("function currentDraft()")]
    assert "target.dataset.title" in lifecycle and "if(!confirm(question))return" in lifecycle
    assert "is_deleted:deleted" in lifecycle
    assert "setRecipeVisibility" not in script and "setRecipeLifecycle" in script
    css = (ROOT / "source/web/static/admin.css").read_text(encoding="utf-8")
    assert ".admin-ingredient-table-wrap table{min-width:620px}" in css
    assert "@media(max-width:680px)" in css


def test_admin_add_recipe_button_uses_catalog_readiness_and_opens_shared_ingredient_editor():
    script = (ROOT / "source/web/static/admin.js").read_text(encoding="utf-8")
    template = (ROOT / "source/web/templates/admin.html").read_text(encoding="utf-8")
    button = next(attrs for _, attrs in page("admin.html").elements if attrs.get("id") == "admin-create")
    assert "disabled" in button  # stays fail-closed until authenticated backend readiness loads
    assert button.get("aria-describedby") == "admin-write-note"
    assert "state.recipeCatalogReady=data.recipe_catalog_ready===true" in script
    assert "createButton.disabled=!state.recipeCatalogReady" in script
    assert "backend s\u1eb5n s\u00e0ng" in script
    assert "recipe_catalog_ready" in script and "ki\u1ec3m tra migration 009" in script
    assert "$('#admin-create').onclick=()=>openEditor(null,null,$('#admin-create'))" in script
    assert "await refreshIngredientOptions()" in script
    assert "id=\"admin-write-note\"" in template


def test_user_catalog_restore_drops_stale_ids_without_replacing_and_validates_result_ids():
    script = (ROOT / "source/web/static/app.js").read_text(encoding="utf-8")
    assert "function validPublicIngredientId(id)" in script
    assert "validPublicIds(item.missing_ids, 50)" in script
    assert "conditions.available.filter(id=>state.ingredients.has(id))" in script
    assert "conditions.excluded.filter(id=>state.ingredients.has(id))" in script
    assert "kh\\u00f4ng thay b\\u1eb1ng nguy\\u00ean li\\u1ec7u kh\\u00e1c" in script


def test_admin_save_error_handling_preserves_auth_distinction_and_pending_draft():
    script = (ROOT / "source/web/static/admin.js").read_text(encoding="utf-8")
    login = (ROOT / "source/web/static/admin-login.js").read_text(encoding="utf-8")
    assert "if(response.status===401)" in script
    assert "if(response.status===401||response.status===403)" not in script
    assert "ADMIN_WRITE_DENIED:'T\u00e0i kho\u1ea3n Admin kh\u00f4ng c\u00f3 quy\u1ec1n ghi thao t\u00e1c n\u00e0y.'" in script
    assert "ADMIN_CSRF:" in script and "ADMIN_UNAUTHORIZED:" in script
    assert "preserveDraftForReauth()" in script and "adminDraftReauth" in script
    assert "restoreDraftAfterReauth()" in script and "imageNeedsReselect" in script
    assert "if(error.code==='ADMIN_CSRF')" in script and "Đăng nhập lại và giữ biểu mẫu" in script
    assert "if(state.dirty&&!state.busy&&!state.reauthenticating)" in script
    assert "parsed.origin===location.origin&&parsed.pathname==='/admin'" in login
