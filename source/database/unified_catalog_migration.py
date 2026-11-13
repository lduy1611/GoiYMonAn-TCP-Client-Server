"""Repeatable TEST_ONLY conversion from the current effective catalog.

This utility refuses production targets. It reads legacy/v2 through the same
MySQL repository adapters as User requests, preserves public numeric IDs, and
does not mutate the source schema. The v2 review/release tables remain intact
in the source database as the archive/rollback copy.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
from pathlib import Path
import unicodedata

import mysql.connector

from source.common.catalog_ids import V2_OFFSET, v2_public_id

VERSION = "unified-catalog-1"
ROOT = Path(__file__).resolve().parents[2]
SCHEMA_SQL = Path(__file__).with_name("unified_schema.sql")

# Reference units needed by the structured Admin form and portion calculator.
# Conversion factors are intentionally absent: v3 currently combines quantities
# only when their unit codes match, so these rows cannot imply a conversion.
STANDARD_UNITS = (
    ("g", "gam", "mass"),
    ("kg", "ki-lô-gam", "mass"),
    ("ml", "mi-li-lít", "volume"),
    ("l", "lít", "volume"),
    ("piece", "cái", "count"),
    ("clove", "tép", "count"),
    ("stalk", "nhánh", "count"),
    ("bunch", "bó", "count"),
    ("leaf", "lá", "count"),
    ("tsp", "muỗng cà phê", "volume"),
    ("tbsp", "muỗng canh", "volume"),
    ("cup", "chén", "volume"),
)


class UnifiedMigrationError(RuntimeError):
    pass


def _query(connection, sql, params=()):
    cur = connection.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()


def _execute(connection, sql, params=()):
    cur = connection.cursor()
    try:
        cur.execute(sql, params)
        return cur.lastrowid, cur.rowcount
    finally:
        cur.close()


def _canonical(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def _hash(value):
    blob = json.dumps(_canonical(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _norm(value):
    return " ".join(unicodedata.normalize("NFC", str(value)).casefold().split())


def create_schema(connection):
    """Create target tables. Caller must have selected an isolated *_test DB."""
    db = _query(connection, "SELECT DATABASE() AS db")[0]["db"]
    if not db or not str(db).endswith("_test"):
        raise UnifiedMigrationError("Unified schema creation is restricted to a database ending in _test")
    text = SCHEMA_SQL.read_text(encoding="utf-8")
    statements = []
    for raw in text.split(";"):
        statement = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("--")).strip()
        if statement:
            statements.append(statement)
    for statement in statements:
        _execute(connection, statement)
    seed_standard_units(connection)
    return len(statements)


def seed_standard_units(connection):
    """Idempotently add the built-in unit vocabulary to an isolated *_test DB.

    Existing unit definitions are preserved. A conflicting definition fails
    closed instead of silently changing quantities already stored against it.
    """
    db = _query(connection, "SELECT DATABASE() AS db")[0]["db"]
    if not db or not str(db).endswith("_test"):
        raise UnifiedMigrationError("Unit catalog setup is restricted to a database ending in _test")
    tables = _query(connection, """SELECT COUNT(*) AS n FROM information_schema.tables
        WHERE table_schema=%s AND table_name='units'""", (db,))
    if int(tables[0]["n"]) != 1:
        raise UnifiedMigrationError("Unified units table is unavailable")
    for code, name, dimension in STANDARD_UNITS:
        existing = _query(connection, "SELECT name,dimension FROM units WHERE code=%s", (code,))
        if existing:
            if existing[0]["name"] != name or existing[0]["dimension"] != dimension:
                raise UnifiedMigrationError(f"Existing unit definition conflicts with standard code {code}")
            continue
        _execute(connection, "INSERT INTO units(code,name,dimension) VALUES(%s,%s,%s)",
                  (code, name, dimension))
    return len(STANDARD_UNITS)


def _adapter(connection):
    """Construct the read-only runtime projection without creating a pool."""
    from source.server.repository import MySQLRepository
    from source.server.published_repository import PublishedRepository
    from source.server.mysql_recipe_catalog import load_catalog

    legacy = MySQLRepository.__new__(MySQLRepository)
    legacy.config = {"database": _query(connection, "SELECT DATABASE() AS db")[0]["db"]}
    catalog = load_catalog(connection)
    return legacy, PublishedRepository(legacy, catalog), catalog


def _legacy_roles():
    path = ROOT / "data" / "recipe_categories.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        categories = value.get("categories", {})
        if categories:
            return {int(k): str(v) for k, v in categories.items()}
        # The checked-in legacy file uses a list of {recipe_id, category} rows.
        # Accept a mapping as well for future classification snapshots.
        rows = value.get("recipes", {})
        if isinstance(rows, list):
            return {int(row["recipe_id"]): str(row["category"])
                    for row in rows if isinstance(row, dict)
                    and row.get("recipe_id") is not None and row.get("category")}
        if isinstance(rows, dict):
            return {int(k): str(v) for k, v in rows.items()}
        return {}
    except (OSError, ValueError, TypeError):
        return {}


def _role(value):
    aliases = {"main": "main", "vegetable": "vegetable", "soup": "soup",
               "side": "side", "drink": "drink", "starch": "starch", "other": "other"}
    return aliases.get(value, "other")


def _numbered_steps(text):
    matches=list(re.finditer(r"(?m)^\s*(?:B\u01b0\u1edbc\s*)?(\d+)[.):]\s+",str(text or "")))
    if not matches or matches[0].start()!=0:
        return []
    return [{"step_no":i+1,"instruction":str(text)[m.end():matches[i+1].start() if i+1<len(matches) else len(text)].strip()}
            for i,m in enumerate(matches)]


def _fallback_images():
    path = ROOT / "source" / "web" / "static" / "recipe-images.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        rows = value.get("recipes", value) if isinstance(value, dict) else value
        result = {}
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("recipe_id") and isinstance(row.get("image_path"), str):
                    result[int(row["recipe_id"])] = row["image_path"]
        elif isinstance(rows, dict):
            for key, row in rows.items():
                if isinstance(row, dict) and isinstance(row.get("image_path"), str):
                    result[int(key)] = row["image_path"]
        return result
    except (OSError, ValueError, TypeError):
        return {}


def _source_snapshot(source):
    legacy, published, catalog = _adapter(source)
    legacy_rows = legacy._legacy_ingredient_catalog(source, include_inactive=True)
    legacy_by_id = {int(row["id"]): row for row in legacy_rows}
    legacy_by_name = {}
    for row in legacy_rows:
        legacy_by_name.setdefault(_norm(row["name"]), int(row["id"]))

    public_ingredients = published.list_ingredients(source, "", 100)
    public_ingredient_ids = {int(row["id"]) for row in public_ingredients}
    ingredient_source_rows = []
    ingredient_map = {}
    aliases = []
    for row in legacy_rows:
        iid = int(row["id"])
        ingredient_map[iid] = iid
        ingredient_source_rows.append({"source_kind": "legacy", "source_id": iid,
            "ingredient_id": iid, "name": row["name"], "normalized_name": row["normalized_name"],
            "group_name": None, "is_active": bool(row["is_active"])})
        aliases.extend((iid, alias, _norm(alias)) for alias in row.get("aliases", []))

    v2_rows = _query(source, """SELECT i.id,i.legacy_ingredient_id,i.canonical_name,i.normalized_name,
        i.identity_status,i.review_decision_id,i.evidence_set_id,COALESCE(s.is_active,1) AS is_active
        FROM v2_ingredients i LEFT JOIN v2_ingredient_admin_state s ON s.ingredient_id=i.id ORDER BY i.id""")
    v2_to_legacy = {}
    for row in v2_rows:
        internal = int(row["id"])
        if row["legacy_ingredient_id"] is not None:
            v2_to_legacy[internal] = int(row["legacy_ingredient_id"])
        else:
            # Exact normalized matches are the existing business-ID rule; no
            # fuzzy/synonym matching is performed by this converter.
            old_id = legacy_by_name.get(_norm(row["canonical_name"]))
            if old_id is not None:
                v2_to_legacy[internal] = old_id
        business_id = v2_to_legacy.get(internal, v2_public_id(internal))
        ingredient_map[business_id] = business_id
        ingredient_source_rows.append({"source_kind": "v2", "source_id": internal,
            "ingredient_id": business_id,
            "name": legacy_by_id[business_id]["name"] if business_id in legacy_by_id else row["canonical_name"],
            "normalized_name": _norm(legacy_by_id[business_id]["name"] if business_id in legacy_by_id else row["canonical_name"]),
            "group_name": None,
            "is_active": business_id in public_ingredient_ids})

    # Duplicate source identities are retained as rows. IDs are only mapped
    # together for an explicit legacy link or the pre-existing exact-name
    # business-ID projection. Unlinked synonyms are never fuzzy-merged.
    ingredient_rows_by_id = {}
    ingredient_maps = []
    for row in ingredient_source_rows:
        iid = row["ingredient_id"]
        current = ingredient_rows_by_id.get(iid)
        if current is None:
            ingredient_rows_by_id[iid] = dict(row)
        else:
            current["is_active"] = current["is_active"] or row["is_active"]
            if current["name"] != row["name"]:
                raise UnifiedMigrationError(f"Source ID {iid} maps to conflicting ingredient names")
        ingredient_maps.append((row["source_kind"], row["source_id"], iid))

    legacy_recipe_ids = [int(r[0]) for r in legacy._fetchall(source, "SELECT id FROM recipes ORDER BY id")]
    if len(legacy_recipe_ids) != 50:
        raise UnifiedMigrationError(f"Expected 50 source legacy recipes, found {len(legacy_recipe_ids)}")
    recipe_rows_by_id = {}
    recipe_lines_by_id = {}
    recipe_maps = []
    categories = _legacy_roles()
    hidden = set(catalog.hidden_ids)
    deleted = set(catalog.deleted_ids)
    for rid in legacy_recipe_ids:
        detail = legacy.get_recipe(source, rid)
        if detail is None:
            raise UnifiedMigrationError(f"Legacy recipe {rid} cannot be read through the current repository")
        is_deleted = rid in deleted
        visible = bool(detail.get("is_visible", True)) and rid not in hidden and not is_deleted
        recipe_rows_by_id[rid] = {"recipe_id": rid, "title": detail["title"],
            "normalized_title": _norm(detail["title"]), "description": detail.get("description") or "",
            "role": _role(categories.get(rid)), "minutes_total": int(detail["minutes"]),
            "minutes_prep": None, "minutes_cook": None, "servings": None,
            "instructions_legacy": detail.get("instructions") or "", "fallback_image_url": None,
            "source_url": detail.get("source_url"), "is_public": visible,
            "deleted_at": None, "edit_version": 1}
        recipe_lines_by_id[rid] = _detail_lines(detail, ingredient_map)
        recipe_maps.append(("legacy", rid, rid))
    for old_id, url in _fallback_images().items():
        if old_id in recipe_rows_by_id:
            recipe_rows_by_id[old_id]["fallback_image_url"] = url

    # The runtime catalog is the source of truth for public v2 dishes. Directly
    # hidden/deleted Admin rows are retained privately; unregistered old drafts
    # remain in the source DB archive and are never turned into public recipes.
    v2_recipe_rows = _query(source, """SELECT id,legacy_recipe_id,origin_kind FROM v2_recipes ORDER BY id""")
    for row in v2_recipe_rows:
        if row["legacy_recipe_id"] is not None:
            recipe_maps.append(("v2_link", int(row["id"]), int(row["legacy_recipe_id"])))
    for public_id, detail in catalog.details.items():
        internal = int(public_id) - V2_OFFSET
        if internal <= 0:
            continue
        role = catalog.roles.get(public_id, detail.get("role", "other"))
        recipe_rows_by_id[int(public_id)] = {"recipe_id": int(public_id), "title": detail["title"],
            "normalized_title": _norm(detail["title"]), "description": detail.get("description") or "",
            "role": _role(role), "minutes_total": int(detail["minutes"]), "minutes_prep": None,
            "minutes_cook": None, "servings": None, "instructions_legacy": detail.get("instructions") or "",
            "fallback_image_url": None, "source_url": detail.get("source_url"), "is_public": True,
            "deleted_at": None, "edit_version": 1}
        recipe_lines_by_id[int(public_id)] = _detail_lines(detail, ingredient_map)
        recipe_maps.append(("v2_catalog", internal, int(public_id)))

    # Preserve explicit Admin-hidden/deleted v2 recipes without publishing them.
    direct = _query(source, """SELECT v2_recipe_id,revision_id,role_code,is_visible,is_deleted,updated_at
        FROM v2_admin_recipe_catalog_overrides WHERE v2_recipe_id IS NOT NULL""")
    for row in direct:
        rid = int(row["v2_recipe_id"])
        public_id = v2_public_id(rid)
        if public_id in recipe_rows_by_id:
            recipe_rows_by_id[public_id]["is_public"] = bool(row["is_visible"]) and not bool(row["is_deleted"])
            if row["is_deleted"]:
                recipe_rows_by_id[public_id]["deleted_at"] = row["updated_at"]
            continue
        revision_id = row["revision_id"]
        if not revision_id:
            continue
        rev = _query(source, "SELECT title,description,instructions,minutes FROM v2_recipe_revisions WHERE id=%s AND recipe_id=%s",
                     (revision_id, rid))
        if not rev:
            raise UnifiedMigrationError(f"Admin catalog recipe {rid} points to a missing revision")
        lines = _query(source, """SELECT l.line_no,l.ingredient_id,l.quantity_raw,l.requirement,
            i.legacy_ingredient_id,i.canonical_name FROM v2_recipe_ingredient_lines l
            JOIN v2_ingredients i ON i.id=l.ingredient_id WHERE l.revision_id=%s ORDER BY l.line_no""", (revision_id,))
        recipe_rows_by_id[public_id] = {"recipe_id": public_id, "title": rev[0]["title"],
            "normalized_title": _norm(rev[0]["title"]), "description": rev[0]["description"] or "",
            "role": _role(row["role_code"]), "minutes_total": int(rev[0]["minutes"] or 1),
            "minutes_prep": None, "minutes_cook": None, "servings": None,
            "instructions_legacy": rev[0]["instructions"] or "", "fallback_image_url": None,
            "source_url": None, "is_public": bool(row["is_visible"]) and not bool(row["is_deleted"]),
            "deleted_at": row["updated_at"] if row["is_deleted"] else None, "edit_version": 1}
        recipe_lines_by_id[public_id] = []
        for line in lines:
            source_iid = int(line["ingredient_id"])
            business_iid = (int(line["legacy_ingredient_id"]) if line["legacy_ingredient_id"] is not None
                            else v2_public_id(source_iid))
            if business_iid not in ingredient_rows_by_id:
                raise UnifiedMigrationError(f"Recipe {public_id} ingredient ID {business_iid} has no catalog mapping")
            recipe_lines_by_id[public_id].append({"line_no": int(line["line_no"]), "ingredient_id": business_iid,
                "quantity_text": line["quantity_raw"] or "", "requirement": line["requirement"] or "unknown"})
        recipe_maps.append(("v2_catalog", rid, public_id))

    # Active direct/approved v2 recipes and legacy recipes must resolve every
    # ingredient to the same business ID that the User picker exposes.
    for rid,row in recipe_rows_by_id.items():
        if row["is_public"]:
            missing = sorted({line["ingredient_id"] for line in recipe_lines_by_id.get(rid, [])}
                             - public_ingredient_ids)
            if missing:
                raise UnifiedMigrationError(f"Public recipe {rid} refers to ingredients absent from the current User catalog: {missing}")

    image_rows = _query(source, """SELECT recipe_id,catalog_kind,storage_key,media_type,byte_size,width,height,sha256
        FROM v2_recipe_image_overrides ORDER BY recipe_id""")
    # Images must point at an imported recipe. Physical bytes are verified and
    # copied into the target-specific private storage by migrate().
    image_rows = [r for r in image_rows if int(r["recipe_id"]) in recipe_rows_by_id]
    accounts = _query(source, """SELECT user_id,username,normalized_username,password_hash,role,account_status,
        created_at,updated_at,last_login_at FROM v2_user_accounts ORDER BY user_id""")
    aliases.sort(key=lambda x: (x[0], x[2], x[1]))
    tags=[]
    for rid in catalog.plant_ids:
        if int(rid) in recipe_rows_by_id:tags.append((int(rid),"diet","vegetarian","Chay"))
    for group in ("region","occasion"):
        for code,ids in catalog.contexts.get(group,{}).items():
            for rid in ids:
                if int(rid) in recipe_rows_by_id:
                    tags.append((int(rid),group,str(code),str(code)))
    return {"recipes": recipe_rows_by_id, "recipe_lines": recipe_lines_by_id,
        "recipe_maps": sorted(set(recipe_maps)), "ingredients": ingredient_rows_by_id,
        "ingredient_maps": sorted(set(ingredient_maps)), "aliases": aliases,
        "images": image_rows, "accounts": accounts, "tags": sorted(set(tags)), "public_recipe_ids": sorted(
            rid for rid,row in recipe_rows_by_id.items() if row["is_public"]),
        "public_ingredient_ids": sorted(public_ingredient_ids),
        "legacy_counts": {"recipes": len(legacy_recipe_ids),
            "ingredients": len(legacy_rows),
            "recipe_ingredients": int(_query(source,"SELECT COUNT(*) n FROM recipe_ingredients")[0]["n"])},
        "catalog_version": published.dataset_version(source)}


def _detail_lines(detail, ingredient_map):
    result = []
    for index,line in enumerate(detail.get("ingredients", []),1):
        iid = int(line["id"])
        mapped = ingredient_map.get(iid)
        if mapped is None:
            raise UnifiedMigrationError(f"Recipe ingredient public ID {iid} is not mapped")
        result.append({"line_no": index,"ingredient_id": mapped,
            "quantity_text": line.get("quantity") or "",
            "requirement": "required" if line.get("is_required", True) else "optional"})
    return result


def _fingerprint(snapshot, source_db):
    payload = {"source_database": source_db, "version": VERSION,
        "recipes": list(snapshot["recipes"].values()), "recipe_lines": snapshot["recipe_lines"],
        "recipe_maps": snapshot["recipe_maps"], "ingredients": list(snapshot["ingredients"].values()),
        "ingredient_maps": snapshot["ingredient_maps"], "aliases": snapshot["aliases"],
        "images": snapshot["images"], "accounts": snapshot["accounts"], "tags": snapshot["tags"]}
    return _hash(payload)


def _empty_target(connection):
    for table in ("users","ingredients","recipes","recipe_ingredients","recipe_steps",
                  "recipe_tag_links","recipe_images","recipe_edit_history","recipe_id_map","ingredient_id_map",
                  "unified_import_runs","achievement_posts","achievement_images",
                  "achievement_comments","feedback_submissions"):
        n = int(_query(connection, f"SELECT COUNT(*) n FROM {table}")[0]["n"])
        if n:
            return False
    # Taxonomy v3 creates these seven core types before import. They are
    # reference vocabulary, like units; arbitrary/deleted/renamed tags still
    # make the target nonempty. Never delete target rows to permit an import.
    from source.server.admin_taxonomies import CORE_DISH_TYPES
    tags=_query(connection,"SELECT tag_type,code,label,normalized_label,is_core,deleted_at FROM recipe_tags")
    actual_tags=sorted((r['tag_type'],r['code'],r['label'],r['normalized_label'],bool(r['is_core']),r['deleted_at']) for r in tags)
    expected_tags=sorted(('dish_type',code,label,_norm(label),True,None) for code,label in CORE_DISH_TYPES.items())
    if actual_tags not in ([],expected_tags):
        return False
    # create_schema seeds this exact immutable reference vocabulary for Admin's
    # structured amount editor. It is not imported business data; permit either
    # an empty unit table (older TEST_ONLY schemas) or the exact standard seed.
    unit_rows = _query(connection, "SELECT code,name,dimension FROM units ORDER BY code")
    expected_units = sorted(STANDARD_UNITS)
    actual_units = sorted((row["code"], row["name"], row["dimension"]) for row in unit_rows)
    if actual_units not in ([], expected_units):
        return False
    return True


def _copy_test_images(images, target_db, *, source_root=None, target_root=None):
    """Verify source image bytes and copy them to an isolated TEST_ONLY root."""
    from source.web.recipe_images import safe_image_path, storage_root

    source_root = Path(source_root).resolve() if source_root else storage_root()
    runtime_root = ROOT / "statics" / "runtime"
    target_root = (Path(target_root).resolve() if target_root else
                   (runtime_root / "unified-test-images" / target_db).resolve())
    if target_root == source_root or source_root in target_root.parents or target_root in source_root.parents:
        raise UnifiedMigrationError("TEST_ONLY image storage must be separate from the source image root")
    target_root.mkdir(parents=True, exist_ok=True)
    copied, reused, created = 0, 0, []
    prepared = []
    try:
        from hashlib import sha256
        from PIL import Image
        for row in images:
            key = str(row["storage_key"])
            source_path = safe_image_path(source_root, key)
            try:
                data = source_path.read_bytes()
            except OSError as exc:
                raise UnifiedMigrationError(f"Image file for recipe {row['recipe_id']} is unavailable") from exc
            if len(data) != int(row["byte_size"]) or sha256(data).hexdigest() != str(row["sha256"]).lower():
                raise UnifiedMigrationError(f"Image bytes for recipe {row['recipe_id']} do not match stored metadata")
            try:
                with Image.open(source_path) as image:
                    fmt = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(image.format)
                    if (fmt != row["media_type"] or image.size != (int(row["width"]), int(row["height"]))):
                        raise UnifiedMigrationError(f"Image dimensions/type for recipe {row['recipe_id']} mismatch metadata")
                    image.verify()
            except UnifiedMigrationError:
                raise
            except Exception as exc:
                raise UnifiedMigrationError(f"Image file for recipe {row['recipe_id']} is invalid") from exc
            target_path = safe_image_path(target_root, key)
            if target_path.exists():
                if sha256(target_path.read_bytes()).hexdigest() != str(row["sha256"]).lower():
                    raise UnifiedMigrationError(f"TEST_ONLY image key collision for recipe {row['recipe_id']}")
                reused += 1
            else:
                # Exclusive create prevents overwriting an unrelated file.
                with target_path.open("xb") as stream:
                    stream.write(data)
                    stream.flush()
                created.append(target_path)
                copied += 1
            prepared.append({**row, "storage_key": key})
        return prepared, {"copied": copied, "reused": reused}, created
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def migrate(source, target, *, test_only=False, admin_username=None, admin_password_hash=None,
            source_image_root=None, target_image_root=None):
    """Convert a source snapshot in one target transaction; source is read-only."""
    source_db = _query(source, "SELECT DATABASE() db")[0]["db"]
    target_db = _query(target, "SELECT DATABASE() db")[0]["db"]
    if not test_only or not target_db or not str(target_db).endswith("_test") or source_db == target_db:
        raise UnifiedMigrationError("Conversion requires test_only=True and a separate target database ending in _test")
    snapshot = _source_snapshot(source)
    fingerprint = _fingerprint(snapshot, source_db)
    prior = _query(target, """SELECT run_id,status,report FROM unified_import_runs
        WHERE source_database=%s AND source_fingerprint=%s AND converter_version=%s""",
        (source_db,fingerprint,VERSION))
    if prior:
        return {"status":"NOOP_ALREADY_APPLIED","source_database":source_db,"target_database":target_db,
            "fingerprint":fingerprint,"report":prior[0]["report"]}
    if not _empty_target(target):
        raise UnifiedMigrationError("Target contains data but has no matching import marker; refusing duplicate/partial import")

    # Preserve the separate environment-configured Admin credential as a user
    # identity only when explicitly supplied by the caller. Never log the hash.
    accounts = list(snapshot["accounts"])
    if admin_username and admin_password_hash:
        normalized = _norm(admin_username)
        if any(row["normalized_username"] == normalized for row in accounts):
            raise UnifiedMigrationError("Configured Admin username conflicts with an existing account row")
        next_id = max((int(r["user_id"]) for r in accounts),default=0)+1
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        accounts.append({"user_id":next_id,"username":admin_username,"normalized_username":normalized,
            "password_hash":admin_password_hash,"role":"ADMIN","account_status":"ACTIVE",
            "created_at":now,"updated_at":now,"last_login_at":None})

    prepared_images, image_copy_report, created_image_files = _copy_test_images(
        snapshot["images"], target_db, source_root=source_image_root, target_root=target_image_root)

    report = {"TEST_ONLY":True,"source_database":source_db,"target_database":target_db,
        "source_fingerprint":fingerprint,"legacy_counts":snapshot["legacy_counts"],
        "recipe_count":len(snapshot["recipes"]),"ingredient_count":len(snapshot["ingredients"]),
        "public_recipe_count":len(snapshot["public_recipe_ids"]),
        "public_ingredient_count":len(snapshot["public_ingredient_ids"]),
        "account_count":len(accounts),"image_metadata_count":len(snapshot["images"]),
        "image_files":image_copy_report,
        "user_catalog_version":snapshot["catalog_version"]}
    target.start_transaction()
    try:
        for row in snapshot["ingredients"].values():
            _execute(target,"""INSERT INTO ingredients(ingredient_id,name,normalized_name,group_name,is_active)
                VALUES(%s,%s,%s,%s,%s)""",(row["ingredient_id"],row["name"],row["normalized_name"],
                row.get("group_name"),int(row["is_active"])))
        for source_kind,source_id,ingredient_id in snapshot["ingredient_maps"]:
            _execute(target,"INSERT INTO ingredient_id_map(source_kind,source_id,ingredient_id) VALUES(%s,%s,%s)",
                     (source_kind,source_id,ingredient_id))
        for iid,alias,normalized in snapshot["aliases"]:
            _execute(target,"INSERT INTO ingredient_aliases(ingredient_id,alias,normalized_alias) VALUES(%s,%s,%s)",
                     (iid,alias,normalized))
        for row in accounts:
            _execute(target,"""INSERT INTO users(user_id,username,normalized_username,password_hash,role,status,
                created_at,updated_at,last_login_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (row["user_id"],row["username"],row["normalized_username"],row["password_hash"],row["role"],
                 row["account_status"],row["created_at"],row["updated_at"],row["last_login_at"]))
        for rid,row in snapshot["recipes"].items():
            _execute(target,"""INSERT INTO recipes(recipe_id,title,normalized_title,description,role,minutes_total,
                minutes_prep,minutes_cook,servings,instructions_legacy,fallback_image_url,source_url,is_public,
                deleted_at,edit_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (rid,row["title"],row["normalized_title"],row["description"],row["role"],row["minutes_total"],
                 row["minutes_prep"],row["minutes_cook"],row["servings"],row["instructions_legacy"],
                 row["fallback_image_url"],row["source_url"],int(row["is_public"]),row["deleted_at"],row["edit_version"]))
            for line in snapshot["recipe_lines"].get(rid,[]):
                _execute(target,"""INSERT INTO recipe_ingredients(recipe_id,line_no,ingredient_id,quantity_text,
                    amount_kind,requirement) VALUES(%s,%s,%s,%s,'unknown',%s)""",
                    (rid,line["line_no"],line["ingredient_id"],line["quantity_text"],line["requirement"]))
            for step in _numbered_steps(row["instructions_legacy"]):
                _execute(target,"INSERT INTO recipe_steps(recipe_id,step_no,instruction) VALUES(%s,%s,%s)",
                         (rid,step["step_no"],step["instruction"]))
        tag_ids={}
        for _,tag_type,code,label in snapshot["tags"]:
            key=(tag_type,code)
            if key in tag_ids:continue
            existing=_query(target,"SELECT tag_id FROM recipe_tags WHERE tag_type=%s AND code=%s",key)
            if existing:tag_id=int(existing[0]["tag_id"])
            else:
                tag_id=_execute(target,"INSERT INTO recipe_tags(tag_type,code,label,normalized_label) VALUES(%s,%s,%s,%s)",
                    (tag_type,code,label,_norm(label)))[0]
            tag_ids[key]=tag_id
        for rid,tag_type,code,label in snapshot["tags"]:
            if rid in snapshot["recipes"]:
                _execute(target,"INSERT INTO recipe_tag_links(recipe_id,tag_id) VALUES(%s,%s)",(rid,tag_ids[(tag_type,code)]))
        # Core dish-type tags mirror the operational recipe role at import time;
        # additional Admin-selected dish types remain many-to-many metadata.
        _execute(target,"""INSERT IGNORE INTO recipe_tag_links(recipe_id,tag_id)
            SELECT r.recipe_id,t.tag_id FROM recipes r JOIN recipe_tags t
              ON t.tag_type='dish_type' AND t.code=r.role AND t.is_core=TRUE""")
        for source_kind,source_id,recipe_id in snapshot["recipe_maps"]:
            _execute(target,"INSERT INTO recipe_id_map(source_kind,source_id,recipe_id) VALUES(%s,%s,%s)",
                     (source_kind,source_id,recipe_id))
        for image in prepared_images:
            if int(image["recipe_id"]) not in snapshot["recipes"]:
                continue
            _execute(target,"""INSERT INTO recipe_images(recipe_id,storage_key,media_type,byte_size,width,height,sha256)
                VALUES(%s,%s,%s,%s,%s,%s,%s)""",(image["recipe_id"],image["storage_key"],image["media_type"],
                image["byte_size"],image["width"],image["height"],image["sha256"]))
        _execute(target,"""INSERT INTO unified_import_runs(source_database,source_fingerprint,converter_version,report)
            VALUES(%s,%s,%s,%s)""",(source_db,fingerprint,VERSION,json.dumps(report,ensure_ascii=False,default=str)))
        target.commit()
    except Exception:
        target.rollback()
        for path in created_image_files:
            path.unlink(missing_ok=True)
        raise
    return {"status":"APPLIED_TEST_ONLY","source_database":source_db,"target_database":target_db,
        "fingerprint":fingerprint,"report":report}


class UnifiedRepository:
    """Thin future TCP adapter preserving the existing recipe response shape."""
    def dataset_version(self, connection):
        rows=_query(connection,"SELECT source_fingerprint FROM unified_import_runs ORDER BY run_id DESC LIMIT 1")
        return "unified:"+(rows[0]["source_fingerprint"][:16] if rows else "empty")

    def list_ingredients(self, connection, query="", limit=100):
        needle=_norm(query)
        sql="SELECT ingredient_id AS id,name FROM ingredients WHERE is_active=1"
        rows=_query(connection,sql+" ORDER BY normalized_name,ingredient_id")
        if needle:rows=[r for r in rows if needle in _norm(r["name"])]
        return rows[:limit]

    def _visible_recipes(self, connection):
        return _query(connection,"SELECT recipe_id,title,minutes_total AS minutes,role FROM recipes WHERE is_public=1 AND deleted_at IS NULL ORDER BY recipe_id")

    def recipes_for_ranking(self, connection, *, include_drinks=False):
        recipes=[r for r in self._visible_recipes(connection) if include_drinks or r["role"]!="drink"]
        if not recipes:return []
        ids=[int(r["recipe_id"]) for r in recipes]
        marks=",".join(["%s"]*len(ids))
        lines=_query(connection,f"SELECT recipe_id,ingredient_id,requirement FROM recipe_ingredients WHERE recipe_id IN ({marks}) ORDER BY recipe_id,line_no",tuple(ids))
        grouped={rid:{"required_ids":set(),"all_ids":set()} for rid in ids}
        for row in lines:
            rid=int(row["recipe_id"]);iid=int(row["ingredient_id"])
            grouped[rid]["all_ids"].add(iid)
            if row["requirement"]=="required":grouped[rid]["required_ids"].add(iid)
        portion_rows=_query(connection,f"""SELECT r.recipe_id,r.servings,r.role,r.portion_data_status,COUNT(ri.line_no) AS line_count,
            SUM(CASE WHEN ri.amount_kind='exact' AND ri.amount_min>0 AND ri.amount_max=ri.amount_min
                AND u.code IS NOT NULL AND ri.measurement_basis IN ('gross','edible','prepared')
                AND ri.purpose IN ('main','seasoning','cooking_medium','garnish','unknown','consumed')
                AND ri.requirement IN ('required','optional','unknown') AND ri.scaling_mode IN ('linear','fixed')
                THEN 1 ELSE 0 END) AS complete_lines,
            SUM(CASE WHEN ri.requirement='required' AND (
                    (r.role='soup' AND ri.purpose='main' AND u.code IN ('ml','l'))
                    OR (r.role IN ('main','vegetable','side') AND ri.purpose='main'))
                THEN 1 ELSE 0 END) AS driver_lines,
            SUM(CASE WHEN ri.requirement='required' AND ri.amount_kind='exact' AND ri.amount_min>0
                AND ri.amount_max=ri.amount_min AND ri.measurement_basis='gross'
                AND ri.scaling_mode='linear' AND (
                    (r.role='soup' AND ri.purpose='main' AND u.code IN ('ml','l') AND u.dimension='volume')
                    OR (r.role IN ('main','vegetable','side') AND ri.purpose='main'
                        AND u.code IN ('g','kg') AND u.dimension='mass'))
                THEN 1 ELSE 0 END) AS valid_driver_lines
            FROM recipes r JOIN recipe_ingredients ri USING(recipe_id)
            LEFT JOIN units u USING(unit_id)
            WHERE r.recipe_id IN ({marks}) GROUP BY r.recipe_id,r.servings,r.role""",tuple(ids))
        portions={int(row["recipe_id"]):bool(row["servings"] is not None and row["servings"]>0
            and row["line_count"]>0 and row["line_count"]==row["complete_lines"]
            and row["driver_lines"]>0 and row["driver_lines"]==row["valid_driver_lines"]
            and row["portion_data_status"] in ("verified","estimated"))
            for row in portion_rows}
        portions_by_id={int(row["recipe_id"]):row for row in portion_rows}
        return [{"id":int(r["recipe_id"]),"title":r["title"],"minutes":int(r["minutes"]),
                 "portion_ready":portions.get(int(r["recipe_id"]),False),
                 "service_capacity":(str(portions_by_id[int(r["recipe_id"])]["servings"])
                    if int(r["recipe_id"]) in portions_by_id and portions_by_id[int(r["recipe_id"])]["portion_data_status"] in ("verified","estimated")
                    and portions_by_id[int(r["recipe_id"])]["servings"] is not None else None),
                 "service_capacity_status":(portions_by_id[int(r["recipe_id"])]["portion_data_status"]
                    if int(r["recipe_id"]) in portions_by_id else "needs_review"),
                 **grouped[int(r["recipe_id"])]} for r in recipes]

    def recipes_for_search(self, connection):
        rows=self.recipes_for_ranking(connection)
        names={int(r["id"]):r["name"] for r in self.list_ingredients(connection,"",10000)}
        return [{**row,"ingredient_names":[names[i] for i in sorted(row["all_ids"]) if i in names]} for row in rows]

    def get_recipe(self, connection, recipe_id):
        rows=_query(connection,"SELECT * FROM recipes WHERE recipe_id=%s AND is_public=1 AND deleted_at IS NULL",(recipe_id,))
        if not rows:return None
        recipe=rows[0]
        lines=_query(connection,"""SELECT ri.line_no,ri.ingredient_id,i.name,ri.quantity_text,ri.requirement
            FROM recipe_ingredients ri JOIN ingredients i USING(ingredient_id)
            WHERE ri.recipe_id=%s ORDER BY ri.line_no""",(recipe_id,))
        steps=_query(connection,"SELECT step_no,instruction FROM recipe_steps WHERE recipe_id=%s ORDER BY step_no",(recipe_id,))
        tags=_query(connection,"SELECT t.tag_type,t.code,t.label FROM recipe_tag_links l JOIN recipe_tags t USING(tag_id) WHERE l.recipe_id=%s ORDER BY t.tag_type,t.code",(recipe_id,))
        instructions="\n".join(f"Bước {r['step_no']}: {r['instruction']}" for r in steps) or recipe["instructions_legacy"] or ""
        return {"id":int(recipe_id),"title":recipe["title"],"description":recipe["description"],"role":recipe["role"],
            "servings":str(recipe["servings"]) if recipe["servings"] is not None else None,
            "minutes_prep":recipe["minutes_prep"],"minutes_cook":recipe["minutes_cook"],"tags":tags,
            "instructions":instructions,"minutes":int(recipe["minutes_total"]),
            "source_url":recipe["source_url"],"ingredients":[{"id":int(r["ingredient_id"]),"name":r["name"],
                "quantity":r["quantity_text"],"is_required":r["requirement"]=="required"} for r in lines]}

    def meal_classification(self, connection):
        from source.server.meal_plan import Classification,default_classification
        base=default_classification()
        roles={int(r["recipe_id"]):r["role"] for r in self._visible_recipes(connection)}
        return Classification("unified:"+base.version,{**base.categories,**roles})
