"""Validation for direct Admin catalog saves; publication is explicit in the save transaction."""
import hashlib
import json

from source.common.protocol import ProtocolError
from source.common.catalog_ids import V2_OFFSET

MAX_ID=2**64-1


def revision_edit_version(*, revision_id, recipe_id, revision_no, status, title,
                          description, instructions, minutes, ingredients):
    """Stable optimistic-concurrency token for the editable recipe snapshot."""
    normalized_lines=[]
    for line in ingredients:
        normalized_lines.append({
            "line_no":int(line["line_no"]),
            "ingredient_id":int(line["ingredient_id"]),
            "quantity_raw":line["quantity_raw"],
            "requirement":line["requirement"],
            "status":line["status"],
            "quantity_review_id":line.get("quantity_review_id"),
            "scaling_review_id":line.get("scaling_review_id"),
        })
    snapshot={
        "revision_id":int(revision_id),"recipe_id":int(recipe_id),"revision_no":int(revision_no),
        "status":status,"title":title,"description":description or "","instructions":instructions,
        "minutes":int(minutes) if minutes is not None else None,
        "ingredients":normalized_lines,
    }
    encoded=json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def validate_save(payload,request_id,*,update=False):
    required={"title","description","instructions","minutes","ingredients","role"}
    allowed=required|({"recipe_id","revision_id","expected_version"} if update else {"idempotency_key"})
    if not isinstance(payload,dict) or set(payload)!=allowed:
        raise ProtocolError("INVALID_PAYLOAD","invalid Admin recipe fields",request_id)
    if update and (type(payload["recipe_id"]) is not int or not V2_OFFSET < payload["recipe_id"] <= V2_OFFSET+2**32-1
                   or type(payload["revision_id"]) is not int or not 1<=payload["revision_id"]<=MAX_ID
                   or not isinstance(payload["expected_version"],str)
                   or len(payload["expected_version"])!=64
                   or any(char not in "0123456789abcdef" for char in payload["expected_version"])):
        raise ProtocolError("INVALID_PAYLOAD","invalid Admin recipe identity",request_id)
    title=payload["title"];description=payload["description"];instructions=payload["instructions"]
    minutes=payload["minutes"];ingredients=payload["ingredients"];role=payload["role"]
    if (not isinstance(title,str) or not 1<=len(title.strip())<=255
        or not isinstance(description,str) or len(description.strip())>1000
        or not isinstance(instructions,str) or not 1<=len(instructions.strip())<=12000
        or type(minutes) is not int or not 1<=minutes<=240
        or role not in {"main","vegetable","soup"}
        or not isinstance(ingredients,list) or not 1<=len(ingredients)<=50):
        raise ProtocolError("INVALID_PAYLOAD","invalid Admin recipe fields",request_id)
    lines=[]
    for line in ingredients:
        if not isinstance(line,dict) or set(line) not in ({"ingredient_id","quantity_raw"},
                                                            {"ingredient_id","quantity_raw","requirement"}):
            raise ProtocolError("INVALID_PAYLOAD","invalid Admin recipe ingredients",request_id)
        iid=line["ingredient_id"];raw=line["quantity_raw"]
        requirement=line.get("requirement","required")
        if (type(iid) is not int or not 1<=iid<=MAX_ID
            or raw is not None and (not isinstance(raw,str) or len(raw)>255)
            or requirement not in {"required","optional","unknown"}):
            raise ProtocolError("INVALID_PAYLOAD","invalid Admin recipe ingredients",request_id)
        lines.append({"ingredient_id":iid,"quantity_raw":raw.strip() if isinstance(raw,str) else None,
                      # Admin's simplified recipe editor treats every line as
                      # required, including requests from cached older clients.
                      "requirement":"required"})
    if len({x["ingredient_id"] for x in lines})!=len(lines):
        raise ProtocolError("INVALID_PAYLOAD","duplicate Admin recipe ingredient",request_id)
    if not update and (not isinstance(payload["idempotency_key"],str)
        or len(payload["idempotency_key"])!=36 or any(char not in "0123456789abcdefABCDEF-" for char in payload["idempotency_key"])):
        raise ProtocolError("INVALID_PAYLOAD","invalid Admin recipe idempotency key",request_id)
    out={"title":title.strip(),"description":description.strip(),"instructions":instructions.strip(),
         "minutes":minutes,"ingredients":lines,"role":role}
    if update:out.update(recipe_id=payload["recipe_id"],revision_id=payload["revision_id"],expected_version=payload["expected_version"])
    else:out["idempotency_key"]=payload["idempotency_key"].lower()
    return out


def mysql_save_error(exc,request_id):
    """Translate known MySQL write failures without exposing SQL or credentials."""
    errno=getattr(exc,"errno",None)
    if errno in (1044,1045,1142,1227):
        return ProtocolError("ADMIN_WRITE_DENIED","Admin writer lacks a required recipe permission",request_id)
    if errno==1062:
        return ProtocolError("ADMIN_RECIPE_CONFLICT","recipe identity already exists; reload before saving",request_id)
    if errno in (1451,1452):
        return ProtocolError("ADMIN_INGREDIENT_CONFLICT","ingredient reference conflicts with the current catalog",request_id)
    if errno in (3819,4025):
        return ProtocolError("ADMIN_RECIPE_CONSTRAINT","recipe data violates a database constraint",request_id)
    if errno in (1048,1265,1364,1366,1406):
        return ProtocolError("ADMIN_RECIPE_INVALID_DATA","recipe value does not fit the database field",request_id)
    if errno in (1054,1146):
        return ProtocolError("ADMIN_SCHEMA_UNAVAILABLE","required recipe catalog schema is unavailable",request_id)
    if errno in (2002,2003,2006,2013,2055):
        return ProtocolError("DB_UNAVAILABLE","MySQL connection failed while saving the recipe",request_id)
    return None

def validate_state(payload,request_id):
    if (not isinstance(payload,dict) or set(payload)!={"recipe_id","is_visible","is_deleted"}
        or type(payload["recipe_id"]) is not int or not 1<=payload["recipe_id"]<=MAX_ID
        or type(payload["is_visible"]) is not bool or type(payload["is_deleted"]) is not bool):
        raise ProtocolError("INVALID_PAYLOAD","invalid recipe lifecycle state",request_id)
    if payload["is_deleted"] and payload["is_visible"] is False:
        # Preserve the pre-delete visibility flag so restore can recover the
        # exact prior state; callers set is_deleted independently.
        pass
    return payload
