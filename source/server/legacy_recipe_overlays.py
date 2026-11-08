"""Non-destructive Admin overrides for the legacy recipe catalog."""
from source.common.protocol import ProtocolError


MAX_UINT32=2**32-1


def _reject(request_id):
    raise ProtocolError("INVALID_PAYLOAD","invalid legacy recipe overlay payload",request_id)


def validate_update(payload,request_id):
    keys={"recipe_id","title","description","instructions","minutes","ingredients","is_visible"}
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
            or not isinstance(lines,list) or not 1<=len(lines)<=100):_reject(request_id)
    normalized=[]
    for line in lines:
        if not isinstance(line,dict) or set(line)!={"ingredient_id","quantity","is_required"}:_reject(request_id)
        iid,quantity,required=line["ingredient_id"],line["quantity"],line["is_required"]
        if (type(iid) is not int or not 1<=iid<=MAX_UINT32 or not isinstance(quantity,str)
                or len(quantity)>255 or type(required) is not bool):_reject(request_id)
        # Compatibility payloads may still contain a boolean. Admin recipe
        # edits no longer classify lines: every submitted ingredient is required.
        normalized.append({"ingredient_id":iid,"quantity":quantity.strip(),"is_required":True})
    if len({line["ingredient_id"] for line in normalized})!=len(normalized):_reject(request_id)
    return {"recipe_id":rid,"title":title.strip(),"description":description.strip(),
        "instructions":instructions.strip(),"minutes":minutes,"ingredients":normalized,
        "is_visible":payload["is_visible"]}


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
            cursor.execute(f"""SELECT x.recipe_id,x.line_no,x.ingredient_id,i.name,x.quantity,x.is_required
                FROM v2_admin_legacy_recipe_override_ingredients x JOIN ingredients i ON i.id=x.ingredient_id
                WHERE x.recipe_id IN ({marks}) ORDER BY x.recipe_id,x.line_no""",tuple(ids))
            ingredient_rows=cursor.fetchall()
            from source.server.legacy_ingredient_overlays import display_name,read_overrides
            ingredient_overrides=read_overrides(connection,[int(row["ingredient_id"]) for row in ingredient_rows])
            for row in ingredient_rows:
                result[int(row["recipe_id"])]["ingredients"].append({"id":int(row["ingredient_id"]),"name":display_name(row["name"],ingredient_overrides.get(int(row["ingredient_id"]))),
                    "quantity":row["quantity"],"is_required":bool(row["is_required"])})
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
        return result
    finally:
        cursor.close()


def _verify_recipe_and_ingredients(connection,payload):
    cursor=connection.cursor()
    try:
        cursor.execute("SELECT 1 FROM recipes WHERE id=%s",(payload["recipe_id"],))
        if not cursor.fetchone():raise ValueError("legacy recipe does not exist")
        ids=sorted({line["ingredient_id"] for line in payload["ingredients"]})
        marks=",".join("%s" for _ in ids)
        cursor.execute(f"SELECT COUNT(*) FROM ingredients WHERE id IN ({marks})",tuple(ids))
        if int(cursor.fetchone()[0])!=len(ids):raise ValueError("legacy ingredient IDs do not exist")
    finally:
        cursor.close()


def update(repository,payload,author):
    connection=repository._admin_writer();committed=False
    try:
        _verify_recipe_and_ingredients(connection,payload)
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
            cursor.execute("SELECT 1 FROM recipes WHERE id=%s",(payload["recipe_id"],))
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
