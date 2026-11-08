"""Read legacy SQL into temporary fixtures; never approve metadata or write MySQL."""
from copy import deepcopy
from dataclasses import replace

import pytest

from source.client.tcp_client import TCPClient
from source.common.protocol import ProtocolError, encode_frame
from source.server.meal_plan import default_classification
from source.server.meal_plan_v2 import generate, validate
from source.server.meal_preferences import load
from tests.meal_plan_fixtures import full_dataset, sql_rows, REQUEST_ID
from tests.test_web_meal_plan import meal_web
from tests.test_meal_plan_integration import meal_tcp


def catalog_data():
    recipes, _ = full_dataset()
    names = {r[0]: r[1] for r in sql_rows('ingredients')}
    return recipes, names, load(recipes, names, default_classification())


def run(payload):
    recipes, _, metadata = catalog_data()
    return generate(recipes, validate(payload, REQUEST_ID), default_classification(), REQUEST_ID, metadata)


def test_verified_positive_evidence_has_exact_coverage_and_does_not_certify_vegetarian():
    _, _, catalog = catalog_data()
    data = catalog.capabilities()
    assert data['role_recipe_count'] == 50
    meat, veggie = data['choices']['diet']
    assert meat['enabled'] and meat['recipe_count'] == 23
    assert meat['role_counts'] == {'main': 18, 'vegetable': 0, 'soup': 5}
    assert not veggie['enabled'] and veggie['recipe_count'] == 0
    assert all(not c['enabled'] for g in ('region', 'occasion') for c in data['choices'][g])
    assert catalog.evidence[7] == (13,)
    assert 44 not in catalog.meat_ids  # No animal evidence is UNKNOWN, never certified chay.
    assert 11 not in catalog.meat_ids  # Starch is outside current meal slots.


def test_identity_changes_and_optional_meat_cannot_provide_evidence():
    recipes, names, catalog = catalog_data()
    names[13] = 'TEST_ONLY plant ingredient with reused ID'
    assert 7 not in load(recipes, names, default_classification()).meat_ids
    recipes = deepcopy(recipes)
    next(r for r in recipes if r['id'] == 6)['required_ids'].remove(14)
    assert 6 not in load(recipes, names, default_classification()).meat_ids
    assert catalog.version != load(recipes, names, default_classification()).version


def test_diet_changes_actual_results_with_plant_sides_and_no_duplicates():
    plain = run({})
    assert [i['recipe_id'] for i in plain['plan']['items']] == [44, 45, 32]
    result = run({'preferences': {'diet': 'non_vegetarian'}})
    ids = [i['recipe_id'] for i in result['plan']['items']]
    assert set(ids) & catalog_data()[2].meat_ids
    assert len(ids) == len(set(ids)) == 3
    assert any(i in (5, 9, 45, 47) for i in ids)  # Plant side dishes remain eligible.
    assert result['preferences'] == {'diet': 'non_vegetarian'}
    assert 'preferences' not in plain and 'metadata_version' not in plain


def test_pins_are_kept_and_people_do_not_enter_generator_payload():
    result = run({'preferences': {'diet': 'non_vegetarian'},
                  'current_plan': {'main:1': 44, 'vegetable:1': 45, 'soup:1': 32},
                  'locked_slots': ['vegetable:1', 'soup:1']})
    chosen = {i['slot']: i['recipe_id'] for i in result['plan']['items']}
    assert chosen['vegetable:1'] == 45 and chosen['soup:1'] == 32 and chosen['main:1'] != 44
    assert result['changed_slots'] == ['main:1']
    assert validate({'people': 4, 'preferences': {'diet': 'non_vegetarian'}}, REQUEST_ID).counts == {'main': 1, 'vegetable': 1, 'soup': 1}


@pytest.mark.parametrize('payload', [
    {'counts': {'main': 0, 'vegetable': 1, 'soup': 0}},
    {'excluded_ids': [4, 13, 14, 28, 35, 36, 37, 38, 39]},
    {'current_plan': {'main:1': 44, 'vegetable:1': 45, 'soup:1': 32},
     'locked_slots': ['main:1', 'vegetable:1', 'soup:1']},
])
def test_no_verified_meat_returns_specific_reason_without_relaxation(payload):
    result = run({**payload, 'preferences': {'diet': 'non_vegetarian'}})
    assert result['plan'] is None and result['reason']['code'] == 'NO_VERIFIED_MEAT'
    assert result['reason']['suggestions']
    assert result['preferences']['diet'] == 'non_vegetarian'


def test_timing_and_missing_limits_still_apply():
    result = run({'max_total_minutes': 1, 'preferences': {'diet': 'non_vegetarian'}})
    assert result['plan'] is None and result['reason']['code'] == 'PREFERENCES_UNSATISFIED'
    assert run({'max_missing': 0, 'preferences': {'diet': 'non_vegetarian'}})['plan'] is None
    result = run({'max_minutes': 35, 'max_total_minutes': 105, 'preferences': {'diet': 'non_vegetarian'}})
    assert result['plan']['total_minutes'] <= 105
    assert all(i['minutes'] <= 35 for i in result['plan']['items'])


@pytest.mark.parametrize('preference', [{'region': 'north'}, {'region': 'central'}, {'region': 'south'},
    {'occasion': 'daily'}, {'occasion': 'tet'},
    {'diet': 'non_vegetarian', 'occasion': 'ancestral'}])
def test_unverified_metadata_is_never_silently_ignored(preference):
    result = run({'preferences': preference})
    assert result['plan'] is None and result['reason']['code'] == 'METADATA_UNAVAILABLE'


def test_missing_catalog_fails_closed():
    recipes, _, catalog = catalog_data()
    opts = validate({'preferences': {'diet': 'non_vegetarian'}}, REQUEST_ID)
    result = generate(recipes, opts, default_classification(), REQUEST_ID)
    assert result['plan'] is None and result['reason']['code'] == 'METADATA_UNAVAILABLE'
    assert replace(catalog, evidence={}).capabilities()['choices']['diet'][0]['enabled'] is False


@pytest.mark.parametrize('value', [None, [], {'diet': 'vegan'}, {'diet': True}, {'region': 1},
    {'occasion': 'any'}, {'approved': True}])
def test_invalid_preferences_rejected_by_tcp_and_gateway(meal_web, value):
    payload = {'preferences': value}
    with pytest.raises(ProtocolError):
        validate(payload, REQUEST_ID)
    # JSON null means "absent" in the backwards-compatible HTTP transport schema.
    if value is not None:
        assert meal_web[0].post('/api/meal-plan/v2', json=payload).status_code == 422


def test_real_http_tcp_catalog_filtered_plan_and_legacy_compatibility(meal_web):
    web, _ = meal_web
    catalog = web.get('/api/meal-plan/filters')
    assert catalog.status_code == 200 and catalog.json()['data']['choices']['diet'][0]['recipe_count'] == 23
    calls = [('/api/meal-plan/v2', {}), ('/api/meal-plan', {}),
             ('/api/recommend', {'ingredient_ids': [1, 2]}), ('/api/search', {'query': 'cá'})]
    before = [web.post(path, json=body).json()['data'] for path, body in calls]
    result = web.post('/api/meal-plan/v2', json={'preferences': {'diet': 'non_vegetarian'}})
    assert result.status_code == 200 and result.json()['data']['plan']
    assert result.json()['data']['metadata_version'] == catalog.json()['data']['metadata_version']
    assert [web.post(path, json=body).json()['data'] for path, body in calls] == before
    assert web.post('/api/meal-plan/v2', json={'preferences': {'region': 'south'}}).json()['data']['reason']['code'] == 'METADATA_UNAVAILABLE'
    calc = web.post('/api/meal-plan/calculate', json={'recipe_ids': [44, 45, 32], 'people': 4}).json()['data']
    assert calc['status'] == 'INCOMPLETE' and not calc['known_ingredients']


def test_tcp_frames_and_persistent_connection(meal_tcp):
    client = TCPClient(port=meal_tcp[1], persistent=True)
    try:
        for op, payload in [('GET_MEAL_PLAN_FILTERS', {}),
                            ('GENERATE_MEAL_PLAN_V2', {'preferences': {'diet': 'non_vegetarian'},
                              'counts': {'main': 2, 'vegetable': 2, 'soup': 2}})]:
            reply = client.request(op, payload)
            assert reply['ok'] and len(encode_frame(reply)) <= 65540
        assert client.request('GET_MEAL_PLAN_FILTERS', {'diet': 'non_vegetarian'})['error']['code'] == 'INVALID_PAYLOAD'
        assert client.request('PING', {})['ok']
    finally:
        client.close()
