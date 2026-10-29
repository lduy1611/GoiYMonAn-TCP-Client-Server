from source.server.ranking import rank_recipes


def fixture():
    return [{"id": 1, "title": "A", "minutes": 15, "required_ids": {1, 2}, "all_ids": {1, 2}}, {"id": 2, "title": "B", "minutes": 30, "required_ids": {1, 2, 3, 4}, "all_ids": {1, 2, 3, 4}}, {"id": 3, "title": "C", "minutes": 10, "required_ids": {1}, "all_ids": {1, 3}}]


def test_spec_fixture_order_and_scores():
    result = rank_recipes(fixture(), {1, 2}, set(), None, 5, "proposed")
    assert [item["recipe_id"] for item in result] == [1, 3, 2]
    assert [item["score"] for item in result] == [1.0, 0.85, 0.65]


def test_optional_exclusion_and_time_filter():
    assert [x["recipe_id"] for x in rank_recipes(fixture(), {1, 2}, {3}, None, 5, "proposed")] == [1]
    assert [x["recipe_id"] for x in rank_recipes(fixture(), {1, 2}, set(), 15, 5, "proposed")] == [1, 3]
