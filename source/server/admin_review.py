"""Admin review and release writes for v2 recipes.

All writes use the dedicated draft writer connection. Decisions are append-only;
publication eligibility is recalculated from the same hashes used by the public
catalog before the active release pointer can move.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
import re

from source.server import mysql_calculation_catalog as portions
from source.server import mysql_recipe_catalog as publication


class ReviewConflict(RuntimeError):
    pass


class ReviewBlocked(RuntimeError):
    pass


ROLES = {"main", "vegetable", "soup"}
ID_TABLES = {"v2_sources", "v2_evidence_sets", "v2_evidence", "v2_review_decisions", "v2_data_releases"}


def validate_submission(payload):
    allowed = {"revision_id", "source_kind", "source_title", "source_url", "publisher",
               "usage_note", "accessed_on", "content_locator", "content_evidence",
               "publication_locator", "publication_evidence", "role", "role_locator", "role_evidence"}
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise ValueError("invalid review submission fields")
    revision_id = payload["revision_id"]
    if type(revision_id) is not int or not 1 <= revision_id < 2**64:
        raise ValueError("invalid revision ID")
    for key, maximum in (("source_kind",40),("source_title",255),("source_url",1000),
                         ("publisher",255),("usage_note",2000),("content_locator",500),
                         ("content_evidence",5000),("publication_locator",500),
                         ("publication_evidence",5000),("role_locator",500),("role_evidence",5000)):
        value = payload[key]
        optional = key in {"publisher", "usage_note"}
        if not isinstance(value,str) or (not optional and len(value.strip()) == 0) or len(value) > maximum:
            raise ValueError("invalid evidence fields")
    if payload["role"] not in ROLES:
        raise ValueError("invalid recipe role")
    try:
        accessed_on=date.fromisoformat(payload["accessed_on"])
        if accessed_on>date.today(): raise ValueError("source access date cannot be in the future")
    except (TypeError,ValueError): raise ValueError("invalid source access date") from None
    url = payload["source_url"].strip()
    if not re.match(r"^https?://[^\s]+$",url,re.IGNORECASE):
        raise ValueError("source URL must be HTTP or HTTPS")
    return {**payload, **{key:value.strip() for key,value in payload.items() if isinstance(value,str)}}


def validate_source_decision(payload):
    if (not isinstance(payload,dict) or set(payload)!={"source_id","evidence_set_id","decision","rationale"}
            or type(payload["source_id"]) is not int or not 1<=payload["source_id"]<2**64
            or type(payload["evidence_set_id"]) is not int or not 1<=payload["evidence_set_id"]<2**64
            or payload["decision"] not in {"APPROVED","REJECTED"}
            or not isinstance(payload["rationale"],str) or not 10<=len(payload["rationale"].strip())<=4000):
        raise ValueError("invalid source review fields")
    return {**payload,"rationale":payload["rationale"].strip()}


def validate_revision_action(payload, *, release=False, unpublish=False):
    if not isinstance(payload,dict): raise ValueError("invalid Admin action")
    if release:
        expected={"release_id","rationale"}
        key="release_id"
    elif unpublish:
        expected={"recipe_id","rationale"}
        key="recipe_id"
    else:
        expected={"revision_id","rationale"}
        key="revision_id"
    value=payload.get(key)
    if (set(payload)!=expected or type(value) is not int or not 1<=value<2**64
            or not isinstance(payload.get("rationale"),str)
            or not 10<=len(payload["rationale"].strip())<=4000):
        raise ValueError("invalid review action fields")
    return {**payload,"rationale":payload["rationale"].strip()}


def _next_id(cursor, table):
    if table not in ID_TABLES:
        raise ValueError("unsupported v2 identity table")
    cursor.execute(f"SELECT COALESCE(MAX(id),0)+1 FROM {table}")
    row=cursor.fetchone()
    value = int(next(iter(row.values())) if isinstance(row,dict) else row[0])
    if not 1 <= value < 2**64:
        raise ReviewConflict("v2 identity space is exhausted")
    return value


def _evidence_set(cursor, description):
    sid = _next_id(cursor,"v2_evidence_sets")
    cursor.execute("INSERT INTO v2_evidence_sets(id,description) VALUES(%s,%s)",(sid,description[:255]))
    return sid


def _evidence(cursor, set_id, source_id, scope, entity_ref, observation, locator):
    evidence_id = _next_id(cursor,"v2_evidence")
    raw = observation if isinstance(observation,str) else json.dumps(observation,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    cursor.execute("""INSERT INTO v2_evidence(id,source_id,locator,excerpt_or_observation,claim_scope,
        entity_ref,captured_at,content_hash) VALUES(%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6),%s)""",
        (evidence_id,source_id,locator[:500],raw,scope,entity_ref,digest))
    cursor.execute("INSERT INTO v2_evidence_set_members(evidence_set_id,evidence_id) VALUES(%s,%s)",(set_id,evidence_id))


def _decision(cursor, decision, reviewer, rationale, scope, entity_ref, subject_hash, evidence_set_id):
    decision_id = _next_id(cursor,"v2_review_decisions")
    cursor.execute("""INSERT INTO v2_review_decisions(id,decision,reviewer_ref,decided_at,rationale,
        claim_scope,entity_ref,subject_hash,evidence_set_id)
        VALUES(%s,%s,%s,UTC_TIMESTAMP(6),%s,%s,%s,%s,%s)""",
        (decision_id,decision,reviewer[:255],rationale[:4000],scope,entity_ref,subject_hash,evidence_set_id))
    return decision_id


def submit(connection, payload, reviewer=None):
    """Attach source evidence to an editable draft and submit it for review."""
    cursor=connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id,recipe_id,status,content_evidence_set_id FROM v2_recipe_revisions WHERE id=%s FOR UPDATE",
                       (payload["revision_id"],))
        revision=cursor.fetchone()
        if not revision or revision["status"]!="DRAFT" or revision["content_evidence_set_id"] is not None:
            raise ReviewConflict("only a DRAFT without an evidence dossier can be submitted")
        cursor.execute("SELECT line_no,ingredient_id,requirement FROM v2_recipe_ingredient_lines WHERE revision_id=%s ORDER BY line_no",
                       (payload["revision_id"],))
        lines=cursor.fetchall()
        if not lines or any(not row["ingredient_id"] or row["requirement"] not in {"required","optional"} for row in lines):
            raise ReviewBlocked("all ingredient rows need a valid v2 ingredient and required/optional classification")
        cursor.execute("SELECT id,title,instructions,minutes FROM v2_recipe_revisions WHERE id=%s",(payload["revision_id"],))
        content=cursor.fetchone()
        if not content["title"].strip() or not content["instructions"].strip() or not content["minutes"]:
            raise ReviewBlocked("title, instructions and cooking time are required before review")
        cursor.execute("SELECT COUNT(*) AS n FROM v2_ingredients WHERE id IN (%s)" % ",".join(["%s"]*len({r["ingredient_id"] for r in lines})),
                       tuple(sorted({r["ingredient_id"] for r in lines})))
        if int(cursor.fetchone()["n"]) != len({r["ingredient_id"] for r in lines}):
            raise ReviewBlocked("a recipe ingredient ID does not exist in v2")
        set_id=_evidence_set(cursor,f"Admin review dossier for revision {payload['revision_id']}")
        source_id=_next_id(cursor,"v2_sources")
        accessed_at=datetime.combine(date.fromisoformat(payload["accessed_on"]),datetime.min.time(),tzinfo=timezone.utc).replace(tzinfo=None)
        cursor.execute("""INSERT INTO v2_sources(id,source_kind,title,url,author_or_publisher,accessed_at,
            usage_note,verification_status) VALUES(%s,%s,%s,%s,%s,%s,%s,'NEEDS_VERIFICATION')""",
            (source_id,payload["source_kind"],payload["source_title"],payload["source_url"],
             payload["publisher"] or None,accessed_at,payload["usage_note"] or None))
        entity=f"revision:{payload['revision_id']}"
        _evidence(cursor,set_id,source_id,"recipe_content",entity,payload["content_evidence"],payload["content_locator"])
        _evidence(cursor,set_id,source_id,"recipe_publication",entity,payload["publication_evidence"],payload["publication_locator"])
        _evidence(cursor,set_id,source_id,"role",entity,{"proposal":payload["role"],"source_excerpt":payload["role_evidence"]},payload["role_locator"])
        cursor.execute("UPDATE v2_recipe_revisions SET content_complete=1,status='NEEDS_VERIFICATION',content_evidence_set_id=%s WHERE id=%s AND status='DRAFT'",
                       (set_id,payload["revision_id"]))
        if cursor.rowcount != 1:
            raise ReviewConflict("revision changed while being submitted")
        return {"revision_id":payload["revision_id"],"status":"NEEDS_VERIFICATION","source_id":source_id,"evidence_set_id":set_id}
    finally:
        cursor.close()


def decide_source(connection, payload, reviewer):
    cursor=connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM v2_sources WHERE id=%s FOR UPDATE",(payload["source_id"],))
        source=cursor.fetchone()
        if not source:
            raise ReviewConflict("source does not exist")
        cursor.execute("""SELECT COUNT(*) AS n FROM v2_evidence e JOIN v2_evidence_set_members m ON m.evidence_id=e.id
            WHERE m.evidence_set_id=%s AND e.source_id=%s AND e.claim_scope IN ('recipe_content','recipe_publication','role')
            AND CHAR_LENGTH(TRIM(e.locator))>0 AND CHAR_LENGTH(TRIM(e.excerpt_or_observation))>0""",
            (payload["evidence_set_id"],payload["source_id"]))
        if int(cursor.fetchone()["n"]) < 3:
            raise ReviewBlocked("the source must have content, publication and role evidence before verification")
        digest=portions.subject_hash("source_verification",{key:source[key] for key in
            ("id","source_kind","title","url","document_ref","author_or_publisher","accessed_at","content_hash","usage_note")})
        cursor.execute("UPDATE v2_sources SET verification_status=%s WHERE id=%s",(payload["decision"],payload["source_id"]))
        _evidence(cursor,payload["evidence_set_id"],payload["source_id"],"source_verification",
                  f"source:{payload['source_id']}",{"decision":payload["decision"],"rationale":payload["rationale"]},
                  "Admin source verification decision")
        _decision(cursor,payload["decision"],reviewer,payload["rationale"],"source_verification",
                  f"source:{payload['source_id']}",digest,payload["evidence_set_id"])
        return {"source_id":payload["source_id"],"verification_status":payload["decision"]}
    finally:
        cursor.close()


def _review_snapshot(connection, revision_id):
    """Build a temporary candidate release snapshot for a not-yet-published revision."""
    cursor=connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT recipe_id FROM v2_recipe_revisions WHERE id=%s",(revision_id,))
        row=cursor.fetchone()
        if not row:
            raise ReviewConflict("revision does not exist")
        cursor.execute("SELECT id,legacy_dataset_version FROM v2_data_releases WHERE status='PUBLISHED' ORDER BY id DESC LIMIT 1")
        active=cursor.fetchone()
        if active:
            release_id=int(active["id"])
            cursor.execute("SELECT active_release_id FROM v2_calculation_settings WHERE id=1")
            pointer=cursor.fetchone()
            if not pointer or pointer["active_release_id"] != release_id:
                raise ReviewConflict("latest published release is not the active release")
            cursor.execute("SELECT recipe_id,revision_id FROM v2_release_recipes WHERE release_id=%s",(release_id,))
            members=cursor.fetchall()
        else:
            cursor.execute("SELECT value FROM metadata WHERE `key`='dataset_version'")
            version=cursor.fetchone()
            if not version:raise ReviewBlocked("legacy dataset version is unavailable")
            return None
        return active,members
    finally:cursor.close()


def _start_candidate(connection, revision_id):
    cursor=connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT active_release_id FROM v2_calculation_settings WHERE id=1 FOR UPDATE")
        pointer=cursor.fetchone(); active_id=pointer["active_release_id"] if pointer else None
        cursor.execute("SELECT recipe_id FROM v2_recipe_revisions WHERE id=%s",(revision_id,)); target=cursor.fetchone()
        if not target: raise ReviewConflict("revision does not exist")
        recipe_id=int(target["recipe_id"])
        members=[]
        if active_id is not None:
            cursor.execute("SELECT recipe_id,revision_id FROM v2_release_recipes WHERE release_id=%s ORDER BY recipe_id FOR UPDATE",(active_id,))
            members=cursor.fetchall()
            if any(int(r["recipe_id"])==recipe_id for r in members):
                raise ReviewConflict("recipe is already present in the active release")
        cursor.execute("SELECT value FROM metadata WHERE `key`='dataset_version'")
        version=cursor.fetchone()
        if not version: raise ReviewBlocked("legacy dataset version is unavailable")
        release_id=_next_id(cursor,"v2_data_releases")
        code=f"admin-review-{revision_id}-{active_id or 0}-{release_id}"
        cursor.execute("INSERT INTO v2_data_releases(id,code,legacy_dataset_version,status) VALUES(%s,%s,%s,'DRAFT')",
                       (release_id,code,version["value"]))
        for member in members:
            cursor.execute("INSERT INTO v2_release_recipes(release_id,recipe_id,revision_id) VALUES(%s,%s,%s)",
                           (release_id,member["recipe_id"],member["revision_id"]))
        cursor.execute("INSERT INTO v2_release_recipes(release_id,recipe_id,revision_id) VALUES(%s,%s,%s)",
                       (release_id,recipe_id,revision_id))
        return release_id, active_id, members, recipe_id
    finally: cursor.close()


def _active_catalog(connection):
    snapshot=publication.read_publication_snapshot(connection)
    return publication._published(connection,snapshot)


def submit_source_decision(connection, payload, reviewer):
    cursor=connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM v2_sources WHERE id=%s FOR UPDATE",(payload["source_id"],))
        source=cursor.fetchone()
        if not source: raise ReviewConflict("source does not exist")
        cursor.execute("""SELECT COUNT(DISTINCT e.claim_scope) AS n FROM v2_evidence e
            JOIN v2_evidence_set_members m ON m.evidence_id=e.id
            WHERE m.evidence_set_id=%s AND e.source_id=%s AND e.claim_scope IN ('recipe_content','recipe_publication','role')
            AND CHAR_LENGTH(TRIM(e.locator))>0 AND CHAR_LENGTH(TRIM(e.excerpt_or_observation))>0""",
                       (payload["evidence_set_id"],payload["source_id"]))
        if int(cursor.fetchone()["n"]) < 3: raise ReviewBlocked("content, publication and role evidence are required")
        cursor.execute("""SELECT COUNT(*) AS n FROM v2_recipe_revisions r JOIN v2_evidence_set_members m
            ON m.evidence_set_id=r.content_evidence_set_id JOIN v2_evidence e ON e.id=m.evidence_id
            WHERE r.content_evidence_set_id=%s AND r.status='NEEDS_VERIFICATION' AND e.source_id=%s""",
                       (payload["evidence_set_id"],payload["source_id"]))
        if int(cursor.fetchone()["n"]) < 3:
            raise ReviewBlocked("source dossier is not attached to a submitted recipe")
        digest=portions.subject_hash("source_verification",portions.source_subject(source))
        cursor.execute("UPDATE v2_sources SET verification_status=%s WHERE id=%s",(payload["decision"],payload["source_id"]))
        _evidence(cursor,payload["evidence_set_id"],payload["source_id"],"source_verification",
                  f"source:{payload['source_id']}",{"decision":payload["decision"],"rationale":payload["rationale"]},
                  "Admin source verification decision")
        _decision(cursor,payload["decision"],reviewer,payload["rationale"],"source_verification",
                  f"source:{payload['source_id']}",digest,payload["evidence_set_id"])
        return {"source_id":payload["source_id"],"verification_status":payload["decision"]}
    finally: cursor.close()


def approve_recipe(connection, payload, reviewer):
    """Approve publication content and role; never changes serving/quantity reviews."""
    cursor=connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM v2_recipe_revisions WHERE id=%s FOR UPDATE",(payload["revision_id"],))
        revision=cursor.fetchone()
        if not revision or revision["status"]!="NEEDS_VERIFICATION" or not revision["content_evidence_set_id"]:
            raise ReviewConflict("only a submitted NEEDS_VERIFICATION revision can be approved")
        set_id=revision["content_evidence_set_id"]
        cursor.execute("""SELECT s.verification_status,e.claim_scope,e.entity_ref,e.excerpt_or_observation
            FROM v2_evidence_set_members m JOIN v2_evidence e ON e.id=m.evidence_id
            JOIN v2_sources s ON s.id=e.source_id WHERE m.evidence_set_id=%s AND e.entity_ref=%s""",
            (set_id,f"revision:{payload['revision_id']}"))
        evidence=cursor.fetchall()
        scopes={r["claim_scope"] for r in evidence if r["verification_status"]=="APPROVED"}
        if not {"recipe_content","recipe_publication","role"}.issubset(scopes):
            raise ReviewBlocked("source verification must approve content, publication and role evidence first")
        role_values=[]
        for row in evidence:
            if row["claim_scope"]=="role":
                try: role_values.append(json.loads(row["excerpt_or_observation"]))
                except (TypeError,ValueError): pass
        if len(role_values)!=1 or role_values[0].get("proposal") not in ROLES or not role_values[0].get("source_excerpt"):
            raise ReviewBlocked("exactly one evidenced role proposal is required")
        cursor.execute("""SELECT l.ingredient_id,l.requirement,i.identity_status FROM v2_recipe_ingredient_lines l
            LEFT JOIN v2_ingredients i ON i.id=l.ingredient_id WHERE l.revision_id=%s ORDER BY l.line_no""",(payload["revision_id"],))
        lines=cursor.fetchall()
        if not lines or any(r["ingredient_id"] is None or r["requirement"] not in {"required","optional"}
                            or r["identity_status"]!="APPROVED" for r in lines):
            raise ReviewBlocked("all ingredient identities and required/optional classifications must be approved")
        cursor.execute("UPDATE v2_recipe_revisions SET status='APPROVED' WHERE id=%s AND status='NEEDS_VERIFICATION'",
                       (payload["revision_id"],))
        if cursor.rowcount!=1: raise ReviewConflict("revision changed during approval")
        release_id, active_id, members, recipe_id = _start_candidate(connection,payload["revision_id"])
        snapshot=publication.read_publication_snapshot(connection,release_id=release_id)
        if snapshot is None: raise ReviewBlocked("candidate release could not be loaded")
        subjects=portions.claims(snapshot); subjects.update(publication.publication_claims(snapshot))
        for scope in ("recipe_content","recipe_publication","role"):
            ref=f"revision:{payload['revision_id']}"; claim=subjects.get((scope,ref))
            if claim is None: raise ReviewBlocked(f"missing {scope} claim")
            decision=_decision(cursor,"APPROVED",reviewer,payload["rationale"],scope,ref,
                               portions.subject_hash(scope,claim.payload),set_id)
            if scope=="recipe_content": cursor.execute("UPDATE v2_recipe_revisions SET content_review_id=%s WHERE id=%s",(decision,payload["revision_id"]))
        return {"revision_id":payload["revision_id"],"status":"APPROVED","release_id":release_id,
                "active_release_id":active_id,"quantity_status":"UNCHANGED"}
    finally: cursor.close()


def reject_recipe(connection, payload, reviewer):
    cursor=connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id,status,content_evidence_set_id FROM v2_recipe_revisions WHERE id=%s FOR UPDATE",(payload["revision_id"],))
        revision=cursor.fetchone()
        if not revision or revision["status"]!="NEEDS_VERIFICATION" or not revision["content_evidence_set_id"]:
            raise ReviewConflict("only a submitted revision can be rejected")
        release_id,_,_,_=_start_candidate(connection,payload["revision_id"])
        snapshot=publication.read_publication_snapshot(connection,release_id=release_id)
        subjects=portions.claims(snapshot); subjects.update(publication.publication_claims(snapshot))
        ref=f"revision:{payload['revision_id']}"; claim=subjects.get(("recipe_publication",ref))
        if claim is None: raise ReviewBlocked("publication subject is unavailable for review")
        _decision(cursor,"REJECTED",reviewer,payload["rationale"],"recipe_publication",ref,
                  portions.subject_hash("recipe_publication",claim.payload),revision["content_evidence_set_id"])
        cursor.execute("UPDATE v2_recipe_revisions SET status='REJECTED' WHERE id=%s",(payload["revision_id"],))
        cursor.execute("UPDATE v2_data_releases SET status='REJECTED' WHERE id=%s",(release_id,))
        return {"revision_id":payload["revision_id"],"status":"REJECTED"}
    finally: cursor.close()


def publish(connection, payload, reviewer):
    cursor=connection.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM v2_data_releases WHERE id=%s FOR UPDATE",(payload["release_id"],)); release=cursor.fetchone()
        if not release or release["status"]!="DRAFT" or not release["code"].startswith("admin-review-"):
            raise ReviewConflict("candidate release is missing or no longer publishable")
        cursor.execute("SELECT active_release_id FROM v2_calculation_settings WHERE id=1 FOR UPDATE")
        pointer=cursor.fetchone(); current=pointer["active_release_id"] if pointer else None
        old_catalog=_active_catalog(connection)
        parts=release["code"].split("-")
        if len(parts)<5: raise ReviewConflict("invalid candidate release code")
        expected=int(parts[-2])
        if current != (expected or None): raise ReviewConflict("active release changed; create a fresh candidate")
        cursor.execute("""SELECT m.revision_id,m.recipe_id,r.legacy_recipe_id FROM v2_release_recipes m
            JOIN v2_recipes r ON r.id=m.recipe_id WHERE m.release_id=%s""",(payload["release_id"],))
        members=cursor.fetchall()
        cursor.execute("SELECT id,content_evidence_set_id,status FROM v2_recipe_revisions WHERE id IN (%s)" % ",".join(["%s"]*len(members)),
                       tuple(r["revision_id"] for r in members))
        revisions=cursor.fetchall()
        for row in revisions:
            if row["status"]!="APPROVED" or row["content_evidence_set_id"] is None:
                raise ReviewBlocked("every recipe in a release must be approved and evidence-backed")
        # Release proof cites an already verified source; release evidence is separate from recipe evidence.
        source=None
        for row in revisions:
            cursor.execute("""SELECT s.id FROM v2_evidence_set_members m JOIN v2_evidence e ON e.id=m.evidence_id
                JOIN v2_sources s ON s.id=e.source_id WHERE m.evidence_set_id=%s AND s.verification_status='APPROVED' ORDER BY s.id LIMIT 1""",
                           (row["content_evidence_set_id"],))
            source=cursor.fetchone()
            if source: break
        if not source: raise ReviewBlocked("an approved source is required to attest the release")
        release_set=_evidence_set(cursor,f"Release review for {release['code']}")
        cursor.execute("UPDATE v2_data_releases SET evidence_set_id=%s,status='PUBLISHED',approved_at=UTC_TIMESTAMP(6) WHERE id=%s",
                       (release_set,payload["release_id"]))
        _evidence(cursor,release_set,source["id"],"release",f"release:{payload['release_id']}",payload["rationale"],"Admin release action")
        snapshot=publication.read_publication_snapshot(connection,release_id=payload["release_id"])
        subjects=portions.claims(snapshot); claim=subjects[("release",f"release:{payload['release_id']}")]
        digest=portions.subject_hash("release",claim.payload)
        decision=_decision(cursor,"APPROVED",reviewer,payload["rationale"],"release",f"release:{payload['release_id']}",digest,release_set)
        cursor.execute("UPDATE v2_data_releases SET review_decision_id=%s,manifest_hash=%s WHERE id=%s",
                       (decision,digest,payload["release_id"]))
        if pointer: cursor.execute("UPDATE v2_calculation_settings SET active_release_id=%s WHERE id=1",(payload["release_id"],))
        else: cursor.execute("INSERT INTO v2_calculation_settings(id,active_release_id) VALUES(1,%s)",(payload["release_id"],))
        new_catalog=_active_catalog(connection)
        if not old_catalog.details.keys() <= new_catalog.details.keys():
            raise ReviewBlocked("candidate release would remove an existing published recipe")
        from source.common.catalog_ids import v2_public_id
        for member in members:
            if member["legacy_recipe_id"] is None:
                public_id=v2_public_id(int(member["recipe_id"]))
                if public_id not in new_catalog.details:
                    raise ReviewBlocked("candidate release contains a recipe that does not pass public publication checks "
                        f"(recipe={public_id}, visible={sorted(new_catalog.details)})")
        return {"release_id":payload["release_id"],"status":"PUBLISHED","active":True}
    finally: cursor.close()


def unpublish(connection, payload, reviewer):
    cursor=connection.cursor(dictionary=True)
    try:
        from source.common.catalog_ids import UINT32_MAX,V2_OFFSET,MAX_PUBLIC_ID
        public_id=payload["recipe_id"]
        if not V2_OFFSET < public_id <= MAX_PUBLIC_ID:
            raise ReviewBlocked("only v2 recipes can be removed from a v2 release; legacy recipes remain unchanged")
        internal_id=public_id-V2_OFFSET
        cursor.execute("SELECT active_release_id FROM v2_calculation_settings WHERE id=1 FOR UPDATE")
        pointer=cursor.fetchone()
        if not pointer or pointer["active_release_id"] is None: raise ReviewConflict("there is no active release")
        active_id=pointer["active_release_id"]
        old_catalog=_active_catalog(connection)
        cursor.execute("SELECT recipe_id,revision_id FROM v2_release_recipes WHERE release_id=%s ORDER BY recipe_id FOR UPDATE",(active_id,))
        members=cursor.fetchall(); kept=[m for m in members if int(m["recipe_id"])!=internal_id]
        if len(kept)==len(members): raise ReviewConflict("recipe is not in the active release")
        cursor.execute("SELECT value FROM metadata WHERE `key`='dataset_version'"); version=cursor.fetchone()
        release_id=_next_id(cursor,"v2_data_releases")
        code=f"admin-review-unpublish-{internal_id}-{active_id}-{release_id}"
        cursor.execute("INSERT INTO v2_data_releases(id,code,legacy_dataset_version,status) VALUES(%s,%s,%s,'DRAFT')",
                       (release_id,code,version["value"]))
        for row in kept: cursor.execute("INSERT INTO v2_release_recipes(release_id,recipe_id,revision_id) VALUES(%s,%s,%s)",
                                        (release_id,row["recipe_id"],row["revision_id"]))
        cursor.execute("SELECT r.content_evidence_set_id FROM v2_release_recipes m JOIN v2_recipe_revisions r ON r.id=m.revision_id WHERE m.release_id=%s LIMIT 1",(release_id,))
        row=cursor.fetchone()
        if row:
            cursor.execute("SELECT s.id FROM v2_evidence_set_members m JOIN v2_evidence e ON e.id=m.evidence_id JOIN v2_sources s ON s.id=e.source_id WHERE m.evidence_set_id=%s AND s.verification_status='APPROVED' LIMIT 1",(row["content_evidence_set_id"],))
            source=cursor.fetchone()
        else:
            cursor.execute("SELECT r.content_evidence_set_id FROM v2_release_recipes m JOIN v2_recipe_revisions r ON r.id=m.revision_id WHERE m.release_id=%s AND m.recipe_id=%s LIMIT 1",(active_id,internal_id))
            removed=cursor.fetchone()
            cursor.execute("SELECT s.id FROM v2_evidence_set_members m JOIN v2_evidence e ON e.id=m.evidence_id JOIN v2_sources s ON s.id=e.source_id WHERE m.evidence_set_id=%s AND s.verification_status='APPROVED' LIMIT 1",(removed["content_evidence_set_id"],))
            source=cursor.fetchone()
        if not source: raise ReviewBlocked("an approved source is required to attest the new release")
        release_set=_evidence_set(cursor,f"Unpublish release {release_id}")
        cursor.execute("UPDATE v2_data_releases SET evidence_set_id=%s,status='PUBLISHED',approved_at=UTC_TIMESTAMP(6) WHERE id=%s",(release_set,release_id))
        _evidence(cursor,release_set,source["id"],"release",f"release:{release_id}",payload["rationale"],"Admin unpublish action")
        snapshot=publication.read_publication_snapshot(connection,release_id=release_id)
        claim=portions.claims(snapshot)[("release",f"release:{release_id}")]
        digest=portions.subject_hash("release",claim.payload)
        decision=_decision(cursor,"APPROVED",reviewer,payload["rationale"],"release",f"release:{release_id}",digest,release_set)
        cursor.execute("UPDATE v2_data_releases SET review_decision_id=%s,manifest_hash=%s WHERE id=%s",(decision,digest,release_id))
        cursor.execute("UPDATE v2_calculation_settings SET active_release_id=%s WHERE id=1",(release_id,))
        new_catalog=_active_catalog(connection)
        from source.common.catalog_ids import v2_public_id
        target_public_id=v2_public_id(internal_id)
        expected={key for key in old_catalog.details if key!=target_public_id}
        if not expected <= new_catalog.details.keys():
            raise ReviewBlocked("unpublish release would remove another published recipe")
        return {"release_id":release_id,"status":"PUBLISHED","removed_recipe_id":payload["recipe_id"]}
    finally: cursor.close()
