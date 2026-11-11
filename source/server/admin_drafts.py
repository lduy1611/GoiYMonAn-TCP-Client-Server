"""Strict validation for unauthored Admin draft mutations; no approval fields."""
from source.common.protocol import ProtocolError

MAX_ID=2**64-1


def _reject(request_id):
    raise ProtocolError("INVALID_PAYLOAD","invalid Admin draft payload",request_id)


def validate_draft_fields(payload,request_id,*,update=False):
    required={"title","description","instructions","minutes","ingredients"}
    allowed=required|({"revision_id"} if update else set())
    if not isinstance(payload,dict) or set(payload)!=allowed:
        _reject(request_id)
    if update and (type(payload["revision_id"]) is not int or not 1<=payload["revision_id"]<=MAX_ID):
        _reject(request_id)
    title=payload["title"]
    description=payload["description"]
    instructions=payload["instructions"]
    minutes=payload["minutes"]
    ingredients=payload["ingredients"]
    if (not isinstance(title,str) or not 1<=len(title.strip())<=255
            or not isinstance(description,str) or len(description.strip())>1000
            or not isinstance(instructions,str) or not 1<=len(instructions.strip())<=12000
            or (minutes is not None and (type(minutes) is not int or not 1<=minutes<=240))
            or not isinstance(ingredients,list) or not 1<=len(ingredients)<=50):
        _reject(request_id)
    normalized=[]
    for line in ingredients:
        if not isinstance(line,dict) or set(line)!={"ingredient_id","quantity_raw","requirement"}:
            _reject(request_id)
        iid=line["ingredient_id"]
        raw=line["quantity_raw"]
        requirement=line["requirement"]
        if (type(iid) is not int or not 1<=iid<=MAX_ID
                or raw is not None and (not isinstance(raw,str) or len(raw)>255)
                or not isinstance(requirement,str) or requirement not in {"required","optional","unknown"}):
            _reject(request_id)
        normalized.append({"ingredient_id":iid,"quantity_raw":raw.strip() if isinstance(raw,str) else None,
                           "requirement":requirement})
    if len({line["ingredient_id"] for line in normalized})!=len(normalized):
        _reject(request_id)
    result={"title":title.strip(),"description":description.strip(),"instructions":instructions.strip(),
            "minutes":minutes,"ingredients":normalized}
    if update:result["revision_id"]=payload["revision_id"]
    return result
