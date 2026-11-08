from __future__ import annotations

import unicodedata

import pytest

from source.client.tcp_client import TCPClient
from source.common.protocol import ProtocolError, encode_frame
from source.server.search import fold_name, search_recipes, validate_search
from tests.test_web_integration import web_with_tcp

REQUEST_ID = "e35954bb-19f1-40a6-a8d2-77288ead8050"


@pytest.mark.parametrize("query", ["ĐẬU PHỤ", "dau phu", unicodedata.normalize("NFD", "đậu phụ"), "  Đậu   phụ "])
def test_name_folding(query):
    assert fold_name(query) == "dau phu"


def test_search_relevance_and_filtering_before_pagination():
    recipes = [
        {"id": i, "title": title, "minutes": minutes, "required_ids": required, "all_ids": required | optional}
        for i, title, minutes, required, optional in [
            (1, "Phở bò", 90, {1, 2}, {3}), (2, "Phở", 30, {1}, set()),
            (3, "Canh phở", 20, {1, 2}, set()), (4, "Phở gà", 60, {2}, set()),
        ]
    ]
    result = search_recipes(recipes, validate_search({"query": "pho", "limit": 2}, REQUEST_ID))
    assert [item["recipe_id"] for item in result["items"]] == [2, 1]
    assert result["total"] == 4 and result["has_more"]
    result = search_recipes(recipes, validate_search({"query": "phở", "ingredient_ids": [1],
        "excluded_ids": [3], "max_minutes": 60, "max_missing": 1, "limit": 1, "offset": 1}, REQUEST_ID))
    assert result["total"] == 3
    assert result["items"] == [{"recipe_id": 4, "title": "Phở gà", "minutes": 60,
        "matched_ids": [], "missing_ids": [2], "missing_count": 1}]
    assert result["has_more"]
    assert "score" not in result["items"][0]


@pytest.mark.parametrize("payload", [
    {"query": None}, {"query": 1}, {"query": "x" * 81}, {"unknown": 1},
    {"ingredient_ids": None}, {"ingredient_ids": {}}, {"ingredient_ids": [True]},
    {"ingredient_ids": [0]}, {"ingredient_ids": [-1]}, {"ingredient_ids": ["1"]},
    {"ingredient_ids": [1] * 31}, {"excluded_ids": [False]}, {"excluded_ids": [1] * 31},
    {"ingredient_ids": [1], "excluded_ids": [1]},
    {"max_minutes": 0}, {"max_minutes": 241}, {"max_minutes": True}, {"max_minutes": "20"},
    {"max_missing": -1}, {"max_missing": 51}, {"max_missing": False}, {"max_missing": 1.5},
    {"limit": 0}, {"limit": 21}, {"limit": None}, {"limit": True},
    {"offset": -1}, {"offset": True}, {"offset": 1.5}, {"offset": "0"},
])
def test_search_validation_rejects_invalid_payload(payload):
    with pytest.raises(ProtocolError) as error:
        validate_search(payload, REQUEST_ID)
    assert error.value.code == "INVALID_PAYLOAD"
    assert error.value.request_id == REQUEST_ID


def test_search_defaults_and_empty_page():
    options = validate_search({}, REQUEST_ID)
    assert options.max_missing is None and not options.selected and options.limit == 12
    assert search_recipes([], options) == {"items": [], "total": 0, "limit": 12,
        "offset": 0, "has_more": False, "warnings": ["NO_MATCH"]}
    assert search_recipes([], validate_search({"offset": 10**40}, REQUEST_ID))["items"] == []


def test_search_invalid_request_does_not_break_persistent_connection(web_with_tcp):
    _, server, _ = web_with_tcp
    client = TCPClient(port=server.port, persistent=True)
    try:
        response = client.request("SEARCH_RECIPES", {"offset": -1}, request_id=REQUEST_ID)
        assert response["error"]["code"] == "INVALID_PAYLOAD" and response["request_id"] == REQUEST_ID
        original = client.sock
        assert client.request("SEARCH_RECIPES", {})["ok"]
        assert client.request("PING", {})["ok"] and client.sock is original
    finally:
        client.close()


@pytest.mark.parametrize("query", ["trứng", "TRUNG", unicodedata.normalize("NFD", "Trứng")])
def test_tcp_search_without_ingredients_and_no_score(web_with_tcp, query):
    _, server, _ = web_with_tcp
    client = TCPClient(port=server.port, persistent=True)
    try:
        response = client.request("SEARCH_RECIPES", {"query": query}, request_id=REQUEST_ID)
        assert response["version"] == 1 and response["request_id"] == REQUEST_ID and response["ok"]
        # Recipe 2 contains eggs, but its title does not: it follows all title hits.
        assert [item["recipe_id"] for item in response["data"]["items"]] == [1, 3, 10, 2]
        assert all(item["missing_count"] == len(item["missing_ids"]) > 0 for item in response["data"]["items"])
        assert all(not item["matched_ids"] and "score" not in item for item in response["data"]["items"])
        assert client.request("PING", {})["ok"]
        assert client.request("LIST_INGREDIENTS", {})["data"]["items"]
        assert client.request("GET_RECIPE", {"recipe_id": 1})["data"]["id"] == 1
        for algorithm in ("baseline", "proposed"):
            assert client.request("RECOMMEND", {"ingredient_ids": [1, 2], "algorithm": algorithm})["data"]["algorithm"] == algorithm
    finally:
        client.close()


def test_web_search_combined_filters_and_pages(web_with_tcp):
    client, _, _ = web_with_tcp
    payload = {"query": "trung", "ingredient_ids": [1, 2], "excluded_ids": [7],
               "max_minutes": 20, "max_missing": 0, "limit": 1}
    first = client.post("/api/search", json=payload)
    assert first.status_code == 200
    assert first.headers["x-request-id"] == first.json()["request_id"]
    assert first.json()["data"]["total"] == 2
    assert first.json()["data"]["items"][0]["recipe_id"] == 1
    second = client.post("/api/search", json={**payload, "offset": 1}).json()["data"]
    assert second["items"][0]["recipe_id"] == 3 and not second["has_more"]
    beyond = client.post("/api/search", json={**payload, "offset": 99}).json()["data"]
    assert beyond["total"] == 2 and beyond["items"] == [] and not beyond["has_more"]
    for query in ("%", "_", "' OR 1=1 --", "khong-co-mon-nay"):
        response = client.post("/api/search", json={"query": query})
        assert response.status_code == 200 and response.json()["data"]["total"] == 0


@pytest.mark.parametrize("payload", [{"query": 1}, {"offset": -1}, {"limit": True},
    {"max_missing": 51}, {"ingredient_ids": [True]}, {"ingredient_ids": [999999]},
    {"ingredient_ids": [1], "excluded_ids": [1]}, {"algorithm": "proposed"}])
def test_web_and_tcp_search_reject_invalid_input(web_with_tcp, payload):
    client, server, _ = web_with_tcp
    response = client.post("/api/search", json=payload)
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_PAYLOAD"
    response = TCPClient(port=server.port).request("SEARCH_RECIPES", payload, request_id=REQUEST_ID)
    assert response["request_id"] == REQUEST_ID and response["error"]["code"] == "INVALID_PAYLOAD"


def test_search_worst_case_response_fits_v1_frame():
    recipes = [{"id": i, "title": "ế" * 255, "minutes": 20,
                "required_ids": set(range(1, 51)), "all_ids": set(range(1, 51))} for i in range(1, 21)]
    data = search_recipes(recipes, validate_search({"limit": 20}, REQUEST_ID))
    from source.common.protocol import success_response
    assert len(encode_frame(success_response(REQUEST_ID, {"dataset_version": "test", **data}))) <= 65540
