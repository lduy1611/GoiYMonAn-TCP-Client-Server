from __future__ import annotations

import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import mysql.connector
import pytest
from fastapi.testclient import TestClient

from source.client.tcp_client import TCPClient
from source.server.main import TCPServer
from source.server.repository import MySQLRepository, mysql_config_from_env
from source.web.main import app


@pytest.fixture(scope="module")
def mysql_server():
    try:
        config = mysql_config_from_env()
        repository = MySQLRepository(config)
    except (RuntimeError, mysql.connector.Error) as exc:
        pytest.skip(f"MySQL integration not run: {exc}")
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    server = TCPServer("127.0.0.1", port, repository=repository)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            TCPClient(port=port).request("PING", {})
            break
        except Exception:
            time.sleep(0.01)
    else:
        server.shutdown()
        pytest.fail("MySQL TCP server did not start")
    old_port = os.environ.get("TCP_PORT")
    os.environ["TCP_PORT"] = str(port)
    yield server, thread, port
    if old_port is None:
        os.environ.pop("TCP_PORT", None)
    else:
        os.environ["TCP_PORT"] = old_port
    server.shutdown()
    thread.join(timeout=2)


def test_mysql_tcp_operations(mysql_server):
    _, _, port = mysql_server
    client = TCPClient(port=port)
    assert client.request("PING", {})["ok"]
    assert client.request("LIST_INGREDIENTS", {"query": "cà", "limit": 20})["data"]["items"]
    assert client.request("GET_RECIPE", {"recipe_id": 1})["data"]["id"] == 1
    recommendation = client.request("RECOMMEND", {"ingredient_ids": [1, 2], "top_k": 5})
    assert recommendation["data"]["algorithm"] == "proposed"
    assert recommendation["data"]["items"]


def test_mysql_multiclient_and_http_outage(mysql_server):
    server, thread, port = mysql_server
    with ThreadPoolExecutor(max_workers=10) as executor:
        responses = list(executor.map(lambda _: TCPClient(port=port).request("PING", {}), range(10)))
    assert len(responses) == 10
    assert all(response["ok"] for response in responses)
    os.environ["TCP_HOST"] = "127.0.0.1"
    os.environ["TCP_PORT"] = str(port)
    server.shutdown()
    thread.join(timeout=2)
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
