import pytest

from source.common.protocol import ProtocolError
from source.server.admin_recipes import mysql_save_error, validate_save
from source.server.legacy_recipe_overlays import validate_update
from tests.meal_plan_fixtures import REQUEST_ID


def v2_payload(line):
    return {
        "title": "TEST_ONLY stew",
        "description": "",
        "instructions": "TEST_ONLY steps",
        "minutes": 20,
        "role": "main",
        "idempotency_key": "456789ab-cdef-4123-8456-789abcdef012",
        "ingredients": [line],
    }


@pytest.mark.parametrize("line", [
    {"ingredient_id": 1, "quantity_raw": None},
    {"ingredient_id": 1, "quantity_raw": "", "requirement": "optional"},
    {"ingredient_id": 1, "quantity_raw": "1 tsp", "requirement": "unknown"},
])
def test_admin_recipe_lines_always_normalize_to_required(line):
    result = validate_save(v2_payload(line), REQUEST_ID)
    assert result["ingredients"] == [{
        "ingredient_id": 1,
        "quantity_raw": (line["quantity_raw"].strip() if isinstance(line["quantity_raw"], str) else None),
        "requirement": "required",
    }]


def test_admin_recipe_rejects_invalid_legacy_requirement_value():
    with pytest.raises(ProtocolError) as error:
        validate_save(v2_payload({"ingredient_id": 1, "quantity_raw": None, "requirement": "sometimes"}), REQUEST_ID)
    assert error.value.code == "INVALID_PAYLOAD"


def test_admin_recipe_update_requires_a_sha256_edit_version():
    from source.common.catalog_ids import V2_OFFSET

    payload=v2_payload({"ingredient_id":1,"quantity_raw":None})
    payload.pop("idempotency_key")
    payload.update(recipe_id=V2_OFFSET+1,revision_id=10,expected_version="a"*64)
    result=validate_save(payload,REQUEST_ID,update=True)
    assert result["expected_version"]=="a"*64
    payload["expected_version"]="bad"
    with pytest.raises(ProtocolError) as error:
        validate_save(payload,REQUEST_ID,update=True)
    assert error.value.code=="INVALID_PAYLOAD"


def test_unified_recipe_tags_do_not_require_optional_source_url():
    payload=v2_payload({"ingredient_id":1,"quantity_raw":"250 g"})
    payload.update(servings=None,minutes_prep=None,minutes_cook=None,steps=None,tags=[])
    optional_metadata_payload=v2_payload({"ingredient_id":1,"quantity_raw":"250 g"})
    assert validate_save(optional_metadata_payload,REQUEST_ID,unified=True)["role"]=="main"
    payload["tags"]=[{"tag_type":"diet","code":"vegetarian"}]
    result=validate_save(payload,REQUEST_ID,unified=True)
    assert result["tags"]==payload["tags"]
    payload.pop("source_url",None)
    payload["tags"]=[{"tag_type":"diet","code":"non_vegetarian"}]
    with pytest.raises(ProtocolError,match="unsupported recipe tag"):
        validate_save(payload,REQUEST_ID,unified=True)


def test_admin_recipe_rejects_question_mark_in_quantity_but_allows_free_text():
    payload = v2_payload({"ingredient_id": 1, "quantity_raw": "250 g?"})
    with pytest.raises(ProtocolError) as error:
        validate_save(payload, REQUEST_ID)
    assert error.value.code == "INVALID_PAYLOAD"

    payload["ingredients"][0]["quantity_raw"] = "250 g"
    payload["description"] = "Is this the right amount?"
    payload["instructions"] = "Check the texture? Continue cooking until tender."
    result = validate_save(payload, REQUEST_ID)
    assert result["description"].endswith("?")
    assert result["instructions"].endswith("tender.")


def test_legacy_admin_edit_also_forces_required_ingredients():
    payload = {
        "recipe_id": 1,
        "title": "TEST_ONLY legacy",
        "description": "",
        "instructions": "TEST_ONLY steps",
        "minutes": 12,
        "is_visible": True,
        "expected_version": "a" * 64,
        "ingredients": [{"ingredient_id": 2, "quantity": "", "is_required": False}],
    }
    result = validate_update(payload, REQUEST_ID)
    assert result["ingredients"][0]["is_required"] is True


@pytest.mark.parametrize(("errno", "code"), [
    (1142, "ADMIN_WRITE_DENIED"),
    (3819, "ADMIN_RECIPE_CONSTRAINT"),
    (1366, "ADMIN_RECIPE_INVALID_DATA"),
    (2003, "DB_UNAVAILABLE"),
])
def test_mysql_write_error_is_classified_without_exposing_sql(errno, code):
    class MysqlFailure(Exception):
        pass

    failure = MysqlFailure("TEST_ONLY sensitive SQL text")
    failure.errno = errno
    mapped = mysql_save_error(failure, REQUEST_ID)
    assert isinstance(mapped, ProtocolError)
    assert mapped.code == code
    assert "sensitive SQL" not in mapped.message
