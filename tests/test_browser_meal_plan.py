from pathlib import Path
import os
import shutil
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from source.web.main import app
from tests.test_web_meal_plan import meal_web


def current_custom_journey(browser_path,base,width,journey,repository,monkeypatch):
    """Current UI + real HTTP/TCP, with explicitly synthetic reviewed v2 amounts.

    SQLite deliberately has no trusted Daily food catalog. Daily automatic
    structures/seasons are exercised on private MySQL in the Daily integration
    tests; these journeys retain the Custom selection/allocation/state checks.
    """
    from playwright.sync_api import sync_playwright
    from tests.calculation_fixtures import fixture_catalog
    from fractions import Fraction
    import json
    from dataclasses import replace
    def catalog_for(_c,ids):
        catalog=fixture_catalog(tuple(ids))
        return replace(catalog,revisions={rid:replace(rev,lines=tuple(
            replace(line,name='TEST_ONLY <img src=x onerror=alert(1)>') if line.ingredient_id==1001 else line
            for line in rev.lines)) for rid,rev in catalog.revisions.items()})
    monkeypatch.setattr(repository,'calculation_catalog',catalog_for)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path=str(browser_path),headless=True)
        page=browser.new_page(viewport={'width':width,'height':900})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(base+'/meal-plan')
        page.wait_for_function("!document.querySelector('#meal-generate').disabled")
        with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/calculate')) as reply:
            page.locator('[data-meal-type="custom"]').click()
        assert reply.value.status==200
        def saved():return page.evaluate("JSON.parse(sessionStorage.getItem('goiy-meal-plan-v2'))")
        def ready():page.wait_for_function("!document.querySelector('#meal-shopping').classList.contains('hidden')&&!document.querySelector('#meal-shopping-note').textContent.startsWith('Đang')")
        def mapping():return {i['slot']:i['recipe_id'] for i in saved()['view']['data']['plan']['items']}
        ready();assert len(mapping())==3
        assert page.locator('#meal-season').is_hidden()
        if journey=='browser_meal_plan_v2.mjs':
            # Current manual structure: 3 mains + 2 vegetables + 1 soup.
            for group in ['main','main','vegetable']:
                with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/calculate')):
                    page.locator('[data-layout-plus="'+group+'"]').click()
                ready()
            assert saved()['conditions']['counts']=={'main':3,'vegetable':2,'soup':1}
            assert len(mapping())==6
            assert page.locator('[data-layout-plus]:not(:disabled)').count()==0
        elif journey=='browser_meal_plan_vegetarian.mjs':
            with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/calculate')):
                page.locator('#meal-pref-diet').select_option('vegetarian')
            ready();assert set(mapping().values())<={4,44,5,9,6,32}
            assert saved()['conditions']['preferences']['diet']=='vegetarian'
        page.locator('[data-pin="main:1"]').click();held=mapping()['main:1']
        initial=mapping()
        if journey=='browser_meal_plan_people.mjs':
            current=4
            for n in [2,4,6,8,12,4]:
                with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/calculate') and r.request.post_data_json['people']==n) as reply:
                    for _ in range(abs(n-current)):page.locator('#meal-adults-'+('plus' if n>current else 'minus')).click()
                calc=reply.value.json()['data'];current=n;ready()
                assert calc['status']=='COMPLETE' and calc['totals_complete']
                # Fixture source: 100 g/2 servings + two x 50 g/4 servings.
                amount=next(i for i in calc['known_ingredients'] if i['ingredient_id']==1001)
                assert Fraction(amount['quantity_value'])==75*n
                liquid=next(i for i in calc['known_ingredients'] if i['unit']=='ml')
                assert Fraction(liquid['quantity_min'])==100*n and Fraction(liquid['quantity_max'])==150*n
                assert page.locator('#meal-shopping-required img').count()==0
                assert mapping()==initial
                assert page.locator('[data-pin="main:1"]').get_attribute('aria-pressed')=='true'
            # Outage keeps the user's food and visibly reports failed calculation.
            page.route('**/api/meal-plan/calculate',lambda route:route.fulfill(status=503,content_type='application/json',body=json.dumps({'ok':False,'error':{'code':'UPSTREAM_UNAVAILABLE','message':'TEST_ONLY outage'}})),times=1)
            with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/calculate')):
                page.locator('#meal-adults-plus').click()
            page.wait_for_function("document.querySelector('#meal-shopping-note').textContent.includes('Chưa thể tính khẩu phần. Hãy thử lại.')")
            assert mapping()==initial and page.locator('#meal-shopping').is_visible()
            with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/calculate')):page.locator('#meal-adults-minus').click()
            ready()
            # Deliver an old calculation after the latest one; it must not win.
            page.evaluate("""()=>{const original=window.fetch;let held=false;window.fetch=(url,opts)=>{
              if(String(url).endsWith('/api/meal-plan/calculate')&&JSON.parse(opts.body).people===3&&!held){held=true;return new Promise(resolve=>{
                original(url,{...opts,signal:undefined}).then(r=>window.releaseOld=()=>resolve(r));});}
              return original(url,opts);};}""")
            page.locator('#meal-adults-minus').click()
            page.wait_for_function("typeof window.releaseOld==='function'")
            with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/calculate') and r.request.post_data_json['people']==4):page.locator('#meal-adults-plus').click()
            ready();latest=page.locator('#meal-portion-summary').inner_text()
            page.evaluate('window.releaseOld()');page.wait_for_timeout(350)
            assert page.locator('#meal-portion-summary').inner_text()==latest
            assert mapping()==initial
        else:
            before=mapping()
            with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/calculate')):
                page.locator('[data-replace="vegetable:1"]').click()
            ready();after=mapping()
            assert after['vegetable:1']!=before['vegetable:1']
            assert all(after[k]==v for k,v in before.items() if k!='vegetable:1')
            with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/calculate')):page.locator('#meal-regenerate').click()
            ready();assert mapping()!=after and mapping()['main:1']==held
        before=saved()
        with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/calculate')):page.reload()
        ready();after=saved()
        for key in ['conditions','pins','history']:assert after[key]==before[key],key
        assert after['view']['data']==before['view']['data']
        assert mapping()['main:1']==held
        assert page.locator('#meal-portion-summary').is_visible()
        if journey=='browser_meal_plan_vegetarian.mjs':
            page.locator('[data-pin="main:1"]').click()
            with page.expect_response(lambda r:r.url.endswith('/api/meal-plan/v2')) as reply:
                page.locator('[data-exclude="5"]').click()
            assert reply.value.json()['data']['plan'] is None
            assert saved()['conditions']['excluded_ids']==[5]
            assert 'chay' in page.locator('#meal-message').inner_text().lower()
            assert set(mapping().values())<={4,44,5,9,6,32}
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        assert not errors,errors
        browser.close()


@pytest.mark.parametrize("width", [1280,390], ids=["desktop","mobile"])
@pytest.mark.parametrize("journey", ["browser_meal_plan.mjs", "browser_meal_plan_v2.mjs", "browser_meal_plan_people.mjs", "browser_meal_plan_vegetarian.mjs"], ids=["legacy", "flexible", "people", "vegetarian"])
def test_meal_plan_browser_journey(meal_web, tmp_path: Path, width, journey, monkeypatch):
    if journey == "browser_meal_plan_vegetarian.mjs":
        from tests.vegetarian_fixtures import install_private_fixture
        install_private_fixture(meal_web[1].repository, monkeypatch)
    node = shutil.which("node")
    browser = next((path for root in (os.getenv("PROGRAMFILES"),os.getenv("PROGRAMFILES(X86)")) if root
                    for relative in ("Google/Chrome/Application/chrome.exe","Microsoft/Edge/Application/msedge.exe")
                    if (path := Path(root)/relative).is_file()), None)
    if not node or not browser:
        pytest.skip("Meal UI tests require Node 22+ and installed Chrome/Edge")
    capability = subprocess.run([node,"-e","process.exit(typeof WebSocket==='function'&&typeof fetch==='function'?0:1)"],capture_output=True,timeout=10)
    if capability.returncode:
        pytest.skip("Meal UI tests require built-in Node WebSocket/fetch")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=port,log_level="error"))
    thread = threading.Thread(target=server.run,daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        if journey!='browser_meal_plan.mjs':
            current_custom_journey(browser,f'http://127.0.0.1:{port}',width,journey,meal_web[1].repository,monkeypatch)
            return
        profile = tmp_path/"chrome"
        profile.mkdir()
        result = subprocess.run([node,str(Path(__file__).with_name(journey)),str(browser),
                                 f"http://127.0.0.1:{port}",str(profile),str(width)],
                                capture_output=True,text=True,encoding="utf-8",timeout=120)
        assert result.returncode == 0, result.stdout+result.stderr
        print(result.stdout.encode("ascii",errors="backslashreplace").decode("ascii"))
    finally:
        server.should_exit = True
        thread.join(timeout=5)
