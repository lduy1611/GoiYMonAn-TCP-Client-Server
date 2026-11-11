"""Add-only vegetarian source dossiers -> migration 001, ALWAYS unapproved.

Dry-run by default. --apply --draft-only writes only whitelisted v2 tables in
one transaction. No legacy writes, UPDATE/DELETE, review/release writer or DDL.
Source recipe identities are independent of legacy IDs and of batch names.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

import mysql.connector

from source.database import import_v2_drafts as common
from source.database import migrate_v2

FORMAT = "vegetarian-v2-source-batch-1"
STATUS = "NEEDS_VERIFICATION"
ImportError = common.ImportError
need, number, text, digest = common._need, common._number, common._text, common._hash


def identity(table, key):
    return common._id(table, "vegetarian-source-v1/" + key)


def source_key(recipe):
    url = urlsplit(recipe["source"]["url"])
    need(url.scheme == "https" and bool(url.hostname) and not url.username and not url.password,
         "An HTTPS source URL without credentials is required")
    canonical = urlunsplit(("https", url.netloc.lower(), url.path.rstrip("/") + "/", "", ""))
    return canonical + "#" + recipe["source"]["variant_key"]


def validate(document, recipe_keys=None):
    need(isinstance(document, dict) and document.get("format") == FORMAT, "Unsupported source dossier")
    common._unapproved(document)
    need(document.get("publication_allowed") is False, "Publication must remain disabled")
    rows = document.get("recipes")
    need(isinstance(rows, list) and 1 <= len(rows) <= 20, "Expected 1..20 source recipes")
    selected, seen, sources = [], set(), set()
    for recipe in rows:
        need(not {"recipe_id", "revision_id", "source_id", "legacy_recipe_id"} & set(recipe), "Database IDs are allocated by the importer")
        key = text(recipe.get("recipe_key"), 40, "recipe key")
        need(key not in seen, "Duplicate recipe key"); seen.add(key)
        source = recipe.get("source")
        need(isinstance(source, dict), "Missing source")
        text(source.get("url"), 1000, "source URL")
        text(source.get("variant_key"), 80, "source variant")
        skey = source_key(recipe)
        need(skey not in sources, "Duplicate source recipe variant"); sources.add(skey)
        need(source.get("access_status") == "DIRECT_CONTENT_OBSERVED", "Search snippets or inaccessible sources cannot be imported")
        need(source.get("verification_status") == STATUS and recipe.get("review_status") == STATUS,
             "This writer only accepts NEEDS_VERIFICATION source records")
        for name in ("publisher", "author", "observed_on", "locator"):
            text(source.get(name), 500, "source " + name)
        need(re.fullmatch(r"\d{4}-\d{2}-\d{2}", source["observed_on"]) is not None, "Invalid observation date")
        try:date.fromisoformat(source["observed_on"])
        except ValueError as exc:raise ImportError("Invalid observation date") from exc
        need(recipe.get("role_proposed") in ("main", "vegetable", "soup"), "Unknown proposed role")
        text(recipe.get("title"), 255, "title")
        need(type(recipe.get("revision_no")) is int and 1 <= recipe["revision_no"] <= 10000, "Invalid revision number")
        lineage = recipe.get("candidate_legacy_recipe_id")
        need(lineage is None or type(lineage) is int and 1 <= lineage <= 4294967295, "Invalid candidate legacy identity")
        need(recipe.get("content_complete") is False, "Draft import cannot assert reviewed completeness")
        need(recipe.get("reviewer_ref") is None and recipe.get("reviewed_on") is None, "Draft import cannot invent a review identity/date")
        number(recipe.get("base_servings"), 3, 7)
        need((recipe.get("base_servings") is None) == (recipe.get("serving_basis") is None), "Unknown servings must not get a basis/default")
        need(recipe.get("serving_basis") in (None, "source_servings"), "Unsupported serving basis")
        need(recipe.get("minutes") is None or type(recipe["minutes"]) is int and 1 <= recipe["minutes"] <= 240,
             "Invalid source total time")
        steps = recipe.get("instructions_paraphrased")
        need(isinstance(steps, list) and 1 <= len(steps) <= 12 and all(isinstance(s, str) and s.strip() for s in steps),
             "Expected short source-based instruction summaries")
        lines = recipe.get("ingredient_lines")
        need(isinstance(lines, list) and 1 <= len(lines) <= 64, "Invalid component count")
        need(all(type(l.get("line_no")) is int for l in lines) and [l.get("line_no") for l in lines] == list(range(1, len(lines)+1)), "Component lines must be contiguous and unique")
        for line in lines:
            need(not {"ingredient_id", "unit_id", "form_id"} & set(line), "Do not mix source observations with unverified database IDs")
            name = text(line.get("source_name"), 255, "source ingredient")
            # A source-qualified vegan product is retained AS SUCH, never created
            # by replacing an animal ingredient in a different source recipe.
            qualified = re.sub(r"\bvegan\s+(?:fish sauce|ground meat substitute|shrimp|egg liquid|butter)\b|\b(?:soy|coconut) milk\b", "plant-product", name.casefold())
            need(not re.search(r"\b(?:fish sauce|oyster sauce|pork|chicken|beef|shrimp|egg|milk|lard|butter)\b|nước mắm|dầu hào|thịt|sườn", qualified),
                 "Unqualified animal component in a vegetarian source dossier: " + name)
            need(line.get("review_status") == STATUS, "Unapproved component required")
            need(line.get("requirement") in ("required", "optional", "unknown"), "Invalid requirement")
            need(line.get("purpose") in ("consumed", "cooking_medium", "garnish"), "Invalid purpose")
            need(line.get("amount_kind") in ("exact", "range", "to_taste", "as_needed", "unknown"), "Invalid amount kind")
            text(line.get("quantity_raw"), 255, "raw source quantity")
            text(line.get("evidence_locator"), 500, "component locator")
            if line.get("unit") is not None: text(line["unit"], 40, "source unit")
            kind = line["amount_kind"]
            value, low, high = (number(line.get(k)) for k in ("quantity_value", "quantity_min", "quantity_max"))
            if kind == "exact":
                need(value is not None and low is None and high is None and line.get("unit") is not None, "Invalid scalar quantity")
            elif kind == "range":
                need(value is None and low is not None and high is not None and low <= high and line.get("unit") is not None, "Invalid quantity range")
            else:
                need(value is None and low is None and high is None, "Unknown amounts cannot become zero or guessed values")
            need(line.get("source_url", source["url"]) == source["url"], "Do not mix component data from different sources")
            if "source_fraction" in line:
                fraction = line["source_fraction"]
                need(kind == "unknown" and type(fraction.get("numerator")) is int and type(fraction.get("denominator")) is int
                     and fraction["numerator"] > 0 and fraction["denominator"] > 0, "Do not silently round source fractions")
        if recipe_keys is None or key in recipe_keys: selected.append(recipe)
    need(recipe_keys is None or set(recipe_keys) <= seen, "Unknown selected recipe key")
    need(bool(selected), "Empty import selection")
    return selected


def load_document(path):
    path = Path(path)
    need(path.stat().st_size <= 2_000_000, "Dossier too large")
    def distinct(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, "Duplicate JSON key"); result[key] = value
        return result
    result = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=distinct,
                        parse_constant=lambda _: (_ for _ in ()).throw(ImportError("Invalid JSON number")))
    validate(result)
    return result


def build_plan(document, batch_key, recipe_keys=None):
    need(re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", batch_key) is not None, "Invalid batch key")
    recipes = validate(document, recipe_keys)
    bundle = {"format": FORMAT, "batch_key": batch_key, "recipes": recipes}
    plan = common.Plan()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    def evidence_set(key, description):
        eid = identity("v2_evidence_sets", key)
        plan.add("v2_evidence_sets", {"id": eid, "description": description})
        return eid
    def evidence(key, source_id, scope, ref, locator, value, group=None):
        encoded = common._json(value)
        need(len(encoded.encode()) <= 65535, "Evidence exceeds TEXT size")
        eid = identity("v2_evidence", key)
        plan.add("v2_evidence", {"id": eid, "source_id": source_id, "locator": locator,
            "excerpt_or_observation": encoded, "claim_scope": scope, "entity_ref": ref,
            "captured_at": now, "content_hash": sha256(encoded.encode()).hexdigest()})
        if group is not None:plan.add("v2_evidence_set_members", {"evidence_set_id": group, "evidence_id": eid})
    internal = identity("v2_sources", "bundle/"+batch_key)
    plan.add("v2_sources", {"id": internal, "source_kind": "internal_dossier", "title": batch_key,
        "url": None, "document_ref": "vegetarian-draft:"+batch_key, "author_or_publisher": None,
        "accessed_at": None, "content_hash": digest(bundle), "usage_note": "Draft-only; no approval, release or legacy update.", "verification_status": STATUS})
    evidence("bundle/"+batch_key, internal, "import_manifest", "batch:"+batch_key, "selected records from recipes.json", {
        "format":FORMAT,"batch_key":batch_key,"bundle_hash":digest(bundle),
        "records":[{"recipe_key":r["recipe_key"],"revision_no":r["revision_no"],"record_hash":digest(r)} for r in recipes],
        "storage":"Each complete selected record is retained in its own recipe_content evidence; manifest avoids TEXT truncation."})
    mapping = []
    for recipe in recipes:
        key = source_key(recipe)
        rid = identity("v2_recipes", key)
        revision = identity("v2_recipe_revisions", key+"/"+str(recipe["revision_no"]))
        ref = "revision:"+str(revision)
        sid = identity("v2_sources", key+"/"+digest(recipe))
        source = recipe["source"]
        plan.add("v2_sources", {"id":sid, "source_kind":"candidate_recipe_reference", "title":recipe["title"],
            "url":source["url"], "document_ref":recipe["recipe_key"], "author_or_publisher":source["author"]+" / "+source["publisher"],
            "accessed_at":None, "content_hash":source.get("source_content_sha256"), "usage_note":common._json(source), "verification_status":STATUS})
        content = evidence_set(ref+"/content", "NEEDS_VERIFICATION: source recipe content")
        servings = evidence_set(ref+"/servings", "NEEDS_VERIFICATION: source servings")
        evidence(ref+"/content", sid, "recipe_content", ref, source["locator"], recipe, content)
        evidence(ref+"/servings", sid, "servings", ref, source["locator"], {
            "base_servings":recipe["base_servings"], "servings_raw":recipe["servings_raw"], "status":STATUS}, servings)
        for scope, value in (("role", recipe["role_proposed"]), ("diet", recipe["diet_claim"])):
            evidence(ref+"/"+scope, sid, scope, ref, source["locator"], {"proposal":value,"status":STATUS}, content)
        plan.add("v2_recipes", {"id":rid, "legacy_recipe_id":None, "variant_of_recipe_id":None, "origin_kind":"curated_new", "author_ref":source["author"]})
        plan.add("v2_recipe_revisions", {"id":revision, "recipe_id":rid, "revision_no":recipe["revision_no"], "title":recipe["title"],
            "instructions":"\n".join(recipe["instructions_paraphrased"]), "minutes":recipe["minutes"], "base_servings":number(recipe["base_servings"],3,7),
            "serving_basis":recipe["serving_basis"], "content_complete":0, "status":STATUS,
            "content_evidence_set_id":content, "servings_evidence_set_id":servings, "content_review_id":None,
            "servings_review_id":None, "legacy_snapshot_hash":None})
        mapping.append({"recipe_key":recipe["recipe_key"], "recipe_id":rid, "revision_id":revision})
        for line in recipe["ingredient_lines"]:
            name = line["source_name"]
            canonical = " ".join(unicodedata.normalize("NFC",name).casefold().split())
            iid = identity("v2_ingredients", canonical)
            plan.add("v2_ingredients", {"id":iid, "legacy_ingredient_id":None, "canonical_name":canonical,
                "normalized_name":canonical, "identity_status":STATUS, "evidence_set_id":None, "review_decision_id":None})
            uid = None
            if line.get("unit"):
                label = line["unit"]
                uid = identity("v2_units", label)
                plan.add("v2_units", {"id":uid, "code":"veg_"+sha256(label.encode()).hexdigest()[:20],
                    "dimension":{"g":"mass","ml":"volume","lb":"mass"}.get(label,"source_defined"), "symbol":label,
                    "definition":"Unreviewed source label; no conversion asserted: "+label,
                    "status":STATUS, "evidence_set_id":None, "review_decision_id":None})
            line_ref = ref+":"+str(line["line_no"])
            qset = evidence_set(line_ref, "NEEDS_VERIFICATION: complete source component observation")
            evidence(line_ref, sid, "quantity", line_ref, line["evidence_locator"], line, qset)
            # Preserve the original observation/identity for safe replay of old
            # draft batches. Add a canonical calculator binding, never rewrite
            # an observation or manufacture an approval on existing data.
            canonical_ref = "line:"+str(revision)+":"+str(line["line_no"])
            evidence(canonical_ref+"/quantity", sid, "quantity", canonical_ref,
                     line["evidence_locator"], line, qset)
            amount = number(line["quantity_value"]) if line["amount_kind"]=="exact" else number(line["quantity_min"])
            plan.add("v2_recipe_ingredient_lines", {"revision_id":revision, "line_no":line["line_no"], "ingredient_id":iid,
                "form_id":None, "quantity_raw":line["quantity_raw"], "amount_kind":line["amount_kind"], "amount_min":amount,
                "amount_max":number(line["quantity_max"]), "unit_id":uid, "requirement":line["requirement"], "purpose":line["purpose"],
                "measurement_basis":"unknown", "scaling_mode":None, "status":STATUS, "quantity_evidence_set_id":qset,
                "quantity_review_id":None, "scaling_evidence_set_id":None, "scaling_review_id":None, "legacy_relation_hash":None})
    return plan, mapping, digest(bundle)


def import_drafts(connection, document, batch_key, recipe_keys=None, *, apply=False):
    plan, mapping, bundle_hash = build_plan(document, batch_key, recipe_keys)
    need(not connection.in_transaction, "Use a dedicated idle import connection")
    original = connection.autocommit
    connection.autocommit = True
    lock = None
    try:
        database = common._query(connection, "SELECT DATABASE() AS name")[0]["name"]
        lock = "v2-draft-import-"+sha256(database.encode()).hexdigest()[:32]
        need(common._query(connection,"SELECT GET_LOCK(%s,5) AS ok",(lock,))[0]["ok"]==1,"Another import holds the lock")
        need(migrate_v2.check(connection)["state"]=="APPLIED","Migration 001 must be present; this command never migrates")
        need(common._query(connection,"SELECT @@SESSION.foreign_key_checks AS ok")[0]["ok"]==1,"Keep FK checks enabled")
        connection.start_transaction(isolation_level="SERIALIZABLE")
        lineage_ids = sorted({r.get("candidate_legacy_recipe_id") for r in validate(document,recipe_keys) if r.get("candidate_legacy_recipe_id") is not None})
        if lineage_ids:
            rows = common._query(connection,"SELECT id FROM recipes WHERE id IN ("+','.join('%s' for _ in lineage_ids)+")",tuple(lineage_ids))
            need({r['id'] for r in rows} == set(lineage_ids), "Candidate legacy identity does not exist; no legacy rows are created")
        added, reused = {}, {}
        for table, rows in plan.rows.items():
            added[table] = reused[table] = 0
            for row in rows.values():
                if common._ensure(connection,table,row,apply):added[table]+=1
                else:reused[table]+=1
        if apply:connection.commit()
        else:connection.rollback()
        return {"database":database,"batch_key":batch_key,"bundle_hash":bundle_hash,"applied":apply,
            "inserted" if apply else "would_insert":added,"reused":reused,"recipes":mapping,"status":STATUS}
    except Exception:
        connection.rollback();raise
    finally:
        if lock:common._query(connection,"SELECT RELEASE_LOCK(%s)",(lock,))
        connection.autocommit = original


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--json',required=True)
    parser.add_argument('--batch-key',required=True)
    parser.add_argument('--recipe-keys',help='Comma-separated keys; omit to select the complete dossier')
    parser.add_argument('--draft-only',action='store_true',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    from dotenv import dotenv_values
    from source.server.repository import mysql_config_from_env
    config=mysql_config_from_env();values=dotenv_values(Path(__file__).resolve().parents[2]/'.env')
    for key in ('user','password'):
        value=values.get('MYSQL_MIGRATION_'+key.upper())
        need(value is not None,'Missing dedicated migration credentials');config[key]=value
    need(config['user']!='goiy_app','Runtime account cannot import data')
    config['database']=args.database
    document=load_document(args.json)
    selected=args.recipe_keys.split(',') if args.recipe_keys else None
    connection=mysql.connector.connect(**config)
    try:print(json.dumps(import_drafts(connection,document,args.batch_key,selected,apply=args.apply),ensure_ascii=True))
    finally:connection.close()


if __name__=='__main__':main()
