import socket
import threading
import time
from pathlib import Path

from source.client.tcp_client import TCPClient
from source.database.seed import seed
from source.server.main import TCPServer


def test_multiple_clients(tmp_path: Path):
    db = tmp_path / "recipes.db"
    seed(db)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    server = TCPServer("127.0.0.1", port, db)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            response = TCPClient(port=port).request("PING", {})
            if response["ok"]:
                break
        except Exception:
            time.sleep(0.01)
    results = []

    def worker():
        results.append(TCPClient(port=port).request("RECOMMEND", {"ingredient_ids": [1, 2]}))

    workers = [threading.Thread(target=worker) for _ in range(10)]
    for item in workers: item.start()
    for item in workers: item.join()
    server.shutdown()
    assert len(results) == 10
    assert all(item["ok"] and item["request_id"] for item in results)
