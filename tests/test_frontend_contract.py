from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit
import json
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[1]


def shopping_formatter_script():
    source=(ROOT/"source/web/static/meal-plan-v2.js").read_text(encoding="utf-8")
    unit_label=next(line for line in source.splitlines() if "const unitLabel=" in line)
    return unit_label+"\n"+source[source.index("  const shoppingUnit="):source.index("  // End shopping presentation.")]


def custom_portion_presentation(data):
    node=shutil.which("node")
    if not node:pytest.skip("Node is required to execute the actual Custom renderer")
    source=(ROOT/"source/web/static/meal-plan-v2.js").read_text(encoding="utf-8")
    decimal=next(line for line in source.splitlines() if "const decimal =" in line)
    script=decimal+"\nconst esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\"','&quot;');\n"
    script+=source[source.index("  // Custom portion presentation only."):source.index("  // End custom portion presentation.")]
    script+="\nconst data="+json.dumps(data)+"; const before=JSON.stringify(data);\n"
    script+="const freeze=o=>{if(o&&typeof o==='object'){Object.values(o).forEach(freeze);Object.freeze(o);}};freeze(data);\n"
    script+="const result=customPortionPresentation(data,new Map([[1,'TEST main'],[2,'TEST vegetable'],[3,'TEST soup']]));if(JSON.stringify(data)!==before)throw Error('mutated');process.stdout.write(JSON.stringify(result));"
    return json.loads(subprocess.run([node],input=script,text=True,encoding="utf-8",capture_output=True,check=True).stdout)


def custom_display_fixture(people=12,equivalent=None,missing=False):
    equivalent=equivalent or str(people)
    roles=["main","vegetable","soup"]
    recipes=[{"recipe_id":i,"base_servings":"6" if i==3 else "4","target_servings":equivalent,
              "status":"COMPLETE","data_status":"needs_review" if missing and i==2 else "estimated"}
             for i in (1,2,3)]
    groups=[{"label":role,"source_capacity":r["base_servings"],
             "adjustment_factor":None if missing and i==2 else "1.333333333333",
             "recipes":[{"recipe_id":i,"source_servings":None if missing and i==2 else r["base_servings"],
                         "target_servings":None if missing and i==2 else equivalent}]}
            for i,(role,r) in enumerate(zip(roles,recipes),1)]
    return {"people":people,"adults":4 if equivalent=="5.2" else people,"children":2 if equivalent=="5.2" else 0,
            "child_equivalent":"0.6","equivalent_people":equivalent,"recipes":recipes,
            "totals_complete":True,"portion_groups":[],"service_assessment":{"groups":groups},
            "known_ingredients":[{"quantity_value":"266.666666666667","unit":"g"}]}


@pytest.mark.parametrize("people",[2,4,6,8,12])
def test_custom_portion_labels_distinguish_demand_original_servings_and_allocation(people):
    result=custom_portion_presentation(custom_display_fixture(people))
    assert result["complete"]
    assert f"Định lượng chuẩn bị cho {people} người" in result["html"]
    assert f"Đã tính định lượng tham khảo cho {people} người" in result["html"]
    assert "suất người lớn tương đương" in result["html"]
    assert "4 suất gốc" in result["html"] and "6 suất gốc" in result["html"]
    assert "Số suất công thức gốc (trước điều chỉnh)" in result["html"]
    assert "Khả năng phục vụ theo nhóm món" not in result["html"]
    assert "1.333333333333" not in result["html"]


def test_custom_portion_incomplete_allocation_does_not_inherit_totals_complete_claim():
    result=custom_portion_presentation(custom_display_fixture(missing=True))
    assert not result["complete"]
    assert "Chưa tính đầy đủ" in result["html"]
    assert "TEST vegetable: chưa đủ cơ sở phân bổ" in result["html"]
    assert "ƯỚC TÍNH · Cần duyệt" in result["html"]
    assert "4 suất gốc · Cần duyệt; số suất này chưa đủ căn cứ để phân bổ." in result["html"]
    assert "Đã tính định lượng tham khảo cho 12 người" not in result["html"]


def test_custom_portion_child_equivalence_is_demand_and_comes_from_response():
    result=custom_portion_presentation(custom_display_fixture(6,"5.2"))
    assert "5,2 suất người lớn tương đương" in result["html"]
    assert "4 người lớn + 0,6 × 2 trẻ em" in result["html"]
    assert "không phải kết luận mâm gốc đủ ăn" in result["html"]


def test_custom_portion_missing_recipe_metadata_stays_unknown_and_incomplete():
    data=custom_display_fixture()
    data["service_assessment"]=None
    data["recipes"][1].update(base_servings=None,target_servings=None,status="INCOMPLETE",data_status=None)
    result=custom_portion_presentation(data)
    assert not result["complete"] and "Chưa xác định" in result["html"]


def test_daily_beverage_cards_preserve_response_escape_names_and_clear_empty_results():
    from playwright.sync_api import sync_playwright
    source=(ROOT/'source/web/static/meal-plan-v2.js').read_text(encoding='utf-8')
    renderer=source[source.index('  function dailyBeverageReason('):source.index('  let dailyCalculation=')]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page();page.set_content('<div id="meal-beverages"></div>')
        page.add_script_tag(content="const $=id=>document.getElementById(id);const esc=v=>String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('\"','&quot;');window.RecipeImages={mount:root=>{window.mounts=(window.mounts||0)+1;}};"+renderer)
        reason='Admin phân loại phù hợp mùa Hạ. Có thể dùng mát theo cách pha đã lưu. Admin phân loại phù hợp kiểu mâm đã chọn.'
        data=[{'recipe_id':i,'title':'Trà <sen>','reason':reason,'amount':None,'people':8} for i in [1,2,3]]
        assert page.evaluate("data=>{const original=JSON.stringify(data);data.forEach(Object.freeze);Object.freeze(data);renderDailyBeverages(data);return JSON.stringify(data)===original}",data)
        assert page.locator('.meal-beverage-card').count()==2
        assert page.locator('.meal-beverage-card a').first.inner_text()=='Trà <sen>'
        assert page.locator('.meal-beverage-card a').first.get_attribute('href')=='/recipes/1'
        assert page.locator('.meal-beverage-card p').first.inner_text()=='Hợp mùa Hạ; dùng mát.'
        assert page.locator('#meal-beverages details').count()==0
        assert page.locator('.meal-beverage-card small').first.inner_text()=='Chưa có định lượng tham khảo'
        assert page.evaluate('mounts')==1
        page.evaluate('renderDailyBeverages([])')
        assert page.locator('.meal-beverage-card').count()==0
        assert 'Chưa có đồ uống phù hợp' in page.locator('#meal-beverages').inner_text()
        browser.close()


def test_daily_previous_plan_archive_is_collapsed_reversible_and_preserves_pin_events():
    from playwright.sync_api import sync_playwright
    source=(ROOT/"source/web/static/meal-plan-v2.js").read_text(encoding="utf-8")
    archive=source[source.index("  function archivePreviousDaily("):source.index("  function controls()")]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel="msedge",headless=True)
        page=browser.new_page()
        page.set_content('<section id="results"><p id="meal-summary">Previous meal</p>'
                         '<div id="meal-cards"><button id="pin">Pin</button></div><p id="after">After</p></section>')
        original=page.locator('#results').inner_html()
        page.add_script_tag(content="const $=id=>document.getElementById(id); const state={people:11};"
            "const conditions=()=>({people:state.people}); const dailyResultKey=c=>JSON.stringify(c);"
            "let clicks=0;document.getElementById('meal-cards').addEventListener('click',()=>clicks++);"+archive)
        page.evaluate('archivePreviousDaily(true)')
        assert page.locator('#meal-previous-plan').count()==1
        assert not page.locator('#pin').is_visible()
        assert '11 người' in page.locator('#meal-previous-plan > summary').inner_text()
        page.locator('#meal-previous-plan > summary').click()
        page.locator('#pin').click()
        page.evaluate('archivePreviousDaily(true)')
        assert page.locator('#pin').is_visible()  # same context retains the user's expansion
        page.evaluate('state.people=12;archivePreviousDaily(true)')
        assert not page.locator('#pin').is_visible()
        page.evaluate('archivePreviousDaily(false)')
        assert page.locator('#results').inner_html()==original
        page.locator('#pin').click()
        assert page.evaluate('clicks')==2
        browser.close()


@pytest.mark.parametrize("unit,low,high,precision,expected", [
    ("g","250",None,"exact","250"),
    ("g","266.666666","266.666667","outward_6dp","≈ 266,7"),
    ("ml","333.333333","333.333334","outward_6dp","≈ 333,3"),
    ("kg","1.23456",None,"exact","≈ 1,23"),
    ("l","0.666666",None,"exact","≈ 0,67"),
    ("g","10.11","20.22","exact","10,1–20,3"),
    ("ml","100","200","exact","100–200"),
    ("g","266.666666","399.999999","outward_6dp","266,6–400"),
    ("kg","1.234","2.345","exact","1,23–2,35"),
    ("clove","1.333333","1.333334","outward_6dp","≈ 1 1/3"),
    ("piece","0.666666","0.666667","outward_6dp","≈ 2/3"),
    ("source_spoon","1.333333","1.333334","outward_6dp","≈ 1 1/3"),
    ("clove","0.25",None,"exact","1/4"),
    ("piece","0.5","1.5","exact","1/2–1 1/2"),
    ("piece","0.37",None,"exact","0,37"),
    ("g","0.001",None,"exact","< 0,1"),
    ("l","0.001",None,"exact","< 0,01"),
    ("quả","3",None,"exact","3"),
    ("tép","0.5",None,"exact","1/2"),
    ("củ","1.5",None,"exact","1 1/2"),
    ("muỗng","0.125",None,"exact","1/8"),
    ("g","9007199254740993",None,"exact","9007199254740993"),
])
def test_shopping_quantity_format_preserves_source_values(unit,low,high,precision,expected):
    node=shutil.which("node")
    if not node:pytest.skip("Node is required to execute the browser formatter")
    q={"unit":unit,"amount_kind":"exact" if high is None else "range",
       "quantity_value":low if high is None else None,"quantity_min":low,
       "quantity_max":high or low,"precision":precision}
    script=shopping_formatter_script()+"\nconst q=Object.freeze("+json.dumps(q)+");\n"
    script+="const before=JSON.stringify(q); const value=formatShoppingQuantity(q);if(JSON.stringify(q)!==before)throw Error('mutated');process.stdout.write(JSON.stringify(value));"
    result=subprocess.run([node],input=script,text=True,encoding="utf-8",capture_output=True,check=True)
    assert json.loads(result.stdout)==expected


@pytest.mark.parametrize("unit,name,expected", [
    ("clove","Tỏi","tép"),("piece","Chanh","quả"),("piece","Cà rốt","củ"),
    ("piece","Thịt gà","piece (chưa rõ loại)"),
    ("source_spoon","Nước mắm","muỗng (chưa rõ loại)"),("l","Nước","lít"),
])
def test_shopping_unit_translation_is_contextual_and_does_not_convert(unit,name,expected):
    node=shutil.which("node")
    if not node:pytest.skip("Node is required to execute the browser formatter")
    script=shopping_formatter_script()+"\nprocess.stdout.write(JSON.stringify(shoppingUnit("+json.dumps(unit)+","+json.dumps(name)+")));"
    result=subprocess.run([node],input=script,text=True,encoding="utf-8",capture_output=True,check=True)
    assert json.loads(result.stdout)==expected


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
    assert "mode-switch" not in (ROOT / "source/web/templates/index.html").read_text(encoding="utf-8")
    script = (ROOT / "source/web/static/app.js").read_text(encoding="utf-8")
    targets = set(re.findall(r"\$\('([a-z-]+)'\)", script))
    # This button is created only after an ingredient fetch failure.
    assert targets - {"retry-ingredients"} <= set(home.ids)


def test_user_pages_share_single_header_and_account_route():
    header=(ROOT/"source/web/templates/_user_header.html").read_text(encoding="utf-8")
    for label in ("Khám phá","Tủ lạnh","Mâm cơm","Trưa nay","Tài khoản"):
        assert label in header
    assert "user-account-tab" in header and "account_target" in header
    for name in ("index.html","meal_plan.html","meal_plan_v2.html","detail.html","account_auth.html","account_profile.html"):
        source=(ROOT/"source/web/templates"/name).read_text(encoding="utf-8")
        assert '_user_header.html' in source
        assert '/static/styles.css?v=feedback-widget-20261111' in source
        assert 'id="feedback-open"' in header and 'id="feedback-dialog"' in header
        assert 'id="feedback-form"' in header and 'id="feedback-image"' in header
    menu=(ROOT/"source/web/static/account-menu.js").read_text(encoding="utf-8")
    assert "envelope.data?.authenticated===true?'/account/profile':'/account/login'" in menu
    profile=(ROOT/"source/web/templates/account_profile.html").read_text(encoding="utf-8")
    assert 'id="profile-username"' in profile and 'id="profile-logout"' in profile


def test_meal_plan_v2_keeps_unquantified_items_without_fabricating_amounts():
    script=(ROOT/"source/web/static/meal-plan-v2.js").read_text(encoding="utf-8")
    template=(ROOT/"source/web/templates/meal_plan_v2.html").read_text(encoding="utf-8")
    assert "u.quantity===null||typeof u.quantity==='string'" in script
    assert "u.quantity||'" in script
    assert "validClassificationVersion(d?.classification_version,baseVersion)" in script
    assert "^:v2:[a-f0-9]{16}:admin:[a-f0-9]{12}$" in script
    assert "^::admin:[a-f0-9]{12}$" in script
    assert "Mã yêu cầu: '+e.request_id" in script
    assert "meal-plan-v2.js?v=beverage-cards-20261113-2" in template
    assert "buttonKey==='snacks'?'snack'" in script
    assert "['daily','guests','drinking'].includes(v)" in script


def test_meal_plan_hides_snack_mode_and_migrates_saved_selection_to_daily():
    script=(ROOT/"source/web/static/meal-plan-v2.js").read_text(encoding="utf-8")
    template=(ROOT/"source/web/templates/meal_plan_v2.html").read_text(encoding="utf-8")
    assert 'data-meal-type="snacks"' not in template
    assert "!['daily','guests','drinking'].includes(savedOccasion)" in script
    assert "cleanPreferences.occasion='daily'" in script
    assert "params.get('type')" in script and "state.preferences.occasion='daily'" in script
    assert "params.get('type')" in script and "['snack','snacks'].includes(params.get('type'))" in script


def test_meal_plan_keeps_shopping_calculation_without_portion_panel():
    script = (ROOT / "source/web/static/meal-plan-v2.js").read_text(encoding="utf-8")
    template = (ROOT / "source/web/templates/meal_plan_v2.html").read_text(encoding="utf-8")
    assert 'id="meal-portions"' not in template
    assert "Khẩu phần theo số người" not in template
    assert 'id="meal-shopping"' in template and 'id="meal-copy-list"' in template
    assert "fetch('/api/meal-plan/calculate'" in script
    assert "renderCalculatedShopping(e.data,unresolved)" in script
    assert "['main','seasoning','cooking_medium','garnish','unknown','consumed'].includes(i.purpose)" in script
    assert "i.measurement_basis!=='unknown'" in script and "typeof i.mergeable==='boolean'" in script
    assert "i.ingredient_form===null||text(i.ingredient_form,120)" in script
    assert "i.uses.length===1" in script
    assert r"Gi\u1eef ri\u00eang" in script


def test_meal_plan_generates_on_open_and_updates_filter_changes_automatically():
    script=(ROOT/"source/web/static/meal-plan-v2.js").read_text(encoding="utf-8")
    assert "if(state.autoPending||!state.view){state.autoPending=true;scheduleLayout();}" in script
    changed=script[script.index("function changed() {"):script.index("function restore() {")]
    assert "state.autoPending=true;" in changed and "scheduleLayout();" in changed
    assert "layoutMismatch()||state.autoPending" in script
    assert "Nhấn Tạo mâm cơm" not in script
    assert "state.controller?.abort()" in script and "++state.sequence" in script


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


def test_admin_recipe_ingredient_editor_supports_v3_structured_amounts_and_optional_lines():
    script = (ROOT / "source/web/static/admin.js").read_text(encoding="utf-8")
    styles = (ROOT / "source/web/static/admin.css").read_text(encoding="utf-8")
    assert "data-requirement" in script
    assert "amount_kind" in script and "unit_id" in script and "scaling_mode" in script
    assert "id=\"draft-servings\"" in (ROOT / "source/web/templates/admin.html").read_text(encoding="utf-8")
    assert "id=\"draft-minutes-prep\"" in (ROOT / "source/web/templates/admin.html").read_text(encoding="utf-8")
    assert "id=\"draft-structured-steps\"" in (ROOT / "source/web/templates/admin.html").read_text(encoding="utf-8")
    assert ".admin-line{grid-template-columns:repeat(4,minmax(0,1fr))" in styles
    assert "@media(max-width:680px)" in styles
    assert "@media(max-width:720px)" in styles


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


def test_admin_can_enable_only_unverified_ingredient_from_ingredient_editor():
    script=(ROOT/"source/web/static/admin.js").read_text(encoding="utf-8")
    template=(ROOT/"source/web/templates/admin.html").read_text(encoding="utf-8")
    assert 'id="admin-ingredient-catalog-mode"' in template
    assert 'id="admin-ingredient-status"' in template
    assert 'option value="all">Tất cả' in template
    assert 'option value="active">Đang sử dụng' in template
    assert 'option value="inactive">Ngừng sử dụng' in template
    assert 'data-unified-schema="{{ \'true\' if unified_schema else \'false\' }}"' in template
    assert 'id="admin-ingredient-availability-option"' in template
    assert 'id="admin-ingredient-make-available"' in template
    assert "item?.identity_status==='NEEDS_VERIFICATION'&&item?.can_edit===true" in script
    assert "payload.make_available=$('#admin-ingredient-make-available').checked" in script
    assert "status='+encodeURIComponent($('#admin-ingredient-status')?.value||state.ingredientStatus)" in script
    assert "catalog='+encodeURIComponent(state.ingredientCatalog==='v2'?'v2':'shared')" in script


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


def test_permanent_delete_actions_are_guarded_and_separate_from_restore():
    admin=(ROOT/"source/web/static/admin.js").read_text(encoding="utf-8")
    repository=(ROOT/"source/server/unified_repository.py").read_text(encoding="utf-8")
    assert "row.can_permanently_delete===true" in admin
    assert "item.can_permanently_delete===true" in admin
    assert "data-recipe-permanent" in admin and "data-ingredient-permanent" in admin
    assert "catalog-recipes/'+encodeURIComponent(id)+'/permanent'" in admin
    assert "ingredients/'+encodeURIComponent(id)+'/permanent'" in admin
    assert "confirm_user_content_delete" in repository
    assert "expected_achievement_counts" in repository
    assert "recipe_images" in repository and "recipe_edit_history" in repository and "recipe_id_map" in repository
    assert "achievement_posts" in repository and "achievement_images" in repository
    assert "ingredient is still referenced by one or more recipes" in repository
    assert "permanent_delete_block_reason" in admin
    assert "data-achievement-posts" in admin and "expected_achievement_counts:counts" in admin
    assert r"X\u00e1c nh\u1eadn l\u1ea7n cu\u1ed1i" in admin
    assert r"Th\u00f4ng tin x\u00e1c nh\u1eadn x\u00f3a kh\u00f4ng h\u1ee3p l\u1ec7" in admin
    assert "error.serverMessage=envelope.error?.message||null" in admin
    assert r"M\u00e3 y\u00eau c\u1ea7u:" in admin


def test_admin_delete_lists_allow_mapped_and_legacy_recipes_and_report_user_content(monkeypatch):
    import source.server.unified_repository as unified_repository
    from source.server.unified_repository import UnifiedMySQLRepository

    recipe_rows = [
        {"recipe_id": 7, "title": "TEST_ONLY legacy", "role": "main", "minutes_total": 10,
         "is_public": 0, "deleted_at": object(), "edit_version": 1},
        {"recipe_id": 9_000_000_001, "title": "TEST_ONLY mapped", "role": "main", "minutes_total": 10,
         "is_public": 0, "deleted_at": object(), "edit_version": 1},
        {"recipe_id": 9_000_000_002, "title": "TEST_ONLY eligible", "role": "main", "minutes_total": 10,
         "is_public": 0, "deleted_at": object(), "edit_version": 1},
    ]
    ingredient_rows = [
        {"ingredient_id": 201, "name": "TEST_ONLY referenced", "normalized_name": "referenced", "is_active": 0},
        {"ingredient_id": 202, "name": "TEST_ONLY mapped", "normalized_name": "mapped", "is_active": 0},
        {"ingredient_id": 203, "name": "TEST_ONLY eligible", "normalized_name": "eligible", "is_active": 0},
    ]

    def query(_connection, sql, args=()):
        if "COUNT(*) n FROM recipes" in sql:
            return [{"n": len(recipe_rows)}]
        if "SELECT recipe_id,title,role,minutes_total,is_public,deleted_at,edit_version FROM recipes" in sql:
            return recipe_rows
        if "FROM recipe_id_map WHERE recipe_id IN" in sql:
            return [{"recipe_id": 9_000_000_001}]
        if "FROM achievement_posts p" in sql:
            return [{"recipe_id": 9_000_000_001,"post_count":2,"comment_count":3,"image_count":4}]
        if "SELECT ingredient_id,name,normalized_name,is_active FROM ingredients" in sql:
            return ingredient_rows
        if "COUNT(DISTINCT recipe_id) n FROM recipe_ingredients" in sql:
            return [{"n": 1 if args[0] == 201 else 0}]
        if "FROM ingredient_id_map WHERE ingredient_id=%s" in sql:
            return [{"ingredient_id": 202}] if args[0] == 202 else []
        raise AssertionError(f"unexpected query: {sql}")

    monkeypatch.setattr(unified_repository, "_query", query)
    repo = object.__new__(UnifiedMySQLRepository)
    repo._version = lambda _connection, recipe_id: f"TEST_ONLY:{recipe_id}"
    recipes = repo.admin_list_recipes(None, "", 20, 0, visibility="deleted")["items"]
    by_recipe_id = {row["recipe_id"]: row for row in recipes}
    assert all(by_recipe_id[rid]["can_permanently_delete"] for rid in by_recipe_id)
    assert by_recipe_id[9_000_000_001]["has_identity_mapping"] is True
    assert by_recipe_id[9_000_000_001]["achievement_post_count"] == 2
    assert by_recipe_id[9_000_000_001]["achievement_comment_count"] == 3
    assert by_recipe_id[9_000_000_001]["achievement_image_count"] == 4
    ingredients = repo.admin_list_ingredients(None, "", 20, 0, status="inactive")["items"]
    by_ingredient_id = {row["ingredient_id"]: row for row in ingredients}
    assert "1" in by_ingredient_id[201]["permanent_delete_block_reason"] and "tham chi" in by_ingredient_id[201]["permanent_delete_block_reason"]
    assert by_ingredient_id[202]["permanent_delete_block_reason"]
    assert by_ingredient_id[203]["can_permanently_delete"] is True
