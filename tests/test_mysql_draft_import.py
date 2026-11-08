"""Draft import on an isolated MySQL instance; parents are TEST_ONLY synthetic rows.

No production credentials are used; no APPROVED decisions or releases are created.
"""
from copy import deepcopy
import json

import pytest

from source.database import import_v2_drafts as importer, migrate_v2, v2_schema
from source.server.meal_plan_calculation import calculate, validate
from source.server.mysql_calculation_catalog import load_catalog
from tests.mysql_v2_fixtures import mysql_db, private_mysql, sql, legacy_hashes
from tests.test_v2_draft_import import pilot_batch


@pytest.fixture
def draft_db(mysql_db):
    connection, config = mysql_db
    batch = pilot_batch()
    for proposal in batch.dossier['proposals']:
        rid = proposal['legacy_recipe_id']
        sql(connection, "INSERT INTO recipes VALUES(%s,%s,'TEST_ONLY never reuse these instructions',10,NULL,'TEST_ONLY synthetic parent')",
            (rid, 'TEST_ONLY legacy recipe '+str(rid)))
    ids = {l['ingredient_id'] for p in batch.dossier['proposals'] for l in p['ingredient_lines'] if l['ingredient_id'] is not None}
    for iid in ids:
        sql(connection, 'INSERT INTO ingredients VALUES(%s,%s,%s)', (iid, 'TEST_ONLY ingredient '+str(iid), 'test_only_'+str(iid)))
    migrate_v2.run(connection, 'apply')
    return connection, batch


def table_counts(connection):
    return {table: sql(connection, f'SELECT COUNT(*) AS n FROM {table}')[0]['n'] for table in v2_schema.tables()}


def test_actual_mysql_import_is_draft_only_atomic_and_idempotent(draft_db):
    connection, batch = draft_db
    before = legacy_hashes(connection)
    preview = importer.import_drafts(connection, batch)
    assert not preview['applied'] and not any(table_counts(connection).values())
    first = importer.import_drafts(connection, batch, apply=True)
    assert first['changed'] and len(first['recipes']) == 3
    counts = table_counts(connection)
    assert counts['v2_recipe_revisions'] == counts['v2_recipes'] == 3
    assert counts['v2_recipe_ingredient_lines'] == 28 and counts['v2_sources'] == 4
    assert counts['v2_ingredients'] == counts['v2_ingredient_forms'] == 5
    assert counts['v2_units'] == 9
    for table in ['v2_review_decisions','v2_data_releases','v2_release_recipes','v2_calculation_settings',
                  'v2_portion_policy_versions','v2_portion_policy_rules','v2_release_portion_policies']:
        assert counts[table] == 0
    snapshot = {table: sql(connection, f'SELECT * FROM {table}') for table in v2_schema.tables()}
    second = importer.import_drafts(connection, batch, apply=True)
    assert not second['changed'] and sum(second['inserted'].values()) == 0
    assert table_counts(connection) == counts
    assert {table: sql(connection, f'SELECT * FROM {table}') for table in v2_schema.tables()} == snapshot
    assert legacy_hashes(connection) == before
    assert migrate_v2.run(connection)['state'] == 'APPLIED'
    assert not connection.in_transaction


def test_nulls_ranges_gaps_and_evidence_survive_mysql_roundtrip(draft_db):
    connection, batch = draft_db
    result = importer.import_drafts(connection, batch, apply=True)
    revisions = {row['legacy_recipe_id']: row['revision_id'] for row in result['recipes']}
    rows = sql(connection, 'SELECT * FROM v2_recipe_revisions')
    assert all(r['status']=='NEEDS_VERIFICATION' and r['instructions']=='' and r['content_complete']==0
               and r['content_review_id'] is None and r['servings_review_id'] is None for r in rows)
    assert sql(connection, 'SELECT COUNT(*) AS n FROM v2_recipe_ingredient_lines WHERE ingredient_id IS NULL')[0]['n'] == 23
    assert sql(connection, 'SELECT COUNT(*) AS n FROM v2_recipe_ingredient_lines WHERE amount_min IS NULL')[0]['n'] == 4
    assert sql(connection, "SELECT COUNT(*) AS n FROM v2_evidence WHERE claim_scope='instruction_gap'")[0]['n'] == 3
    snapshot = sql(connection, "SELECT excerpt_or_observation FROM v2_evidence WHERE claim_scope='import_manifest' AND locator='proposed-revisions.json'")[0]
    assert json.loads(snapshot['excerpt_or_observation']) == batch.dossier
    carrot = sql(connection, 'SELECT amount_min,amount_max FROM v2_recipe_ingredient_lines WHERE revision_id=%s AND line_no=2', (revisions[9],))[0]
    assert str(carrot['amount_min'])=='0.500000' and str(carrot['amount_max'])=='1.000000'
    # MySQL actually enforces both ingredient-form and source evidence foreign keys.
    orphans = sql(connection, '''SELECT COUNT(*) AS n FROM v2_recipe_ingredient_lines l
        LEFT JOIN v2_evidence_sets e ON e.id=l.quantity_evidence_set_id
        LEFT JOIN v2_recipe_revisions r ON r.id=l.revision_id WHERE e.id IS NULL OR r.id IS NULL''')[0]['n']
    assert orphans == 0


def test_drafts_never_enable_calculate_meal_plan(draft_db):
    connection, batch = draft_db
    importer.import_drafts(connection, batch, apply=True)
    data = calculate(validate({'recipe_ids':[30,29,9],'people':4}), load_catalog(connection,(30,29,9)))
    assert data['status']=='INCOMPLETE' and not data['totals_complete'] and data['known_ingredients']==[]
    assert all(r['reasons'][0]['code']=='APPROVED_DATA_UNAVAILABLE' for r in data['recipes'])


def test_changed_bundle_conflicts_without_overwriting_rows(draft_db):
    connection, batch = draft_db
    importer.import_drafts(connection,batch,apply=True)
    before = {t:sql(connection,f'SELECT * FROM {t}') for t in v2_schema.tables()}
    dossier = deepcopy(batch.dossier)
    dossier['proposals'][0]['remaining_issues'].append('TEST_ONLY changed import version')
    changed = importer.Batch(batch.key,dossier,batch.csv_rows)
    with pytest.raises(importer.ImportError,match='conflict'):
        importer.import_drafts(connection,changed,apply=True)
    assert {t:sql(connection,f'SELECT * FROM {t}') for t in v2_schema.tables()} == before


def test_existing_edited_revision_is_not_reset_or_duplicated(draft_db):
    connection,batch=draft_db
    first=importer.import_drafts(connection,batch,apply=True)
    revision=first['recipes'][0]['revision_id']
    sql(connection,"UPDATE v2_recipe_revisions SET instructions='TEST_ONLY human draft edit' WHERE id=%s",(revision,))
    before=table_counts(connection)
    with pytest.raises(importer.ImportError,match='conflict'):
        importer.import_drafts(connection,batch,apply=True)
    assert table_counts(connection)==before
    assert sql(connection,'SELECT instructions FROM v2_recipe_revisions WHERE id=%s',(revision,))[0]['instructions']=='TEST_ONLY human draft edit'


def test_failure_mid_import_rolls_back_every_insert_and_releases_lock(draft_db,monkeypatch):
    connection,batch=draft_db
    original=importer._ensure
    def fail(c,table,row,apply):
        if table=='v2_recipe_revisions':
            raise RuntimeError('TEST_ONLY interrupted import')
        return original(c,table,row,apply)
    with monkeypatch.context() as local:
        local.setattr(importer,'_ensure',fail)
        with pytest.raises(RuntimeError):importer.import_drafts(connection,batch,apply=True)
    assert not any(table_counts(connection).values()) and not connection.in_transaction
    assert importer.import_drafts(connection,batch,apply=True)['changed']


def test_missing_migration_refuses_to_import_without_creating_schema(mysql_db):
    connection,_=mysql_db
    with pytest.raises(importer.ImportError,match='Migration'):
        importer.import_drafts(connection,pilot_batch(),apply=True)
    assert not sql(connection,"SHOW TABLES LIKE 'v2_%'")


def test_foreign_key_checks_must_remain_enabled(draft_db):
    connection,batch=draft_db
    sql(connection,'SET SESSION foreign_key_checks=0')
    try:
        with pytest.raises(importer.ImportError,match='Foreign keys'):
            importer.import_drafts(connection,batch,apply=True)
    finally:sql(connection,'SET SESSION foreign_key_checks=1')
    assert not any(table_counts(connection).values())
