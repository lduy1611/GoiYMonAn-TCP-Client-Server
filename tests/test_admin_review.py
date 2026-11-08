"""Admin content-review lifecycle, using TEST_ONLY data on an isolated mysqld."""
import json
import mysql.connector
import pytest

from source.database import migrate_v2
from source.server import admin_review
from source.server.repository import MySQLRepository,AdminReviewBlocked
from source.server.mysql_calculation_catalog import subject_hash
from source.server.mysql_recipe_catalog import load_catalog
from source.common.catalog_ids import v2_public_id
from tests.mysql_v2_fixtures import mysql_db,private_mysql,sql,legacy_hashes
from tests.meal_plan_fixtures import REQUEST_ID
from source.server.handler import dispatch
from source.common.protocol import ProtocolError


def submission(revision_id):
    return {"revision_id":revision_id,"source_kind":"TEST_ONLY",
        "source_title":"TEST_ONLY simulated source","source_url":"https://example.test/TEST_ONLY",
        "publisher":"TEST_ONLY publisher","usage_note":"TEST_ONLY, not real source evidence",
        "accessed_on":"2026-11-05","content_locator":"TEST_ONLY section 1",
        "content_evidence":"TEST_ONLY fabricated ingredient and instruction evidence",
        "publication_locator":"TEST_ONLY section 2","publication_evidence":"TEST_ONLY fabricated publication evidence",
        "role":"main","role_locator":"TEST_ONLY heading","role_evidence":"TEST_ONLY fabricated main-course evidence"}


def test_review_contract_rejects_missing_or_fake_protocol_fields():
    body=submission(9)
    assert admin_review.validate_submission(body)["role"]=="main"
    with pytest.raises(ValueError):admin_review.validate_submission({**body,"source_url":"file:///tmp/source"})
    with pytest.raises(ValueError):admin_review.validate_submission({**body,"servings":4})
    with pytest.raises(ValueError):admin_review.validate_revision_action({"revision_id":True,"rationale":"long enough rationale"})
    with pytest.raises(ValueError):admin_review.validate_source_decision({"source_id":1,"evidence_set_id":1,"decision":"APPROVED","rationale":"short"})


def _identity_fixture(connection):
    sql(connection,"""INSERT INTO v2_sources(id,source_kind,title,url,document_ref,accessed_at,verification_status)
        VALUES(1,'TEST_ONLY','TEST_ONLY identity source','https://example.test/TEST_ONLY','TEST_ONLY',UTC_TIMESTAMP(6),'APPROVED')""")
    sql(connection,"INSERT INTO v2_evidence_sets VALUES(1,'TEST_ONLY identity evidence')")
    sql(connection,"""INSERT INTO v2_ingredients(id,canonical_name,normalized_name,identity_status,evidence_set_id)
        VALUES(1001,'TEST_ONLY ingredient','test_only ingredient','APPROVED',1)""")
    sql(connection,"""INSERT INTO v2_evidence(id,source_id,locator,excerpt_or_observation,claim_scope,entity_ref,captured_at)
        VALUES(1,1,'TEST_ONLY fixture','TEST_ONLY identity observation','ingredient_identity','ingredient_identity:1001',UTC_TIMESTAMP(6))""")
    sql(connection,"INSERT INTO v2_evidence_set_members VALUES(1,1)")
    claim={"id":1001,"legacy_ingredient_id":None,"canonical_name":"TEST_ONLY ingredient","normalized_name":"test_only ingredient"}
    sql(connection,"""INSERT INTO v2_review_decisions VALUES(1,'APPROVED','TEST_ONLY reviewer',UTC_TIMESTAMP(6),
        'TEST_ONLY fixture only','ingredient_identity','ingredient_identity:1001',%s,1)""",(subject_hash("ingredient_identity",claim),))
    sql(connection,"UPDATE v2_ingredients SET review_decision_id=1 WHERE id=1001")
    sql(connection,"INSERT INTO v2_recipes(id,origin_kind,author_ref) VALUES(1001,'curated_new','TEST_ONLY')")
    sql(connection,"""INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,instructions,minutes,status)
        VALUES(2001,1001,1,'TEST_ONLY pumpkin dish','TEST_ONLY steps',20,'DRAFT')""")
    sql(connection,"""INSERT INTO v2_recipe_ingredient_lines(revision_id,line_no,ingredient_id,quantity_raw,requirement,status)
        VALUES(2001,1,1001,'TEST_ONLY amount','required','DRAFT')""")


def test_submit_verify_approve_publish_user_search_and_unpublish_are_atomic(mysql_db,monkeypatch):
    connection,config=mysql_db
    migrate_v2.run(connection,"apply")
    before=legacy_hashes(connection)
    _identity_fixture(connection)
    repo=MySQLRepository(config,pool_size=2)
    def writer():
        return mysql.connector.connect(**{**config,"autocommit":False})
    monkeypatch.setattr(repo,"_admin_writer",writer)
    body=admin_review.validate_submission(submission(2001))
    submitted=repo.admin_submit_review(body,"TEST_ONLY_ADMIN")
    assert submitted["status"]=="NEEDS_VERIFICATION"
    assert sql(connection,"SELECT verification_status FROM v2_sources WHERE id=%s",(submitted["source_id"],))[0]["verification_status"]=="NEEDS_VERIFICATION"
    with pytest.raises(AdminReviewBlocked):
        repo.admin_approve_recipe({"revision_id":2001,"rationale":"TEST_ONLY before source verification"},"TEST_ONLY_ADMIN")
    assert sql(connection,"SELECT active_release_id FROM v2_calculation_settings WHERE id=1")==[]
    repo.admin_review_source({"source_id":submitted["source_id"],"evidence_set_id":submitted["evidence_set_id"],
        "decision":"APPROVED","rationale":"TEST_ONLY simulated manual verification"},"TEST_ONLY_ADMIN")
    approved=repo.admin_approve_recipe({"revision_id":2001,"rationale":"TEST_ONLY simulated content decision"},"TEST_ONLY_ADMIN")
    assert approved["quantity_status"]=="UNCHANGED"
    assert sql(connection,"SELECT status FROM v2_recipe_ingredient_lines WHERE revision_id=2001")[0]["status"]=="DRAFT"
    assert load_catalog(connection).details=={}
    release=repo.admin_publish_release({"release_id":approved["release_id"],
        "rationale":"TEST_ONLY simulated release decision"},"TEST_ONLY_ADMIN")
    assert release["status"]=="PUBLISHED"
    catalog=load_catalog(connection)
    public_id=v2_public_id(1001)
    assert catalog.details[public_id]["title"]=="TEST_ONLY pumpkin dish"
    assert catalog.roles[public_id]=="main"
    search,_=dispatch(repo,{"version":1,"request_id":REQUEST_ID,"op":"SEARCH_RECIPES",
        "payload":{"query":"TEST_ONLY pumpkin","limit":12,"offset":0}})
    assert search["ok"] and any(row["recipe_id"]==public_id for row in search["data"]["items"])
    detail,_=dispatch(repo,{"version":1,"request_id":REQUEST_ID,"op":"GET_RECIPE","payload":{"recipe_id":public_id}})
    assert detail["ok"] and detail["data"]["title"]=="TEST_ONLY pumpkin dish"
    from source.server.published_repository import PublishedRepository
    public=PublishedRepository(repo,catalog)
    assert public.get_recipe(connection,public_id)["title"]=="TEST_ONLY pumpkin dish"
    sql(connection,"INSERT INTO v2_recipes(id,origin_kind,author_ref) VALUES(1002,'curated_new','TEST_ONLY')")
    sql(connection,"""INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,instructions,minutes,status)
        VALUES(2002,1002,1,'TEST_ONLY second dish','TEST_ONLY steps',10,'DRAFT')""")
    sql(connection,"""INSERT INTO v2_recipe_ingredient_lines(revision_id,line_no,ingredient_id,requirement,status)
        VALUES(2002,1,1001,'required','DRAFT')""")
    second_submission=repo.admin_submit_review(admin_review.validate_submission(submission(2002)),"TEST_ONLY_ADMIN")
    repo.admin_review_source({"source_id":second_submission["source_id"],"evidence_set_id":second_submission["evidence_set_id"],
        "decision":"APPROVED","rationale":"TEST_ONLY simulated verification"},"TEST_ONLY_ADMIN")
    second_approval=repo.admin_approve_recipe({"revision_id":2002,"rationale":"TEST_ONLY second content decision"},"TEST_ONLY_ADMIN")
    repo.admin_publish_release({"release_id":second_approval["release_id"],"rationale":"TEST_ONLY second release"},"TEST_ONLY_ADMIN")
    second_public_id=v2_public_id(1002)
    assert {public_id,second_public_id} <= load_catalog(connection).details.keys()
    removed=repo.admin_unpublish_recipe({"recipe_id":second_public_id,"rationale":"TEST_ONLY remove second dish"},"TEST_ONLY_ADMIN")
    assert public_id in load_catalog(connection).details
    removed=repo.admin_unpublish_recipe({"recipe_id":public_id,"rationale":"TEST_ONLY simulated unpublish"},"TEST_ONLY_ADMIN")
    assert removed["removed_recipe_id"]==public_id
    assert not load_catalog(connection).details
    hidden,_=dispatch(repo,{"version":1,"request_id":REQUEST_ID,"op":"SEARCH_RECIPES",
        "payload":{"query":"TEST_ONLY pumpkin","limit":12,"offset":0}})
    assert hidden["ok"] and all(row["recipe_id"]!=public_id for row in hidden["data"]["items"])
    sql(connection,"INSERT INTO v2_recipes(id,origin_kind,author_ref) VALUES(1003,'curated_new','TEST_ONLY')")
    sql(connection,"""INSERT INTO v2_recipe_revisions(id,recipe_id,revision_no,title,instructions,minutes,status)
        VALUES(2003,1003,1,'TEST_ONLY rejected dish','TEST_ONLY steps',10,'DRAFT')""")
    sql(connection,"""INSERT INTO v2_recipe_ingredient_lines(revision_id,line_no,ingredient_id,requirement,status)
        VALUES(2003,1,1001,'required','DRAFT')""")
    rejected_submission=repo.admin_submit_review(admin_review.validate_submission(submission(2003)),"TEST_ONLY_ADMIN")
    rejected=repo.admin_reject_recipe({"revision_id":2003,"rationale":"TEST_ONLY evidence is insufficient"},"TEST_ONLY_ADMIN")
    assert rejected["status"]=="REJECTED"
    assert sql(connection,"SELECT status FROM v2_recipe_revisions WHERE id=2003")[0]["status"]=="REJECTED"
    assert sql(connection,"SELECT verification_status FROM v2_sources WHERE id=%s",(rejected_submission["source_id"],))[0]["verification_status"]=="NEEDS_VERIFICATION"
    assert legacy_hashes(connection)==before


def test_review_tcp_operations_require_admin_token(mysql_db):
    connection,config=mysql_db
    migrate_v2.run(connection,"apply")
    repo=MySQLRepository(config,pool_size=1)
    request={"version":1,"request_id":REQUEST_ID,"op":"ADMIN_SUBMIT_REVIEW","payload":submission(2)}
    with pytest.raises(ProtocolError,match="administrator authentication") as error:
        dispatch(repo,request)
    assert error.value.code=="ADMIN_UNAUTHORIZED"
