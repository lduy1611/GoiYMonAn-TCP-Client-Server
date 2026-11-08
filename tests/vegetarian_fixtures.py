"""TEST_ONLY complete plant recipes/reviews, never real approvals or MySQL data."""
from copy import deepcopy
import sqlite3

from source.server.vegetarian import PROFILE, snapshot_hash
from tests.meal_plan_fixtures import full_dataset, sql_rows

IDS = (4,44,5,9,6,32)


def review_for(recipe):
    return {"recipe_id":recipe['id'], "profile":PROFILE, "status":"VERIFIED",
        "snapshot_sha256":snapshot_hash(recipe), "components_complete":True,
        "instructions_complete":True, "optional_components_included":True, "unresolved":[],
        "reviewer_ref":"TEST_ONLY reviewer fixture", "reviewed_on":"TEST_ONLY",
        "evidence_ref":"TEST_ONLY synthetic complete declaration; not a real source",
        "ingredient_evidence":[{"ingredient_id":i['id'], "classification":"plant_or_mineral",
                                "evidence_ref":"TEST_ONLY full component declaration"} for i in recipe['ingredients']],
        "instruction_only_components":[]}


def fixture_data():
    recipes,details=deepcopy(full_dataset())
    names={r[0]:r[1] for r in sql_rows('ingredients')}
    components={4:[2,5,7],44:[5,46,8],5:[6,7],9:[11,10,3],6:[2,5],32:[46,5,8]}
    for rid,ids in components.items():
        detail=next(r for r in details if r['id']==rid)
        detail.update(title='TEST_ONLY plant recipe '+str(rid),
                      instructions='TEST_ONLY: Cook only the declared components; add nothing else.',source_url=None)
        detail['ingredients']=[{'id':iid,'name':names[iid],'quantity':'TEST_ONLY 1 portion','is_required':j<2} for j,iid in enumerate(ids)]
        candidate=next(r for r in recipes if r['id']==rid)
        candidate.update(title=detail['title'],required_ids=set(ids[:2]),all_ids=set(ids))
    reviews={r['id']:review_for(r) for r in details if r['id'] in IDS}
    return recipes,details,names,reviews


def install_private_fixture(repository, monkeypatch):
    from source.server import vegetarian
    recipes,details,names,reviews=fixture_data()
    # The normal test fixture supplies a private temporary SQLite path, never MySQL.
    assert repository.__class__.__name__=='Repository' and repository.db_path.name=='meal-web.sqlite'
    with sqlite3.connect(repository.db_path) as connection:
        for detail in (d for d in details if d['id'] in IDS):
            connection.execute('UPDATE recipes SET title=?,instructions=?,source_url=NULL WHERE id=?',
                               (detail['title'],detail['instructions'],detail['id']))
            connection.execute('DELETE FROM recipe_ingredients WHERE recipe_id=?',(detail['id'],))
            connection.executemany('INSERT INTO recipe_ingredients VALUES(?,?,?,?)',
                [(detail['id'],i['id'],i['quantity'],int(i['is_required'])) for i in detail['ingredients']])
    monkeypatch.setattr(vegetarian,'read_reviews',lambda:reviews)
    return reviews
