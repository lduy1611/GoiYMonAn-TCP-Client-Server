from __future__ import annotations

import sqlite3
import time
from typing import Any

from source.common.protocol import ProtocolError, error_response, success_response, validate_request
from source.server.ranking import rank_recipes
from source.server.repository import Repository
from source.server.search import search_recipes, validate_search


def dispatch(repository: Repository, value: Any) -> tuple[dict[str, Any], str]:
    request_id, op, payload = validate_request(value)
    connection = repository.connect()
    try:
        version = repository.dataset_version(connection)
        if op == "PING":
            if payload:
                raise ProtocolError("INVALID_PAYLOAD", "PING payload must be empty", request_id)
            return success_response(request_id, {"status": "ok", "dataset_version": version}), op
        if op == "LIST_INGREDIENTS":
            unknown = set(payload) - {"query", "limit"}
            query = payload.get("query", "")
            limit = payload.get("limit", 20)
            if unknown or not isinstance(query, str) or len(query.strip()) > 80 or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
                raise ProtocolError("INVALID_PAYLOAD", "invalid LIST_INGREDIENTS payload", request_id)
            return success_response(request_id, {"items": repository.list_ingredients(connection, query, limit), "dataset_version": version}), op
        if op == "GET_RECIPE":
            if set(payload) != {"recipe_id"} or not isinstance(payload["recipe_id"], int) or isinstance(payload["recipe_id"], bool) or payload["recipe_id"] <= 0:
                raise ProtocolError("INVALID_PAYLOAD", "invalid recipe_id", request_id)
            recipe = repository.get_recipe(connection, payload["recipe_id"])
            if recipe is None:
                raise ProtocolError("NOT_FOUND", "recipe not found", request_id)
            recipe["dataset_version"] = version
            return success_response(request_id, recipe), op
        if op == "SEARCH_RECIPES":
            options = validate_search(payload, request_id)
            if not repository.ingredient_ids_exist(connection, options.selected | options.excluded):
                raise ProtocolError("INVALID_PAYLOAD", "ingredient ids are invalid", request_id)
            data = search_recipes(repository.recipes_for_ranking(connection), options)
            return success_response(request_id, {"dataset_version": version, **data}), op
        unknown = set(payload) - {"ingredient_ids", "excluded_ids", "max_minutes", "top_k", "algorithm"}
        selected = payload.get("ingredient_ids")
        excluded = payload.get("excluded_ids", [])
        max_minutes = payload.get("max_minutes")
        top_k = payload.get("top_k", 5)
        algorithm = payload.get("algorithm", "proposed")
        if unknown or not isinstance(selected, list) or not 1 <= len(selected) <= 30 or not isinstance(excluded, list) or len(excluded) > 30 or any(not isinstance(x, int) or isinstance(x, bool) or x <= 0 for x in selected + excluded) or not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20 or (max_minutes is not None and (not isinstance(max_minutes, int) or isinstance(max_minutes, bool) or not 1 <= max_minutes <= 240)) or algorithm not in {"baseline", "proposed"}:
            raise ProtocolError("INVALID_PAYLOAD", "invalid RECOMMEND payload", request_id)
        selected_set, excluded_set = set(selected), set(excluded)
        if selected_set & excluded_set or not repository.ingredient_ids_exist(connection, selected_set | excluded_set):
            raise ProtocolError("INVALID_PAYLOAD", "ingredient ids are invalid", request_id)
        items = rank_recipes(repository.recipes_for_ranking(connection), selected_set, excluded_set, max_minutes, top_k, algorithm)
        return success_response(request_id, {"dataset_version": version, "algorithm": algorithm, "items": items, "warnings": [] if items else ["NO_MATCH"]}), op
    finally:
        connection.close()
