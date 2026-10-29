"""Length-prefixed JSON protocol shared by the TCP client and server."""
from __future__ import annotations

import json
import socket
import struct
import time
import uuid
from typing import Any

MAX_FRAME_SIZE = 65536
PROTOCOL_VERSION = 1
READ_DEADLINE = 5.0
CLIENT_TOTAL_BUDGET = 7.0
SUPPORTED_OPS = {"PING", "LIST_INGREDIENTS", "GET_RECIPE", "RECOMMEND"}


class ProtocolError(Exception):
    def __init__(self, code: str, message: str, request_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.request_id = request_id


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _depth(value: Any, current: int = 0) -> int:
    if current > 16:
        return current
    if isinstance(value, dict):
        return max((_depth(v, current + 1) for v in value.values()), default=current)
    if isinstance(value, list):
        return max((_depth(v, current + 1) for v in value), default=current)
    return current


def encode_body(value: dict[str, Any]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError("MALFORMED_FRAME", "cannot serialize JSON") from exc


def encode_frame(value: dict[str, Any]) -> bytes:
    body = encode_body(value)
    if not 1 <= len(body) <= MAX_FRAME_SIZE:
        raise ProtocolError("FRAME_LENGTH", "frame body must be 1..65536 bytes")
    return struct.pack("!I", len(body)) + body


def recv_exact(sock: socket.socket, size: int, deadline: float) -> bytes | None:
    data = bytearray()
    while len(data) < size:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProtocolError("TIMEOUT", "frame read deadline exceeded")
        sock.settimeout(remaining)
        try:
            chunk = sock.recv(size - len(data))
        except socket.timeout as exc:
            raise ProtocolError("TIMEOUT", "frame read deadline exceeded") from exc
        if not chunk:
            if not data:
                return None
            raise ProtocolError("TRUNCATED_FRAME", "connection closed during frame")
        data.extend(chunk)
    return bytes(data)


def recv_frame(sock: socket.socket, timeout: float = READ_DEADLINE) -> tuple[dict[str, Any] | None, int]:
    deadline = time.monotonic() + timeout
    header = recv_exact(sock, 4, deadline)
    if header is None:
        return None, 0
    length = struct.unpack("!I", header)[0]
    if not 1 <= length <= MAX_FRAME_SIZE:
        raise ProtocolError("FRAME_LENGTH", "frame length outside 1..65536")
    body = recv_exact(sock, length, deadline)
    assert body is not None
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_constant)
        if not isinstance(value, dict) or _depth(value) > 16:
            raise ValueError("JSON top-level must be object and nesting <= 16")
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProtocolError("MALFORMED_FRAME", "invalid UTF-8 or JSON") from exc
    return value, 4 + length


def valid_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value.lower()
    except ValueError:
        return False


def error_response(request_id: str | None, code: str, message: str) -> dict[str, Any]:
    return {"version": PROTOCOL_VERSION, "request_id": request_id, "ok": False, "data": None, "error": {"code": code, "message": message}}


def success_response(request_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"version": PROTOCOL_VERSION, "request_id": request_id, "ok": True, "data": data, "error": None}


def validate_request(value: Any) -> tuple[str, str, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != {"version", "request_id", "op", "payload"}:
        raise ProtocolError("INVALID_REQUEST", "request envelope must have exactly four fields")
    request_id = value.get("request_id")
    safe_id = request_id if valid_uuid(request_id) else None
    if not isinstance(value["version"], int) or isinstance(value["version"], bool) or value["version"] != 1:
        raise ProtocolError("UNSUPPORTED_VERSION", "unsupported protocol version", safe_id)
    if not valid_uuid(request_id):
        raise ProtocolError("INVALID_REQUEST", "request_id must be a UUID", None)
    op = value["op"]
    if not isinstance(op, str) or op not in SUPPORTED_OPS:
        raise ProtocolError("UNKNOWN_OPERATION", "unsupported operation", request_id)
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise ProtocolError("INVALID_PAYLOAD", "payload must be an object", request_id)
    return request_id, op, payload
