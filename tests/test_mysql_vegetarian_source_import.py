"""Private mysqld instance + TEST_ONLY dossiers. Never uses project DB credentials."""
from copy import deepcopy

import pytest

from source.database import import_vegetarian_v2 as importer
from source.database.migrate_v2 import run
from tests.mysql_v2_fixtures import private_mysql,mysql_db,sql,legacy_hashes
from tests.test_vegetarian_source_import import synthetic_document,document


def test_dry_run_apply_replay_and_fks(mysql_db):
    connection,_=mysql_db;run(connection,'apply');before=legacy_hashes(connection)
    data=synthetic_document()
    dry=importer.import_drafts(connection,data,'TEST_ONLY-veg')
    assert not dry['applied'] and dry['would_insert']['v2_recipe_revisions']==2
    assert sql(connection,'SELECT COUNT(*) n FROM v2_recipe_revisions')[0]['n']==0
    first=importer.import_drafts(connection,data,'TEST_ONLY-veg',apply=True)
    again=importer.import_drafts(connection,data,'TEST_ONLY-veg',apply=True)
    assert first['inserted']['v2_recipe_revisions']==2 and not any(again['inserted'].values())
    assert again['recipes']==first['recipes']
    assert sql(connection,'SELECT status,COUNT(*) n FROM v2_recipe_revisions GROUP BY status')==[{'status':'NEEDS_VERIFICATION','n':2}]
    assert sql(connection,'SELECT COUNT(*) n FROM v2_data_releases')[0]['n']==0
    assert sql(connection,'SELECT COUNT(*) n FROM v2_review_decisions')[0]['n']==0
    assert sql(connection,'''SELECT COUNT(*) n FROM v2_recipe_ingredient_lines l
        LEFT JOIN v2_recipe_revisions r ON r.id=l.revision_id LEFT JOIN v2_ingredients i ON i.id=l.ingredient_id
        LEFT JOIN v2_units u ON u.id=l.unit_id WHERE r.id IS NULL OR i.id IS NULL OR u.id IS NULL''')[0]['n']==0
    assert before==legacy_hashes(connection) and not connection.in_transaction


def test_partial_failure_rolls_back_every_insert(mysql_db,monkeypatch):
    connection,_=mysql_db;run(connection,'apply')
    original=importer.common._ensure
    def fail(c,table,row,apply):
        if table=='v2_recipe_revisions':raise RuntimeError('TEST_ONLY failure after parent inserts')
        return original(c,table,row,apply)
    monkeypatch.setattr(importer.common,'_ensure',fail)
    with pytest.raises(RuntimeError):importer.import_drafts(connection,synthetic_document(),'TEST_ONLY-rollback',apply=True)
    for table in ('v2_sources','v2_recipes','v2_ingredients','v2_recipe_revisions'):
        assert sql(connection,'SELECT COUNT(*) n FROM '+table)[0]['n']==0
    assert not connection.in_transaction


def test_old_draft_replay_only_adds_canonical_evidence_and_remains_unapproved(mysql_db,monkeypatch):
    connection,_=mysql_db;run(connection,'apply');data=synthetic_document()
    build=importer.build_plan
    def historical(*args,**kwargs):
        plan,mapping,digest=build(*args,**kwargs)
        removed={key for key,row in plan.rows['v2_evidence'].items() if row['entity_ref'].startswith('line:')}
        plan.rows['v2_evidence']={k:r for k,r in plan.rows['v2_evidence'].items() if k not in removed}
        plan.rows['v2_evidence_set_members']={k:r for k,r in plan.rows['v2_evidence_set_members'].items()
            if (r['evidence_id'],) not in removed}
        return plan,mapping,digest
    with monkeypatch.context() as patch:
        patch.setattr(importer,'build_plan',historical)
        importer.import_drafts(connection,data,'TEST_ONLY-old-draft',apply=True)
    before=sql(connection,'SELECT * FROM v2_evidence ORDER BY id')
    added=importer.import_drafts(connection,data,'TEST_ONLY-old-draft',apply=True)
    assert added['inserted']['v2_evidence']==added['inserted']['v2_evidence_set_members']==2
    assert added['inserted']['v2_recipe_revisions']==added['inserted']['v2_recipe_ingredient_lines']==0
    after={r['id']:r for r in sql(connection,'SELECT * FROM v2_evidence')}
    assert all(after[r['id']]==r for r in before)
    assert not any(importer.import_drafts(connection,data,'TEST_ONLY-old-draft',apply=True)['inserted'].values())
    assert sql(connection,"SELECT COUNT(*) n FROM v2_recipe_ingredient_lines WHERE status<>'NEEDS_VERIFICATION' OR quantity_review_id IS NOT NULL")[0]['n']==0
    assert sql(connection,'SELECT COUNT(*) n FROM v2_review_decisions')[0]['n']==0
    assert sql(connection,'SELECT COUNT(*) n FROM v2_data_releases')[0]['n']==0


def test_changed_or_approved_rows_are_never_overwritten(mysql_db):
    connection,_=mysql_db;run(connection,'apply');data=synthetic_document()
    first=importer.import_drafts(connection,data,'TEST_ONLY-approved',apply=True)
    rid=first['recipes'][0]['revision_id']
    # Synthetic status conflict only, on our private TEST_ONLY database.
    sql(connection,"UPDATE v2_recipe_revisions SET status='APPROVED' WHERE id=%s",(rid,))
    with pytest.raises(importer.ImportError):importer.import_drafts(connection,data,'TEST_ONLY-approved',apply=True)
    assert sql(connection,'SELECT status FROM v2_recipe_revisions WHERE id=%s',(rid,))[0]['status']=='APPROVED'
    changed=deepcopy(data);changed['recipes'][0]['title']='TEST_ONLY changed content'
    with pytest.raises(importer.ImportError):importer.import_drafts(connection,changed,'TEST_ONLY-approved',apply=True)
    assert sql(connection,'SELECT COUNT(*) n FROM v2_recipe_revisions')[0]['n']==2


def test_absent_migration_and_bad_ids_never_write(mysql_db):
    connection,_=mysql_db
    with pytest.raises(importer.ImportError):importer.import_drafts(connection,synthetic_document(),'TEST_ONLY-no-schema',apply=True)
    assert not connection.in_transaction


def test_complete_source_dossier_fits_actual_schema_on_private_test_instance(mysql_db):
    connection,_=mysql_db;run(connection,'apply')
    data=document()
    # The private instance has synthetic legacy IDs 1,2 only. Candidate lineage
    # is deliberately unset here; source observations remain real and unapproved.
    for r in data['recipes']:r['candidate_legacy_recipe_id']=None
    before=legacy_hashes(connection)
    result=importer.import_drafts(connection,data,'TEST_ONLY-all-18',apply=True)
    assert result['inserted']['v2_recipe_revisions']==18
    assert result['inserted']['v2_recipe_ingredient_lines']==200
    again=importer.import_drafts(connection,data,'TEST_ONLY-all-18',apply=True)
    assert not any(again['inserted'].values()) and legacy_hashes(connection)==before
    changed=synthetic_document();changed['recipes'][0]['candidate_legacy_recipe_id']=999
    with pytest.raises(importer.ImportError):importer.import_drafts(connection,changed,'TEST_ONLY-bad-lineage',apply=True)
    assert sql(connection,'SELECT COUNT(*) n FROM v2_recipe_revisions')[0]['n']==18
