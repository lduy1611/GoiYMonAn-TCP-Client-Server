from __future__ import annotations

import unicodedata

import pytest

from source.server.search import search_recipes, validate_search
from tests.test_web_integration import web_with_tcp

REQUEST_ID = "e35954bb-19f1-40a6-a8d2-77288ead8050"


def search(recipes, query, **filters):
    return search_recipes(recipes, validate_search({"query": query, **filters}, REQUEST_ID))


def ids(result):
    return [item["recipe_id"] for item in result["items"]]


def test_reproduce_ca_returns_fish_instead_of_canh_or_ca_chua(web_with_tcp):
    client, _, _ = web_with_tcp
    result = client.post("/api/search", json={"query": "cá"}).json()["data"]
    assert ids(result) == [7], [(item["recipe_id"], item["title"]) for item in result["items"]]


@pytest.fixture
def recipes():
    # Deliberately give less relevant matches smaller IDs and reverse the input.
    rows = [
        (1, "Canh gà nấm hương", ["Thịt gà", "Cà rốt"]),
        (2, "Cà ri", ["Cà rốt"]),
        (3, "Gà luộc", ["Thịt gà"]),
        (4, "Món hấp", ["Cá basa"]),
        (5, "Rau xào", ["Cà rốt"]),
        (6, "Chả cá chiên", ["Cá basa"]),
        (7, "Cá basa kho gừng", ["Cá basa"]),
        (8, "Gà", ["Thịt gà"]),
        (9, "Cá", ["Cá basa"]),
        (10, "Ca", []),
        (11, "Ga", []),
        (12, "Canh", []),
        (13, "Món trộn", ["Thịt gà"]),
        (14, "Gạo rang", []),
        (15, "Canhga", []),
        (16, "Cacao", []),
    ]
    return [{"id": rid, "title": title, "minutes": 20,
             "required_ids": {rid}, "all_ids": {rid, 99}, "ingredient_names": names}
            for rid, title, names in reversed(rows)]


@pytest.mark.parametrize("query,expected", [
    ("cá", [9, 7, 6, 4]),
    ("ca", [10, 9, 2, 7, 6, 1, 4, 5]),
    ("cà", [2, 1, 5]),
    ("canh", [12, 1]),
    ("gà", [8, 3, 1, 13]),
    ("ga", [11, 8, 3, 1, 13]),
    ("cá basa", [7, 4, 6, 9]),
    ("  CÁ   BASA ", [7, 4, 6, 9]),
    (unicodedata.normalize("NFD", "CÁ"), [9, 7, 6, 4]),
    ("cá bas", []),
    ("%", []),
    ("_", []),
])
def test_accent_word_boundaries_and_title_before_ingredients(recipes, query, expected):
    assert ids(search(recipes, query, limit=20)) == expected


def test_rank_before_pagination_and_keep_filters(recipes):
    assert ids(search(recipes, "cá", limit=2)) == [9, 7]
    page = search(recipes, "cá", limit=2, offset=2)
    assert ids(page) == [6, 4] and page["total"] == 4 and not page["has_more"]
    filtered = search(recipes, "cá", ingredient_ids=[4, 6], max_missing=0, limit=1)
    assert ids(filtered) == [6] and filtered["total"] == 2 and filtered["has_more"]
    assert ids(search(recipes, "cá", ingredient_ids=[4, 6], max_missing=0, limit=1, offset=1)) == [4]
    assert search(recipes, "cá", excluded_ids=[99])["total"] == 0
    assert search(recipes, "cá", max_minutes=19)["total"] == 0


def test_boundaries_include_punctuation_but_not_inside_words():
    rows = [{"id": i, "title": title, "minutes": 10, "all_ids": set(), "required_ids": set()}
            for i, title in enumerate(["Canh", "Cacao", "Cá-hấp", "Chả (cá)", "Cábasà"], 1)]
    assert ids(search(rows, "cá")) == [3, 4]
    assert ids(search(rows, "ca")) == [3, 4]


def test_folded_title_still_precedes_literal_ingredient_and_exact_accent_wins_ties():
    rows = [{"id": i, "title": title, "minutes": 10, "all_ids": set(), "required_ids": set(),
             "ingredient_names": names}
            for i, title, names in [(1, "Món hấp", ["Ca"]), (2, "Chả cá", []),
                                    (3, "Chả ca", [])]]
    assert ids(search(rows, "ca")) == [3, 2, 1]
    assert ids(search(rows, "cá")) == [2]


@pytest.mark.parametrize("query,expected", [
    ("cà", [1, 4, 9, 2, 6, 10]),
    ("ca", [7, 1, 4, 9, 2, 6, 10]),
    ("canh", [6]),
    ("gà", [6]),
    ("ga", [6]),
    ("gừng", [7, 6]),
])
def test_http_tcp_repository_supplies_ingredient_names(web_with_tcp, query, expected):
    client, _, _ = web_with_tcp
    response = client.post("/api/search", json={"query": query, "limit": 20})
    assert response.status_code == 200
    assert ids(response.json()["data"]) == expected
