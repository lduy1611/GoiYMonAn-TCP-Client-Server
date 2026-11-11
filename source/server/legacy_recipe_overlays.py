"""Non-destructive Admin overrides for the legacy recipe catalog."""
from source.common.protocol import ProtocolError
import hashlib
import json


from source.common.catalog_ids import UINT32_MAX, valid_public_id, V2_OFFSET

MAX_UINT32=UINT32_MAX


def _reject(request_id):
    raise ProtocolError("INVALID_PAYLOAD","invalid legacy recipe overlay payload",request_id)


def edit_version(detail):
    """Hash only editable recipe fields so an old snapshot cannot overwrite a newer save."""
    snapshot={"recipe_id":detail["id"],"title":detail["title"],"description":detail["description"],
        "instructions":detail["instructions"],"minutes":detail["minutes"],"is_visible":detail["is_visible"],
        "ingredients":[{"ingredient_id":line["id"],"quantity":line["quantity"],
                         "is_required":line["is_required"]} for line in detail["ingredients"]]}
    encoded=json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_update(payload,request_id):
    keys={"recipe_id","title","description","instructions","minutes","ingredients","is_visible","expected_version"}
    if not isinstance(payload,dict) or set(payload)!=keys:_reject(request_id)
    rid=payload["recipe_id"]
    title,description,instructions,minutes=payload["title"],payload["description"],payload["instructions"],payload["minutes"]
    lines=payload["ingredients"]
    if (type(rid) is not int or not 1<=rid<=MAX_UINT32
            or not isinstance(title,str) or not 1<=len(title.strip())<=255
            or not isinstance(description,str) or len(description.strip())>1000
            or not isinstance(instructions,str) or not 1<=len(instructions.strip())<=12000
            or type(minutes) is not int or not 1<=minutes<=240
            or type(payload["is_visible"]) is not bool
            or not isinstance(payload["expected_version"],str)
            or len(payload["expected_version"])!=64
            or any(c not in "0123456789abcdef" for c in payload["expected_version"])
            or not isinstance(lines,list) or not 1<=len(lines)<=100):_reject(request_id)
    normalized=[]
    for line in lines:
        if not isinstance(line,dict) or set(line)!={"ingredient_id","quantity","is_required"}:_reject(request_id)
        iid,quantity,required=line["ingredient_id"],line["quantity"],line["is_required"]
        if (not valid_public_id(iid) or not isinstance(quantity,str)
                or len(quantity)>255 or type(required) is not bool):_reject(request_id)
        # Compatibility payloads may still contain a boolean. Admin recipe
        # edits no longer classify lines: every submitted ingredient is required.
        normalized.append({"ingredient_id":iid,"quantity":quantity.strip(),"is_required":True})
    if len({line["ingredient_id"] for line in normalized})!=len(normalized):_reject(request_id)
    return {"recipe_id":rid,"title":title.strip(),"description":description.strip(),
        "instructions":instructions.strip(),"minutes":minutes,"ingredients":normalized,
        "is_visible":payload["is_visible"],"expected_version":payload["expected_version"]}


def validate_restore(payload,request_id):
    """Validate a checksummed snapshot restore while preserving historical line flags."""
    if not isinstance(payload,dict) or not isinstance(payload.get("ingredients"),list):
        _reject(request_id)
    normalized=validate_update({**payload,"ingredients":[
        {**line,"is_required":True} for line in payload.get("ingredients",[])
    ]},request_id)
    # The normal update contract intentionally makes all current Admin lines
    # required. Snapshot recovery is the only route allowed to restore prior
    # required/optional flags from an authenticated, checksummed snapshot.
    for index,line in enumerate(payload["ingredients"]):
        if type(line.get("is_required")) is not bool:
            _reject(request_id)
        normalized["ingredients"][index]["is_required"]=line["is_required"]
    return normalized


def validate_visibility(payload,request_id):
    if (not isinstance(payload,dict) or set(payload)!={"recipe_id","is_visible"}
            or type(payload["recipe_id"]) is not int or not 1<=payload["recipe_id"]<=MAX_UINT32
            or type(payload["is_visible"]) is not bool):_reject(request_id)
    return payload


def read_overlays(connection,recipe_ids=None):
    params=tuple(recipe_ids or ())
    where=" WHERE o.recipe_id IN ("+",".join("%s" for _ in params)+")" if params else ""
    cursor=connection.cursor(dictionary=True)
    try:
        try:
            cursor.execute("""SELECT o.recipe_id,o.title,o.description,o.instructions,o.minutes,o.is_visible,
                o.ingredients_overridden,o.updated_by,o.updated_at FROM v2_admin_legacy_recipe_overrides o"""+where,params)
            rows=cursor.fetchall()
        except Exception as exc:
            import mysql.connector
            if isinstance(exc,mysql.connector.Error) and exc.errno==1146:return {}
            raise
        result={int(row["recipe_id"]):{**row,"recipe_id":int(row["recipe_id"]),"is_visible":bool(row["is_visible"]),
            "ingredients_overridden":bool(row["ingredients_overridden"]),"ingredients":[]} for row in rows}
        ids=[rid for rid,row in result.items() if row["ingredients_overridden"]]
        if ids:
            marks=",".join("%s" for _ in ids)
            cursor.execute("SHOW COLUMNS FROM v2_admin_legacy_recipe_override_ingredients LIKE 'v2_ingredient_id'")
            has_shared_link=cursor.fetchone() is not None
            if has_shared_link:
                cursor.execute(f"""SELECT x.recipe_id,x.line_no,x.ingredient_id,x.v2_ingredient_id,
                        legacy.name AS legacy_name,v2.canonical_name AS v2_name,v2.legacy_ingredient_id,
                        x.quantity,x.is_required
                    FROM v2_admin_legacy_recipe_override_ingredients x
                    LEFT JOIN v2_ingredients v2 ON v2.id=x.v2_ingredient_id
                    LEFT JOIN ingredients legacy ON legacy.id=COALESCE(x.ingredient_id,v2.legacy_ingredient_id)
                    WHERE x.recipe_id IN ({marks}) ORDER BY x.recipe_id,x.line_no""",tuple(ids))
                ingredient_rows=[(row["recipe_id"],row["line_no"],row["ingredient_id"],row["v2_ingredient_id"],
                                  row["legacy_name"],row["v2_name"],row["legacy_ingredient_id"],
                                  row["quantity"],row["is_required"]) for row in cursor.fetchall()]
            else:
                cursor.execute(f"""SELECT x.recipe_id,x.line_no,x.ingredient_id,i.name,x.quantity,x.is_required
                    FROM v2_admin_legacy_recipe_override_ingredients x JOIN ingredients i ON i.id=x.ingredient_id
                    WHERE x.recipe_id IN ({marks}) ORDER BY x.recipe_id,x.line_no""",tuple(ids))
                ingredient_rows=[(row["recipe_id"],row["line_no"],row["ingredient_id"],None,
                                  row["name"],None,None,row["quantity"],row["is_required"])
                                 for row in cursor.fetchall()]
            from source.server.legacy_ingredient_overlays import display_name,read_overrides
            legacy_ids=[int(row[2]) if row[2] is not None else int(row[6])
                        for row in ingredient_rows if row[2] is not None or row[6] is not None]
            ingredient_overrides=read_overrides(connection,legacy_ids)
            for row in ingredient_rows:
                recipe_id,_,legacy_id,v2_id,legacy_name,v2_name,linked_legacy_id,quantity,is_required=row
                if legacy_id is not None:
                    public_id=int(legacy_id)
                    name=display_name(legacy_name,ingredient_overrides.get(public_id))
                else:
                    storage_id=int(v2_id)
                    public_id=int(linked_legacy_id) if linked_legacy_id is not None else V2_OFFSET+storage_id
                    name=(display_name(legacy_name,ingredient_overrides.get(public_id))
                          if linked_legacy_id is not None else v2_name)
                    if name is None:
                        raise RuntimeError("legacy recipe overlay references a missing v2 ingredient")
                result[int(recipe_id)]["ingredients"].append({"id":public_id,"name":name,
                    "quantity":quantity,"is_required":bool(is_required)})
        return result
    finally:
        cursor.close()


def effective_recipe(base,overlay):
    if overlay is None:return base
    if not overlay["is_visible"]:return None
    result={**base}
    for field in ("title","description","instructions","minutes"):
        if overlay[field] is not None:result[field]=overlay[field]
    if overlay["ingredients_overridden"]:result["ingredients"]=overlay["ingredients"]
    return result


def admin_detail(connection,recipe_id):
    from source.server.meal_plan import default_classification
    cursor=connection.cursor()
    try:
        cursor.execute("SELECT id,title,instructions,minutes,source_url,source_note FROM recipes WHERE id=%s",(recipe_id,))
        row=cursor.fetchone()
        if not row:return None
        cursor.execute("SELECT i.id,i.name,ri.quantity,ri.is_required FROM recipe_ingredients ri JOIN ingredients i ON i.id=ri.ingredient_id WHERE ri.recipe_id=%s ORDER BY i.id",(recipe_id,))
        lines=cursor.fetchall()
        from source.server.legacy_ingredient_overlays import display_name,read_overrides
        ingredient_overrides=read_overrides(connection,[int(line[0]) for line in lines])
        base={"id":int(row[0]),"title":row[1],"description":"","instructions":row[2],"minutes":int(row[3]),
            "source_url":row[4],"ingredients":[{"id":int(x[0]),"name":display_name(x[1],ingredient_overrides.get(int(x[0]))),"quantity":x[2],"is_required":bool(x[3])} for x in lines]}
        overlay=read_overlays(connection,[recipe_id]).get(recipe_id)
        result={**base,"is_legacy":True,"role":default_classification().categories.get(int(recipe_id)),
                "is_visible":overlay["is_visible"] if overlay else True,
                "has_override":bool(overlay and (overlay["title"] is not None or overlay["description"] is not None
                    or overlay["instructions"] is not None or overlay["minutes"] is not None or overlay["ingredients_overridden"]))}
        if overlay:
            for field in ("title","description","instructions","minutes"):
                if overlay[field] is not None:result[field]=overlay[field]
            if overlay["ingredients_overridden"]:result["ingredients"]=overlay["ingredients"]
        result["edit_version"]=edit_version(result)
        return result
    finally:
        cursor.close()


def _verify_recipe_and_ingredients(connection,payload,repository):
    cursor=connection.cursor()
    try:
        cursor.execute("SELECT 1 FROM recipes WHERE id=%s",(payload["recipe_id"],))
        if not cursor.fetchone():raise ValueError("legacy recipe does not exist")
        ids={line["ingredient_id"] for line in payload["ingredients"]}
        available={int(row["id"]) for row in repository.list_ingredients(connection,"",2**31-1)}
        if not ids<=available:raise ValueError("ingredient is missing or inactive in the shared catalog")
    finally:
        cursor.close()


def update(repository,payload,author):
    connection=repository._admin_writer();committed=False
    try:
        cursor=connection.cursor()
        try:cursor.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        finally:cursor.close()
        _verify_recipe_and_ingredients(connection,payload,repository)
        has_v2=any(line["ingredient_id"]>MAX_UINT32 for line in payload["ingredients"])
        if has_v2 and not repository.legacy_recipe_shared_ingredient_ready(connection):
            from source.server.repository import AdminSchemaUnavailable
            raise AdminSchemaUnavailable("migration 010 is required to link v2 catalog ingredients to legacy recipes")
        cursor=connection.cursor()
        try:
            cursor.execute("SELECT id FROM recipes WHERE id=%s FOR UPDATE",(payload["recipe_id"],))
            if cursor.fetchone() is None:raise ValueError("legacy recipe does not exist")
            cursor.execute("SELECT recipe_id FROM v2_admin_legacy_recipe_overrides WHERE recipe_id=%s FOR UPDATE",(payload["recipe_id"],))
            cursor.fetchall()
            cursor.execute("SELECT recipe_id,line_no FROM v2_admin_legacy_recipe_override_ingredients WHERE recipe_id=%s ORDER BY line_no FOR UPDATE",(payload["recipe_id"],))
            cursor.fetchall()
        finally:cursor.close()
        current=admin_detail(connection,payload["recipe_id"])
        if current is None:raise ValueError("legacy recipe does not exist")
        if current["edit_version"]!=payload["expected_version"]:
            from source.server.repository import AdminDraftConflict
            raise AdminDraftConflict("recipe changed after it was opened; reload before saving",reason="stale_version")
        cursor=connection.cursor()
        try:
            cursor.execute("""INSERT INTO v2_admin_legacy_recipe_overrides
                (recipe_id,title,description,instructions,minutes,is_visible,ingredients_overridden,updated_by)
                VALUES(%s,%s,%s,%s,%s,%s,TRUE,%s)
                ON DUPLICATE KEY UPDATE title=VALUES(title),description=VALUES(description),
                  instructions=VALUES(instructions),minutes=VALUES(minutes),is_visible=VALUES(is_visible),
                  ingredients_overridden=TRUE,updated_by=VALUES(updated_by)""",
                (payload["recipe_id"],payload["title"],payload["description"],payload["instructions"],
                 payload["minutes"],payload["is_visible"],str(author)[:255]))
            cursor.execute("DELETE FROM v2_admin_legacy_recipe_override_ingredients WHERE recipe_id=%s",(payload["recipe_id"],))
            if has_v2:
                cursor.executemany("""INSERT INTO v2_admin_legacy_recipe_override_ingredients
                    (recipe_id,line_no,ingredient_id,v2_ingredient_id,quantity,is_required)
                    VALUES(%s,%s,%s,%s,%s,%s)""",
                    [(payload["recipe_id"],n,
                      line["ingredient_id"] if line["ingredient_id"]<=MAX_UINT32 else None,
                      line["ingredient_id"]-V2_OFFSET if line["ingredient_id"]>MAX_UINT32 else None,
                      line["quantity"],line["is_required"])
                     for n,line in enumerate(payload["ingredients"],1)])
            else:
                cursor.executemany("""INSERT INTO v2_admin_legacy_recipe_override_ingredients
                    (recipe_id,line_no,ingredient_id,quantity,is_required) VALUES(%s,%s,%s,%s,%s)""",
                    [(payload["recipe_id"],n,line["ingredient_id"],line["quantity"],line["is_required"])
                     for n,line in enumerate(payload["ingredients"],1)])
        finally:cursor.close()
        connection.commit();committed=True
        return {"recipe_id":payload["recipe_id"],"is_visible":payload["is_visible"],"status":"SAVED"}
    except Exception:
        if not committed:connection.rollback()
        raise
    finally:connection.close()


def set_visibility(repository,payload,author):
    connection=repository._admin_writer();committed=False
    try:
        cursor=connection.cursor()
        try:
            cursor.execute("SELECT 1 FROM recipes WHERE id=%s FOR UPDATE",(payload["recipe_id"],))
            if not cursor.fetchone():raise ValueError("legacy recipe does not exist")
            cursor.execute("""INSERT INTO v2_admin_legacy_recipe_overrides(recipe_id,is_visible,updated_by)
                VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE is_visible=VALUES(is_visible),updated_by=VALUES(updated_by)""",
                (payload["recipe_id"],payload["is_visible"],str(author)[:255]))
        finally:cursor.close()
        connection.commit();committed=True
        return {"recipe_id":payload["recipe_id"],"is_visible":payload["is_visible"],"status":"SAVED"}
    except Exception:
        if not committed:connection.rollback()
        raise
    finally:connection.close()
