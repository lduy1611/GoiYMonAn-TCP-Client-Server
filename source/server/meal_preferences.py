"""Positive ingredient evidence, separate from v2 revision/release approval.

The meat profile is a meal-level requirement. Plant-only eligibility instead
requires complete snapshot-bound component reviews for every selected dish.
Missing facts fail closed; region/occasion metadata remains unavailable.
"""
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import unicodedata

from source.common.protocol import ProtocolError
from source.server import vegetarian

PATH = Path(__file__).resolve().parents[2] / "data/meal_preferences.json"
CODES = {
    "diet": {"non_vegetarian": "Mặn", "vegetarian": "Chay"},
    "region": {"north": "Miền Bắc", "central": "Miền Trung", "south": "Miền Nam"},
    "occasion": {"daily": "Hằng ngày", "weekend": "Cuối tuần", "guests": "Đãi khách",
                 "birthday": "Sinh nhật", "tet": "Tết", "ancestral": "Cúng gia tiên"},
}


def validate(value, request_id):
    if (not isinstance(value, dict) or set(value) - set(CODES)
            or any(not isinstance(v, str) or v not in CODES[k] for k, v in value.items())):
        raise ProtocolError("INVALID_PAYLOAD", "invalid meal preferences", request_id)
    return dict(value)


@dataclass(frozen=True)
class Catalog:
    version: str
    evidence: dict[int, tuple[int, ...]]
    roles: dict[int, str]
    vegetarian_assessments: dict[int, dict] = field(default_factory=dict)
    # Only release-pinned, approved revision assertions may populate this map.
    # Shape: {"region": {"south": frozenset(recipe_ids)}, "occasion": ...}
    contexts: dict[str, dict[str, frozenset[int]]] = field(default_factory=dict)

    @property
    def vegetarian_ids(self):
        return frozenset(rid for rid, result in self.vegetarian_assessments.items()
                         if result["status"] == "VERIFIED" and self.roles.get(rid) in ("main", "vegetable", "soup"))

    @property
    def meat_ids(self):
        return frozenset(self.evidence)

    def unsupported(self, preferences):
        return [key for key, value in preferences.items()
                if (key == "diet" and (value not in ("non_vegetarian", "vegetarian")
                                        or value == "non_vegetarian" and not self.evidence)
                    or key in ("region", "occasion") and not self._context_supported(key, value)
                    or key not in ("diet", "region", "occasion"))]

    def _context_supported(self, group, code):
        ids = self.contexts.get(group, {}).get(code, frozenset())
        counts = {g: sum(self.roles.get(rid) == g for rid in ids) for g in ("main", "vegetable", "soup")}
        minimum = {"main": 1, "vegetable": 1, "soup": 1}
        return all(counts[g] >= minimum[g] for g in counts)

    def eligible_ids(self, group, code):
        return self.contexts.get(group, {}).get(code, frozenset())

    def capabilities(self, *, layout_support=False):
        choices = {}
        for group, codes in CODES.items():
            choices[group] = []
            for code, label in codes.items():
                if group == "diet" and code == "vegetarian":
                    from source.server.meal_plan_v2 import counts_for_people
                    counts = {g: sum(self.roles.get(rid) == g for rid in self.vegetarian_ids) for g in ("main", "vegetable", "soup")}
                    supported = [n for n in range(1,13) if all(counts[g] >= required for g, required in counts_for_people(n).items())]
                    choices[group].append({"code": code, "label": label, "enabled": bool(supported) if layout_support else 4 in supported,
                        "recipe_count": len(self.vegetarian_ids), "role_counts": counts,
                        **({"supported_people": supported} if layout_support else {}),
                        "reason": "Chỉ dùng công thức đã xác minh đầy đủ thành phần thực vật/khoáng, kể cả gia vị và nguyên liệu tùy chọn; không trứng, sữa hoặc nước mắm thông thường."
                            if supported else "Chưa đủ món chay được xác minh để ghép mâm: " +
                            f"{counts['main']} chính, {counts['vegetable']} rau, {counts['soup']} canh. Công thức thiếu thông tin vẫn cần xác minh."})
                    continue
                if group in ("region", "occasion"):
                    ids = self.eligible_ids(group, code)
                    counts = {g: sum(self.roles.get(rid) == g for rid in ids)
                              for g in ("main", "vegetable", "soup")}
                    supported = all(counts[g] >= 1 for g in counts)
                    choices[group].append({"code": code, "label": label, "enabled": supported,
                        "recipe_count": len(ids), "role_counts": counts,
                        "reason": "Äá»§ metadata Ä‘Ã£ duyá»‡t cho cáº¥u trÃºc 4 ngÆ°á»i (1 chÃ­nh, 1 rau, 1 canh)." if supported else
                            "ChÆ°a Ä‘á»§ metadata Ä‘Ã£ duyá»‡t Ä‘á»ƒ ghÃ©p mÃ¢m 4 ngÆ°á»i: cáº§n Ã­t nháº¥t 1 mÃ³n chÃ­nh, 1 mÃ³n rau vÃ  1 mÃ³n canh. NEEDS_VERIFICATION khÃ´ng Ä‘Æ°á»£c tÃ­nh."})
                    continue
                usable = group == "diet" and code == "non_vegetarian" and bool(self.evidence)
                counts = {g: sum(self.roles.get(rid) == g for rid in self.evidence)
                          for g in ("main", "vegetable", "soup")}
                choices[group].append({"code": code, "label": label, "enabled": usable,
                    "recipe_count": len(self.evidence) if usable else 0,
                    "role_counts": counts if usable else dict.fromkeys(counts, 0),
                    "reason": "Ít nhất một món có thịt/cá/hải sản bắt buộc trong công thức gốc; rau và canh có thể là món thực vật." if usable else
                        "Chưa có đủ bằng chứng thành phần thịt/cá/hải sản trong dữ liệu hiện tại." if group == "diet" and code == "non_vegetarian" else
                        "Chưa đủ metadata vùng miền được xác minh cho đúng phiên bản công thức." if group == "region" else
                        "Chưa xác minh đủ thành phần, gia vị và lựa chọn tùy chọn để chứng nhận chay." if group == "diet" else
                        "Chưa có metadata dịp ăn và bối cảnh sử dụng được xác minh."})
        return {"metadata_version": self.version, "choices": choices,
                "scope": "positive_required_ingredient_evidence",
                "role_recipe_count": len(self.roles)}


def load(recipes, ingredient_names, classification, details=()):
    """Exact source identities and required membership, all read from the server DB."""
    registry = json.loads(PATH.read_text(encoding="utf-8"))
    if registry.get("basis") != "positive_required_ingredient_evidence":
        raise ValueError("unknown meal metadata basis")
    explicit = {entry["ingredient_id"] for entry in registry["explicit_animal_ingredients"]
                if unicodedata.normalize("NFC", ingredient_names.get(entry["ingredient_id"], "")) == entry["expected_name"]}
    roles = {r["id"]: classification.categories[r["id"]] for r in recipes if r["id"] in classification.categories}
    evidence = {r["id"]: tuple(sorted(set(r["required_ids"]) & explicit)) for r in recipes
                if roles.get(r["id"]) in ("main", "vegetable", "soup") and set(r["required_ids"]) & explicit}
    reviews = vegetarian.read_reviews()
    assessments = {r["id"]: vegetarian.assess(r, reviews.get(r["id"])) for r in details}
    # Require the detail snapshot to agree with the candidate identities in this request.
    by_id = {r["id"]: r for r in recipes}
    for r in details:
        candidate = by_id.get(r["id"])
        if (candidate is None or {i["id"] for i in r["ingredients"]} != set(candidate["all_ids"])
                or {i["id"] for i in r["ingredients"] if i["is_required"]} != set(candidate["required_ids"])):
            assessments[r["id"]] = {"status": "NEEDS_VERIFICATION", "reasons": ["Snapshot nguyên liệu đã thay đổi."]}
    digest = sha256(json.dumps([registry, sorted(roles.items()), sorted(evidence.items()), reviews, assessments],
                              ensure_ascii=True, sort_keys=True).encode()).hexdigest()[:16]
    return Catalog(registry["version"] + ":" + digest, evidence, roles, assessments)
