"""Add-only import of unapproved portion dossiers into migration 001.

JSON supplies source/recipe metadata; an optional CSV mirror must agree exactly.
--apply --draft-only explicitly authorizes draft import even when a preparation
dossier says import_allowed=false. It NEVER authorizes approval or publication.
Default is a database dry run. Existing changed/reviewed rows cause a conflict;
there is no UPDATE, DELETE, legacy DML, new DDL, review or release writer here.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import re

import mysql.connector

from source.database import migrate_v2

STATUS = "NEEDS_VERIFICATION"
FORMAT = "data-v2-portion-review-batch-1"
KEYS = {
    "v2_sources": ("id",), "v2_evidence_sets": ("id",), "v2_evidence": ("id",),
    "v2_evidence_set_members": ("evidence_set_id", "evidence_id"),
    "v2_units": ("id",), "v2_ingredients": ("id",), "v2_ingredient_forms": ("id",),
    "v2_recipes": ("id",), "v2_recipe_revisions": ("id",),
    "v2_recipe_ingredient_lines": ("revision_id", "line_no"),
}


class ImportError(ValueError):
    pass


def _json(value):
    def number(v):
        if isinstance(v, Decimal):
            text = format(v, "f")
            return text.rstrip("0").rstrip(".") if "." in text else text
        raise TypeError("unsupported import value")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, default=number)


def _hash(value):
    return sha256(_json(value).encode()).hexdigest()


def _id(table, key):
    return int(sha256(("portion-draft-v1/" + table + "/" + key).encode()).hexdigest()[:8], 16) or 1


def _need(condition, message):
    if not condition:
        raise ImportError(message)


def _text(value, limit, label):
    _need(isinstance(value, str) and 0 < len(value) <= limit and bool(value.strip()), label + " missing/too long")
    return value


def _number(value, precision=6, integer_digits=12):
    if value is None:
        return None
    _need(isinstance(value, str) and re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is not None,
          "Amounts must be positive decimal strings, never inferred")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ImportError("Invalid decimal") from exc
    _need(number > 0 and number.adjusted() < integer_digits and number.as_tuple().exponent >= -precision,
          "Amount outside the schema precision/range")
    return number


def _unapproved(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("status") or key in {"decision", "review_status"}:
                _need(item not in ("APPROVED", "PUBLISHED"), "This importer accepts unapproved dossiers only")
            if key in {"reviewer", "reviewed_at"}:
                _need(item in (None, ""), "Do not import a review identity/date as a draft")
            _unapproved(item)
    elif isinstance(value, list):
        for item in value:
            _unapproved(item)


@dataclass(frozen=True)
class Batch:
    key: str
    dossier: dict
    csv_rows: tuple[dict, ...] = ()

    @property
    def digest(self):
        return _hash({"key": self.key, "dossier": self.dossier, "csv_rows": self.csv_rows})


def validate(batch):
    _need(re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", batch.key) is not None, "Invalid batch key")
    d = batch.dossier
    _need(d.get("format") == FORMAT, "Unsupported dossier format")
    _unapproved(d)
    sources, proposals = d.get("sources"), d.get("proposals")
    _need(isinstance(sources, list) and isinstance(proposals, list) and 1 <= len(proposals) <= 6,
          "Expected source metadata and 1..6 proposals")
    refs, source_map = set(), {}
    for source in sources:
        key = _text(source.get("source_key"), 80, "source key")
        _need(key not in source_map, "Duplicate source key")
        source_map[key] = source
        _text(source.get("url"), 1000, "source URL")
        _text(source.get("title"), 255, "source title")
        _text(source.get("publisher"), 255, "source publisher")
        local = set()
        for evidence in source.get("evidence", []):
            ref = _text(evidence.get("ref"), 80, "evidence ref")
            _need(ref not in refs, "Duplicate evidence ref")
            refs.add(ref); local.add(ref)
            _text(evidence.get("locator"), 500, "evidence locator")
        source_map[key] = (source, local)
    keys, legacy_ids = set(), set()
    defaults = d["contract_notes"]["defaults_for_every_line"]
    _need(defaults.get("review_status") == STATUS, "Missing draft defaults")
    for proposal in proposals:
        key = _text(proposal.get("proposal_key"), 120, "proposal key")
        rid = proposal.get("legacy_recipe_id")
        _need(key not in keys and type(rid) is int and 1 <= rid <= 4294967295 and rid not in legacy_ids,
              "Duplicate proposal/legacy recipe or invalid ID")
        keys.add(key); legacy_ids.add(rid)
        _text(proposal.get("title"), 255, "recipe title")
        _need(proposal.get("source_key") in source_map, "Missing proposal source")
        local = source_map[proposal["source_key"]][1]
        _need(proposal.get("servings_evidence_ref") in local, "Servings evidence belongs to another source")
        _number(proposal.get("base_servings"), 3, 7)
        _need(proposal.get("serving_basis") in (None, "source_servings", "adult_equivalent"), "Invalid serving basis")
        lines = proposal.get("ingredient_lines")
        _need(isinstance(lines, list) and 1 <= len(lines) <= 64, "Invalid ingredient line count")
        line_ids = set()
        for line in lines:
            number = line.get("line_no")
            _need(type(number) is int and 1 <= number <= 4294967295 and number not in line_ids, "Invalid/duplicate line number")
            line_ids.add(number)
            _need(line.get("component_kind") in {"ingredient_usage", "unresolved_instruction"}, "Unknown component kind")
            _text(line.get("source_name"), 255, "source ingredient name")
            iid = line.get("ingredient_id")
            _need(iid is None or type(iid) is int and 1 <= iid <= 4294967295, "Invalid legacy ingredient mapping")
            _need(line.get("quantity_evidence_ref") in local and line.get("form_evidence_ref") in local | {None},
                  "Line evidence belongs to another source")
            kind, value = line.get("amount_kind"), line.get("quantity_value")
            _need(kind in {"exact", "range", "unknown", "to_taste", "as_needed"}, "Invalid amount kind")
            if kind == "exact":
                _need(value is not None and line.get("quantity_min") is None and line.get("quantity_max") is None,
                      "Exact amount needs one explicit value")
                _number(value)
            elif kind == "range":
                low, high = _number(line.get("quantity_min")), _number(line.get("quantity_max"))
                _need(value is None and low is not None and high is not None and low <= high,
                      "Do not select a midpoint or mix scalar/range amounts")
            else:
                _need(value is None and line.get("quantity_min") is None and line.get("quantity_max") is None,
                      "Unknown amounts must stay null")
            if kind in {"exact", "range"}:
                _text(line.get("unit"), 40, "source unit")
            if line.get("unit") is not None:
                _text(line["unit"], 40, "source unit")
            if line.get("ingredient_form") is not None:
                _text(line["ingredient_form"], 80, "ingredient form")
            if line.get("quantity_raw") is not None:
                _text(line["quantity_raw"], 255, "raw amount")
            if line["component_kind"] == "unresolved_instruction":
                _need(iid is None and value is None, "An instruction gap must not become an ingredient")
            merged = {**defaults, **line}
            _need(merged.get("requirement") in {"required", "optional", "unknown"}, "Invalid requirement")
            _need(merged.get("measurement_basis") in {None, "unknown", "gross", "edible", "prepared"}, "Invalid measurement basis")
            _need(merged.get("purpose") in {None, "unknown", "consumed", "cooking_medium", "garnish"}, "Invalid purpose")
            _need(merged.get("scaling_mode") in {None, "linear", "fixed"}, "Invalid scaling mode")
        _need(sum(l["component_kind"] == "ingredient_usage" for l in lines) <= 50, "Too many ingredient uses")
    if batch.csv_rows:
        indexed = {(p["proposal_key"], str(l["line_no"])): (p, l) for p in proposals for l in p["ingredient_lines"]}
        _need(len(batch.csv_rows) == len(indexed), "CSV row count mismatch")
        seen = set()
        for row in batch.csv_rows:
            pair = (row.get("proposal_key"), row.get("line_no"))
            _need(pair in indexed and pair not in seen, "CSV contains missing/duplicate/unknown lines")
            seen.add(pair)
            proposal, line = indexed[pair]
            expected = {**defaults, **line, **{key: proposal[key] for key in
                ["proposal_key", "legacy_recipe_id", "base_servings", "serving_basis", "base_servings_review_status", "source_key"]}}
            expected["source_url"] = source_map[proposal["source_key"]][0]["url"]
            for field in ["legacy_recipe_id", "base_servings", "serving_basis", "base_servings_review_status", "component_kind",
                          "source_name", "ingredient_id", "quantity_value", "quantity_min", "quantity_max", "amount_kind",
                          "unit", "quantity_raw", "ingredient_form", "stage", "purpose", "measurement_basis", "requirement",
                          "scaling_mode", "quantity_evidence_ref", "form_evidence_ref", "source_key", "source_url"]:
                value = expected.get(field)
                _need(row.get(field, "") == ("" if value is None else str(value)), "CSV/JSON mismatch: " + field)
            for field in ["candidate_ingredient_ids", "source_alternative_measurement"]:
                actual = json.loads(row[field]) if row.get(field) else None
                _need(actual == line.get(field), "CSV/JSON mismatch: " + field)
            _need(all(value == STATUS for key, value in row.items() if key.endswith("_review_status") or key == "review_status"),
                  "CSV contains reviewed values")
    return batch


def load_batch(json_path, csv_path=None, key="portion-batch-01"):
    def no_duplicates(pairs):
        value = {}
        for name, item in pairs:
            _need(name not in value, "Duplicate JSON key")
            value[name] = item
        return value
    path = Path(json_path)
    _need(path.stat().st_size <= 2_000_000, "Dossier too large")
    dossier = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=no_duplicates)
    rows = ()
    if csv_path:
        _need(Path(csv_path).stat().st_size <= 2_000_000, "CSV too large")
        with Path(csv_path).open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            _need(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), "Duplicate CSV headers")
            rows = tuple(reader)
    return validate(Batch(key, dossier, rows))


class Plan:
    def __init__(self):
        self.rows = {table: {} for table in KEYS}

    def add(self, table, row):
        key = tuple(row[k] for k in KEYS[table])
        existing = self.rows[table].get(key)
        _need(existing is None or existing == row, "Planned identity collision: " + table)
        self.rows[table][key] = row
        return row.get("id")


def build_plan(batch, legacy):
    validate(batch)
    plan, d = Plan(), batch.dossier
    captured = datetime.now(timezone.utc).replace(tzinfo=None)
    def evidence_set(key, description):
        identity = _id("v2_evidence_sets", key)
        plan.add("v2_evidence_sets", {"id": identity, "description": description})
        return identity
    def evidence(key, source, scope, ref, locator, value):
        payload = _json(value)
        _need(len(payload.encode()) <= 65535, "Evidence exceeds MySQL TEXT capacity")
        identity = _id("v2_evidence", batch.key + "/" + key)
        plan.add("v2_evidence", {"id": identity, "source_id": source, "locator": locator,
            "excerpt_or_observation": payload, "claim_scope": scope, "entity_ref": ref,
            "captured_at": captured, "content_hash": sha256(payload.encode()).hexdigest()})
        return identity
    def member(group, item):
        plan.add("v2_evidence_set_members", {"evidence_set_id": group, "evidence_id": item})
    internal = _id("v2_sources", batch.key + "/bundle")
    plan.add("v2_sources", {"id": internal, "source_kind": "internal_dossier", "title": batch.key + " draft import bundle",
        "url": None, "document_ref": "draft-import:" + batch.key, "author_or_publisher": None,
        "accessed_at": None, "content_hash": batch.digest,
        "usage_note": _json({"mode": "draft-only; explicitly authorized despite preparation import_allowed=false",
            "capture_semantics": "Existing dossier imported now; no new web visit or human review",
            "json_format": d["format"], "csv_mirror_present": bool(batch.csv_rows)}), "verification_status": STATUS})
    evidence("json-snapshot", internal, "import_manifest", "batch:" + batch.key, "proposed-revisions.json", d)
    if batch.csv_rows:
        evidence("csv-snapshot", internal, "import_manifest", "batch:" + batch.key + ":csv", "ingredient-lines.csv", batch.csv_rows)
    sources = {}
    for source in d["sources"]:
        identity = _id("v2_sources", batch.key + "/" + source["source_key"])
        sources[source["source_key"]] = (identity, {e["ref"]: e for e in source["evidence"]})
        plan.add("v2_sources", {"id": identity, "source_kind": "candidate_recipe_reference", "title": source["title"],
            "url": source["url"], "document_ref": source["source_key"], "author_or_publisher": source["publisher"],
            "accessed_at": None, "content_hash": source.get("source_content_sha256"),
            "usage_note": _json({"source": source, "date_only_access": "checked_on is retained; exact web access time is unknown"}),
            "verification_status": STATUS})
        for observation in source["evidence"]:
            evidence("observation/" + observation["ref"], identity, "source_observation", "source:" + str(identity),
                     observation["locator"], observation)
    defaults = d["contract_notes"]["defaults_for_every_line"]
    csv_map = {(r["proposal_key"], int(r["line_no"])): r for r in batch.csv_rows}
    recipe_map = []
    for proposal in d["proposals"]:
        key, legacy_id = proposal["proposal_key"], proposal["legacy_recipe_id"]
        _need(legacy_id in legacy["recipes"], "Legacy recipe does not exist")
        recipe_id = _id("v2_recipes", "legacy/" + str(legacy_id))
        revision_id = _id("v2_recipe_revisions", batch.key + "/" + key)
        ref = "revision:" + str(revision_id)
        source_id, observations = sources[proposal["source_key"]]
        content = evidence_set(batch.key + "/content/" + key, STATUS + ": content " + key)
        servings = evidence_set(batch.key + "/servings/" + key, STATUS + ": servings " + key)
        observation = observations[proposal["servings_evidence_ref"]]
        marker = evidence("content/" + key, source_id, "recipe_content", ref, observation["locator"], {
            "proposal": proposal, "import_gaps": ["instructions_missing_from_dossier", "minutes_missing_from_dossier"],
            "content_complete": False, "review_status": STATUS})
        member(content, marker)
        marker = evidence("servings/" + key, source_id, "servings", ref, observation["locator"], {
            "base_servings": proposal.get("base_servings"), "serving_basis": proposal.get("serving_basis"),
            "observation": observation, "review_status": STATUS})
        member(servings, marker)
        plan.add("v2_recipes", {"id": recipe_id, "legacy_recipe_id": legacy_id, "variant_of_recipe_id": None,
                               "origin_kind": "curated_variant", "author_ref": None})
        plan.add("v2_recipe_revisions", {"id": revision_id, "recipe_id": recipe_id, "revision_no": 1,
            "title": proposal["title"], "instructions": "", "minutes": None,
            "base_servings": _number(proposal.get("base_servings"), 3, 7), "serving_basis": proposal.get("serving_basis"),
            "content_complete": 0, "status": STATUS, "content_evidence_set_id": content,
            "servings_evidence_set_id": servings, "content_review_id": None, "servings_review_id": None,
            "legacy_snapshot_hash": _hash(legacy["recipes"][legacy_id])})
        recipe_map.append({"proposal_key": key, "legacy_recipe_id": legacy_id, "recipe_id": recipe_id, "revision_id": revision_id})
        for original in proposal["ingredient_lines"]:
            line = {**defaults, **original}
            line_key = key + "/" + str(line["line_no"])
            line_ref = "line:" + str(revision_id) + ":" + str(line["line_no"])
            observed = observations[line["quantity_evidence_ref"]]
            scope = "instruction_gap" if line["component_kind"] == "unresolved_instruction" else "quantity"
            entity_ref = ref + ":gap:" + str(line["line_no"]) if scope == "instruction_gap" else line_ref
            marker = evidence("line/" + line_key, source_id, scope, entity_ref, observed["locator"], {
                "line": line, "csv_row": csv_map.get((key, line["line_no"])), "source_observation": observed,
                "capture_semantics": "Database capture of existing unapproved dossier; no new source verification"})
            if line["component_kind"] == "unresolved_instruction":
                member(content, marker)
                continue
            quantity_set = evidence_set(batch.key + "/quantity/" + line_key, STATUS + ": quantity " + line_key)
            member(quantity_set, marker)
            unit_id = ingredient_id = form_id = None
            if line.get("unit") is not None:
                label = line["unit"]
                unit_id = _id("v2_units", label)
                unit_set = evidence_set("unit/" + label, STATUS + ": source unit " + label)
                unit_marker = evidence("unit/" + line_key, source_id, "unit", "unit:" + str(unit_id),
                    observed["locator"], {"source_unit": label, "original_line": original,
                        "source_observation": observed, "verification_status": STATUS, "conversion_rule": None})
                member(unit_set, unit_marker)
                standard = {"g": "mass", "ml": "volume", "l": "volume"}
                code = label if label in standard else "source_" + sha256(label.encode()).hexdigest()[:16]
                plan.add("v2_units", {"id": unit_id, "code": code, "dimension": standard.get(label, "source_defined"),
                    "symbol": label, "definition": "Source label: " + label + "; NEEDS_VERIFICATION; no conversion asserted",
                    "status": STATUS, "evidence_set_id": unit_set, "review_decision_id": None})
            legacy_ingredient = line.get("ingredient_id")
            if legacy_ingredient is not None:
                _need(legacy_ingredient in legacy["ingredients"], "Legacy ingredient mapping does not exist")
                identity = legacy["ingredients"][legacy_ingredient]
                ingredient_id = _id("v2_ingredients", "legacy/" + str(legacy_ingredient))
                identity_set = evidence_set("ingredient/" + str(legacy_ingredient), STATUS + ": proposed legacy identity " + str(legacy_ingredient))
                identity_marker = evidence("identity/" + line_key, source_id, "ingredient_identity",
                    "ingredient_identity:" + str(ingredient_id), observed["locator"], {
                        "legacy_identity_proposed": identity, "source_name": line["source_name"],
                        "original_line": original, "mapping_status": STATUS})
                member(identity_set, identity_marker)
                plan.add("v2_ingredients", {"id": ingredient_id, "legacy_ingredient_id": legacy_ingredient,
                    "canonical_name": identity["name"], "normalized_name": identity["normalized_name"],
                    "identity_status": STATUS, "evidence_set_id": identity_set, "review_decision_id": None})
                if line.get("ingredient_form") is not None:
                    form_key = str(ingredient_id) + "/" + line["ingredient_form"]
                    form_id = _id("v2_ingredient_forms", form_key)
                    form_set = evidence_set("form/" + form_key, STATUS + ": proposed form " + str(form_id))
                    form_observation = observations.get(line.get("form_evidence_ref"))
                    form_marker = evidence("form/" + line_key, source_id, "ingredient_form",
                        "ingredient_form:" + str(form_id), (form_observation or observed)["locator"], {
                            "form_proposed": line["ingredient_form"], "form_observation": form_observation,
                            "original_line": original, "verification_status": STATUS})
                    member(form_set, form_marker)
                    plan.add("v2_ingredient_forms", {"id": form_id, "ingredient_id": ingredient_id,
                        "form_code": line["ingredient_form"], "description": line["ingredient_form"],
                        "status": STATUS, "evidence_set_id": form_set, "review_decision_id": None})
            low = _number(line.get("quantity_value")) if line["amount_kind"] == "exact" else _number(line.get("quantity_min"))
            high = _number(line.get("quantity_max")) if line["amount_kind"] == "range" else None
            plan.add("v2_recipe_ingredient_lines", {"revision_id": revision_id, "line_no": line["line_no"],
                "ingredient_id": ingredient_id, "form_id": form_id, "quantity_raw": line.get("quantity_raw"),
                "amount_kind": line["amount_kind"], "amount_min": low, "amount_max": high, "unit_id": unit_id,
                "requirement": line["requirement"], "purpose": line.get("purpose") or "unknown",
                "measurement_basis": line.get("measurement_basis") or "unknown", "scaling_mode": line.get("scaling_mode"),
                "status": STATUS, "quantity_evidence_set_id": quantity_set, "quantity_review_id": None,
                "scaling_evidence_set_id": None, "scaling_review_id": None, "legacy_relation_hash": None})
    return plan, recipe_map


def _query(connection, sql, params=()):
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.with_rows else []
    finally:
        cursor.close()


def _ensure(connection, table, row, apply):
    key = KEYS[table]
    where = " AND ".join(f"`{k}`=%s" for k in key)
    existing = _query(connection, f"SELECT * FROM `{table}` WHERE {where} FOR UPDATE", tuple(row[k] for k in key))
    if existing:
        old = existing[0]
        _need(all(_json(old[k]) == _json(v) for k, v in row.items() if k != "captured_at"),
              "Import conflict; existing row changed or reviewed: " + table)
        return False
    if apply:
        columns = list(row)
        _query(connection, f"INSERT INTO `{table}` ({','.join('`'+k+'`' for k in columns)}) VALUES ({','.join('%s' for _ in columns)})",
               tuple(row[k] for k in columns))
    return True


def import_drafts(connection, batch, apply=False):
    validate(batch)
    _need(not connection.in_transaction, "Use a dedicated idle import connection")
    original_autocommit = connection.autocommit
    connection.autocommit = True
    lock = None
    try:
        database = _query(connection, "SELECT DATABASE() AS name")[0]["name"]
        lock = "v2-draft-import-" + sha256(database.encode()).hexdigest()[:32]
        _need(_query(connection, "SELECT GET_LOCK(%s,5) AS ok", (lock,))[0]["ok"] == 1, "Another import holds the lock")
        _need(migrate_v2.check(connection)["state"] == "APPLIED", "Migration 001 must be applied first")
        _need(_query(connection, "SELECT @@SESSION.foreign_key_checks AS ok")[0]["ok"] == 1, "Foreign keys must stay enabled")
        connection.start_transaction(isolation_level="SERIALIZABLE")
        recipe_ids = sorted(p["legacy_recipe_id"] for p in batch.dossier["proposals"])
        ingredient_ids = sorted({l["ingredient_id"] for p in batch.dossier["proposals"] for l in p["ingredient_lines"] if l.get("ingredient_id") is not None})
        legacy = {}
        for table, ids in [("recipes", recipe_ids), ("ingredients", ingredient_ids)]:
            rows = _query(connection, f"SELECT * FROM `{table}` WHERE id IN ({','.join('%s' for _ in ids)})", tuple(ids)) if ids else []
            legacy[table] = {row["id"]: row for row in rows}
        plan, recipe_map = build_plan(batch, legacy)
        added, reused = {}, {}
        for table, entries in plan.rows.items():
            added[table] = reused[table] = 0
            for row in entries.values():
                if _ensure(connection, table, row, apply):
                    added[table] += 1
                else:
                    reused[table] += 1
        if apply:
            connection.commit()
        else:
            connection.rollback()
        return {"database": database, "batch_key": batch.key, "bundle_hash": batch.digest,
                "mode": "draft-only", "applied": apply, "changed": apply and any(added.values()),
                "inserted" if apply else "would_insert": added, "reused": reused, "recipes": recipe_map}
    except Exception:
        connection.rollback()
        raise
    finally:
        if lock:
            _query(connection, "SELECT RELEASE_LOCK(%s)", (lock,))
        connection.autocommit = original_autocommit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--json", required=True)
    parser.add_argument("--lines-csv")
    parser.add_argument("--batch-key", default="portion-batch-01")
    parser.add_argument("--draft-only", action="store_true", required=True)
    parser.add_argument("--apply", action="store_true", help="Without this flag, only check existing rows and the import plan")
    args = parser.parse_args()
    from dotenv import dotenv_values
    from source.server.repository import mysql_config_from_env
    config = mysql_config_from_env()
    values = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
    for key in ("user", "password"):
        value = values.get("MYSQL_MIGRATION_" + key.upper())
        _need(value is not None, "Missing dedicated migration credentials in root .env")
        config[key] = value
    _need(config["user"] != "goiy_app", "Runtime account cannot import data")
    config["database"] = args.database
    batch = load_batch(args.json, args.lines_csv, args.batch_key)
    connection = mysql.connector.connect(**config)
    try:
        print(json.dumps(import_drafts(connection, batch, args.apply), ensure_ascii=True))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
