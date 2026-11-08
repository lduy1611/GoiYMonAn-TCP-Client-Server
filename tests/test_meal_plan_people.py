"""Automatic layout policy; only temporary SQL fixtures, no MySQL writes."""
import pytest

from source.client.tcp_client import TCPClient
from source.common.protocol import ProtocolError, encode_frame, success_response
from source.server.meal_plan import default_classification
from source.server.meal_plan_v2 import counts_for_people, generate, validate
from tests.meal_plan_fixtures import full_dataset, REQUEST_ID
from tests.test_web_meal_plan import meal_web


@pytest.mark.parametrize('people,counts', [
    (1, (1,1,0)), (2, (1,1,0)), (3, (1,1,1)), (4, (1,1,1)),
    (5, (2,1,1)), (6, (2,1,1)), (7, (2,2,1)), (8, (2,2,1)),
    (9, (2,2,2)), (10, (2,2,2)), (11, (2,2,2)), (12, (2,2,2)),
])
def test_server_derives_every_headcount_and_http_uses_same_policy(meal_web, people, counts):
    expected = dict(zip(('main','vegetable','soup'),counts))
    assert counts_for_people(people) == expected
    assert validate({'people': people}, REQUEST_ID).counts == expected
    body = meal_web[0].post('/api/meal-plan/v2', json={'people': people})
    assert body.status_code == 200
    data = body.json()['data']
    assert data['people'] == people and data['counts'] == expected
    assert len(data['plan']['items']) == sum(counts)
    assert len({i['recipe_id'] for i in data['plan']['items']}) == sum(counts)
    assert len(encode_frame(body.json())) <= 65540
    calc = meal_web[0].post('/api/meal-plan/calculate',json={
        'people': people,'recipe_ids':[i['recipe_id'] for i in data['plan']['items']]}).json()['data']
    assert calc['status'] == 'INCOMPLETE' and not calc['known_ingredients']


@pytest.mark.parametrize('payload', [
    {'people': True}, {'people': 0}, {'people': 13}, {'people': '4'}, {'people': 4.0},
    {'people': None}, {'counts': None},
    {'people': 2, 'counts': {'main':1,'vegetable':1,'soup':1}},
    {'people': 9, 'counts': {'main':1,'vegetable':1,'soup':1}},
])
def test_forged_or_invalid_headcount_cannot_bypass_tcp(meal_web,payload):
    with pytest.raises(ProtocolError):validate(payload,REQUEST_ID)
    assert meal_web[0].post('/api/meal-plan/v2',json=payload).status_code == 422


def test_old_clients_keep_manual_counts_and_original_response_shape(meal_web):
    web,_=meal_web
    for payload,expected in [({}, {'main':1,'vegetable':1,'soup':1}),
                             ({'counts':{'main':0,'vegetable':1,'soup':0}}, {'main':0,'vegetable':1,'soup':0})]:
        data=web.post('/api/meal-plan/v2',json=payload).json()['data']
        assert data['counts']==expected and 'people' not in data
    data=web.post('/api/meal-plan/v2',json={'people':2,'counts':{'main':1,'vegetable':1,'soup':0}}).json()['data']
    assert data['people']==2 and data['plan']


def test_boundaries_preserve_pins_and_decrease_reports_exact_conflicting_slots():
    recipes,_=full_dataset();classification=default_classification()
    current={};pinned={}
    for people in (2,3,4,5,6,7,8,9):
        opts=validate({'people':people,'current_plan':current,'locked_slots':list(pinned)},REQUEST_ID)
        data=generate(recipes,opts,classification,REQUEST_ID)
        assert data['plan']
        current={i['slot']:i['recipe_id'] for i in data['plan']['items']}
        if not pinned:pinned={'main:1':current['main:1']}
        assert current['main:1']==pinned['main:1']
    for people,slot in [(8,'soup:2'),(6,'vegetable:2'),(4,'main:2'),(2,'soup:1')]:
        data=generate(recipes,validate({'people':people,'current_plan':current,'locked_slots':[slot]},REQUEST_ID),classification,REQUEST_ID)
        assert data['plan'] is None and data['reason']['code']=='PINNED_SLOT_REMOVED'
        assert data['reason']['slots']==[slot] and 'người' in data['reason']['suggestions'][0]


def test_gateway_rejects_server_ignoring_people(meal_web,monkeypatch):
    data=meal_web[0].post('/api/meal-plan/v2',json={}).json()['data']
    monkeypatch.setattr(TCPClient,'request',lambda self,op,payload,request_id=None:success_response(request_id,data))
    assert meal_web[0].post('/api/meal-plan/v2',json={'people':4}).status_code==502
