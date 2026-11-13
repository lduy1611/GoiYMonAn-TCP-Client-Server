"""Validation for direct Admin catalog saves; publication is explicit in the save transaction."""
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from source.common.protocol import ProtocolError
from source.common.catalog_ids import V2_OFFSET, valid_public_id

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

_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?\Z")


def _positive_decimal(value):
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        return False
    try:
        return Decimal(value) > 0
    except InvalidOperation:
        return False


def validate_save(payload,request_id,*,update=False,allow_repeated=False,unified=False):
    required={"title","description","instructions","minutes","ingredients","role"}
    structured={"servings","minutes_prep","minutes_cook","steps","source_url","tags","portion_data_status","portion_data_evidence","beverage_temperature","beverage_light","is_non_alcoholic","is_visible"} if unified else set()
    identity={"recipe_id","revision_id","expected_version"} if update else {"idempotency_key"}
    required_fields=required|identity
    allowed=required_fields|structured
    if (not isinstance(payload,dict) or not required_fields<=set(payload)
            or not set(payload)<=allowed):
        raise ProtocolError("INVALID_PAYLOAD","invalid Admin recipe fields",request_id)
    if update and (type(payload["recipe_id"]) is not int or not valid_public_id(payload["recipe_id"])
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
        or type(minutes) is not int or not 1<=minutes<=(1440 if unified else 240)
        or role not in ({"main","vegetable","soup","side","drink","starch","other"} if unified else {"main","vegetable","soup"})
        or not isinstance(ingredients,list) or not 1<=len(ingredients)<=50):
        raise ProtocolError("INVALID_PAYLOAD","invalid Admin recipe fields",request_id)
    servings = payload.get("servings")
    minutes_prep, minutes_cook = payload.get("minutes_prep"), payload.get("minutes_cook")
    steps = payload.get("steps")
    source_url=payload.get("source_url")
    tags=payload.get("tags")
    if unified:
        review_status = payload.get("portion_data_status")
        review_evidence = payload.get("portion_data_evidence")
        if review_status is not None:
            if review_status not in {"verified", "estimated", "needs_review"}:
                raise ProtocolError("INVALID_PAYLOAD", "invalid portion review status", request_id)
            if not isinstance(review_evidence, str) or len(review_evidence) > 2000 or (review_status != "needs_review" and not review_evidence.strip()):
                raise ProtocolError("INVALID_PAYLOAD", "portion review requires evidence", request_id)
        if servings is not None and (not _positive_decimal(servings) or Decimal(servings)>1000):
            raise ProtocolError("INVALID_PAYLOAD","invalid base servings",request_id)
        for value in (minutes_prep, minutes_cook):
            if value is not None and (type(value) is not int or not 0<=value<=1440):
                raise ProtocolError("INVALID_PAYLOAD","invalid preparation or cooking minutes",request_id)
        if (minutes_prep is not None and minutes_cook is not None
                and minutes_prep+minutes_cook>1440):
            raise ProtocolError("INVALID_PAYLOAD","combined preparation time exceeds the limit",request_id)
        if steps is not None:
            if not isinstance(steps,list) or not 1<=len(steps)<=50:
                raise ProtocolError("INVALID_PAYLOAD","invalid recipe steps",request_id)
            clean_steps=[]
            for step in steps:
                if not isinstance(step,dict) or set(step)!={"instruction","duration_minutes","heat_level"}:
                    raise ProtocolError("INVALID_PAYLOAD","invalid recipe step fields",request_id)
                instruction, duration, heat=step["instruction"],step["duration_minutes"],step["heat_level"]
                if (not isinstance(instruction,str) or not instruction.strip() or len(instruction)>5000
                    or duration is not None and (type(duration) is not int or not 0<=duration<=1440)
                    or heat is not None and (not isinstance(heat,str) or len(heat)>40)):
                    raise ProtocolError("INVALID_PAYLOAD","invalid recipe step values",request_id)
                clean_steps.append({"instruction":instruction.strip(),"duration_minutes":duration,
                                    "heat_level":heat.strip() if isinstance(heat,str) and heat.strip() else None})
            steps=clean_steps
        if source_url is not None:
            if not isinstance(source_url,str) or len(source_url)>1000:
                raise ProtocolError("INVALID_PAYLOAD","invalid recipe source URL",request_id)
            if source_url.strip():
                parsed=urlsplit(source_url.strip())
                if parsed.scheme not in {"http","https"} or not parsed.netloc or parsed.username or parsed.password:
                    raise ProtocolError("INVALID_PAYLOAD","recipe source URL must be an http(s) URL",request_id)
                source_url=source_url.strip()
            else:source_url=None
        if tags is not None:
            allowed_tags={
                # Labels are managed by Admin for the demo catalog. The v3
                # reader still checks ingredient composition before a recipe
                # qualifies for vegetarian meal plans.
                "diet":{"vegetarian"},
                "region":{"north","central","south"},
                "season":{"spring","summer","autumn","winter"},
                "occasion":{"daily","weekend","guests","birthday","tet","ancestral","snack","drinking"},
            }
            if not isinstance(tags,list) or len(tags)>16:
                raise ProtocolError("INVALID_PAYLOAD","invalid recipe tags",request_id)
            normalized_tags=[];seen_tags=set()
            for tag in tags:
                if (not isinstance(tag,dict) or set(tag)!={"tag_type","code"}
                        or tag.get("tag_type") not in allowed_tags
                        or tag.get("code") not in allowed_tags[tag["tag_type"]]):
                    raise ProtocolError("INVALID_PAYLOAD","unsupported recipe tag",request_id)
                key=(tag["tag_type"],tag["code"])
                if key in seen_tags:raise ProtocolError("INVALID_PAYLOAD","duplicate recipe tag",request_id)
                seen_tags.add(key);normalized_tags.append({"tag_type":key[0],"code":key[1]})
            tags=normalized_tags
    lines=[]
    for line in ingredients:
        base_keys={"ingredient_id","quantity_raw"}
        structured_keys={"requirement","amount_kind","amount_min","amount_max","unit_id",
                         "ingredient_form","measurement_basis","purpose","scaling_mode"}
        if not isinstance(line,dict) or "ingredient_id" not in line or set(line)-base_keys-structured_keys or not base_keys<=set(line):
            raise ProtocolError("INVALID_PAYLOAD","invalid Admin recipe ingredients",request_id)
        iid=line["ingredient_id"];raw=line["quantity_raw"]
        requirement=line.get("requirement","required")
        if (type(iid) is not int or not 1<=iid<=MAX_ID
            or raw is not None and (not isinstance(raw,str) or len(raw)>255 or "?" in raw)
            or requirement not in ({"required","optional"} if unified else {"required","optional","unknown"})):
            raise ProtocolError("INVALID_PAYLOAD","invalid Admin recipe ingredients",request_id)
        normalized={"ingredient_id":iid,"quantity_raw":raw.strip() if isinstance(raw,str) else None,
                    "requirement":requirement if unified else "required"}
        if unified:
            amount_kind=line.get("amount_kind","unknown")
            amount_min=line.get("amount_min");amount_max=line.get("amount_max")
            unit_id=line.get("unit_id")
            form=line.get("ingredient_form")
            basis=line.get("measurement_basis","unknown")
            purpose=line.get("purpose","unknown")
            scaling=line.get("scaling_mode","unknown")
            if (amount_kind not in {"exact","range","to_taste","as_needed","unknown"}
                or basis not in {"gross","edible","prepared","unknown"}
                or purpose not in {"main","seasoning","cooking_medium","garnish","unknown"}
                or scaling not in {"linear","fixed","unknown"}
                or form is not None and (not isinstance(form,str) or len(form)>120)
                or unit_id is not None and (type(unit_id) is not int or not 1<=unit_id<=65535)):
                raise ProtocolError("INVALID_PAYLOAD","invalid structured ingredient fields",request_id)
            if amount_kind=="exact":
                if not _positive_decimal(amount_min) or amount_max not in (None,amount_min) or unit_id is None:
                    raise ProtocolError("INVALID_PAYLOAD","exact amounts require one positive amount and a unit",request_id)
                amount_max=amount_min
            elif amount_kind=="range":
                if not _positive_decimal(amount_min) or not _positive_decimal(amount_max) or Decimal(amount_min)>=Decimal(amount_max) or unit_id is None:
                    raise ProtocolError("INVALID_PAYLOAD","ranges require increasing amounts and a unit",request_id)
            else:
                amount_min=amount_max=None
                if amount_kind in {"to_taste","as_needed"} and not normalized["quantity_raw"]:
                    normalized["quantity_raw"]={"to_taste":"nêm vừa ăn","as_needed":"tùy lượng"}[amount_kind]
            normalized.update(amount_kind=amount_kind,amount_min=amount_min,amount_max=amount_max,unit_id=unit_id,
                              ingredient_form=form.strip() if isinstance(form,str) and form.strip() else None,
                              measurement_basis=basis,purpose=purpose,scaling_mode=scaling)
        lines.append(normalized)
    if not allow_repeated and len({x["ingredient_id"] for x in lines})!=len(lines):
        raise ProtocolError("INVALID_PAYLOAD","duplicate Admin recipe ingredient",request_id)
    if not update and (not isinstance(payload["idempotency_key"],str)
        or len(payload["idempotency_key"])!=36 or any(char not in "0123456789abcdefABCDEF-" for char in payload["idempotency_key"])):
        raise ProtocolError("INVALID_PAYLOAD","invalid Admin recipe idempotency key",request_id)
    out={"title":title.strip(),"description":description.strip(),"instructions":instructions.strip(),
         "minutes":minutes,"ingredients":lines,"role":role}
    if unified:
        out.update(servings=servings,minutes_prep=minutes_prep,minutes_cook=minutes_cook,steps=steps)
        from source.server.beverages import validate_settings
        try:out.update(validate_settings(payload,role))
        except ValueError as exc:raise ProtocolError("INVALID_PAYLOAD",str(exc),request_id) from None
        if payload.get("portion_data_status") is not None:
            out["portion_data_status"]=review_status
            out["portion_data_evidence"]=review_evidence.strip()
        if "source_url" in payload:out["source_url"]=source_url
        if "tags" in payload:out["tags"]=tags
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
