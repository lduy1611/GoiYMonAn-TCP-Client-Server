from __future__ import annotations

import os
import json
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
    # Accepted only for compatibility with older Admin clients. Catalog saves
    # normalize every Admin-managed line to required before forwarding to TCP.
    requirement:Literal["required","optional","unknown"]="required"


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
    minutes:StrictInt=Field(ge=1,le=240)
    role:Literal["main","vegetable","soup"]
    ingredients:list[AdminIngredientLine]=Field(min_length=1,max_length=50)
    idempotency_key:StrictStr|None=Field(default=None,min_length=36,max_length=36,pattern=r"^[0-9a-fA-F-]{36}$")
    expected_version:StrictStr|None=Field(default=None,min_length=64,max_length=64,pattern=r"^[0-9a-f]{64}$")


class AdminRecipeStateRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    is_visible:StrictBool
    is_deleted:StrictBool


class AdminLegacyIngredientLine(BaseModel):
    model_config=ConfigDict(extra="forbid")
    ingredient_id:StrictInt=Field(gt=0,lt=2**32)
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
    if code=="ADMIN_IMAGE_CONFLICT":return 409
    if code=="USER_ACCOUNT_CONFLICT":return 409
    if code in {"USER_UNAUTHORIZED","USER_LOCKED"}:return 401
    if code=="USER_CSRF":return 403
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
    else:
        result.delete_cookie(ADMIN_COOKIE,path="/",secure=secure,httponly=True,samesite="strict")
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
    return templates.TemplateResponse(request=request, name="index.html", context={"page_title": "Hôm nay ăn gì?"})


@app.get("/account/login",response_class=HTMLResponse)
def user_login_page(request:Request):
    if _user_claims(request):
        return RedirectResponse("/",status_code=303)
    return templates.TemplateResponse(request=request,name="account_auth.html",
        context={"page_title":"Đăng nhập · Hôm nay ăn gì?","mode":"login"})


@app.get("/account/register",response_class=HTMLResponse)
def user_register_page(request:Request):
    if _user_claims(request):
        return RedirectResponse("/",status_code=303)
    return templates.TemplateResponse(request=request,name="account_auth.html",
        context={"page_title":"Tạo tài khoản · Hôm nay ăn gì?","mode":"register"})


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
    response=JSONResponse({**envelope,"data":{"authenticated":True,"username":data.get("username"),
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
    response.delete_cookie(ADMIN_COOKIE,path="/",secure=secure,httponly=True,samesite="strict")
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
    return templates.TemplateResponse(request=request,name="admin.html",context={"page_title":"Admin · Quản lý công thức"})


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
                  offset:int=Query(default=0,ge=0,le=10000),role:Literal["main","vegetable","soup"]|None=None,
                  visibility:Literal["visible","hidden","deleted"]|None=None,max_minutes:int|None=Query(default=None,ge=1,le=240)):
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


@app.patch("/api/admin/legacy-recipes/{recipe_id}/visibility")
def admin_set_legacy_recipe_visibility(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**32),body:AdminLegacyVisibility|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","visibility state is required"),status_code=422)
    payload,error=_admin_tcp(request,{"recipe_id":recipe_id,**body.model_dump()},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SET_LEGACY_RECIPE_VISIBILITY",payload)


@app.get("/api/admin/ingredients")
def admin_ingredients(request:Request,query:str=Query(default="",max_length=80),limit:int=Query(default=20,ge=1,le=50),
                      offset:int=Query(default=0,ge=0,le=1_000_000),active_only:bool=Query(default=False),
                      catalog:str=Query(default="shared",pattern="^(shared|v2)$")):
    payload,error=_admin_tcp(request,{"query":query,"limit":limit,"offset":offset,"active_only":active_only,"catalog":catalog})
    return error or call_tcp(request,"ADMIN_LIST_INGREDIENTS",payload)


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
    payload,error=_admin_tcp(request,body.model_dump(),csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_CREATE_INGREDIENT",payload)


@app.patch("/api/admin/ingredients/{ingredient_id}")
def admin_update_ingredient(request:Request,ingredient_id:int=FastAPIPath(ge=1,lt=2**64),body:AdminIngredientName|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","ingredient name is required"),status_code=422)
    payload,error=_admin_tcp(request,{"ingredient_id":ingredient_id,**body.model_dump()},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_UPDATE_INGREDIENT",payload)


@app.patch("/api/admin/ingredients/{ingredient_id}/active")
def admin_set_ingredient_active(request:Request,ingredient_id:int=FastAPIPath(ge=1,lt=2**64),body:AdminIngredientActive|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","ingredient state is required"),status_code=422)
    payload,error=_admin_tcp(request,{"ingredient_id":ingredient_id,**body.model_dump()},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SET_INGREDIENT_ACTIVE",payload)


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
    data["ingredients"]=[{**line,"requirement":"required"} for line in data["ingredients"]]
    payload,error=_admin_tcp(request,data,csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SAVE_RECIPE",payload)


@app.patch("/api/admin/catalog-recipes/{recipe_id}")
def admin_update_catalog_recipe(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**64),
                                body:AdminRecipeSaveRequest|None=None,revision_id:int=Query(ge=1,lt=2**64)):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","recipe fields are required"),status_code=422)
    data=body.model_dump()
    data.pop("idempotency_key",None)
    data["ingredients"]=[{**line,"requirement":"required"} for line in data["ingredients"]]
    payload={**data,"recipe_id":recipe_id,"revision_id":revision_id}
    signed,error=_admin_tcp(request,payload,csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SAVE_RECIPE",signed)


@app.patch("/api/admin/catalog-recipes/{recipe_id}/state")
def admin_recipe_state(request:Request,recipe_id:int=FastAPIPath(ge=1,lt=2**64),body:AdminRecipeStateRequest|None=None):
    if body is None:return JSONResponse(error_response(_request_id(request),"INVALID_PAYLOAD","recipe state is required"),status_code=422)
    payload,error=_admin_tcp(request,{"recipe_id":recipe_id,**body.model_dump()},csrf=request.headers.get("x-csrf-token",""))
    return error or call_tcp(request,"ADMIN_SET_RECIPE_LIFECYCLE",payload)


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
        "return_to": return_to}, status_code=200 if valid_id else 422)


@app.get("/api/ingredients")
def list_ingredients(request: Request, query: str = Query(default="", max_length=80), limit: int = Query(default=20, ge=1, le=50)):
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
        "page_title": "Mâm cơm hôm nay", "classification_version": version})


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
