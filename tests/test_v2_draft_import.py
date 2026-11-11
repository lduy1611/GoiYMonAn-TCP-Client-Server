"""Dossier parsing/planning only. Legacy parents below are TEST_ONLY, not recipes."""
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

import pytest

from source.database import import_v2_drafts as importer

PILOT = Path(__file__).resolve().parents[1] / 'docs/data-v2/pilot-12/portion-batch-01'


def pilot_batch(csv=True):
    return importer.load_batch(PILOT / 'proposed-revisions.json', PILOT / 'ingredient-lines.csv' if csv else None)


def synthetic_legacy(batch):
    return {
        'recipes': {p['legacy_recipe_id']: {'id': p['legacy_recipe_id'], 'title': 'TEST_ONLY legacy parent',
                    'instructions': 'TEST_ONLY must never become source-variant instructions'} for p in batch.dossier['proposals']},
        'ingredients': {l['ingredient_id']: {'id': l['ingredient_id'], 'name': 'TEST_ONLY ingredient '+str(l['ingredient_id']),
                        'normalized_name': 'test_only_'+str(l['ingredient_id'])}
                        for p in batch.dossier['proposals'] for l in p['ingredient_lines'] if l['ingredient_id'] is not None},
    }


def plan_for(batch=None):
    batch = pilot_batch() if batch is None else batch
    return importer.build_plan(batch, synthetic_legacy(batch))


def entries(plan, table):
    return list(plan.rows[table].values())


def test_pilot_import_plan_keeps_all_data_unapproved_and_does_not_invent_steps():
    plan, mapping = plan_for()
    assert len(mapping) == 3
    assert {row['legacy_recipe_id'] for row in mapping} == {30, 29, 9}
    assert len(entries(plan, 'v2_recipe_ingredient_lines')) == 28
    assert len(entries(plan, 'v2_ingredients')) == len(entries(plan, 'v2_ingredient_forms')) == 5
    assert set(plan.rows) == set(importer.KEYS)
    assert not {'v2_review_decisions', 'v2_data_releases', 'v2_calculation_settings'} & set(plan.rows)
    revisions = entries(plan, 'v2_recipe_revisions')
    assert sorted(r['base_servings'] for r in revisions) == [Decimal('2'), Decimal('3'), Decimal('4')]
    assert all(r['instructions'] == '' and r['minutes'] is None and r['content_complete'] == 0 for r in revisions)
    assert all(r['content_review_id'] is None and r['servings_review_id'] is None for r in revisions)
    for table, rows in plan.rows.items():
        for row in rows.values():
            assert all(value == 'NEEDS_VERIFICATION' for key, value in row.items() if key.endswith('status'))
            assert all(value is None for key, value in row.items() if key.endswith('review_id') or key == 'review_decision_id')


def test_sources_raw_dossier_csv_and_gaps_remain_recoverable():
    batch = pilot_batch()
    plan, _ = plan_for(batch)
    sources = entries(plan, 'v2_sources')
    assert len(sources) == 4 and sum(s['url'] is not None for s in sources) == 3
    assert all(s['accessed_at'] is None for s in sources)
    observed = [json.loads(s['usage_note'])['source'] for s in sources if s['source_kind'] == 'candidate_recipe_reference']
    assert observed == batch.dossier['sources']
    evidence = entries(plan, 'v2_evidence')
    snapshots = [e for e in evidence if e['claim_scope'] == 'import_manifest']
    assert len(snapshots) == 2
    assert json.loads(snapshots[0]['excerpt_or_observation']) == batch.dossier
    assert json.loads(snapshots[1]['excerpt_or_observation']) == list(batch.csv_rows)
    gaps = [e for e in evidence if e['claim_scope'] == 'instruction_gap']
    assert len(gaps) == 3
    assert all(e['entity_ref'].startswith('revision:') and ':gap:' in e['entity_ref'] for e in gaps)
    assert all(json.loads(e['excerpt_or_observation'])['line']['component_kind'] == 'unresolved_instruction' for e in gaps)
    assert len([e for e in evidence if e['claim_scope'] == 'source_observation']) == 10


def test_unknown_identity_ranges_and_approximate_mass_are_preserved():
    plan, mapping = plan_for()
    revisions = {m['legacy_recipe_id']: m['revision_id'] for m in mapping}
    lines = entries(plan, 'v2_recipe_ingredient_lines')
    assert sum(l['ingredient_id'] is None for l in lines) == 23
    assert {l['legacy_ingredient_id'] for l in entries(plan, 'v2_ingredients')} == {43, 38, 44, 11, 10}
    assert all(l['measurement_basis'] == 'unknown' and l['scaling_mode'] is None for l in lines)
    by_line = {(l['revision_id'], l['line_no']): l for l in lines}
    assert (by_line[revisions[9], 1]['amount_min'], by_line[revisions[9], 1]['amount_max']) == (Decimal('2'), Decimal('3'))
    assert (by_line[revisions[9], 2]['amount_min'], by_line[revisions[9], 2]['amount_max']) == (Decimal('0.5'), Decimal('1'))
    pumpkin = by_line[revisions[29], 2]
    assert pumpkin['amount_min'] == Decimal('1') and pumpkin['amount_max'] is None
    evidence = next(e for e in entries(plan, 'v2_evidence') if e['claim_scope']=='quantity' and e['entity_ref']==f"line:{revisions[29]}:2")
    alternate = json.loads(evidence['excerpt_or_observation'])['line']['source_alternative_measurement']
    assert alternate['quantity_value'] == '300' and alternate['precision'] == 'approximate' and not alternate['is_additional_usage']
    assert sum(l['amount_min'] is not None for l in lines) == 24
    assert sum(l['amount_kind'] == 'unknown' and l['amount_min'] is None for l in lines) == 4


def test_source_units_are_not_converted_or_assigned_a_spoon_volume():
    plan, _ = plan_for()
    units = entries(plan, 'v2_units')
    assert {u['symbol'] for u in units} == {'g', 'ml', 'l', 'quả', 'nhánh', 'muỗng cà phê', 'muỗng canh', 'củ', 'cọng'}
    assert all(u['code'].isascii() for u in units)
    assert all(u['dimension'] == 'source_defined' for u in units if u['symbol'] not in {'g', 'ml', 'l'})
    assert all('conversion' in u['definition'] and u['status'] == 'NEEDS_VERIFICATION' for u in units)


def test_evidence_sets_preserve_the_claim_scope_and_entity_for_future_review():
    plan, _ = plan_for()
    evidence = {row['id']: row for row in entries(plan, 'v2_evidence')}
    members = entries(plan, 'v2_evidence_set_members')
    for table, scope, prefix in [('v2_units','unit','unit'),
        ('v2_ingredients','ingredient_identity','ingredient_identity'),
        ('v2_ingredient_forms','ingredient_form','ingredient_form')]:
        for row in entries(plan,table):
            refs = [evidence[m['evidence_id']] for m in members if m['evidence_set_id']==row['evidence_set_id']]
            assert refs and all(e['claim_scope']==scope and e['entity_ref']==prefix+':'+str(row['id']) for e in refs)
    for row in entries(plan,'v2_recipe_ingredient_lines'):
        refs = [evidence[m['evidence_id']] for m in members if m['evidence_set_id']==row['quantity_evidence_set_id']]
        assert len(refs)==1 and refs[0]['claim_scope']=='quantity'
        assert refs[0]['entity_ref']==f"line:{row['revision_id']}:{row['line_no']}"


def test_same_bundle_has_stable_keys_and_ids_without_mutating_input():
    batch = pilot_batch()
    before = deepcopy(batch)
    first, first_mapping = plan_for(batch)
    second, second_mapping = plan_for(batch)
    assert batch == before and first_mapping == second_mapping
    assert {t: set(rows) for t, rows in first.rows.items()} == {t: set(rows) for t, rows in second.rows.items()}
    assert all(0 < m['revision_id'] <= 4294967295 for m in first_mapping)


@pytest.mark.parametrize('change', ['approved_source', 'approved_revision', 'reviewer', 'missing_source',
    'cross_source_evidence', 'duplicate_line', 'zero_amount', 'range_midpoint', 'range_order', 'missing_unit', 'missing_parent'])
def test_invalid_or_reviewed_input_is_rejected(change):
    base = pilot_batch(False)
    data = deepcopy(base.dossier)
    proposal = data['proposals'][0]
    line = proposal['ingredient_lines'][0]
    if change == 'approved_source': data['sources'][0]['source_acceptance_status'] = 'APPROVED'
    elif change == 'approved_revision': proposal['review_status'] = 'APPROVED'
    elif change == 'reviewer': proposal['reviewer'] = 'TEST_ONLY_CANNOT_IMPORT_REVIEW'
    elif change == 'missing_source': proposal['source_key'] = 'MISSING'
    elif change == 'cross_source_evidence': line['quantity_evidence_ref'] = 'S09-I'
    elif change == 'duplicate_line': proposal['ingredient_lines'].append(deepcopy(line))
    elif change == 'zero_amount': line['quantity_value'] = '0'
    elif change == 'range_midpoint':
        line.update(amount_kind='range', quantity_value='3', quantity_min='2', quantity_max='4')
    elif change == 'range_order':
        line.update(amount_kind='range', quantity_value=None, quantity_min='4', quantity_max='2')
    elif change == 'missing_unit': line['unit'] = None
    batch = importer.Batch(base.key, data)
    with pytest.raises(importer.ImportError):
        legacy = synthetic_legacy(batch)
        if change == 'missing_parent': legacy['recipes'].pop(proposal['legacy_recipe_id'])
        importer.build_plan(batch, legacy)


@pytest.mark.parametrize('field,value', [('quantity_value','999'), ('source_url','https://TEST_ONLY.invalid/'),
    ('candidate_ingredient_ids','[999]'), ('quantity_review_status','APPROVED')])
def test_csv_must_agree_with_json_and_remain_unreviewed(field, value):
    batch = pilot_batch()
    rows = deepcopy(list(batch.csv_rows))
    rows[0][field] = value
    with pytest.raises(importer.ImportError):
        importer.validate(importer.Batch(batch.key, batch.dossier, tuple(rows)))


def test_planned_primary_key_collisions_are_not_ignored(monkeypatch):
    monkeypatch.setattr(importer, '_id', lambda *args: 123)
    with pytest.raises(importer.ImportError, match='collision'):
        plan_for()
