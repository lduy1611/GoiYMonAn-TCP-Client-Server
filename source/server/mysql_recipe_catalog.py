"""Read-only, release-pinned recipe publication. No approval or draft fallback.

recipe_publication reviews bind the entire displayed revision, line values,
identities and source references. Role/diet decisions additionally bind that
publication hash; a content-only approval never certifies a plant-only recipe.
"""
from dataclasses import dataclass, field
import json
import re

import mysql.connector

from source.common.catalog_ids import v2_public_id
from source.database import v2_schema
from source.server import mysql_calculation_catalog as proof
from source.server import vegetarian


@dataclass
class PublishedCatalog:
    version: str = ""
    details: dict = field(default_factory=dict)
    release_ingredient_ids: set = field(default_factory=set)
    roles: dict = field(default_factory=dict)
    plant_ids: set = field(default_factory=set)
    contexts: dict = field(default_factory=dict)
    hidden_ids: set = field(default_factory=set)
    deleted_ids: set = field(default_factory=set)


def publication_payload(snapshot, revision):
    """Exact subject to present for human publication review; never approves."""
    owner = next(m for m in snapshot["members"] if m["revision_id"] == revision["id"])
    lines = [r for r in snapshot["lines"] if r["revision_id"] == revision["id"]]
    ingredient_ids = {r["ingredient_id"] for r in lines}
    form_ids, unit_ids = {r["form_id"] for r in lines}, {r["unit_id"] for r in lines}
    # Include all recipe values except review pointers/status flags. Quantities
    # remain source text until their separate quantitative reviews pass.
    fields = (*proof.QUANTITY_FIELDS, "scaling_mode")
    bound_scopes = ("recipe_content", "recipe_publication", "role")
    evidence = evidence_payload(snapshot, revision, bound_scopes)
    sources = evidence["sources"]
    return {"public_id_version": 1,
        "recipe": {k:owner[k] for k in ("recipe_id","revision_id","legacy_recipe_id","variant_of_recipe_id","origin_kind","author_ref")},
        "revision": {k:revision[k] for k in ("id","recipe_id","revision_no","title","instructions","minutes",
                                             "base_servings","serving_basis","content_complete")},
        "lines": [{k:r[k] for k in fields} for r in lines],
        "ingredients": [{k:r[k] for k in ("id","legacy_ingredient_id","canonical_name","normalized_name")}
                        for r in snapshot["ingredients"] if r["id"] in ingredient_ids],
        "forms": [{k:r[k] for k in ("id","ingredient_id","form_code","description")}
                  for r in snapshot["forms"] if r["id"] in form_ids],
        "units": [{k:r[k] for k in ("id","code","dimension","symbol","definition")}
                  for r in snapshot["units"] if r["id"] in unit_ids],
        "sources": sources, "evidence": evidence}


def evidence_payload(snapshot, revision, scopes):
    rows = [r for r in snapshot["publication_evidence"]
            if r["evidence_set_id"] == revision["content_evidence_set_id"]
            and r["entity_ref"] == f"revision:{revision['id']}" and r["claim_scope"] in scopes]
    source_ids = {r["source_id"] for r in rows}
    sources = [{k:r[k] for k in ("id","source_kind","url","document_ref","title","author_or_publisher",
                                  "content_hash","usage_note")}
               | {"accessed_at": r["accessed_at"].isoformat(sep=" ", timespec="microseconds")
                    if hasattr(r["accessed_at"], "isoformat") else r["accessed_at"]}
               for r in snapshot["publication_sources"] if r["id"] in source_ids]
    evidence = [{k:r[k] for k in ("id","source_id","locator","excerpt_or_observation","claim_scope","entity_ref","content_hash")}
                for r in rows]
    return {"sources":sources,"evidence":evidence}


def observations(snapshot, revision, scope):
    values = []
    for row in snapshot["publication_evidence"]:
        if (row["evidence_set_id"] != revision["content_evidence_set_id"]
                or row["entity_ref"] != f"revision:{revision['id']}" or row["claim_scope"] != scope):
            continue
        try:
            value = json.loads(row["excerpt_or_observation"])
        except (ValueError, TypeError):
            return []
        if not isinstance(value, dict):
            return []
        if value not in values:
            values.append(value)
    return values


def publication_claims(snapshot):
    """Unlinked review subjects live in existing append-only decisions table.

    Latest decision per scope/entity wins (including rejection); there is no
    fallback to a previously approved hash after a later rejection/change.
    """
    result = {}
    for revision in snapshot["revisions"]:
        ref = f"revision:{revision['id']}"
        payload = publication_payload(snapshot, revision)
        digest = proof.subject_hash("recipe_publication", payload)
        proposals = {"recipe_publication":payload}
        for scope in ("role", "diet"):
            values = observations(snapshot, revision, scope)
            if len(values) == 1:
                proposals[scope] = {"revision_id":revision["id"], "publication_hash":digest, "observation":values[0],
                                    "evidence":evidence_payload(snapshot,revision,(scope,))}
        for scope, subject in proposals.items():
            decisions = [r for r in snapshot["publication_decisions"] if r["claim_scope"] == scope and r["entity_ref"] == ref]
            latest = max(decisions, key=lambda r:(r["decided_at"],r["id"])) if decisions else None
            result[(scope,ref)] = proof.Claim(scope,ref,revision["status"], latest["id"] if latest else None,
                                              revision["content_evidence_set_id"],subject)
    return result


def read_publication_snapshot(connection, *, release_id=None):
    # Explicit IDs prepare human review of an INACTIVE candidate release. The
    # runtime loader never passes one and can only read the active pointer.
    snapshot = proof.read_snapshot(connection, None, release_id=release_id)
    if snapshot is None:
        return None
    sets = sorted({r["content_evidence_set_id"] for r in snapshot["revisions"] if r["content_evidence_set_id"] is not None})
    evidence = proof._query(connection, f"""SELECT m.evidence_set_id,e.* FROM v2_evidence_set_members m
        JOIN v2_evidence e ON e.id=m.evidence_id WHERE m.evidence_set_id IN ({','.join('%s' for _ in sets)})
        ORDER BY m.evidence_set_id,e.id""", tuple(sets)) if sets else []
    refs = [f"revision:{r['id']}" for r in snapshot["revisions"]]
    decisions = proof._query(connection, f"""SELECT * FROM v2_review_decisions WHERE entity_ref IN ({','.join('%s' for _ in refs)})
        AND claim_scope IN ('recipe_publication','role','diet')""", tuple(refs)) if refs else []
    context_assertions, context_manifest, context_decisions = [], [], []
    revision_ids = [r["revision_id"] for r in snapshot["members"]]
    if revision_ids:
        marks = ",".join("%s" for _ in revision_ids)
        try:
            context_marker = proof._query(connection, "SELECT version FROM v2_migration_history WHERE version=%s AND execution_result='APPLIED'",
                                          ("002_recipe_context",))
            if not context_marker:
                snapshot.update(publication_evidence=evidence, publication_decisions=decisions,
                    publication_sources=proof._by_ids(connection,"v2_sources",[r["source_id"] for r in evidence]),
                    context_assertions=[],context_manifest=[],context_decisions=[])
                return snapshot
            regions = proof._query(connection, f"""SELECT a.id,a.revision_id,'region' AS context_group,
                t.code AS context_code,a.relation_kind,a.decision,a.evidence_set_id,a.review_decision_id
                FROM v2_recipe_regions a JOIN v2_regions t ON t.id=a.region_id
                WHERE a.revision_id IN ({marks}) ORDER BY a.id""", tuple(revision_ids))
            occasions = proof._query(connection, f"""SELECT a.id,a.revision_id,'occasion' AS context_group,
                t.code AS context_code,'applicable' AS relation_kind,a.decision,a.evidence_set_id,a.review_decision_id
                FROM v2_recipe_occasions a JOIN v2_occasions t ON t.id=a.occasion_id
                WHERE a.revision_id IN ({marks}) ORDER BY a.id""", tuple(revision_ids))
            context_assertions = regions + occasions
            context_manifest = proof._query(connection, "SELECT * FROM v2_release_context_manifests WHERE release_id=%s", (snapshot["release"][0]["id"],))
            refs = [f"context:{r['id']}" for r in context_assertions] + [f"release:{snapshot['release'][0]['id']}"]
            if refs:
                context_decisions = proof._query(connection, f"""SELECT * FROM v2_review_decisions
                    WHERE entity_ref IN ({','.join('%s' for _ in refs)})
                    AND claim_scope IN ('recipe_context','release_context_manifest') ORDER BY decided_at,id""", tuple(refs))
        except mysql.connector.ProgrammingError as exc:
            if exc.errno != 1146:  # Missing migration 002 means no supported context filters.
                raise
            context_assertions, context_manifest, context_decisions = [], [], []
    snapshot.update(publication_evidence=evidence, publication_decisions=decisions,
        publication_sources=proof._by_ids(connection,"v2_sources",[r["source_id"] for r in evidence]))
    snapshot.update(context_assertions=context_assertions, context_manifest=context_manifest,
                    context_decisions=context_decisions)
    return snapshot


def _context_assertion_payload(row):
    return {key:row[key] for key in ("id","revision_id","context_group","context_code","relation_kind","decision","evidence_set_id")}


def context_claims(snapshot):
    claims = {}
    for row in snapshot.get("context_assertions", []):
        ref = f"context:{row['id']}"
        claims[("recipe_context",ref)] = proof.Claim("recipe_context",ref,row["decision"],
            row["review_decision_id"],row["evidence_set_id"],_context_assertion_payload(row))
    release_id = snapshot["release"][0]["id"]
    rows = sorted((_context_assertion_payload(r) for r in snapshot.get("context_assertions", [])),
                  key=lambda r:(r["context_group"],r["revision_id"],r["id"]))
    payload = {"release_id":release_id,"assertions":rows}
    expected_hash = proof.subject_hash("release_context_manifest",payload)
    for manifest in snapshot.get("context_manifest", []):
        ref = f"release:{release_id}"
        claims[("release_context_manifest",ref)] = proof.Claim("release_context_manifest",ref,
            manifest["status"],manifest["review_decision_id"],manifest["evidence_set_id"],payload)
        if manifest["manifest_hash"] != expected_hash:
            claims[("release_context_manifest",ref)] = proof.Claim("release_context_manifest",ref,
                "INVALID",manifest["review_decision_id"],manifest["evidence_set_id"],payload)
    return claims


def latest_context_reviews(snapshot):
    latest = {}
    for row in snapshot.get("context_decisions", []):
        key = (row["claim_scope"],row["entity_ref"])
        latest[key] = row
    return latest


def _plant_only(snapshot, revision, lines, identities):
    values = observations(snapshot,revision,"diet")
    if len(values) != 1:
        return False
    row = values[0]
    if (row.get("profile") != vegetarian.PROFILE or row.get("unresolved") != []
            or any(row.get(k) is not True for k in ("components_complete","instructions_complete","optional_components_included"))):
        return False
    covered = row.get("ingredient_evidence")
    if (not isinstance(covered,list) or len(covered) != len(lines)
            or any(not isinstance(r,dict) or type(r.get("line_no")) is not int for r in covered)
            or len({r["line_no"] for r in covered}) != len(lines)):
        return False
    by_line = {r["line_no"]:r for r in covered}
    for line in lines:
        evidence = by_line.get(line["line_no"],{})
        if (evidence.get("ingredient_id") != line["ingredient_id"] or evidence.get("classification") != "plant_or_mineral"
                or not isinstance(evidence.get("evidence_ref"),str) or not evidence["evidence_ref"].strip()):
            return False
    extras = row.get("instruction_only_components")
    if not isinstance(extras,list) or any(not isinstance(r,dict) or r.get("classification") != "plant_or_mineral"
            or not isinstance(r.get("name"),str) or not r["name"].strip()
            or not isinstance(r.get("evidence_ref"),str) or not r["evidence_ref"].strip() for r in extras):
        return False
    # A reviewed plant product must explicitly say which animal-free variant it
    # is. This is a veto, not an automatic classifier or an approval substitute.
    text = " ".join([revision["instructions"], *[identities[r["ingredient_id"]]["canonical_name"] for r in lines],
                     *[r["name"] for r in extras]])
    text = re.sub(r"\bvegan\s+(?:fish sauce|butter|egg|milk|chicken|shrimp)\b|\b(?:soy|coconut|oat|almond) milk\b",
                  "plant product", vegetarian.normalized(text), flags=re.IGNORECASE)
    return vegetarian.ANIMAL_PATTERN.search(text) is None and not re.search(r"\b(?:oyster sauce|honey|gelatine?)\b",text,re.I)


def _published(connection,snapshot):
    catalog = PublishedCatalog()
    if snapshot is None:
        return catalog
    subjects = proof.claims(snapshot)
    subjects.update(publication_claims(snapshot))
    subjects.update(context_claims(snapshot))
    proofs = proof._proofs(connection,subjects)
    release = snapshot["release"][0]
    release_key = ("release",f"release:{release['id']}")
    if (proofs[release_key].status != "APPROVED" or release["approved_at"] is None
            or release["legacy_dataset_version"] != snapshot["legacy_version"]
            or release["manifest_hash"] != proof.subject_hash("release",subjects[release_key].payload)):
        return catalog
    catalog.version = "v2:" + release["manifest_hash"][:16]
    context_review_rows = latest_context_reviews(snapshot)
    context_manifest_claim = subjects.get(("release_context_manifest",f"release:{release['id']}"))
    context_manifest_review = proofs.get(("release_context_manifest",f"release:{release['id']}"),proof.Review())
    latest_manifest_review = context_review_rows.get(("release_context_manifest",f"release:{release['id']}"))
    context_rows = snapshot.get("context_assertions", [])
    # A release context snapshot is all-or-nothing. Stale, unreviewed, draft,
    # or post-review edits disable the filter instead of exposing partial labels.
    manifest_valid = (bool(context_rows) and context_manifest_claim is not None
        and context_manifest_review.status == "APPROVED" and latest_manifest_review is not None
        and latest_manifest_review["decision"] == "APPROVED"
        and latest_manifest_review["id"] == snapshot["context_manifest"][0]["review_decision_id"])
    approved = []
    if manifest_valid:
        for row in context_rows:
            ref = f"context:{row['id']}"
            latest = context_review_rows.get(("recipe_context",ref))
            if (row["decision"] != "APPROVED" or latest is None or latest["decision"] != "APPROVED"
                    or latest["id"] != row["review_decision_id"]
                    or proofs.get(("recipe_context",ref),proof.Review()).status != "APPROVED"):
                manifest_valid = False
                break
            approved.append(row)
    if manifest_valid:
        member_by_revision = {r["revision_id"]:r for r in snapshot["members"]}
        for row in approved:
            member = member_by_revision.get(row["revision_id"])
            if not member:
                continue
            rid = v2_public_id(member["recipe_id"])
            if row["context_group"] == "region" and row["relation_kind"] == "suitable_for_meal":
                catalog.contexts.setdefault("region",{}).setdefault(row["context_code"],set()).add(rid)
            elif row["context_group"] == "occasion" and row["relation_kind"] == "applicable":
                catalog.contexts.setdefault("occasion",{}).setdefault(row["context_code"],set()).add(rid)
        catalog.contexts = {group:{code:frozenset(ids) for code,ids in values.items()}
                            for group,values in catalog.contexts.items()}
    identities = {r["id"]:r for r in snapshot["ingredients"]}
    from source.server.ingredient_catalog import business_id, normalized_key
    from source.server.legacy_ingredient_overlays import display_name,read_overrides
    try:
        legacy_base={int(row["id"]):row["name"] for row in proof._query(connection,"SELECT id,name FROM ingredients")}
        legacy_overrides=read_overrides(connection,legacy_base)
        legacy_names={iid:display_name(name,legacy_overrides.get(iid)) for iid,name in legacy_base.items()}
        legacy_name_ids={}
        for iid,name in legacy_names.items():
            legacy_name_ids[normalized_key(name)]=iid
            legacy_name_ids[normalized_key(legacy_base[iid])]=iid
    except mysql.connector.Error as exc:
        if exc.errno!=1146:raise
        legacy_names={};legacy_name_ids={}
    sources = {r["id"]:r for r in snapshot["publication_sources"]}
    members = {r["revision_id"]:r for r in snapshot["members"]}
    for revision in snapshot["revisions"]:
        owner = members[revision["id"]]
        # Approved legacy variants continue to serve portions under the existing
        # adapter. Never replace or duplicate the 50 original recipe responses.
        if owner["legacy_recipe_id"] is not None:
            continue
        ref = f"revision:{revision['id']}"
        required = ("recipe_content","recipe_publication","role")
        if (revision["content_complete"] != 1 or not revision["title"].strip() or not revision["instructions"].strip()
                or revision["minutes"] is None or not 1 <= revision["minutes"] <= 240
                or any(proofs.get((scope,ref),proof.Review()).status != "APPROVED" for scope in required)):
            continue
        role_values = observations(snapshot,revision,"role")
        role = role_values[0].get("proposal") if len(role_values)==1 else None
        lines = [r for r in snapshot["lines"] if r["revision_id"] == revision["id"]]
        if role not in ("main","vegetable","soup") or not lines or len(lines)>50:
            continue
        if any(r["ingredient_id"] not in identities or r["requirement"] not in ("required","optional")
               or proofs.get(("ingredient_identity",f"ingredient_identity:{r['ingredient_id']}"),proof.Review()).status != "APPROVED"
               or not identities[r["ingredient_id"]]["canonical_name"].strip() for r in lines):
            continue
        try:
            public_id = v2_public_id(owner["recipe_id"])
            ingredients = [{"id":business_id(i["id"],i["legacy_ingredient_id"],i["canonical_name"],legacy_name_ids),
                "name":(legacy_names.get(int(i["legacy_ingredient_id"]),i["canonical_name"])
                    if i["legacy_ingredient_id"] is not None else
                    legacy_names.get(legacy_name_ids.get(normalized_key(i["canonical_name"])),i["canonical_name"])),
                "quantity":r["quantity_raw"], "is_required":r["requirement"]=="required"}
                for r in lines for i in [identities[r["ingredient_id"]]]]
        except ValueError:
            continue
        # Source revisions can repeat an ingredient in multiple stages. The
        # legacy detail/shopping contract has one use per recipe/ingredient;
        # retain the raw observations as text, without summing unreviewed units.
        grouped = {}
        for ingredient in ingredients:
            entry = grouped.setdefault(ingredient["id"], {"id":ingredient["id"],"name":ingredient["name"],
                                                         "parts":[],"is_required":False})
            raw = ingredient["quantity"] or "chưa ghi định lượng"
            if not ingredient["is_required"]:
                raw += " (tùy chọn)"
            entry["parts"].append(raw)
            entry["is_required"] |= ingredient["is_required"]
        ingredients = [{"id":r["id"],"name":r["name"],"quantity":"; ".join(r["parts"]),"is_required":r["is_required"]}
                       for r in grouped.values()]
        if any(len(r["quantity"])>255 for r in ingredients):
            continue
        content_sources = [sources[e["source_id"]] for e in snapshot["publication_evidence"]
            if e["evidence_set_id"] == revision["content_evidence_set_id"] and e["entity_ref"] == ref
            and e["claim_scope"] == "recipe_content" and e["source_id"] in sources
            and sources[e["source_id"]]["verification_status"] == "APPROVED"]
        if not content_sources:
            continue
        catalog.details[public_id] = {"id":public_id,"title":revision["title"],"instructions":revision["instructions"],
            "minutes":revision["minutes"],"source_url":content_sources[0]["url"],"ingredients":ingredients}
        catalog.release_ingredient_ids.update(item["id"] for item in ingredients)
        catalog.roles[public_id] = role
        if proofs.get(("diet",ref),proof.Review()).status == "APPROVED" and _plant_only(snapshot,revision,lines,identities):
            catalog.plant_ids.add(public_id)
    catalog.version = "v2:" + proof.subject_hash("recipe_catalog", {
        "release_manifest":release["manifest_hash"], "roles":sorted(catalog.roles.items()),
        "plant_ids":sorted(catalog.plant_ids),
        "contexts":{g:{c:sorted(ids) for c,ids in values.items()} for g,values in catalog.contexts.items()}})[:16]
    return catalog


def load_catalog(connection):
    if connection.in_transaction:
        raise mysql.connector.InternalError("Recipe publication requires an idle private connection")
    connection.start_transaction(isolation_level="REPEATABLE READ",readonly=True,consistent_snapshot=True)
    try:
        try:
            history = proof._query(connection,"SELECT version,checksum,execution_result,applied_at FROM v2_migration_history")
        except mysql.connector.ProgrammingError as exc:
            if exc.errno == 1146:
                return PublishedCatalog()
            raise
        if not v2_schema.history_is_compatible(history):
            return PublishedCatalog()
        catalog=_published(connection,read_publication_snapshot(connection))
        markers={row["version"]:row for row in history}
        from source.database import v2_admin_recipe_catalog_schema
        marker=markers.get(v2_admin_recipe_catalog_schema.VERSION)
        if marker and marker["execution_result"]=="APPLIED":
            _load_admin_catalog(connection,catalog)
        return catalog
    finally:
        connection.rollback()


def _load_admin_catalog(connection,catalog):
    """Load explicit Admin saves; old drafts without this marker stay private."""
    from source.common.catalog_ids import v2_public_id
    from source.server.ingredient_catalog import business_id,normalized_key
    from source.server.legacy_ingredient_overlays import display_name,read_overrides
    rows=proof._query(connection,"""SELECT legacy_recipe_id,v2_recipe_id,revision_id,role_code,
        direct_publication,is_visible,is_deleted FROM v2_admin_recipe_catalog_overrides""")
    for row in rows:
        legacy_id=row["legacy_recipe_id"];v2_id=row["v2_recipe_id"];revision_id=row["revision_id"]
        role=row["role_code"];direct=row["direct_publication"];visible=row["is_visible"];deleted=row["is_deleted"]
        public_id=int(legacy_id) if legacy_id is not None else v2_public_id(int(v2_id))
        if deleted:catalog.deleted_ids.add(public_id)
        if deleted or not visible:catalog.hidden_ids.add(public_id)
    direct_ids=[int(row["revision_id"]) for row in rows if row["v2_recipe_id"] is not None
                and row["direct_publication"] and row["is_visible"] and not row["is_deleted"]]
    if not direct_ids:
        return
    marks=",".join("%s" for _ in direct_ids)
    result=proof._query(connection,f"""SELECT o.v2_recipe_id,o.revision_id,o.role_code,r.title,r.description,
        r.instructions,r.minutes,l.line_no,l.ingredient_id,l.quantity_raw,l.requirement,
        i.legacy_ingredient_id,i.canonical_name,i.id
        FROM v2_admin_recipe_catalog_overrides o
        JOIN v2_recipe_revisions r ON r.id=o.revision_id AND r.recipe_id=o.v2_recipe_id
        JOIN v2_recipe_ingredient_lines l ON l.revision_id=r.id
        JOIN v2_ingredients i ON i.id=l.ingredient_id
        WHERE o.direct_publication=1 AND o.is_visible=1 AND o.is_deleted=0
          AND r.status='DRAFT' AND r.id IN ({marks})
        ORDER BY r.id,l.line_no""",tuple(direct_ids))
    legacy_base={int(row["id"]):row["name"] for row in proof._query(connection,"SELECT id,name FROM ingredients")}
    overrides=read_overrides(connection,legacy_base)
    names={iid:display_name(name,overrides.get(iid)) for iid,name in legacy_base.items()}
    legacy_name_ids={normalized_key(name):iid for iid,name in names.items()}
    details={}
    for row in result:
        recipe_id=row["v2_recipe_id"];revision_id=row["revision_id"];role=row["role_code"]
        title=row["title"];description=row["description"];instructions=row["instructions"];minutes=row["minutes"]
        line_no=row["line_no"];ingredient_id=row["ingredient_id"];quantity=row["quantity_raw"]
        requirement=row["requirement"];legacy_id=row["legacy_ingredient_id"]
        canonical_name=row["canonical_name"];storage_id=row["id"]
        public_id=v2_public_id(int(recipe_id))
        detail=details.setdefault(public_id,{"id":public_id,"title":title,"description":description or "",
            "instructions":instructions,"minutes":int(minutes),"source_url":"","ingredients":[],"role":role})
        try:
            ingredient_business_id=business_id(int(storage_id),legacy_id,canonical_name,legacy_name_ids)
        except ValueError:
            continue
        name=names.get(int(legacy_id),canonical_name) if legacy_id is not None else names.get(legacy_name_ids.get(normalized_key(canonical_name)),canonical_name)
        detail["ingredients"].append({"id":ingredient_business_id,"name":name,"quantity":quantity,
            "is_required":requirement=="required"})
    for public_id,detail in details.items():
        if detail["ingredients"] and detail["role"] in {"main","vegetable","soup"}:
            catalog.details[public_id]=detail
            catalog.roles[public_id]=detail.pop("role")
    import hashlib
    catalog.version += ":admin:"+hashlib.sha256(json.dumps({"details":catalog.details,"roles":sorted(catalog.roles.items()),
        "hidden":sorted(catalog.hidden_ids),"deleted":sorted(catalog.deleted_ids)},ensure_ascii=False,default=str,sort_keys=True).encode()).hexdigest()[:12]
