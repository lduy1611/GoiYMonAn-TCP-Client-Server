"""Exact migration identity shared by the offline runner and read-only adapter."""
from hashlib import sha256
from pathlib import Path
import re

VERSION = "001_portion_catalog"
SQL_PATH = Path(__file__).with_name("migrations") / f"{VERSION}.sql"


def checksum():
    # Portable across Windows/Linux checkouts; all other text changes still fail closed.
    return sha256(SQL_PATH.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def statements():
    # This controlled migration has no procedures, delimiters or semicolons in literals.
    text = re.sub(r"(?m)^\s*--.*$", "", SQL_PATH.read_text(encoding="utf-8"))
    return [part.strip() for part in text.split(";") if part.strip()]


def tables():
    return re.findall(r"CREATE TABLE (v2_[a-z_]+)", SQL_PATH.read_text(encoding="utf-8"))


def history_is_compatible(rows):
    """Accept known additive migrations without trusting unknown history rows."""
    from source.database import v2_context_schema
    from source.database import v2_admin_schema
    from source.database import v2_ingredient_admin_schema
    from source.database import v2_user_account_schema
    from source.database import v2_legacy_recipe_overlay_schema
    from source.database import v2_legacy_ingredient_admin_schema
    from source.database import v2_recipe_image_schema
    from source.database import v2_admin_recipe_catalog_schema
    by_version = {row["version"]:row for row in rows}
    supported = {VERSION, v2_context_schema.VERSION, v2_admin_schema.VERSION,
                 v2_ingredient_admin_schema.VERSION, v2_user_account_schema.VERSION}
    supported.add(v2_legacy_recipe_overlay_schema.VERSION)
    supported.add(v2_legacy_ingredient_admin_schema.VERSION)
    supported.add(v2_recipe_image_schema.VERSION)
    supported.add(v2_admin_recipe_catalog_schema.VERSION)
    if VERSION not in by_version or set(by_version) - supported:
        return False
    base = by_version[VERSION]
    if (base["checksum"] != checksum() or base["execution_result"] != "APPLIED"
            or base["applied_at"] is None):
        return False
    context = by_version.get(v2_context_schema.VERSION)
    if context is not None and (context["checksum"] != v2_context_schema.checksum()
            or context["execution_result"] != "APPLIED" or context["applied_at"] is None):
        return False
    draft = by_version.get(v2_admin_schema.VERSION)
    if draft is not None and not (draft["checksum"] == v2_admin_schema.checksum()
        and draft["execution_result"] == "APPLIED" and draft["applied_at"] is not None):
        return False
    for module in (v2_ingredient_admin_schema, v2_user_account_schema):
        row = by_version.get(module.VERSION)
        if row is not None and not (row["checksum"] == module.checksum()
            and row["execution_result"] == "APPLIED" and row["applied_at"] is not None):
            return False
    overlay = by_version.get(v2_legacy_recipe_overlay_schema.VERSION)
    if overlay is not None and not (overlay["checksum"] == v2_legacy_recipe_overlay_schema.checksum()
        and overlay["execution_result"] == "APPLIED" and overlay["applied_at"] is not None):
        return False
    legacy_ingredients = by_version.get(v2_legacy_ingredient_admin_schema.VERSION)
    if legacy_ingredients is not None and not (legacy_ingredients["checksum"] == v2_legacy_ingredient_admin_schema.checksum()
            and legacy_ingredients["execution_result"] == "APPLIED" and legacy_ingredients["applied_at"] is not None):
        return False
    images = by_version.get(v2_recipe_image_schema.VERSION)
    if images is not None and not (images["checksum"] == v2_recipe_image_schema.checksum()
            and images["execution_result"] == "APPLIED" and images["applied_at"] is not None):
        return False
    catalog = by_version.get(v2_admin_recipe_catalog_schema.VERSION)
    if catalog is not None and not (catalog["checksum"] == v2_admin_recipe_catalog_schema.checksum()
            and catalog["execution_result"] == "APPLIED" and catalog["applied_at"] is not None):
        return False
    return True
