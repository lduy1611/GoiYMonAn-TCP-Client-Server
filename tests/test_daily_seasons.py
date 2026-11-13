"""Seasonal demo ranking: synthetic fixtures, no demo database writes."""
from dataclasses import replace
from copy import deepcopy

import pytest
from pydantic import ValidationError

from source.common.protocol import ProtocolError
from source.server import daily_seasons as season, meal_plan_v2 as planner
from source.server.daily_demo_portions import calculate_daily
from source.server.meal_plan_calculation import validate as calc_options
from source.web.meal_plan_v2_contract import Request
from tests.test_daily_demo_portions import demo_fixture


@pytest.mark.parametrize('selected,method', [('SPRING','steam'),('SUMMER','boil'),('AUTUMN','braise'),('WINTER','stew')])
def test_each_season_rewards_an_explained_database_method(selected, method):
    result = season.evaluate({'id':1,'title':'TEST_ONLY'},None,{'cooking_method':{method}},selected)
    assert result['score'] > 0 and result['reasons']
    assert season.evaluate({'id':1,'title':'TEST_ONLY'},None,{'cooking_method':{method}},'ALL')['score'] == 0


@pytest.mark.parametrize('title,expected', [
    ('Canh khổ qua nhồi đậu hũ', set()),
    ('Canh cải ngồng nấu tôm khô', set()),
    ('Tôm khô rang', {'roast'}),
    ('Thịt kho củ cải trắng', {'braise'}),
    ('Cá kho tộ', {'braise'}),
    ('Dau hu kho', set()),  # No reliable tone evidence in this ASCII title.
    ('Gà hấp hành', {'steam'}), ('Rau muống luộc', {'boil'}),
    ('Canh khoai tây hầm sườn', {'stew'}), ('Cá chiên', {'fry'}),
    ('Su su xào tôm', {'stir_fry'}), ('Tôm nướng', {'roast'}),
    ('Thịt rang', {'roast'}), ('Gỏi gà', {'salad'}),
    ('Khoai tây', set()), ('Hầmnhừ', set()),
])
def test_cooking_fallback_keeps_tones_and_word_boundaries(title, expected):
    import unicodedata
    assert season.cooking_methods(title) == expected
    assert season.cooking_methods(unicodedata.normalize('NFD', title)) == expected
    assert season.cooking_methods(title, {'cooking_method': {'steam'}}) == {'steam'}


@pytest.mark.parametrize('title,expected', [
    ('Cơm hến Huế', True), ('Bún cá ngừ', True), ('Miến xào rau củ', True),
    ('Cháo gà hạt sen', True), ('Bánh canh bột lọc Huế', True), ('Phở bò', True),
    ('Canh bí đao', False), ('Thịt rang ăn với cơm', False),
    ('Đậu hũ sốt cơm mẻ', False), ('Bánh cuốn', False),
])
def test_standalone_requires_a_leading_dish_phrase(title, expected):
    assert season.standalone_meal(title) is expected


def test_soup_role_alone_is_not_a_summer_or_winter_signal():
    recipe = {'id': 1, 'title': 'Canh TEST_ONLY', 'role': 'soup'}
    assert season.evaluate(recipe, None, {}, 'SUMMER')['score'] == 0
    assert season.evaluate(recipe, None, {}, 'WINTER')['score'] == 0
    assert season.evaluate(recipe, None, {'cooking_method': {'stew'}}, 'WINTER')['score'] == 5
    rows, _, catalog = demo_fixture(5)
    rev = catalog.revisions[30]  # Cải thảo supports winter, not summer.
    assert season.evaluate(recipe, rev, {}, 'SUMMER')['score'] == 0
    assert season.evaluate({'id': 1, 'title': 'Canh tôm khô'}, None, {}, 'AUTUMN')['score'] == 0


def test_new_signals_do_not_change_all_response_or_food_estimates():
    rows, cl, catalog = demo_fixture(5, mains=4, vegetables=2, soups=2)
    rows = [dict(row, title='Bánh canh TEST_ONLY' if row['id'] == 1 else row['title']) for row in rows]
    def run(**extra):
        return planner.generate(rows, planner.validate({'people':5, 'adaptive_daily':True, **extra}, 'season-context'),
                                cl, 'season-context', daily_catalog=catalog)
    assert run() == run(season='ALL')
    data = run(season='SPRING')
    assert data['plan'] and all(i['recipe_id'] != 1 for i in data['plan']['items'])
    current = {i['slot']:i['recipe_id'] for i in data['plan']['items']}
    swapped = run(season='SPRING', action='regenerate', current_plan=current,
                  combo_history=[data['daily_combo_id']])
    assert swapped['plan'] and swapped['daily_combo_id'] != data['daily_combo_id']
    assert all(i['recipe_id'] != 1 for i in swapped['plan']['items'])
    # A pinned standalone dish remains allowed: season/context is a preference.
    pinned = run(season='SPRING', current_plan={'main:1':1}, locked_slots=['main:1'])
    assert pinned['plan'] and next(i['recipe_id'] for i in pinned['plan']['items'] if i['slot']=='main:1') == 1


def test_ingredient_signals_and_title_fallback_never_claim_verified_seasons():
    rows,_,catalog = demo_fixture(5)
    revision = catalog.revisions[30]  # Actual ingredient in this fixture: cải thảo.
    result = season.evaluate({'id':30,'title':'TEST_ONLY hấp'},revision,{},'SPRING')
    assert result['score'] == 4
    assert any('cách nấu trong tên món' in s for s in result['reasons'])
    assert any('thử nghiệm' in s for s in result['reasons'])
    # Cooking tags are authoritative when available, even with conflicting title.
    assert season.evaluate({'id':30,'title':'TEST_ONLY hấp'},None,{'cooking_method':{'fry'}},'SUMMER')['score'] == -2


def test_neutral_is_allowed_pins_are_explained_and_standalone_context_is_explicit():
    neutral = season.evaluate({'id':1,'title':'TEST_ONLY'},None,{},'SPRING')
    assert neutral['score'] == 0
    meal = season.evaluate({'id':2,'title':'Cơm hến Huế'},None,{},'SPRING')
    assert meal['standalone']
    data = season.assessment([neutral,meal],'SPRING',{1})
    assert data['neutral_count'] == 2 and 'món ghim' in data['summary']
    assert 'món ăn riêng' in data['summary']


def test_season_changes_backend_ranking_but_not_portions_filters_or_all_policy():
    rows,cl,catalog = demo_fixture(5,mains=4,vegetables=2,soups=2)
    tags = {i:{'cooking_method':{m}} for i,m in enumerate(['steam','fry','braise','stew'],1)}
    snapshot = deepcopy(catalog)
    def run(**extra):
        options = planner.validate({'people':5,'adaptive_daily':True,**extra},'season-test')
        return planner.generate(rows,options,cl,'season-test',pairing_metadata=tags,daily_catalog=catalog)
    all_data = run()
    assert all_data == run(season='ALL')
    assert 'season' not in all_data and 'seasonal_assessment' not in all_data
    spring,winter = run(season='SPRING'),run(season='WINTER')
    selected = lambda data:{i['recipe_id'] for i in data['plan']['items'] if i['slot'].startswith('main:')}
    assert selected(spring) != selected(winter)
    assert 1 in selected(spring) and selected(winter) == {3,4}
    for data in [spring,winter]:
        ids = [i['recipe_id'] for i in data['plan']['items']]
        calc = calculate_daily(calc_options({'people':5,'recipe_ids':ids}),catalog,tags)
        assert calc['daily_demo']['status'] == 'conditional'
        for line in calc['known_ingredients']:
            for use in line['uses']:
                assert use['quantity_value'] == catalog.revisions[use['recipe_id']].lines[0].amount_min
        current = {i['slot']:i['recipe_id'] for i in data['plan']['items']}
        swapped = run(season=data['season'],weather='cold',action='regenerate',current_plan=current,
                      locked_slots=['main:1'],combo_history=[data['daily_combo_id']])
        assert swapped['plan'] and swapped['daily_combo_id'] != data['daily_combo_id']
        assert swapped['weather'] == 'cold' and swapped['season'] == data['season']
        assert next(i['recipe_id'] for i in swapped['plan']['items'] if i['slot']=='main:1') == current['main:1']
        rejected = run(season=data['season'],excluded_ids=[1001])
        assert rejected['plan'] is None
    assert catalog == snapshot


def test_low_season_score_is_soft_even_for_a_pinned_fried_main():
    from decimal import Decimal
    rows,cl,catalog = demo_fixture(5,mains=4,vegetables=2,soups=2)
    # Frying has a lower demo yield than the fixture's default braise.
    # Give synthetic original batches enough food to remain qualified.
    catalog = replace(catalog,revisions={rid:replace(rev,lines=tuple(
        replace(line,amount_min=str((Decimal(line.amount_min)*Decimal('1.05')).quantize(Decimal('.000001'))))
        for line in rev.lines)) for rid,rev in catalog.revisions.items()})
    tags = {2:{'cooking_method':{'fry'}}}
    options = planner.validate({'people':5,'adaptive_daily':True,'season':'SUMMER',
                                'current_plan':{'main:1':2},'locked_slots':['main:1']},'season-pin')
    data = planner.generate(rows,options,cl,'season-pin',pairing_metadata=tags,daily_catalog=catalog)
    assert data['plan']
    assert next(i['recipe_id'] for i in data['plan']['items'] if i['slot']=='main:1') == 2
    assert 'món ghim' in data['seasonal_assessment']['summary']


@pytest.mark.parametrize('value',[None,True,1,[],{},'summer','MONSOON',''])
def test_invalid_season_is_rejected_at_http_and_tcp_contract(value):
    with pytest.raises(ValidationError):Request.model_validate({'adaptive_daily':True,'season':value})
    with pytest.raises(ProtocolError) as e:planner.validate({'adaptive_daily':True,'season':value},'season-test')
    assert e.value.code == 'INVALID_PAYLOAD'


@pytest.mark.parametrize('extra',[{'layout_mode':'custom'}, {'preferences':{'occasion':'guests'}}, {'preferences':{'occasion':'drinking'}}])
def test_selected_season_cannot_enter_other_modes(extra):
    with pytest.raises(ValidationError):Request.model_validate({'season':'WINTER',**extra})
    with pytest.raises(ProtocolError):planner.validate({'season':'WINTER',**extra},'season-test')
    assert 'season' not in Request.model_validate(extra).model_dump(exclude_none=True)


@pytest.mark.parametrize('pin_removed',[False,True])
def test_seven_daily_source_slots_can_transition_to_six_custom_dishes(pin_removed):
    rows,cl,catalog=demo_fixture(12)
    current={**{f'main:{i}':i for i in range(1,6)},'vegetable:1':30,'soup:1':50}
    payload={'people':12,'layout_mode':'custom','counts':{'main':2,'vegetable':2,'soup':2},
             'current_plan':current,'locked_slots':['main:5'] if pin_removed else []}
    Request.model_validate(payload)
    data=planner.generate(rows,planner.validate(payload,'transition'),cl,'transition')
    if pin_removed:
        assert data['plan'] is None and data['reason']['code']=='PINNED_SLOT_REMOVED'
        assert data['reason']['slots']==['main:5']
    else:
        assert len(data['plan']['items'])==6 and data['counts']==payload['counts']
    assert payload['current_plan']==current
    with pytest.raises(ValidationError):Request.model_validate({**payload,'counts':{'main':5,'vegetable':1,'soup':1}})
    with pytest.raises(ProtocolError):planner.validate({**payload,'counts':{'main':5,'vegetable':1,'soup':1}},'transition')
