from __future__ import annotations

import os
import json
import base64
import binascii
import hmac
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Path as FastAPIPath, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, ValidationError, field_validator
from dotenv import load_dotenv

from source.client.tcp_client import TCPClient, TCPClientError
from source.common.protocol import error_response
from source.common.catalog_ids import valid_public_id
from source.web.meal_plan_contract import MealPlanData, MealPlanRequest
from source.web.meal_plan_v2_contract import Data as MealPlanV2Data, Request as MealPlanV2Request, FilterCatalog
from source.web.meal_plan_calculation_contract import CalculationData, CalculationRequest
from source.web import admin_auth
from source.common.admin_tokens import issue as issue_admin_token, verify as verify_admin_token

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parents[1] / ".env")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="Hôm nay ăn gì?", version="1.2.0")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
_GATEWAY_LOG_PATH = Path(os.getenv("FASTAPI_GATEWAY_LOG_PATH", BASE_DIR.parents[1] / "statics/runtime/fastapi_gateway.jsonl"))
_GATEWAY_LOG_LOCK = threading.Lock()


def _unified_schema_mode() -> bool:
    return os.getenv("UNIFIED_SCHEMA_MODE") == "1"


def _gateway_log(**fields: Any) -> None:
    """Append correlation/timing metadata; never log request bodies or credentials."""
    record = {"timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **fields}
    try:
        with _GATEWAY_LOG_LOCK:
            _GATEWAY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with _GATEWAY_LOG_PATH.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        return


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ingredient_ids: list[StrictInt] = Field(min_length=1, max_length=30)
    excluded_ids: list[StrictInt] = Field(default_factory=list, max_length=30)
    max_minutes: StrictInt | None = Field(default=None, ge=1, le=240)
    top_k: StrictInt = Field(default=5, ge=1, le=20)
    algorithm: Literal["baseline", "proposed"] = "proposed"


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: StrictStr = Field(default="", max_length=80)
    ingredient_ids: list[StrictInt] = Field(default_factory=list, max_length=30)
    excluded_ids: list[StrictInt] = Field(default_factory=list, max_length=30)
    max_minutes: StrictInt | None = Field(default=None, ge=1, le=240)
    max_missing: StrictInt | None = Field(default=None, ge=0, le=50)
    limit: StrictInt = Field(default=12, ge=1, le=20)
    offset: StrictInt = Field(default=0, ge=0)


class AdminLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: StrictStr = Field(min_length=1,max_length=100)
    password: StrictStr = Field(min_length=1,max_length=256)


class UserRegisterRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    username:StrictStr=Field(min_length=3,max_length=32)
    password:StrictStr=Field(min_length=12,max_length=256)
    password_confirmation:StrictStr=Field(min_length=12,max_length=256)


class UserLoginRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    username:StrictStr=Field(min_length=3,max_length=32)
    password:StrictStr=Field(min_length=1,max_length=256)


class AchievementCommentRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    body:StrictStr=Field(min_length=1,max_length=2000)


class AdminUserStatusRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    account_status:Literal["ACTIVE","LOCKED"]


class AdminUserRoleRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    role:Literal["USER","ADMIN"]


class AdminIngredientLine(BaseModel):
    model_config=ConfigDict(extra="forbid")
    ingredient_id:StrictInt=Field(gt=0,lt=2**64)
    quantity_raw:StrictStr|None=Field(default=None,max_length=255)
    requirement:Literal["required","optional"]="required"
    amount_kind:Literal["exact","range","to_taste","as_needed","unknown"]="unknown"
    amount_min:StrictStr|None=Field(default=None,max_length=32)
    amount_max:StrictStr|None=Field(default=None,max_length=32)
    unit_id:StrictInt|None=Field(default=None,ge=1,le=65535)
    ingredient_form:StrictStr|None=Field(default=None,max_length=120)
    measurement_basis:Literal["gross","edible","prepared","unknown"]="unknown"
    purpose:Literal["main","seasoning","cooking_medium","garnish","unknown"]="unknown"
    scaling_mode:Literal["linear","fixed","unknown"]="unknown"


class AdminRecipeStep(BaseModel):
    model_config=ConfigDict(extra="forbid")
    instruction:StrictStr=Field(min_length=1,max_length=5000)
    duration_minutes:StrictInt|None=Field(default=None,ge=0,le=1440)
    heat_level:StrictStr|None=Field(default=None,max_length=40)


class AdminRecipeTag(BaseModel):
    model_config=ConfigDict(extra="forbid")
    tag_type:Literal["diet","region","season","occasion"]
    code:StrictStr=Field(min_length=1,max_length=48,pattern=r"^[a-z0-9_]+$")


class AdminDraftRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    title:StrictStr=Field(min_length=1,max_length=255)
    description:StrictStr=Field(default="",max_length=1000)
    instructions:StrictStr=Field(min_length=1,max_length=12000)
    minutes:StrictInt|None=Field(default=None,ge=1,le=240)
    ingredients:list[AdminIngredientLine]=Field(min_length=1,max_length=50)


class AdminRecipeSaveRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    title:StrictStr=Field(min_length=1,max_length=255)
    description:StrictStr=Field(default="",max_length=1000)
    instructions:StrictStr=Field(min_length=1,max_length=12000)
    minutes:StrictInt=Field(ge=1,le=1440)
    role:Literal["main","vegetable","soup","side","drink","starch","other"]
    ingredients:list[AdminIngredientLine]=Field(min_length=1,max_length=50)
    servings:StrictStr|None=Field(default=None,max_length=32)
    minutes_prep:StrictInt|None=Field(default=None,ge=0,le=1440)
    minutes_cook:StrictInt|None=Field(default=None,ge=0,le=1440)
    steps:list[AdminRecipeStep]|None=Field(default=None,min_length=1,max_length=50)
    source_url:StrictStr|None=Field(default=None,max_length=1000)
    tags:list[AdminRecipeTag]|None=Field(default=None,max_length=16)
    idempotency_key:StrictStr|None=Field(default=None,min_length=36,max_length=36,pattern=r"^[0-9a-fA-F-]{36}$")
    expected_version:StrictStr|None=Field(default=None,min_length=64,max_length=64,pattern=r"^[0-9a-f]{64}$")


class AdminRecipeStateRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    is_visible:StrictBool
    is_deleted:StrictBool


class AdminLegacyIngredientLine(BaseModel):
    model_config=ConfigDict(extra="forbid")
    ingredient_id:StrictInt=Field(gt=0,lt=2**33)
    quantity:StrictStr=Field(max_length=255)
    # Kept for old clients; Admin edits now make every ingredient required.
    is_required:StrictBool=True


class AdminLegacyRecipeUpdate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    title:StrictStr=Field(min_length=1,max_length=255)
    description:StrictStr=Field(default="",max_length=1000)
    instructions:StrictStr=Field(min_length=1,max_length=12000)
    minutes:StrictInt=Field(ge=1,le=240)
    ingredients:list[AdminLegacyIngredientLine]=Field(min_length=1,max_length=100)
    is_visible:StrictBool
    expected_version:StrictStr=Field(min_length=64,max_length=64,pattern=r"^[0-9a-f]{64}$")


class AdminRecipeSnapshotCreate(BaseModel):
    model_config=ConfigDict(extra="forbid")
    kind:Literal["legacy","v2"]
    revision_id:StrictInt|None=Field(default=None,gt=0,lt=2**64)


class AdminRecipeSnapshotRestore(BaseModel):
    model_config=ConfigDict(extra="forbid")
    snapshot_id:StrictStr=Field(min_length=36,max_length=36,pattern=r"^[0-9a-fA-F-]{36}$")
    expected_version:StrictStr=Field(min_length=64,max_length=64,pattern=r"^[0-9a-f]{64}$")


class AdminLegacyVisibility(BaseModel):
    model_config=ConfigDict(extra="forbid")
    is_visible:StrictBool


class AdminReviewSubmission(BaseModel):
    model_config=ConfigDict(extra="forbid")
    revision_id:StrictInt=Field(gt=0,lt=2**64)
    source_kind:StrictStr=Field(min_length=1,max_length=40)
    source_title:StrictStr=Field(min_length=1,max_length=255)
    source_url:StrictStr=Field(min_length=8,max_length=1000)
    publisher:StrictStr=Field(default="",max_length=255)
    usage_note:StrictStr=Field(default="",max_length=2000)
    accessed_on:StrictStr=Field(min_length=10,max_length=10)
    content_locator:StrictStr=Field(min_length=1,max_length=500)
    content_evidence:StrictStr=Field(min_length=1,max_length=5000)
    publication_locator:StrictStr=Field(min_length=1,max_length=500)
    publication_evidence:StrictStr=Field(min_length=1,max_length=5000)
    role:Literal["main","vegetable","soup"]
    role_locator:StrictStr=Field(min_length=1,max_length=500)
    role_evidence:StrictStr=Field(min_length=1,max_length=5000)

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_http(cls,value):
        if not value.lower().startswith(("http://","https://")):
            raise ValueError("source URL must use HTTP or HTTPS")
        return value

    @field_validator("accessed_on")
    @classmethod
    def accessed_on_must_be_iso_date(cls,value):
        from datetime import date
        try: date.fromisoformat(value)
        except ValueError: raise ValueError("source access date must be YYYY-MM-DD") from None
        return value


class AdminSourceDecision(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source_id:StrictInt=Field(gt=0,lt=2**64)
    evidence_set_id:StrictInt=Field(gt=0,lt=2**64)
    decision:Literal["APPROVED","REJECTED"]
    rationale:StrictStr=Field(min_length=10,max_length=4000)


class AdminIngredientName(BaseModel):
    model_config=ConfigDict(extra="forbid")
    name:StrictStr=Field(min_length=2,max_length=255)
    make_available:StrictBool|None=None


class AdminIngredientActive(BaseModel):
    model_config=ConfigDict(extra="forbid")
    is_active:StrictBool


class AdminReviewAction(BaseModel):
    model_config=ConfigDict(extra="forbid")
    revision_id:StrictInt=Field(gt=0,lt=2**64)
    rationale:StrictStr=Field(min_length=10,max_length=4000)


class AdminPublishAction(BaseModel):
    model_config=ConfigDict(extra="forbid")
    release_id:StrictInt=Field(gt=0,lt=2**64)
    rationale:StrictStr=Field(min_length=10,max_length=4000)


class AdminUnpublishAction(BaseModel):
    model_config=ConfigDict(extra="forbid")
    recipe_id:StrictInt=Field(gt=0,lt=2**64)
    rationale:StrictStr=Field(min_length=10,max_length=4000)


def http_status_for_error(code: str) -> int:
    if code == "ADMIN_UNAUTHORIZED":
        return 401
    if code in {"ADMIN_CSRF", "ADMIN_WRITE_DENIED"}:
        return 403
    if code=="ADMIN_DRAFT_CONFLICT":return 409
    if code=="ADMIN_RECIPE_CONFLICT":return 409
    if code=="ADMIN_RECIPE_CONSTRAINT":return 409
    if code=="ADMIN_RECIPE_INVALID_DATA":return 422
    if code in {"ADMIN_REVIEW_BLOCKED","ADMIN_REVIEW_CONFLICT"}:return 409
    if code=="ADMIN_INGREDIENT_CONFLICT":return 409
    if code in {"ADMIN_RECIPE_DELETE_BLOCKED","ADMIN_INGREDIENT_DELETE_BLOCKED"}:return 409
    if code=="ADMIN_IMAGE_CONFLICT":return 409
    if code=="USER_ACCOUNT_CONFLICT":return 409
    if code in {"USER_UNAUTHORIZED","USER_LOCKED"}:return 401
    if code=="USER_CSRF":return 403
    if code=="FORBIDDEN":return 403
    if code=="ACHIEVEMENT_CONFLICT":return 409
    if code=="USER_ACCOUNT_UNAVAILABLE":return 503
    if code in {"DB_UNAVAILABLE", "ADMIN_WRITE_UNAVAILABLE", "ADMIN_SCHEMA_UNAVAILABLE"}:return 503
    if code in {"INVALID_REQUEST", "INVALID_PAYLOAD"}:
        return 422
    if code == "NOT_FOUND":
        return 404
    if code in {"TIMEOUT", "CONNECT_TIMEOUT"}:
        return 504
    if code in {"UPSTREAM_DISCONNECTED", "UPSTREAM_PROTOCOL", "UNKNOWN_OPERATION", "UNSUPPORTED_VERSION", "MALFORMED_FRAME", "FRAME_LENGTH", "TRUNCATED_FRAME"}:
        return 502
    return 503


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if not value:
        value = str(uuid.uuid4())
        request.state.request_id = value
    return value


ADMIN_COOKIE="goiy_admin_session"
USER_COOKIE="goiy_user_session"


def _admin_claims(request):
    return verify_admin_token(request.cookies.get(ADMIN_COOKIE))


def _admin_error(request, code="ADMIN_UNAUTHORIZED", status=401):
    return JSONResponse(error_response(_request_id(request),code,"Admin session is missing or expired."),status_code=status,
                        headers={"X-Request-ID":_request_id(request)})


def _admin_tcp(request,payload,*,csrf=None):
    claims=_admin_claims(request)
    if claims is None:
        return None,_admin_error(request)
    if csrf is not None and not hmac.compare_digest(str(csrf),claims["csrf"]):
        return None,_admin_error(request,"ADMIN_CSRF",403)
    return {**payload,"admin_token":request.cookies[ADMIN_COOKIE]},None


def _user_claims(request):
    from source.common.user_tokens import verify
    return verify(request.cookies.get(USER_COOKIE))


def _user_tcp(request,payload,*,csrf=None):
    claims=_user_claims(request)
    token=request.cookies.get(USER_COOKIE)
    if claims is None or not token:
        return None,JSONResponse(error_response(_request_id(request),"USER_UNAUTHORIZED","User session is missing or expired."),status_code=401)
    if csrf is not None and not hmac.compare_digest(str(csrf),claims["csrf"]):
        return None,JSONResponse(error_response(_request_id(request),"USER_CSRF","Invalid CSRF token."),status_code=403)
    return {**payload,"session_token":token},None


def _account_exchange(request,operation,payload):
    response=call_tcp(request,operation,payload)
    try:
        envelope=json.loads(response.body)
    except (ValueError,TypeError):
        return response
    if response.status_code!=200 or envelope.get("ok") is not True:
        return response
    data=envelope.get("data") or {}
    token=data.pop("session_token",None)
    public_data={key:value for key,value in data.items() if key!="csrf_token"}
    result=JSONResponse({**envelope,"data":public_data},status_code=200,headers={"X-Request-ID":_request_id(request)})
    secure_setting=os.getenv("USER_COOKIE_SECURE")
    secure=(secure_setting.casefold() not in {"0","false","no"}) if secure_setting is not None else request.url.scheme=="https"
    if token:
        result.set_cookie(USER_COOKIE,token,max_age=43200,httponly=True,secure=secure,samesite="lax",path="/")
    if data.get("role")=="ADMIN" and data.get("user_id"):
        admin_token,_=issue_admin_token(data["username"],account_uid=int(data["user_id"]))
        result.set_cookie(ADMIN_COOKIE,admin_token,max_age=3600,httponly=True,secure=secure,samesite="strict",path="/")
    return result


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        if request.url.path.startswith("/api/"):
            _gateway_log(request_id=request.state.request_id, layer="http", method=request.method,
                         path=request.url.path, outcome="exception", status=500,
                         elapsed_ms=round((time.monotonic() - started) * 1000, 3))
        raise
    response.headers["X-Request-ID"] = request.state.request_id
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        _gateway_log(request_id=request.state.request_id, layer="http", method=request.method,
                     path=request.url.path, outcome="response", status=response.status_code,
                     elapsed_ms=round((time.monotonic() - started) * 1000, 3))
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, _exc: RequestValidationError):
    request_id = _request_id(request)
    return JSONResponse(error_response(request_id, "INVALID_PAYLOAD", "Dữ liệu gửi lên không hợp lệ."), status_code=422, headers={"X-Request-ID": request_id})


def call_tcp(request: Request, op: str, payload: dict[str, Any]) -> JSONResponse:
    request_id = _request_id(request)
    host = os.getenv("TCP_HOST", "127.0.0.1")
    port = int(os.getenv("TCP_PORT", "9000"))
    target = f"{host}:{port}"
    started = time.monotonic()
    try:
        response = TCPClient(host, port).request(op, payload, request_id=request_id)
    except TCPClientError as exc:
        code = exc.code
        _gateway_log(request_id=request_id, layer="tcp_client", op=op, target=target,
                     outcome="transport_error", error_code=code, phase=exc.phase,
                     os_error=exc.os_error, elapsed_ms=round((time.monotonic() - started) * 1000, 3))
        message = {
            "UPSTREAM_UNAVAILABLE": "Không thể kết nối tới TCP Server.",
            "CONNECT_TIMEOUT": "Kết nối tới TCP Server quá thời gian chờ.",
            "TIMEOUT": "TCP Server không trả lời trong thời gian cho phép.",
            "UPSTREAM_DISCONNECTED": "TCP Server đã đóng kết nối trước khi trả kết quả.",
            "UPSTREAM_PROTOCOL": "Phản hồi từ TCP Server không hợp lệ.",
        }.get(code, "Yêu cầu TCP thất bại.")
        response = error_response(request_id, code, message)
        return JSONResponse(response, status_code=http_status_for_error(code), headers={"X-Request-ID": request_id})
    if not isinstance(response, dict) or response.get("request_id") != request_id or response.get("version") != 1 or not isinstance(response.get("ok"), bool):
        _gateway_log(request_id=request_id, layer="tcp_client", op=op, target=target,
                     outcome="invalid_envelope", error_code="UPSTREAM_PROTOCOL",
                     elapsed_ms=round((time.monotonic() - started) * 1000, 3))
        response = error_response(request_id, "UPSTREAM_PROTOCOL", "TCP Server trả về response không hợp lệ.")
        return JSONResponse(response, status_code=502, headers={"X-Request-ID": request_id})
    if response["ok"] is False:
        error = response.get("error") or {}
        backend_code = error.get("code", "INTERNAL_ERROR") if isinstance(error, dict) else "INTERNAL_ERROR"
        outcome = "backend_error"
    else:
        backend_code = None
        outcome = "response"
    _gateway_log(request_id=request_id, layer="tcp_client", op=op, target=target,
                 outcome=outcome, error_code=backend_code,
                 elapsed_ms=round((time.monotonic() - started) * 1000, 3))
    if response["ok"] is False:
        error = response.get("error") or {}
        code = error.get("code", "INTERNAL_ERROR") if isinstance(error, dict) else "INTERNAL_ERROR"
        if code == "NOT_FOUND" and op == "GET_RECIPE":
            response = error_response(request_id, code, "Không tìm thấy món ăn với mã đã yêu cầu.")
        return JSONResponse(response, status_code=http_status_for_error(code), headers={"X-Request-ID": request_id})
    if response.get("data") is None or response.get("error") is not None:
        response = error_response(request_id, "UPSTREAM_PROTOCOL", "TCP Server trả về response không hợp lệ.")
        return JSONResponse(response, status_code=502, headers={"X-Request-ID": request_id})
    if op in {"GENERATE_MEAL_PLAN", "GENERATE_MEAL_PLAN_V2"}:
        try:
            parsed = (MealPlanData if op == "GENERATE_MEAL_PLAN" else MealPlanV2Data).model_validate(response["data"])
            if op == "GENERATE_MEAL_PLAN_V2" and payload.get("people") is not None and parsed.people != payload["people"]:
                raise ValueError("meal people changed")
            if op == "GENERATE_MEAL_PLAN_V2" and parsed.layout_mode != payload.get("layout_mode", "automatic"):
                raise ValueError("meal layout mode changed")
            if op == "GENERATE_MEAL_PLAN_V2" and payload.get("preferences"):
                if parsed.preferences is None or parsed.preferences.model_dump(exclude_none=True) != payload["preferences"]:
                    raise ValueError("meal preferences changed")
        except (ValidationError, ValueError):
            response = error_response(request_id, "UPSTREAM_PROTOCOL", "Dữ liệu mâm cơm từ TCP Server không hợp lệ.")
            return JSONResponse(response, status_code=502, headers={"X-Request-ID": request_id})
    if op == "GET_MEAL_PLAN_FILTERS":
        try:
            FilterCatalog.model_validate(response["data"])
        except ValidationError:
            response = error_response(request_id, "UPSTREAM_PROTOCOL", "Danh mục bộ lọc không hợp lệ.")
            return JSONResponse(response, status_code=502, headers={"X-Request-ID": request_id})
    if op == "CALCULATE_MEAL_PLAN":
        try:
            calculation = CalculationData.model_validate(response["data"])
            if calculation.recipe_ids != payload["recipe_ids"] or calculation.people != payload["people"]:
                raise ValueError("calculation response does not match request")
        except (ValidationError, ValueError):
            response = error_response(request_id, "UPSTREAM_PROTOCOL", "Dữ liệu khẩu phần từ TCP Server không hợp lệ.")
            return JSONResponse(response, status_code=502, headers={"X-Request-ID": request_id})
    return JSONResponse(response, status_code=200, headers={"X-Request-ID": request_id})


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    view=request.query_params.get("view", "fridge")
    active_tab=view if view in {"explore", "fridge", "lunch"} else "fridge"
    return templates.TemplateResponse(request=request, name="index.html", context={"page_title": "Hôm nay ăn gì?", "active_tab":active_tab,
        "account_target":"/account/profile" if _user_claims(request) else "/account/login"})


@app.get("/account/login",response_class=HTMLResponse)
def user_login_page(request:Request, next: str = Query(default="", max_length=300)):
    if _user_claims(request):
        destination=next if next.startswith("/") and not next.startswith("//") else "/"
        return RedirectResponse(destination,status_code=303)
    return templates.TemplateResponse(request=request,name="account_auth.html",
        context={"page_title":"Đăng nhập · Hôm nay ăn gì?","mode":"login","next_url":next if next.startswith("/") and not next.startswith("//") else "/"})


@app.get("/account/register",response_class=HTMLResponse)
def user_register_page(request:Request, next: str = Query(default="", max_length=300)):
    if _user_claims(request):
        destination=next if next.startswith("/") and not next.startswith("//") else "/"
        return RedirectResponse(destination,status_code=303)
    return templates.TemplateResponse(request=request,name="account_auth.html",
        context={"page_title":"Tạo tài khoản · Hôm nay ăn gì?","mode":"register","next_url":next if next.startswith("/") and not next.startswith("//") else "/"})


@app.get("/account/profile",response_class=HTMLResponse)
def user_profile_page(request:Request):
    if not _user_claims(request):
        return RedirectResponse("/account/login",status_code=303)
    return templates.TemplateResponse(request=request,name="account_profile.html",
        context={"page_title":"Tài khoản của tôi · Hôm nay ăn gì?","active_tab":"account","account_target":"/account/profile"})


@app.post("/api/auth/register")
def user_register(request:Request,body:UserRegisterRequest):
    return _account_exchange(request,"USER_REGISTER",body.model_dump())


@app.post("/api/auth/login")
def user_login(request:Request,body:UserLoginRequest):
    return _account_exchange(request,"USER_LOGIN",body.model_dump())


@app.get("/api/auth/session")
def user_session(request:Request):
    claims=_user_claims(request)
    if claims is None:
        response=JSONResponse({"version":1,"request_id":_request_id(request),"ok":True,
            "data":{"authenticated":False},"error":None})
        if request.cookies.get(USER_COOKIE):
            response.delete_cookie(USER_COOKIE,path="/",httponly=True,samesite="lax")
        return response
    payload,error=_user_tcp(request,{})
    if error:return error
    upstream=call_tcp(request,"USER_SESSION",payload)
    try:envelope=json.loads(upstream.body)
    except (ValueError,TypeError):return upstream
    if upstream.status_code!=200 or envelope.get("ok") is not True:
        if upstream.status_code==401:
            upstream.delete_cookie(USER_COOKIE,path="/",httponly=True,samesite="lax")
        return upstream
    data=envelope.get("data") or {}
    response=JSONResponse({**envelope,"data":{"authenticated":True,"user_id":data.get("user_id"),"username":data.get("username"),
        "role":data.get("role"),"csrf_token":data.get("csrf_token")}},headers={"X-Request-ID":_request_id(request)})
    return response


@app.post("/api/auth/logout")
def user_logout(request:Request):
    claims=_user_claims(request)
    if claims is not None and not hmac.compare_digest(request.headers.get("x-csrf-token",""),claims["csrf"]):
        return JSONResponse(error_response(_request_id(request),"USER_CSRF","Invalid CSRF token."),status_code=403)
    response=JSONResponse({"version":1,"request_id":_request_id(request),"ok":True,
        "data":{"logged_out":True},"error":None})
    secure_setting=os.getenv("USER_COOKIE_SECURE")
    secure=(secure_setting.casefold() not in {"0","false","no"}) if secure_setting is not None else request.url.scheme=="https"
    response.delete_cookie(USER_COOKIE,path="/",secure=secure,httponly=True,samesite="lax")
    return response


@app.get("/admin/login",response_class=HTMLResponse)
def admin_login_page(request:Request):
    if _admin_claims(request):
        return RedirectResponse("/admin",status_code=303)
    return templates.TemplateResponse(request=request,name="admin_login.html",context={"page_title":"Admin · Đăng nhập"})


@app.get("/admin",response_class=HTMLResponse)
def admin_page(request:Request):
    if not _admin_claims(request):
        return RedirectResponse("/admin/login",status_code=303)
    return templates.TemplateResponse(request=request,name="admin.html",context={"page_title":"Admin · Quản lý công thức",
        "unified_schema":_unified_schema_mode()})


@app.post("/api/admin/login")
def admin_login(request:Request,body:AdminLoginRequest):
    request_id=_request_id(request)
    if not admin_auth.configured():
        return JSONResponse(error_response(request_id,"ADMIN_NOT_CONFIGURED","Admin authentication is not configured on the server."),status_code=503)
    valid_user=admin_auth.username_matches(body.username)
    valid_password=admin_auth.password_matches(body.password)
    if not(valid_user and valid_password):
        return JSONResponse(error_response(request_id,"ADMIN_UNAUTHORIZED","Invalid administrator credentials."),status_code=401)
    token,_claims=issue_admin_token(body.username)
    secure=os.getenv("ADMIN_COOKIE_SECURE","true").casefold() not in {"0","false","no"}
    response=JSONResponse({"version":1,"request_id":request_id,"ok":True,"data":{"authenticated":True},"error":None})
    response.set_cookie(ADMIN_COOKIE,token,max_age=3600,httponly=True,secure=secure,samesite="strict",path="/")
    response.headers["X-Request-ID"]=request_id
    return response


def _achievement_urls(data, *, admin=False):
    def attach(post):
        if not isinstance(post, dict):
            return
        for image in post.get("images", []):
            key = image.get("storage_key", "")
            base = "/api/admin/achievements/media/" if admin else "/media/achievements/"
            image["image_url"] = base + key + "?v=" + str(image.get("sha256", ""))
    if isinstance(data, dict):
        if "items" in data:
            for item in data.get("items", []): attach(item)
        if "post_id" in data: attach(data)
    return data


@app.get("/achievements", response_class=HTMLResponse)
def achievements_page(request: Request):
    return templates.TemplateResponse(request=request, name="achievements.html", context={
        "page_title": "Thành quả · Hôm nay ăn gì?", "active_tab": "achievements",
        "account_target": "/account/profile" if _user_claims(request) else "/account/login"})


@app.get("/api/achievements")
def achievements_list(request: Request, query: str = Query(default="", max_length=80),
                      limit: int = Query(default=12, ge=1, le=30), offset: int = Query(default=0, ge=0, le=100000)):
    response = call_tcp(request, "ACHIEVEMENT_LIST", {"query": query, "limit": limit, "offset": offset})
    envelope = _tcp_envelope(response)
    if envelope.get("ok") is True:
        data = _achievement_urls(envelope.get("data") or {})
        return JSONResponse({**envelope, "data": data}, status_code=response.status_code, headers={"X-Request-ID": _request_id(request)})
    return response


@app.get("/api/achievements/{post_id}")
def achievement_get(request: Request, post_id: int = FastAPIPath(ge=1, lt=2**64)):
    response = call_tcp(request, "ACHIEVEMENT_GET", {"post_id": post_id})
    envelope = _tcp_envelope(response)
    if envelope.get("ok") is True:
        return JSONResponse({**envelope, "data": _achievement_urls(envelope.get("data") or {})},
                            status_code=response.status_code, headers={"X-Request-ID": _request_id(request)})
    return response


@app.post("/api/achievements")
async def achievement_create(request: Request):
    auth, error = _user_tcp(request, {}, csrf=request.headers.get("x-csrf-token", ""))
    if error:
        return error
    declared = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if declared != "application/json":
        return JSONResponse(error_response(_request_id(request), "INVALID_PAYLOAD", "Send achievement content as JSON."), status_code=422)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 22 * 1024 * 1024:
            return JSONResponse(error_response(_request_id(request), "INVALID_PAYLOAD", "Combined photo upload is too large."), status_code=413)
        raw.extend(chunk)
    try:
        body = json.loads(raw.decode("utf-8"))
        if not isinstance(body, dict) or set(body) != {"recipe_id", "description", "changed_ingredients", "request_key", "images"}:
            raise ValueError
        if not isinstance(body["images"], list) or not 1 <= len(body["images"]) <= 3:
            raise ValueError
        from source.web.achievement_images import validate_image, write_image, storage_root, delete_image
        saved_keys, image_rows = [], []
        prepared = []
        for item in body["images"]:
            if not isinstance(item, dict) or set(item) != {"media_type", "data_base64"} or not isinstance(item["data_base64"], str):
                raise ValueError
            binary = base64.b64decode(item["data_base64"], validate=True)
            if len(binary) > 5 * 1024 * 1024:
                return JSONResponse(error_response(_request_id(request), "INVALID_PAYLOAD", "Each photo must be 5 MB or smaller."), status_code=413)
            normalized, metadata = validate_image(binary, item["media_type"])
            prepared.append((normalized, metadata))
        for normalized, metadata in prepared:
            key, _path = write_image(normalized, str(metadata["extension"]), storage_root())
            saved_keys.append(key)
            image_rows.append({key_name: metadata[key_name] for key_name in ("media_type", "byte_size", "width", "height", "sha256")})
            image_rows[-1]["storage_key"] = key
        payload = {key: body[key] for key in ("recipe_id", "description", "changed_ingredients", "request_key")}
        payload["images"] = image_rows
        response = call_tcp(request, "ACHIEVEMENT_CREATE", {**auth, **payload})
        envelope = _tcp_envelope(response)
        if response.status_code >= 400 or envelope.get("ok") is not True:
            # The create is idempotent. Probe its request key before removing any
            # files, since a transport timeout can happen after MySQL commits.
            probe = call_tcp(request, "ACHIEVEMENT_CREATE_STATUS", {**auth, "request_key": body["request_key"]})
            probe_envelope = _tcp_envelope(probe)
            post = ((probe_envelope.get("data") or {}).get("achievement") if probe.status_code < 400 and probe_envelope.get("ok") is True else None)
            if post:
                for key in saved_keys:
                    delete_image(key, storage_root())
                return JSONResponse({"version": 1, "request_id": _request_id(request), "ok": True,
                    "data": {"post_id": post["post_id"], "created": False, "url": "/achievements?post_id=" + post["post_id"]}, "error": None})
            for key in saved_keys:
                delete_image(key, storage_root())
            return response
        data = envelope.get("data") or {}
        if data.get("created") is False:
            for key in saved_keys:
                delete_image(key, storage_root())
        data["url"] = "/achievements?post_id=" + str(data.get("post_id", ""))
        return JSONResponse({**envelope, "data": data}, status_code=response.status_code,
                            headers={"X-Request-ID": _request_id(request)})
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, binascii.Error):
        try:
            for key in saved_keys:
                delete_image(key, storage_root())
        except UnboundLocalError:
            pass
        return JSONResponse(error_response(_request_id(request), "INVALID_PAYLOAD", "Check the achievement text and choose valid JPG, PNG or WebP photos."), status_code=422)


@app.post("/api/achievements/{post_id}/comments")
def achievement_comment_create(request: Request, body: AchievementCommentRequest, post_id: int = FastAPIPath(ge=1, lt=2**64)):
    auth, error = _user_tcp(request, {"post_id": post_id, **body.model_dump()}, csrf=request.headers.get("x-csrf-token", ""))
    return error or call_tcp(request, "ACHIEVEMENT_COMMENT_CREATE", auth)


@app.get("/media/achievements/{storage_key}")
def achievement_image_file(request: Request, storage_key: str = FastAPIPath(min_length=36, max_length=36), admin: bool = False):
    from hashlib import sha256
    from source.web.achievement_images import safe_image_path, storage_root, RecipeImageError
    if admin:
        auth, auth_error = _admin_tcp(request, {})
        if auth_error: return auth_error
        metadata = call_tcp(request, "ADMIN_ACHIEVEMENT_IMAGE_GET", {**auth, "storage_key": storage_key})
    else:
        metadata = call_tcp(request, "ACHIEVEMENT_IMAGE_GET", {"storage_key": storage_key})
    envelope = _tcp_envelope(metadata)
    if metadata.status_code >= 400 or envelope.get("ok") is not True:
        return JSONResponse(error_response(_request_id(request), "NOT_FOUND", "Achievement image not found."), status_code=404)
    image = envelope.get("data") or {}
    try:
        path = safe_image_path(storage_root(), storage_key)
        content = path.read_bytes()
    except (RecipeImageError, OSError):
        return JSONResponse(error_response(_request_id(request), "NOT_FOUND", "Achievement image not found."), status_code=404)
    if len(content) != image.get("byte_size") or sha256(content).hexdigest() != image.get("sha256"):
        return JSONResponse(error_response(_request_id(request), "NOT_FOUND", "Achievement image integrity check failed."), status_code=404)
    return Response(content, media_type=image.get("media_type"), headers={"Cache-Control":"private, no-store", "X-Content-Type-Options":"nosniff"})


@app.delete("/api/achievements/{post_id}")
def achievement_delete(request: Request, post_id: int = FastAPIPath(ge=1, lt=2**64)):
    auth, error = _user_tcp(request, {"post_id": post_id}, csrf=request.headers.get("x-csrf-token", ""))
    if error:
        return error
    response = call_tcp(request, "ACHIEVEMENT_POST_DELETE", auth)
    envelope = _tcp_envelope(response)
    if response.status_code < 400 and envelope.get("ok") is True:
        from source.web.achievement_images import delete_image
        for key in (envelope.get("data") or {}).get("storage_keys", []): delete_image(key)
    return response


@app.delete("/api/achievements/comments/{comment_id}")
def achievement_comment_delete(request: Request, comment_id: int = FastAPIPath(ge=1, lt=2**64)):
    auth, error = _user_tcp(request, {"comment_id": comment_id}, csrf=request.headers.get("x-csrf-token", ""))
    return error or call_tcp(request, "ACHIEVEMENT_COMMENT_DELETE", auth)


@app.get("/api/admin/achievements")
def admin_achievements(request: Request, query: str = Query(default="", max_length=80),
                       limit: int = Query(default=20, ge=1, le=30), offset: int = Query(default=0, ge=0, le=100000)):
    auth, error = _admin_tcp(request, {"query": query, "limit": limit, "offset": offset})
    if error: return error
    response = call_tcp(request, "ADMIN_ACHIEVEMENT_LIST", auth)
    envelope = _tcp_envelope(response)
    if envelope.get("ok") is True:
        return JSONResponse({**envelope, "data": _achievement_urls(envelope.get("data") or {}, admin=True)},
                            status_code=response.status_code, headers={"X-Request-ID": _request_id(request)})
    return response


@app.get("/api/admin/achievements/media/{storage_key}")
def admin_achievement_image_file(request: Request, storage_key: str = FastAPIPath(min_length=36, max_length=36)):
    return achievement_image_file(request, storage_key, admin=True)


@app.get("/api/admin/achievements/{post_id}")
def admin_achievement_get(request: Request, post_id: int = FastAPIPath(ge=1, lt=2**64)):
    auth, error = _admin_tcp(request, {"post_id": post_id})
    if error: return error
    response = call_tcp(request, "ADMIN_ACHIEVEMENT_GET", auth)
    envelope = _tcp_envelope(response)
    if envelope.get("ok") is True:
        return JSONResponse({**envelope, "data": _achievement_urls(envelope.get("data") or {}, admin=True)},
                            status_code=response.status_code, headers={"X-Request-ID": _request_id(request)})
    return response


@app.delete("/api/admin/achievements/{post_id}")
def admin_achievement_delete(request: Request, post_id: int = FastAPIPath(ge=1, lt=2**64)):
    auth, error = _admin_tcp(request, {"post_id": post_id}, csrf=request.headers.get("x-csrf-token", ""))
    if error: return error
    response = call_tcp(request, "ADMIN_ACHIEVEMENT_POST_DELETE", auth)
    envelope = _tcp_envelope(response)
    if response.status_code < 400 and envelope.get("ok") is True:
        from source.web.achievement_images import delete_image
        for key in (envelope.get("data") or {}).get("storage_keys", []): delete_image(key)
    return response


@app.delete("/api/admin/achievements/comments/{comment_id}")
def admin_achievement_comment_delete(request: Request, comment_id: int = FastAPIPath(ge=1, lt=2**64)):
    auth, error = _admin_tcp(request, {"comment_id": comment_id}, csrf=request.headers.get("x-csrf-token", ""))
    return error or call_tcp(request, "ADMIN_ACHIEVEMENT_COMMENT_DELETE", auth)


@app.get("/api/admin/session")
def admin_session(request:Request):
    claims=_admin_claims(request)
    if claims is None:return _admin_error(request)
    return JSONResponse({"version":1,"request_id":_request_id(request),"ok":True,
        "data":{"username":claims["sub"],"csrf_token":claims["csrf"]},"error":None},headers={"X-Request-ID":_request_id(request)})


@app.post("/api/admin/logout")
def admin_logout(request:Request):
    request_id=_request_id(request)
    claims=_admin_claims(request)
    if claims is None:return _admin_error(request)
    if not hmac.compare_digest(request.headers.get("x-csrf-token",""),claims["csrf"]):
        return _admin_error(request,"ADMIN_CSRF",403)
    response=JSONResponse({"version":1,"request_id":_request_id(request),"ok":True,"data":{"logged_out":True},"error":None})
    secure=os.getenv("ADMIN_COOKIE_SECURE","true").casefold() not in {"0","false","no"}
    response.delete_cookie(ADMIN_COOKIE,path="/",secure=secure,httponly=True,samesite="strict")
    response.headers["X-Request-ID"]=request_id
    return response


@app.get("/api/admin/dashboard")
def admin_dashboard(request:Request):
    payload,error=_admin_tcp(request,{})
    return error or call_tcp(request,"ADMIN_DASHBOARD",payload)


@app.get("/api/admin/recipes")
def admin_recipes(request:Request,query:str=Query(default="",max_length=80),limit:int=Query(default=20,ge=1,le=50),
                  offset:int=Query(default=0,ge=0,le=10000),role:Literal["main","vegetable","soup","side","drink","starch","other"]|None=None,
                  visibility:Literal["visible","hidden","deleted"]|None=None,max_minutes:int|None=Query(default=None,ge=1,le=1440)):
    payload={"query":query,"limit":limit,"offset":offset}
    if role is not None:payload["role"]=role
    if visibility is not None:payload["visibility"]=visibility
    if max_minutes is not None:payload["max_minutes"]=max_minutes
    payload,error=_admin_tcp(request,payload)
    return error or call_tcp(request,"ADMIN_LIST_RECIPES",payload)


@app.get("/api/admin/revisions/{revision_id}")
def admin_revision(request:Request,revision_id:int=FastAPIPath(ge=1,lt=2**64)):
    payload,error=_admin_tcp(request,{"revision_id":revision_id})
    return error or call_tcp(request,"ADMIN_GET_RECIPE",payload)


@app.get("/api/admin/legacy-recipes/{recipe_id}")
def admin_legacy_recipe(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**32)):
    payload,error=_admin_tcp(request,{"recipe_id":recipe_id})
    return error or call_tcp(request,"ADMIN_GET_LEGACY_RECIPE",payload)


@app.patch("/api/admin/legacy-recipes/{recipe_id}")
def admin_update_legacy_recipe(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**32),body:AdminLegacyRecipeUpdate|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","legacy recipe fields are required"),status_code=422)
    data=body.model_dump()
    data["ingredients"]=[{**line,"is_required":True} for line in data["ingredients"]]
    payload,error=_admin_tcp(request,{"recipe_id":recipe_id,**data},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_UPDATE_LEGACY_RECIPE",payload)


@app.post("/api/admin/recipes/{recipe_id}/snapshot")
def admin_create_recipe_snapshot(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**64),body:AdminRecipeSnapshotCreate|None=None):
    from source.common.protocol import success_response
    from source.common.catalog_ids import UINT32_MAX,valid_public_id
    from source.web import recipe_snapshots
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","snapshot kind is required"),status_code=422)
    if not valid_public_id(recipe_id) or (recipe_id<=UINT32_MAX)!=(body.kind=="legacy"):
        return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","snapshot recipe identity does not match its catalog kind"),status_code=422)
    if (body.kind=="legacy" and body.revision_id is not None) or (body.kind=="v2" and body.revision_id is None):
        return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","legacy snapshots omit revision_id; v2 snapshots require it"),status_code=422)
    auth,error=_admin_tcp(request,{},csrf=request.headers.get("x-csrf-token",""))
    if error:return error
    if body.kind=="legacy":
        response=call_tcp(request,"ADMIN_GET_LEGACY_RECIPE",{"recipe_id":recipe_id,**auth})
    else:
        response=call_tcp(request,"ADMIN_GET_RECIPE",{"revision_id":body.revision_id,**auth})
    envelope=_tcp_envelope(response)
    if response.status_code>=400 or envelope.get("ok") is not True:return response
    recipe=envelope.get("data") or {}
    if body.kind=="v2" and (recipe.get("recipe_id")!=recipe_id or recipe.get("revision_id")!=body.revision_id):
        return JSONResponse(error_response(_request_id(request),"ADMIN_RECIPE_CONFLICT","revision identity changed; reload before taking a snapshot"),status_code=409)
    image_response=call_tcp(request,"ADMIN_GET_RECIPE_IMAGE",{"recipe_id":recipe_id,**auth})
    image_envelope=_tcp_envelope(image_response)
    if image_response.status_code>=400 or image_envelope.get("ok") is not True:return image_response
    image_data=image_envelope.get("data") or {}
    image={"metadata":image_data.get("image"),"fallback_url":_legacy_fallback_image(recipe_id) if body.kind=="legacy" else "/static/images/recipes/placeholder.svg"}
    try:
        result=recipe_snapshots.create(body.kind,recipe_id,recipe,image,revision_id=body.revision_id)
    except recipe_snapshots.SnapshotError as exc:
        return JSONResponse(error_response(_request_id(request),"ADMIN_SNAPSHOT_ERROR",str(exc)),status_code=409)
    return JSONResponse(success_response(_request_id(request),result),headers={"X-Request-ID":_request_id(request)})


@app.post("/api/admin/recipes/{recipe_id}/restore")
def admin_restore_recipe_snapshot(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**64),body:AdminRecipeSnapshotRestore|None=None):
    from source.common.catalog_ids import UINT32_MAX,valid_public_id
    from source.web import recipe_snapshots
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","snapshot ID and expected version are required"),status_code=422)
    if not valid_public_id(recipe_id):return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","recipe ID is invalid"),status_code=422)
    auth,error=_admin_tcp(request,{},csrf=request.headers.get("x-csrf-token",""))
    if error:return error
    try:snapshot=recipe_snapshots.load(body.snapshot_id)
    except recipe_snapshots.SnapshotError as exc:
        return JSONResponse(error_response(_request_id(request),"NOT_FOUND",str(exc)),status_code=404)
    kind="legacy" if recipe_id<=UINT32_MAX else "v2"
    if snapshot["recipe_id"]!=recipe_id or snapshot["kind"]!=kind:
        return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","snapshot belongs to a different recipe"),status_code=422)
    if kind=="legacy":
        current_response=call_tcp(request,"ADMIN_GET_LEGACY_RECIPE",{"recipe_id":recipe_id,**auth})
    else:
        revision_id=snapshot.get("revision_id")
        if not revision_id:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","v2 snapshot has no revision identity"),status_code=422)
        current_response=call_tcp(request,"ADMIN_GET_RECIPE",{"revision_id":revision_id,**auth})
    current_envelope=_tcp_envelope(current_response)
    if current_response.status_code>=400 or current_envelope.get("ok") is not True:return current_response
    current=current_envelope.get("data") or {}
    current_version=current.get("edit_version")
    if current_version!=body.expected_version:
        return JSONResponse(error_response(_request_id(request),"ADMIN_RECIPE_CONFLICT","recipe changed after the restore screen was opened; reload before restoring"),status_code=409)
    fields=snapshot.get("fields") or {}
    if kind=="legacy":
        payload={"kind":"legacy","recipe_id":recipe_id,"title":fields.get("title"),"description":fields.get("description"),
            "instructions":fields.get("instructions"),"minutes":fields.get("minutes"),"is_visible":fields.get("is_visible"),
            "ingredients":fields.get("ingredients"),"expected_version":current_version,"admin_token":auth["admin_token"]}
        return call_tcp(request,"ADMIN_RESTORE_RECIPE_SNAPSHOT",payload)
    payload={"kind":"v2","recipe_id":recipe_id,"revision_id":snapshot["revision_id"],"title":fields.get("title"),
        "description":fields.get("description"),"instructions":fields.get("instructions"),"minutes":fields.get("minutes"),
        "role":fields.get("role"),"ingredients":fields.get("ingredients"),"expected_version":current_version,
        "admin_token":auth["admin_token"]}
    return call_tcp(request,"ADMIN_RESTORE_RECIPE_SNAPSHOT",payload)


@app.patch("/api/admin/legacy-recipes/{recipe_id}/visibility")
def admin_set_legacy_recipe_visibility(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**32),body:AdminLegacyVisibility|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","visibility state is required"),status_code=422)
    payload,error=_admin_tcp(request,{"recipe_id":recipe_id,**body.model_dump()},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SET_LEGACY_RECIPE_VISIBILITY",payload)


@app.get("/api/admin/ingredients")
def admin_ingredients(request:Request,query:str=Query(default="",max_length=80),limit:int=Query(default=20,ge=1,le=50),
                      offset:int=Query(default=0,ge=0,le=1_000_000),active_only:bool=Query(default=False),
                      status:str=Query(default="all",pattern="^(all|active|inactive)$"),
                      catalog:str=Query(default="shared",pattern="^(shared|v2)$")):
    payload,error=_admin_tcp(request,{"query":query,"limit":limit,"offset":offset,"active_only":active_only,"status":status,"catalog":catalog})
    return error or call_tcp(request,"ADMIN_LIST_INGREDIENTS",payload)


@app.get("/api/admin/units")
def admin_units(request:Request):
    if not _unified_schema_mode():
        return JSONResponse(error_response(_request_id(request),"UNSUPPORTED_OPERATION","Đơn vị cấu trúc chỉ có trên catalog v3."),status_code=404)
    payload,error=_admin_tcp(request,{})
    return error or call_tcp(request,"ADMIN_LIST_UNITS",payload)


@app.get("/api/admin/users")
def admin_users(request:Request,query:str=Query(default="",max_length=80),limit:int=Query(default=20,ge=1,le=50),
                offset:int=Query(default=0,ge=0,le=1_000_000)):
    payload,error=_admin_tcp(request,{"query":query,"limit":limit,"offset":offset})
    return error or call_tcp(request,"ADMIN_LIST_USERS",payload)


@app.patch("/api/admin/users/{user_id}/status")
def admin_user_status(request:Request,user_id:str=FastAPIPath(pattern=r"^[0-9]{1,20}$"),body:AdminUserStatusRequest|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","account status is required"),status_code=422)
    payload,error=_admin_tcp(request,{"user_id":user_id,**body.model_dump()},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SET_USER_STATUS",payload)


@app.patch("/api/admin/users/{user_id}/role")
def admin_user_role(request:Request,user_id:str=FastAPIPath(pattern=r"^[0-9]{1,20}$"),body:AdminUserRoleRequest|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","account role is required"),status_code=422)
    payload,error=_admin_tcp(request,{"user_id":user_id,**body.model_dump()},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SET_USER_ROLE",payload)


@app.post("/api/admin/ingredients")
def admin_create_ingredient(request:Request,body:AdminIngredientName):
    payload,error=_admin_tcp(request,body.model_dump(exclude_none=True),csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_CREATE_INGREDIENT",payload)


@app.patch("/api/admin/ingredients/{ingredient_id}")
def admin_update_ingredient(request:Request,ingredient_id:int=FastAPIPath(ge=1,lt=2**64),body:AdminIngredientName|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","ingredient name is required"),status_code=422)
    payload,error=_admin_tcp(request,{"ingredient_id":ingredient_id,**body.model_dump(exclude_none=True)},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_UPDATE_INGREDIENT",payload)


@app.patch("/api/admin/ingredients/{ingredient_id}/active")
def admin_set_ingredient_active(request:Request,ingredient_id:int=FastAPIPath(ge=1,lt=2**64),body:AdminIngredientActive|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","ingredient state is required"),status_code=422)
    payload,error=_admin_tcp(request,{"ingredient_id":ingredient_id,**body.model_dump()},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SET_INGREDIENT_ACTIVE",payload)


@app.delete("/api/admin/ingredients/{ingredient_id}/permanent")
def admin_ingredient_delete_permanent(request:Request,ingredient_id:int=FastAPIPath(ge=1,lt=2**64)):
    payload,error=_admin_tcp(request,{"ingredient_id":ingredient_id},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_DELETE_INGREDIENT_PERMANENT",payload)


@app.patch("/api/admin/legacy-ingredients/{ingredient_id}")
def admin_update_legacy_ingredient(request:Request,ingredient_id:int=FastAPIPath(ge=1,lt=2**32),body:AdminIngredientName|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","ingredient name is required"),status_code=422)
    payload,error=_admin_tcp(request,{"ingredient_id":ingredient_id,"name":body.name},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_UPDATE_LEGACY_INGREDIENT",payload)


@app.patch("/api/admin/legacy-ingredients/{ingredient_id}/active")
def admin_set_legacy_ingredient_active(request:Request,ingredient_id:int=FastAPIPath(ge=1,lt=2**32),body:AdminIngredientActive|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","ingredient state is required"),status_code=422)
    payload,error=_admin_tcp(request,{"ingredient_id":ingredient_id,**body.model_dump()},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SET_LEGACY_INGREDIENT_ACTIVE",payload)


@app.post("/api/admin/revisions")
def admin_create_draft(request:Request,body:AdminDraftRequest):
    payload,error=_admin_tcp(request,body.model_dump(),csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_CREATE_DRAFT",payload)


@app.patch("/api/admin/revisions/{revision_id}")
def admin_update_draft(request:Request,body:AdminDraftRequest,revision_id:int=FastAPIPath(ge=1,lt=2**64)):
    payload={**body.model_dump(),"revision_id":revision_id}
    payload,error=_admin_tcp(request,payload,csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_UPDATE_DRAFT",payload)


@app.post("/api/admin/catalog-recipes")
def admin_save_recipe(request:Request,body:AdminRecipeSaveRequest):
    data=body.model_dump()
    data.pop("expected_version",None)
    if _unified_schema_mode():
        data["steps"]=[step.model_dump() for step in body.steps] if body.steps is not None else None
        if "source_url" not in body.model_fields_set:data.pop("source_url",None)
        if "tags" not in body.model_fields_set:data.pop("tags",None)
    else:
        data.pop("source_url",None)
        data.pop("tags",None)
        for key in ("servings","minutes_prep","minutes_cook","steps"):
            data.pop(key,None)
        data["ingredients"]=[{"ingredient_id":line["ingredient_id"],"quantity_raw":line["quantity_raw"],"requirement":"required"} for line in data["ingredients"]]
    payload,error=_admin_tcp(request,data,csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SAVE_RECIPE",payload)


@app.patch("/api/admin/catalog-recipes/{recipe_id}")
def admin_update_catalog_recipe(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**64),
                                body:AdminRecipeSaveRequest|None=None,revision_id:int=Query(ge=1,lt=2**64)):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","recipe fields are required"),status_code=422)
    data=body.model_dump()
    data.pop("idempotency_key",None)
    if _unified_schema_mode():
        data["steps"]=[step.model_dump() for step in body.steps] if body.steps is not None else None
        if "source_url" not in body.model_fields_set:data.pop("source_url",None)
        if "tags" not in body.model_fields_set:data.pop("tags",None)
    else:
        data.pop("source_url",None)
        data.pop("tags",None)
        for key in ("servings","minutes_prep","minutes_cook","steps"):
            data.pop(key,None)
        data["ingredients"]=[{"ingredient_id":line["ingredient_id"],"quantity_raw":line["quantity_raw"],"requirement":"required"} for line in data["ingredients"]]
    payload={**data,"recipe_id":recipe_id,"revision_id":revision_id}
    signed,error=_admin_tcp(request,payload,csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SAVE_RECIPE",signed)


@app.patch("/api/admin/catalog-recipes/{recipe_id}/state")
def admin_recipe_state(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**64),body:AdminRecipeStateRequest|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","recipe state is required"),status_code=422)
    payload,error=_admin_tcp(request,{"recipe_id":recipe_id,**body.model_dump()},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SET_RECIPE_LIFECYCLE",payload)


@app.delete("/api/admin/catalog-recipes/{recipe_id}/permanent")
def admin_recipe_delete_permanent(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**64)):
    payload,error=_admin_tcp(request,{"recipe_id":recipe_id},csrf=request.headers.get("x-csrf-token",""))
    if error:return error
    response=call_tcp(request,"ADMIN_DELETE_RECIPE_PERMANENT",payload)
    envelope=_tcp_envelope(response)
    if response.status_code==200 and envelope.get("ok") is True:
        data=envelope.get("data") or {}
        key=data.pop("previous_image_key",None)
        if key:
            from source.web.recipe_images import delete_image
            data["image_cleanup_pending"]=not delete_image(key)
        return JSONResponse(envelope,status_code=response.status_code,headers={"X-Request-ID":_request_id(request)})
    return response


def _tcp_envelope(response: JSONResponse):
    try:
        return json.loads(response.body)
    except (ValueError, TypeError):
        return {}


def _legacy_fallback_image(recipe_id: int):
    try:
        catalog=json.loads((BASE_DIR/"static"/"recipe-images.json").read_text(encoding="utf-8"))
        entry=catalog.get("recipes",{}).get(str(recipe_id),{})
        path=entry.get("image_path")
        if isinstance(path,str) and path.startswith("/static/images/recipes/") and ".." not in path:
            return path
    except (OSError,ValueError,AttributeError):
        pass
    return "/static/images/recipes/placeholder.svg"


@app.get("/api/admin/recipes/{recipe_id}/image")
def admin_recipe_image(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**33)):
    payload,error=_admin_tcp(request,{"recipe_id":recipe_id})
    if error:return error
    response=call_tcp(request,"ADMIN_GET_RECIPE_IMAGE",payload)
    envelope=_tcp_envelope(response)
    if response.status_code>=400 or envelope.get("ok") is not True:return response
    data=envelope.get("data") or {}
    image=data.get("image")
    data["image_url"]=(f"/api/admin/recipes/{recipe_id}/image/file?v={image['sha256']}" if image else
        (_legacy_fallback_image(recipe_id) if recipe_id<2**32 else "/static/images/recipes/placeholder.svg"))
    return JSONResponse(envelope,status_code=response.status_code,headers={"X-Request-ID":str(envelope.get("request_id",""))})


@app.get("/api/admin/recipes/{recipe_id}/image/file")
def admin_recipe_image_file(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**33)):
    from source.web.recipe_images import RecipeImageError,safe_image_path,storage_root
    from hashlib import sha256
    payload,error=_admin_tcp(request,{"recipe_id":recipe_id})
    if error:return error
    response=call_tcp(request,"ADMIN_GET_RECIPE_IMAGE",payload)
    envelope=_tcp_envelope(response);data=envelope.get("data") or {};image=data.get("image")
    if response.status_code>=400 or envelope.get("ok") is not True or not image:
        return JSONResponse(error_response(_request_id(request),"NOT_FOUND","Recipe image not found."),status_code=404)
    try:path=safe_image_path(storage_root(),image["storage_key"])
    except (RecipeImageError,KeyError):return JSONResponse(error_response(_request_id(request),"NOT_FOUND","Recipe image not found."),status_code=404)
    try:content=path.read_bytes()
    except OSError:return JSONResponse(error_response(_request_id(request),"NOT_FOUND","Recipe image not found."),status_code=404)
    if len(content)!=image["byte_size"] or sha256(content).hexdigest()!=image["sha256"]:
        return JSONResponse(error_response(_request_id(request),"NOT_FOUND","Recipe image integrity check failed."),status_code=404)
    return Response(content=content,media_type=image["media_type"],headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"})


@app.post("/api/admin/recipes/{recipe_id}/image")
async def admin_upload_recipe_image(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**33)):
    from source.web.recipe_images import MAX_UPLOAD_BYTES,RecipeImageError,delete_image,safe_image_path,storage_root,validate_image,write_image
    payload,error=_admin_tcp(request,{"recipe_id":recipe_id},csrf=request.headers.get("x-csrf-token",""))
    if error:return error
    declared=request.headers.get("content-type","").split(";",1)[0].strip().lower()
    if declared not in {"image/jpeg","image/png","image/webp"}:
        return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","Chỉ hỗ trợ ảnh JPG, PNG hoặc WebP."),status_code=422)
    chunks=bytearray()
    async for chunk in request.stream():
        if len(chunks)+len(chunk)>MAX_UPLOAD_BYTES:
            return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","Ảnh tải lên không được lớn hơn 5 MB."),status_code=413)
        chunks.extend(chunk)
    try:
        normalized,metadata=validate_image(bytes(chunks),declared)
        storage_key,path=write_image(normalized,str(metadata["extension"]))
    except RecipeImageError as exc:
        return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD",str(exc)),status_code=422)
    tcp_payload={**payload,"storage_key":storage_key,**{key:value for key,value in metadata.items() if key!="extension"}}
    response=call_tcp(request,"ADMIN_SET_RECIPE_IMAGE",tcp_payload)
    envelope=_tcp_envelope(response)
    if response.status_code>=400 or envelope.get("ok") is not True:
        # If a TCP timeout made the commit outcome ambiguous, query the authoritative row before cleanup.
        verified=False
        probe=call_tcp(request,"ADMIN_GET_RECIPE_IMAGE",payload)
        probe_envelope=_tcp_envelope(probe)
        if probe.status_code<400 and probe_envelope.get("ok") is True:
            current=(probe_envelope.get("data") or {}).get("image") or {}
            verified=current.get("storage_key")==storage_key
        if not verified:delete_image(storage_key)
        return response
    old_key=(envelope.get("data") or {}).get("previous_storage_key")
    if old_key and old_key!=storage_key:delete_image(old_key)
    return JSONResponse(envelope,status_code=response.status_code,headers={"X-Request-ID":str(envelope.get("request_id",""))})


@app.delete("/api/admin/recipes/{recipe_id}/image")
def admin_remove_recipe_image(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**33)):
    from source.web.recipe_images import delete_image
    payload,error=_admin_tcp(request,{"recipe_id":recipe_id},csrf=request.headers.get("x-csrf-token",""))
    response=error or call_tcp(request,"ADMIN_REMOVE_RECIPE_IMAGE",payload)
    envelope=_tcp_envelope(response)
    if response.status_code<400 and envelope.get("ok") is True:
        old_key=(envelope.get("data") or {}).get("previous_storage_key")
        if old_key:delete_image(old_key)
    return response


@app.post("/api/admin/reviews")
def admin_submit_review(request:Request,body:AdminReviewSubmission):
    payload,error=_admin_tcp(request,body.model_dump(),csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SUBMIT_REVIEW",payload)


@app.post("/api/admin/reviews/source")
def admin_review_source(request:Request,body:AdminSourceDecision):
    payload,error=_admin_tcp(request,body.model_dump(),csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_REVIEW_SOURCE",payload)


@app.post("/api/admin/reviews/approve")
def admin_approve_recipe(request:Request,body:AdminReviewAction):
    payload,error=_admin_tcp(request,body.model_dump(),csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_APPROVE_RECIPE",payload)


@app.post("/api/admin/reviews/reject")
def admin_reject_recipe(request:Request,body:AdminReviewAction):
    payload,error=_admin_tcp(request,body.model_dump(),csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_REJECT_RECIPE",payload)


@app.post("/api/admin/releases/publish")
def admin_publish_release(request:Request,body:AdminPublishAction):
    payload,error=_admin_tcp(request,body.model_dump(),csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_PUBLISH_RELEASE",payload)


@app.post("/api/admin/releases/unpublish")
def admin_unpublish_recipe(request:Request,body:AdminUnpublishAction):
    payload,error=_admin_tcp(request,body.model_dump(),csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_UNPUBLISH_RECIPE",payload)


@app.get("/recipes/{recipe_id}", response_class=HTMLResponse)
def recipe_page(request: Request, recipe_id: str):
    destinations = request.query_params.getlist("return_to")
    return_to = destinations[0] if len(destinations) == 1 and destinations[0] in {"/", "/meal-plan", "/meal-plan/v1"} else "/"
    from source.common.catalog_ids import valid_public_id
    valid_id = recipe_id.isascii() and recipe_id.isdecimal() and len(recipe_id) <= 10 and valid_public_id(int(recipe_id))
    return templates.TemplateResponse(request=request, name="detail.html", context={
        "page_title": "Chi tiết món ăn", "recipe_id": int(recipe_id) if valid_id else 0,
        "return_to": return_to, "active_tab":"meal" if return_to=="/meal-plan" else "explore",
        "account_target":"/account/profile" if _user_claims(request) else "/account/login?next=" + f"/recipes/{recipe_id}%23achievement-form",
        "user_authenticated":bool(_user_claims(request))}, status_code=200 if valid_id else 422)


@app.get("/api/ingredients")
def list_ingredients(request: Request, query: str = Query(default="", max_length=80), limit: int = Query(default=20, ge=1, le=250)):
    return call_tcp(request, "LIST_INGREDIENTS", {"query": query, "limit": limit})


@app.post("/api/recommend")
def recommend(request: Request, body: RecommendRequest):
    if any(item <= 0 for item in body.ingredient_ids + body.excluded_ids):
        return JSONResponse(error_response(_request_id(request), "INVALID_PAYLOAD", "Mã nguyên liệu phải là số dương."), status_code=422)
    if set(body.ingredient_ids) & set(body.excluded_ids):
        return JSONResponse(error_response(_request_id(request), "INVALID_PAYLOAD", "Nguyên liệu đã có không được đồng thời loại trừ."), status_code=422)
    return call_tcp(request, "RECOMMEND", body.model_dump(exclude_none=True))


@app.get("/api/recipes/{recipe_id}")
def recipe_detail(request: Request, recipe_id: int = FastAPIPath(ge=1)):
    if not valid_public_id(recipe_id):
        return JSONResponse(error_response(_request_id(request), "INVALID_PAYLOAD", "Mã công thức không hợp lệ."), status_code=422)
    return call_tcp(request, "GET_RECIPE", {"recipe_id": recipe_id})


@app.get("/api/recipes/{recipe_id}/image")
def public_recipe_image_metadata(request:Request,recipe_id:int=FastAPIPath(ge=1)):
    if not valid_public_id(recipe_id):
        return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","Mã món không hợp lệ."),status_code=422)
    response=call_tcp(request,"GET_RECIPE_IMAGE",{"recipe_id":recipe_id})
    envelope=_tcp_envelope(response)
    if response.status_code>=400 or envelope.get("ok") is not True:return response
    data=envelope.get("data") or {}
    image=(data.get("image") or {})
    data["image_url"]=f"/media/recipes/{recipe_id}?v={image.get('sha256','')}"
    return JSONResponse(envelope,status_code=response.status_code)


@app.get("/media/recipes/{recipe_id}")
def public_recipe_image_file(request:Request,recipe_id:int=FastAPIPath(ge=1)):
    from source.web.recipe_images import RecipeImageError,safe_image_path,storage_root
    from hashlib import sha256
    if not valid_public_id(recipe_id):
        return JSONResponse(error_response(_request_id(request),"NOT_FOUND","Recipe image not found."),status_code=404)
    response=call_tcp(request,"GET_RECIPE_IMAGE",{"recipe_id":recipe_id})
    envelope=_tcp_envelope(response)
    image=(envelope.get("data") or {}).get("image") if response.status_code<400 and envelope.get("ok") is True else None
    if not image:
        return JSONResponse(error_response(_request_id(request),"NOT_FOUND","Recipe image not found."),status_code=404)
    try:path=safe_image_path(storage_root(),image["storage_key"])
    except (RecipeImageError,KeyError):return JSONResponse(error_response(_request_id(request),"NOT_FOUND","Recipe image not found."),status_code=404)
    if not path.is_file():return JSONResponse(error_response(_request_id(request),"NOT_FOUND","Recipe image not found."),status_code=404)
    try:
        content=path.read_bytes()
    except OSError:
        return JSONResponse(error_response(_request_id(request),"NOT_FOUND","Recipe image not found."),status_code=404)
    if len(content)!=image["byte_size"] or sha256(content).hexdigest()!=image["sha256"]:
        return JSONResponse(error_response(_request_id(request),"NOT_FOUND","Recipe image integrity check failed."),status_code=404)
    return Response(content=content,media_type=image["media_type"],headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"})


@app.post("/api/search")
def search(request: Request, body: SearchRequest):
    if any(item <= 0 for item in body.ingredient_ids + body.excluded_ids) or set(body.ingredient_ids) & set(body.excluded_ids):
        return JSONResponse(error_response(_request_id(request), "INVALID_PAYLOAD", "Mã nguyên liệu không hợp lệ hoặc trùng với nhóm loại trừ."), status_code=422)
    return call_tcp(request, "SEARCH_RECIPES", body.model_dump(exclude_none=True))


@app.get("/api/health")
def health(request: Request):
    return call_tcp(request, "PING", {})


@app.get("/meal-plan", response_class=HTMLResponse)
@app.get("/meal-plan/v1", response_class=HTMLResponse)
def meal_plan_page(request: Request):
    # Local catalog version is only a cache hint; the gateway does not classify/select dishes.
    try:
        catalog = json.loads((BASE_DIR.parent.parent / "data/recipe_categories.json").read_text(encoding="utf-8"))
        version = catalog.get("classification_version")
        if not isinstance(version, str) or not 1 <= len(version) <= 80:
            version = ""
    except (OSError, ValueError, AttributeError):
        version = ""
    template = "meal_plan.html" if request.url.path == "/meal-plan/v1" else "meal_plan_v2.html"
    return templates.TemplateResponse(request=request, name=template, context={
        "page_title": "Mâm cơm hôm nay", "classification_version": version, "active_tab":"meal",
        "account_target":"/account/profile" if _user_claims(request) else "/account/login"})


@app.post("/api/meal-plan")
def generate_meal_plan(request: Request, body: MealPlanRequest):
    exclude = {"avoid_recipe_ids"} if not body.avoid_recipe_ids else set()
    return call_tcp(request, "GENERATE_MEAL_PLAN", body.model_dump(exclude_none=True, exclude=exclude))


@app.post("/api/meal-plan/v2")
def generate_meal_plan_v2(request: Request, body: MealPlanV2Request):
    return call_tcp(request, "GENERATE_MEAL_PLAN_V2", body.model_dump(exclude_none=True))


@app.get("/api/meal-plan/filters")
def meal_plan_filters(request: Request, layout_support: bool = Query(default=False)):
    return call_tcp(request, "GET_MEAL_PLAN_FILTERS", {"layout_support":True} if layout_support else {})


@app.post("/api/meal-plan/calculate")
def calculate_meal_plan(request: Request, body: CalculationRequest):
    return call_tcp(request, "CALCULATE_MEAL_PLAN", body.model_dump())
