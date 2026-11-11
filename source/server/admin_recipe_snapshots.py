"""Validation for Admin-authenticated recipe snapshot restores."""
import re

from source.common.catalog_ids import UINT32_MAX, valid_public_id
from source.common.protocol import ProtocolError


def validate_restore(payload, request_id):
    def reject():
        raise ProtocolError("INVALID_PAYLOAD", "invalid recipe snapshot restore payload", request_id)

    common={"kind","recipe_id","expected_version","title","description","instructions","minutes","ingredients"}
    if not isinstance(payload,dict) or payload.get("kind") not in {"legacy","v2"}:
        reject()
    kind=payload["kind"]
    allowed=common|({"is_visible"} if kind=="legacy" else {"revision_id","role"})
    if set(payload)!=allowed:
        reject()
    recipe_id=payload["recipe_id"]
    if not valid_public_id(recipe_id) or (recipe_id<=UINT32_MAX)!=(kind=="legacy"):
        reject()
    version=payload["expected_version"]
    if not isinstance(version,str) or not re.fullmatch(r"[0-9a-f]{64}",version):
        reject()
    title,description,instructions,minutes=payload["title"],payload["description"],payload["instructions"],payload["minutes"]
    lines=payload["ingredients"]
    if (not isinstance(title,str) or not 1<=len(title.strip())<=255
        or not isinstance(description,str) or len(description)>1000
        or not isinstance(instructions,str) or not 1<=len(instructions.strip())<=12000
        or type(minutes) is not int or not 1<=minutes<=240
        or not isinstance(lines,list) or not 1<=len(lines)<=100):
        reject()
    normalized=[]
    for line in lines:
        if kind=="legacy":
            if not isinstance(line,dict) or set(line)!={"ingredient_id","quantity","is_required"}:
                reject()
            iid,quantity,required=line["ingredient_id"],line["quantity"],line["is_required"]
        else:
            if not isinstance(line,dict) or set(line)!={"ingredient_id","quantity_raw","requirement"}:
                reject()
            iid,quantity,requirement=line["ingredient_id"],line["quantity_raw"],line["requirement"]
            if requirement not in {"required","optional","unknown"}:
                reject()
            required=None
        if (type(iid) is not int or not valid_public_id(iid)
            or quantity is not None and (not isinstance(quantity,str) or len(quantity)>255)):
            reject()
        if kind=="legacy" and type(required) is not bool:
            reject()
        normalized.append({"ingredient_id":iid,"quantity":quantity,"is_required":required} if kind=="legacy"
                          else {"ingredient_id":iid,"quantity_raw":quantity,"requirement":requirement})
    if len({line["ingredient_id"] for line in normalized})!=len(normalized):
        reject()
    result={key:payload[key] for key in ("kind","recipe_id","expected_version","title","description","instructions","minutes")}
    result["ingredients"]=normalized
    if kind=="legacy":
        if type(payload["is_visible"]) is not bool:reject()
        result["is_visible"]=payload["is_visible"]
    else:
        if (type(payload["revision_id"]) is not int or payload["revision_id"]<=0
            or payload["role"] not in {"main","vegetable","soup"}):reject()
        result["revision_id"]=payload["revision_id"]
        result["role"]=payload["role"]
    return result
