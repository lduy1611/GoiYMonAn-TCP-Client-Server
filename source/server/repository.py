from __future__ import annotations

import os
import sqlite3
import threading
import unicodedata
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import mysql.connector
from mysql.connector import pooling

from source.server.meal_plan_calculation import Catalog as CalculationCatalog


class AdminWriteUnavailable(RuntimeError):
    pass


class AdminDraftConflict(RuntimeError):
    def __init__(self, message: str, *, mysql_errno: int | None = None, reason: str = "recipe_conflict"):
        super().__init__(message)
        self.mysql_errno = mysql_errno
        self.reason = reason


class AdminSchemaUnavailable(RuntimeError):
    pass


class AdminReviewConflict(RuntimeError):
    pass


class AdminReviewBlocked(RuntimeError):
    pass


class AdminIngredientConflict(RuntimeError):
    pass


class AdminIngredientSchemaUnavailable(RuntimeError):
    pass


class AdminRecipeImageUnavailable(RuntimeError):
    pass


class AdminRecipeImageSchemaUnavailable(RuntimeError):
    pass


class UserAccountUnavailable(RuntimeError):
    pass


class UserAccountConflict(RuntimeError):
    pass


class UserAccountUnauthorized(RuntimeError):
    pass


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def ingredient_search_normalize(value: str) -> str:
    folded = unicodedata.normalize("NFD", normalize(value))
    return "".join("d" if char == "đ" else char for char in folded
                   if unicodedata.category(char) != "Mn")


def _preference_details(rows, lines):
    grouped = defaultdict(list)
    for recipe_id, iid, name, quantity, required in lines:
        grouped[recipe_id].append({"id": iid, "name": name, "quantity": quantity, "is_required": bool(required)})
    return [{"id": rid, "title": title, "instructions": instructions, "minutes": minutes,
             "source_url": url, "ingredients": grouped[rid]} for rid, title, instructions, minutes, url in rows]


def mysql_config_from_env() -> dict[str, Any]:
    load_dotenv()
    required = ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE")
    missing = [key for key in required if os.getenv(key) is None]
    if missing:
        raise RuntimeError("Missing MySQL configuration: " + ", ".join(missing))
    return {
        "host": os.environ["MYSQL_HOST"],
        "port": int(os.environ["MYSQL_PORT"]),
        "user": os.environ["MYSQL_USER"],
        "password": os.environ["MYSQL_PASSWORD"],
        "database": os.environ["MYSQL_DATABASE"],
        "charset": "utf8mb4",
        "collation": "utf8mb4_unicode_ci",
        "connection_timeout": 5,
    }


class Repository:
    """Legacy read-only SQLite repository retained for regression comparison."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.db_path.resolve()}?mode=ro", uri=True)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def dataset_version(self, connection: sqlite3.Connection) -> str:
        row = connection.execute("SELECT value FROM metadata WHERE key='dataset_version'").fetchone()
        if row is None:
            raise sqlite3.DatabaseError("missing dataset_version")
        return str(row[0])

    def recipe_ids_exist(self, connection, ids: tuple[int, ...]) -> bool:
        marks = ",".join("?" for _ in ids)
        row = connection.execute(f"SELECT COUNT(*) FROM recipes WHERE id IN ({marks})", ids).fetchone()
        return row[0] == len(ids)

    def calculation_catalog(self, connection, recipe_ids: tuple[int, ...]) -> CalculationCatalog:
        # No released v2 adapter yet. Never parse legacy quantities or load review dossiers.
        return CalculationCatalog(available=False)

    def meal_preference_catalog(self, connection, recipes, classification):
        from source.server.meal_preferences import load
        rows = connection.execute("SELECT id,title,instructions,minutes,source_url FROM recipes ORDER BY id").fetchall()
        lines = connection.execute("SELECT ri.recipe_id,i.id,i.name,ri.quantity,ri.is_required FROM recipe_ingredients ri JOIN ingredients i ON i.id=ri.ingredient_id ORDER BY ri.recipe_id,i.id").fetchall()
        names = dict(connection.execute("SELECT id,name FROM ingredients").fetchall())
        return load(recipes, names, classification, _preference_details(rows, lines))

    def list_ingredients(self, connection: sqlite3.Connection, query: str, limit: int) -> list[dict[str, Any]]:
        normalized = normalize(query.strip())
        escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        rows = connection.execute("SELECT DISTINCT i.id, i.name FROM ingredients i LEFT JOIN ingredient_aliases a ON a.ingredient_id=i.id WHERE i.normalized_name LIKE ? ESCAPE '\\' OR a.alias_norm LIKE ? ESCAPE '\\' ORDER BY i.id LIMIT ?", (pattern, pattern, limit)).fetchall()
        return [{"id": row[0], "name": row[1]} for row in rows]

    def recipes_for_ranking(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute("SELECT id,title,minutes FROM recipes ORDER BY id").fetchall()
        relations = connection.execute("SELECT recipe_id,ingredient_id,is_required FROM recipe_ingredients ORDER BY recipe_id,ingredient_id").fetchall()
        grouped: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for recipe_id, ingredient_id, is_required in relations:
            grouped[recipe_id].append((ingredient_id, is_required))
        return [{"id": recipe_id, "title": title, "minutes": minutes, "required_ids": {x[0] for x in grouped[recipe_id] if x[1]}, "all_ids": {x[0] for x in grouped[recipe_id]}} for recipe_id, title, minutes in rows]

    def recipes_for_search(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        recipes = self.recipes_for_ranking(connection)
        names = dict(connection.execute("SELECT id,name FROM ingredients").fetchall())
        return [{**recipe, "ingredient_names": [names[i] for i in sorted(recipe["all_ids"])]}
                for recipe in recipes]

    def ingredient_ids_exist(self, connection: sqlite3.Connection, ids: set[int]) -> bool:
        if not ids:
            return True
        marks = ",".join("?" for _ in ids)
        row = connection.execute(f"SELECT COUNT(*) FROM ingredients WHERE id IN ({marks})", tuple(ids)).fetchone()
        return row[0] == len(ids)

    def get_recipe(self, connection: sqlite3.Connection, recipe_id: int) -> dict[str, Any] | None:
        row = connection.execute("SELECT id,title,instructions,minutes,source_url FROM recipes WHERE id=?", (recipe_id,)).fetchone()
        if row is None:
            return None
        ingredients = connection.execute("SELECT i.id,i.name,ri.quantity,ri.is_required FROM recipe_ingredients ri JOIN ingredients i ON i.id=ri.ingredient_id WHERE ri.recipe_id=? ORDER BY i.id", (recipe_id,)).fetchall()
        return {"id": row[0], "title": row[1], "instructions": row[2], "minutes": row[3], "source_url": row[4], "ingredients": [{"id": x[0], "name": x[1], "quantity": x[2], "is_required": bool(x[3])} for x in ingredients]}

    def admin_dashboard(self, connection):
        recipes=connection.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]
        ingredients=connection.execute("SELECT COUNT(*) FROM ingredients").fetchone()[0]
        return {"recipes_total":recipes,"ingredients_total":ingredients,"revisions_total":0,
                "draft_revisions":0,"needs_verification_revisions":0,"approved_revisions":0,"draft_write_ready":False,
                "review_write_ready":False,"ingredient_admin_ready":False}

    def admin_list_recipes(self, connection, query, limit, offset, *, role=None, visibility=None, max_minutes=None):
        return {"items":[],"total":0,"limit":limit,"offset":offset}

    def admin_get_recipe(self, connection, revision_id):
        return None

    def admin_get_legacy_recipe(self,connection,recipe_id):
        return None

    def admin_update_legacy_recipe(self,payload,author):
        raise AdminWriteUnavailable("legacy recipe overlays require a dedicated writer")

    def admin_set_legacy_recipe_visibility(self,payload,author):
        raise AdminWriteUnavailable("legacy recipe overlays require a dedicated writer")

    def admin_list_ingredients(self, connection, query, limit=20, offset=0, active_only=False):
        return {"items":[],"total":0,"limit":limit,"offset":offset,"ingredient_admin_ready":False}

    def admin_create_ingredient(self,payload):
        raise AdminWriteUnavailable("ingredient writes require the MySQL v2 writer adapter")

    def admin_update_ingredient(self,payload):
        raise AdminWriteUnavailable("ingredient writes require the MySQL v2 writer adapter")

    def admin_set_ingredient_active(self,payload):
        raise AdminWriteUnavailable("ingredient writes require the MySQL v2 writer adapter")

    def admin_create_draft(self,payload,author_ref):
        raise AdminWriteUnavailable("draft writes require the MySQL v2 writer adapter")

    def admin_update_draft(self,payload):
        raise AdminWriteUnavailable("draft writes require the MySQL v2 writer adapter")

    def user_register(self, payload):
        raise UserAccountUnavailable("user account migration or writer is unavailable")

    def user_login(self, payload):
        raise UserAccountUnavailable("user account migration or writer is unavailable")

    def user_session(self, claims):
        raise UserAccountUnavailable("user account migration or writer is unavailable")

    def admin_list_users(self, connection, query, limit, offset):
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "account_admin_ready": False}

    def admin_set_user_status(self, payload):
        raise UserAccountUnavailable("user account migration or writer is unavailable")

    def admin_set_user_role(self, payload):
        raise UserAccountUnavailable("user account migration or writer is unavailable")


class MySQLRepository:
    """Thread-safe MySQL repository; only the TCP server constructs this class."""

    def __init__(self, config: dict[str, Any] | None = None, pool_size: int = 32):
        # Configure real pooled sessions, not attributes on PooledMySQLConnection.
        # The wrapper forwards reads via __getattr__, but not property assignments.
        self.config = {**(config or mysql_config_from_env()), "autocommit": True}
        self._pool = pooling.MySQLConnectionPool(
            pool_name=f"goiy_mon_an_{uuid.uuid4().hex[:10]}",
            pool_size=pool_size,
            pool_reset_session=True,
            **self.config,
        )
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "MySQLRepository":
        try:
            # Connector pools eagerly open every slot. A smaller default keeps
            # parallel local dev servers from consuming MySQL's connection cap
            # before the service is ready; deployments can still tune it.
            pool_size=int(os.getenv("TCP_DB_POOL_SIZE","4"))
        except ValueError:
            raise RuntimeError("TCP_DB_POOL_SIZE must be an integer") from None
        if not 1<=pool_size<=64:
            raise RuntimeError("TCP_DB_POOL_SIZE must be between 1 and 64")
        return cls(pool_size=pool_size)

    def connect(self):
        """Return a private pooled connection; caller must close it."""
        return self._pool.get_connection()

    def request_view(self, connection, operation):
        if operation not in {'SEARCH_RECIPES','GET_RECIPE','GENERATE_MEAL_PLAN_V2',
                             'GET_MEAL_PLAN_FILTERS','LIST_INGREDIENTS','CALCULATE_MEAL_PLAN',
                             'RECOMMEND','GENERATE_MEAL_PLAN','GET_RECIPE_IMAGE'}:
            return self
        from source.server.mysql_recipe_catalog import load_catalog
        from source.server.published_repository import PublishedRepository
        return PublishedRepository(self,load_catalog(connection))

    @staticmethod
    def _fetchall(connection, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
            return cursor.fetchall()
        finally:
            cursor.close()

    @staticmethod
    def _fetchone(connection, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
        cursor = connection.cursor()
        try:
            cursor.execute(sql, params)
            return cursor.fetchone()
        finally:
            cursor.close()

    def _admin_writer(self):
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2]/".env")
        user=os.getenv("MYSQL_DRAFT_WRITER_USER")
        password=os.getenv("MYSQL_DRAFT_WRITER_PASSWORD")
        if not user or not password:
            raise AdminWriteUnavailable("a dedicated v2 writer account is not configured")
        if user==self.config.get("user"):
            raise AdminWriteUnavailable("Admin writes require a database account separate from the runtime reader")
        config={k:v for k,v in self.config.items() if k!="autocommit"}
        config.update(user=user,password=password,autocommit=False)
        connection=mysql.connector.connect(**config)
        cursor=connection.cursor()
        try:
            cursor.execute("SELECT CURRENT_USER()")
            actual=str(cursor.fetchone()[0]).split("@",1)[0]
        finally:
            cursor.close()
        if actual==str(self.config.get("user")):
            connection.close()
            raise AdminWriteUnavailable("database resolved Admin writer to the runtime reader account")
        return connection

    def admin_recipe_catalog_ready(self):
        try:
            writer=self._admin_writer();cursor=writer.cursor()
            try:
                from source.database import v2_admin_recipe_catalog_schema as schema
                marker=self._fetchone(writer,"SELECT checksum,schema_hash,execution_result FROM v2_migration_history WHERE version=%s",(schema.VERSION,))
                if (not marker or marker[0]!=schema.checksum() or marker[2]!="APPLIED"
                    or marker[1]!=schema.schema_hash(writer)):return False
                cursor.execute("SHOW COLUMNS FROM v2_admin_recipe_catalog_overrides LIKE 'direct_publication'")
                if cursor.fetchone() is None:return False
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants=[str(row[0]) for row in cursor.fetchall()]
                scopes=[g.casefold().replace('`','') for g in grants]
                target=f"{self.config['database']}.v2_admin_recipe_catalog_overrides"
                for required in ("select","insert","update"):
                    if not any(target in grant and required in grant for grant in scopes):return False
                return True
            finally:cursor.close();writer.close()
        except Exception:return False

    def admin_save_recipe(self,payload,author_ref):
        """Save an Admin-authored recipe and publish it atomically via migration 009."""
        connection=self._admin_writer();locked=False
        try:
            cursor=connection.cursor()
            try:
                cursor.execute("SELECT version FROM v2_migration_history WHERE version=%s AND execution_result='APPLIED'",
                               ("009_admin_recipe_catalog",))
                if cursor.fetchone() is None:raise AdminSchemaUnavailable("Admin recipe catalog migration 009 is not installed")
                cursor.execute("SELECT GET_LOCK('goiy_admin_direct_recipe_ids',5)")
                if cursor.fetchone()[0]!=1:raise AdminDraftConflict("recipe catalog is busy",reason="catalog_lock_busy")
                locked=True
            finally:cursor.close()
            lines=self._admin_validate_ingredients(connection,payload["ingredients"])
            create_revision=False
            create_key=None;payload_hash=None
            if "recipe_id" not in payload:
                import hashlib,json
                create_key=payload["idempotency_key"]
                stable={key:value for key,value in payload.items() if key!="idempotency_key"}
                payload_hash=hashlib.sha256(json.dumps(stable,ensure_ascii=False,sort_keys=True,
                    separators=(",",":" )).encode("utf-8")).hexdigest()
                cursor=connection.cursor()
                try:
                    cursor.execute("SELECT v2_recipe_id,revision_id,create_payload_hash FROM v2_admin_recipe_catalog_overrides WHERE create_request_key=%s FOR UPDATE",(create_key,))
                    prior=cursor.fetchone()
                finally:cursor.close()
                if prior:
                    if prior[2]!=payload_hash:raise AdminDraftConflict("this create request was already used with different recipe content")
                    from source.common.catalog_ids import v2_public_id
                    connection.rollback()
                    return {"recipe_id":v2_public_id(int(prior[0])),"revision_id":int(prior[1]),"status":"VISIBLE","idempotent_replay":True}
            if "recipe_id" in payload:
                from source.common.catalog_ids import V2_OFFSET,v2_public_id
                recipe_id=payload["recipe_id"]-V2_OFFSET
                cursor=connection.cursor(dictionary=True)
                try:
                    cursor.execute("""SELECT r.id,r.revision_no,r.status,r.content_review_id,r.servings_review_id,c.direct_publication,
                               r.title,r.description,r.instructions,r.minutes
                        FROM v2_recipe_revisions r LEFT JOIN v2_admin_recipe_catalog_overrides c
                          ON c.v2_recipe_id=r.recipe_id
                        WHERE r.id=%s AND r.recipe_id=%s FOR UPDATE""",(payload["revision_id"],recipe_id))
                    row=cursor.fetchone()
                    if row is None:raise AdminDraftConflict("recipe revision was not found",reason="revision_identity_mismatch")
                    cursor.execute("""SELECT line_no,ingredient_id,quantity_raw,requirement,status,
                               quantity_review_id,scaling_review_id
                        FROM v2_recipe_ingredient_lines WHERE revision_id=%s ORDER BY line_no FOR UPDATE""",
                        (payload["revision_id"],))
                    current_lines=cursor.fetchall()
                    from source.server.admin_recipes import revision_edit_version
                    current_version=revision_edit_version(
                        revision_id=row["id"],recipe_id=recipe_id,revision_no=row["revision_no"],status=row["status"],
                        title=row["title"],description=row["description"] or "",instructions=row["instructions"],
                        minutes=row["minutes"],ingredients=[{"line_no":line["line_no"],"ingredient_id":line["ingredient_id"],
                            "quantity_raw":line["quantity_raw"],"requirement":line["requirement"],"status":line["status"],
                            "quantity_review_id":line["quantity_review_id"],"scaling_review_id":line["scaling_review_id"]}
                            for line in current_lines])
                    if current_version!=payload["expected_version"]:
                        raise AdminDraftConflict("recipe changed after it was opened; reload before saving",reason="stale_version")
                    if row["status"]=="NEEDS_VERIFICATION":
                        raise AdminDraftConflict("recipe is awaiting verification and cannot be published by a normal save",reason="revision_unverified")
                    if row["status"]=="DRAFT" and row["content_review_id"] is None and row["servings_review_id"] is None:
                        cursor.execute("SELECT status,quantity_review_id,scaling_review_id FROM v2_recipe_ingredient_lines WHERE revision_id=%s",
                                       (payload["revision_id"],))
                        if any(x["status"]!="DRAFT" or x["quantity_review_id"] is not None or x["scaling_review_id"] is not None
                               for x in cursor.fetchall()):raise AdminDraftConflict("reviewed ingredient data cannot be changed",reason="reviewed_ingredient_data")
                        revision_id=payload["revision_id"]
                        create_revision=False
                    else:
                        # Published/verified history stays immutable. Admin edits create a
                        # fresh revision and atomically point the Admin catalog at it.
                        cursor.execute("SELECT COALESCE(MAX(revision_no),0)+1 FROM v2_recipe_revisions WHERE recipe_id=%s FOR UPDATE",(recipe_id,))
                        next_revision_no=int(cursor.fetchone()[0])
                        cursor.execute("SELECT COALESCE(MAX(id),0)+1 FROM v2_recipe_revisions FOR UPDATE")
                        revision_id=int(cursor.fetchone()[0])
                        if next_revision_no>65535 or revision_id>2**64-1:raise AdminDraftConflict("recipe revision ID space exhausted")
                        cursor.execute("""INSERT INTO v2_recipe_revisions
                            (id,recipe_id,revision_no,title,description,instructions,minutes)
                            VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                            (revision_id,recipe_id,next_revision_no,payload["title"],payload["description"],payload["instructions"],payload["minutes"]))
                        create_revision=True
                finally:cursor.close()
                if not create_revision:
                    cursor=connection.cursor()
                    try:
                        cursor.execute("UPDATE v2_recipe_revisions SET title=%s,description=%s,instructions=%s,minutes=%s WHERE id=%s AND recipe_id=%s AND status='DRAFT'",
                            (payload["title"],payload["description"],payload["instructions"],payload["minutes"],revision_id,recipe_id))
                        # The revision and its lines are locked and the edit_version was
                        # checked above. MySQL rowcount is zero when these metadata fields
                        # are unchanged; ingredient-only edits must still proceed.
                        cursor.execute("DELETE FROM v2_recipe_ingredient_lines WHERE revision_id=%s AND status='DRAFT'",(revision_id,))
                    finally:cursor.close()
            else:
                cursor=connection.cursor()
                try:
                    cursor.execute("SELECT COALESCE(MAX(id),0)+1 FROM v2_recipes");recipe_id=int(cursor.fetchone()[0])
                    cursor.execute("SELECT COALESCE(MAX(id),0)+1 FROM v2_recipe_revisions");revision_id=int(cursor.fetchone()[0])
                    if not 1<=recipe_id<=2**32-1 or not 1<=revision_id<=2**64-1:raise AdminDraftConflict("recipe ID space exhausted")
                    cursor.execute("INSERT INTO v2_recipes(id,origin_kind,author_ref) VALUES(%s,'curated_new',%s)",(recipe_id,author_ref[:255]))
                    cursor.execute("""INSERT INTO v2_recipe_revisions
                        (id,recipe_id,revision_no,title,description,instructions,minutes)
                        VALUES(%s,%s,1,%s,%s,%s,%s)""",
                        (revision_id,recipe_id,payload["title"],payload["description"],payload["instructions"],payload["minutes"]))
                finally:cursor.close()
            self._admin_insert_lines(connection,revision_id,lines)
            from source.common.catalog_ids import v2_public_id
            public_id=v2_public_id(recipe_id)
            cursor=connection.cursor()
            try:
                cursor.execute("""INSERT INTO v2_admin_recipe_catalog_overrides
                    (v2_recipe_id,revision_id,role_code,direct_publication,is_visible,is_deleted,updated_by,create_request_key,create_payload_hash)
                    VALUES(%s,%s,%s,1,1,0,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE revision_id=VALUES(revision_id),role_code=VALUES(role_code),
                      direct_publication=1,is_visible=1,is_deleted=0,updated_by=VALUES(updated_by)""",
                    (recipe_id,revision_id,payload["role"],author_ref[:255],create_key,payload_hash))
            finally:cursor.close()
            connection.commit()
            return {"recipe_id":public_id,"revision_id":revision_id,"status":"VISIBLE"}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno==1146:raise AdminSchemaUnavailable("Admin recipe catalog migration 009 is not installed") from None
            if exc.errno==1062:raise AdminDraftConflict("recipe already exists; reload the list before saving again",mysql_errno=1062,reason="mysql_duplicate_key") from None
            raise
        except Exception:
            connection.rollback();raise
        finally:
            if locked:
                cursor=connection.cursor()
                try:cursor.execute("SELECT RELEASE_LOCK('goiy_admin_direct_recipe_ids')");cursor.fetchone()
                finally:cursor.close()
            connection.close()

    def admin_set_recipe_lifecycle(self,payload,author_ref):
        from source.common.catalog_ids import V2_OFFSET
        from source.server.ingredient_catalog import internal_id
        writer=self._admin_writer();connection=writer
        try:
            cur=connection.cursor(dictionary=True)
            try:
                cur.execute("SELECT version FROM v2_migration_history WHERE version=%s AND execution_result='APPLIED'",("009_admin_recipe_catalog",))
                if cur.fetchone() is None:raise AdminSchemaUnavailable("Admin recipe catalog migration 009 is not installed")
            finally:cur.close()
            public_id=payload["recipe_id"]
            legacy_id=public_id if public_id<=V2_OFFSET else None
            v2_id=None if legacy_id is not None else internal_id(public_id)
            if legacy_id is None and v2_id is None:raise ValueError("invalid recipe ID")
            cursor=connection.cursor(dictionary=True)
            try:
                if legacy_id is not None:
                    cursor.execute("SELECT id FROM recipes WHERE id=%s FOR UPDATE",(legacy_id,))
                    if cursor.fetchone() is None:raise AdminDraftConflict("recipe not found")
                    cursor.execute("SELECT id FROM v2_admin_recipe_catalog_overrides WHERE legacy_recipe_id=%s FOR UPDATE",(legacy_id,))
                    existing=cursor.fetchone()
                    if existing:
                        cursor.execute("UPDATE v2_admin_recipe_catalog_overrides SET is_visible=%s,is_deleted=%s,updated_by=%s WHERE legacy_recipe_id=%s",
                            (int(payload["is_visible"]),int(payload["is_deleted"]),author_ref[:255],legacy_id))
                    else:
                        cursor.execute("INSERT INTO v2_admin_recipe_catalog_overrides(legacy_recipe_id,is_visible,is_deleted,updated_by) VALUES(%s,%s,%s,%s)",
                            (legacy_id,int(payload["is_visible"]),int(payload["is_deleted"]),author_ref[:255]))
                else:
                    cursor.execute("SELECT id,direct_publication FROM v2_admin_recipe_catalog_overrides WHERE v2_recipe_id=%s FOR UPDATE",(v2_id,))
                    state_row=cursor.fetchone()
                    cursor.execute("SELECT id FROM v2_recipes WHERE id=%s",(v2_id,))
                    if not cursor.fetchone():raise AdminDraftConflict("recipe not found")
                    if state_row and state_row["direct_publication"]:
                        cursor.execute("SELECT revision_id FROM v2_admin_recipe_catalog_overrides WHERE v2_recipe_id=%s",(v2_id,))
                        revision_row=cursor.fetchone();revision_id=int(revision_row["revision_id"])
                    else:
                        cursor.execute("SELECT active_release_id FROM v2_calculation_settings WHERE id=1")
                        active=cursor.fetchone();active_id=active["active_release_id"] if active else None
                        cursor.execute("SELECT revision_id FROM v2_release_recipes WHERE release_id=%s AND recipe_id=%s",(active_id,v2_id))
                        active_recipe=cursor.fetchone()
                        if active_recipe is None:
                            if payload["is_visible"] and not payload["is_deleted"]:
                                raise AdminDraftConflict("recipe is not eligible for public visibility; save its content first")
                            cursor.execute("SELECT id FROM v2_recipe_revisions WHERE recipe_id=%s ORDER BY revision_no DESC LIMIT 1",(v2_id,))
                            any_revision=cursor.fetchone()
                            if any_revision is None:raise AdminDraftConflict("recipe revision not found")
                            revision_id=int(any_revision["id"])
                        else:revision_id=int(active_recipe["revision_id"])
                    if state_row:
                        cursor.execute("UPDATE v2_admin_recipe_catalog_overrides SET is_visible=%s,is_deleted=%s,updated_by=%s WHERE id=%s",
                            (int(payload["is_visible"]),int(payload["is_deleted"]),author_ref[:255],state_row["id"]))
                    else:
                        cursor.execute("INSERT INTO v2_admin_recipe_catalog_overrides(v2_recipe_id,revision_id,is_visible,is_deleted,updated_by) VALUES(%s,%s,%s,%s,%s)",
                            (v2_id,revision_id,int(payload["is_visible"]),int(payload["is_deleted"]),author_ref[:255]))
            finally:cursor.close()
            connection.commit();return {"recipe_id":public_id,"is_visible":payload["is_visible"],"is_deleted":payload["is_deleted"]}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno==1146:raise AdminSchemaUnavailable("Admin recipe catalog migration 009 is not installed") from None
            raise
        except Exception:
            connection.rollback();raise
        finally:connection.close()

    def _account_writer(self):
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2]/".env")
        user=os.getenv("MYSQL_USER_ACCOUNT_WRITER_USER")
        password=os.getenv("MYSQL_USER_ACCOUNT_WRITER_PASSWORD")
        if not user or not password:
            raise UserAccountUnavailable("dedicated user account writer is not configured")
        if user == self.config.get("user"):
            raise UserAccountUnavailable("account writes require a database account separate from the runtime reader")
        config={k:v for k,v in self.config.items() if k!="autocommit"}
        config.update(user=user,password=password,autocommit=False)
        connection=mysql.connector.connect(**config)
        cursor=connection.cursor()
        try:
            cursor.execute("SELECT CURRENT_USER()")
            actual=str(cursor.fetchone()[0]).split("@",1)[0]
        finally:
            cursor.close()
        if actual == str(self.config.get("user")):
            connection.close()
            raise UserAccountUnavailable("database resolved account writer to the runtime reader account")
        return connection

    @staticmethod
    def _validate_account_writer_grants(grants, database):
        import re
        if not grants:
            raise UserAccountUnavailable("account writer privileges are unavailable")
        target=f"{database}.v2_user_accounts".casefold()
        history=f"{database}.v2_migration_history".casefold()
        observed={target:{},history:{}}

        def split_privileges(value):
            result=[];depth=0;start=0
            for index,char in enumerate(value):
                if char=="(":depth+=1
                elif char==")":depth-=1
                elif char=="," and depth==0:
                    result.append(value[start:index].strip());start=index+1
            result.append(value[start:].strip())
            return result

        def parse_privilege(value):
            match=re.fullmatch(r"([a-z ]+)\s*\((.*?)\)",value)
            if not match:return value,None
            privilege,columns=match.groups()
            return privilege.strip(),{column.strip() for column in columns.split(",")}

        for grant in grants:
            normalized=" ".join(str(grant).replace("`","").casefold().split())
            match=re.match(r"grant\s+(.+?)\s+on\s+(.+?)\s+to\s+", normalized)
            if not match:
                raise UserAccountUnavailable("account writer has an unrecognized grant or role")
            privileges, scope=match.groups()
            if scope == "*.*":
                if privileges not in {"usage", "usage with grant option"}:
                    raise UserAccountUnavailable("account writer has privileges broader than the account table")
                continue
            if scope not in observed:
                raise UserAccountUnavailable("account writer has grants outside the account table and migration history")
            for token in split_privileges(privileges):
                privilege,columns=parse_privilege(token)
                allowed=("select" if scope==history else privilege in {"select","insert","update"})
                if not allowed:
                    raise UserAccountUnavailable("account writer has an unapproved account-table privilege")
                if privilege in observed[scope] and (observed[scope][privilege] is None or columns is None):
                    observed[scope][privilege]=None
                elif privilege not in observed[scope]:
                    observed[scope][privilege]=columns
                else:
                    observed[scope][privilege]|=columns

        required={"select":None,"insert":{"username","normalized_username","password_hash"},
                  "update":{"account_status","role","last_login_at"}}
        if observed[target]!=required or observed[history]!={"select":None}:
            raise UserAccountUnavailable("account writer requires column-limited INSERT/UPDATE plus SELECT on accounts and migration history")

    def user_account_writer_ready(self):
        try:
            from source.database import v2_user_account_schema
            connection=self._account_writer()
            try:
                cursor=connection.cursor()
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants=[str(row[0]) for row in cursor.fetchall()]
                self._validate_account_writer_grants(grants,str(self.config["database"]))
                cursor.execute("SELECT checksum,schema_hash,execution_result FROM v2_migration_history WHERE version=%s",
                               (v2_user_account_schema.VERSION,))
                row=cursor.fetchone()
                if not row or row[0]!=v2_user_account_schema.checksum() or row[2]!="APPLIED":
                    return False
                if not v2_user_account_schema.schema_hash_matches(connection,row[1]):
                    return False
                return True
            finally:
                connection.close()
        except Exception:
            return False

    def _account_write_connection(self):
        if not self.user_account_writer_ready():
            raise UserAccountUnavailable("migration 005 and minimum account writer grants are not ready")
        return self._account_writer()

    def user_register(self,payload):
        from source.server.user_accounts import hash_password
        from source.common.user_tokens import issue
        connection=self._account_write_connection()
        try:
            cursor=connection.cursor()
            # Keep the INSERT inside the writer's column-level grant. The DB
            # defaults enforce role=USER and account_status=ACTIVE.
            cursor.execute("INSERT INTO v2_user_accounts(username,normalized_username,password_hash) VALUES(%s,%s,%s)",
                           (payload["username"],payload["normalized_username"],hash_password(payload["password"])))
            user_id=int(cursor.lastrowid)
            connection.commit()
            token,claims=issue(user_id,payload["username"],"USER")
            return {"user_id":str(user_id),"username":payload["username"],"role":"USER","session_token":token,
                    "csrf_token":claims["csrf"]}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno==1062:raise UserAccountConflict("username is already registered") from None
            if exc.errno in (1142,1143,1146,1227):raise UserAccountUnavailable("account writer grant or migration is missing") from None
            raise
        finally:
            connection.close()

    def _legacy_ingredient_write_connection(self):
        connection=self._admin_writer()
        if not self.legacy_ingredient_admin_writer_ready(connection):
            connection.close()
            raise AdminWriteUnavailable("legacy ingredient overlay migration or minimum writer grants are unavailable")
        return connection

    def _validate_legacy_ingredient_name(self,connection,name,normalized_name,exclude_id,
                                         exclude_v2_id=None,ignore_v2_name=None):
        # The dedicated ingredient writer already has SELECT-only grants on
        # legacy ingredients and their overlay. Reuse it while a TCP request
        # owns a runtime pool slot (pool_size=1 must remain supported).
        rows=self._fetchall(connection,"SELECT id,name FROM ingredients ORDER BY id")
        from source.server.legacy_ingredient_overlays import read_overrides
        overrides=read_overrides(connection)
        for ingredient_id,base_name in rows:
            ingredient_id=int(ingredient_id)
            if ingredient_id==exclude_id:continue
            current=overrides.get(ingredient_id,{}).get("name_override") or base_name
            if normalize(current)==normalized_name:
                raise AdminIngredientConflict("an ingredient with this normalized legacy name already exists")
        sql="SELECT normalized_name,legacy_ingredient_id,id FROM v2_ingredients"
        params=()
        if exclude_v2_id is not None:
            sql+=" WHERE id<>%s";params=(exclude_v2_id,)
        v2_names=self._fetchall(connection,sql,params)
        if any(normalize(str(row[0]))==normalized_name
               and not (exclude_id is not None and row[1] is not None and int(row[1])==exclude_id)
               and not (ignore_v2_name is not None and normalize(str(row[0]))==ignore_v2_name)
               for row in v2_names):
            raise AdminIngredientConflict("an ingredient with this normalized name already exists in v2")

    def admin_update_legacy_ingredient(self,payload,author):
        connection=self._legacy_ingredient_write_connection();locked=False;committed=False
        try:
            cursor=connection.cursor()
            cursor.execute("SELECT GET_LOCK('goiy_admin_ingredient_ids',5)")
            if cursor.fetchone()[0]!=1:raise AdminIngredientConflict("ingredient catalog is busy")
            locked=True
            row=self._fetchone(connection,"SELECT name FROM ingredients WHERE id=%s",(payload["ingredient_id"],))
            from source.server.legacy_ingredient_overlays import display_name,read_overrides
            current_overrides=read_overrides(connection,{payload["ingredient_id"]})
            if not row:raise AdminIngredientConflict("legacy ingredient not found")
            current_name=normalize(str(display_name(row[0],current_overrides.get(payload["ingredient_id"]))))
            self._validate_legacy_ingredient_name(connection,payload["name"],payload["normalized_name"],
                payload["ingredient_id"],ignore_v2_name=current_name)
            cursor.execute("""INSERT INTO v2_admin_legacy_ingredient_overrides
                (ingredient_id,name_override,normalized_name,is_active,updated_by) VALUES(%s,%s,%s,1,%s)
                ON DUPLICATE KEY UPDATE name_override=VALUES(name_override),normalized_name=VALUES(normalized_name),updated_by=VALUES(updated_by)""",
                (payload["ingredient_id"],payload["name"],payload["normalized_name"],str(author)[:255]))
            connection.commit();committed=True
            return {"ingredient_id":payload["ingredient_id"],"name":payload["name"],"source":"LEGACY","status":"SAVED"}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno==1062:raise AdminIngredientConflict("legacy ingredient name conflicts with the current catalog") from None
            if exc.errno in (1142,1146,1227):raise AdminWriteUnavailable("legacy ingredient overlay grant or migration is missing") from None
            raise
        except Exception:
            if not committed:connection.rollback()
            raise
        finally:
            if locked:
                try:self._fetchone(connection,"SELECT RELEASE_LOCK('goiy_admin_ingredient_ids')")
                except mysql.connector.Error:pass
            connection.close()

    def admin_set_legacy_ingredient_active(self,payload,author):
        connection=self._legacy_ingredient_write_connection();committed=False
        try:
            reader=self.connect()
            try:row=self._fetchone(reader,"SELECT id FROM ingredients WHERE id=%s",(payload["ingredient_id"],))
            finally:reader.close()
            if not row:raise AdminIngredientConflict("legacy ingredient not found")
            cursor=connection.cursor()
            try:
                cursor.execute("""INSERT INTO v2_admin_legacy_ingredient_overrides
                    (ingredient_id,is_active,updated_by) VALUES(%s,%s,%s)
                    ON DUPLICATE KEY UPDATE is_active=VALUES(is_active),updated_by=VALUES(updated_by)""",
                    (payload["ingredient_id"],int(payload["is_active"]),str(author)[:255]))
            finally:cursor.close()
            connection.commit();committed=True
            return {"ingredient_id":payload["ingredient_id"],"is_active":payload["is_active"],"source":"LEGACY"}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno in (1142,1146,1227):raise AdminWriteUnavailable("legacy ingredient overlay grant or migration is missing") from None
            raise
        except Exception:
            if not committed:connection.rollback()
            raise
        finally:connection.close()

    def user_login(self,payload):
        from source.server.user_accounts import verify_password
        from source.common.user_tokens import issue
        connection=self._account_write_connection()
        try:
            cursor=connection.cursor()
            cursor.execute("SELECT user_id,username,password_hash,role,account_status FROM v2_user_accounts WHERE normalized_username=%s",
                           (payload["normalized_username"],))
            row=cursor.fetchone()
            valid=verify_password(payload["password"],row[2] if row else "")
            if not row or not valid:raise UserAccountUnauthorized("invalid username or password")
            if row[4]!="ACTIVE":raise UserAccountUnauthorized("account is locked")
            cursor.execute("UPDATE v2_user_accounts SET last_login_at=UTC_TIMESTAMP(6) WHERE user_id=%s",(row[0],))
            connection.commit()
            token,claims=issue(int(row[0]),row[1],row[3])
            return {"user_id":str(row[0]),"username":row[1],"role":row[3],"session_token":token,
                    "csrf_token":claims["csrf"]}
        finally:
            connection.close()

    def user_session(self,claims):
        connection=self._account_write_connection()
        try:
            cursor=connection.cursor()
            cursor.execute("SELECT username,role,account_status FROM v2_user_accounts WHERE user_id=%s",(claims["uid"],))
            row=cursor.fetchone()
            if not row or row[0]!=claims["sub"] or row[1]!=claims["role"] or row[2]!="ACTIVE":
                raise UserAccountUnauthorized("account is locked or no longer available")
            return {"user_id":str(claims["uid"]),"username":row[0],"role":row[1],"csrf_token":claims["csrf"]}
        finally:
            connection.close()

    def admin_list_users(self,connection,query,limit,offset):
        normalized=normalize(query)
        escaped=normalized.replace("\\","\\\\").replace("%","\\%").replace("_","\\_")
        pattern=f"%{escaped}%"
        writer=self._account_write_connection()
        try:
            where=" WHERE normalized_username LIKE %s ESCAPE '\\\\' OR username LIKE %s ESCAPE '\\\\'" if normalized else ""
            params=(pattern,pattern) if normalized else ()
            total=int(self._fetchone(writer,f"SELECT COUNT(*) FROM v2_user_accounts{where}",params)[0])
            rows=self._fetchall(writer,f"SELECT user_id,username,role,account_status,created_at,last_login_at FROM v2_user_accounts{where} ORDER BY created_at DESC,user_id DESC LIMIT %s OFFSET %s",
                                (*params,limit,offset))
            items=[{"user_id":str(r[0]),"username":r[1],"role":r[2],"account_status":r[3],
                    "created_at":r[4].isoformat() if r[4] else None,"last_login_at":r[5].isoformat() if r[5] else None} for r in rows]
            return {"items":items,"total":total,"limit":limit,"offset":offset,"account_admin_ready":True}
        finally:
            writer.close()

    def admin_set_user_status(self,payload):
        connection=self._account_write_connection()
        try:
            cursor=connection.cursor()
            cursor.execute("UPDATE v2_user_accounts SET account_status=%s WHERE user_id=%s",
                           (payload["account_status"],payload["user_id"]))
            if cursor.rowcount==0:
                cursor.execute("SELECT user_id FROM v2_user_accounts WHERE user_id=%s",(payload["user_id"],))
                if cursor.fetchone() is None:raise UserAccountConflict("user account not found")
            connection.commit()
            return {"user_id":str(payload["user_id"]),"account_status":payload["account_status"]}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno in (1142,1146,1227):raise UserAccountUnavailable("account writer grant or migration is missing") from None
            raise
        finally:
            connection.close()

    def admin_set_user_role(self,payload):
        connection=self._account_write_connection()
        try:
            cursor=connection.cursor()
            cursor.execute("UPDATE v2_user_accounts SET role=%s WHERE user_id=%s",(payload["role"],payload["user_id"]))
            if cursor.rowcount==0:
                cursor.execute("SELECT user_id FROM v2_user_accounts WHERE user_id=%s",(payload["user_id"],))
                if cursor.fetchone() is None:raise UserAccountConflict("user account not found")
            connection.commit()
            return {"user_id":str(payload["user_id"]),"role":payload["role"]}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno in (1142,1146,1227):raise UserAccountUnavailable("account writer grant or migration is missing") from None
            raise
        finally:
            connection.close()

    def _admin_validate_ingredients(self,connection,lines):
        """Map stable catalog IDs to v2 storage IDs inside the draft transaction."""
        from source.common.catalog_ids import UINT32_MAX
        from source.server.ingredient_catalog import internal_id
        from source.server.legacy_ingredient_overlays import display_name,read_overrides

        ids=sorted({line["ingredient_id"] for line in lines})
        legacy_ids=[iid for iid in ids if 1<=iid<=UINT32_MAX]
        v2_public={iid:internal_id(iid) for iid in ids if iid>UINT32_MAX}
        active_v2={}
        if v2_public:
            internal_ids=sorted(i for i in v2_public.values() if i is not None)
            if internal_ids:
                marks=",".join("%s" for _ in internal_ids)
                try:
                    rows=self._fetchall(connection,f"""SELECT i.id,COALESCE(s.is_active,1)
                        FROM v2_ingredients i LEFT JOIN v2_ingredient_admin_state s ON s.ingredient_id=i.id
                        WHERE i.id IN ({marks})""",tuple(internal_ids))
                except mysql.connector.Error as exc:
                    if exc.errno!=1146:raise
                    rows=[(iid,1) for (iid,) in self._fetchall(connection,
                        f"SELECT id FROM v2_ingredients WHERE id IN ({marks})",tuple(internal_ids))]
                active_v2={int(iid):bool(active) for iid,active in rows}

        legacy_map={}
        if legacy_ids:
            marks=",".join("%s" for _ in legacy_ids)
            base=self._fetchall(connection,f"SELECT id,name FROM ingredients WHERE id IN ({marks})",tuple(legacy_ids))
            overrides=read_overrides(connection,{int(iid) for iid,_ in base})
            for iid,name in base:
                iid=int(iid);override=overrides.get(iid)
                if override and not override["is_active"]:continue
                legacy_map[iid]=display_name(name,override)
            if len(legacy_map)!=len(legacy_ids):
                raise ValueError("ingredient is missing or inactive in the shared catalog")

            # Reuse a persisted identity crosswalk where available. New links
            # are metadata only and remain NEEDS_VERIFICATION; they do not
            # approve or publish an ingredient or recipe.
            marks=",".join("%s" for _ in legacy_ids)
            linked={int(legacy):int(v2id) for v2id,legacy in self._fetchall(connection,
                f"SELECT id,legacy_ingredient_id FROM v2_ingredients WHERE legacy_ingredient_id IN ({marks})",tuple(legacy_ids))}
            missing=[iid for iid in legacy_ids if iid not in linked]
            if missing:
                lock=self._fetchone(connection,"SELECT GET_LOCK('goiy_admin_ingredient_ids',5)")
                if not lock or lock[0]!=1:raise AdminDraftConflict("ingredient catalog is busy")
                try:
                    for iid in missing:
                        name=legacy_map[iid]
                        normalized=normalize(name)
                        next_id=int(self._fetchone(connection,"SELECT COALESCE(MAX(id),0)+1 FROM v2_ingredients")[0])
                        if not 1<=next_id<=UINT32_MAX:raise AdminDraftConflict("v2 ingredient identity space is exhausted")
                        cursor=connection.cursor()
                        try:
                            # The schema default is NEEDS_VERIFICATION. Omit that
                            # column so the dedicated writer does not need an
                            # INSERT grant beyond the catalog identity columns.
                            cursor.execute("""INSERT INTO v2_ingredients
                                (id,legacy_ingredient_id,canonical_name,normalized_name)
                                VALUES(%s,%s,%s,%s)""",(next_id,iid,name,normalized))
                        finally:cursor.close()
                        linked[iid]=next_id
                finally:
                    self._fetchone(connection,"SELECT RELEASE_LOCK('goiy_admin_ingredient_ids')")

        mapped=[]
        for line in lines:
            iid=line["ingredient_id"]
            if iid in legacy_map:
                storage_id=linked[iid]
            else:
                storage_id=v2_public.get(iid)
                if storage_id is None or not active_v2.get(storage_id,False):
                    raise ValueError("ingredient is missing or inactive in the shared catalog")
            mapped.append({**line,"ingredient_id":storage_id})
        return mapped

    @staticmethod
    def _admin_insert_lines(connection,revision_id,lines):
        cursor=connection.cursor()
        try:
            cursor.executemany("""INSERT INTO v2_recipe_ingredient_lines
                (revision_id,line_no,ingredient_id,quantity_raw,amount_kind,requirement,purpose,
                 measurement_basis)
                VALUES(%s,%s,%s,%s,'unknown',%s,'unknown','unknown')""",
                [(revision_id,n,line["ingredient_id"],line["quantity_raw"],line["requirement"])
                 for n,line in enumerate(lines,1)])
        finally:cursor.close()

    def admin_list_ingredients(self,connection,query,limit=20,offset=0,active_only=False,catalog="shared"):
        writer=self._admin_writer()
        try:
            needle=ingredient_search_normalize(query.strip())
            v2_rows=[]
            state_exists=bool(self._fetchone(writer,"SHOW TABLES LIKE 'v2_ingredient_admin_state'"))
            state_join="LEFT JOIN v2_ingredient_admin_state s ON s.ingredient_id=i.id" if state_exists else ""
            active_expr="COALESCE(s.is_active,1)" if state_exists else "1"
            v2_rows=self._fetchall(writer,f"""SELECT i.id,i.legacy_ingredient_id,i.canonical_name,i.normalized_name,
                    i.identity_status,{active_expr},i.review_decision_id,i.evidence_set_id,
                    COALESCE(u.uses,0)
                FROM v2_ingredients i {state_join}
                LEFT JOIN (SELECT ingredient_id,COUNT(DISTINCT revision_id) uses
                           FROM v2_recipe_ingredient_lines GROUP BY ingredient_id) u ON u.ingredient_id=i.id
                ORDER BY i.normalized_name,i.id""")
            if catalog=="v2":
                filtered=[]
                for iid,legacy_id,name,normalized_name,identity_status,is_active,review_id,evidence_id,uses in v2_rows:
                    # V2 imports remain available to recipe revision history,
                    # but the ordinary Admin catalog includes only ingredients
                    # explicitly created through Admin. Legacy crosswalk rows
                    # are represented by their original legacy business ID.
                    admin_managed=(legacy_id is None and identity_status=="DRAFT"
                                   and review_id is None and evidence_id is None)
                    if not admin_managed:continue
                    if active_only and not is_active:continue
                    if needle and needle not in ingredient_search_normalize(name):continue
                    from source.common.catalog_ids import v2_public_id
                    try:public_id=int(legacy_id) if legacy_id is not None else v2_public_id(int(iid))
                    except ValueError:continue
                    filtered.append({"ingredient_id":public_id,"name":name,"normalized_name":normalized_name,"identity_status":identity_status,
                        "is_active":bool(is_active),"usage_count":int(uses),
                        "can_edit":identity_status in {"DRAFT","NEEDS_VERIFICATION"} and review_id is None and evidence_id is None,
                        "can_manage":True})
            else:
                from source.server.ingredient_catalog import merge_catalog
                legacy_rows=self._legacy_ingredient_catalog(connection,query="",include_inactive=True)
                legacy_usage={int(iid):int(count) for iid,count in self._fetchall(
                    connection,"SELECT ingredient_id,COUNT(DISTINCT recipe_id) FROM recipe_ingredients GROUP BY ingredient_id")}
                v2_rows_for_merge=[]
                for iid,legacy_id,name,norm,status,is_active,review_id,evidence_id,uses in v2_rows:
                    admin_managed=(legacy_id is None and status=="DRAFT"
                                   and review_id is None and evidence_id is None)
                    if legacy_id is None and not admin_managed:continue
                    v2_rows_for_merge.append({"id":int(iid),"legacy_ingredient_id":legacy_id,"name":name,
                        "normalized_name":norm,"identity_status":status,"is_active":bool(is_active),
                        "usage_count":int(uses),"can_edit":status in {"DRAFT","NEEDS_VERIFICATION"}
                            and review_id is None and evidence_id is None,"can_manage":True})
                legacy_usage_by_id={int(iid):int(count) for iid,count in legacy_usage.items()}
                for row in legacy_rows:row["usage_count"]=legacy_usage_by_id.get(int(row["id"]),0)
                filtered=merge_catalog(legacy_rows,v2_rows_for_merge,active_only=active_only,query=query)
            legacy_ready=self.legacy_ingredient_admin_writer_ready(writer)
            ingredient_ready=self.admin_ingredient_writer_ready()
            for item in filtered:
                item["can_manage"]=legacy_ready if item["ingredient_id"]<=2**32-1 else ingredient_ready
                item["can_edit"]=item["can_manage"] and (item["ingredient_id"]<=2**32-1 or item.get("can_edit",False))
            if catalog=="v2":
                filtered=[item for item in filtered if item["ingredient_id"]>2**32-1]
            total=len(filtered)
            return {"items":filtered[offset:offset+limit],"total":total,"limit":limit,"offset":offset,
                    "catalog":catalog,"ingredient_admin_ready":ingredient_ready,
                    "legacy_ingredient_admin_ready":legacy_ready}
        finally:
            writer.close()

    def legacy_ingredient_admin_writer_ready(self,connection=None):
        owned=connection is None
        writer=connection or self._admin_writer()
        try:
            from source.database import v2_legacy_ingredient_admin_schema as schema
            from source.web.setup_admin import validate_writer_grants
            cursor=writer.cursor()
            try:
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                validate_writer_grants([str(row[0]) for row in cursor.fetchall()],legacy_ingredient_admin=True)
                cursor.execute("SELECT checksum,schema_hash,execution_result FROM v2_migration_history WHERE version=%s",(schema.VERSION,))
                row=cursor.fetchone()
                if not row or row[0]!=schema.checksum() or row[2]!="APPLIED":return False
                if schema.schema_hash(writer)!=row[1]:return False
                return True
            finally:
                cursor.close()
        except Exception:
            return False
        finally:
            if owned:writer.close()

    def admin_ingredient_writer_ready(self):
        try:
            from source.database import v2_ingredient_admin_schema
            from source.web.setup_admin import validate_writer_grants
            connection=self._admin_writer()
            try:
                cursor=connection.cursor()
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                validate_writer_grants([str(row[0]) for row in cursor.fetchall()],ingredient_admin=True)
                cursor.execute("SELECT checksum,schema_hash,execution_result FROM v2_migration_history WHERE version=%s",
                    (v2_ingredient_admin_schema.VERSION,))
                row=cursor.fetchone()
                if not row or row[0]!=v2_ingredient_admin_schema.checksum() or row[2]!="APPLIED":return False
                if v2_ingredient_admin_schema.schema_hash(connection)!=row[1]:return False
                cursor.close()
                return True
            finally:
                connection.close()
        except Exception:
            return False

    def _ingredient_write_connection(self):
        if not self.admin_ingredient_writer_ready():
            raise AdminWriteUnavailable("ingredient Admin schema and minimum writer grants are not ready")
        return self._admin_writer()

    def _ingredient_duplicate(self,connection,normalized_name,exclude_id=None):
        sql="SELECT id FROM v2_ingredients WHERE normalized_name=%s"
        params=[normalized_name]
        if exclude_id is not None:
            sql+=" AND id<>%s";params.append(exclude_id)
        sql+=" LIMIT 1 FOR UPDATE"
        return self._fetchone(connection,sql,tuple(params))

    def admin_create_ingredient(self,payload):
        connection=self._ingredient_write_connection();locked=False;committed=False
        try:
            cursor=connection.cursor()
            cursor.execute("SELECT GET_LOCK('goiy_admin_ingredient_ids',5)")
            if cursor.fetchone()[0]!=1:raise AdminIngredientConflict("ingredient catalog is busy")
            locked=True
            if self._ingredient_duplicate(connection,payload["normalized_name"]):
                raise AdminIngredientConflict("an ingredient with this Vietnamese-normalized name already exists")
            self._validate_legacy_ingredient_name(connection,payload["name"],payload["normalized_name"],None)
            cursor.execute("SELECT COALESCE(MAX(id),0)+1 FROM v2_ingredients")
            ingredient_id=int(cursor.fetchone()[0])
            if not 1<=ingredient_id<=2**32-1:raise AdminIngredientConflict("no available public ingredient ID")
            # DRAFT here marks a deliberate Admin catalog addition. Imported
            # identities remain NEEDS_VERIFICATION and stay out of User/Admin
            # catalogs until they are explicitly managed.
            cursor.execute("INSERT INTO v2_ingredients(id,canonical_name,normalized_name,identity_status) VALUES(%s,%s,%s,'DRAFT')",
                (ingredient_id,payload["name"],payload["normalized_name"]))
            cursor.execute("INSERT INTO v2_ingredient_admin_state(ingredient_id,is_active) VALUES(%s,1)",(ingredient_id,))
            connection.commit();committed=True
            from source.common.catalog_ids import v2_public_id
            return {"ingredient_id":v2_public_id(ingredient_id),"name":payload["name"],"normalized_name":payload["normalized_name"],
                    "identity_status":"DRAFT","is_active":True,"usage_count":0}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno==1062:raise AdminIngredientConflict("ingredient name or ID already exists") from None
            if exc.errno in (1142,1146,1227):raise AdminWriteUnavailable("ingredient writer grant or migration is missing") from None
            raise
        except Exception:
            if not committed:connection.rollback()
            raise
        finally:
            if locked:
                try:self._fetchone(connection,"SELECT RELEASE_LOCK('goiy_admin_ingredient_ids')")
                except mysql.connector.Error:pass
            connection.close()

    def admin_update_ingredient(self,payload):
        from source.common.catalog_ids import UINT32_MAX
        if payload["ingredient_id"]<=UINT32_MAX:
            return self.admin_update_legacy_ingredient(payload,"admin")
        from source.server.ingredient_catalog import internal_id
        storage_id=internal_id(payload["ingredient_id"])
        if storage_id is None:raise AdminIngredientConflict("ingredient not found")
        connection=self._ingredient_write_connection();locked=False;committed=False
        try:
            cursor=connection.cursor()
            cursor.execute("SELECT GET_LOCK('goiy_admin_ingredient_ids',5)")
            if cursor.fetchone()[0]!=1:raise AdminIngredientConflict("ingredient catalog is busy")
            locked=True
            row=self._fetchone(connection,"SELECT identity_status,review_decision_id,evidence_set_id,legacy_ingredient_id FROM v2_ingredients WHERE id=%s FOR UPDATE",
                (storage_id,))
            if not row:raise AdminIngredientConflict("ingredient not found")
            if row[3] is not None:raise AdminIngredientConflict("linked ingredients must be managed through their shared catalog ID")
            if row[0] not in {"DRAFT","NEEDS_VERIFICATION"} or row[1] is not None or row[2] is not None:
                raise AdminIngredientConflict("reviewed ingredients or ingredients with attached evidence cannot be renamed")
            if self._ingredient_duplicate(connection,payload["normalized_name"],storage_id):
                raise AdminIngredientConflict("an ingredient with this Vietnamese-normalized name already exists")
            self._validate_legacy_ingredient_name(connection,payload["name"],payload["normalized_name"],None,storage_id)
            cursor.execute("UPDATE v2_ingredients SET canonical_name=%s,normalized_name=%s WHERE id=%s AND identity_status IN ('DRAFT','NEEDS_VERIFICATION') AND review_decision_id IS NULL AND evidence_set_id IS NULL",
                (payload["name"],payload["normalized_name"],storage_id))
            if cursor.rowcount!=1:raise AdminIngredientConflict("ingredient is no longer editable")
            connection.commit();committed=True
            return {"ingredient_id":payload["ingredient_id"],"name":payload["name"],
                    "normalized_name":payload["normalized_name"],"identity_status":row[0]}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno==1062:raise AdminIngredientConflict("ingredient name or ID already exists") from None
            if exc.errno in (1142,1146,1227):raise AdminWriteUnavailable("ingredient writer grant or migration is missing") from None
            raise
        except Exception:
            if not committed:connection.rollback()
            raise
        finally:
            if locked:
                try:self._fetchone(connection,"SELECT RELEASE_LOCK('goiy_admin_ingredient_ids')")
                except mysql.connector.Error:pass
            connection.close()

    def admin_set_ingredient_active(self,payload):
        from source.common.catalog_ids import UINT32_MAX
        if payload["ingredient_id"]<=UINT32_MAX:
            return self.admin_set_legacy_ingredient_active(payload,"admin")
        from source.server.ingredient_catalog import internal_id
        storage_id=internal_id(payload["ingredient_id"])
        if storage_id is None:raise AdminIngredientConflict("ingredient not found")
        connection=self._ingredient_write_connection();committed=False
        try:
            cursor=connection.cursor()
            row=self._fetchone(connection,"SELECT id,legacy_ingredient_id FROM v2_ingredients WHERE id=%s FOR UPDATE",(storage_id,))
            if not row:raise AdminIngredientConflict("ingredient not found")
            if row[1] is not None:raise AdminIngredientConflict("linked ingredients must be managed through their shared catalog ID")
            cursor.execute("INSERT INTO v2_ingredient_admin_state(ingredient_id,is_active) VALUES(%s,%s) ON DUPLICATE KEY UPDATE is_active=VALUES(is_active)",
                (storage_id,int(payload["is_active"])))
            connection.commit();committed=True
            return {"ingredient_id":payload["ingredient_id"],"is_active":payload["is_active"]}
        except mysql.connector.Error as exc:
            connection.rollback()
            if exc.errno in (1142,1146,1227):raise AdminWriteUnavailable("ingredient writer grant or migration is missing") from None
            raise
        except Exception:
            if not committed:connection.rollback()
            raise
        finally:
            connection.close()

    def admin_create_draft(self,payload,author_ref):
        connection=self._admin_writer();locked=False
        try:
            cursor=connection.cursor()
            try:
                cursor.execute("SELECT GET_LOCK('goiy_admin_draft_ids',5)")
                if cursor.fetchone()[0]!=1:raise AdminDraftConflict("draft ID allocator is busy")
                locked=True
                cursor.execute("SHOW COLUMNS FROM v2_recipe_revisions LIKE 'description'")
                if cursor.fetchone() is None:raise AdminSchemaUnavailable("revision description column migration is required")
            finally:cursor.close()
            lines=self._admin_validate_ingredients(connection,payload["ingredients"])
            cursor=connection.cursor()
            try:
                cursor.execute("SELECT COALESCE(MAX(id),0)+1 FROM v2_recipes")
                recipe_id=int(cursor.fetchone()[0])
                cursor.execute("SELECT COALESCE(MAX(id),0)+1 FROM v2_recipe_revisions")
                revision_id=int(cursor.fetchone()[0])
                if not 1<=recipe_id<=2**32-1 or not 1<=revision_id<=2**64-1:
                    raise AdminDraftConflict("v2 identity space is exhausted")
                cursor.execute("INSERT INTO v2_recipes(id,origin_kind,author_ref) VALUES(%s,'curated_new',%s)",(recipe_id,author_ref[:255]))
                cursor.execute("""INSERT INTO v2_recipe_revisions
                    (id,recipe_id,revision_no,title,description,instructions,minutes)
                    VALUES(%s,%s,1,%s,%s,%s,%s)""",
                    (revision_id,recipe_id,payload["title"],payload["description"],payload["instructions"],payload["minutes"]))
                self._admin_insert_lines(connection,revision_id,lines)
                connection.commit()
                return {"recipe_id":recipe_id,"revision_id":revision_id,"revision_no":1,"status":"DRAFT"}
            finally:cursor.close()
        except Exception:
            connection.rollback()
            raise
        finally:
            if locked:
                cur=connection.cursor()
                try:
                    cur.execute("SELECT RELEASE_LOCK('goiy_admin_draft_ids')")
                    cur.fetchone()
                finally:cur.close()
            connection.close()

    def admin_update_draft(self,payload):
        connection=self._admin_writer()
        try:
            cursor=connection.cursor(dictionary=True)
            try:
                cursor.execute("SHOW COLUMNS FROM v2_recipe_revisions LIKE 'description'")
                if cursor.fetchone() is None:raise AdminSchemaUnavailable("revision description column migration is required")
                cursor.execute("""SELECT r.status,r.content_review_id,r.servings_review_id,
                    EXISTS(SELECT 1 FROM v2_release_recipes x WHERE x.revision_id=r.id) AS released
                    FROM v2_recipe_revisions r WHERE r.id=%s FOR UPDATE""",(payload["revision_id"],))
                row=cursor.fetchone()
                if (row is None or row["status"]!="DRAFT" or row["content_review_id"] is not None
                        or row["servings_review_id"] is not None or row["released"]):
                    raise AdminDraftConflict("only unpublished DRAFT revisions without review pointers are editable")
                cursor.execute("SELECT status,quantity_review_id,scaling_review_id FROM v2_recipe_ingredient_lines WHERE revision_id=%s",(payload["revision_id"],))
                if any(line["status"]!="DRAFT" or line["quantity_review_id"] is not None
                       or line["scaling_review_id"] is not None for line in cursor.fetchall()):
                    raise AdminDraftConflict("reviewed ingredient lines cannot be edited as a draft")
            finally:cursor.close()
            lines=self._admin_validate_ingredients(connection,payload["ingredients"])
            cursor=connection.cursor()
            try:
                cursor.execute("""UPDATE v2_recipe_revisions SET title=%s,description=%s,instructions=%s,minutes=%s
                    WHERE id=%s AND status='DRAFT'""",(payload["title"],payload["description"],payload["instructions"],
                    payload["minutes"],payload["revision_id"]))
                if cursor.rowcount!=1:raise AdminDraftConflict("draft changed while being edited")
                cursor.execute("DELETE FROM v2_recipe_ingredient_lines WHERE revision_id=%s AND status='DRAFT'",(payload["revision_id"],))
                self._admin_insert_lines(connection,payload["revision_id"],lines)
                connection.commit()
                return {"revision_id":payload["revision_id"],"status":"DRAFT"}
            finally:cursor.close()
        except Exception:
            connection.rollback()
            raise
        finally:connection.close()

    @staticmethod
    def _image_writer_grants(connection, database):
        grants = [str(row[0]) for row in MySQLRepository._fetchall(connection, "SHOW GRANTS FOR CURRENT_USER()")]
        target = f"ON `{database}`.`v2_recipe_image_overrides`".upper()
        for grant in grants:
            upper = grant.upper()
            if target not in upper:
                continue
            privilege = upper.split("GRANT ", 1)[1].split(" ON ", 1)[0]
            available = {value.strip().split("(", 1)[0] for value in privilege.split(",")}
            if {"SELECT", "INSERT", "UPDATE", "DELETE"} <= available:
                return True
        return False

    def admin_recipe_image_ready(self, connection):
        from source.database import v2_recipe_image_schema
        try:
            marker = self._fetchone(connection,
                "SELECT checksum,schema_hash,execution_result FROM v2_migration_history WHERE version=%s",
                (v2_recipe_image_schema.VERSION,))
            if (not marker or marker[0] != v2_recipe_image_schema.checksum() or marker[2] != "APPLIED"
                    or not v2_recipe_image_schema.schema_hash_matches(connection, marker[1])):
                return False
            # Public recipe pages use the SELECT-only runtime account to resolve image overrides.
            self._fetchall(connection, "SELECT recipe_id FROM v2_recipe_image_overrides LIMIT 0")
            writer = self._admin_writer()
            try:
                return self._image_writer_grants(writer, self.config["database"])
            finally:
                writer.close()
        except Exception:
            return False

    def admin_get_recipe_image(self, connection, recipe_id):
        from source.common.catalog_ids import valid_public_id, UINT32_MAX, V2_OFFSET
        if not valid_public_id(recipe_id):
            return None
        ready = self.admin_recipe_image_ready(connection)
        result = {"recipe_id": recipe_id, "ready": ready, "image": None}
        if not ready:
            return result
        row = self._fetchone(connection, """SELECT catalog_kind,storage_key,media_type,byte_size,width,height,sha256,updated_at
            FROM v2_recipe_image_overrides WHERE recipe_id=%s""", (recipe_id,))
        if row:
            expected_kind = "legacy" if recipe_id <= UINT32_MAX else "v2"
            if row[0] != expected_kind:
                raise AdminRecipeImageUnavailable("image metadata identity does not match catalog ID")
            result["image"] = {"storage_key": row[1], "media_type": row[2], "byte_size": int(row[3]),
                "width": int(row[4]), "height": int(row[5]), "sha256": row[6],
                "updated_at": row[7].isoformat() if row[7] else None}
        return result

    def admin_set_recipe_image(self, reader_connection, payload, admin):
        from source.common.catalog_ids import valid_public_id, UINT32_MAX, V2_OFFSET
        image = payload
        if not valid_public_id(image["recipe_id"]):
            raise ValueError("invalid public recipe ID")
        kind = "legacy" if image["recipe_id"] <= UINT32_MAX else "v2"
        rid = image["recipe_id"]
        if kind == "legacy":
            exists = self._fetchone(reader_connection, "SELECT id FROM recipes WHERE id=%s", (rid,))
            legacy_recipe_id, v2_recipe_id = rid, None
        else:
            exists = self._fetchone(reader_connection, "SELECT id FROM v2_recipes WHERE id=%s AND legacy_recipe_id IS NULL",
                                    (rid - V2_OFFSET,))
            legacy_recipe_id, v2_recipe_id = None, rid - V2_OFFSET
        if exists is None:
            raise AdminDraftConflict("recipe no longer exists")
        connection = self._admin_writer()
        try:
            if not self._image_writer_grants(connection, self.config["database"]):
                raise AdminRecipeImageUnavailable("image writer grants are unavailable")
            old = self._fetchone(connection, "SELECT storage_key FROM v2_recipe_image_overrides WHERE recipe_id=%s FOR UPDATE", (rid,))
            cursor = connection.cursor()
            try:
                params=(kind,legacy_recipe_id,v2_recipe_id,image["storage_key"],image["media_type"],image["byte_size"],
                    image["width"],image["height"],image["sha256"],str(admin)[:255])
                if old:
                    cursor.execute("""UPDATE v2_recipe_image_overrides SET catalog_kind=%s,legacy_recipe_id=%s,v2_recipe_id=%s,
                        storage_key=%s,media_type=%s,byte_size=%s,width=%s,height=%s,sha256=%s,updated_by=%s
                        WHERE recipe_id=%s""",params+(rid,))
                else:
                    cursor.execute("""INSERT INTO v2_recipe_image_overrides
                        (recipe_id,catalog_kind,legacy_recipe_id,v2_recipe_id,storage_key,media_type,byte_size,width,height,sha256,updated_by)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(rid,*params))
            finally:
                cursor.close()
            connection.commit()
            return {"recipe_id": rid, "storage_key": image["storage_key"], "previous_storage_key": old[0] if old else None}
        except mysql.connector.Error as exc:
            if exc.errno == 1146:
                connection.rollback()
                raise AdminRecipeImageSchemaUnavailable("recipe image migration is not installed") from exc
            connection.rollback()
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def admin_remove_recipe_image(self, recipe_id):
        from source.common.catalog_ids import valid_public_id
        if not valid_public_id(recipe_id):
            raise ValueError("invalid public recipe ID")
        connection = self._admin_writer()
        try:
            if not self._image_writer_grants(connection, self.config["database"]):
                raise AdminRecipeImageUnavailable("image writer grants are unavailable")
            old = self._fetchone(connection, "SELECT storage_key FROM v2_recipe_image_overrides WHERE recipe_id=%s FOR UPDATE", (recipe_id,))
            cursor = connection.cursor()
            try:
                cursor.execute("DELETE FROM v2_recipe_image_overrides WHERE recipe_id=%s", (recipe_id,))
            finally:
                cursor.close()
            connection.commit()
            return {"recipe_id": recipe_id, "removed": old is not None,
                    "previous_storage_key": old[0] if old else None}
        except mysql.connector.Error as exc:
            if exc.errno == 1146:
                connection.rollback()
                raise AdminRecipeImageSchemaUnavailable("recipe image migration is not installed") from exc
            connection.rollback()
            raise
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def public_recipe_image(self, connection, recipe_id):
        from source.common.catalog_ids import valid_public_id, V2_OFFSET
        if not valid_public_id(recipe_id):
            return None
        if recipe_id > V2_OFFSET:
            from source.server.mysql_recipe_catalog import load_catalog
            if recipe_id not in load_catalog(connection).details:
                return None
        elif self.get_recipe(connection, recipe_id) is None:
            return None
        try:
            row = self._fetchone(connection, """SELECT catalog_kind,storage_key,media_type,byte_size,width,height,sha256
                FROM v2_recipe_image_overrides WHERE recipe_id=%s""", (recipe_id,))
        except mysql.connector.Error as exc:
            if exc.errno == 1146:
                return None
            raise
        if row is None:
            return None
        expected_kind = "v2" if recipe_id > V2_OFFSET else "legacy"
        if row[0] != expected_kind:
            return None
        return {"recipe_id": recipe_id, "storage_key": row[1], "media_type": row[2], "byte_size": int(row[3]),
                "width": int(row[4]), "height": int(row[5]), "sha256": row[6]}

    def _admin_review_write(self, function, payload, reviewer):
        from source.server import admin_review
        connection=self._admin_writer();locked=False
        try:
            cursor=connection.cursor()
            try:
                cursor.execute("SELECT GET_LOCK('goiy_admin_review_ids',5)")
                if cursor.fetchone()[0]!=1:raise AdminReviewConflict("review ID allocator is busy")
                locked=True
            finally:cursor.close()
            result=function(connection,payload,reviewer)
            connection.commit()
            return result
        except admin_review.ReviewConflict as exc:
            connection.rollback();raise AdminReviewConflict(str(exc)) from None
        except admin_review.ReviewBlocked as exc:
            connection.rollback();raise AdminReviewBlocked(str(exc)) from None
        except Exception:
            connection.rollback();raise
        finally:
            if locked:
                cursor=connection.cursor()
                try:
                    cursor.execute("SELECT RELEASE_LOCK('goiy_admin_review_ids')");cursor.fetchone()
                finally:cursor.close()
            connection.close()

    def admin_submit_review(self,payload,reviewer):
        from source.server.admin_review import submit
        return self._admin_review_write(submit,payload,reviewer)

    def admin_review_source(self,payload,reviewer):
        from source.server.admin_review import submit_source_decision
        return self._admin_review_write(submit_source_decision,payload,reviewer)

    def admin_approve_recipe(self,payload,reviewer):
        from source.server.admin_review import approve_recipe
        return self._admin_review_write(approve_recipe,payload,reviewer)

    def admin_reject_recipe(self,payload,reviewer):
        from source.server.admin_review import reject_recipe
        return self._admin_review_write(reject_recipe,payload,reviewer)

    def admin_publish_release(self,payload,reviewer):
        from source.server.admin_review import publish
        return self._admin_review_write(publish,payload,reviewer)

    def admin_unpublish_recipe(self,payload,reviewer):
        from source.server.admin_review import unpublish
        return self._admin_review_write(unpublish,payload,reviewer)

    def dataset_version(self, connection) -> str:
        row = self._fetchone(connection, "SELECT value FROM metadata WHERE `key`=%s", ("dataset_version",))
        if row is None:
            raise mysql.connector.errors.DatabaseError("missing dataset_version")
        return str(row[0])

    def recipe_ids_exist(self, connection, ids: tuple[int, ...]) -> bool:
        marks = ",".join("%s" for _ in ids)
        row = self._fetchone(connection, f"SELECT COUNT(*) FROM recipes WHERE id IN ({marks})", ids)
        return int(row[0]) == len(ids)

    def calculation_catalog(self, connection, recipe_ids: tuple[int, ...]) -> CalculationCatalog:
        from source.server.mysql_calculation_catalog import load_catalog
        return load_catalog(connection, recipe_ids)

    def meal_preference_catalog(self, connection, recipes, classification):
        from source.server.meal_preferences import load
        names = dict(self._fetchall(connection, "SELECT id,name FROM ingredients"))
        from source.server.legacy_ingredient_overlays import display_name,read_overrides
        for iid,overlay in read_overrides(connection).items():
            if iid in names:names[iid]=display_name(names[iid],overlay)
        rows=[];lines=[]
        for recipe in recipes:
            detail=self.get_recipe(connection,recipe["id"])
            if detail is None:continue
            rows.append((detail["id"],detail["title"],detail["instructions"],detail["minutes"],detail.get("source_url")))
            lines.extend((detail["id"],item["id"],item["name"],item.get("quantity"),item["is_required"])
                         for item in detail["ingredients"])
        return load(recipes,names,classification,_preference_details(rows,lines))

    def list_ingredients(self, connection, query: str, limit: int) -> list[dict[str, Any]]:
        from source.server.ingredient_catalog import merge_catalog
        legacy=self._legacy_ingredient_catalog(connection,query="",include_inactive=True)
        try:
            rows=self._fetchall(connection,"""SELECT i.id,i.legacy_ingredient_id,i.canonical_name,i.normalized_name,
                    COALESCE(s.is_active,1),COALESCE(u.uses,0)
                FROM v2_ingredients i LEFT JOIN v2_ingredient_admin_state s ON s.ingredient_id=i.id
                LEFT JOIN (SELECT ingredient_id,COUNT(DISTINCT revision_id) uses FROM v2_recipe_ingredient_lines GROUP BY ingredient_id) u
                  ON u.ingredient_id=i.id ORDER BY i.id""")
        except mysql.connector.Error as exc:
            if exc.errno!=1146:raise
            rows=[]
            try:
                rows=[(*row,1,0) for row in self._fetchall(connection,
                    "SELECT id,legacy_ingredient_id,canonical_name,normalized_name FROM v2_ingredients")]
            except mysql.connector.Error as missing:
                if missing.errno!=1146:raise
        v2=[{"id":int(r[0]),"legacy_ingredient_id":r[1],"name":r[2],"normalized_name":r[3],
             "is_active":bool(r[4]),"usage_count":int(r[5])} for r in rows]
        merged=merge_catalog(legacy,v2,active_only=True,query=query)
        return [{"id":row["ingredient_id"],"name":row["name"]} for row in merged[:limit]]

    def _legacy_ingredient_catalog(self,connection,query="",limit=None,include_inactive=False):
        needle=ingredient_search_normalize(query.strip())
        from source.server.legacy_ingredient_overlays import display_name,read_overrides
        overrides=read_overrides(connection)
        rows=self._fetchall(connection,"SELECT id,name FROM ingredients ORDER BY id")
        aliases={}
        for iid,alias in self._fetchall(connection,"SELECT ingredient_id,alias_norm FROM ingredient_aliases"):
            aliases.setdefault(int(iid),[]).append(str(alias))
        result=[]
        for ingredient_id,base_name in rows:
            ingredient_id=int(ingredient_id);override=overrides.get(ingredient_id)
            is_active=not override or override["is_active"]
            if not include_inactive and not is_active:continue
            name=display_name(base_name,override)
            row_aliases=list(aliases.get(ingredient_id,[]))
            if normalize(name)!=normalize(base_name):row_aliases.append(str(base_name))
            normalized=normalize(name)
            terms=[name,normalized,*row_aliases]
            if needle and not any(needle in ingredient_search_normalize(term) for term in terms):continue
            result.append({"id":ingredient_id,"name":name,"normalized_name":normalized,
                           "is_active":is_active,"aliases":row_aliases})
        return result if limit is None else result[:limit]

    def recipes_for_ranking(self, connection) -> list[dict[str, Any]]:
        recipes = self._fetchall(connection, "SELECT id,title,minutes FROM recipes ORDER BY id")
        relations = self._fetchall(connection, "SELECT recipe_id,ingredient_id,is_required FROM recipe_ingredients ORDER BY recipe_id,ingredient_id")
        grouped: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for recipe_id, ingredient_id, is_required in relations:
            grouped[int(recipe_id)].append((int(ingredient_id), int(is_required)))
        overlays=__import__("source.server.legacy_recipe_overlays",fromlist=["read_overlays"]).read_overlays(connection)
        result=[]
        for recipe_id,title,minutes in recipes:
            rid=int(recipe_id);overlay=overlays.get(rid)
            if overlay and not overlay["is_visible"]:continue
            required={x[0] for x in grouped[rid] if x[1]};all_ids={x[0] for x in grouped[rid]}
            if overlay and overlay["ingredients_overridden"]:
                required={item["id"] for item in overlay["ingredients"] if item["is_required"]}
                all_ids={item["id"] for item in overlay["ingredients"]}
            result.append({"id":rid,"title":overlay["title"] if overlay and overlay["title"] is not None else title,
                "minutes":int(overlay["minutes"] if overlay and overlay["minutes"] is not None else minutes),
                "required_ids":required,"all_ids":all_ids})
        return result

    def recipes_for_search(self, connection) -> list[dict[str, Any]]:
        recipes = self.recipes_for_ranking(connection)
        names = {int(i): name for i, name in self._fetchall(connection, "SELECT id,name FROM ingredients")}
        from source.server.legacy_ingredient_overlays import display_name,read_overrides
        for iid,overlay in read_overrides(connection).items():
            if iid in names:names[iid]=display_name(names[iid],overlay)
        return [{**recipe, "ingredient_names": [names[i] for i in sorted(recipe["all_ids"])]}
                for recipe in recipes]

    def ingredient_ids_exist(self, connection, ids: set[int]) -> bool:
        if not ids:
            return True
        available={row["id"] for row in self.list_ingredients(connection,"",2**31-1)}
        return ids<=available

    def get_recipe(self, connection, recipe_id: int) -> dict[str, Any] | None:
        row = self._fetchone(connection, "SELECT id,title,instructions,minutes,source_url FROM recipes WHERE id=%s", (recipe_id,))
        if row is None:
            return None
        ingredients = self._fetchall(connection, "SELECT i.id,i.name,ri.quantity,ri.is_required FROM recipe_ingredients ri JOIN ingredients i ON i.id=ri.ingredient_id WHERE ri.recipe_id=%s ORDER BY i.id", (recipe_id,))
        from source.server.legacy_ingredient_overlays import display_name,read_overrides
        ingredient_overrides=read_overrides(connection,[int(row[0]) for row in ingredients])
        result={"id":int(row[0]),"title":row[1],"description":"","instructions":row[2],"minutes":int(row[3]),
            "source_url":row[4],"ingredients":[{"id":int(x[0]),"name":display_name(x[1],ingredient_overrides.get(int(x[0]))),"quantity":x[2],"is_required":bool(x[3])} for x in ingredients]}
        from source.server.legacy_recipe_overlays import effective_recipe,read_overlays
        return effective_recipe(result,read_overlays(connection,[recipe_id]).get(recipe_id))

    def admin_dashboard(self, connection):
        # Legacy identities already represented by v2_recipes count once.
        recipe_total=int(self._fetchone(connection,"SELECT COUNT(*) FROM recipes")[0])
        legacy_ingredients=self._legacy_ingredient_catalog(connection,include_inactive=True)
        v2_ingredients=[{"id":int(row[0]),"legacy_ingredient_id":row[1],"name":row[2],"normalized_name":row[3],
                         "is_active":True,"usage_count":0} for row in self._fetchall(connection,
                         """SELECT id,legacy_ingredient_id,canonical_name,normalized_name FROM v2_ingredients
                            WHERE legacy_ingredient_id IS NOT NULL OR
                              (identity_status='DRAFT' AND evidence_set_id IS NULL AND review_decision_id IS NULL)""")]
        from source.server.ingredient_catalog import merge_catalog
        ingredient_total=len(merge_catalog(legacy_ingredients,v2_ingredients))
        direct_v2=[]
        try:
            direct_v2=[int(row[0]) for row in self._fetchall(connection,"""SELECT v2_recipe_id
                FROM v2_admin_recipe_catalog_overrides WHERE v2_recipe_id IS NOT NULL AND is_deleted=0""")]
        except mysql.connector.Error as exc:
            if exc.errno!=1146:raise
        revisions=self._fetchall(connection,"SELECT status,COUNT(*) FROM v2_recipe_revisions GROUP BY status")
        counts={str(status):int(count) for status,count in revisions}
        summary_column=self._fetchone(connection,"SHOW COLUMNS FROM v2_recipe_revisions LIKE 'description'") is not None
        users_total=None
        try:
            account_connection=self._account_write_connection()
            try:users_total=int(self._fetchone(account_connection,"SELECT COUNT(*) FROM v2_user_accounts")[0])
            finally:account_connection.close()
        except Exception:
            # Missing user account writer/schema is shown as unavailable, never as a fabricated zero.
            users_total=None
        legacy_visible_total=recipe_total
        try:
            from source.server.legacy_recipe_overlays import read_overlays
            overlays=read_overlays(connection)
            legacy_visible_total=sum(1 for (recipe_id,) in self._fetchall(connection,"SELECT id FROM recipes")
                                     if recipe_id not in overlays or overlays[int(recipe_id)]["is_visible"])
        except mysql.connector.Error:
            # Until the additive overlay migration is installed, legacy remains visible.
            legacy_visible_total=recipe_total
        published_total=legacy_visible_total
        try:
            from source.server.mysql_recipe_catalog import load_catalog
            public_catalog=load_catalog(connection)
            published_total+=len(public_catalog.details)
            direct_v2.extend(int(recipe_id) for recipe_id in public_catalog.details if int(recipe_id)>2**32-1)
        except Exception:
            # Preserve accurate legacy count while making v2 publication count visibly unavailable.
            published_total=None
        draft_write_ready=bool(summary_column and self.admin_draft_writer_ready())
        recipe_catalog_ready=bool(draft_write_ready and self.admin_recipe_catalog_ready())
        return {"recipes_total":recipe_total+len(set(direct_v2)),"ingredients_total":ingredient_total,
                "users_total":users_total,"published_total":published_total,
                "revisions_total":sum(counts.values()),"draft_revisions":counts.get("DRAFT",0),
                "needs_verification_revisions":counts.get("NEEDS_VERIFICATION",0),
                "approved_revisions":counts.get("APPROVED",0),
                "draft_write_ready":draft_write_ready,
                "recipe_catalog_ready":recipe_catalog_ready,
                "review_write_ready":self.admin_review_writer_ready(),
                "ingredient_admin_ready":self.admin_ingredient_writer_ready(),
                "legacy_recipe_overlay_ready":self.admin_legacy_recipe_overlay_ready(connection)}

    def admin_legacy_recipe_overlay_ready(self,connection):
        try:
            from source.database import v2_legacy_recipe_overlay_schema as schema
            marker=self._fetchone(connection,"SELECT checksum,execution_result FROM v2_migration_history WHERE version=%s",
                                   (schema.VERSION,))
            if not marker or marker[0]!=schema.checksum() or marker[1]!="APPLIED":return False
            from source.server.legacy_recipe_overlays import read_overlays
            read_overlays(connection,[])
            writer=self._admin_writer()
            try:
                grants=[row[0] for row in self._fetchall(writer,"SHOW GRANTS FOR CURRENT_USER()")]
                database=self.config["database"]
                expected={"v2_admin_legacy_recipe_overrides":{"SELECT","INSERT","UPDATE"},
                          "v2_admin_legacy_recipe_override_ingredients":{"SELECT","INSERT","UPDATE","DELETE"}}
                for table,required in expected.items():
                    ok=False
                    for grant in grants:
                        upper=str(grant).upper()
                        if f"ON `{database}`.`{table}`".upper() not in upper:continue
                        privilege=upper.split("GRANT ",1)[1].split(" ON ",1)[0]
                        available={part.strip().split("(",1)[0] for part in privilege.split(",")}
                        if required<=available:ok=True;break
                    if not ok:return False
                return True
            finally:writer.close()
        except Exception:
            return False

    def admin_draft_writer_ready(self):
        try:
            writer=self._admin_writer();cursor=writer.cursor()
            try:
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants=[row[0] for row in cursor.fetchall()]
                from source.web.setup_admin import validate_writer_grants
                validate_writer_grants(grants,draft_only=True,database=self.config["database"])
                cursor.execute("SHOW COLUMNS FROM v2_recipe_revisions LIKE 'description'")
                return cursor.fetchone() is not None
            finally:
                cursor.close();writer.close()
        except Exception:
            return False

    def admin_review_writer_ready(self):
        try:
            connection=self._admin_writer();cursor=connection.cursor()
            try:
                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants=[row[0] for row in cursor.fetchall()]
                from source.web.setup_admin import validate_writer_grants
                validate_writer_grants(grants)
                return True
            finally:
                cursor.close();connection.close()
        except Exception:
            return False

    def admin_list_recipes(self, connection, query, limit, offset, *, role=None, visibility=None, max_minutes=None):
        from source.common.catalog_ids import v2_public_id
        from source.server.legacy_recipe_overlays import read_overlays
        from source.server.meal_plan import default_classification
        normalized=normalize(query.strip())
        overlays=read_overlays(connection)
        lifecycle={}
        try:
            lifecycle={int(row[0] if row[0] is not None else row[1]):{"revision_id":int(row[2]) if row[2] else None,
                "role":row[3],"direct":bool(row[4]),"visible":bool(row[5]),"deleted":bool(row[6]),
                "legacy":row[0] is not None} for row in self._fetchall(connection,
                "SELECT legacy_recipe_id,v2_recipe_id,revision_id,role_code,direct_publication,is_visible,is_deleted FROM v2_admin_recipe_catalog_overrides")}
        except mysql.connector.Error as exc:
            if exc.errno!=1146:raise
        classification=default_classification().categories
        items=[]
        legacy_rows=self._fetchall(connection,"SELECT id,title,instructions,minutes FROM recipes ORDER BY id")
        for recipe_id,title,instructions,minutes in legacy_rows:
            rid=int(recipe_id);overlay=overlays.get(rid)
            current_title=overlay["title"] if overlay and overlay["title"] is not None else title
            current_minutes=int(overlay["minutes"] if overlay and overlay["minutes"] is not None else minutes)
            state=lifecycle.get(rid,{})
            visible=(overlay["is_visible"] if overlay else True) and state.get("visible",True) and not state.get("deleted",False)
            deleted=state.get("deleted",False)
            category=classification.get(rid)
            item={"recipe_id":rid,"title":current_title,"minutes":current_minutes,"visible":visible,"stored_visible":state.get("visible",True),"deleted":deleted,"direct_admin":False,
                  "role":category,"legacy":True,"has_override":bool(overlay and (overlay["title"] is not None
                    or overlay["description"] is not None or overlay["instructions"] is not None
                    or overlay["minutes"] is not None or overlay["ingredients_overridden"]))}
            if deleted and visibility!="deleted":continue
            if visibility=="deleted" and not deleted:continue
            if visibility=="visible" and not visible:continue
            if visibility=="hidden" and (visible or deleted):continue
            items.append(item)
        revision_rows=self._fetchall(connection,"""SELECT r.id,r.recipe_id,r.revision_no,r.title,r.status,r.minutes,
                EXISTS(SELECT 1 FROM v2_calculation_settings cs JOIN v2_release_recipes x
                  ON x.release_id=cs.active_release_id AND x.revision_id=r.id WHERE cs.id=1) AS in_active_release,
                (SELECT d.id FROM v2_data_releases d JOIN v2_release_recipes c ON c.release_id=d.id AND c.revision_id=r.id
                  WHERE d.status='DRAFT' AND d.code LIKE 'admin-review-%' ORDER BY d.id DESC LIMIT 1) AS candidate_release_id,
                r.content_review_id,r.servings_review_id
                FROM v2_recipe_revisions r JOIN v2_recipes v ON v.id=r.recipe_id
                WHERE v.legacy_recipe_id IS NULL ORDER BY r.recipe_id,r.revision_no DESC""")
        catalog_roles={};catalog_details={}
        if revision_rows:
            from source.server.mysql_recipe_catalog import load_catalog
            catalog=load_catalog(connection);catalog_roles=catalog.roles;catalog_details=catalog.details
        groups=defaultdict(list)
        for row in revision_rows:groups[int(row[1])].append(row)
        for rid,rows in groups.items():
            public_id=v2_public_id(rid)
            state=lifecycle.get(rid,{})
            direct_revision=next((row for row in rows if state.get("direct") and row[0]==state.get("revision_id")),None)
            public_revision=next((row for row in rows if row[6] and public_id in catalog_details),None)
            # Keep the ordinary management screen aligned with the public
            # catalog. Historical/imported revisions remain in review/history
            # views and are never promoted merely by appearing here.
            if not direct_revision and not public_revision:
                continue
            chosen=direct_revision or public_revision or rows[0]
            latest_draft=next((row for row in rows if row[4]=="DRAFT" and row[8] is None and row[9] is None),None)
            role_value=state.get("role") if direct_revision else catalog_roles.get(public_id) if public_revision else None
            candidate=next((row[7] for row in rows if row[7] is not None),None)
            deleted=state.get("deleted",False)
            visible=bool(direct_revision or public_revision) and state.get("visible",True) and not deleted
            item={"revision_id":int(chosen[0]),"edit_revision_id":int(latest_draft[0]) if latest_draft else None,
                "recipe_id":public_id,"revision_no":int(chosen[2]),"title":chosen[3],"status":chosen[4],
                "minutes":int(chosen[5]) if chosen[5] is not None else None,"visible":visible,
                "stored_visible":state.get("visible",True),"deleted":deleted,
                "role":role_value,"legacy":False,"has_override":False,
                "candidate_release_id":int(candidate) if candidate else None,"direct_admin":bool(direct_revision)}
            if deleted and visibility!="deleted":continue
            if visibility=="deleted" and not deleted:continue
            if visibility=="visible" and not visible:continue
            if visibility=="hidden" and (visible or deleted):continue
            items.append(item)
        items=[item for item in items if (not normalized or normalized in normalize(item["title"]))
               and (max_minutes is None or item["minutes"] is not None and item["minutes"]<=max_minutes)
               and (role is None or item["role"]==role)]
        items.sort(key=lambda item:(item["recipe_id"],item.get("revision_no",0)))
        total=len(items)
        items=items[offset:offset+limit]
        return {"items":items,"total":total,"limit":limit,"offset":offset,
                "legacy_overlay_ready":self.admin_legacy_recipe_overlay_ready(connection)}

    def admin_get_recipe(self, connection, revision_id):
        has_description=self._fetchone(connection,"SHOW COLUMNS FROM v2_recipe_revisions LIKE 'description'") is not None
        description_column="r.description" if has_description else "NULL"
        row=self._fetchone(connection,f"""SELECT r.id,r.recipe_id,COALESCE(v.legacy_recipe_id,0),r.revision_no,
                r.title,{description_column},r.instructions,r.minutes,r.status,r.content_complete
                FROM v2_recipe_revisions r JOIN v2_recipes v ON v.id=r.recipe_id WHERE r.id=%s""",(revision_id,))
        if not row:return None
        from source.common.catalog_ids import v2_public_id
        rid=int(row[1]);public_id=int(row[2]) if row[2] else v2_public_id(rid)
        lines=self._fetchall(connection,"""SELECT l.line_no,l.ingredient_id,i.legacy_ingredient_id,i.canonical_name,l.quantity_raw,
                l.requirement,l.status,l.quantity_review_id,l.scaling_review_id FROM v2_recipe_ingredient_lines l LEFT JOIN v2_ingredients i ON i.id=l.ingredient_id
                WHERE l.revision_id=%s ORDER BY l.line_no""",(revision_id,))
        evidence=[]
        try:
            evidence=self._fetchall(connection,"""SELECT e.id,e.source_id,r.content_evidence_set_id,s.title,s.url,s.author_or_publisher,
                    s.verification_status,e.claim_scope,e.entity_ref,e.locator,e.excerpt_or_observation,e.content_hash
                FROM v2_recipe_revisions r JOIN v2_evidence_set_members m ON m.evidence_set_id=r.content_evidence_set_id
                JOIN v2_evidence e ON e.id=m.evidence_id JOIN v2_sources s ON s.id=e.source_id
                WHERE r.id=%s ORDER BY e.id LIMIT 12""",(revision_id,))
        except mysql.connector.Error as exc:
            if exc.errno!=1146:raise
        evidence_rows=[{"evidence_id":int(e[0]),"source_id":int(e[1]),"evidence_set_id":int(e[2]),
            "source_title":e[3],"source_url":e[4],"publisher":e[5],"source_status":e[6],
            "claim_scope":e[7],"entity_ref":e[8],"locator":e[9],"excerpt":str(e[10])[:1000],
            "content_hash":e[11]} for e in evidence]
        published=False;verified_role=None;candidate=None
        try:
            from source.server.mysql_recipe_catalog import load_catalog
            catalog=load_catalog(connection)
            active=self._fetchone(connection,"SELECT active_release_id FROM v2_calculation_settings WHERE id=1")
            is_active_revision=bool(active and active[0] is not None and self._fetchone(connection,
                "SELECT 1 FROM v2_release_recipes WHERE release_id=%s AND recipe_id=%s AND revision_id=%s",
                (active[0],rid,revision_id)))
            direct=self._fetchone(connection,"""SELECT 1 FROM v2_admin_recipe_catalog_overrides
                WHERE v2_recipe_id=%s AND revision_id=%s AND direct_publication=1 AND is_visible=1 AND is_deleted=0""",
                (rid,revision_id))
            published=bool((is_active_revision or direct) and public_id in catalog.details)
            verified_role=catalog.roles.get(public_id) if published else None
        except mysql.connector.Error:
            # A missing or unavailable publication catalog is never treated as public.
            published=False
        if row[8]=="APPROVED":
            candidate=self._fetchone(connection,"""SELECT d.id FROM v2_data_releases d JOIN v2_release_recipes m ON m.release_id=d.id
                WHERE d.status='DRAFT' AND d.code LIKE 'admin-review-%' AND m.revision_id=%s ORDER BY d.id DESC LIMIT 1""",(revision_id,))
        from source.common.catalog_ids import v2_public_id
        from source.server.legacy_ingredient_overlays import display_name,read_overrides
        linked_ids={int(line[2]) for line in lines if line[2] is not None}
        linked_overrides=read_overrides(connection,linked_ids)
        legacy_names={int(iid):name for iid,name in self._fetchall(connection,
            "SELECT id,name FROM ingredients WHERE id IN ("+(",".join("%s" for _ in linked_ids) or "NULL")+")",tuple(linked_ids))} if linked_ids else {}
        from source.server.admin_recipes import revision_edit_version
        edit_version=revision_edit_version(
            revision_id=row[0],recipe_id=row[1],revision_no=row[3],status=row[8],title=row[4],
            description=row[5] or "",instructions=row[6],minutes=row[7],
            ingredients=[{"line_no":line[0],"ingredient_id":line[1],"quantity_raw":line[4],
                          "requirement":line[5],"status":line[6],"quantity_review_id":line[7],
                          "scaling_review_id":line[8]} for line in lines])
        return {"revision_id":int(row[0]),"recipe_id":public_id,"revision_no":int(row[3]),"title":row[4],
                "description":row[5] or "","instructions":row[6],"minutes":int(row[7]) if row[7] is not None else None,
                "status":row[8],"content_complete":bool(row[9]),
                "ingredients":[{"line_no":int(l[0]),"ingredient_id":int(l[2]) if l[2] is not None else v2_public_id(int(l[1])),
                    "name":display_name(legacy_names.get(int(l[2]),l[3]),linked_overrides.get(int(l[2]))) if l[2] is not None else l[3],
                    "quantity_raw":l[4],"requirement":l[5],"status":l[6]} for l in lines],
                "evidence":evidence_rows,"edit_version":edit_version,"candidate_release_id":int(candidate[0]) if candidate else None,
                "published":published,"role":verified_role}

    def admin_get_legacy_recipe(self,connection,recipe_id):
        from source.server.legacy_recipe_overlays import admin_detail
        return admin_detail(connection,recipe_id)

    def admin_update_legacy_recipe(self,payload,author):
        from source.server.legacy_recipe_overlays import update
        try:return update(self,payload,author)
        except mysql.connector.Error as exc:
            if exc.errno==1146:raise AdminSchemaUnavailable("legacy recipe overlay migration is not installed") from None
            raise

    def admin_set_legacy_recipe_visibility(self,payload,author):
        from source.server.legacy_recipe_overlays import set_visibility
        try:return set_visibility(self,payload,author)
        except mysql.connector.Error as exc:
            if exc.errno==1146:raise AdminSchemaUnavailable("legacy recipe overlay migration is not installed") from None
            raise
