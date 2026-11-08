from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

from source.client.tcp_client import TCPClient, TCPClientError
from source.common.protocol import ProtocolError, encode_frame, recv_frame
from source.database.seed import seed
from source.server.main import TCPServer


def running_server(tmp_path: Path, max_connections: int = 32):
    db = tmp_path / "recipes.db"
    seed(db)
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server = TCPServer("127.0.0.1", port, db, max_connections=max_connections)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            if TCPClient(port=port).request("PING", {})["ok"]:
                return server, port, thread
        except Exception:
            time.sleep(0.01)
    server.shutdown()
    pytest.fail("TCP server did not start")


@pytest.mark.parametrize("wire", [b"\x00", b"\x00\x00\x00\x05", b"\x00\x00\x00\x05{"])
def test_timeout_closes_slow_client_and_server_survives(tmp_path: Path, wire):
    server, port, thread = running_server(tmp_path)
    client = socket.create_connection(("127.0.0.1", port), timeout=1)
    started = time.monotonic()
    try:
        client.sendall(wire)
        assert TCPClient(port=port).request("PING", {})["ok"] is True
        client.settimeout(7)
        assert client.recv(1) == b""
        assert 4.5 <= time.monotonic() - started < 7
        assert TCPClient(port=port).request("PING", {})["ok"]
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)


def test_disconnect_before_response_does_not_break_next_client(tmp_path: Path):
    server, port, thread = running_server(tmp_path)
    client = socket.create_connection(("127.0.0.1", port), timeout=1)
    client.sendall(encode_frame({"version": 1, "request_id": "4a7f6d4a-f3be-4fdb-b8a8-4d1ec2c32d10", "op": "RECOMMEND", "payload": {"ingredient_ids": [1, 2]}}))
    client.close()
    try:
        assert TCPClient(port=port).request("PING", {})["ok"]
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_malformed_json_is_closed_and_server_survives(tmp_path: Path):
    server, port, thread = running_server(tmp_path)
    client = socket.create_connection(("127.0.0.1", port), timeout=1)
    malformed = b"{\"version\":1,\"duplicate\":1,\"duplicate\":2}"
    client.sendall(len(malformed).to_bytes(4, "big") + malformed)
    client.settimeout(2)
    try:
        assert client.recv(1) == b""
        assert TCPClient(port=port).request("PING", {})["ok"]
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)


def test_client_rejects_response_with_wrong_request_id():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]

    def fake_upstream():
        connection, _ = listener.accept()
        with connection:
            request, _ = _read_frame(connection)
            wrong = {"version": 1, "request_id": "4a7f6d4a-f3be-4fdb-b8a8-4d1ec2c32d10", "ok": True, "data": {"status": "ok"}, "error": None}
            connection.sendall(encode_frame(wrong))
            assert request["op"] == "PING"
        listener.close()

    thread = threading.Thread(target=fake_upstream, daemon=True)
    thread.start()
    with pytest.raises(TCPClientError, match="UPSTREAM_PROTOCOL"):
        TCPClient(port=port).request("PING", {})
    thread.join(timeout=2)


def _read_frame(connection: socket.socket):
    header = connection.recv(4)
    length = int.from_bytes(header, "big")
    body = bytearray()
    while len(body) < length:
        body.extend(connection.recv(length - len(body)))
    return json.loads(body), 4 + length


def test_missing_recipe_returns_error_and_keeps_connection(tmp_path: Path):
    server, port, thread = running_server(tmp_path)
    client = TCPClient(port=port, persistent=True)
    request_id = "4a7f6d4a-f3be-4fdb-b8a8-4d1ec2c32d10"
    try:
        response = client.request("GET_RECIPE", {"recipe_id": 999999}, request_id=request_id)
        assert response == {"version": 1, "request_id": request_id, "ok": False, "data": None,
                            "error": {"code": "NOT_FOUND", "message": "recipe not found"}}
        original_socket = client.sock
        assert client.request("GET_RECIPE", {"recipe_id": 1})["data"]["id"] == 1
        assert client.request("PING", {})["ok"] is True
        assert client.sock is original_socket
    finally:
        client.close()
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.parametrize("wire", [b"", b"\x00", b"\x00\x00\x00\x05", b"\x00\x00\x00\x05{"])
def test_eof_or_truncated_request_releases_handler(tmp_path: Path, wire):
    server, port, thread = running_server(tmp_path)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
            if wire:
                client.sendall(wire)
            client.shutdown(socket.SHUT_WR)
            assert client.recv(1) == b""
        assert TCPClient(port=port).request("PING", {})["ok"] is True
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.parametrize("code", ["UNKNOWN_OPERATION", "INVALID_PAYLOAD", "INVALID_REQUEST", "UNSUPPORTED_VERSION", "NOT_FOUND",
                                  "ADMIN_UNAUTHORIZED", "ADMIN_WRITE_DENIED", "ADMIN_DRAFT_CONFLICT", "ADMIN_RECIPE_CONFLICT",
                                  "ADMIN_WRITE_UNAVAILABLE", "ADMIN_SCHEMA_UNAVAILABLE"])
@pytest.mark.parametrize("send_error", [ConnectionResetError, BrokenPipeError])
def test_disconnect_while_sending_error_releases_slot(monkeypatch, code, send_error):
    # Deterministic send failure: an OS close/reset is otherwise timing dependent.
    from unittest.mock import MagicMock
    import source.server.main as server_module

    server = TCPServer(repository=object(), max_connections=1)
    request_id = "4a7f6d4a-f3be-4fdb-b8a8-4d1ec2c32d10"
    def reject(*_args):
        raise ProtocolError(code, "rejected", request_id)
    monkeypatch.setattr(server_module, "recv_frame", lambda _client: ({}, 4))
    monkeypatch.setattr(server_module, "dispatch", reject)
    client = MagicMock()
    client.sendall.side_effect = send_error("peer disconnected")
    assert server.slots.acquire(blocking=False)
    server._handle(client, None)
    assert server.slots.acquire(blocking=False)
    server.slots.release()
    client.sendall.assert_called_once()


@pytest.mark.parametrize("wire,expected", [
    (b"", "UPSTREAM_DISCONNECTED"),
    (b"\x00", "TRUNCATED_FRAME"),
    (b"\x00\x00\x00\x05", "TRUNCATED_FRAME"),
    (b"\x00\x00\x00\x05{", "TRUNCATED_FRAME"),
    (encode_frame({"request_id": "wrong"}), "UPSTREAM_PROTOCOL"),
])
def test_persistent_client_discards_broken_socket_and_reconnects(monkeypatch, wire, expected):
    first, upstream = socket.socketpair()
    second, recovered_upstream = socket.socketpair()
    client = TCPClient(persistent=True)
    request_id = "4a7f6d4a-f3be-4fdb-b8a8-4d1ec2c32d10"
    sockets = iter((first, second))
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: next(sockets))
    try:
        if wire:
            upstream.sendall(wire)
        upstream.shutdown(socket.SHUT_WR)
        with pytest.raises(TCPClientError, match=expected):
            client.request("PING", {}, request_id=request_id)
        assert client.sock is None
        assert first.fileno() == -1
        recovered_upstream.sendall(encode_frame({"version": 1, "request_id": request_id,
                                               "ok": True, "data": {"status": "ok"}, "error": None}))
        assert client.request("PING", {}, request_id=request_id)["ok"] is True
    finally:
        client.close()
        first.close()
        second.close()
        upstream.close()
        recovered_upstream.close()


def test_server_admission_backpressure_does_not_drop_second_request(monkeypatch, tmp_path):
    import source.server.main as server_module

    entered = threading.Event()
    release = threading.Event()
    original_dispatch = server_module.dispatch

    def slow_dispatch(repository, request):
        if request.get("op") == "SLOW_TEST_ONLY":
            entered.set()
            assert release.wait(2)
        return original_dispatch(repository, request)

    monkeypatch.setattr(server_module, "dispatch", slow_dispatch)
    monkeypatch.setattr(server_module, "LOG_PATH", tmp_path / "TEST_ONLY-admission.jsonl")
    server, port, thread = running_server(tmp_path, max_connections=1)
    first_result = []
    second_result = []
    first = threading.Thread(target=lambda: first_result.append(TCPClient(port=port).request("SLOW_TEST_ONLY", {})))
    second = threading.Thread(target=lambda: second_result.append(TCPClient(port=port).request("PING", {})))
    try:
        first.start()
        assert entered.wait(1)
        second.start()
        time.sleep(0.15)
        assert second.is_alive()  # queued; never accepted then silently closed
        release.set()
        first.join(2)
        second.join(2)
        assert first_result[0]["error"]["code"] == "UNKNOWN_OPERATION"
        assert second_result[0]["ok"] is True
        rows = [json.loads(line) for line in (tmp_path / "TEST_ONLY-admission.jsonl").read_text(encoding="utf-8").splitlines()]
        assert any(row["op"] == "PING" and row["admission_wait_ms"] > 0 for row in rows)
    finally:
        release.set()
        server.shutdown()
        thread.join(timeout=2)


def test_admin_recipe_conflict_is_returned_as_framed_response(monkeypatch, tmp_path):
    import source.server.main as server_module

    monkeypatch.setattr(server_module, "LOG_PATH", tmp_path / "TEST_ONLY-conflict.jsonl")

    original_dispatch = server_module.dispatch

    def conflict(repository, request):
        if request.get("op") == "ADMIN_SAVE_RECIPE":
            raise ProtocolError("ADMIN_RECIPE_CONFLICT", "TEST_ONLY recipe conflict", request["request_id"])
        return original_dispatch(repository, request)

    monkeypatch.setattr(server_module, "dispatch", conflict)
    server, port, thread = running_server(tmp_path)
    try:
        result = TCPClient(port=port).request("ADMIN_SAVE_RECIPE", {"admin_token": "TEST_ONLY"})
        assert result["ok"] is False
        assert result["error"]["code"] == "ADMIN_RECIPE_CONFLICT"
        assert TCPClient(port=port).request("PING", {})["ok"] is True
        rows = [json.loads(line) for line in (tmp_path / "TEST_ONLY-conflict.jsonl").read_text(encoding="utf-8").splitlines()]
        sent = next(row for row in rows if row["error_code"] == "ADMIN_RECIPE_CONFLICT" and row["outcome"] == "error_response_sent")
        assert sent["op"] == "ADMIN_SAVE_RECIPE" and sent["bytes_out"] > 0
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.mark.parametrize("failure,expected", [
    (ProtocolError("TIMEOUT", "frame read deadline exceeded"), "TIMEOUT"),
    (ConnectionResetError("peer reset"), "UPSTREAM_DISCONNECTED"),
])
def test_persistent_client_closes_socket_on_timeout_or_reset(monkeypatch, failure, expected):
    import source.client.tcp_client as client_module

    local, upstream = socket.socketpair()
    client = TCPClient(persistent=True)
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: local)
    def fail_receive(*_args, **_kwargs):
        raise failure
    monkeypatch.setattr(client_module, "recv_frame", fail_receive)
    try:
        with pytest.raises(TCPClientError, match=expected):
            client.request("PING", {})
        assert client.sock is None
        assert local.fileno() == -1
    finally:
        client.close()
        local.close()
        upstream.close()


def test_tcp_client_reports_connect_refused_as_unavailable(monkeypatch):
    def refused(*_args, **_kwargs):
        raise ConnectionRefusedError(10061, "TEST_ONLY refused")

    monkeypatch.setattr(socket, "create_connection", refused)
    with pytest.raises(TCPClientError) as caught:
        TCPClient(port=1).request("PING", {})
    assert caught.value.code == "UPSTREAM_UNAVAILABLE"
    assert caught.value.phase == "connect"
    assert caught.value.os_error == 10061
