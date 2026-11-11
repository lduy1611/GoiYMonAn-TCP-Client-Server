"""Conservative review gate and real HTTP/TCP fixture transport; no MySQL writes."""
from collections import Counter
from copy import deepcopy

import pytest

from source.common.protocol import encode_frame
from source.server import vegetarian
from source.server.meal_plan import default_classification
from source.server.meal_plan_v2 import generate,validate
from source.server.meal_preferences import load
from tests.meal_plan_fixtures import full_dataset,sql_rows,REQUEST_ID
from tests.test_web_meal_plan import meal_web
from tests.vegetarian_fixtures import fixture_data,review_for,install_private_fixture


def test_real_legacy_audit_has_zero_verified_and_never_infers_chay_from_titles():
    recipes,details=full_dataset();names={r[0]:r[1] for r in sql_rows('ingredients')}
    catalog=load(recipes,names,default_classification(),details)
    assert not catalog.vegetarian_ids
    assert Counter(r['status'] for r in catalog.vegetarian_assessments.values())=={'INCOMPATIBLE':47,'NEEDS_VERIFICATION':3}
    assert {rid for rid,r in catalog.vegetarian_assessments.items() if r['status']=='NEEDS_VERIFICATION'}=={4,5,9}
    for rid in (32,44,45,47):
        assert 24 in catalog.vegetarian_assessments[rid]['animal_ingredient_ids']
    for people in (1,4,6,8,12):
        result=generate(recipes,validate({'people':people,'preferences':{'diet':'vegetarian'}},REQUEST_ID),default_classification(),REQUEST_ID,catalog)
        assert result['plan'] is None and result['reason']['code']=='INSUFFICIENT_VEGETARIAN_GROUP'
    assert catalog.capabilities(layout_support=True)['choices']['diet'][1]['supported_people']==[]
    for rid in (4,5,9):
        recipe=deepcopy(next(r for r in details if r['id']==rid))
        # The read-only live DB has expanded instructions compared with SQL test
        # literals. Reproduce its unresolved seasoning explicitly in this fixture.
        recipe['instructions']+=' TEST_ONLY: nêm vừa ăn.'
        assert vegetarian.assess(recipe,review_for(recipe))['status']=='NEEDS_VERIFICATION'


@pytest.mark.parametrize('iid,name',[(1,'Trứng'),(4,'Thịt'),(13,'Cá basa'),(14,'Thịt gà'),(24,'Nước mắm'),
    (26,'Mắm ruốc'),(28,'Cua đồng'),(29,'Giò sống'),(35,'Tôm'),(36,'Mực'),(37,'Thịt bò'),(38,'Thịt heo xay'),(39,'Sườn heo'),(900,'Sữa')])
@pytest.mark.parametrize('required',[True,False],ids=['required','optional'])
def test_animal_component_vetoes_even_a_claimed_verified_review(iid,name,required):
    _,details,_,_=fixture_data();recipe=next(d for d in details if d['id']==4)
    recipe['ingredients'].append({'id':iid,'name':name,'quantity':'TEST_ONLY','is_required':required})
    assert vegetarian.assess(recipe,review_for(recipe))['status']=='INCOMPATIBLE'


@pytest.mark.parametrize('instruction',['Nêm nước mắm.','Thêm thịt gà.','Dùng sữa và mật ong.','Add fish sauce.'])
def test_instruction_only_animal_component_is_not_lost(instruction):
    _,details,_,_=fixture_data();recipe=next(d for d in details if d['id']==4)
    recipe['instructions']+=' '+instruction
    assert vegetarian.assess(recipe,review_for(recipe))['status']=='INCOMPATIBLE'


@pytest.mark.parametrize('change',[
    {'status':'NEEDS_VERIFICATION'},{'status':'DRAFT'},{'status':'APPROVED'},
    {'components_complete':False},{'instructions_complete':False},{'optional_components_included':False},
    {'unresolved':['TEST_ONLY unknown seasoning']},{'ingredient_evidence':[]},
    {'reviewer_ref':None},{'snapshot_sha256':'0'*64}, {'profile':'unknown'},
    {'instruction_only_components':[{'name':'unknown sauce','classification':'unknown','evidence_ref':None}]},
])
def test_incomplete_or_stale_proof_is_never_a_positive_review(change):
    _,details,_,_=fixture_data();recipe=next(d for d in details if d['id']==4)
    assert vegetarian.assess(recipe,{**review_for(recipe),**change})['status']=='NEEDS_VERIFICATION'


def test_snapshot_change_or_missing_details_revokes_positive_eligibility(monkeypatch):
    recipes,details,names,reviews=fixture_data();monkeypatch.setattr(vegetarian,'read_reviews',lambda:reviews)
    assert load(recipes,names,default_classification(),details).vegetarian_ids=={4,44,5,9,6,32}
    assert not load(recipes,names,default_classification()).vegetarian_ids
    changed=deepcopy(details);next(d for d in changed if d['id']==4)['instructions']+=' TEST_ONLY unknown seasoning.'
    assert 4 not in load(recipes,names,default_classification(),changed).vegetarian_ids
    candidate=deepcopy(recipes);next(r for r in candidate if r['id']==4)['all_ids'].add(24)
    assert 4 not in load(candidate,names,default_classification(),details).vegetarian_ids


def test_all_selected_dishes_are_verified_and_structure_support_is_server_derived(monkeypatch):
    recipes,details,names,reviews=fixture_data();monkeypatch.setattr(vegetarian,'read_reviews',lambda:reviews)
    catalog=load(recipes,names,default_classification(),details)
    assert catalog.capabilities(layout_support=True)['choices']['diet'][1]['supported_people']==list(range(1,13))
    for n in range(1,13):
        result=generate(recipes,validate({'people':n,'preferences':{'diet':'vegetarian'}},REQUEST_ID),default_classification(),REQUEST_ID,catalog)
        assert result['plan'] and all(i['recipe_id'] in catalog.vegetarian_ids for i in result['plan']['items'])
    for rid in (6,32):reviews.pop(rid)
    partial=load(recipes,names,default_classification(),details)
    assert partial.capabilities(layout_support=True)['choices']['diet'][1]['supported_people']==[1,2]
    assert not partial.capabilities()['choices']['diet'][1]['enabled']
    assert 'supported_people' not in partial.capabilities()['choices']['diet'][1]


def test_real_http_tcp_vegetarian_filter_pins_shortage_and_legacy_operations(meal_web,monkeypatch):
    web,server=meal_web;install_private_fixture(server.repository,monkeypatch)
    catalog=web.get('/api/meal-plan/filters?layout_support=true').json()['data']
    assert catalog['choices']['diet'][1]['recipe_count']==6
    assert catalog['choices']['diet'][1]['supported_people']==list(range(1,13))
    assert 'supported_people' not in web.get('/api/meal-plan/filters').json()['data']['choices']['diet'][1]
    old_calls=[('/api/meal-plan',{}),('/api/meal-plan/v2',{}),('/api/search',{'query':'cá'}),
               ('/api/recommend',{'ingredient_ids':[1,2],'algorithm':'baseline'}),('/api/recommend',{'ingredient_ids':[1,2],'algorithm':'proposed'})]
    before=[web.post(path,json=body).json()['data'] for path,body in old_calls]
    body={'people':4,'preferences':{'diet':'vegetarian'}}
    response=web.post('/api/meal-plan/v2',json=body)
    assert response.status_code==200
    data=response.json()['data'];assert {i['recipe_id'] for i in data['plan']['items']}<={4,44,5,9,6,32}
    current={i['slot']:i['recipe_id'] for i in data['plan']['items']}
    replaced=web.post('/api/meal-plan/v2',json={**body,'current_plan':current,'locked_slots':['main:1'],'replace_slot':'vegetable:1'}).json()['data']
    assert replaced['plan'] and replaced['plan']['items'][0]['recipe_id']==current['main:1']
    assert replaced['changed_slots']==['vegetable:1']
    incompatible=web.post('/api/meal-plan/v2',json={**body,'current_plan':{'main:1':7},'locked_slots':['main:1']}).json()['data']
    assert incompatible['plan'] is None and incompatible['reason']['code']=='LOCKED_RECIPE_INCOMPATIBLE'
    short=web.post('/api/meal-plan/v2',json={**body,'excluded_ids':[5]}).json()['data']
    assert short['plan'] is None and short['reason']['code']=='INSUFFICIENT_VEGETARIAN_GROUP'
    assert web.post('/api/meal-plan/v2',json={**body,'max_minutes':1}).json()['data']['plan'] is None
    six=web.post('/api/meal-plan/v2',json={**body,'people':12})
    assert len(six.json()['data']['plan']['items'])==6 and len(encode_frame(six.json()))<=65540
    calc=web.post('/api/meal-plan/calculate',json={'people':4,'recipe_ids':list(current.values())}).json()['data']
    assert calc['status']=='INCOMPLETE' and not calc['known_ingredients']
    assert [web.post(path,json=body).json()['data'] for path,body in old_calls]==before
