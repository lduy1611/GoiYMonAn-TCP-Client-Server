"""Conservative plant-only review gate over complete legacy recipe snapshots.

Absence of an animal match is not proof. A positive review must cover required,
optional and instruction-only components, including seasonings/compositions.
This does not approve any v2 revision, source, portion quantity or release.
"""
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata

PROFILE = "plant-only-v1"
REVIEW_PATH = Path(__file__).resolve().parents[2] / "data/vegetarian_reviews.json"
# Identity IDs alone never establish a positive assertion. Names/instructions
# are checked too, so omitted relations and optional fish sauce cannot pass.
ANIMAL_NAMES = frozenset(("Trứng", "Thịt", "Cá basa", "Thịt gà", "Nước mắm", "Mắm ruốc",
                         "Cua đồng", "Giò sống", "Tôm", "Mực", "Thịt bò", "Thịt heo xay", "Sườn heo"))
ANIMAL_PATTERN = re.compile(r"\b(?:nước mắm|mắm ruốc|mắm tôm|thịt|cá|tôm|mực|cua|sườn|xương|trứng|sữa|mật ong|gelatin|mỡ heo|mỡ lợn|bơ sữa|butter|fish sauce|shrimp|chicken|beef|pork|milk|egg|lard)\b", re.IGNORECASE)
VAGUE_PATTERN = re.compile(r"\b(?:nêm (?:vừa ăn|lại|nhẹ)|gia vị (?:vừa đủ|tùy thích)|dầu nóng)\b", re.IGNORECASE)


def normalized(value):
    return unicodedata.normalize("NFC", str(value or ""))


def snapshot_hash(recipe):
    value = {k: recipe.get(k) for k in ("id", "title", "instructions", "minutes", "source_url")}
    value["ingredients"] = sorted(({k: i.get(k) for k in ("id", "name", "quantity", "is_required")}
                                   for i in recipe.get("ingredients", [])), key=lambda i: i["id"])
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def read_reviews():
    try:
        manifest = json.loads(REVIEW_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(manifest, dict):
        return {}
    rows = manifest.get("reviews")
    if manifest.get("profile") != PROFILE or not isinstance(rows, list):
        return {}
    if any(not isinstance(r, dict) or type(r.get("recipe_id")) is not int for r in rows):
        return {}
    result = {r["recipe_id"]: r for r in rows}
    return result if len(result) == len(rows) else {}


def assess(recipe, review=None):
    ingredients = recipe.get("ingredients", [])
    instructions = normalized(recipe.get("instructions"))
    text = instructions + " " + " ".join(normalized(i.get("name")) + " " + normalized(i.get("quantity")) for i in ingredients)
    terms = sorted(set(m.group().casefold() for m in ANIMAL_PATTERN.finditer(text)))
    animal_ids = sorted(i["id"] for i in ingredients if normalized(i.get("name")) in ANIMAL_NAMES)
    result = {"recipe_id": recipe["id"], "snapshot_sha256": snapshot_hash(recipe),
              "animal_ingredient_ids": animal_ids, "animal_instruction_terms": terms}
    if animal_ids or terms:
        return {**result, "status": "INCOMPATIBLE", "reasons": ["Có thành phần động vật hoặc nước mắm thông thường trong nguyên liệu/hướng dẫn; kể cả thành phần tùy chọn."]}
    unknown = {**result, "status": "NEEDS_VERIFICATION", "reasons": ["Chưa xác minh đầy đủ gia vị, dầu/chế phẩm, thành phần tùy chọn và thành phần chỉ ghi trong hướng dẫn."]}
    if VAGUE_PATTERN.search(text):
        return {**unknown, "reasons": ["Hướng dẫn còn ghi gia vị/dầu không rõ thành phần (như nêm vừa ăn, nêm lại hoặc dầu nóng); không thể xác nhận chay bằng cờ trạng thái."]}
    if not review or review.get("status") != "VERIFIED" or review.get("profile") != PROFILE:
        return unknown
    if (review.get("snapshot_sha256") != result["snapshot_sha256"] or not ingredients or not instructions.strip()
            or any(type(i.get("id")) is not int or not str(i.get("name", "")).strip()
                   or type(i.get("is_required")) is not bool for i in ingredients)
            or any(review.get(k) is not True for k in ("components_complete", "instructions_complete", "optional_components_included"))
            or review.get("unresolved") != []
            or any(not isinstance(review.get(k), str) or not review[k].strip() for k in ("reviewer_ref", "evidence_ref", "reviewed_on"))):
        return unknown
    covered = review.get("ingredient_evidence")
    if (not isinstance(covered, list) or len(covered) != len(ingredients)
            or any(not isinstance(e, dict) or type(e.get("ingredient_id")) is not int for e in covered)
            or {e.get("ingredient_id") for e in covered if isinstance(e, dict)} != {i["id"] for i in ingredients}
            or any(not isinstance(e, dict) or e.get("classification") != "plant_or_mineral"
                   or not isinstance(e.get("evidence_ref"), str) or not e["evidence_ref"].strip() for e in covered)):
        return unknown
    extras = review.get("instruction_only_components")
    if (not isinstance(extras, list) or any(not isinstance(e, dict) or e.get("classification") != "plant_or_mineral"
            or not isinstance(e.get("name"),str) or not e["name"].strip()
            or not isinstance(e.get("evidence_ref"),str) or not e["evidence_ref"].strip()
            or ANIMAL_PATTERN.search(normalized(e["name"])) for e in extras)):
        return unknown
    return {**result, "status": "VERIFIED", "reasons": []}
