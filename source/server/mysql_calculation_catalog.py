"""Read an activated, pinned v2 release in a single read-only MySQL snapshot.

Approvals bind scope, entity, evidence and a canonical hash of the actual claim.
Editing reviewed values invalidates eligibility; no latest-revision fallback,
proposal imports, schema creation, implicit conversion or synthetic approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json

import mysql.connector
from source.common.catalog_ids import member_id

from source.database import v2_schema
from source.server.meal_plan_calculation import (
    Allocation, Catalog, IngredientLine, PortionPolicy, Review, Revision, Unit,
)

QUANTITY_FIELDS = ("revision_id", "line_no", "ingredient_id", "form_id", "quantity_raw",
                   "amount_kind", "amount_min", "amount_max", "unit_id", "requirement", "purpose", "measurement_basis")
RULE_FIELDS = ("policy_version_id", "rule_no", "recipe_id", "revision_id", "subject_group",
               "input_definition", "serving_basis", "equivalent_servings")


def subject_hash(scope, payload):
    """Canonical v1 claim digest. Does not create or approve a review decision."""
    def canonical(value):
        if isinstance(value, Decimal):
            return format(value, "f").rstrip("0").rstrip(".") if "." in format(value, "f") else format(value, "f")
        if isinstance(value, dict):
            return {key: canonical(v) for key, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [canonical(v) for v in value]
        return value
    return sha256(json.dumps({"hash_version": 1, "scope": scope, "subject": canonical(payload)},
        ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def source_subject(row):
    """Stable source verification subject, excluding mutable status and audit pointers."""
    fields=("id","source_kind","title","url","document_ref","author_or_publisher",
            "content_hash","usage_note")
    result={key:row.get(key) for key in fields}
    accessed=row.get("accessed_at")
    result["accessed_at"]=(accessed.isoformat(sep=" ",timespec="microseconds")
                            if hasattr(accessed,"isoformat") else accessed)
    return result


def _query(connection, sql, params=()):
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()


def _by_ids(connection, table, ids, order="id"):
    # Table/order are private constants; values always use bound parameters.
    ids = sorted(set(ids))
    if not ids:
        return []
    return _query(connection, f"SELECT * FROM {table} WHERE id IN ({','.join('%s' for _ in ids)}) ORDER BY {order}", tuple(ids))


def read_snapshot(connection, recipe_ids, *, release_id=None):
    """Caller must hold the read-only transaction. Also used to inspect TEST fixtures."""
    releases = (_query(connection,"SELECT * FROM v2_data_releases WHERE id=%s",(release_id,))
        if release_id is not None else _query(connection, """SELECT r.* FROM v2_calculation_settings s
        JOIN v2_data_releases r ON r.id=s.active_release_id WHERE s.id=1"""))
    if not releases:
        return None
    release = releases[0]
    release_id = release["id"]
    members = _query(connection, """SELECT m.*,r.legacy_recipe_id,r.variant_of_recipe_id,r.origin_kind,r.author_ref
        FROM v2_release_recipes m JOIN v2_recipes r ON r.id=m.recipe_id
        WHERE m.release_id=%s ORDER BY m.recipe_id""", (release_id,))
    bindings = _query(connection, "SELECT * FROM v2_release_portion_policies WHERE release_id=%s ORDER BY selection_key", (release_id,))
    selected = members if recipe_ids is None else [m for m in members if member_id(m) in recipe_ids]
    revisions = _by_ids(connection, "v2_recipe_revisions", [m["revision_id"] for m in selected])
    revision_ids = [r["id"] for r in revisions]
    lines = _query(connection, f"SELECT * FROM v2_recipe_ingredient_lines WHERE revision_id IN ({','.join('%s' for _ in revision_ids)}) ORDER BY revision_id,line_no", tuple(revision_ids)) if revision_ids else []
    ingredients = _by_ids(connection, "v2_ingredients", [l["ingredient_id"] for l in lines if l["ingredient_id"] is not None])
    forms = _by_ids(connection, "v2_ingredient_forms", [l["form_id"] for l in lines if l["form_id"] is not None])
    units = _by_ids(connection, "v2_units", [l["unit_id"] for l in lines if l["unit_id"] is not None])
    key = ",".join(str(i) for i in sorted(recipe_ids)) if recipe_ids is not None else None
    bound = [b["policy_version_id"] for b in bindings if b["selection_key"] == key]
    policies = _by_ids(connection, "v2_portion_policy_versions", bound)
    rules = _query(connection, "SELECT * FROM v2_portion_policy_rules WHERE policy_version_id=%s ORDER BY rule_no", (bound[0],)) if bound else []
    legacy = _query(connection, "SELECT value FROM metadata WHERE `key`='dataset_version'")
    return {"release": [release], "members": members, "bindings": bindings, "selected": selected,
            "revisions": revisions, "lines": lines, "ingredients": ingredients, "forms": forms,
            "units": units, "policies": policies, "rules": rules,
            "legacy_version": legacy[0]["value"] if legacy else None}


@dataclass(frozen=True)
class Claim:
    scope: str
    entity_ref: str
    status: str
    review_id: int | None
    evidence_set_id: int | None
    payload: dict


def claims(snapshot):
    """Exact review subjects for this adapter version; no mutation or approval."""
    result = {}
    def emit(scope, ref, row, fields, status="status", review="review_decision_id", evidence="evidence_set_id", extra=None):
        payload = {key: row[key] for key in fields}
        payload.update(extra or {})
        result[(scope, ref)] = Claim(scope, ref, row[status], row[review], row[evidence], payload)
    release = snapshot["release"][0]
    emit("release", f"release:{release['id']}", release,
         ("id", "code", "legacy_dataset_version", "legacy_baseline_hash"), extra={
             "recipes": snapshot["members"], "policies": snapshot["bindings"]})
    for row in snapshot["revisions"]:
        ref = f"revision:{row['id']}"
        emit("recipe_content", ref, row, ("id", "recipe_id", "revision_no", "title", "instructions", "minutes", "content_complete"),
             review="content_review_id", evidence="content_evidence_set_id", extra={"line_membership": [
                 {key: line[key] for key in ("line_no", "ingredient_id", "form_id", "requirement")}
                 for line in snapshot["lines"] if line["revision_id"] == row["id"]]})
        emit("servings", ref, row, ("id", "base_servings", "serving_basis"),
             review="servings_review_id", evidence="servings_evidence_set_id")
    for row in snapshot["lines"]:
        ref = f"line:{row['revision_id']}:{row['line_no']}"
        emit("quantity", ref, row, QUANTITY_FIELDS, review="quantity_review_id", evidence="quantity_evidence_set_id")
        emit("scaling", ref, row, ("revision_id", "line_no", "scaling_mode"),
             review="scaling_review_id", evidence="scaling_evidence_set_id")
    for table, scope, fields, status in [
        ("ingredients", "ingredient_identity", ("id", "legacy_ingredient_id", "canonical_name", "normalized_name"), "identity_status"),
        ("forms", "ingredient_form", ("id", "ingredient_id", "form_code", "description"), "status"),
        ("units", "unit", ("id", "code", "dimension", "symbol", "definition"), "status"),
    ]:
        for row in snapshot[table]:
            emit(scope, f"{scope}:{row['id']}", row, fields, status=status)
    for row in snapshot["policies"]:
        emit("portion_policy", f"policy:{row['id']}", row, ("id", "policy_code", "version", "description"),
             extra={"rules": [{key: r[key] for key in RULE_FIELDS} for r in snapshot["rules"]]})
    for row in snapshot["rules"]:
        emit("portion_allocation", f"rule:{row['policy_version_id']}:{row['rule_no']}", row, RULE_FIELDS)
    return result


def _proofs(connection, subjects):
    ids = sorted({claim.review_id for claim in subjects.values() if claim.review_id is not None})
    decisions = _query(connection, f"""SELECT d.*, EXISTS(
        SELECT 1 FROM v2_evidence_set_members m JOIN v2_evidence e ON e.id=m.evidence_id
        JOIN v2_sources s ON s.id=e.source_id
        WHERE m.evidence_set_id=d.evidence_set_id AND e.claim_scope=d.claim_scope AND e.entity_ref=d.entity_ref
        AND CHAR_LENGTH(TRIM(e.locator))>0 AND CHAR_LENGTH(TRIM(e.excerpt_or_observation))>0
        AND s.verification_status='APPROVED' AND s.accessed_at IS NOT NULL
        AND (CHAR_LENGTH(TRIM(s.url))>0 OR CHAR_LENGTH(TRIM(s.document_ref))>0)
        ) AS has_evidence FROM v2_review_decisions d WHERE d.id IN ({','.join('%s' for _ in ids)})""", tuple(ids)) if ids else []
    decisions = {row["id"]: row for row in decisions}
    evidence_sets=sorted({claim.evidence_set_id for claim in subjects.values() if claim.evidence_set_id is not None})
    evidence_rows=_query(connection,f"""SELECT m.evidence_set_id,e.claim_scope,e.entity_ref,e.source_id,
        e.locator,e.excerpt_or_observation,s.*
        FROM v2_evidence_set_members m JOIN v2_evidence e ON e.id=m.evidence_id
        JOIN v2_sources s ON s.id=e.source_id WHERE m.evidence_set_id IN ({','.join('%s' for _ in evidence_sets)})""",
        tuple(evidence_sets)) if evidence_sets else []
    source_ids=sorted({row["source_id"] for row in evidence_rows})
    source_decisions=_query(connection,f"""SELECT * FROM v2_review_decisions WHERE claim_scope='source_verification'
        AND entity_ref IN ({','.join('%s' for _ in source_ids)}) ORDER BY decided_at,id""",
        tuple(f"source:{source_id}" for source_id in source_ids)) if source_ids else []
    source_audit_rows=_query(connection,f"""SELECT m.evidence_set_id,e.claim_scope,e.entity_ref,e.source_id
        FROM v2_evidence_set_members m JOIN v2_evidence e ON e.id=m.evidence_id
        WHERE e.claim_scope='source_verification' AND e.entity_ref IN ({','.join('%s' for _ in source_ids)})""",
        tuple(f"source:{source_id}" for source_id in source_ids)) if source_ids else []
    latest_source_review={}
    for row in source_decisions: latest_source_review[row["entity_ref"]]=row
    approved_sources=set()
    for row in evidence_rows:
        source_id=row["source_id"]
        latest=latest_source_review.get(f"source:{source_id}")
        source_audit_evidence=bool(latest and any(item["evidence_set_id"]==latest["evidence_set_id"]
            and item["source_id"]==source_id and item["claim_scope"]=="source_verification"
            and item["entity_ref"]==f"source:{source_id}" for item in source_audit_rows)
            )
        audited=(latest is None or (latest["decision"]=="APPROVED"
                 and latest["subject_hash"]==subject_hash("source_verification",source_subject(row))))
        # Older approved imports predate source audit decisions. Continue accepting those
        # unchanged rows; an Admin decision is source-global but must point to its own evidence.
        if row["verification_status"]=="APPROVED" and audited and (latest is None or source_audit_evidence):
            approved_sources.add(source_id)
    evidence_claims={(row["evidence_set_id"],row["claim_scope"],row["entity_ref"])
                     for row in evidence_rows if row["source_id"] in approved_sources
                     and str(row["locator"]).strip() and str(row["excerpt_or_observation"]).strip()}
    result = {}
    for key, claim in subjects.items():
        decision = decisions.get(claim.review_id)
        expected_status = "PUBLISHED" if claim.scope == "release" else "APPROVED"
        if (claim.status == expected_status and decision and decision["decision"] == "APPROVED"
                and decision["claim_scope"] == claim.scope and decision["entity_ref"] == claim.entity_ref
                and decision["evidence_set_id"] == claim.evidence_set_id and decision["has_evidence"]
                and (claim.evidence_set_id,claim.scope,claim.entity_ref) in evidence_claims
                and decision["reviewer_ref"].strip() and decision["decided_at"] is not None
                and decision["subject_hash"] == subject_hash(claim.scope, claim.payload)):
            result[key] = Review("APPROVED", f"mysql:review:{claim.review_id}", f"mysql:evidence_set:{claim.evidence_set_id}")
        else:
            result[key] = Review()
    return result


def _combined(*reviews):
    if any(review.status != "APPROVED" for review in reviews):
        return Review()
    return Review("APPROVED", ";".join(r.decision_ref for r in reviews), ";".join(r.evidence_ref for r in reviews))


def _catalog(connection, snapshot, recipe_ids):
    if snapshot is None:
        return Catalog(available=False)
    subjects = claims(snapshot)
    proofs = _proofs(connection, subjects)
    release = snapshot["release"][0]
    release_key = ("release", f"release:{release['id']}")
    if (proofs[release_key].status != "APPROVED" or release["approved_at"] is None
            or release["legacy_dataset_version"] != snapshot["legacy_version"]
            or release["manifest_hash"] != subject_hash("release", subjects[release_key].payload)):
        return Catalog(available=False)
    def proof(scope, ref):
        return proofs.get((scope, ref), Review())
    ingredients = {r["id"]: r for r in snapshot["ingredients"]}
    forms = {r["id"]: r for r in snapshot["forms"]}
    units = {r["id"]: r for r in snapshot["units"]}
    catalog_units = {r["code"]: Unit(r["code"], r["dimension"], r["definition"], proof("unit", f"unit:{r['id']}")) for r in units.values()}
    by_revision = {m["revision_id"]: m for m in snapshot["selected"]}
    revisions = {}
    for row in snapshot["revisions"]:
        # Do not select drafts or substitute an unpinned newer revision.
        if row["status"] != "APPROVED":
            continue
        member = by_revision[row["id"]]
        recipe_id = member_id(member)
        lines = []
        for line in snapshot["lines"]:
            if line["revision_id"] != row["id"]:
                continue
            ingredient, form, unit = ingredients.get(line["ingredient_id"]), forms.get(line["form_id"]), units.get(line["unit_id"])
            ref = f"line:{row['id']}:{line['line_no']}"
            review = _combined(proof("quantity", ref),
                proof("ingredient_identity", f"ingredient_identity:{line['ingredient_id']}"),
                proof("ingredient_form", f"ingredient_form:{line['form_id']}"))
            if not form or form["ingredient_id"] != line["ingredient_id"] or line["requirement"] not in {"required", "optional"}:
                review = Review()
            lines.append(IngredientLine(line["line_no"], line["ingredient_id"],
                ingredient["canonical_name"] if ingredient else None, form["form_code"] if form else None,
                line["amount_kind"], line["amount_min"], line["amount_max"], unit["code"] if unit else None,
                line["measurement_basis"], line["purpose"], review, line["scaling_mode"], proof("scaling", ref)))
        content_review = proof("recipe_content", f"revision:{row['id']}")
        if not row["title"].strip() or not row["instructions"].strip():
            content_review = Review()
        revisions[recipe_id] = Revision(recipe_id, row["id"], row["base_servings"], row["serving_basis"],
            tuple(lines), row["content_complete"] == 1, content_review, proof("servings", f"revision:{row['id']}"))
    policy = None
    if snapshot["policies"]:
        row = snapshot["policies"][0]
        review = proof("portion_policy", f"policy:{row['id']}")
        rules = snapshot["rules"]
        member_by_id = {m["recipe_id"]: m for m in snapshot["selected"]}
        valid = review.status == "APPROVED" and len(rules) == len(recipe_ids)
        allocations = {}
        for rule in rules:
            member = member_by_id.get(rule["recipe_id"])
            valid = (valid and member is not None and rule["revision_id"] == member["revision_id"]
                     and rule["subject_group"] == "person" and rule["input_definition"] == "per_person"
                     and proof("portion_allocation", f"rule:{row['id']}:{rule['rule_no']}").status == "APPROVED")
            if member:
                allocations[member_id(member)] = Allocation(rule["revision_id"], rule["serving_basis"], rule["equivalent_servings"])
        if valid and set(allocations) == set(recipe_ids):
            policy = PortionPolicy(row["policy_code"] + ":" + row["version"], allocations, review)
    return Catalog(revisions, catalog_units, policy)


def load_catalog(connection, recipe_ids):
    if connection.in_transaction:
        raise mysql.connector.InternalError("Calculation adapter requires an idle private connection")
    connection.start_transaction(isolation_level="REPEATABLE READ", consistent_snapshot=True, readonly=True)
    try:
        try:
            history = _query(connection, "SELECT version,checksum,execution_result,applied_at FROM v2_migration_history")
        except mysql.connector.ProgrammingError as exc:
            if exc.errno == 1146:  # Only an absent migration marker is a normal unavailable state.
                return Catalog(available=False)
            raise
        if not v2_schema.history_is_compatible(history):
            return Catalog(available=False)
        return _catalog(connection, read_snapshot(connection, recipe_ids), recipe_ids)
    finally:
        connection.rollback()  # Ends the read-only snapshot, including early unavailable returns.
