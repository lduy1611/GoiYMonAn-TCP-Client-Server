"""TEST_ONLY synthetic batches. Never import these quantities into the demo."""
from dataclasses import replace
from decimal import Decimal, ROUND_CEILING
from fractions import Fraction

import pytest

from source.server.daily_demo_portions import estimate, assess, calculate_daily
from source.server.meal_plan_calculation import Catalog, Revision, calculate, validate as calc_options
from source.server import meal_plan_v2 as planner
from source.server.meal_plan import Classification
from source.web.meal_plan_calculation_contract import CalculationData
from tests.calculation_fixtures import fixture_catalog, test_line


def revision(name='Thịt heo xay', amount='500', **changes):
    line=test_line(name=name,amount_min=amount,measurement_basis='gross',ingredient_form=None)
    return replace(fixture_catalog((1,)).revisions[1],**{**{'base_servings':'4','data_status':'needs_review','lines':(line,)},**changes})


@pytest.mark.parametrize('method,expected',[('roast','352.8'),('braise','367.5'),('boil','392'),('steam','416.5'),('fry','352.8')])
def test_demo_hand_calculation_varies_by_cooking_method(method,expected):
    profile=estimate(revision(),{'cooking_method':{method}})
    assert profile['prepared_g']==expected
    assert profile['status']=='estimated'


def test_demo_larger_batch_differs_without_using_original_servings():
    small=estimate(revision(amount='250'))
    large=estimate(revision(amount='500',base_servings='99'))
    assert Fraction(large['prepared_g'])==2*Fraction(small['prepared_g'])
    assert large['meal_equivalents']!=small['meal_equivalents']


def test_demo_vegetable_and_chicken_use_different_yield_assumptions():
    assert estimate(revision('Bí đỏ','400',role='vegetable'))['prepared_g']=='306'
    assert estimate(revision('Thịt gà','1000'),{'cooking_method':{'steam'}})['prepared_g']=='630'


def test_demo_prepared_or_edible_basis_does_not_apply_trim_twice():
    rev=revision()
    assert estimate(replace(rev,lines=(replace(rev.lines[0],measurement_basis='prepared'),)))['prepared_g']=='500'
    assert estimate(replace(rev,lines=(replace(rev.lines[0],measurement_basis='edible'),)))['prepared_g']=='375'


def test_demo_water_oil_spices_are_not_food_even_if_marked_main():
    rev=revision(role='soup')
    extras=(test_line(2,name='Nước lọc',amount_min='10000',unit='ml',purpose='main'),
            test_line(3,name='Muối',amount_min='1000',purpose='main'),
            test_line(4,name='Dầu ăn',amount_min='1000',purpose='main'))
    result=estimate(replace(rev,lines=rev.lines+extras))
    assert result['prepared_g']==estimate(rev)['prepared_g']
    assert result['broth_ml']=='10000'
    assert len(result['drivers'])==1


def test_demo_bones_are_not_meat_and_ribs_have_an_explicit_edible_fraction():
    assert estimate(revision('Xương heo','500'))['status']=='unknown'
    ribs=estimate(revision('Sườn heo','500',role='soup'))
    assert ribs['prepared_g']=='212.5'
    assert ribs['drivers'][0]['edible_fraction']=='0.5'


@pytest.mark.parametrize('change',[{'amount_min':None},{'unit':None},{'unit':'bunch'},
    {'measurement_basis':'unknown'},{'amount_kind':'range','amount_max':'1'}])
def test_demo_missing_or_incompatible_driver_is_unknown(change):
    rev=revision()
    assert estimate(replace(rev,lines=(replace(rev.lines[0],**change),)))['status']=='unknown'


def test_demo_standalone_rice_meal_has_separate_context_and_reference():
    rev=revision('Gạo tẻ','300')
    rev=replace(rev,lines=rev.lines+(test_line(2,name='Hến',amount_min='300',measurement_basis='gross'),
        test_line(3,name='Đậu phộng',amount_min='40',measurement_basis='gross')))
    p=estimate(rev)
    assert p['prepared_g']=='840.1' and p['context']=='standalone'
    assert p['reference_g']=='500' and p['meal_equivalents']=='1.6802'


def test_demo_original_shopping_quantities_and_unknown_base_are_preserved():
    base=fixture_catalog((1,))
    rev=revision(base_servings=None)
    catalog=replace(base,revisions={1:rev},trust_admin_catalog=True)
    options=calc_options({'recipe_ids':[1],'people':8})
    result=calculate_daily(options,catalog)
    assert result['recipes'][0]['base_servings'] is None
    assert result['known_ingredients'][0]['quantity_value']=='500'
    CalculationData.model_validate({'dataset_version':'TEST_ONLY',**result})
    # Custom continues to require its original source basis, unchanged.
    custom=calculate(calc_options({'recipe_ids':[1],'people':8,'layout_mode':'custom'}),catalog)
    assert custom['status']=='INCOMPLETE'


def demo_fixture(people,children=0,mains=6,vegetables=3,soups=3):
    target=Decimal(people)-Decimal('.4')*children
    k=1 if people<=3 else 2 if people<=6 else 3 if people<=9 else 4 if people<=11 else 5
    roles={**{i:'main' for i in range(1,mains+1)},**{30+i:'vegetable' for i in range(vegetables)},**{50+i:'soup' for i in range(soups)}}
    base=fixture_catalog(tuple(roles));revs={};recipes=[]
    config={'main':('Thịt heo xay',Decimal('.6')/k,Decimal('.735')),
            'vegetable':('Cải thảo',Decimal('.25'),Decimal('.765')),
            'soup':('Đậu phụ',Decimal('.15'),Decimal('.931'))}
    for rid,role in roles.items():
        name,share,factor=config[role]
        amount=(target*350*share/factor).quantize(Decimal('.000001'),rounding=ROUND_CEILING)
        revs[rid]=replace(base.revisions[rid],role=role,base_servings=None,data_status='needs_review',data_evidence='',
            lines=(test_line(ingredient_id={'main':1001,'vegetable':1002,'soup':1003}[role],name=name,amount_min=str(amount),measurement_basis='gross'),))
        recipes.append({'id':rid,'title':f'TEST_ONLY {rid}','minutes':10,'all_ids':{{'main':1001,'vegetable':1002,'soup':1003}[role]},'required_ids':{{'main':1001,'vegetable':1002,'soup':1003}[role]}})
    return recipes,Classification('TEST_ONLY',roles),replace(base,revisions=revs,trust_admin_catalog=True)


def generate(people,setup=None,children=0,**changes):
    rows,cl,cat=setup or demo_fixture(people,children)
    options=planner.validate({'people':people,'adults':people-children,'children':children,'adaptive_daily':True,**changes},'test-demo')
    return planner.generate(rows,options,cl,'test-demo',daily_catalog=cat),cat


@pytest.mark.parametrize('people',range(1,13))
@pytest.mark.parametrize('children',[0,1])
def test_demo_fixed_layouts_all_people_and_children_with_suitable_test_batches(people,children):
    result,catalog=generate(people,children=children)
    assert result['plan'],result['reason']
    assert result['daily_selection_policy']=='daily-demo-food-v1'
    assert result['counts']['soup']==1 and result['counts']['vegetable']==1
    ids=[i['recipe_id'] for i in result['plan']['items']]
    calc=calculate_daily(calc_options({'recipe_ids':ids,'people':people,'adults':people-children,'children':children}),catalog)
    assert calc['daily_demo']['status']=='conditional'
    for ingredient in calc['known_ingredients']:
        for use in ingredient['uses']:
            assert Fraction(use['quantity_value'])==Fraction(catalog.revisions[use['recipe_id']].lines[0].amount_min)
    assert sum(Fraction(i['quantity_value']) for i in calc['known_ingredients'])==sum(Fraction(catalog.revisions[rid].lines[0].amount_min) for rid in ids)
    CalculationData.model_validate({'dataset_version':'TEST_ONLY',**calc})


def test_demo_ten_rotations_never_repeat_preserve_pin_and_hard_exclusion():
    setup=demo_fixture(5,mains=4,vegetables=2,soups=2)
    first,_=generate(5,setup=setup);previous={i['slot']:i['recipe_id'] for i in first['plan']['items']};seen=[first['daily_combo_id']]
    for _ in range(10):
        result,_=generate(5,setup=setup,action='regenerate',current_plan=previous,locked_slots=['main:1'],combo_history=seen)
        assert result['plan'] and result['daily_combo_id'] not in seen
        next_plan={i['slot']:i['recipe_id'] for i in result['plan']['items']}
        assert next_plan['main:1']==previous['main:1']
        seen.append(result['daily_combo_id']);previous=next_plan
    assert generate(5,setup=setup,excluded_ids=[1001])[0]['plan'] is None


def test_demo_main_guard_prevents_vegetable_compensation_and_surplus_is_not_accepted():
    main=estimate(revision(amount='10'))
    veg=estimate(revision('Bí đỏ','10000',role='vegetable'))
    assert assess([main,veg],4)['status']=='risk'
    assert assess([estimate(revision(amount='10000'))],1)['status']=='surplus'


def test_demo_metadata_cannot_be_used_by_custom_or_for_a_different_household():
    from pydantic import ValidationError
    rows,cl,catalog=demo_fixture(4)
    data=calculate_daily(calc_options({'recipe_ids':[1,2,30,50],'people':4}),catalog)
    data={'dataset_version':'TEST_ONLY',**data}
    with pytest.raises(ValidationError):CalculationData.model_validate({**data,'layout_mode':'custom'})
    with pytest.raises(ValidationError):CalculationData.model_validate({**data,'daily_demo':{**data['daily_demo'],'requested':'5'}})
