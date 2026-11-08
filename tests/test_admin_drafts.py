"""TEST_ONLY transaction/validation cases; these fakes never connect to MySQL."""
import pytest

from source.common.protocol import ProtocolError
from source.common.catalog_ids import V2_OFFSET
from source.server.admin_drafts import validate_draft_fields
from source.server.repository import AdminDraftConflict,AdminSchemaUnavailable,MySQLRepository
from tests.meal_plan_fixtures import REQUEST_ID


def payload(**updates):
    body={"title":"TEST_ONLY draft","description":"TEST_ONLY description","instructions":"TEST_ONLY steps",
          "minutes":12,"ingredients":[{"ingredient_id":V2_OFFSET+11,"quantity_raw":"TEST_ONLY raw amount","requirement":"unknown"}]}
    body.update(updates);return body


@pytest.mark.parametrize("bad",[
    {"title":"  "},{"title":"x"*256},{"description":"x"*1001},{"instructions":""},
    {"minutes":True},{"minutes":241},{"ingredients":[]},{"ingredients":[{"ingredient_id":0,"quantity_raw":None,"requirement":"unknown"}]},
    {"ingredients":[{"ingredient_id":V2_OFFSET+11,"quantity_raw":None,"requirement":[]}]},
    {"ingredients":[{"ingredient_id":V2_OFFSET+11,"quantity_raw":"1 tsp","requirement":"required"},
                     {"ingredient_id":V2_OFFSET+11,"quantity_raw":"2 tsp","requirement":"optional"}]},
])
def test_draft_payload_validation_rejects_bad_fields_at_tcp(bad):
    with pytest.raises(ProtocolError) as exc:
        validate_draft_fields(payload(**bad),REQUEST_ID)
    assert exc.value.code=="INVALID_PAYLOAD"


def test_draft_payload_normalizes_text_without_guessing_quantity_or_status():
    result=validate_draft_fields(payload(title=" TEST_ONLY name ",description="  "),REQUEST_ID)
    assert result["title"]=="TEST_ONLY name" and result["description"]==""
    assert result["ingredients"][0]["quantity_raw"]=="TEST_ONLY raw amount"
    assert result["ingredients"][0]["requirement"]=="unknown"


class FakeCursor:
    def __init__(self,connection,dictionary=False):self.c=connection;self.rows=[];self.rowcount=1
    def execute(self,sql,params=()):
        self.c.sql.append((sql,params));self.rows=[]
        if "GET_LOCK" in sql:self.rows=[(1,)]
        elif "RELEASE_LOCK" in sql:self.rows=[(1,)]
        elif "SHOW COLUMNS" in sql:self.rows=[] if self.c.no_description else [("description",)]
        elif "COALESCE(MAX(id),0)+1 FROM v2_recipes" in sql:self.rows=[(11,)]
        elif "COALESCE(MAX(id),0)+1 FROM v2_recipe_revisions" in sql:self.rows=[(21,)]
        elif "FROM v2_ingredients i LEFT JOIN v2_ingredient_admin_state" in sql:self.rows=[(11,1)]
        elif "COUNT(*) FROM v2_ingredients" in sql:self.rows=[(len(set(params)),)]
        elif "FROM v2_recipe_revisions r WHERE" in sql:self.rows=[{"status":self.c.status,"content_review_id":self.c.review,
            "servings_review_id":None,"released":self.c.released}]
        elif "quantity_review_id,scaling_review_id" in sql:self.rows=self.c.line_reviews
        elif "UPDATE v2_recipe_revisions" in sql:self.rowcount=1
    def executemany(self,sql,rows):
        self.c.sql.append((sql,rows))
        if self.c.fail_lines:raise RuntimeError("TEST_ONLY insert fault")
    def fetchone(self):return self.rows.pop(0) if self.rows else None
    def fetchall(self):rows,self.rows=self.rows,[];return rows
    def close(self):
        if self.c.fail_unread_release and any("RELEASE_LOCK" in sql and self.rows for sql,_ in self.c.sql):
            raise RuntimeError("TEST_ONLY unread MySQL result")


class FakeConnection:
    def __init__(self,*,fail_lines=False,no_description=False,status="DRAFT",review=None,released=0,line_reviews=(),fail_unread_release=False):
        self.sql=[];self.fail_lines=fail_lines;self.no_description=no_description;self.status=status
        self.review=review;self.released=released;self.line_reviews=list(line_reviews);self.fail_unread_release=fail_unread_release
        self.committed=False;self.rolled_back=False;self.closed=False
    def cursor(self,dictionary=False):return FakeCursor(self,dictionary)
    def commit(self):self.committed=True
    def rollback(self):self.rolled_back=True
    def close(self):self.closed=True


@pytest.fixture
def repository(monkeypatch):
    repo=MySQLRepository.__new__(MySQLRepository);repo.config={"user":"TEST_ONLY_reader"}
    connections=[]
    def connect():
        c=FakeConnection();connections.append(c);return c
    monkeypatch.setattr(repo,"_admin_writer",connect)
    return repo,connections


def test_create_draft_writes_one_atomic_v2_revision(repository):
    repo,connections=repository
    result=repo.admin_create_draft(validate_draft_fields(payload(),REQUEST_ID),"TEST_ONLY_ADMIN")
    c=connections[0]
    assert result=={"recipe_id":11,"revision_id":21,"revision_no":1,"status":"DRAFT"}
    assert c.committed and not c.rolled_back and c.closed
    writes=[sql for sql,_ in c.sql if sql.startswith(("INSERT INTO","UPDATE","DELETE FROM"))]
    assert len(writes)==3 and "v2_recipes" in writes[0] and "v2_recipe_revisions" in writes[1]
    assert "v2_recipe_ingredient_lines" in writes[2]
    assert "status" not in writes[1].split("VALUES",1)[0].casefold()
    assert "status" not in writes[2].split("VALUES",1)[0].casefold()


def test_create_consumes_release_lock_result_before_closing_cursor(repository):
    repo,connections=repository;connections.clear()
    c=FakeConnection(fail_unread_release=True);repo._admin_writer=lambda:c
    result=repo.admin_create_draft(validate_draft_fields(payload(),REQUEST_ID),"TEST_ONLY_ADMIN")
    assert result["status"]=="DRAFT" and c.committed and c.closed


def test_create_draft_rolls_back_when_ingredient_line_insert_fails(repository):
    repo,connections=repository;connections.clear()
    c=FakeConnection(fail_lines=True)
    repo._admin_writer=lambda:c
    with pytest.raises(RuntimeError,match="TEST_ONLY"):
        repo.admin_create_draft(validate_draft_fields(payload(),REQUEST_ID),"TEST_ONLY_ADMIN")
    assert c.rolled_back and not c.committed and c.closed


def test_schema_gap_fails_before_any_draft_write(repository):
    repo,connections=repository;connections.clear()
    c=FakeConnection(no_description=True);repo._admin_writer=lambda:c
    with pytest.raises(AdminSchemaUnavailable):
        repo.admin_create_draft(validate_draft_fields(payload(),REQUEST_ID),"TEST_ONLY_ADMIN")
    assert c.rolled_back and not c.committed
    assert not any(sql.startswith("INSERT INTO") for sql,_ in c.sql)


def test_edit_draft_updates_only_draft_content_and_lines_atomically(repository):
    repo,connections=repository;connections.clear()
    c=FakeConnection();repo._admin_writer=lambda:c
    update=validate_draft_fields(payload(revision_id=21,title="TEST_ONLY revised"),REQUEST_ID,update=True)
    assert repo.admin_update_draft(update)=={"revision_id":21,"status":"DRAFT"}
    assert c.committed and not c.rolled_back and c.closed
    writes=[sql for sql,_ in c.sql if sql.startswith(("UPDATE","DELETE FROM","INSERT INTO"))]
    assert len(writes)==3 and writes[0].startswith("UPDATE v2_recipe_revisions")
    assert writes[1].startswith("DELETE FROM v2_recipe_ingredient_lines")
    assert writes[2].startswith("INSERT INTO v2_recipe_ingredient_lines")


@pytest.mark.parametrize("state",[("APPROVED",None,0),("NEEDS_VERIFICATION",None,0),
                                   ("DRAFT",None,1),("DRAFT",88,0)])
def test_only_unreviewed_unreleased_draft_can_be_edited(repository,state):
    repo,connections=repository;connections.clear()
    status,review,released=state;c=FakeConnection(status=status,review=review,released=released);repo._admin_writer=lambda:c
    update=validate_draft_fields(payload(revision_id=21),REQUEST_ID,update=True)
    if status!="DRAFT" or review is not None or released:
        with pytest.raises(AdminDraftConflict):repo.admin_update_draft(update)
        assert c.rolled_back and not any(sql.startswith("UPDATE") or sql.startswith("DELETE") for sql,_ in c.sql)
