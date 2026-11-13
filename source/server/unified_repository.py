"""Runtime repository for the unified schema. TEST_ONLY databases only."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
import re
import unicodedata
import uuid

import mysql.connector

from source.common.catalog_ids import MAX_PUBLIC_ID, UINT32_MAX, V2_OFFSET, valid_public_id
from source.database.unified_catalog_migration import UnifiedRepository as UnifiedReadRepository, _hash, _norm, _query
from source.server.repository import (
    AdminDraftConflict, AdminIngredientConflict, AdminTaxonomyConflict, MySQLRepository,
    UserAccountConflict, UserAccountUnauthorized,
)


def _write(connection, sql, params=()):
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params)
        return cursor.rowcount, cursor.lastrowid
    finally:
        cursor.close()


class UnifiedMySQLRepository(MySQLRepository):
    """Single-source repository used only by an explicitly isolated v3 test DB."""
    unified_catalog_mode = True
    supports_repeated_recipe_ingredients = True

    def __init__(self, config, *, pool_size=4):
        database = config.get("database", "")
        if not str(database).endswith("_test"):
            raise RuntimeError("Unified schema mode requires a TEST_ONLY database ending in _test")
        host = str(config.get("host", "")).casefold()
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = host == "localhost"
        if not loopback:
            raise RuntimeError("Unified schema mode only permits a loopback MySQL TEST_ONLY instance")
        super().__init__(config, pool_size=pool_size)
        self.unified = UnifiedReadRepository()

    @classmethod
    def from_env(cls):
        from dotenv import load_dotenv
        from pathlib import Path
        load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
        required = ("UNIFIED_MYSQL_HOST", "UNIFIED_MYSQL_PORT", "UNIFIED_MYSQL_USER",
                    "UNIFIED_MYSQL_PASSWORD", "UNIFIED_MYSQL_DATABASE")
        missing = [name for name in required if os.getenv(name) is None]
        if missing:
            raise RuntimeError("Missing unified TEST_ONLY MySQL settings: " + ", ".join(missing))
        if os.getenv("UNIFIED_SCHEMA_MODE") != "1":
            raise RuntimeError("Set UNIFIED_SCHEMA_MODE=1 to opt into unified TEST_ONLY mode")
        try:
            port = int(os.environ["UNIFIED_MYSQL_PORT"])
            pool_size = int(os.getenv("UNIFIED_TCP_DB_POOL_SIZE", "4"))
        except ValueError:
            raise RuntimeError("Unified MySQL port and pool size must be integers") from None
        if not 1 <= port <= 65535 or not 1 <= pool_size <= 8:
            raise RuntimeError("Unified MySQL port or pool size is outside its allowed range")
        config = {"host": os.environ["UNIFIED_MYSQL_HOST"], "port": port,
                  "user": os.environ["UNIFIED_MYSQL_USER"], "password": os.environ["UNIFIED_MYSQL_PASSWORD"],
                  "database": os.environ["UNIFIED_MYSQL_DATABASE"], "charset": "utf8mb4",
                  "collation": "utf8mb4_unicode_ci", "connection_timeout": 5}
        return cls(config, pool_size=pool_size)

    def request_view(self, connection, operation):
        return self

    def dataset_version(self, connection):
        # Unlike the importer fingerprint, the serving token must advance when
        # Admin changes the live catalog. It is used by browsers to invalidate
        # saved ingredient selections and cached search/meal results.
        recipes = _query(connection, """SELECT recipe_id,edit_version,is_public,deleted_at
            FROM recipes ORDER BY recipe_id""")
        ingredients = _query(connection, """SELECT ingredient_id,name,normalized_name,is_active
            FROM ingredients ORDER BY ingredient_id""")
        images = _query(connection, "SELECT recipe_id,sha256 FROM recipe_images ORDER BY recipe_id")
        meal_tags = _query(connection, """SELECT l.recipe_id,t.tag_type,t.code
            FROM recipe_tag_links l JOIN recipe_tags t USING(tag_id)
            WHERE t.deleted_at IS NULL ORDER BY l.recipe_id,t.tag_type,t.code""")
        source = self.unified.dataset_version(connection)
        return "unified:" + _hash({"source": source, "recipes": recipes,
                                    "ingredients": ingredients, "images": images,
                                    "meal_tags": meal_tags})[:24]

    def recipes_for_ranking(self, connection):
        return self.unified.recipes_for_ranking(connection)

    def recipes_for_search(self, connection):
        return self.unified.recipes_for_search(connection)

    def list_ingredients(self, connection, query="", limit=100):
        return self.unified.list_ingredients(connection, query, limit)

    def get_recipe(self, connection, recipe_id):
        recipe = self.unified.get_recipe(connection, recipe_id)
        if recipe is not None:
            recipe["image_url"] = self._fallback_image(connection, recipe_id)
            header = _query(connection, "SELECT servings,minutes_prep,minutes_cook,minutes_total FROM recipes WHERE recipe_id=%s AND is_public=1 AND deleted_at IS NULL", (recipe_id,))
            if header:
                recipe["servings"] = str(header[0]["servings"]) if header[0]["servings"] is not None else None
                recipe["minutes_prep"] = header[0]["minutes_prep"]
                recipe["minutes_cook"] = header[0]["minutes_cook"]
                recipe["minutes"] = int(header[0]["minutes_total"])
            lines = _query(connection, """SELECT ri.line_no,ri.ingredient_id,ri.quantity_text,ri.requirement,
                ri.amount_kind,ri.amount_min,ri.amount_max,u.code AS unit_code,u.name AS unit_name,
                ri.ingredient_form,ri.measurement_basis,ri.purpose,ri.scaling_mode
                FROM recipe_ingredients ri LEFT JOIN units u USING(unit_id)
                WHERE ri.recipe_id=%s ORDER BY ri.line_no""", (recipe_id,))
            for item, line in zip(recipe["ingredients"], lines):
                quantity = item.get("quantity") or ""
                if not quantity and line["amount_kind"] in {"exact", "range"} and line["amount_min"] is not None and line["unit_name"]:
                    low = format(line["amount_min"].normalize(), "f") if hasattr(line["amount_min"], "normalize") else str(line["amount_min"])
                    high = format(line["amount_max"].normalize(), "f") if line["amount_max"] is not None and hasattr(line["amount_max"], "normalize") else (str(line["amount_max"]) if line["amount_max"] is not None else low)
                    quantity = (low if low == high else low + "–" + high) + " " + line["unit_name"]
                item["quantity"] = quantity
                item["is_required"] = line["requirement"] == "required"
                item.update({"line_no":int(line["line_no"]),"requirement":line["requirement"],
                    "amount_kind":line["amount_kind"],"amount_min":str(line["amount_min"]) if line["amount_min"] is not None else None,
                    "amount_max":str(line["amount_max"]) if line["amount_max"] is not None else None,
                    "unit_code":line["unit_code"],"unit_name":line["unit_name"],"ingredient_form":line["ingredient_form"],
                    "measurement_basis":line["measurement_basis"],"purpose":line["purpose"],"scaling_mode":line["scaling_mode"]})
            recipe["steps"] = _query(connection, "SELECT step_no,instruction,duration_minutes,heat_level FROM recipe_steps WHERE recipe_id=%s ORDER BY step_no", (recipe_id,))
        return recipe

    def recipe_ids_exist(self, connection, ids):
        if not ids:
            return True
        marks = ",".join(["%s"] * len(ids))
        count = _query(connection, f"SELECT COUNT(*) n FROM recipes WHERE recipe_id IN ({marks}) AND is_public=1 AND deleted_at IS NULL", tuple(ids))[0]["n"]
        return int(count) == len(set(ids))

    def ingredient_ids_exist(self, connection, ids):
        if not ids:
            return True
        marks = ",".join(["%s"] * len(ids))
        count = _query(connection, f"SELECT COUNT(*) n FROM ingredients WHERE ingredient_id IN ({marks}) AND is_active=1", tuple(ids))[0]["n"]
        return int(count) == len(set(ids))

    def public_recipe_image(self, connection, recipe_id):
        row = _query(connection, """SELECT i.storage_key,i.media_type,i.byte_size,i.width,i.height,i.sha256
            FROM recipes r JOIN recipe_images i ON i.recipe_id=r.recipe_id
            WHERE r.recipe_id=%s AND r.is_public=1 AND r.deleted_at IS NULL""", (recipe_id,))
        if not row:
            return None
        return self._image_data(row[0])

    def _fallback_image(self, connection, recipe_id):
        row = _query(connection, "SELECT fallback_image_url FROM recipes WHERE recipe_id=%s", (recipe_id,))
        if row and row[0]["fallback_image_url"]:
            return row[0]["fallback_image_url"]
        return None

    def calculation_catalog(self, connection, recipe_ids):
        """Read only structured quantities from the live unified catalog."""
        from source.server.meal_plan_calculation import Catalog, IngredientLine, Revision, Unit
        if not recipe_ids:
            return Catalog(available=False, unavailable_reason="STRUCTURED_PORTION_DATA_UNAVAILABLE",
                           trust_admin_catalog=True)
        marks = ",".join(["%s"] * len(recipe_ids))
        recipe_rows = _query(connection, f"""SELECT *
            FROM recipes WHERE recipe_id IN ({marks})""", tuple(recipe_ids))
        by_id = {int(row["recipe_id"]): row for row in recipe_rows}
        line_rows = _query(connection, f"""SELECT ri.recipe_id,ri.line_no,ri.ingredient_id,i.name,
            ri.ingredient_form,ri.amount_kind,ri.amount_min,ri.amount_max,u.code AS unit_code,
            u.name AS unit_name,u.dimension AS unit_dimension,
            ri.measurement_basis,ri.purpose,ri.requirement,ri.scaling_mode
            FROM recipe_ingredients ri JOIN ingredients i ON i.ingredient_id=ri.ingredient_id
            LEFT JOIN units u ON u.unit_id=ri.unit_id
            WHERE ri.recipe_id IN ({marks}) ORDER BY ri.recipe_id,ri.line_no""", tuple(recipe_ids))
        grouped = {rid: [] for rid in recipe_ids}
        units = {}
        for row in line_rows:
            code = row["unit_code"]
            if code:
                units[code] = Unit(code=code, dimension=row["unit_dimension"],
                                   definition=row["unit_name"] or code)
            purpose = row["purpose"]
            requirement = row["requirement"]
            grouped[int(row["recipe_id"])].append(IngredientLine(
                line_id=int(row["line_no"]), ingredient_id=int(row["ingredient_id"]), name=row["name"],
                ingredient_form=row["ingredient_form"], amount_kind=row["amount_kind"] or "unknown",
                amount_min=str(row["amount_min"]) if row["amount_min"] is not None else None,
                amount_max=str(row["amount_max"]) if row["amount_max"] is not None else None,
                unit=code, measurement_basis=row["measurement_basis"], purpose=purpose,
                requirement=requirement, scaling_mode=row["scaling_mode"]))
        revisions = {}
        for rid in recipe_ids:
            row = by_id.get(rid)
            if row is None or not row["is_public"] or row["deleted_at"] is not None:
                continue
            servings = row["servings"]
            revisions[rid] = Revision(recipe_id=rid, revision_id=int(row["edit_version"]),
                base_servings=str(servings) if servings is not None else None, serving_basis="source_servings",
                lines=tuple(grouped[rid]), content_complete=bool(grouped[rid]), role=row["role"] or "main",
                data_status=row.get("portion_data_status", "needs_review"), data_evidence=row.get("portion_data_evidence") or "")
        return Catalog(revisions=revisions, units=units, available=True, trust_admin_catalog=True)

    def admin_list_units(self, connection):
        rows = _query(connection, """SELECT unit_id,code,name,dimension,base_unit_id,factor_to_base
            FROM units ORDER BY dimension,name,unit_id""")
        return [{"unit_id": int(row["unit_id"]), "code": row["code"], "name": row["name"],
                 "dimension": row["dimension"],
                 "base_unit_id": int(row["base_unit_id"]) if row["base_unit_id"] is not None else None,
                 "factor_to_base": str(row["factor_to_base"]) if row["factor_to_base"] is not None else None}
                for row in rows]

    def meal_classification_for_connection(self, connection, classification):
        return self.unified.meal_classification(connection)

    def daily_prominent_ingredients(self, connection, recipe_ids):
        """Read recipe ingredient roles for daily pairing, without changing tags."""
        ids = sorted({int(recipe_id) for recipe_id in recipe_ids})
        if not ids:
            return {}
        marks = ",".join(["%s"] * len(ids))
        rows = _query(connection, f"""SELECT ri.recipe_id,ri.ingredient_id,i.name
            FROM recipe_ingredients ri JOIN ingredients i USING(ingredient_id)
            WHERE ri.recipe_id IN ({marks}) AND ri.purpose='main'
              AND ri.requirement='required'""", tuple(ids))
        # Some imported recipes call garlic/water 'main'. Ignore common cooking
        # adjuncts by ingredient identity, never by a substring in a dish title.
        adjuncts = {"muoi","duong","toi","hanh","hanh la","hanh tim","hanh kho","hanh tay",
            "gung","sa","ot","tieu","tieu den","nuoc","nuoc loc","nuoc soi",
            "nuoc lanh","nuoc mam","nuoc mam chay","nuoc tuong","xi dau",
            "dau an","dau me","hat nem","hat nem chay","bot ngot","bot canh"}
        result = {}
        for row in rows:
            name = "".join(c for c in unicodedata.normalize("NFD", row["name"].casefold().replace("đ","d"))
                           if unicodedata.category(c) != "Mn")
            if name.strip() not in adjuncts:
                result.setdefault(int(row["recipe_id"]), set()).add(int(row["ingredient_id"]))
        return result

    def meal_pairing_metadata(self, connection, recipe_ids):
        """Return only active Admin-managed pairing tags for the requested recipes."""
        ids = sorted({int(recipe_id) for recipe_id in recipe_ids})
        if not ids:
            return {}
        marks = ",".join(["%s"] * len(ids))
        rows = _query(connection, f"""SELECT l.recipe_id,t.tag_type,t.code
            FROM recipe_tag_links l JOIN recipe_tags t USING(tag_id)
            JOIN recipes r USING(recipe_id)
            WHERE l.recipe_id IN ({marks}) AND r.is_public=1 AND r.deleted_at IS NULL
              AND t.deleted_at IS NULL
              AND t.tag_type IN ('main_ingredient','cooking_method','dish_type','weather','occasion')
            ORDER BY l.recipe_id,t.tag_type,t.code""", tuple(ids))
        result = {}
        for row in rows:
            result.setdefault(int(row["recipe_id"]), {}).setdefault(row["tag_type"], set()).add(row["code"])
        return {recipe_id: {group: frozenset(codes) for group, codes in groups.items()}
                for recipe_id, groups in result.items()}

    def beverage_metadata(self, connection, recipe_ids):
        ids=sorted(set(recipe_ids))
        if not ids:return {}
        marks=','.join(['%s']*len(ids))
        rows=_query(connection,f"""SELECT l.recipe_id,t.tag_type,t.code FROM recipe_tag_links l
            JOIN recipe_tags t USING(tag_id) JOIN recipes r USING(recipe_id)
            WHERE r.role='drink' AND r.is_public=1 AND r.deleted_at IS NULL
            AND t.deleted_at IS NULL AND l.recipe_id IN ({marks})
            AND t.tag_type IN ('season','dish_type')""",tuple(ids))
        result={}
        for row in rows:result.setdefault(int(row['recipe_id']),{}).setdefault(row['tag_type'],set()).add(row['code'])
        return result

    def admin_list_taxonomies(self, connection, payload):
        from source.server.admin_taxonomies import GROUPS
        groups = sorted(GROUPS[payload["kind"]])
        marks = ",".join(["%s"] * len(groups))
        where = [f"t.tag_type IN ({marks})"]
        args = list(groups)
        if payload["group"] is not None:
            where.append("t.tag_type=%s")
            args.append(payload["group"])
        if payload["status"] == "active":
            where.append("t.deleted_at IS NULL")
        elif payload["status"] == "deleted":
            where.append("t.deleted_at IS NOT NULL")
        if payload["query"].strip():
            needle = f"%{payload['query'].strip().casefold()}%"
            where.append("(LOWER(t.label) LIKE %s OR LOWER(CONVERT(t.code USING utf8mb4)) LIKE %s OR LOWER(COALESCE(t.description,'')) LIKE %s)")
            args.extend((needle, needle, needle))
        clause = " WHERE " + " AND ".join(where)
        total = int(_query(connection, "SELECT COUNT(*) n FROM recipe_tags t" + clause, tuple(args))[0]["n"])
        rows = _query(connection, """SELECT t.tag_id,t.tag_type,t.code,t.label,t.description,t.is_core,t.deleted_at,
                COUNT(DISTINCT l.recipe_id) AS recipe_count
            FROM recipe_tags t LEFT JOIN recipe_tag_links l ON l.tag_id=t.tag_id""" + clause +
            " GROUP BY t.tag_id ORDER BY t.tag_type,t.normalized_label,t.tag_id LIMIT %s OFFSET %s",
            (*args, payload["limit"], payload["offset"]))
        return {"items": [{"tag_id": int(row["tag_id"]), "group": row["tag_type"], "code": row["code"],
            "label": row["label"], "description": row["description"] or "", "is_core": bool(row["is_core"]),
            "deleted": row["deleted_at"] is not None, "recipe_count": int(row["recipe_count"])} for row in rows],
            "total": total, "limit": payload["limit"], "offset": payload["offset"]}

    def admin_save_taxonomy(self, connection, payload):
        try:
            if "tag_id" in payload:
                rows = _query(connection, "SELECT tag_id,tag_type,code,is_core FROM recipe_tags WHERE tag_id=%s FOR UPDATE", (payload["tag_id"],))
                if not rows:
                    raise AdminTaxonomyConflict("taxonomy not found")
                row = rows[0]
                if (row["tag_type"], row["code"]) != (payload["group"], payload["code"]):
                    raise AdminTaxonomyConflict("taxonomy group and code cannot be changed after creation")
                _write(connection, "UPDATE recipe_tags SET label=%s,normalized_label=%s,description=%s WHERE tag_id=%s",
                    (payload["label"], _norm(payload["label"]), payload["description"] or None, payload["tag_id"]))
                tag_id = int(payload["tag_id"])
            else:
                duplicate = _query(connection,"SELECT tag_id FROM recipe_tags WHERE tag_type=%s AND code=%s FOR UPDATE",
                                   (payload["group"],payload["code"]))
                if duplicate:
                    raise AdminTaxonomyConflict("a taxonomy with this group and code already exists")
                _, tag_id = _write(connection, """INSERT INTO recipe_tags(tag_type,code,label,normalized_label,description)
                    VALUES(%s,%s,%s,%s,%s)""", (payload["group"], payload["code"], payload["label"],
                    _norm(payload["label"]), payload["description"] or None))
            connection.commit()
            return {"tag_id": int(tag_id), "group": payload["group"], "code": payload["code"],
                    "label": payload["label"], "description": payload["description"]}
        except Exception:
            connection.rollback()
            raise

    def admin_set_taxonomy_deleted(self, connection, payload):
        try:
            rows = _query(connection, "SELECT tag_id,is_core FROM recipe_tags WHERE tag_id=%s FOR UPDATE", (payload["tag_id"],))
            if not rows:
                raise AdminTaxonomyConflict("taxonomy not found")
            if payload["deleted"] and rows[0]["is_core"]:
                raise AdminTaxonomyConflict("core dish types cannot be deleted")
            _write(connection, "UPDATE recipe_tags SET deleted_at=IF(%s,CURRENT_TIMESTAMP(6),NULL) WHERE tag_id=%s",
                   (payload["deleted"], payload["tag_id"]))
            connection.commit()
            return {"tag_id": payload["tag_id"], "deleted": payload["deleted"]}
        except Exception:
            connection.rollback()
            raise

    def admin_delete_taxonomy_permanent(self, connection, tag_id):
        try:
            rows = _query(connection, "SELECT tag_id,is_core FROM recipe_tags WHERE tag_id=%s FOR UPDATE", (tag_id,))
            if not rows:
                raise AdminTaxonomyConflict("taxonomy not found")
            if rows[0]["is_core"]:
                raise AdminTaxonomyConflict("core dish types cannot be deleted")
            count = int(_query(connection, "SELECT COUNT(*) n FROM recipe_tag_links WHERE tag_id=%s", (tag_id,))[0]["n"])
            if count:
                raise AdminTaxonomyConflict(f"taxonomy is still assigned to {count} recipe(s)")
            _write(connection, "DELETE FROM recipe_tags WHERE tag_id=%s", (tag_id,))
            connection.commit()
            return {"tag_id": tag_id, "deleted_permanently": True}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno in (1451, 1452):
                raise AdminTaxonomyConflict("taxonomy still has recipe links; no recipe was changed") from exc
            raise
        except Exception:
            connection.rollback()
            raise

    def admin_get_recipe_taxonomies(self, connection, recipe_id, kind):
        from source.server.admin_taxonomies import GROUPS
        if not _query(connection, "SELECT recipe_id FROM recipes WHERE recipe_id=%s", (recipe_id,)):
            return None
        groups = sorted(GROUPS[kind])
        marks = ",".join(["%s"] * len(groups))
        rows = _query(connection, f"""SELECT t.tag_id,t.tag_type,t.code,t.label,t.description,t.is_core,t.deleted_at,
                (l.recipe_id IS NOT NULL) AS selected
            FROM recipe_tags t LEFT JOIN recipe_tag_links l ON l.tag_id=t.tag_id AND l.recipe_id=%s
            WHERE t.tag_type IN ({marks}) ORDER BY t.tag_type,t.normalized_label,t.tag_id""",
            (recipe_id, *groups))
        return {"recipe_id": recipe_id, "items": [{"tag_id": int(row["tag_id"]), "group": row["tag_type"],
            "code": row["code"], "label": row["label"], "description": row["description"] or "",
            "is_core": bool(row["is_core"]), "deleted": row["deleted_at"] is not None,
            "selected": bool(row["selected"])} for row in rows]}

    def admin_set_recipe_taxonomies(self, connection, payload):
        from source.server.admin_taxonomies import GROUPS
        try:
            recipes = _query(connection, "SELECT recipe_id FROM recipes WHERE recipe_id=%s FOR UPDATE", (payload["recipe_id"],))
            if not recipes:
                raise AdminTaxonomyConflict("recipe not found")
            groups = sorted(GROUPS[payload["kind"]])
            marks = ",".join(["%s"] * len(groups))
            existing = _query(connection, f"""SELECT t.tag_id,t.tag_type,t.deleted_at
                FROM recipe_tags t JOIN recipe_tag_links l USING(tag_id)
                WHERE l.recipe_id=%s AND t.tag_type IN ({marks}) FOR UPDATE""",
                (payload["recipe_id"], *groups))
            rows = []
            if payload["tag_ids"]:
                ids = payload["tag_ids"]
                id_marks = ",".join(["%s"] * len(ids))
                rows = _query(connection, f"SELECT tag_id,tag_type,deleted_at FROM recipe_tags WHERE tag_id IN ({id_marks}) FOR UPDATE", tuple(ids))
                by_id = {int(row["tag_id"]): row for row in rows}
                current_ids = {int(row["tag_id"]) for row in existing}
                if (set(by_id) != set(ids) or any(row["tag_type"] not in groups for row in rows)
                        or any(row["deleted_at"] is not None and tag_id not in current_ids for tag_id, row in by_id.items())):
                    raise AdminTaxonomyConflict("only active classifications can be assigned to recipes")
            _write(connection, f"""DELETE l FROM recipe_tag_links l JOIN recipe_tags t USING(tag_id)
                WHERE l.recipe_id=%s AND t.tag_type IN ({marks})""", (payload["recipe_id"], *groups))
            for tag_id in payload["tag_ids"]:
                _write(connection, "INSERT INTO recipe_tag_links(recipe_id,tag_id) VALUES(%s,%s)", (payload["recipe_id"], tag_id))
            connection.commit()
            return {"recipe_id": payload["recipe_id"], "kind": payload["kind"], "tag_ids": payload["tag_ids"]}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno in (1451, 1452):
                raise AdminTaxonomyConflict("recipe or classification was changed; reload and retry") from exc
            raise
        except Exception:
            connection.rollback()
            raise

    def meal_preference_catalog(self, connection, recipes, classification):
        from source.server.meal_preferences import load
        from dataclasses import replace
        from hashlib import sha256
        import json
        import re
        import unicodedata
        names = {int(row["ingredient_id"]): row["name"] for row in _query(connection,
            "SELECT ingredient_id,name FROM ingredients")}
        details = [self.unified.get_recipe(connection, int(row["id"])) for row in recipes]
        base=load(recipes, names, classification, [row for row in details if row is not None])
        rows=_query(connection,"""SELECT l.recipe_id,t.tag_type,t.code,r.source_url FROM recipe_tag_links l
            JOIN recipe_tags t USING(tag_id) JOIN recipes r USING(recipe_id)
            WHERE r.is_public=1 AND r.deleted_at IS NULL AND t.deleted_at IS NULL
              AND t.tag_type IN ('diet','region','occasion')
            ORDER BY t.tag_type,t.code,l.recipe_id""")
        contexts={group:{code:frozenset(ids) for code,ids in codes.items()} for group,codes in base.contexts.items()}
        assessments=dict(base.vegetarian_assessments)
        detail_by_id={int(row["id"]):row for row in details if row is not None}
        animal_names={
            "thit","ca basa","thit ga","cua dong","tom","muc","thit bo","thit heo xay","suon heo",
        }
        animal_ids={int(row["ingredient_id"]) for row in _query(connection,
            "SELECT ingredient_id,name FROM ingredients")
            if self._fold_meal_ingredient(row["name"]) in animal_names}
        for row in rows:
            if row["tag_type"] != "diet" or row["code"] != "vegetarian":
                continue
            rid=int(row["recipe_id"])
            recipe=detail_by_id.get(rid)
            lines=recipe.get("ingredients",[]) if recipe else []
            if not recipe or not isinstance(lines,list) or not lines:
                assessments[rid]={"status":"NEEDS_VERIFICATION","reasons":["Công thức thiếu danh sách thành phần."]}
                continue
            blocked=[]
            for line in lines:
                ingredient_id=int(line.get("id",0))
                name=self._fold_meal_ingredient(line.get("name",""))
                is_plant_labeled=(name.endswith(" chay") or name.startswith("chay "))
                animal_word=any(re.search(rf"(?:^| ){re.escape(term)}(?: |$)",name) for term in (
                    "thit","ca basa","ca hoi","ca ngu","ca loc","ca thu","ca trich","ca ro","ca chim","ca cam",
                    "tom","muc","cua","ngheu","ngao","oc","trung","sua",
                    "mo heo","mo dong vat","nuoc mam","mam tom","mam ruoc","bo","phomai",
                ))
                animal_word = animal_word or name == "ca"
                if is_plant_labeled:
                    animal_word = False
                ambiguous_condiment=any(term in name for term in ("dau hao","hat nem","sa te")) and not is_plant_labeled
                if ingredient_id in animal_ids or animal_word or ambiguous_condiment:
                    blocked.append(line.get("name") or str(ingredient_id))
            if blocked:
                assessments[rid]={"status":"NEEDS_VERIFICATION","reasons":["Có thành phần động vật hoặc gia vị chưa rõ: "+", ".join(blocked[:8])]}
            else:
                assessments[rid]={"status":"VERIFIED","reasons":[],
                                  **({"evidence_ref":row["source_url"]} if row.get("source_url") else {})}
        contexts.setdefault("diet",{})
        for row in rows:
            if row["tag_type"] in ("region","occasion"):
                contexts.setdefault(row["tag_type"],{}).setdefault(row["code"],set()).add(int(row["recipe_id"]))
        contexts={group:{code:frozenset(ids) for code,ids in codes.items()} for group,codes in contexts.items()}
        digest=sha256(json.dumps(rows,sort_keys=True,ensure_ascii=True,default=str).encode()).hexdigest()[:16]
        return replace(base,version=base.version+":v3tags:"+digest,contexts=contexts,
                       vegetarian_assessments=assessments)

    @staticmethod
    def _fold_meal_ingredient(value):
        text=unicodedata.normalize("NFD",str(value or "").casefold())
        text="".join(char for char in text if unicodedata.category(char)!="Mn")
        text=text.replace("\u0111","d")
        return re.sub(r"\s+"," ",text).strip()

    # User accounts use the same unified table and existing PBKDF2/token code.
    def user_register(self, payload):
        from source.server.user_accounts import hash_password
        from source.common.user_tokens import issue
        connection = self.connect()
        try:
            connection.start_transaction()
            cursor = connection.cursor()
            cursor.execute("INSERT INTO users(username,normalized_username,password_hash,role,status) VALUES(%s,%s,%s,'USER','ACTIVE')",
                           (payload["username"], payload["normalized_username"], hash_password(payload["password"])))
            user_id = int(cursor.lastrowid)
            connection.commit()
            token, claims = issue(user_id, payload["username"], "USER")
            return {"user_id": str(user_id), "username": payload["username"], "role": "USER",
                    "session_token": token, "csrf_token": claims["csrf"]}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise UserAccountConflict("username is already registered") from None
            raise
        finally:
            connection.close()

    def user_login(self, payload):
        from source.server.user_accounts import verify_password
        from source.common.user_tokens import issue
        connection = self.connect()
        try:
            connection.start_transaction()
            cursor = connection.cursor()
            cursor.execute("SELECT user_id,username,password_hash,role,status FROM users WHERE normalized_username=%s FOR UPDATE",
                           (payload["normalized_username"],))
            row = cursor.fetchone()
            if not row or not verify_password(payload["password"], row[2]):
                raise UserAccountUnauthorized("invalid username or password")
            if row[4] != "ACTIVE":
                raise UserAccountUnauthorized("account is locked")
            cursor.execute("UPDATE users SET last_login_at=UTC_TIMESTAMP(6) WHERE user_id=%s", (row[0],))
            connection.commit()
            token, claims = issue(int(row[0]), row[1], row[3])
            return {"user_id": str(row[0]), "username": row[1], "role": row[3],
                    "session_token": token, "csrf_token": claims["csrf"]}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def user_session(self, claims):
        connection = self.connect()
        try:
            rows = _query(connection, "SELECT username,role,status FROM users WHERE user_id=%s", (claims["uid"],))
            if not rows or rows[0]["username"] != claims["sub"] or rows[0]["role"] != claims["role"] or rows[0]["status"] != "ACTIVE":
                raise UserAccountUnauthorized("account is locked or no longer available")
            return {"user_id": str(claims["uid"]), "username": claims["sub"], "role": claims["role"], "csrf_token": claims["csrf"]}
        finally:
            connection.close()

    def admin_dashboard(self, connection):
        return {"recipes_total": int(_query(connection, "SELECT COUNT(*) n FROM recipes")[0]["n"]),
                "ingredients_total": int(_query(connection, "SELECT COUNT(*) n FROM ingredients")[0]["n"]),
                "users_total": int(_query(connection, "SELECT COUNT(*) n FROM users")[0]["n"]),
                "published_total": int(_query(connection, "SELECT COUNT(*) n FROM recipes WHERE is_public=1 AND deleted_at IS NULL")[0]["n"]),
                "revisions_total": 0, "draft_revisions": 0, "needs_verification_revisions": 0,
                "approved_revisions": 0, "draft_write_ready": True, "recipe_catalog_ready": True,
                "review_write_ready": False, "ingredient_admin_ready": True,
                "legacy_recipe_overlay_ready": True, "legacy_recipe_shared_ingredient_ready": True,
                "account_admin_ready": True, "image_upload_ready": True}

    def admin_list_ingredients(self, connection, query, limit=20, offset=0, active_only=False, catalog="shared", status="all"):
        needle = _norm(query.strip())
        sql = "SELECT ingredient_id,name,normalized_name,is_active FROM ingredients"
        conditions, args = [], []
        if status == "active" or active_only:
            conditions.append("is_active=1")
        elif status == "inactive":
            conditions.append("is_active=0")
        if needle:
            conditions.append("normalized_name LIKE %s")
            args.append("%" + needle.replace("%", "\\%").replace("_", "\\_") + "%")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        all_rows = _query(connection, sql + " ORDER BY normalized_name,ingredient_id", tuple(args))
        items = []
        for row in all_rows[offset:offset+limit]:
            ingredient_id = int(row["ingredient_id"])
            usage_count = self._ingredient_usage(connection, ingredient_id)
            mapped = bool(_query(connection, "SELECT 1 FROM ingredient_id_map WHERE ingredient_id=%s LIMIT 1", (ingredient_id,)))
            can_permanently_delete = not bool(row["is_active"]) and usage_count == 0 and not mapped
            if row["is_active"]:
                delete_block_reason = "Nguyên liệu vẫn đang sử dụng; hãy ngừng sử dụng trước khi xóa vĩnh viễn."
            elif usage_count:
                delete_block_reason = f"Nguyên liệu còn được {usage_count} công thức tham chiếu."
            elif mapped:
                delete_block_reason = "Nguyên liệu có ánh xạ định danh cần giữ để bảo toàn dữ liệu."
            else:
                delete_block_reason = None
            items.append({"ingredient_id": ingredient_id, "name": row["name"],
                          "normalized_name": row["normalized_name"], "is_active": bool(row["is_active"]),
                          "usage_count": usage_count,
                          "can_permanently_delete": can_permanently_delete,
                          "permanent_delete_block_reason": delete_block_reason,
                          "can_edit": True, "can_manage": True})
        return {"items": items,
                "total": len(all_rows), "limit": limit, "offset": offset, "catalog": "shared",
                "ingredient_admin_ready": True, "legacy_ingredient_admin_ready": True}

    def _ingredient_usage(self, connection, ingredient_id):
        return int(_query(connection, "SELECT COUNT(DISTINCT recipe_id) n FROM recipe_ingredients WHERE ingredient_id=%s", (ingredient_id,))[0]["n"])

    def admin_create_ingredient(self, payload):
        connection = self.connect()
        try:
            connection.start_transaction()
            duplicate = _query(connection, "SELECT ingredient_id FROM ingredients WHERE normalized_name=%s FOR UPDATE", (payload["normalized_name"],))
            if duplicate:
                raise AdminIngredientConflict("an ingredient with this normalized name already exists")
            cursor = connection.cursor()
            cursor.execute("INSERT INTO ingredients(name,normalized_name,is_active) VALUES(%s,%s,1)",
                           (payload["name"], payload["normalized_name"]))
            ingredient_id = int(cursor.lastrowid)
            connection.commit()
            return {"ingredient_id": ingredient_id, "name": payload["name"], "is_active": True}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def admin_update_ingredient(self, payload):
        connection = self.connect()
        try:
            connection.start_transaction()
            row = _query(connection, "SELECT ingredient_id FROM ingredients WHERE ingredient_id=%s FOR UPDATE", (payload["ingredient_id"],))
            if not row:
                raise AdminIngredientConflict("ingredient not found")
            duplicate = _query(connection, "SELECT ingredient_id FROM ingredients WHERE normalized_name=%s AND ingredient_id<>%s FOR UPDATE",
                               (payload["normalized_name"], payload["ingredient_id"]))
            if duplicate:
                raise AdminIngredientConflict("an ingredient with this normalized name already exists")
            # A valid catalog edit is immediately available on User in v3.
            # Deactivation remains a separate explicit Admin operation.
            _write(connection, "UPDATE ingredients SET name=%s,normalized_name=%s,is_active=1 WHERE ingredient_id=%s",
                   (payload["name"], payload["normalized_name"], payload["ingredient_id"]))
            connection.commit()
            return {"ingredient_id": payload["ingredient_id"], "name": payload["name"],
                    "is_active": True}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def admin_set_ingredient_active(self, payload):
        connection = self.connect()
        try:
            connection.start_transaction()
            rows = _query(connection, "SELECT ingredient_id FROM ingredients WHERE ingredient_id=%s FOR UPDATE", (payload["ingredient_id"],))
            if not rows:
                raise AdminIngredientConflict("ingredient not found")
            _write(connection, "UPDATE ingredients SET is_active=%s WHERE ingredient_id=%s", (int(payload["is_active"]), payload["ingredient_id"]))
            connection.commit()
            return {"ingredient_id": payload["ingredient_id"], "is_active": payload["is_active"]}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def admin_update_legacy_ingredient(self, payload, author):
        connection = self.connect()
        try:
            connection.start_transaction()
            row = _query(connection, "SELECT ingredient_id,is_active FROM ingredients WHERE ingredient_id=%s FOR UPDATE", (payload["ingredient_id"],))
            if not row:
                raise AdminIngredientConflict("ingredient not found")
            duplicate = _query(connection, "SELECT ingredient_id FROM ingredients WHERE normalized_name=%s AND ingredient_id<>%s FOR UPDATE",
                               (payload["normalized_name"], payload["ingredient_id"]))
            if duplicate:
                raise AdminIngredientConflict("an ingredient with this normalized name already exists")
            _write(connection, "UPDATE ingredients SET name=%s,normalized_name=%s WHERE ingredient_id=%s",
                   (payload["name"], payload["normalized_name"], payload["ingredient_id"]))
            connection.commit()
            return {"ingredient_id": payload["ingredient_id"], "name": payload["name"],
                    "source": "UNIFIED", "is_active": bool(row[0]["is_active"])}
        except Exception:
            connection.rollback(); raise
        finally: connection.close()

    def admin_set_legacy_ingredient_active(self, payload, author):
        result = self.admin_set_ingredient_active(payload)
        return {**result, "source": "UNIFIED"}

    def admin_list_recipes(self, connection, query, limit, offset, *, role=None, visibility=None, max_minutes=None, portion_filter=None):
        needle = _norm(query.strip())
        sql = "SELECT recipe_id,title,role,minutes_total,is_public,deleted_at,edit_version FROM recipes"
        conditions, args = [], []
        if needle:
            conditions.append("normalized_title LIKE %s")
            args.append("%" + needle.replace("%", "\\%").replace("_", "\\_") + "%")
        if role:
            conditions.append("role=%s"); args.append(role)
        if max_minutes:
            conditions.append("minutes_total<=%s"); args.append(max_minutes)
        if portion_filter in {"verified", "estimated", "needs_review"}:
            conditions.append("portion_data_status=%s"); args.append(portion_filter)
        elif portion_filter in {"missing", "structured"}:
            ready = """(servings>0 AND EXISTS(SELECT 1 FROM recipe_ingredients pi WHERE pi.recipe_id=recipes.recipe_id)
                AND NOT EXISTS(SELECT 1 FROM recipe_ingredients pi WHERE pi.recipe_id=recipes.recipe_id
                AND (pi.amount_min IS NULL OR pi.unit_id IS NULL OR pi.measurement_basis='unknown'
                OR pi.purpose='unknown' OR pi.scaling_mode='unknown')))"""
            conditions.append(ready if portion_filter == "structured" else "NOT COALESCE("+ready+",0)")
        if visibility == "visible": conditions.append("is_public=1 AND deleted_at IS NULL")
        elif visibility == "hidden": conditions.append("is_public=0 AND deleted_at IS NULL")
        elif visibility == "deleted": conditions.append("deleted_at IS NOT NULL")
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        total = int(_query(connection, "SELECT COUNT(*) n FROM recipes" + where, tuple(args))[0]["n"])
        rows = _query(connection, sql + where + " ORDER BY recipe_id LIMIT %s OFFSET %s", (*args, limit, offset))
        recipe_ids = [int(row["recipe_id"]) for row in rows]
        mapped_ids, achievement_counts = set(), {}
        if recipe_ids:
            marks = ",".join(["%s"] * len(recipe_ids))
            mapped_ids = {int(item["recipe_id"]) for item in _query(
                connection, f"SELECT recipe_id FROM recipe_id_map WHERE recipe_id IN ({marks})", tuple(recipe_ids))}
            count_rows = _query(connection, f"""SELECT p.recipe_id,
                    COUNT(DISTINCT p.post_id) AS post_count,
                    COUNT(DISTINCT c.comment_id) AS comment_count,
                    COUNT(DISTINCT i.image_id) AS image_count
                FROM achievement_posts p
                LEFT JOIN achievement_comments c ON c.post_id=p.post_id
                LEFT JOIN achievement_images i ON i.post_id=p.post_id
                WHERE p.recipe_id IN ({marks})
                GROUP BY p.recipe_id""", tuple(recipe_ids))
            achievement_counts = {int(item["recipe_id"]): item for item in count_rows}
        items = []
        for row in rows:
            rid = int(row["recipe_id"])
            deleted = row["deleted_at"] is not None
            counts = achievement_counts.get(rid, {})
            items.append({"recipe_id": rid, "title": row["title"], "role": row["role"],
                          "minutes": int(row["minutes_total"]), "visible": bool(row["is_public"]),
                          "deleted": deleted, "legacy": rid <= UINT32_MAX,
                          "can_permanently_delete": deleted,
                          "permanent_delete_block_reason": None,
                          "has_identity_mapping": rid in mapped_ids,
                          "achievement_post_count": int(counts.get("post_count", 0)),
                          "achievement_comment_count": int(counts.get("comment_count", 0)),
                          "achievement_image_count": int(counts.get("image_count", 0)),
                          "has_override": True, "status": "PUBLISHED" if row["is_public"] else "HIDDEN",
                          "revision_no": int(row["edit_version"]), "revision_id": rid,
                          "edit_revision_id": rid, "edit_version": self._version(connection, rid)})
        return {"items": items, "total": total, "limit": limit, "offset": offset,
                "legacy_overlay_ready": True, "recipe_catalog_ready": True}

    def _recipe_rows(self, connection, recipe_id):
        rows = _query(connection, "SELECT * FROM recipes WHERE recipe_id=%s", (recipe_id,))
        if not rows:
            return None, []
        lines = _query(connection, """SELECT ri.line_no,ri.ingredient_id,i.name,ri.quantity_text,ri.requirement,
            ri.amount_kind,ri.amount_min,ri.amount_max,ri.unit_id,u.code AS unit_code,u.name AS unit_name,
            ri.purpose,ri.ingredient_form,ri.measurement_basis,ri.scaling_mode
            FROM recipe_ingredients ri JOIN ingredients i USING(ingredient_id)
            LEFT JOIN units u USING(unit_id)
            WHERE ri.recipe_id=%s ORDER BY ri.line_no""", (recipe_id,))
        return rows[0], lines

    def _version(self, connection, recipe_id):
        row, lines = self._recipe_rows(connection, recipe_id)
        if row is None:
            return None
        steps = _query(connection, "SELECT step_no,instruction,duration_minutes,heat_level FROM recipe_steps WHERE recipe_id=%s ORDER BY step_no", (recipe_id,))
        tags=_query(connection,"SELECT t.tag_type,t.code FROM recipe_tag_links l JOIN recipe_tags t USING(tag_id) WHERE l.recipe_id=%s AND t.deleted_at IS NULL ORDER BY t.tag_type,t.code",(recipe_id,))
        return _hash({"recipe": {key: row[key] for key in ("recipe_id", "title", "description", "role", "minutes_total", "minutes_prep", "minutes_cook", "servings", "instructions_legacy", "fallback_image_url", "source_url", "is_public", "deleted_at", "edit_version")},
                      "lines": [{key: line[key] for key in ("line_no", "ingredient_id", "name", "quantity_text", "requirement", "amount_kind", "amount_min", "amount_max", "unit_id", "unit_code", "purpose", "ingredient_form", "measurement_basis", "scaling_mode")} for line in lines],
                      "steps": steps,"tags":tags,"portion_review": [row.get("portion_data_status"), row.get("portion_data_evidence")]})

    def _record_history(self, connection, recipe_id):
        row, lines = self._recipe_rows(connection, recipe_id)
        if row is None:
            return
        snapshot = {
            "recipe": {key: row[key] for key in (
                "title", "normalized_title", "description", "role", "minutes_total",
                "minutes_prep", "minutes_cook", "servings", "instructions_legacy",
                "fallback_image_url", "source_url", "is_public", "deleted_at", "edit_version")},
            "ingredients": [{key: line[key] for key in (
                "line_no", "ingredient_id", "name", "quantity_text", "requirement", "amount_kind",
                "amount_min", "amount_max", "unit_id", "purpose", "ingredient_form", "measurement_basis", "scaling_mode")}
                for line in lines],
            "steps": _query(connection, "SELECT step_no,instruction,duration_minutes,heat_level FROM recipe_steps WHERE recipe_id=%s ORDER BY step_no", (recipe_id,)),
        }
        snapshot["portion_review"] = {"status":row.get("portion_data_status", "needs_review"), "evidence":row.get("portion_data_evidence") or ""}
        image = _query(connection, "SELECT storage_key,media_type,byte_size,width,height,sha256 FROM recipe_images WHERE recipe_id=%s", (recipe_id,))
        snapshot["image"] = image[0] if image else None
        _write(connection, """INSERT INTO recipe_edit_history(recipe_id,edit_version,actor_user_id,snapshot)
            VALUES(%s,%s,NULL,%s)""", (recipe_id, int(row["edit_version"]),
                                           json.dumps(snapshot, ensure_ascii=False, default=str)))

    def admin_get_recipe(self, connection, recipe_id):
        return self._admin_recipe_detail(connection, recipe_id)

    def _admin_recipe_detail(self, connection, recipe_id):
        row, lines = self._recipe_rows(connection, recipe_id)
        if row is None:
            return None
        tags=_query(connection,"SELECT t.tag_type,t.code FROM recipe_tag_links l JOIN recipe_tags t USING(tag_id) WHERE l.recipe_id=%s ORDER BY t.tag_type,t.code",(recipe_id,))
        return {"recipe_id": int(recipe_id), "revision_id": int(recipe_id), "revision_no": int(row["edit_version"]),
                "title": row["title"], "description": row["description"], "instructions": row["instructions_legacy"] or "",
                "minutes": int(row["minutes_total"]), "minutes_prep": row["minutes_prep"],
                "minutes_cook": row["minutes_cook"], "servings": str(row["servings"]) if row["servings"] is not None else None,
                "role": row["role"], "source_url":row["source_url"], "tags":tags,
                "portion_data_status": row.get("portion_data_status", "needs_review"),
                "portion_data_evidence": row.get("portion_data_evidence") or "",
                "status": "PUBLISHED" if row["is_public"] else "HIDDEN",
                "content_complete": True, "edit_version": self._version(connection, recipe_id),
                "ingredients": [{"line_no": int(line["line_no"]), "ingredient_id": int(line["ingredient_id"]),
                    "id": int(line["ingredient_id"]), "name": line["name"], "quantity_raw": line["quantity_text"],
                    "quantity": line["quantity_text"], "requirement": line["requirement"],
                    "amount_kind": line["amount_kind"], "amount_min": str(line["amount_min"]) if line["amount_min"] is not None else None,
                    "amount_max": str(line["amount_max"]) if line["amount_max"] is not None else None,
                    "unit_id": int(line["unit_id"]) if line["unit_id"] is not None else None,
                    "unit_code": line["unit_code"], "unit_name": line["unit_name"],
                    "ingredient_form": line["ingredient_form"], "measurement_basis": line["measurement_basis"],
                    "purpose": line["purpose"], "scaling_mode": line["scaling_mode"], "status": "CURRENT"}
                    for line in lines], "evidence": [], "published": bool(row["is_public"]), "visible": bool(row["is_public"]),
                "deleted": row["deleted_at"] is not None, "is_visible": bool(row["is_public"]),
                "candidate_release_id": None,
                "steps": _query(connection, "SELECT step_no,instruction,duration_minutes,heat_level FROM recipe_steps WHERE recipe_id=%s ORDER BY step_no", (recipe_id,))}

    def admin_get_legacy_recipe(self, connection, recipe_id):
        return self._admin_recipe_detail(connection, recipe_id)

    def _insert_lines(self, connection, recipe_id, ingredients, previous_lines=()):
        previous_by_no = {int(line["line_no"]): line for line in previous_lines}
        for line_no, line in enumerate(ingredients, 1):
            ingredient_id = int(line["ingredient_id"])
            exists = _query(connection, "SELECT ingredient_id FROM ingredients WHERE ingredient_id=%s AND is_active=1 FOR UPDATE", (ingredient_id,))
            if not exists:
                raise ValueError("ingredient is not active in the shared catalog")
            quantity = line.get("quantity_raw", line.get("quantity")) or ""
            previous = previous_by_no.get(line_no)
            keep_structure = bool(previous and int(previous["ingredient_id"]) == ingredient_id
                                  and (previous["quantity_text"] or "") == quantity)
            structure = {
                "amount_kind": line.get("amount_kind", previous["amount_kind"] if keep_structure else "unknown"),
                "amount_min": line.get("amount_min", previous["amount_min"] if keep_structure else None),
                "amount_max": line.get("amount_max", previous["amount_max"] if keep_structure else None),
                "unit_id": line.get("unit_id", previous["unit_id"] if keep_structure else None),
                "requirement": line.get("requirement", previous["requirement"] if keep_structure else "required"),
                "purpose": line.get("purpose", previous["purpose"] if keep_structure else "unknown"),
                "ingredient_form": line.get("ingredient_form", previous["ingredient_form"] if keep_structure else None),
                "measurement_basis": line.get("measurement_basis", previous["measurement_basis"] if keep_structure else "unknown"),
                "scaling_mode": line.get("scaling_mode", previous["scaling_mode"] if keep_structure else "unknown"),
            }
            _write(connection, """INSERT INTO recipe_ingredients(recipe_id,line_no,ingredient_id,quantity_text,
                amount_kind,amount_min,amount_max,unit_id,requirement,purpose,ingredient_form,measurement_basis,scaling_mode)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (recipe_id,line_no,ingredient_id,quantity,structure["amount_kind"],structure["amount_min"],
                 structure["amount_max"],structure["unit_id"],structure["requirement"],structure["purpose"],
                 structure["ingredient_form"],structure["measurement_basis"],structure["scaling_mode"]))

    @staticmethod
    def _replace_steps(connection, recipe_id, instructions, steps=None):
        _write(connection, "DELETE FROM recipe_steps WHERE recipe_id=%s", (recipe_id,))
        if steps:
            normalized = steps
        else:
            from source.database.unified_catalog_migration import _numbered_steps
            normalized = _numbered_steps(instructions)
        for index, step in enumerate(normalized, 1):
            _write(connection, """INSERT INTO recipe_steps(recipe_id,step_no,instruction,duration_minutes,heat_level)
                VALUES(%s,%s,%s,%s,%s)""",
                (recipe_id,int(step.get("step_no",index)),step["instruction"],step.get("duration_minutes"),step.get("heat_level")))

    def _recipe_payload_hash(self, payload):
        from source.server.beverages import FIELDS
        data={key: payload.get(key) for key in ("title", "description", "instructions", "minutes", "role", "ingredients", "servings", "minutes_prep", "minutes_cook", "steps", "source_url", "tags", "portion_data_status", "portion_data_evidence")}
        data.update({key:payload[key] for key in FIELDS if key in payload})
        return _hash(data)

    @staticmethod
    def _save_beverage_tags(connection, recipe_id, payload):
        from source.server.beverages import tag_changes,TAG_LABELS
        for code,enabled in tag_changes(payload).items():
            rows=_query(connection,"SELECT tag_id,deleted_at FROM recipe_tags WHERE tag_type='dish_type' AND code=%s FOR UPDATE",(code,))
            if not enabled:
                if rows:_write(connection,"DELETE FROM recipe_tag_links WHERE recipe_id=%s AND tag_id=%s",(recipe_id,rows[0]['tag_id']))
                continue
            if rows and rows[0]['deleted_at'] is not None:raise AdminDraftConflict('beverage tag is deleted; restore it before use')
            if not rows:
                label=TAG_LABELS[code]
                _write(connection,"INSERT INTO recipe_tags(tag_type,code,label,normalized_label) VALUES('dish_type',%s,%s,%s)",(code,label,_norm(label)))
                rows=_query(connection,"SELECT tag_id FROM recipe_tags WHERE tag_type='dish_type' AND code=%s",(code,))
            _write(connection,"INSERT IGNORE INTO recipe_tag_links(recipe_id,tag_id) VALUES(%s,%s)",(recipe_id,rows[0]['tag_id']))

    @staticmethod
    def _replace_recipe_tags(connection, recipe_id, tags):
        from source.server.meal_preferences import CODES
        labels={group:{code:label for code,label in codes.items()} for group,codes in CODES.items()}
        labels["season"]={"spring":"Xuân","summer":"Hè","autumn":"Thu","winter":"Đông"}
        labels["diet"]={"vegetarian":"Chay","non_vegetarian":"Mặn"}
        for tag in tags:
            group,code=tag["tag_type"],tag["code"]
            label=labels[group][code]
            _write(connection,"""INSERT INTO recipe_tags(tag_type,code,label,normalized_label)
                VALUES(%s,%s,%s,%s) ON DUPLICATE KEY UPDATE label=VALUES(label),normalized_label=VALUES(normalized_label)""",
                (group,code,label,_norm(label)))
        managed_groups = tuple(labels)
        marks = ",".join(["%s"] * len(managed_groups))
        _write(connection,f"""DELETE l FROM recipe_tag_links l JOIN recipe_tags t USING(tag_id)
            WHERE l.recipe_id=%s AND t.tag_type IN ({marks})""",(recipe_id,*managed_groups))
        for tag in tags:
            rows=_query(connection,"SELECT tag_id FROM recipe_tags WHERE tag_type=%s AND code=%s FOR UPDATE",
                        (tag["tag_type"],tag["code"]))
            _write(connection,"INSERT INTO recipe_tag_links(recipe_id,tag_id) VALUES(%s,%s)",(recipe_id,int(rows[0]["tag_id"])))

    @staticmethod
    def _sync_core_dish_type(connection, recipe_id, role):
        rows=_query(connection,"SELECT tag_id FROM recipe_tags WHERE tag_type='dish_type' AND code=%s AND is_core=TRUE FOR UPDATE",(role,))
        if rows:
            _write(connection,"INSERT IGNORE INTO recipe_tag_links(recipe_id,tag_id) VALUES(%s,%s)",(recipe_id,int(rows[0]["tag_id"])))

    def admin_save_recipe(self, payload, author_ref):
        connection = self.connect()
        lock_name = "unified_recipe_create_id_allocator"
        locked = False
        try:
            connection.start_transaction()
            if "recipe_id" not in payload:
                _query(connection, "SELECT GET_LOCK(%s,5) acquired", (lock_name,))
                locked = True
                key = payload["idempotency_key"]
                digest = self._recipe_payload_hash(payload)
                prior = _query(connection, "SELECT recipe_id,create_payload_hash FROM recipes WHERE create_request_key=%s FOR UPDATE", (key,))
                if prior:
                    if prior[0]["create_payload_hash"] != digest:
                        raise AdminDraftConflict("idempotency key was already used with different recipe data")
                    connection.commit()
                    return {"recipe_id": int(prior[0]["recipe_id"]), "revision_id": int(prior[0]["recipe_id"]), "created": False}
                duplicate = _query(connection, "SELECT recipe_id FROM recipes WHERE normalized_title=%s AND deleted_at IS NULL FOR UPDATE", (_norm(payload["title"]),))
                if duplicate:
                    raise AdminDraftConflict("a recipe with this normalized title already exists")
                maximum = int(_query(connection, "SELECT COALESCE(MAX(recipe_id),%s) n FROM recipes WHERE recipe_id>%s", (V2_OFFSET, V2_OFFSET))[0]["n"])
                recipe_id = maximum + 1
                if recipe_id > MAX_PUBLIC_ID:
                    raise AdminDraftConflict("recipe public ID range is exhausted")
                _write(connection, """INSERT INTO recipes(recipe_id,title,normalized_title,description,role,minutes_total,
                    minutes_prep,minutes_cook,servings,instructions_legacy,source_url,is_public,edit_version,created_by,updated_by,
                    create_request_key,create_payload_hash)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,NULL,NULL,%s,%s)""",
                    (recipe_id, payload["title"], _norm(payload["title"]), payload["description"], payload["role"],
                     payload["minutes"],payload.get("minutes_prep"),payload.get("minutes_cook"),payload.get("servings"),
                     payload["instructions"],payload.get("source_url"),int(payload.get('is_visible',True)), key, digest))
                self._insert_lines(connection, recipe_id, payload["ingredients"])
                self._replace_steps(connection, recipe_id, payload["instructions"], payload.get("steps"))
                if payload.get("tags") is not None:self._replace_recipe_tags(connection,recipe_id,payload["tags"])
                self._sync_core_dish_type(connection, recipe_id, payload["role"])
            else:
                recipe_id = int(payload["recipe_id"])
                row = _query(connection, "SELECT edit_version,deleted_at FROM recipes WHERE recipe_id=%s FOR UPDATE", (recipe_id,))
                if not row or row[0]["deleted_at"] is not None:
                    raise AdminDraftConflict("recipe no longer exists or is deleted")
                if recipe_id != int(payload["revision_id"]) or self._version(connection, recipe_id) != payload["expected_version"]:
                    raise AdminDraftConflict("recipe changed since it was opened")
                _old_recipe, old_lines = self._recipe_rows(connection, recipe_id)
                duplicate = _query(connection, "SELECT recipe_id FROM recipes WHERE normalized_title=%s AND recipe_id<>%s AND deleted_at IS NULL FOR UPDATE",
                                   (_norm(payload["title"]), recipe_id))
                if duplicate:
                    raise AdminDraftConflict("a recipe with this normalized title already exists")
                self._record_history(connection, recipe_id)
                _write(connection, """UPDATE recipes SET title=%s,normalized_title=%s,description=%s,role=%s,minutes_total=%s,
                    minutes_prep=%s,minutes_cook=%s,servings=%s,instructions_legacy=%s,source_url=COALESCE(%s,source_url),
                    is_public=COALESCE(%s,is_public),edit_version=edit_version+1 WHERE recipe_id=%s""",
                    (payload["title"],_norm(payload["title"]),payload["description"],payload["role"],payload["minutes"],
                     payload.get("minutes_prep"),payload.get("minutes_cook"),payload.get("servings"),payload["instructions"],
                     payload.get("source_url"),int(payload["is_visible"]) if "is_visible" in payload else None,recipe_id))
                _write(connection, "DELETE FROM recipe_ingredients WHERE recipe_id=%s", (recipe_id,))
                self._insert_lines(connection, recipe_id, payload["ingredients"], old_lines)
                self._replace_steps(connection, recipe_id, payload["instructions"], payload.get("steps"))
                if payload.get("tags") is not None:self._replace_recipe_tags(connection,recipe_id,payload["tags"])
                self._sync_core_dish_type(connection, recipe_id, payload["role"])
            if payload.get("portion_data_status") is not None:
                _write(connection, "UPDATE recipes SET portion_data_status=%s,portion_data_evidence=%s WHERE recipe_id=%s",
                       (payload["portion_data_status"],payload.get("portion_data_evidence") or "",recipe_id))
            if payload['role']=='drink':self._save_beverage_tags(connection,recipe_id,payload)
            connection.commit()
            return {"recipe_id": recipe_id, "revision_id": recipe_id, "created": "recipe_id" not in payload}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno == 1062:
                raise AdminDraftConflict("recipe identity or idempotency key already exists", mysql_errno=1062) from None
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            if locked:
                try: _query(connection, "SELECT RELEASE_LOCK(%s)", (lock_name,))
                except mysql.connector.Error: pass
            connection.close()

    def admin_update_legacy_recipe(self, payload, author):
        reader = self.connect()
        try:
            current = self._admin_recipe_detail(reader, int(payload["recipe_id"]))
        finally:
            reader.close()
        if current is None or current["edit_version"] != payload["expected_version"]:
            raise AdminDraftConflict("recipe changed since it was opened")
        normalized = {"recipe_id": int(payload["recipe_id"]), "revision_id": int(payload["recipe_id"]),
            "expected_version": payload["expected_version"], "title": payload["title"],
            "description": payload["description"], "instructions": payload["instructions"],
            "minutes": payload["minutes"], "role": current["role"], "is_visible": bool(payload.get("is_visible", True)),
            "ingredients": [{"ingredient_id": int(x["ingredient_id"]), "quantity_raw": x.get("quantity", ""),
                              "requirement": "required"} for x in payload["ingredients"]]}
        return self.admin_save_recipe(normalized, author)

    def admin_set_legacy_recipe_visibility(self, payload, author):
        return self.admin_set_recipe_lifecycle({"recipe_id": payload["recipe_id"],
            "is_visible": bool(payload["is_visible"]), "is_deleted": False}, author)

    def admin_set_recipe_lifecycle(self, payload, author):
        connection = self.connect()
        try:
            connection.start_transaction()
            rows = _query(connection, "SELECT recipe_id,is_public,deleted_at FROM recipes WHERE recipe_id=%s FOR UPDATE", (payload["recipe_id"],))
            if not rows:
                raise AdminDraftConflict("recipe not found")
            self._record_history(connection, payload["recipe_id"])
            deleted_at = datetime.now(timezone.utc).replace(tzinfo=None) if payload["is_deleted"] else None
            # Preserve prior visibility through soft deletion. Public readers
            # exclude deleted_at, while restore can re-enable the same recipe.
            is_public = int(rows[0]["is_public"]) if payload["is_deleted"] else int(payload["is_visible"])
            _write(connection, "UPDATE recipes SET is_public=%s,deleted_at=%s,edit_version=edit_version+1 WHERE recipe_id=%s",
                   (is_public, deleted_at, payload["recipe_id"]))
            connection.commit()
            return {"recipe_id": payload["recipe_id"], "is_visible": payload["is_visible"], "is_deleted": payload["is_deleted"]}
        except Exception:
            connection.rollback(); raise
        finally: connection.close()

    def admin_permanently_delete_recipe(self, recipe_id, *, confirm_user_content_delete,
                                        expected_achievement_counts):
        """Atomically purge a soft-deleted recipe and explicitly confirmed user content."""
        connection = self.connect()
        try:
            connection.start_transaction()
            rows = _query(connection, "SELECT recipe_id,deleted_at FROM recipes WHERE recipe_id=%s FOR UPDATE", (recipe_id,))
            if not rows:
                raise AdminDraftConflict("M\u00f3n c\u1ea7n x\u00f3a kh\u00f4ng c\u00f2n t\u1ed3n t\u1ea1i.")
            if rows[0]["deleted_at"] is None:
                raise AdminDraftConflict("H\u00e3y x\u00f3a m\u1ec1m m\u00f3n tr\u01b0\u1edbc khi x\u00f3a v\u0129nh vi\u1ec5n.")

            posts = _query(connection, "SELECT post_id FROM achievement_posts WHERE recipe_id=%s ORDER BY post_id FOR UPDATE", (recipe_id,))
            post_ids = [int(item["post_id"]) for item in posts]
            comments, achievement_images = [], []
            if post_ids:
                marks = ",".join(["%s"] * len(post_ids))
                comments = _query(connection, f"SELECT comment_id FROM achievement_comments WHERE post_id IN ({marks}) ORDER BY comment_id FOR UPDATE", tuple(post_ids))
                achievement_images = _query(connection, f"SELECT image_id,storage_key FROM achievement_images WHERE post_id IN ({marks}) ORDER BY image_id FOR UPDATE", tuple(post_ids))
            actual_counts = {"posts": len(post_ids), "comments": len(comments), "images": len(achievement_images)}
            if actual_counts != expected_achievement_counts:
                raise AdminDraftConflict("N\u1ed9i dung Th\u00e0nh qu\u1ea3 \u0111\u00e3 thay \u0111\u1ed5i. T\u1ea3i l\u1ea1i danh s\u00e1ch v\u00e0 x\u00e1c nh\u1eadn l\u1ea1i.")
            if any(actual_counts.values()) and not confirm_user_content_delete:
                raise AdminDraftConflict("M\u00f3n c\u00f2n b\u00e0i Th\u00e0nh qu\u1ea3, b\u00ecnh lu\u1eadn ho\u1eb7c \u1ea3nh ng\u01b0\u1eddi d\u00f9ng; c\u1ea7n x\u00e1c nh\u1eadn ri\u00eang.")

            recipe_images = _query(connection, "SELECT storage_key FROM recipe_images WHERE recipe_id=%s FOR UPDATE", (recipe_id,))
            if post_ids:
                _write(connection, "DELETE FROM achievement_posts WHERE recipe_id=%s", (recipe_id,))
            for table in ("recipe_ingredients", "recipe_steps", "recipe_tag_links", "recipe_images",
                          "recipe_edit_history", "recipe_id_map"):
                _write(connection, f"DELETE FROM {table} WHERE recipe_id=%s", (recipe_id,))
            _write(connection, "DELETE FROM recipes WHERE recipe_id=%s AND deleted_at IS NOT NULL", (recipe_id,))
            connection.commit()
            return {"recipe_id": recipe_id, "deleted": True, "achievement_counts": actual_counts,
                    "recipe_image_keys": [item["storage_key"] for item in recipe_images],
                    "achievement_image_keys": [item["storage_key"] for item in achievement_images]}
        except Exception:
            connection.rollback(); raise
        finally:
            connection.close()

    def admin_permanently_delete_ingredient(self, ingredient_id):
        """Purge only an inactive, unreferenced, unmapped unified ingredient."""
        connection = self.connect()
        try:
            connection.start_transaction()
            rows = _query(connection, "SELECT ingredient_id,is_active FROM ingredients WHERE ingredient_id=%s FOR UPDATE", (ingredient_id,))
            if not rows:
                raise AdminIngredientConflict("ingredient not found")
            if rows[0]["is_active"]:
                raise AdminIngredientConflict("deactivate the ingredient before permanent deletion")
            if self._ingredient_usage(connection, ingredient_id):
                raise AdminIngredientConflict("ingredient is still referenced by one or more recipes")
            if _query(connection, "SELECT 1 FROM ingredient_id_map WHERE ingredient_id=%s LIMIT 1 FOR UPDATE", (ingredient_id,)):
                raise AdminIngredientConflict("ingredient has an import identity mapping and is protected")
            _write(connection, "DELETE FROM ingredient_aliases WHERE ingredient_id=%s", (ingredient_id,))
            _write(connection, "DELETE FROM ingredients WHERE ingredient_id=%s AND is_active=0", (ingredient_id,))
            connection.commit()
            return {"ingredient_id": ingredient_id, "deleted": True}
        except Exception:
            connection.rollback(); raise
        finally:
            connection.close()

    def admin_list_users(self, connection, query, limit, offset):
        needle = _norm(query.strip())
        where = " WHERE normalized_username LIKE %s OR username LIKE %s" if needle else ""
        params = (f"%{needle}%", f"%{needle}%") if needle else ()
        total = int(_query(connection, "SELECT COUNT(*) n FROM users" + where, params)[0]["n"])
        rows = _query(connection, "SELECT user_id,username,role,status,created_at,last_login_at FROM users" + where +
                      " ORDER BY created_at DESC,user_id DESC LIMIT %s OFFSET %s", (*params, limit, offset))
        return {"items": [{"user_id": str(r["user_id"]), "username": r["username"], "role": r["role"],
                            "account_status": r["status"], "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                            "last_login_at": r["last_login_at"].isoformat() if r["last_login_at"] else None} for r in rows],
                "total": total, "limit": limit, "offset": offset, "account_admin_ready": True}

    def admin_set_user_status(self, payload):
        return self._set_user_field(payload["user_id"], "status", payload["account_status"])

    def admin_set_user_role(self, payload):
        return self._set_user_field(payload["user_id"], "role", payload["role"])

    def _set_user_field(self, user_id, field, value):
        if field not in {"status", "role"}:
            raise ValueError("invalid account field")
        connection = self.connect()
        try:
            connection.start_transaction()
            row = _query(connection, "SELECT user_id,role,status FROM users WHERE user_id=%s FOR UPDATE", (user_id,))
            if not row:
                raise UserAccountConflict("user account not found")
            if row[0]["role"] == "ADMIN" and ((field == "role" and value != "ADMIN") or (field == "status" and value != "ACTIVE")):
                active_admins = int(_query(connection, "SELECT COUNT(*) n FROM users WHERE role='ADMIN' AND status='ACTIVE'")[0]["n"])
                if active_admins <= 1:
                    raise UserAccountConflict("cannot disable or demote the last active Admin account")
            _write(connection, f"UPDATE users SET {field}=%s WHERE user_id=%s", (value, user_id))
            connection.commit()
            return {"user_id": str(user_id), "account_status" if field == "status" else "role": value}
        except Exception:
            connection.rollback(); raise
        finally: connection.close()

    # Achievement posts are ordinary user content attached to the same public
    # recipe and account records. Image files are removed by FastAPI only after
    # these metadata transactions commit.
    @staticmethod
    def _achievement_row(row):
        return {"post_id": str(row["post_id"]), "recipe_id": str(row["recipe_id"]),
                "user_id": str(row["user_id"]), "username": row["username"],
                "recipe_title": row["recipe_title"], "description": row["description"],
                "changed_ingredients": row["changed_ingredients"],
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                "comment_count": int(row.get("comment_count", 0)), "images": []}

    def achievement_list(self, connection, query="", limit=12, offset=0, *, admin=False):
        needle = _norm(query.strip())
        conditions, args = [], []
        if not admin:
            conditions.append("r.is_public=1 AND r.deleted_at IS NULL")
        if needle:
            conditions.append("(LOWER(p.description) LIKE %s OR LOWER(r.normalized_title) LIKE %s OR LOWER(u.normalized_username) LIKE %s)")
            pattern = f"%{needle}%"
            args.extend((pattern, pattern, pattern))
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        total = int(_query(connection, "SELECT COUNT(*) AS n FROM achievement_posts p JOIN recipes r ON r.recipe_id=p.recipe_id JOIN users u ON u.user_id=p.user_id" + where, tuple(args))[0]["n"])
        rows = _query(connection, """SELECT p.post_id,p.recipe_id,p.user_id,p.description,p.changed_ingredients,p.created_at,
                u.username,r.title AS recipe_title,(SELECT COUNT(*) FROM achievement_comments c WHERE c.post_id=p.post_id) AS comment_count
            FROM achievement_posts p JOIN recipes r ON r.recipe_id=p.recipe_id JOIN users u ON u.user_id=p.user_id""" + where +
            " ORDER BY p.created_at DESC,p.post_id DESC LIMIT %s OFFSET %s", (*args, limit, offset))
        items = [self._achievement_row(row) for row in rows]
        if items:
            ids = [int(item["post_id"]) for item in items]
            marks = ",".join(["%s"] * len(ids))
            images = _query(connection, f"SELECT post_id,storage_key,media_type,byte_size,width,height,sha256 FROM achievement_images WHERE post_id IN ({marks}) ORDER BY image_id", tuple(ids))
            by_post = {int(item["post_id"]): item for item in items}
            for image in images:
                by_post[int(image["post_id"])]["images"].append({key: image[key] for key in ("storage_key", "media_type", "byte_size", "width", "height", "sha256")})
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def achievement_get(self, connection, post_id, *, admin=False):
        public_filter = " AND r.is_public=1 AND r.deleted_at IS NULL" if not admin else ""
        rows = _query(connection, """SELECT p.post_id,p.recipe_id,p.user_id,p.description,p.changed_ingredients,p.created_at,
            u.username,r.title AS recipe_title,(SELECT COUNT(*) FROM achievement_comments c WHERE c.post_id=p.post_id) AS comment_count
            FROM achievement_posts p JOIN recipes r ON r.recipe_id=p.recipe_id JOIN users u ON u.user_id=p.user_id
            WHERE p.post_id=%s""" + public_filter, (post_id,))
        if not rows:
            return None
        result = self._achievement_row(rows[0])
        result["images"] = [{key: row[key] for key in ("storage_key", "media_type", "byte_size", "width", "height", "sha256")}
            for row in _query(connection, "SELECT storage_key,media_type,byte_size,width,height,sha256 FROM achievement_images WHERE post_id=%s ORDER BY image_id", (post_id,))]
        result["comments"] = [{"comment_id": str(row["comment_id"]), "user_id": str(row["user_id"]),
            "username": row["username"], "body": row["body"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None}
            for row in _query(connection, """SELECT c.comment_id,c.user_id,c.body,c.created_at,u.username
                FROM achievement_comments c JOIN users u ON u.user_id=c.user_id
                WHERE c.post_id=%s ORDER BY c.created_at,c.comment_id""", (post_id,))]
        return result

    def achievement_image(self, connection, storage_key, *, admin=False):
        visibility = "" if admin else " AND r.is_public=1 AND r.deleted_at IS NULL"
        rows = _query(connection, """SELECT i.storage_key,i.media_type,i.byte_size,i.width,i.height,i.sha256
            FROM achievement_images i JOIN achievement_posts p ON p.post_id=i.post_id
            JOIN recipes r ON r.recipe_id=p.recipe_id
            WHERE i.storage_key=%s""" + visibility, (storage_key,))
        return {key: rows[0][key] for key in ("storage_key", "media_type", "byte_size", "width", "height", "sha256")} if rows else None

    @staticmethod
    def _feedback_row(row):
        result = {"feedback_id": str(row["feedback_id"]), "category": row["category"],
                  "content": row["content"], "status": row["status"],
                  "username": row.get("username") or "Khách", "created_at": row["created_at"].isoformat(),
                  "image": None}
        if row.get("image_storage_key"):
            result["image"] = {"storage_key": row["image_storage_key"], "media_type": row["image_media_type"],
                "byte_size": int(row["image_byte_size"]), "width": int(row["image_width"]),
                "height": int(row["image_height"]), "sha256": row["image_sha256"]}
        return result

    def feedback_create(self, payload):
        connection = self.connect()
        try:
            connection.start_transaction()
            prior = _query(connection, "SELECT feedback_id FROM feedback_submissions WHERE request_key=%s FOR UPDATE",
                           (payload["request_key"],))
            if prior:
                connection.commit()
                return {"feedback_id": str(prior[0]["feedback_id"]), "created": False}
            image = payload["image"]
            _write(connection, """INSERT INTO feedback_submissions
                (user_id,category,content,request_key,image_storage_key,image_media_type,image_byte_size,image_width,image_height,image_sha256)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (payload.get("user_id"), payload["category"], payload["content"], payload["request_key"],
                 image["storage_key"] if image else None, image["media_type"] if image else None,
                 image["byte_size"] if image else None, image["width"] if image else None,
                 image["height"] if image else None, image["sha256"] if image else None))
            feedback_id = _query(connection, "SELECT feedback_id FROM feedback_submissions WHERE request_key=%s",
                                 (payload["request_key"],))[0]["feedback_id"]
            connection.commit()
            return {"feedback_id": str(feedback_id), "created": True}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def feedback_admin_list(self, connection, status, limit, offset):
        where, args = (" WHERE f.status=%s", [status]) if status != "all" else ("", [])
        total = int(_query(connection, "SELECT COUNT(*) AS n FROM feedback_submissions f" + where, tuple(args))[0]["n"])
        rows = _query(connection, """SELECT f.feedback_id,f.category,f.content,f.status,f.created_at,
            u.username,f.image_storage_key,f.image_media_type,f.image_byte_size,f.image_width,f.image_height,f.image_sha256
            FROM feedback_submissions f LEFT JOIN users u ON u.user_id=f.user_id""" + where +
            " ORDER BY f.created_at DESC,f.feedback_id DESC LIMIT %s OFFSET %s", (*args, limit, offset))
        return {"items": [self._feedback_row(row) for row in rows], "total": total, "limit": limit, "offset": offset}

    def feedback_admin_get(self, connection, feedback_id):
        rows = _query(connection, """SELECT f.feedback_id,f.category,f.content,f.status,f.created_at,
            u.username,f.image_storage_key,f.image_media_type,f.image_byte_size,f.image_width,f.image_height,f.image_sha256
            FROM feedback_submissions f LEFT JOIN users u ON u.user_id=f.user_id WHERE f.feedback_id=%s""", (feedback_id,))
        return self._feedback_row(rows[0]) if rows else None

    def feedback_admin_image(self, connection, storage_key):
        rows = _query(connection, """SELECT feedback_id,image_storage_key,image_media_type,image_byte_size,
            image_width,image_height,image_sha256 FROM feedback_submissions WHERE image_storage_key=%s""", (storage_key,))
        if not rows:
            return None
        row = rows[0]
        return {"feedback_id": str(row["feedback_id"]), "storage_key": row["image_storage_key"],
            "media_type": row["image_media_type"], "byte_size": int(row["image_byte_size"]),
            "width": int(row["image_width"]), "height": int(row["image_height"]), "sha256": row["image_sha256"]}

    def feedback_admin_set_status(self, feedback_id, status):
        connection = self.connect()
        try:
            connection.start_transaction()
            rows = _query(connection, "SELECT feedback_id FROM feedback_submissions WHERE feedback_id=%s FOR UPDATE", (feedback_id,))
            if not rows:
                connection.rollback()
                return None
            _write(connection, "UPDATE feedback_submissions SET status=%s WHERE feedback_id=%s", (status, feedback_id))
            connection.commit()
            return {"feedback_id": str(feedback_id), "status": status}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def feedback_admin_delete(self, feedback_id):
        connection = self.connect()
        try:
            connection.start_transaction()
            rows = _query(connection, "SELECT feedback_id,image_storage_key FROM feedback_submissions WHERE feedback_id=%s FOR UPDATE", (feedback_id,))
            if not rows:
                connection.rollback()
                return None
            _write(connection, "DELETE FROM feedback_submissions WHERE feedback_id=%s", (feedback_id,))
            connection.commit()
            return {"feedback_id": str(feedback_id), "image_storage_key": rows[0]["image_storage_key"]}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def achievement_create_result(self, connection, user_id, request_key):
        rows = _query(connection, "SELECT post_id FROM achievement_posts WHERE user_id=%s AND request_key=%s", (user_id, request_key))
        return self.achievement_get(connection, int(rows[0]["post_id"])) if rows else None

    def achievement_create(self, payload):
        connection = self.connect()
        try:
            connection.start_transaction()
            recipe = _query(connection, "SELECT recipe_id FROM recipes WHERE recipe_id=%s AND is_public=1 AND deleted_at IS NULL FOR UPDATE", (payload["recipe_id"],))
            if not recipe:
                raise ValueError("recipe unavailable")
            image_content = [{key: image[key] for key in ("media_type", "byte_size", "width", "height", "sha256")}
                             for image in payload["images"]]
            payload_hash = _hash({"recipe_id": payload["recipe_id"], "description": payload["description"],
                                  "changed_ingredients": payload["changed_ingredients"], "images": image_content})
            prior = _query(connection, "SELECT post_id,payload_hash FROM achievement_posts WHERE user_id=%s AND request_key=%s FOR UPDATE", (payload["user_id"], payload["request_key"]))
            if prior:
                if prior[0]["payload_hash"] != payload_hash:
                    raise ValueError("request key reused with different content")
                post_id = int(prior[0]["post_id"])
                connection.commit()
                return {"post_id": str(post_id), "created": False}
            _, post_id = _write(connection, """INSERT INTO achievement_posts(recipe_id,user_id,description,changed_ingredients,request_key,payload_hash)
                VALUES(%s,%s,%s,%s,%s,%s)""", (payload["recipe_id"], payload["user_id"], payload["description"],
                payload["changed_ingredients"], payload["request_key"], payload_hash))
            for image in payload["images"]:
                _write(connection, """INSERT INTO achievement_images(post_id,storage_key,media_type,byte_size,width,height,sha256)
                    VALUES(%s,%s,%s,%s,%s,%s,%s)""", (post_id, image["storage_key"], image["media_type"], image["byte_size"], image["width"], image["height"], image["sha256"]))
            connection.commit()
            return {"post_id": str(post_id), "created": True}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def achievement_comment_create(self, payload):
        connection = self.connect()
        try:
            connection.start_transaction()
            post = _query(connection, "SELECT p.post_id FROM achievement_posts p JOIN recipes r ON r.recipe_id=p.recipe_id WHERE p.post_id=%s AND r.is_public=1 AND r.deleted_at IS NULL FOR UPDATE", (payload["post_id"],))
            if not post:
                raise ValueError("achievement unavailable")
            _, comment_id = _write(connection, "INSERT INTO achievement_comments(post_id,user_id,body) VALUES(%s,%s,%s)",
                                   (payload["post_id"], payload["user_id"], payload["body"]))
            connection.commit()
            return {"comment_id": str(comment_id), "post_id": str(payload["post_id"])}
        except Exception:
            connection.rollback(); raise
        finally:
            connection.close()

    def achievement_delete_post(self, post_id, *, user_id=None):
        connection = self.connect()
        try:
            connection.start_transaction()
            rows = _query(connection, "SELECT post_id,user_id FROM achievement_posts WHERE post_id=%s FOR UPDATE", (post_id,))
            if not rows:
                raise LookupError("achievement not found")
            if user_id is not None and int(rows[0]["user_id"]) != int(user_id):
                raise PermissionError("only the post author can delete this achievement")
            keys = [row["storage_key"] for row in _query(connection, "SELECT storage_key FROM achievement_images WHERE post_id=%s FOR UPDATE", (post_id,))]
            _write(connection, "DELETE FROM achievement_posts WHERE post_id=%s", (post_id,))
            connection.commit()
            return {"post_id": str(post_id), "deleted": True, "storage_keys": keys}
        except Exception:
            connection.rollback(); raise
        finally:
            connection.close()

    def achievement_delete_comment(self, comment_id, *, user_id=None):
        connection = self.connect()
        try:
            connection.start_transaction()
            rows = _query(connection, "SELECT comment_id,user_id,post_id FROM achievement_comments WHERE comment_id=%s FOR UPDATE", (comment_id,))
            if not rows:
                raise LookupError("comment not found")
            if user_id is not None and int(rows[0]["user_id"]) != int(user_id):
                raise PermissionError("only the comment author can delete this comment")
            _write(connection, "DELETE FROM achievement_comments WHERE comment_id=%s", (comment_id,))
            connection.commit()
            return {"comment_id": str(comment_id), "post_id": str(rows[0]["post_id"]), "deleted": True}
        except Exception:
            connection.rollback(); raise
        finally:
            connection.close()

    def admin_get_recipe_image(self, connection, recipe_id):
        ready = bool(_query(connection, "SELECT COUNT(*) n FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='recipe_images'")[0]["n"])
        row = _query(connection, "SELECT storage_key,media_type,byte_size,width,height,sha256 FROM recipe_images WHERE recipe_id=%s", (recipe_id,))
        return {"recipe_id": recipe_id, "ready": ready, "image": self._image_data(row[0]) if row else None}

    @staticmethod
    def _image_data(row):
        return {"storage_key": row["storage_key"], "media_type": row["media_type"], "byte_size": int(row["byte_size"]),
                "width": int(row["width"]), "height": int(row["height"]), "sha256": row["sha256"]}

    def admin_set_recipe_image(self, reader_connection, payload, author):
        connection = self.connect()
        try:
            connection.start_transaction()
            recipe = _query(connection, "SELECT recipe_id FROM recipes WHERE recipe_id=%s FOR UPDATE", (payload["recipe_id"],))
            if not recipe:
                raise AdminDraftConflict("recipe not found")
            previous = _query(connection, "SELECT storage_key FROM recipe_images WHERE recipe_id=%s FOR UPDATE", (payload["recipe_id"],))
            old_key = previous[0]["storage_key"] if previous else None
            _write(connection, """INSERT INTO recipe_images(recipe_id,storage_key,media_type,byte_size,width,height,sha256)
                VALUES(%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE storage_key=VALUES(storage_key),media_type=VALUES(media_type),
                byte_size=VALUES(byte_size),width=VALUES(width),height=VALUES(height),sha256=VALUES(sha256)""",
                tuple(payload[key] for key in ("recipe_id", "storage_key", "media_type", "byte_size", "width", "height", "sha256")))
            connection.commit()
            return {"recipe_id": payload["recipe_id"], "previous_storage_key": old_key, "image": self.admin_get_recipe_image(connection, payload["recipe_id"])["image"]}
        except Exception:
            connection.rollback(); raise
        finally: connection.close()

    def admin_remove_recipe_image(self, recipe_id):
        connection = self.connect()
        try:
            connection.start_transaction()
            rows = _query(connection, "SELECT storage_key FROM recipe_images WHERE recipe_id=%s FOR UPDATE", (recipe_id,))
            if not rows:
                raise AdminDraftConflict("recipe image not found")
            _write(connection, "DELETE FROM recipe_images WHERE recipe_id=%s", (recipe_id,))
            connection.commit()
            return {"recipe_id": recipe_id, "previous_storage_key": rows[0]["storage_key"]}
        except Exception:
            connection.rollback(); raise
        finally: connection.close()

    def admin_restore_v2_recipe_snapshot(self, payload, author):
        raise AdminDraftConflict("snapshot restore must be performed through the current authenticated Admin snapshot endpoint")

    def admin_restore_legacy_recipe_snapshot(self, payload, author):
        return self.admin_update_legacy_recipe(payload, author)

    def admin_create_draft(self, payload, author_ref):
        raise AdminDraftConflict("review-based drafts are not part of unified schema v3")

    def admin_update_draft(self, payload):
        raise AdminDraftConflict("review-based drafts are not part of unified schema v3")
