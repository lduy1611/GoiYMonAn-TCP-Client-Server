"""TEST_ONLY approvals on an isolated mysqld; NEVER loads project credentials."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

import mysql.connector
import pytest
import uvicorn
from fastapi.testclient import TestClient

from source.common.catalog_ids import v2_public_id, valid_public_id, UINT32_MAX, MAX_PUBLIC_ID
from source.client.tcp_client import TCPClient
from source.common.protocol import ProtocolError, encode_frame
from source.database import migrate_v2
from source.server import mysql_calculation_catalog as portions
from source.server import mysql_recipe_catalog as publication
from source.server.repository import MySQLRepository
from source.server.handler import dispatch
from source.web.meal_plan_v2_contract import Data as MealData
from source.web.meal_plan_v2_contract import Request as MealPlanV2Request
from source.web.meal_plan_calculation_contract import CalculationData, CalculationRequest
from pydantic import ValidationError
from tests.mysql_v2_fixtures import private_mysql, mysql_db, sql, legacy_hashes
from tests.meal_plan_fixtures import running_repository, REQUEST_ID
from source.web.main import app


def fixture_publication(connection, *, animal=False, staged=False):
    """Fabricated, source-free TEST_ONLY records/decisions, never real approval."""
    assert sql(connection,'SELECT DATABASE() AS name')[0]['name'].startswith('goiy_v2_test_')
    migrate_v2.run(connection,'apply')
    before=legacy_hashes(connection)
    sql(connection,"""INSERT INTO v2_sources(id,source_kind,title,url,document_ref,accessed_at,verification_status)
        VALUES(1,'TEST_ONLY','TEST_ONLY simulated source','https://example.test/TEST_ONLY/',
        'TEST_ONLY NOT REAL EVIDENCE',UTC_TIMESTAMP(6),'APPROVED')""")
    for iid,name in [(71,'TEST_ONLY plant'),(72,'ordinary fish sauce' if animal else 'TEST_ONLY salt')]:
        sql(connection,"""INSERT INTO v2_ingredients(id,canonical_name,normalized_name,identity_status,evidence_set_id)
            VALUES(%s,%s,%s,'APPROVED',NULL)""",(iid,name,name))
    for n in range(1,7):
        sql(connection,"INSERT INTO v2_recipes(id,origin_kind) VALUES(%s,'curated_new')",(n,))
        sql(connection,"""INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,instructions,minutes,
            base_servings,serving_basis,content_complete,status,content_evidence_set_id)
            VALUES(%s,%s,1,%s,'TEST_ONLY stir plant',10,2,'source_servings',1,'APPROVED',NULL)""",
            (200+n,n,f'TEST_ONLY V2 recipe {n}'))
        for line,iid,required in ([(1,71,'required'),(2,72,'optional')] + ([(3,71,'required')] if staged else [])):
            sql(connection,"""INSERT INTO v2_recipe_ingredient_lines(revision_id,line_no,ingredient_id,quantity_raw,
                amount_kind,amount_min,requirement,purpose,status) VALUES(%s,%s,%s,'TEST_ONLY 2 g','exact',2,%s,
                'consumed','NEEDS_VERIFICATION')""",(200+n,line,iid,required))
    sql(connection,"""INSERT INTO v2_data_releases(id,code,legacy_dataset_version,status,approved_at)
        VALUES(401,'TEST_ONLY PUBLICATION','TEST_ONLY_BASE','PUBLISHED',UTC_TIMESTAMP(6))""")
    for n in range(1,7):sql(connection,'INSERT INTO v2_release_recipes VALUES(401,%s,%s)',(n,200+n))
    sql(connection,'INSERT INTO v2_calculation_settings VALUES(1,NULL)')
    counter=iter(range(10000,20000))
    def evidence(group,scope,ref,value):
        eid=next(counter)
        sql(connection,"""INSERT INTO v2_evidence(id,source_id,locator,excerpt_or_observation,claim_scope,entity_ref,captured_at)
            VALUES(%s,1,'TEST_ONLY fixture',%s,%s,%s,UTC_TIMESTAMP(6))""",(eid,json.dumps(value),scope,ref))
        sql(connection,'INSERT INTO v2_evidence_set_members VALUES(%s,%s)',(group,eid))
    for n in range(1,7):
        group=1000+n;ref=f'revision:{200+n}'
        sql(connection,"INSERT INTO v2_evidence_sets VALUES(%s,'TEST_ONLY NOT REAL EVIDENCE')",(group,))
        sql(connection,'UPDATE v2_recipe_revisions SET content_evidence_set_id=%s WHERE id=%s',(group,200+n))
        evidence(group,'recipe_content',ref,{'TEST_ONLY':'invented source observation'})
        evidence(group,'recipe_publication',ref,{'TEST_ONLY':'invented publication evidence'})
        evidence(group,'role',ref,{'proposal':('main','vegetable','soup')[(n-1)//2],'status':'NEEDS_VERIFICATION'})
        evidence(group,'diet',ref,{'profile':'plant-only-v1','components_complete':True,'instructions_complete':True,
            'optional_components_included':True,'unresolved':[],
            'ingredient_evidence':[{'line_no':line,'ingredient_id':iid,'classification':'plant_or_mineral',
                                   'evidence_ref':'TEST_ONLY fabricated classification'} for line,iid in ([(1,71),(2,72)] + ([(3,71)] if staged else []))],
            'instruction_only_components':[]})
    for iid in (71,72):
        sql(connection,"INSERT INTO v2_evidence_sets VALUES(%s,'TEST_ONLY identity')",(iid,))
        sql(connection,'UPDATE v2_ingredients SET evidence_set_id=%s WHERE id=%s',(iid,iid))
        evidence(iid,'ingredient_identity',f'ingredient_identity:{iid}',{'TEST_ONLY':'identity'})
    sql(connection,"INSERT INTO v2_evidence_sets VALUES(9000,'TEST_ONLY release')")
    sql(connection,'UPDATE v2_data_releases SET evidence_set_id=9000 WHERE id=401')
    evidence(9000,'release','release:401',{'TEST_ONLY':'release'})
    snapshot=publication.read_publication_snapshot(connection,release_id=401)
    subjects=portions.claims(snapshot)
    subjects.update(publication.publication_claims(snapshot))
    for claim in subjects.values():
        if claim.scope not in ('release','recipe_content','ingredient_identity','recipe_publication','role','diet'):
            continue
        decision=next(counter)
        digest=portions.subject_hash(claim.scope,claim.payload)
        sql(connection,"""INSERT INTO v2_review_decisions VALUES(%s,'APPROVED','TEST_ONLY_SIMULATED_REVIEWER',
            UTC_TIMESTAMP(6),'TEST_ONLY NOT HUMAN APPROVAL',%s,%s,%s,%s)""",
            (decision,claim.scope,claim.entity_ref,digest,claim.evidence_set_id))
        if claim.scope=='release':
            sql(connection,'UPDATE v2_data_releases SET review_decision_id=%s,manifest_hash=%s WHERE id=401',(decision,digest))
        elif claim.scope=='recipe_content':
            sql(connection,'UPDATE v2_recipe_revisions SET content_review_id=%s WHERE id=%s',(decision,int(claim.entity_ref.split(':')[1])))
        elif claim.scope=='ingredient_identity':
            sql(connection,'UPDATE v2_ingredients SET review_decision_id=%s WHERE id=%s',(decision,int(claim.entity_ref.split(':')[1])))
    assert not publication.load_catalog(connection).details
    sql(connection,'UPDATE v2_calculation_settings SET active_release_id=401 WHERE id=1')
    assert legacy_hashes(connection)==before


@pytest.fixture
def released(mysql_db):
    connection,config=mysql_db
    fixture_publication(connection)
    return connection,MySQLRepository(config,pool_size=2)


def request(repo,op,payload):
    return dispatch(repo,{'version':1,'request_id':REQUEST_ID,'op':op,'payload':payload})[0]


def test_real_tcp_search_details_chay_pins_shopping_and_portions(released,monkeypatch,tmp_path):
    connection,repo=released
    before=legacy_hashes(connection)
    old=repo.get_recipe(connection,1)
    import source.server.main as server_main
    monkeypatch.setattr(server_main,'LOG_PATH',tmp_path/'TEST_ONLY-tcp.jsonl')
    with running_repository(repo) as (_,port):
        client=TCPClient(port=port,persistent=True)
        try:
            all_ids={v2_public_id(n) for n in range(1,7)}
            data=client.request('SEARCH_RECIPES',{'query':'TEST_ONLY V2','limit':20})['data']
            assert {r['recipe_id'] for r in data['items']}==all_ids
            for n in range(1,7):
                detail=client.request('GET_RECIPE',{'recipe_id':v2_public_id(n)})['data']
                assert detail['title']==f'TEST_ONLY V2 recipe {n}'
                assert detail['instructions']=='TEST_ONLY stir plant'
                assert [i['id'] for i in detail['ingredients']]==[v2_public_id(71),v2_public_id(72)]
            assert {k:v for k,v in client.request('GET_RECIPE',{'recipe_id':1})['data'].items() if k!='dataset_version'}==old
            filters=client.request('GET_MEAL_PLAN_FILTERS',{'layout_support':True})['data']
            assert filters['choices']['diet'][1]['recipe_count']==6
            assert filters['choices']['diet'][1]['supported_people']==list(range(1,13))
            for people in (2,4,6,8,12):
                data=client.request('GENERATE_MEAL_PLAN_V2',{'people':people,'preferences':{'diet':'vegetarian'}})['data']
                MealData.model_validate(data)
                ids=[r['recipe_id'] for r in data['plan']['items']]
                assert len(set(ids))==len(ids) and set(ids)<=all_ids
                assert data['plan']['shopping_list'][0]['ingredient_id']==v2_public_id(71)
            body={'people':4,'preferences':{'diet':'vegetarian'}}
            data=client.request('GENERATE_MEAL_PLAN_V2',body)['data']
            current={r['slot']:r['recipe_id'] for r in data['plan']['items']}
            changed=client.request('GENERATE_MEAL_PLAN_V2',{**body,'current_plan':current,'locked_slots':['main:1'],
                'replace_slot':'vegetable:1'})['data']
            assert changed['plan']['items'][0]['recipe_id']==current['main:1']
            assert changed['changed_slots']==['vegetable:1']
            for filters in ({'excluded_ids':[v2_public_id(72)]},{'max_minutes':1}):
                empty=client.request('GENERATE_MEAL_PLAN_V2',{**body,**filters})['data']
                assert empty['plan'] is None and empty['reason']['code']=='INSUFFICIENT_VEGETARIAN_GROUP'
            ingredient=client.request('LIST_INGREDIENTS',{'query':'TEST_ONLY plant','limit':50})['data']['items']
            assert ingredient==[{'id':v2_public_id(71),'name':'TEST_ONLY plant'}]
            calc=client.request('CALCULATE_MEAL_PLAN',{'recipe_ids':list(current.values()),'people':4})
            assert calc['ok'] and calc['data']['status']=='INCOMPLETE' and not calc['data']['known_ingredients']
            CalculationData.model_validate(calc['data'])
            assert len(encode_frame(calc))<=65540
            assert client.request('GET_RECIPE',{'recipe_id':v2_public_id(999)})['error']['code']=='NOT_FOUND'
            assert client.request('PING',{})['ok']
            for algorithm in ('baseline','proposed'):
                legacy=client.request('RECOMMEND',{'ingredient_ids':[1],'algorithm':algorithm})['data']
                assert all(r['recipe_id'] in (1,2) for r in legacy['items'])
        finally:client.close()
    assert legacy_hashes(connection)==before


@pytest.mark.parametrize('change',[
 "UPDATE v2_calculation_settings SET active_release_id=NULL",
 "UPDATE v2_data_releases SET status='NEEDS_VERIFICATION'",
 "UPDATE v2_sources SET verification_status='NEEDS_VERIFICATION'",
 "UPDATE v2_recipe_revisions SET status='DRAFT'",
 "UPDATE v2_recipe_revisions SET status='NEEDS_VERIFICATION'",
 "UPDATE v2_recipe_revisions SET content_complete=0",
 "UPDATE v2_recipe_revisions SET minutes=NULL",
 "UPDATE v2_ingredients SET identity_status='NEEDS_VERIFICATION'",
 "UPDATE v2_data_releases SET approved_at=NULL",
 "DELETE FROM v2_recipe_ingredient_lines",
])
def test_unreleased_unapproved_incomplete_data_never_leaks(released,change):
    connection,repo=released;sql(connection,change)
    assert request(repo,'SEARCH_RECIPES',{'query':'TEST_ONLY V2'})['data']['total']==0
    with pytest.raises(ProtocolError) as exc:request(repo,'GET_RECIPE',{'recipe_id':v2_public_id(1)})
    assert exc.value.code=='NOT_FOUND'


@pytest.mark.parametrize('change',[
 "UPDATE v2_recipe_revisions SET title='TEST_ONLY tampered' WHERE id=201",
 "UPDATE v2_recipe_revisions SET instructions='TEST_ONLY modified' WHERE id=201",
 "UPDATE v2_recipe_revisions SET base_servings=3 WHERE id=201",
 "UPDATE v2_recipe_ingredient_lines SET quantity_raw='TEST_ONLY changed' WHERE revision_id=201",
 "UPDATE v2_recipe_ingredient_lines SET amount_min=3 WHERE revision_id=201",
 "UPDATE v2_ingredients SET canonical_name='TEST_ONLY changed'",
 "UPDATE v2_sources SET url='https://example.test/TEST_ONLY/tampered/'",
])
def test_editing_reviewed_subject_invalidates_publication(released,change):
    connection,repo=released;sql(connection,change)
    with pytest.raises(ProtocolError) as exc:request(repo,'GET_RECIPE',{'recipe_id':v2_public_id(1)})
    assert exc.value.code=='NOT_FOUND'


def test_release_pins_exact_revision_and_search_orders_before_paging(released):
    connection,repo=released
    sql(connection,"""INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,instructions,status)
        VALUES(999,1,2,'TEST_ONLY draft must not replace published','TEST_ONLY','DRAFT')""")
    assert request(repo,'GET_RECIPE',{'recipe_id':v2_public_id(1)})['data']['title']=='TEST_ONLY V2 recipe 1'
    whole=request(repo,'SEARCH_RECIPES',{'query':'TEST_ONLY V2','limit':20})['data']['items']
    pages=sum((request(repo,'SEARCH_RECIPES',{'query':'TEST_ONLY V2','limit':2,'offset':n})['data']['items'] for n in (0,2,4)),[])
    assert pages==whole
    detail=repo.admin_get_recipe(connection,999)
    assert detail['published'] is False


def test_admin_recipe_filters_only_mark_valid_active_release_as_visible(released):
    connection,repo=released
    sql(connection,"""INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,instructions,status,minutes)
        VALUES(999,1,2,'TEST_ONLY hidden draft','TEST_ONLY', 'DRAFT',20)""")
    visible=repo.admin_list_recipes(connection,'TEST_ONLY V2',20,0,visibility='visible')
    hidden=repo.admin_list_recipes(connection,'TEST_ONLY',20,0,visibility='hidden')
    mains=repo.admin_list_recipes(connection,'TEST_ONLY V2',20,0,role='main')
    quick=repo.admin_list_recipes(connection,'TEST_ONLY',20,0,max_minutes=5)
    assert visible['total']==6 and all(row['visible'] and row['role'] for row in visible['items'])
    # One v2 identity is one Admin row: its active public revision stays visible,
    # while the editable draft is exposed through edit_revision_id rather than duplicated.
    assert hidden['total']==0
    unified=next(row for row in visible['items'] if row['recipe_id']==v2_public_id(1))
    assert unified['revision_id']==201 and unified['edit_revision_id']==999 and unified['visible']
    assert mains['total']==2 and all(row['role']=='main' for row in mains['items'])
    assert quick['total']==0


def test_admin_recipe_catalog_merges_legacy_and_v2_without_identity_duplicates(released):
    connection,repo=released
    sql(connection,"INSERT INTO v2_recipes(id,origin_kind,author_ref) VALUES(99,'curated_new','TEST_ONLY private recipe')")
    sql(connection,"""INSERT INTO v2_recipe_revisions
        (id,recipe_id,revision_no,title,instructions,minutes,status)
        VALUES(199,99,1,'TEST_ONLY private draft','TEST_ONLY instructions',15,'NEEDS_VERIFICATION')""")
    rows=repo.admin_list_recipes(connection,'TEST_ONLY',50,0)['items']
    ids=[row['recipe_id'] for row in rows]
    assert len(rows)==8
    assert len(ids)==len(set(ids))
    assert {1,2} <= set(ids)
    assert {v2_public_id(n) for n in range(1,7)} <= set(ids)
    assert v2_public_id(99) not in ids


def test_user_ingredient_catalog_keeps_legacy_and_exposes_only_admin_or_released_v2(released):
    from source.server.published_repository import PublishedRepository
    connection,repo=released
    sql(connection,"""INSERT INTO v2_ingredients(id,canonical_name,normalized_name,identity_status)
        VALUES(73,'TEST_ONLY unreviewed ingredient','test_only unreviewed ingredient','NEEDS_VERIFICATION')""")
    sql(connection,"""INSERT INTO v2_ingredients(id,canonical_name,normalized_name,identity_status)
        VALUES(74,'TEST_ONLY Admin ingredient','test_only admin ingredient','DRAFT')""")
    public=PublishedRepository(repo,publication.load_catalog(connection))
    rows=public.list_ingredients(connection,"",50)
    ids={row['id'] for row in rows}
    assert {1,2} <= ids
    assert {v2_public_id(71),v2_public_id(72)} <= ids
    assert v2_public_id(74) in ids
    assert v2_public_id(73) not in ids
    assert public.ingredient_ids_exist(connection,{1,v2_public_id(71),v2_public_id(74)})
    assert not public.ingredient_ids_exist(connection,{v2_public_id(73)})
    assert 'user-catalog-v2' in public.dataset_version(connection)


def test_animal_optional_ingredient_vetoes_claimed_test_diet(mysql_db):
    connection,config=mysql_db;fixture_publication(connection,animal=True)
    catalog=publication.load_catalog(connection)
    assert len(catalog.details)==6 and not catalog.plant_ids
    data=request(MySQLRepository(config,pool_size=1),'GENERATE_MEAL_PLAN_V2',{'people':4,'preferences':{'diet':'vegetarian'}})['data']
    assert data['plan'] is None and data['reason']['code']=='INSUFFICIENT_VEGETARIAN_GROUP'


def test_later_rejection_cannot_fall_back_to_old_diet_approval(released):
    connection,repo=released
    old=sql(connection,"SELECT * FROM v2_review_decisions WHERE claim_scope='diet' ORDER BY id LIMIT 1")[0]
    sql(connection,"""INSERT INTO v2_review_decisions VALUES(99000,'REJECTED','TEST_ONLY',
        TIMESTAMPADD(SECOND,1,UTC_TIMESTAMP(6)),'TEST_ONLY rejection',%s,%s,%s,%s)""",
        (old['claim_scope'],old['entity_ref'],old['subject_hash'],old['evidence_set_id']))
    catalog=publication.load_catalog(connection)
    assert len(catalog.details)==6 and len(catalog.plant_ids)==5


@pytest.mark.parametrize('scope',['role','diet'])
def test_missing_metadata_decision_or_changed_evidence_is_not_trusted(released,scope):
    connection,repo=released
    before=publication.load_catalog(connection)
    sql(connection,"UPDATE v2_evidence SET excerpt_or_observation='{}' WHERE claim_scope=%s AND entity_ref='revision:201'",(scope,))
    after=publication.load_catalog(connection)
    assert v2_public_id(1) not in after.plant_ids and before.version!=after.version
    assert (v2_public_id(1) not in after.details) == (scope=='role')


def test_repeated_ingredient_stages_preserve_raw_quantities_without_duplicate_shopping_use(mysql_db):
    connection,config=mysql_db;fixture_publication(connection,staged=True)
    repo=MySQLRepository(config,pool_size=1)
    detail=request(repo,'GET_RECIPE',{'recipe_id':v2_public_id(1)})['data']
    assert len(detail['ingredients'])==2
    assert detail['ingredients'][0]['quantity']=='TEST_ONLY 2 g; TEST_ONLY 2 g'
    data=request(repo,'GENERATE_MEAL_PLAN_V2',{'people':4,'preferences':{'diet':'vegetarian'}})['data']
    MealData.model_validate(data)
    assert all(len({r['recipe_id'] for r in row['uses']})==len(row['uses']) for row in data['plan']['shopping_list'])


def test_legacy_outputs_identical_with_publication_active_or_inactive(released):
    connection,repo=released;complete_test_legacy_catalog(connection)
    calls=[('GET_RECIPE',{'recipe_id':1}),('GENERATE_MEAL_PLAN',{}),
           *[('RECOMMEND',{'ingredient_ids':[1],'algorithm':a}) for a in ('baseline','proposed')]]
    active=[request(repo,op,body) for op,body in calls]
    sql(connection,'UPDATE v2_calculation_settings SET active_release_id=NULL')
    inactive=[request(repo,op,body) for op,body in calls]
    # Public picker/cache versions intentionally change with release state,
    # while the legacy recipe payload and algorithm output stay identical.
    assert active[0]["data"]["dataset_version"] != inactive[0]["data"]["dataset_version"]
    for left,right in zip(active,inactive):
        if isinstance(left.get("data"),dict):
            left["data"].pop("dataset_version",None)
        if isinstance(right.get("data"),dict):
            right["data"].pop("dataset_version",None)
    assert active==inactive


def test_absent_schema_is_legacy_only_but_mysql_error_is_reported(mysql_db,monkeypatch,tmp_path):
    connection,config=mysql_db;repo=MySQLRepository(config,pool_size=1)
    assert request(repo,'GET_RECIPE',{'recipe_id':1})['ok']
    assert request(repo,'SEARCH_RECIPES',{'query':'TEST_ONLY'})['data']['total']==2
    def fail(*args,**kwargs):raise mysql.connector.OperationalError('TEST_ONLY disconnect',errno=2013)
    monkeypatch.setattr(publication.proof,'_query',fail)
    import source.server.main as server_main
    monkeypatch.setattr(server_main,'LOG_PATH',tmp_path/'TEST_ONLY-error.jsonl')
    with running_repository(repo) as (_,port):
        client=TCPClient(port=port,persistent=True)
        try:
            result=client.request('SEARCH_RECIPES',{'query':'TEST_ONLY'})
            assert result['error']['code']=='DB_ERROR' and 'TEST_ONLY' not in result['error']['message']
            assert client.request('PING',{})['ok']
        finally:client.close()


def test_public_ids_are_injective_stable_json_safe_and_calculation_contract_accepts_them():
    assert v2_public_id(1)>UINT32_MAX and v2_public_id(UINT32_MAX)==MAX_PUBLIC_ID<2**53
    assert not valid_public_id(2**32) and not valid_public_id(True)
    with pytest.raises(ValueError):v2_public_id(0)
    CalculationRequest.model_validate({'recipe_ids':[v2_public_id(1)],'people':4})
    MealPlanV2Request.model_validate({'current_plan':{'main:1':v2_public_id(1)}})
    for invalid in (2**32,MAX_PUBLIC_ID+1,True):
        with pytest.raises(ValidationError):
            MealPlanV2Request.model_validate({'current_plan':{'main:1':invalid}})


def complete_test_legacy_catalog(connection):
    """Fill the 50-item picker with TEST_ONLY rows, never import real seeds."""
    assert sql(connection,'SELECT DATABASE() AS n')[0]['n'].startswith('goiy_v2_test_')
    for n in range(3,51):
        sql(connection,'INSERT INTO ingredients VALUES(%s,%s,%s)',(n,f'TEST_ONLY legacy ingredient {n}',f'test_only legacy ingredient {n}'))
        sql(connection,"INSERT INTO recipes VALUES(%s,%s,'TEST_ONLY legacy instructions',10,NULL,'TEST_ONLY synthetic')",(n,f'TEST_ONLY legacy recipe {n}'))


def test_real_http_gateway_accepts_public_ids_and_expanded_role_catalog(released,monkeypatch,tmp_path):
    connection,repo=released;complete_test_legacy_catalog(connection)
    import source.server.main as server_main
    monkeypatch.setattr(server_main,'LOG_PATH',tmp_path/'TEST_ONLY-http.jsonl')
    with running_repository(repo) as (_,port):
        monkeypatch.setenv('TCP_HOST','127.0.0.1');monkeypatch.setenv('TCP_PORT',str(port))
        with TestClient(app) as web:
            assert web.get('/api/meal-plan/filters?layout_support=true').json()['data']['role_recipe_count']==56
            result=web.post('/api/meal-plan/v2',json={'people':4,'preferences':{'diet':'vegetarian'}})
            assert result.status_code==200 and result.json()['data']['plan']
            ids=[i['recipe_id'] for i in result.json()['data']['plan']['items']]
            assert web.get(f'/recipes/{ids[0]}').status_code==200
            assert web.get(f'/api/recipes/{ids[0]}').status_code==200
            assert web.get(f'/api/recipes/{2**32}').status_code==422
            assert web.get(f'/api/recipes/{MAX_PUBLIC_ID+1}').status_code==422
            calc=web.post('/api/meal-plan/calculate',json={'recipe_ids':ids,'people':4})
            assert calc.status_code==200 and calc.json()['data']['status']=='INCOMPLETE'
            assert web.get(f'/recipes/{2**32}').status_code==422


@pytest.mark.parametrize('width',[1280,390],ids=['desktop','mobile'])
def test_published_v2_browser_after_50_legacy_ingredients(released,monkeypatch,tmp_path,width):
    connection,repo=released;complete_test_legacy_catalog(connection)
    node=shutil.which('node')
    browser=next((p for root in (os.getenv('PROGRAMFILES'),os.getenv('PROGRAMFILES(X86)')) if root
        for rel in ('Google/Chrome/Application/chrome.exe','Microsoft/Edge/Application/msedge.exe')
        if (p:=Path(root)/rel).is_file()),None)
    if not node or not browser:pytest.skip('Node + Chrome/Edge required for publication UI checks')
    import source.server.main as server_main
    monkeypatch.setattr(server_main,'LOG_PATH',tmp_path/'TEST_ONLY-browser.jsonl')
    with running_repository(repo) as (_,tcp_port):
        monkeypatch.setenv('TCP_HOST','127.0.0.1');monkeypatch.setenv('TCP_PORT',str(tcp_port))
        with socket.socket() as probe:probe.bind(('127.0.0.1',0));http_port=probe.getsockname()[1]
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=http_port,log_level='error'))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                time.sleep(.05)
            assert server.started
            profile=tmp_path/'chrome';profile.mkdir()
            result=subprocess.run([node,str(Path(__file__).with_name('browser_meal_plan_vegetarian.mjs')),str(browser),
                f'http://127.0.0.1:{http_port}',str(profile),str(width),'published-v2'],
                capture_output=True,text=True,encoding='utf-8',timeout=120)
            assert result.returncode==0,result.stdout+result.stderr
        finally:server.should_exit=True;thread.join(timeout=5)
