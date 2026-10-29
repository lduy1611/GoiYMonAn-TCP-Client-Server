from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

from source.client.tcp_client import TCPClient, TCPClientError
from source.common.protocol import encode_frame
from source.database.seed import seed
from source.server.main import TCPServer


def running_server(tmp_path: Path):
    db = tmp_path / "recipes.db"
    seed(db)
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server = TCPServer("127.0.0.1", port, db)
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


def test_timeout_closes_slow_client_and_server_survives(tmp_path: Path):
    server, port, thread = running_server(tmp_path)
    client = socket.create_connection(("127.0.0.1", port), timeout=1)
    started = time.monotonic()
    try:
        client.sendall(b"\x00")
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
