from __future__ import annotations

import sqlite3
import time
from typing import Any

from source.common.protocol import ProtocolError, encode_frame, error_response, success_response, validate_request
from source.server.ranking import rank_recipes
from source.server.repository import Repository
from source.server.search import search_recipes, validate_search
from source.server.meal_plan import build_shopping_lists, default_classification, generate_meal_plan, validate_meal_plan
from source.server import meal_plan_v2, meal_plan_calculation
from source.common.catalog_ids import valid_public_id


def dispatch(repository: Repository, value: Any) -> tuple[dict[str, Any], str]:
    request_id, op, payload = validate_request(value)
    if op.startswith("ADMIN_"):
        from source.common.admin_tokens import verify
        token = payload.get("admin_token")
        claims = verify(token)
        if claims is None:
            raise ProtocolError("ADMIN_UNAUTHORIZED", "administrator authentication is required", request_id)
        payload = {key:value for key,value in payload.items() if key != "admin_token"}
        # The unified v3 catalog publishes valid Admin saves directly. Prevent
        # legacy revision/review endpoints from falling through to inherited
        # v2 repository methods and touching tables outside the selected schema.
        if getattr(repository, "unified_catalog_mode", False) and op in {
            "ADMIN_CREATE_DRAFT", "ADMIN_UPDATE_DRAFT", "ADMIN_SUBMIT_REVIEW",
            "ADMIN_REVIEW_SOURCE", "ADMIN_APPROVE_RECIPE", "ADMIN_REJECT_RECIPE",
            "ADMIN_PUBLISH_RELEASE", "ADMIN_UNPUBLISH_RECIPE", "ADMIN_RESTORE_RECIPE_SNAPSHOT",
        }:
            raise ProtocolError("UNSUPPORTED_OPERATION", "v3 Admin saves directly to the unified catalog", request_id)
        if "account_uid" in claims:
            from source.server.repository import UserAccountUnauthorized, UserAccountUnavailable
            try:
                repository.user_session({"uid":claims["account_uid"],"sub":claims["sub"],"role":"ADMIN","csrf":claims["csrf"]})
            except (UserAccountUnauthorized,UserAccountUnavailable):
                raise ProtocolError("ADMIN_UNAUTHORIZED", "administrator account is locked or no longer has the ADMIN role", request_id)
    if op in {"USER_REGISTER", "USER_LOGIN", "USER_SESSION"}:
        from source.server import user_accounts
        from source.server.repository import UserAccountConflict, UserAccountUnauthorized, UserAccountUnavailable
        try:
            if op == "USER_REGISTER":
                result = repository.user_register(user_accounts.validate_register(payload, request_id))
            elif op == "USER_LOGIN":
                result = repository.user_login(user_accounts.validate_login(payload, request_id))
            else:
                claims = user_accounts.validate_session(payload, request_id)
                result = repository.user_session(claims)
        except ProtocolError:
            raise
        except UserAccountConflict as exc:
            raise ProtocolError("USER_ACCOUNT_CONFLICT", str(exc), request_id)
        except UserAccountUnauthorized as exc:
            code = "USER_LOCKED" if "locked" in str(exc) else "USER_UNAUTHORIZED"
            raise ProtocolError(code, str(exc), request_id)
        except UserAccountUnavailable:
            raise ProtocolError("USER_ACCOUNT_UNAVAILABLE", "user account migration or writer is unavailable", request_id)
        return success_response(request_id, result), op
    achievement_user = None
    if op in {"ACHIEVEMENT_CREATE", "ACHIEVEMENT_CREATE_STATUS", "ACHIEVEMENT_COMMENT_CREATE", "ACHIEVEMENT_POST_DELETE", "ACHIEVEMENT_COMMENT_DELETE"}:
        from source.common.user_tokens import verify as verify_user_token
        from source.server import achievements
        from source.server.repository import UserAccountUnauthorized
        token = payload.get("session_token")
        achievement_user = verify_user_token(token)
        if achievement_user is None:
            raise ProtocolError("USER_UNAUTHORIZED", "a signed-in account is required", request_id)
        try:
            account = repository.user_session({"uid": achievement_user["uid"], "sub": achievement_user["sub"],
                "role": achievement_user["role"], "csrf": achievement_user["csrf"]})
        except (UserAccountUnauthorized, Exception) as exc:
            # Do not turn database outages into an authorization bypass.
            if isinstance(exc, UserAccountUnauthorized):
                raise ProtocolError("USER_UNAUTHORIZED", "account is locked or unavailable", request_id)
            raise
        payload = {key: value for key, value in payload.items() if key != "session_token"}
        if op == "ACHIEVEMENT_CREATE":
            payload = achievements.validate_post({**payload, "user_id": int(account["user_id"])})
        elif op == "ACHIEVEMENT_CREATE_STATUS":
            key = payload.get("request_key")
            try:
                import uuid
                uuid.UUID(key)
            except (ValueError, TypeError, AttributeError):
                raise ProtocolError("INVALID_PAYLOAD", "invalid achievement request key", request_id) from None
            payload = {"request_key": key, "user_id": int(account["user_id"])}
        elif op == "ACHIEVEMENT_COMMENT_CREATE":
            payload = achievements.validate_comment({**payload, "user_id": int(account["user_id"])})
        elif op == "ACHIEVEMENT_POST_DELETE":
            payload = achievements.validate_owned_delete({**payload, "user_id": int(account["user_id"])})
        else:
            payload = achievements.validate_owned_delete({**payload, "user_id": int(account["user_id"])}, comment=True)
    connection = repository.connect()
    try:
        view = getattr(repository, "request_view", None)
        if view is not None:
            repository = view(connection, op)
        version = repository.dataset_version(connection)
        if op == "ACHIEVEMENT_LIST" or op == "ADMIN_ACHIEVEMENT_LIST":
            from source.server.achievements import validate_list
            query, limit, offset = validate_list(payload)
            if op.startswith("ADMIN_") and not getattr(repository, "unified_catalog_mode", False):
                raise ProtocolError("UNSUPPORTED_OPERATION", "achievements are available only in unified schema v3", request_id)
            data = repository.achievement_list(connection, query, limit, offset, admin=op.startswith("ADMIN_"))
            return success_response(request_id, {"dataset_version": version, **data}), op
        if op in {"ACHIEVEMENT_GET", "ADMIN_ACHIEVEMENT_GET"}:
            admin = op.startswith("ADMIN_")
            post_id = payload.get("post_id")
            if set(payload) != {"post_id"} or type(post_id) is not int or not 1 <= post_id < 2**64:
                raise ProtocolError("INVALID_PAYLOAD", "invalid achievement ID", request_id)
            result = repository.achievement_get(connection, post_id, admin=admin)
            if result is None:
                raise ProtocolError("NOT_FOUND", "achievement not found", request_id)
            return success_response(request_id, {"dataset_version": version, **result}), op
        if op == "ACHIEVEMENT_CREATE_STATUS":
            key = payload.get("request_key")
            if set(payload) != {"request_key", "user_id"} or not isinstance(key, str) or type(payload.get("user_id")) is not int:
                raise ProtocolError("INVALID_PAYLOAD", "invalid achievement request status query", request_id)
            result = repository.achievement_create_result(connection, payload["user_id"], key)
            return success_response(request_id, {"dataset_version": version, "achievement": result}), op
        if op == "ACHIEVEMENT_IMAGE_GET":
            key = payload.get("storage_key")
            if set(payload) != {"storage_key"} or not isinstance(key, str) or len(key) > 100:
                raise ProtocolError("INVALID_PAYLOAD", "invalid achievement image key", request_id)
            result = repository.achievement_image(connection, key)
            if result is None:
                raise ProtocolError("NOT_FOUND", "achievement image not found", request_id)
            return success_response(request_id, result), op
        if op == "ADMIN_ACHIEVEMENT_IMAGE_GET":
            key = payload.get("storage_key")
            if set(payload) != {"storage_key"} or not isinstance(key, str) or len(key) > 100:
                raise ProtocolError("INVALID_PAYLOAD", "invalid achievement image key", request_id)
            result = repository.achievement_image(connection, key, admin=True)
            if result is None:
                raise ProtocolError("NOT_FOUND", "achievement image not found", request_id)
            return success_response(request_id, result), op
        if op == "ACHIEVEMENT_CREATE":
            try:
                result = repository.achievement_create(payload)
            except ValueError as exc:
                message = str(exc)
                code = "NOT_FOUND" if "unavailable" in message else "ACHIEVEMENT_CONFLICT"
                raise ProtocolError(code, message, request_id)
            return success_response(request_id, {"dataset_version": version, **result}), op
        if op == "ACHIEVEMENT_COMMENT_CREATE":
            try:
                result = repository.achievement_comment_create(payload)
            except ValueError as exc:
                raise ProtocolError("NOT_FOUND", str(exc), request_id)
            return success_response(request_id, {"dataset_version": version, **result}), op
        if op in {"ACHIEVEMENT_POST_DELETE", "ADMIN_ACHIEVEMENT_POST_DELETE"}:
            admin = op.startswith("ADMIN_")
            allowed = {"post_id"} if admin else {"post_id", "user_id"}
            if set(payload) != allowed or type(payload.get("post_id")) is not int or not 1 <= payload["post_id"] < 2**64:
                raise ProtocolError("INVALID_PAYLOAD", "invalid achievement delete request", request_id)
            try:
                result = repository.achievement_delete_post(payload["post_id"], user_id=None if admin else payload["user_id"])
            except LookupError as exc:
                raise ProtocolError("NOT_FOUND", str(exc), request_id)
            except PermissionError as exc:
                raise ProtocolError("FORBIDDEN", str(exc), request_id)
            return success_response(request_id, {"dataset_version": version, **result}), op
        if op in {"ACHIEVEMENT_COMMENT_DELETE", "ADMIN_ACHIEVEMENT_COMMENT_DELETE"}:
            admin = op.startswith("ADMIN_")
            allowed = {"comment_id"} if admin else {"comment_id", "user_id"}
            if set(payload) != allowed or type(payload.get("comment_id")) is not int or not 1 <= payload["comment_id"] < 2**64:
                raise ProtocolError("INVALID_PAYLOAD", "invalid comment delete request", request_id)
            try:
                result = repository.achievement_delete_comment(payload["comment_id"], user_id=None if admin else payload["user_id"])
            except LookupError as exc:
                raise ProtocolError("NOT_FOUND", str(exc), request_id)
            except PermissionError as exc:
                raise ProtocolError("FORBIDDEN", str(exc), request_id)
            return success_response(request_id, {"dataset_version": version, **result}), op
        if op == "ADMIN_DASHBOARD":
            if payload:
                raise ProtocolError("INVALID_PAYLOAD", "invalid administrator dashboard request", request_id)
            return success_response(request_id, {"dataset_version":version, **repository.admin_dashboard(connection)}), op
        if op == "ADMIN_LIST_RECIPES":
            query=payload.get("query","")
            limit=payload.get("limit",20)
            offset=payload.get("offset",0)
            role=payload.get("role")
            visibility=payload.get("visibility")
            max_minutes=payload.get("max_minutes")
            if (set(payload)-{"query","limit","offset","role","visibility","max_minutes"} or not isinstance(query,str) or len(query)>80
                    or type(limit) is not int or not 1<=limit<=50 or type(offset) is not int or not 0<=offset<=10000):
                raise ProtocolError("INVALID_PAYLOAD", "invalid administrator recipe query", request_id)
            unified = bool(getattr(repository, "unified_catalog_mode", False))
            allowed_roles = {"main","vegetable","soup","side","drink","starch","other"} if unified else {"main","vegetable","soup"}
            max_allowed = 1440 if unified else 240
            if (role is not None and role not in allowed_roles
                    or visibility is not None and visibility not in {"visible","hidden","deleted"}
                    or max_minutes is not None and (type(max_minutes) is not int or not 1<=max_minutes<=max_allowed)):
                raise ProtocolError("INVALID_PAYLOAD", "invalid administrator recipe filters", request_id)
            return success_response(request_id, {"dataset_version":version, **repository.admin_list_recipes(
                connection,query,limit,offset,role=role,visibility=visibility,max_minutes=max_minutes)}), op
        if op == "ADMIN_GET_RECIPE":
            revision_id=payload.get("revision_id")
            if set(payload)!={"revision_id"} or type(revision_id) is not int or not 1<=revision_id<2**64:
                raise ProtocolError("INVALID_PAYLOAD", "invalid administrator revision ID", request_id)
            result=repository.admin_get_recipe(connection,revision_id)
            if result is None:
                raise ProtocolError("NOT_FOUND", "revision not found", request_id)
            return success_response(request_id, {"dataset_version":version, **result}), op
        if op=="ADMIN_GET_LEGACY_RECIPE":
            recipe_id=payload.get("recipe_id")
            if set(payload)!={"recipe_id"} or type(recipe_id) is not int or not 1<=recipe_id<2**32:
                raise ProtocolError("INVALID_PAYLOAD","invalid legacy recipe ID",request_id)
            result=repository.admin_get_legacy_recipe(connection,recipe_id)
            if result is None:raise ProtocolError("NOT_FOUND","legacy recipe not found",request_id)
            return success_response(request_id,{"dataset_version":version,**result}),op
        if op == "ADMIN_LIST_INGREDIENTS":
            from source.server.admin_ingredients import validate_list
            normalized=validate_list(payload,request_id)
            if getattr(repository, "unified_catalog_mode", False):
                return success_response(request_id, {"dataset_version":version,
                    **repository.admin_list_ingredients(connection, **normalized)}), op
            status=normalized.pop("status")
            if status != "all":
                raise ProtocolError("UNSUPPORTED_OPERATION", "ingredient status filtering is available in the unified catalog", request_id)
            return success_response(request_id,{"dataset_version":version,
                **repository.admin_list_ingredients(connection,**normalized)}),op
        if op == "ADMIN_LIST_UNITS":
            if payload or not getattr(repository, "unified_catalog_mode", False):
                raise ProtocolError("UNSUPPORTED_OPERATION", "unit catalog is available only in the unified recipe editor", request_id)
            return success_response(request_id,{"dataset_version":version,
                "items":repository.admin_list_units(connection)}),op
        if op == "ADMIN_LIST_USERS":
            from source.server.user_accounts import validate_admin_list
            options=validate_admin_list(payload,request_id)
            return success_response(request_id,{"dataset_version":version,
                **repository.admin_list_users(connection,**options)}),op
        if op == "ADMIN_SET_USER_STATUS":
            from source.server.user_accounts import validate_admin_status
            from source.server.repository import UserAccountConflict,UserAccountUnavailable
            try:
                result=repository.admin_set_user_status(validate_admin_status(payload,request_id))
            except ProtocolError:
                raise
            except UserAccountConflict as exc:
                raise ProtocolError("USER_ACCOUNT_CONFLICT",str(exc),request_id)
            except UserAccountUnavailable:
                raise ProtocolError("USER_ACCOUNT_UNAVAILABLE","user account migration or writer is unavailable",request_id)
            return success_response(request_id,{"dataset_version":version,**result}),op
        if op == "ADMIN_SET_USER_ROLE":
            from source.server.user_accounts import validate_admin_role
            from source.server.repository import UserAccountConflict,UserAccountUnavailable
            try:
                result=repository.admin_set_user_role(validate_admin_role(payload,request_id))
            except ProtocolError:
                raise
            except UserAccountConflict as exc:
                raise ProtocolError("USER_ACCOUNT_CONFLICT",str(exc),request_id)
            except UserAccountUnavailable:
                raise ProtocolError("USER_ACCOUNT_UNAVAILABLE","user account migration or writer is unavailable",request_id)
            return success_response(request_id,{"dataset_version":version,**result}),op
        if op in {"ADMIN_CREATE_INGREDIENT","ADMIN_UPDATE_INGREDIENT","ADMIN_SET_INGREDIENT_ACTIVE"}:
            from source.server import admin_ingredients
            from source.server.repository import AdminIngredientConflict,AdminWriteUnavailable
            import mysql.connector
            try:
                if op=="ADMIN_CREATE_INGREDIENT":
                    normalized=admin_ingredients.validate_create(payload,request_id)
                    result=repository.admin_create_ingredient(normalized)
                elif op=="ADMIN_UPDATE_INGREDIENT":
                    normalized=admin_ingredients.validate_update(payload,request_id)
                    result=repository.admin_update_ingredient(normalized)
                else:
                    normalized=admin_ingredients.validate_active(payload,request_id)
                    result=repository.admin_set_ingredient_active(normalized)
            except ProtocolError:
                raise
            except AdminIngredientConflict as exc:
                raise ProtocolError("ADMIN_INGREDIENT_CONFLICT",str(exc),request_id)
            except AdminWriteUnavailable:
                raise ProtocolError("ADMIN_WRITE_UNAVAILABLE","ingredient Admin migration or writer grants are unavailable",request_id)
            except mysql.connector.Error as exc:
                if exc.errno in (1062,1451,1452):
                    raise ProtocolError("ADMIN_INGREDIENT_CONFLICT","ingredient conflicts with existing catalog data",request_id)
                if exc.errno in (1142,1146,1227):
                    raise ProtocolError("ADMIN_WRITE_DENIED","ingredient writer lacks the required v2-only privileges",request_id)
                raise
            return success_response(request_id,{"dataset_version":version,**result}),op
        if op in {"ADMIN_UPDATE_LEGACY_INGREDIENT","ADMIN_SET_LEGACY_INGREDIENT_ACTIVE"}:
            from source.server import admin_ingredients
            from source.server.repository import AdminIngredientConflict,AdminWriteUnavailable
            import mysql.connector
            try:
                if op=="ADMIN_UPDATE_LEGACY_INGREDIENT":
                    normalized=admin_ingredients.validate_legacy_update(payload,request_id)
                    result=repository.admin_update_legacy_ingredient(normalized,claims["sub"])
                else:
                    normalized=admin_ingredients.validate_legacy_active(payload,request_id)
                    result=repository.admin_set_legacy_ingredient_active(normalized,claims["sub"])
            except ProtocolError:raise
            except AdminIngredientConflict as exc:raise ProtocolError("ADMIN_INGREDIENT_CONFLICT",str(exc),request_id)
            except AdminWriteUnavailable:
                raise ProtocolError("ADMIN_WRITE_UNAVAILABLE","legacy ingredient overlay migration or writer grants are unavailable",request_id)
            except mysql.connector.Error as exc:
                if exc.errno in (1062,1451,1452):raise ProtocolError("ADMIN_INGREDIENT_CONFLICT","legacy ingredient conflicts with the current catalog",request_id)
                if exc.errno in (1142,1146,1227):raise ProtocolError("ADMIN_WRITE_DENIED","Admin writer lacks legacy ingredient overlay privileges",request_id)
                raise
            return success_response(request_id,{"dataset_version":version,**result}),op
        if op == "ADMIN_DELETE_RECIPE_PERMANENT":
            if set(payload) != {"recipe_id"} or not valid_public_id(payload.get("recipe_id")):
                raise ProtocolError("INVALID_PAYLOAD", "invalid recipe ID", request_id)
            if not getattr(repository, "unified_catalog_mode", False):
                raise ProtocolError("UNSUPPORTED_OPERATION", "permanent deletion is available only in the unified catalog", request_id)
            from source.server.repository import AdminDraftConflict
            import mysql.connector
            try:
                result = repository.admin_permanently_delete_recipe(payload["recipe_id"])
            except AdminDraftConflict as exc:
                raise ProtocolError("ADMIN_RECIPE_DELETE_BLOCKED", str(exc), request_id)
            except mysql.connector.Error as exc:
                if exc.errno in (1451, 1452):
                    raise ProtocolError("ADMIN_RECIPE_DELETE_BLOCKED", "recipe still has protected references", request_id)
                if exc.errno in (1044, 1045, 1142, 1227):
                    raise ProtocolError("ADMIN_WRITE_DENIED", "Admin writer lacks permanent recipe deletion privileges", request_id)
                raise
            return success_response(request_id, {"dataset_version":version, **result}), op
        if op == "ADMIN_DELETE_INGREDIENT_PERMANENT":
            ingredient_id = payload.get("ingredient_id")
            if set(payload) != {"ingredient_id"} or type(ingredient_id) is not int or not 1 <= ingredient_id < 2**64:
                raise ProtocolError("INVALID_PAYLOAD", "invalid ingredient ID", request_id)
            if not getattr(repository, "unified_catalog_mode", False):
                raise ProtocolError("UNSUPPORTED_OPERATION", "permanent deletion is available only in the unified catalog", request_id)
            from source.server.repository import AdminIngredientConflict
            import mysql.connector
            try:
                result = repository.admin_permanently_delete_ingredient(ingredient_id)
            except AdminIngredientConflict as exc:
                raise ProtocolError("ADMIN_INGREDIENT_DELETE_BLOCKED", str(exc), request_id)
            except mysql.connector.Error as exc:
                if exc.errno in (1451, 1452):
                    raise ProtocolError("ADMIN_INGREDIENT_DELETE_BLOCKED", "ingredient still has protected references", request_id)
                if exc.errno in (1044, 1045, 1142, 1227):
                    raise ProtocolError("ADMIN_WRITE_DENIED", "Admin writer lacks permanent ingredient deletion privileges", request_id)
                raise
            return success_response(request_id, {"dataset_version":version, **result}), op
        if op in {"ADMIN_SAVE_RECIPE","ADMIN_SET_RECIPE_LIFECYCLE"}:
            from source.server import admin_recipes
            from source.server.repository import AdminDraftConflict,AdminSchemaUnavailable,AdminWriteUnavailable
            try:
                if op=="ADMIN_SAVE_RECIPE":
                    normalized=admin_recipes.validate_save(payload,request_id,update="recipe_id" in payload,
                        allow_repeated=bool(getattr(repository,"supports_repeated_recipe_ingredients",False)),
                        unified=bool(getattr(repository,"unified_catalog_mode",False)))
                    result=repository.admin_save_recipe(normalized,claims["sub"])
                else:
                    normalized=admin_recipes.validate_state(payload,request_id)
                    result=repository.admin_set_recipe_lifecycle(normalized,claims["sub"])
            except ProtocolError:raise
            except AdminWriteUnavailable:
                raise ProtocolError("ADMIN_WRITE_UNAVAILABLE","dedicated Admin writer is not configured",request_id)
            except AdminSchemaUnavailable:
                raise ProtocolError("ADMIN_SCHEMA_UNAVAILABLE","Admin catalog migration 009 or its grants are unavailable",request_id)
            except AdminDraftConflict as exc:
                error = ProtocolError("ADMIN_RECIPE_CONFLICT",str(exc),request_id)
                error.mysql_errno = getattr(exc,"mysql_errno",None)
                error.diagnostic_code = getattr(exc,"reason","recipe_conflict")
                raise error
            except ValueError:
                raise ProtocolError("INVALID_PAYLOAD","one or more ingredient IDs are not active in the shared catalog",request_id)
            except Exception as exc:
                import mysql.connector
                if isinstance(exc,mysql.connector.Error):
                    mapped=admin_recipes.mysql_save_error(exc,request_id)
                    if mapped is not None:
                        mapped.mysql_errno=getattr(exc,"errno",None)
                        mapped.diagnostic_code=f"mysql_{getattr(exc,'errno',0)}"
                        raise mapped from None
                raise
            return success_response(request_id,{"dataset_version":version,**result}),op
        if op in {"ADMIN_CREATE_DRAFT","ADMIN_UPDATE_DRAFT"}:
            from source.server.admin_drafts import validate_draft_fields
            from source.server.repository import AdminDraftConflict,AdminSchemaUnavailable,AdminWriteUnavailable
            try:
                normalized=validate_draft_fields(payload,request_id,update=op=="ADMIN_UPDATE_DRAFT")
                if op=="ADMIN_CREATE_DRAFT":
                    result=repository.admin_create_draft(normalized,claims["sub"])
                else:
                    result=repository.admin_update_draft(normalized)
            except ProtocolError:
                raise
            except AdminWriteUnavailable:
                raise ProtocolError("ADMIN_WRITE_UNAVAILABLE","dedicated Admin writer is not configured",request_id)
            except AdminSchemaUnavailable:
                raise ProtocolError("ADMIN_SCHEMA_UNAVAILABLE","draft description schema is not installed",request_id)
            except AdminDraftConflict:
                raise ProtocolError("ADMIN_DRAFT_CONFLICT","revision is no longer an editable draft",request_id)
            except ValueError:
                raise ProtocolError("INVALID_PAYLOAD","one or more ingredient IDs are not active in the shared catalog",request_id)
            except Exception as exc:
                import mysql.connector
                if isinstance(exc,mysql.connector.Error):
                    if exc.errno in (1044,1045,1142,1227):
                        raise ProtocolError("ADMIN_WRITE_DENIED","Admin writer lacks the required v2-only privileges",request_id)
                    if exc.errno==1062:
                        raise ProtocolError("ADMIN_DRAFT_CONFLICT","draft ID already exists; retry the operation",request_id)
                raise
            return success_response(request_id,{"dataset_version":version,**result}),op
        if op in {"ADMIN_GET_RECIPE_IMAGE","ADMIN_SET_RECIPE_IMAGE","ADMIN_REMOVE_RECIPE_IMAGE"}:
            import re
            from source.server.repository import (AdminDraftConflict, AdminRecipeImageSchemaUnavailable,
                AdminRecipeImageUnavailable, AdminWriteUnavailable)
            if op == "ADMIN_GET_RECIPE_IMAGE":
                recipe_id = payload.get("recipe_id")
                if set(payload) != {"recipe_id"} or not valid_public_id(recipe_id):
                    raise ProtocolError("INVALID_PAYLOAD", "invalid recipe image identity", request_id)
                result = repository.admin_get_recipe_image(connection, recipe_id)
            elif op == "ADMIN_REMOVE_RECIPE_IMAGE":
                recipe_id = payload.get("recipe_id")
                if set(payload) != {"recipe_id"} or not valid_public_id(recipe_id):
                    raise ProtocolError("INVALID_PAYLOAD", "invalid recipe image identity", request_id)
                try:
                    result = repository.admin_remove_recipe_image(recipe_id)
                except AdminWriteUnavailable:
                    raise ProtocolError("ADMIN_WRITE_UNAVAILABLE", "dedicated Admin writer is not configured", request_id)
                except AdminRecipeImageUnavailable:
                    raise ProtocolError("ADMIN_WRITE_DENIED", "recipe image migration or grants are unavailable", request_id)
                except AdminRecipeImageSchemaUnavailable:
                    raise ProtocolError("ADMIN_SCHEMA_UNAVAILABLE", "recipe image migration 007 is required", request_id)
                except AdminDraftConflict:
                    raise ProtocolError("NOT_FOUND", "recipe does not exist", request_id)
                except Exception as exc:
                    import mysql.connector
                    if isinstance(exc, mysql.connector.Error) and exc.errno in (1044,1045,1142,1227):
                        raise ProtocolError("ADMIN_WRITE_DENIED", "Admin writer lacks recipe image table privileges", request_id)
                    raise
            else:
                expected = {"recipe_id","storage_key","media_type","byte_size","width","height","sha256"}
                image = payload
                if (set(image) != expected or not valid_public_id(image.get("recipe_id"))
                        or not isinstance(image.get("storage_key"), str)
                        or not re.fullmatch(r"[a-f0-9]{32}\.(?:jpg|png|webp)", image["storage_key"])
                        or image.get("media_type") not in {"image/jpeg","image/png","image/webp"}
                        or image["storage_key"].rsplit(".",1)[-1] != {"image/jpeg":"jpg","image/png":"png","image/webp":"webp"}.get(image.get("media_type"))
                        or type(image.get("byte_size")) is not int or not 1 <= image["byte_size"] <= 5 * 1024 * 1024
                        or type(image.get("width")) is not int or not 1 <= image["width"] <= 8000
                        or type(image.get("height")) is not int or not 1 <= image["height"] <= 8000
                        or image["width"] * image["height"] > 20_000_000
                        or not isinstance(image.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", image["sha256"])):
                    raise ProtocolError("INVALID_PAYLOAD", "invalid recipe image metadata", request_id)
                try:
                    result = repository.admin_set_recipe_image(connection, image, claims["sub"])
                except AdminWriteUnavailable:
                    raise ProtocolError("ADMIN_WRITE_UNAVAILABLE", "dedicated Admin writer is not configured", request_id)
                except AdminRecipeImageUnavailable:
                    raise ProtocolError("ADMIN_WRITE_DENIED", "recipe image migration or grants are unavailable", request_id)
                except AdminRecipeImageSchemaUnavailable:
                    raise ProtocolError("ADMIN_SCHEMA_UNAVAILABLE", "recipe image migration 007 is required", request_id)
                except AdminDraftConflict:
                    raise ProtocolError("NOT_FOUND", "recipe does not exist", request_id)
                except Exception as exc:
                    import mysql.connector
                    if isinstance(exc, mysql.connector.Error) and exc.errno in (1044,1045,1142,1227):
                        raise ProtocolError("ADMIN_WRITE_DENIED", "Admin writer lacks recipe image table privileges", request_id)
                    if isinstance(exc, mysql.connector.Error) and exc.errno == 1062:
                        raise ProtocolError("ADMIN_IMAGE_CONFLICT", "recipe image metadata conflicts with another image", request_id)
                    raise
            return success_response(request_id, {"dataset_version": version, **result}), op
        if op in {"ADMIN_UPDATE_LEGACY_RECIPE","ADMIN_SET_LEGACY_RECIPE_VISIBILITY","ADMIN_RESTORE_RECIPE_SNAPSHOT"}:
            from source.server import legacy_recipe_overlays
            from source.server.repository import AdminDraftConflict,AdminSchemaUnavailable,AdminWriteUnavailable
            try:
                if op=="ADMIN_RESTORE_RECIPE_SNAPSHOT":
                    from source.server.admin_recipe_snapshots import validate_restore
                    normalized=validate_restore(payload,request_id)
                    if normalized["kind"]=="legacy":
                        result=repository.admin_restore_legacy_recipe_snapshot(normalized,claims["sub"])
                    else:
                        result=repository.admin_restore_v2_recipe_snapshot(normalized,claims["sub"])
                else:
                    normalized=(legacy_recipe_overlays.validate_update(payload,request_id)
                        if op=="ADMIN_UPDATE_LEGACY_RECIPE" else legacy_recipe_overlays.validate_visibility(payload,request_id))
                    result=(repository.admin_update_legacy_recipe(normalized,claims["sub"])
                        if op=="ADMIN_UPDATE_LEGACY_RECIPE" else repository.admin_set_legacy_recipe_visibility(normalized,claims["sub"]))
            except ProtocolError:raise
            except AdminWriteUnavailable:
                raise ProtocolError("ADMIN_WRITE_UNAVAILABLE","dedicated Admin writer is not configured",request_id)
            except AdminSchemaUnavailable:
                raise ProtocolError("ADMIN_SCHEMA_UNAVAILABLE","recipe snapshot restore schema and grants are required",request_id)
            except AdminDraftConflict as exc:
                raise ProtocolError("ADMIN_RECIPE_CONFLICT",str(exc),request_id)
            except ValueError:
                raise ProtocolError("INVALID_PAYLOAD","legacy recipe or ingredient ID is invalid",request_id)
            except mysql.connector.Error as exc:
                if exc.errno in (1044,1045,1142,1227):
                    raise ProtocolError("ADMIN_WRITE_DENIED","Admin writer or runtime reader lacks legacy overlay privileges",request_id)
                if exc.errno in (1062,1452,3819):
                    raise ProtocolError("ADMIN_LEGACY_RECIPE_CONFLICT","legacy overlay conflicts with the current catalog",request_id)
                raise
            return success_response(request_id,{"dataset_version":version,**result}),op
        review_ops={"ADMIN_SUBMIT_REVIEW","ADMIN_REVIEW_SOURCE","ADMIN_APPROVE_RECIPE",
                    "ADMIN_REJECT_RECIPE","ADMIN_PUBLISH_RELEASE","ADMIN_UNPUBLISH_RECIPE"}
        if op in review_ops:
            from source.server import admin_review
            from source.server.repository import AdminReviewBlocked,AdminReviewConflict,AdminWriteUnavailable
            try:
                if op=="ADMIN_SUBMIT_REVIEW":
                    normalized=admin_review.validate_submission(payload)
                    result=repository.admin_submit_review(normalized,claims["sub"])
                elif op=="ADMIN_REVIEW_SOURCE":
                    normalized=admin_review.validate_source_decision(payload)
                    result=repository.admin_review_source(normalized,claims["sub"])
                elif op=="ADMIN_APPROVE_RECIPE":
                    normalized=admin_review.validate_revision_action(payload)
                    result=repository.admin_approve_recipe(normalized,claims["sub"])
                elif op=="ADMIN_REJECT_RECIPE":
                    normalized=admin_review.validate_revision_action(payload)
                    result=repository.admin_reject_recipe(normalized,claims["sub"])
                elif op=="ADMIN_PUBLISH_RELEASE":
                    normalized=admin_review.validate_revision_action(payload,release=True)
                    result=repository.admin_publish_release(normalized,claims["sub"])
                else:
                    normalized=admin_review.validate_revision_action(payload,unpublish=True)
                    result=repository.admin_unpublish_recipe(normalized,claims["sub"])
            except (AdminReviewBlocked,AdminReviewConflict) as exc:
                raise ProtocolError("ADMIN_REVIEW_BLOCKED" if isinstance(exc,AdminReviewBlocked) else "ADMIN_REVIEW_CONFLICT",
                                    str(exc),request_id)
            except AdminWriteUnavailable:
                raise ProtocolError("ADMIN_WRITE_UNAVAILABLE","dedicated Admin writer is not configured",request_id)
            except ValueError:
                raise ProtocolError("INVALID_PAYLOAD","invalid Admin review fields",request_id)
            except Exception as exc:
                import mysql.connector
                if isinstance(exc,mysql.connector.Error):
                    if exc.errno in (1044,1045,1142,1227):
                        raise ProtocolError("ADMIN_WRITE_DENIED","Admin review writer lacks the required v2 privileges",request_id)
                    if exc.errno in (1062,1452,3819):
                        raise ProtocolError("ADMIN_REVIEW_CONFLICT","review data conflicts with the current v2 schema state",request_id)
                raise
            return success_response(request_id,{"dataset_version":version,**result}),op
        if op == "PING":
            if payload:
                raise ProtocolError("INVALID_PAYLOAD", "PING payload must be empty", request_id)
            return success_response(request_id, {"status": "ok", "dataset_version": version}), op
        if op == "LIST_INGREDIENTS":
            unknown = set(payload) - {"query", "limit"}
            query = payload.get("query", "")
            limit = payload.get("limit", 20)
            if unknown or not isinstance(query, str) or len(query.strip()) > 80 or not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 250:
                raise ProtocolError("INVALID_PAYLOAD", "invalid LIST_INGREDIENTS payload", request_id)
            return success_response(request_id, {"items": repository.list_ingredients(connection, query, limit), "dataset_version": version}), op
        if op == "GET_RECIPE":
            if set(payload) != {"recipe_id"} or not valid_public_id(payload.get("recipe_id")):
                raise ProtocolError("INVALID_PAYLOAD", "invalid recipe_id", request_id)
            recipe = repository.get_recipe(connection, payload["recipe_id"])
            if recipe is None:
                raise ProtocolError("NOT_FOUND", "recipe not found", request_id)
            recipe["dataset_version"] = version
            return success_response(request_id, recipe), op
        if op == "GET_RECIPE_IMAGE":
            if set(payload) != {"recipe_id"} or not valid_public_id(payload.get("recipe_id")):
                raise ProtocolError("INVALID_PAYLOAD", "invalid recipe_id", request_id)
            image = repository.public_recipe_image(connection, payload["recipe_id"])
            if image is None:
                raise ProtocolError("NOT_FOUND", "recipe image not found", request_id)
            return success_response(request_id, {"dataset_version": version, "image": image}), op
        if op == "SEARCH_RECIPES":
            options = validate_search(payload, request_id)
            if not repository.ingredient_ids_exist(connection, options.selected | options.excluded):
                raise ProtocolError("INVALID_PAYLOAD", "ingredient ids are invalid", request_id)
            data = search_recipes(repository.recipes_for_search(connection), options)
            return success_response(request_id, {"dataset_version": version, **data}), op
        if op == "CALCULATE_MEAL_PLAN":
            options = meal_plan_calculation.validate(payload, request_id)
            if not repository.recipe_ids_exist(connection, options.recipe_ids):
                raise ProtocolError("NOT_FOUND", "one or more recipes do not exist", request_id)
            catalog = repository.calculation_catalog(connection, options.recipe_ids)
            data = meal_plan_calculation.calculate(options, catalog)
            response = success_response(request_id, {"dataset_version": version, **data})
            try:
                encode_frame(response)
            except ProtocolError as exc:
                if exc.code != "FRAME_LENGTH":
                    raise
                data = meal_plan_calculation.unavailable(options, "RESULT_TOO_LARGE")
                response = success_response(request_id, {"dataset_version": version, **data})
            return response, op
        if op == "GET_MEAL_PLAN_FILTERS":
            if set(payload)-{"layout_support"} or type(payload.get("layout_support",False)) is not bool:
                raise ProtocolError("INVALID_PAYLOAD", "filter catalog payload must be empty", request_id)
            recipes = repository.recipes_for_ranking(connection)
            classification = default_classification()
            if hasattr(repository, "meal_classification_for_connection"):
                classification = repository.meal_classification_for_connection(connection, classification)
            elif hasattr(repository, "meal_classification"):
                classification = repository.meal_classification(classification)
            catalog = repository.meal_preference_catalog(connection, recipes, classification)
            return success_response(request_id, {"dataset_version": version, **catalog.capabilities(layout_support=payload.get("layout_support",False))}), op
        if op == "GENERATE_MEAL_PLAN_V2":
            options = meal_plan_v2.validate(payload, request_id)
            if not repository.ingredient_ids_exist(connection, options.filters.selected | options.filters.excluded):
                raise ProtocolError("INVALID_PAYLOAD", "ingredient ids are invalid", request_id)
            recipes = repository.recipes_for_ranking(connection)
            classification = default_classification()
            if hasattr(repository, "meal_classification_for_connection"):
                classification = repository.meal_classification_for_connection(connection, classification)
            elif hasattr(repository, "meal_classification"):
                classification = repository.meal_classification(classification)
            catalog = repository.meal_preference_catalog(connection, recipes, classification) if options.preferences else None
            data = meal_plan_v2.generate(recipes, options, classification, request_id, catalog)
            if data["plan"] is not None:
                details = [repository.get_recipe(connection, item["recipe_id"]) for item in data["plan"]["items"]]
                if any(r is None for r in details):
                    raise ProtocolError("NOT_FOUND", "meal plan recipe no longer exists", request_id)
                data["plan"].update(build_shopping_lists(details, options.filters.selected))
            response = success_response(request_id, {"dataset_version": version, **data})
            try:
                encode_frame(response)
            except ProtocolError as exc:
                if exc.code != "FRAME_LENGTH":
                    raise
                data = meal_plan_v2.no_plan(data, "RESULT_TOO_LARGE", "Mâm vượt giới hạn dữ liệu trả về.",
                                           suggestions=["Giảm số người rồi thử lại." if options.people is not None else "Giảm số món rồi thử lại."])
                response = success_response(request_id, {"dataset_version": version, **data})
            return response, op
        if op == "GENERATE_MEAL_PLAN":
            options = validate_meal_plan(payload, request_id)
            if not repository.ingredient_ids_exist(connection, options.selected | options.excluded):
                raise ProtocolError("INVALID_PAYLOAD", "ingredient ids are invalid", request_id)
            classification = default_classification()
            if hasattr(repository, "meal_classification_for_connection"):
                classification = repository.meal_classification_for_connection(connection, classification)
            elif hasattr(repository, "meal_classification"):
                classification = repository.meal_classification(classification)
            data = generate_meal_plan(repository.recipes_for_ranking(connection), options,
                                      classification, request_id)
            if data["plan"] is not None:
                details = []
                for item in data["plan"]["items"]:
                    recipe = repository.get_recipe(connection, item["recipe_id"])
                    if recipe is None:
                        raise ProtocolError("NOT_FOUND", "meal plan recipe no longer exists", request_id)
                    details.append(recipe)
                data["plan"].update(build_shopping_lists(details, options.selected))
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
