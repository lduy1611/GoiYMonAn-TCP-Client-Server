"""Regression coverage for safe recipe returns and per-slot replacement history."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from source.client.tcp_client import TCPClient
from source.common.protocol import ProtocolError
from source.server.meal_plan import Classification, SLOTS, default_classification, generate_meal_plan, validate_meal_plan
from tests.meal_plan_fixtures import REQUEST_ID, ROOT, full_dataset
from tests.test_meal_plan_integration import meal_tcp
from tests.test_web_meal_plan import meal_web

CURRENT = {"main":1,"vegetable":5,"soup":29}


def plan(payload, recipes=None, classification=None):
    if recipes is None:
        recipes,_=full_dataset()
    return generate_meal_plan(recipes,validate_meal_plan(payload,REQUEST_ID),classification or default_classification(),REQUEST_ID)


@pytest.mark.parametrize("history", [None, [], {"other":[]}, {"soup":None}, {"soup":[True]},
    {"soup":[0]}, {"soup":[-1]}, {"soup":[1.5]}, {"soup":["29"]}, {"soup":[29,29]},
    {"soup":list(range(1,52))}, {"main":list(range(1,26)),"soup":list(range(26,52))}])
def test_history_shape_is_strict_in_tcp_and_gateway(meal_web,history):
    payload={"current_plan":CURRENT,"avoid_recipe_ids":history}
    with pytest.raises(ProtocolError) as exc:
        validate_meal_plan(payload,REQUEST_ID)
    assert exc.value.code=="INVALID_PAYLOAD" and exc.value.request_id==REQUEST_ID
    assert meal_web[0].post('/api/meal-plan',json=payload).status_code==422


@pytest.mark.parametrize("payload", [
    {"avoid_recipe_ids":{"soup":[29]}},
    {"current_plan":CURRENT,"avoid_recipe_ids":{"soup":[999]}},
    {"current_plan":CURRENT,"avoid_recipe_ids":{"soup":[1]}},
    {"current_plan":CURRENT,"avoid_recipe_ids":{"main":[8]}},
])
def test_history_unknown_id_wrong_category_or_missing_current_is_rejected(meal_tcp,payload):
    client=TCPClient(port=meal_tcp[1],persistent=True)
    try:
        reply=client.request('GENERATE_MEAL_PLAN',payload,REQUEST_ID)
        assert not reply['ok'] and reply['error']['code']=='INVALID_PAYLOAD' and reply['request_id']==REQUEST_ID
        assert client.request('PING',{})['ok']
    finally: client.close()


def test_six_soups_are_visited_before_recycling_with_stable_ranking():
    def journey():
        current=dict(CURRENT);seen=[29];warnings=[]
        for _ in range(6):
            reply=plan({'ingredient_ids':[1,2,6,7],'max_minutes':60,'current_plan':current,
                'locked_slots':['main','vegetable'],'avoid_recipe_ids':{'soup':seen}})
            assert reply['changed_slots']==['soup']
            items={i['slot']:i['recipe_id'] for i in reply['plan']['items']}
            assert items['main']==1 and items['vegetable']==5 and items['soup']!=current['soup']
            warnings.append(reply['warnings']);seen.append(items['soup']);current=items
        return seen,warnings
    seen,warnings=journey()
    assert len(set(seen[:6]))==6 and set(seen[:6])=={6,28,29,30,31,32}
    assert all('HISTORY_RECYCLED' not in w for w in warnings[:5])
    assert warnings[-1]==['HISTORY_RECYCLED']
    assert journey()==(seen,warnings)


def test_two_candidates_recycle_but_never_return_unchanged():
    current={'main':1,'vegetable':5,'soup':30};seen=[30]
    for expected,warning in [(32,[]),(30,['HISTORY_RECYCLED'])]:
        reply=plan({'max_minutes':25,'current_plan':current,'locked_slots':['main','vegetable'],
                    'avoid_recipe_ids':{'soup':seen}})
        assert reply['plan']['items'][2]['recipe_id']==expected
        assert reply['warnings']==warning and reply['changed_slots']==['soup']
        seen.append(expected);current['soup']=expected


def test_history_never_relaxes_filters_or_changes_locked_dishes():
    payload={'ingredient_ids':[1,2,6,7],'max_minutes':60,'max_total_minutes':90,'max_missing':2,
             'current_plan':CURRENT,'locked_slots':['main','vegetable'],'avoid_recipe_ids':{'soup':[6,28,29,30,31,32]}}
    reply=plan(payload)
    assert reply['plan'] is None and reply['changed_slots']==[] and reply['reason']['code']=='NO_ALTERNATIVE'
    incompatible=plan({**payload,'ingredient_ids':[1,2,6],'excluded_ids':[7]})
    assert incompatible['reason']['code']=='LOCKED_RECIPE_INCOMPATIBLE'


def test_whole_plan_prefers_unseen_slots_and_preserves_changed_slots():
    def recipe(rid,ingredient):
        return {'id':rid,'title':f'Món {rid}','minutes':10,'required_ids':{ingredient},'all_ids':{ingredient}}
    recipes=[recipe(1,2),recipe(3,2),recipe(4,4),recipe(5,2),recipe(9,3),recipe(45,4),recipe(6,2),recipe(28,4)]
    categories=Classification('test',{1:'main',3:'main',4:'main',5:'vegetable',9:'vegetable',45:'vegetable',6:'soup',28:'soup'})
    reply=plan({'current_plan':{'main':1,'vegetable':5,'soup':6},'max_missing':2,
                'avoid_recipe_ids':{'main':[1,4],'vegetable':[5,45],'soup':[6,28]}},recipes,categories)
    assert [i['recipe_id'] for i in reply['plan']['items']]==[3,9,6]
    assert reply['changed_slots']==['main','vegetable'] and reply['warnings']==['PARTIAL_REGENERATION']


def test_omitting_history_preserves_previous_request_contract():
    payload={'current_plan':CURRENT,'locked_slots':['main','vegetable']}
    assert plan(payload)==plan({**payload,'avoid_recipe_ids':{}})


def test_http_real_tcp_visits_three_distinct_soups_and_forwards_history(meal_web):
    web,_=meal_web;current=dict(CURRENT);seen=[29]
    for _ in range(2):
        reply=web.post('/api/meal-plan',json={'current_plan':current,'locked_slots':['main','vegetable'],
                'avoid_recipe_ids':{'soup':seen}})
        assert reply.status_code==200
        data=reply.json()['data'];current={i['slot']:i['recipe_id'] for i in data['plan']['items']}
        assert current['soup'] not in seen;seen.append(current['soup'])
    assert len(set(seen))==3


def test_cli_accepts_history_without_http(meal_tcp):
    payload={'current_plan':CURRENT,'locked_slots':['main','vegetable'],'avoid_recipe_ids':{'soup':[29,30]}}
    result=subprocess.run([sys.executable,'-B','-m','source.client.cli','--port',str(meal_tcp[1]),'--op',
        'GENERATE_MEAL_PLAN','--payload',json.dumps(payload)],cwd=ROOT,
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,encoding='utf-8',timeout=10)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['data']['plan']['items'][2]['recipe_id'] not in {29,30}


@pytest.mark.parametrize('query,expected',[
    ('','/'),('?return_to=%2F','/'),('?return_to=%2Fmeal-plan','/meal-plan'),
    ('?return_to=https%3A%2F%2Fevil.example','/'),('?return_to=%2F%2Fevil.example','/'),
    ('?return_to=javascript%3Aalert(1)','/'),('?return_to=%2Fmeal-plan%3Fx%3D1','/'),
    ('?return_to=%2Fmeal-plan&return_to=%2F','/'),
])
def test_detail_return_link_allowlist(meal_web,query,expected):
    from html.parser import HTMLParser
    class Links(HTMLParser):
        def __init__(self): super().__init__();self.links={}
        def handle_starttag(self,tag,attrs):
            a=dict(attrs)
            if tag=='a' and a.get('class')=='back':self.links['back']=a['href']
            if tag=='a' and a.get('class')=='brand':self.links['brand']=a['href']
            if tag=='a' and a.get('data-user-tab')=='meal':self.links['meal-nav']=a['href']
    page=meal_web[0].get('/recipes/1'+query)
    assert page.status_code==200
    parser=Links();parser.feed(page.text)
    # The context return is allowlisted; the shared navigation stays canonical.
    assert parser.links=={'back':expected,'brand':'/','meal-nav':'/meal-plan'}


@pytest.mark.parametrize('recipe_id',['0','-1','invalid','99999999999999999'])
def test_invalid_detail_url_has_safe_html_return(meal_web,recipe_id):
    page=meal_web[0].get('/recipes/'+recipe_id)
    assert page.status_code==422 and 'text/html' in page.headers['content-type']
    assert 'href="/" class="back"' in page.text and 'data-recipe-id="0"' in page.text
    assert meal_web[0].get('/api/recipes/0').status_code==422
