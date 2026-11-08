from source.database import v2_admin_schema, v2_context_schema, v2_schema


def row(version, checksum, state="APPLIED", applied_at="TEST_ONLY"):
    return {"version":version,"checksum":checksum,"execution_result":state,"applied_at":applied_at}


def test_admin_draft_migration_is_one_additive_description_column():
    statements=v2_admin_schema.statements()
    assert len(statements)==1
    normalized=" ".join(statements[0].casefold().split())
    assert normalized==("alter table v2_recipe_revisions add column description "
                        "varchar(1000) not null default '' after title")
    assert v2_admin_schema.VERSION=="003_admin_draft_description"


def test_history_accepts_known_003_without_applying_context_002():
    rows=[row(v2_schema.VERSION,v2_schema.checksum()),
          row(v2_admin_schema.VERSION,v2_admin_schema.checksum())]
    assert v2_schema.history_is_compatible(rows)


def test_history_accepts_known_001_002_003_and_rejects_unfinished_003():
    rows=[row(v2_schema.VERSION,v2_schema.checksum()),
          row(v2_context_schema.VERSION,v2_context_schema.checksum()),
          row(v2_admin_schema.VERSION,v2_admin_schema.checksum())]
    assert v2_schema.history_is_compatible(rows)
    rows[-1]=row(v2_admin_schema.VERSION,v2_admin_schema.checksum(),state="FAILED")
    assert not v2_schema.history_is_compatible(rows)
