import pytest
from source.server.beverages import validate_settings,tag_changes,seasonal_score

@pytest.mark.parametrize('temp', ['unspecified','hot','cold','both'])
def test_temperature_metadata_is_explicit(temp):
    assert validate_settings({'beverage_temperature':temp},'drink')=={'beverage_temperature':temp}
    changes=tag_changes({'beverage_temperature':temp})
    assert changes['serve_hot']==(temp in ('hot','both'))
    assert changes['serve_cold']==(temp in ('cold','both'))

@pytest.mark.parametrize('value', ['warm',None,[],{},1])
def test_invalid_temperature_rejected(value):
    with pytest.raises(ValueError):validate_settings({'beverage_temperature':value},'drink')

def test_food_requests_and_omitted_beverage_flags_unchanged():
    assert validate_settings({},'main')=={}
    assert tag_changes({})=={}
    with pytest.raises(ValueError):validate_settings({'is_visible':True},'main')
    with pytest.raises(ValueError):validate_settings({'beverage_light':1},'drink')

@pytest.mark.parametrize('season,flags', [('SPRING',{'beverage_light'}),('SUMMER',{'serve_cold'}),('AUTUMN',{'beverage_light'}),('WINTER',{'serve_hot'})])
def test_season_is_soft_admin_ranking_and_all_is_compatible(season,flags):
    tags={'season':{season.lower()},'dish_type':flags}
    score,reasons=seasonal_score(tags,season)
    assert score>=10 and reasons
    assert seasonal_score(tags,'ALL')==(0,[])
    assert seasonal_score({},season)[0]==0
    assert seasonal_score({'weather':{'cold','hot'}},season)[0]==0
