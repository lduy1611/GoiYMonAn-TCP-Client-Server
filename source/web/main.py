from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Path as FastAPIPath, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from source.client.tcp_client import TCPClient, TCPClientError
from source.common.protocol import error_response

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app = FastAPI(title="Hôm nay ăn gì?", version="phase-2")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


class RecommendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ingredient_ids: list[StrictInt] = Field(min_length=1, max_length=30)
    excluded_ids: list[StrictInt] = Field(default_factory=list, max_length=30)
    max_minutes: StrictInt | None = Field(default=None, ge=1, le=240)
    top_k: StrictInt = Field(default=5, ge=1, le=20)
    algorithm: Literal["baseline", "proposed"] = "proposed"


def http_status_for_error(code: str) -> int:
    if code in {"INVALID_REQUEST", "INVALID_PAYLOAD"}:
        return 422
    if code == "NOT_FOUND":
        return 404
    if code == "TIMEOUT":
        return 504
    if code in {"UPSTREAM_PROTOCOL", "UNKNOWN_OPERATION", "UNSUPPORTED_VERSION", "MALFORMED_FRAME", "FRAME_LENGTH"}:
        return 502
    return 503


def _request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    if not value:
        value = str(uuid.uuid4())
        request.state.request_id = value
    return value


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, _exc: RequestValidationError):
    request_id = _request_id(request)
    return JSONResponse(error_response(request_id, "INVALID_PAYLOAD", "Dữ liệu gửi lên không hợp lệ."), status_code=422, headers={"X-Request-ID": request_id})


def call_tcp(request: Request, op: str, payload: dict[str, Any]) -> JSONResponse:
    request_id = _request_id(request)
    try:
        response = TCPClient(os.getenv("TCP_HOST", "127.0.0.1"), int(os.getenv("TCP_PORT", "9000"))).request(op, payload, request_id=request_id)
    except TCPClientError as exc:
        code = exc.args[0] if exc.args else "UPSTREAM_UNAVAILABLE"
        response = error_response(request_id, code, "Không thể kết nối tới TCP Server.")
        return JSONResponse(response, status_code=http_status_for_error(code), headers={"X-Request-ID": request_id})
    if not isinstance(response, dict) or response.get("request_id") != request_id or response.get("version") != 1 or not isinstance(response.get("ok"), bool):
        response = error_response(request_id, "UPSTREAM_PROTOCOL", "TCP Server trả về response không hợp lệ.")
        return JSONResponse(response, status_code=502, headers={"X-Request-ID": request_id})
    if response["ok"] is False:
        error = response.get("error") or {}
        code = error.get("code", "INTERNAL_ERROR") if isinstance(error, dict) else "INTERNAL_ERROR"
        return JSONResponse(response, status_code=http_status_for_error(code), headers={"X-Request-ID": request_id})
    if response.get("data") is None or response.get("error") is not None:
        response = error_response(request_id, "UPSTREAM_PROTOCOL", "TCP Server trả về response không hợp lệ.")
        return JSONResponse(response, status_code=502, headers={"X-Request-ID": request_id})
    return JSONResponse(response, status_code=200, headers={"X-Request-ID": request_id})


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"page_title": "Hôm nay ăn gì?"})


@app.get("/recipes/{recipe_id}", response_class=HTMLResponse)
def recipe_page(request: Request, recipe_id: int = FastAPIPath(ge=1)):
    return templates.TemplateResponse(request=request, name="detail.html", context={"page_title": "Chi tiết món ăn", "recipe_id": recipe_id})


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
    return call_tcp(request, "GET_RECIPE", {"recipe_id": recipe_id})


@app.get("/api/health")
def health(request: Request):
    return call_tcp(request, "PING", {})
