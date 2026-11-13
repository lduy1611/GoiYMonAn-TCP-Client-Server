"""Synthetic serving evidence only; none of these amounts are recipe advice."""
from dataclasses import replace
from fractions import Fraction
from math import ceil

import pytest

from source.common.protocol import ProtocolError
from source.server import meal_plan_v2 as planner
from source.server.daily_meal_recommendation import required_counts, serving_evidence
from source.server.meal_plan import Classification
from source.server.meal_plan_calculation import Catalog, calculate, validate as portion_options
from tests.calculation_fixtures import fixture_catalog, test_line


def synthetic(people=5, adults=None, children=0, mains=6, vegetables=3, soups=3):
    target = Fraction(people if adults is None else adults) + Fraction(3, 5)*children
    roles = {**{i: "main" for i in range(1, mains+1)},
             **{30+i: "vegetable" for i in range(vegetables)},
             **{50+i: "soup" for i in range(soups)}}
    base = fixture_catalog(tuple(roles))
    revs = {rid: replace(rev, role=roles[rid],
        base_servings=str(ceil(target / required_counts(people)["main"]) if roles[rid] == "main" else ceil(target)),
        data_status="verified", data_evidence="TEST_ONLY simulated source recipe explicitly states its servings",
        lines=(test_line(amount_min=str(100+rid)),)) for rid, rev in base.revisions.items()}
    catalog = Catalog(revs, base.units, trust_admin_catalog=True)
    recipes = [{"id": rid, "title": f"TEST_ONLY {rid}", "minutes": 10,
                "all_ids": {1001}, "required_ids": {1001}} for rid in roles]
    return recipes, Classification("TEST_ONLY", roles), catalog


def run_case(people=5, *, setup=None, **payload):
    recipes, classification, catalog = setup or synthetic(people)
    from source.server.daily_meal_recommendation import generate as verified_generate
    result = verified_generate(recipes, planner.validate({"adaptive_daily": True, "people": people, **payload}, "test-daily"),
                              classification, "test-daily", None, None, catalog)
    return result, catalog


@pytest.mark.parametrize("people", range(1, 13))
def test_daily_qualifies_fixed_layout_and_preserves_every_source_amount(people):
    result, catalog = run_case(people)
    assert result["plan"], result["reason"]
    assert result["counts"] == required_counts(people)
    ids = [i["recipe_id"] for i in result["plan"]["items"]]
    calc = calculate(portion_options({"recipe_ids": ids, "people": people}), catalog)
    assert calc["totals_complete"]
    assert calc["service_assessment"]["assessment_status"] == "conditional"
    for item in calc["recipes"]:
        assert item["lines"][0]["quantity_value"] == catalog.revisions[item["recipe_id"]].lines[0].amount_min
    assert sum(Fraction(i["quantity_value"]) for i in calc["known_ingredients"]) == sum(100+rid for rid in ids)


@pytest.mark.parametrize("people", range(2, 13))
def test_daily_children_use_same_configured_equivalence_as_calculation(people):
    children = 1
    result, _ = run_case(people, setup=synthetic(people, adults=people-children, children=children),
                         adults=people-children, children=children)
    assert result["plan"], result["reason"]


@pytest.mark.parametrize("evidence", ["", "ESTIMATED measurement basis only; existing servings retained, not independently verified",
    "Missing ingredient amounts use peer medians per source serving; no invented yields"])
def test_daily_rejects_four_serving_fallback_without_serving_source(evidence):
    recipes, classification, catalog = synthetic(4)
    catalog = replace(catalog, revisions={rid: replace(r, base_servings="4", data_status="estimated", data_evidence=evidence)
        for rid, r in catalog.revisions.items()})
    result, _ = run_case(4, setup=(recipes, classification, catalog))
    assert result["plan"] is None
    assert result["reason"]["code"] == "PORTION_DATA_UNCONFIRMED"


def test_daily_serving_estimate_requires_matching_value_and_specific_source():
    from source.server.meal_plan_calculation import Review
    revision = next(iter(synthetic()[2].revisions.values()))
    assert serving_evidence(replace(revision, data_status="estimated", base_servings="4",
        data_evidence="base_servings=4; servings_source: TEST_ONLY comparable recipe serving statement"))
    assert not serving_evidence(replace(revision, data_status="estimated", base_servings="5",
        data_evidence="base_servings=4; servings_source: TEST_ONLY comparable recipe serving statement"))
    assert not serving_evidence(replace(revision, data_status="verified", servings_review=Review(),
        data_evidence="Ingredient amounts and measurement basis checked; no serving source"))


def test_daily_weighted_index_cannot_mask_insufficient_mains():
    recipes, classification, catalog = synthetic(8)
    # Three one-serving mains, 20-serving vegetables, 4-serving soup -> Q=8.25,
    # but the independent main check must reject every combo for eight people.
    catalog = replace(catalog, revisions={rid: replace(r, base_servings={"main":"1", "vegetable":"20", "soup":"4"}[r.role])
        for rid, r in catalog.revisions.items()})
    assert run_case(8, setup=(recipes, classification, catalog))[0]["plan"] is None


def test_daily_one_four_serving_soup_does_not_have_to_feed_eight_alone():
    recipes, classification, catalog = synthetic(8)
    catalog = replace(catalog, revisions={rid: replace(r, base_servings="4" if r.role == "soup" else "3" if r.role == "main" else "9")
        for rid, r in catalog.revisions.items()})
    result, _ = run_case(8, setup=(recipes, classification, catalog))
    assert result["plan"]  # Q = .55*9 + .30*9 + .15*4 = 8.25


def test_daily_eleven_people_distinguishes_numeric_shortfall_from_missing_search_result():
    recipes, classification, catalog = synthetic(11,mains=4,vegetables=1,soups=1)
    # TEST_ONLY source evidence is approved in this fixture. Four four-serving
    # mains + four-serving vegetable + four-serving soup have Q=10.6, not 11.
    revisions={rid:replace(rev,base_servings='4') for rid,rev in catalog.revisions.items()}
    short=replace(catalog,revisions=revisions)
    result,_=run_case(11,setup=(recipes,classification,short))
    assert result['plan'] is None
    assert result['daily_combo_search']=={'found':0,'complete':True}
    # Changing only synthetic source data creates Q=11.15. The same search,
    # fixed structure and thresholds must find it; no source recipe is scaled.
    revisions[1]=replace(revisions[1],base_servings='5')
    result,cat=run_case(11,setup=(recipes,classification,replace(catalog,revisions=revisions)))
    assert result['plan']
    assert result['counts']=={'main':4,'vegetable':1,'soup':1}
    ids=[item['recipe_id'] for item in result['plan']['items']]
    calculation=calculate(portion_options({'recipe_ids':ids,'people':11}),cat)
    assert calculation['service_assessment']['meal_capacity']=='11.15'
    assert calculation['totals_complete']


@pytest.mark.parametrize("problem", ["quantity", "basis", "unit", "serving_basis", "excess"])
def test_daily_rejects_incomplete_incompatible_or_excessive_combos(problem):
    recipes, classification, catalog = synthetic(5)
    revisions = {}
    for rid, rev in catalog.revisions.items():
        if rev.role == "main":
            line = rev.lines[0]
            if problem == "quantity": rev = replace(rev, lines=(replace(line, amount_min=None),))
            if problem == "basis": rev = replace(rev, lines=(replace(line, measurement_basis=None),))
            if problem == "unit": rev = replace(rev, lines=(replace(line, unit=None),))
            if problem == "serving_basis": rev = replace(rev, serving_basis="unknown")
            if problem == "excess": rev = replace(rev, base_servings="40")
        revisions[rid] = rev
    assert run_case(5, setup=(recipes, classification, replace(catalog, revisions=revisions)))[0]["plan"] is None


def test_daily_ten_rotations_unique_min_overlap_and_exhaustion_keeps_pins():
    setup = synthetic(5, mains=4, vegetables=2, soups=2)
    first, _ = run_case(5, setup=setup)
    history = [first["daily_combo_id"]]
    previous = {i["slot"]: i["recipe_id"] for i in first["plan"]["items"]}
    second, _ = run_case(5, setup=setup, action="regenerate", current_plan=previous, combo_history=history)
    assert not set(previous.values()) & {i["recipe_id"] for i in second["plan"]["items"]}
    for _ in range(10):
        result, _ = run_case(5, setup=setup, action="regenerate", current_plan=previous,
                             locked_slots=["main:1"], combo_history=history)
        assert result["plan"]
        assert result["daily_combo_id"] not in history
        next_plan = {i["slot"]: i["recipe_id"] for i in result["plan"]["items"]}
        assert next_plan["main:1"] == previous["main:1"]
        history.append(result["daily_combo_id"])
        previous = next_plan
    result, _ = run_case(5, setup=setup, action="regenerate", current_plan=previous,
        locked_slots=["main:1"], combo_history=history)
    # Three possible second mains * two vegetables * two soups =12 combinations.
    if result["plan"]:
        history.append(result["daily_combo_id"])
        previous = {i["slot"]: i["recipe_id"] for i in result["plan"]["items"]}
    assert run_case(5, setup=setup, action="regenerate", current_plan=previous,
        locked_slots=["main:1"], combo_history=history)[0]["plan"] is None


def test_daily_exclusion_remains_hard_and_custom_seven_dishes_stays_invalid():
    assert run_case(5, excluded_ids=[1001])[0]["plan"] is None
    with pytest.raises(ProtocolError):
        planner.validate({"layout_mode":"custom", "counts":{"main":5,"vegetable":1,"soup":1}}, "test-daily")
    with pytest.raises(ProtocolError):
        portion_options({"recipe_ids":list(range(1,8)),"people":12,"layout_mode":"custom"})


def test_daily_unconfirmed_pin_is_preserved_with_specific_reason():
    recipes, classification, catalog = synthetic()
    revisions = dict(catalog.revisions)
    revisions[1] = replace(revisions[1], data_status='needs_review', data_evidence='')
    result, _ = run_case(setup=(recipes,classification,replace(catalog,revisions=revisions)),
                         current_plan={'main:1':1},locked_slots=['main:1'])
    assert result['plan'] is None
    assert result['reason']['code'] == 'PINNED_PORTION_UNCONFIRMED'


def test_daily_prominent_ingredient_across_roles_and_bounded_search(monkeypatch):
    recipes, classification, catalog = synthetic(5, mains=4,vegetables=2,soups=1)
    recipes = [dict(r,daily_prominent_ids={44} if r['id'] in (30,50) else {r['id']+1000}) for r in recipes]
    result, _ = run_case(setup=(recipes,classification,catalog))
    assert next(i['recipe_id'] for i in result['plan']['items'] if i['slot']=='vegetable:1') == 31
    monkeypatch.setattr(planner,'DAILY_LAYOUT_SEARCH_LIMIT',1)
    limited, _ = run_case(setup=(recipes,classification,catalog))
    assert limited['plan'] is None
    assert limited['daily_combo_search']['complete'] is False


# Reuse the existing private-instance fixture; no demo credentials are used.
from tests.test_unified_http_tcp import unified_http_stack, private_mysql, _sql


def test_daily_http_tcp_private_mysql_qualification_and_custom_invariance(unified_http_stack):
    import mysql.connector
    from decimal import Decimal, ROUND_CEILING
    from fastapi.testclient import TestClient
    app, repo, _, _, config, _ = unified_http_stack
    connection = mysql.connector.connect(**config)
    try:
        unit = _sql(connection, "SELECT unit_id FROM units WHERE code='g'")[0][0]
        roles = {**{i:"main" for i in range(10,20)}, **{i:"vegetable" for i in range(30,34)},
                 **{i:"soup" for i in range(50,54)}}
        for iid,name in ((10,'thit heo xay'),(11,'cai thao'),(12,'dau phu')):
            _sql(connection,"INSERT INTO ingredients(ingredient_id,name,normalized_name,is_active) VALUES(%s,%s,%s,1)",(iid,name,name))
        for rid, role in roles.items():
            _sql(connection, """INSERT INTO recipes(recipe_id,title,normalized_title,description,role,minutes_total,
                instructions_legacy,is_public,servings,portion_data_status,portion_data_evidence)
                VALUES(%s,%s,%s,'TEST_ONLY',%s,10,'TEST_ONLY instructions',1,4,'verified',
                'base_servings=4; servings_source: TEST_ONLY simulated source explicitly states base servings')""", (rid,f"TEST_ONLY {rid}",f"test only {rid}",role))
            _sql(connection, """INSERT INTO recipe_ingredients(recipe_id,line_no,ingredient_id,quantity_text,
                amount_kind,amount_min,unit_id,requirement,purpose,measurement_basis,ingredient_form,scaling_mode)
                VALUES(%s,1,%s,'TEST_ONLY 100 g','exact',100,%s,'required','main','gross','test_raw','linear')""", (rid,{'main':10,'vegetable':11,'soup':12}[role],unit))
        tag = _sql(connection,"INSERT INTO recipe_tags(tag_type,code,label,normalized_label) VALUES('occasion','daily','TEST_ONLY daily','test only daily')")
        for rid in roles:
            _sql(connection,"INSERT INTO recipe_tag_links(recipe_id,tag_id) VALUES(%s,%s)",(rid,tag))
        with TestClient(app) as web:
            for people in range(1,13):
                layout = required_counts(people)
                for role in ("main","vegetable","soup"):
                    base = ceil(people/layout["main"]) if role == "main" else people
                    _sql(connection,"UPDATE recipes SET servings=%s,portion_data_evidence=%s WHERE recipe_id>=10 AND role=%s",(base,f"base_servings={base}; servings_source: TEST_ONLY simulated original serving statement",role))
                for role,share,factor in [('main',Decimal('.60'),Decimal('.735')),('vegetable',Decimal('.25'),Decimal('.765')),('soup',Decimal('.15'),Decimal('.931'))]:
                    per_recipe=Decimal(people)*350*share/(layout['main'] if role=='main' else 1)
                    raw=(per_recipe/factor).quantize(Decimal('.000001'),rounding=ROUND_CEILING)
                    _sql(connection,"UPDATE recipe_ingredients ri JOIN recipes r USING(recipe_id) SET ri.amount_min=%s WHERE r.recipe_id>=10 AND r.role=%s",(raw,role))
                custom = {"recipe_ids":[10,11,30,50],"people":people,"layout_mode":"custom"}
                before = web.post('/api/meal-plan/calculate',json=custom).json()['data']
                response = web.post('/api/meal-plan/v2',json={"people":people,"adaptive_daily":True})
                assert response.status_code == 200, response.text
                data = response.json()['data']
                assert data['plan'], (people,data['reason'],repo.meal_classification_for_connection(connection,Classification('test',{})))
                assert data['counts'] == layout
                ids = [i['recipe_id'] for i in data['plan']['items']]
                portion = web.post('/api/meal-plan/calculate',json={"recipe_ids":ids,"people":people})
                assert portion.status_code == 200, portion.text
                calc = portion.json()['data']
                assert calc['totals_complete']
                expected=sum(Fraction(str(repo.calculation_catalog(connection,[rid]).revisions[rid].lines[0].amount_min)) for rid in ids)
                assert sum(Fraction(i['quantity_value']) for i in calc['known_ingredients']) == expected
                assert calc['daily_demo']['status']=='conditional'
                after = web.post('/api/meal-plan/calculate',json=custom).json()['data']
                assert before == after
                if people in (2,5,8,12):
                    original_daily = data
                    assert web.post('/api/meal-plan/v2',json={'people':people,'adaptive_daily':True,'season':'ALL'}).json()['data'] == original_daily
                    for selected_season in ('SPRING','SUMMER','AUTUMN','WINTER'):
                        seasonal_response = web.post('/api/meal-plan/v2',json={
                            'people':people,'adaptive_daily':True,'season':selected_season,'weather':'hot'})
                        assert seasonal_response.status_code == 200, seasonal_response.text
                        seasonal_data = seasonal_response.json()['data']
                        assert seasonal_data['plan'] and seasonal_data['season']==selected_season
                        assert seasonal_data['weather']=='hot'  # Winter never forces cold weather.
                        assert seasonal_data['seasonal_assessment']['items']
                    assert web.post('/api/meal-plan/calculate',json=custom).json()['data'] == before
            current = {i['slot']:i['recipe_id'] for i in data['plan']['items']}
            transition={'people':12,'layout_mode':'custom','counts':{'main':2,'vegetable':2,'soup':2},'current_plan':current}
            moved=web.post('/api/meal-plan/v2',json=transition)
            assert moved.status_code==200, moved.text
            assert len(moved.json()['data']['plan']['items'])==6
            pinned=web.post('/api/meal-plan/v2',json={**transition,'locked_slots':['main:5']})
            assert pinned.status_code==200, pinned.text
            assert pinned.json()['data']['reason']['code']=='PINNED_SLOT_REMOVED'
            assessment = web.post('/api/meal-plan/assess',json={
                'request':{'adaptive_daily':True,'people':12,'current_plan':current,'counts':required_counts(12)},
                'adults':12,'children':0,'propose':True})
            assert assessment.status_code == 200, assessment.text
            advice = assessment.json()['data']
            assert advice['selection']['plan']
            assert advice['proposal']['plan'], advice['proposal']['reason']
            assert advice['proposal']['layout_mode'] == 'automatic'
            assert advice['proposal']['daily_selection_policy'] == 'daily-demo-food-v1'
            assert {i['recipe_id'] for i in advice['proposal']['plan']['items']} != set(current.values())
            # Exercise real seven-dish rendering on an ephemeral test web port;
            # the demo's fixed ports and database are never changed.
            import threading
            import time
            import uvicorn
            from playwright.sync_api import sync_playwright
            from tests.test_unified_http_tcp import _port
            port = _port()
            server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error'))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic()+10
                while not server.started and time.monotonic()<deadline:
                    time.sleep(.02)
                assert server.started
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(channel='msedge',headless=True)
                    for width in (1365,390):
                        page = browser.new_page(viewport={'width':width,'height':900})
                        errors=[]
                        page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(f'http://127.0.0.1:{port}/meal-plan')
                        page.wait_for_function("!document.querySelector('#meal-generate').disabled")
                        # Source rows currently have twelve-person original
                        # servings; a four-person meal must not be proposed.
                        page.wait_for_timeout(800)
                        for _ in range(8):
                            page.locator('#meal-adults-plus').click()
                        page.wait_for_function("document.querySelectorAll('[data-replace]').length===7",timeout=15000)
                        page.wait_for_function("!document.querySelector('#meal-shopping').classList.contains('hidden')")
                        page.wait_for_timeout(500)
                        assert page.locator('#meal-daily-service').is_visible()
                        assert '\u01af\u1edaC T\u00cdNH' in page.locator('#meal-daily-service').inner_text()
                        assert not page.locator('[data-replace]:disabled').count()
                        for selected_season in ('SPRING','SUMMER','AUTUMN','WINTER','ALL'):
                            with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/v2'),timeout=30000) as seasonal_reply:
                                page.locator('#meal-season').select_option(selected_season)
                            seasonal_result=seasonal_reply.value.json()['data']
                            assert seasonal_result['plan']
                            assert seasonal_result.get('season','ALL')==selected_season
                            page.wait_for_function("s=>(JSON.parse(sessionStorage.getItem('goiy-meal-plan-v2'))?.view?.data?.season||'ALL')===s",arg=selected_season)
                            page.wait_for_function("!document.querySelector('#meal-shopping').classList.contains('hidden')")
                            assert page.locator('#meal-season').input_value()==selected_season
                            if selected_season!='ALL':
                                page.wait_for_function("document.querySelector('#meal-reasons').textContent.toLowerCase().includes('mùa')")
                                assert 'mùa' in page.locator('#meal-reasons').inner_text().lower()
                        assert not errors
                        page.close()
                    browser.close()
            finally:
                server.should_exit=True
                thread.join(timeout=5)
                assert not thread.is_alive()
            # Remove serving proof only in this synthetic private database.
            _sql(connection,"UPDATE recipes SET portion_data_status='estimated',portion_data_evidence='TEST_ONLY quantity estimate only' WHERE recipe_id>=10")
            rejected = web.post('/api/meal-plan/v2',json={"people":12,"adaptive_daily":True}).json()['data']
            assert rejected['plan'] is not None  # Demo policy does not require serving-proof notes.
    finally:
        connection.close()
