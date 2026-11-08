"""Source dossier validation/planning; no database writes or approval."""
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from source.database import import_vegetarian_v2 as importer

DOSSIER = Path(__file__).resolve().parents[1]/'docs/data-v2/vegetarian-v2/recipes.json'


def document():
    return importer.load_document(DOSSIER)


def synthetic_document():
    """Completely synthetic TEST_ONLY content for private database tests."""
    data=deepcopy(document());data['recipes']=data['recipes'][:2]
    for n,r in enumerate(data['recipes'],1):
        r.update(recipe_key='T'+str(n),title='TEST_ONLY source recipe '+str(n),candidate_legacy_recipe_id=None,
                 role_proposed='main' if n==1 else 'vegetable',base_servings='2',serving_basis='source_servings',
                 servings_raw='TEST_ONLY two portions',minutes=10,instructions_paraphrased=['TEST_ONLY fabricated instruction.'])
        r['source'].update(url='https://example.test/TEST_ONLY/'+str(n)+'/',author='TEST_ONLY',publisher='TEST_ONLY',locator='TEST_ONLY',source_content_sha256=None)
        r['ingredient_lines']=[dict(r['ingredient_lines'][0],line_no=1,source_name='TEST_ONLY plant '+str(n),
            amount_kind='exact',quantity_value='1.5',quantity_min=None,quantity_max=None,unit='g',quantity_raw='TEST_ONLY 1.5 g')]
    data['priority_recipe_keys']=['T1','T2']
    return data


def test_18_source_records_have_requested_coverage_and_no_approval():
    data=document();rows=importer.validate(data)
    assert len(rows)==18
    assert {g:sum(r['role_proposed']==g for r in rows) for g in ('main','vegetable','soup')}=={'main':6,'vegetable':5,'soup':7}
    assert len(data['priority_recipe_keys'])==6
    assert all(r['review_status']=='NEEDS_VERIFICATION' and not r['content_complete'] for r in rows)
    assert all(r['source']['access_status']=='DIRECT_CONTENT_OBSERVED' for r in rows)


def test_priority_six_have_explicit_time_servings_and_two_of_each_role():
    data=document();rows=importer.validate(data,data['priority_recipe_keys'])
    assert {g:sum(r['role_proposed']==g for r in rows) for g in ('main','vegetable','soup')}=={'main':2,'vegetable':2,'soup':2}
    assert all(r['minutes'] is not None and r['base_servings'] is not None for r in rows)
    plan,mapping,_=importer.build_plan(data,'veg-source-01',data['priority_recipe_keys'])
    assert len(mapping)==6 and len(plan.rows['v2_recipe_ingredient_lines'])==50


def test_quantity_evidence_adds_canonical_line_scope_without_rewriting_original_observation():
    plan,_,_=importer.build_plan(synthetic_document(),'TEST_ONLY-canonical')
    for line in plan.rows['v2_recipe_ingredient_lines'].values():
        linked={r['evidence_id'] for r in plan.rows['v2_evidence_set_members'].values()
                if r['evidence_set_id']==line['quantity_evidence_set_id']}
        refs={r['entity_ref'] for r in plan.rows['v2_evidence'].values() if r['id'] in linked and r['claim_scope']=='quantity'}
        rid,n=line['revision_id'],line['line_no']
        assert refs=={f'revision:{rid}:{n}',f'line:{rid}:{n}'}
        assert line['status']=='NEEDS_VERIFICATION' and line['quantity_review_id'] is None


def test_new_source_identities_never_replace_legacy_and_are_stable_across_batches():
    data=document();a,ma,_=importer.build_plan(data,'batch-a');b,mb,_=importer.build_plan(data,'batch-b')
    assert ma==mb
    assert all(r['legacy_recipe_id'] is None and r['origin_kind']=='curated_new' for r in a.rows['v2_recipes'].values())
    assert all(r['variant_of_recipe_id'] is None for r in a.rows['v2_recipes'].values())
    for table in ('v2_recipes','v2_recipe_revisions','v2_ingredients','v2_units'):assert a.rows[table]==b.rows[table]
    assert not {'v2_review_decisions','v2_data_releases','v2_release_recipes','v2_calculation_settings'} & set(a.rows)


def test_quantities_fractions_unknown_servings_and_stage_lines_are_preserved():
    data=document();by_key={r['recipe_key']:r for r in data['recipes']}
    assert by_key['V01']['base_servings'] is None and by_key['V10']['base_servings'] is None
    assert 'pieces' in by_key['V10']['servings_raw']
    assert by_key['V06']['minutes'] is None
    fraction=next(l for l in by_key['V03']['ingredient_lines'] if l.get('source_fraction'))
    assert fraction['amount_kind']=='unknown' and fraction['quantity_value'] is None
    plan,mapping,_=importer.build_plan(data,'quantities')
    revisions={m['recipe_key']:m['revision_id'] for m in mapping}
    imported=plan.rows['v2_recipe_ingredient_lines'][(revisions['V03'],fraction['line_no'])]
    assert imported['amount_min'] is None and imported['quantity_raw']==fraction['quantity_raw']
    oils=[l for l in by_key['V10']['ingredient_lines'] if l['source_name']=='oil']
    assert len(oils)==3 and {l['stage'] for l in oils}=={'brush','filling','sauce'}
    assert all(r['measurement_basis']=='unknown' and r['scaling_mode'] is None for r in plan.rows['v2_recipe_ingredient_lines'].values())
    assert all(r['quantity_review_id'] is None for r in plan.rows['v2_recipe_ingredient_lines'].values())


def test_internal_references_and_sizes_are_valid():
    plan,mapping,_=importer.build_plan(document(),'complete')
    for r in plan.rows['v2_recipe_revisions'].values():
        assert (r['recipe_id'],) in plan.rows['v2_recipes']
        for field in ('content_evidence_set_id','servings_evidence_set_id'):assert (r[field],) in plan.rows['v2_evidence_sets']
    for r in plan.rows['v2_recipe_ingredient_lines'].values():
        assert (r['revision_id'],) in plan.rows['v2_recipe_revisions']
        assert (r['ingredient_id'],) in plan.rows['v2_ingredients']
        assert r['unit_id'] is None or (r['unit_id'],) in plan.rows['v2_units']
    assert all(len(e['excerpt_or_observation'].encode())<=65535 for e in plan.rows['v2_evidence'].values())


@pytest.mark.parametrize('change',[
    lambda d:d['recipes'][0].update(review_status='APPROVED'),
    lambda d:d['recipes'][0]['source'].update(verification_status='APPROVED'),
    lambda d:d.update(publication_allowed=True),
    lambda d:d['recipes'][0].update(reviewer_ref='invented reviewer'),
    lambda d:d['recipes'][0].update(content_complete=True),
    lambda d:d['recipes'][0]['source'].update(access_status='SEARCH_SNIPPET_ONLY'),
    lambda d:d['recipes'][0]['source'].update(url='file:///local'),
    lambda d:d['recipes'][0]['ingredient_lines'][0].update(source_name='ordinary fish sauce'),
    lambda d:d['recipes'][0]['ingredient_lines'][0].update(source_name='oyster sauce',requirement='optional'),
    lambda d:d['recipes'][0]['ingredient_lines'][0].update(source_url='https://example.test/another-source'),
    lambda d:d['recipes'][0]['ingredient_lines'][0].update(quantity_value='0'),
    lambda d:d['recipes'][0]['ingredient_lines'][0].update(line_no=2),
    lambda d:d['recipes'].append(deepcopy(d['recipes'][0])),
    lambda d:d['recipes'][1].update(recipe_key=d['recipes'][0]['recipe_key']),
    lambda d:d['recipes'][0].update(base_servings='4',serving_basis=None),
    lambda d:d['recipes'][0].update(minutes=0),
    lambda d:d['recipes'][0].update(recipe_id=1),
    lambda d:d['recipes'][0].update(candidate_legacy_recipe_id=True),
    lambda d:d['recipes'][0]['source'].update(observed_on='2026-99-99'),
    lambda d:d['recipes'][0]['ingredient_lines'][0].update(line_no=True),
    lambda d:d['recipes'][0]['ingredient_lines'][0].update(ingredient_id=1),
])
def test_unsafe_or_incoherent_dossiers_are_rejected(change):
    data=synthetic_document();change(data)
    with pytest.raises(importer.ImportError):importer.validate(data)


def test_unknown_selection_and_duplicate_json_keys_rejected(tmp_path):
    with pytest.raises(importer.ImportError):importer.build_plan(document(),'missing',['DOES_NOT_EXIST'])
    path=tmp_path/'duplicate.json';path.write_text('{"format":1,"format":2}',encoding='utf-8')
    with pytest.raises(importer.ImportError):importer.load_document(path)
