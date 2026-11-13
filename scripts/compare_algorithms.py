"""Compare B0 baseline and P1 proposed using real TCP responses."""
from __future__ import annotations

import argparse
import csv
import json
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source.client.tcp_client import TCPClient
from source.server.main import TCPServer


def free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def wait_until_ready(port: int) -> str:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            response = TCPClient(port=port).request("PING", {})
            if response.get("ok"):
                return str(response.get("data", {}).get("dataset_version", ""))
        except Exception:
            time.sleep(0.02)
    raise RuntimeError("TCP Server did not become ready")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="statics/results/algorithm_comparison.csv")
    parser.add_argument("--log", default="statics/results/algorithm_comparison.log")
    args = parser.parse_args()
    output = Path(args.output)
    log = Path(args.log)
    output.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)

    scenarios = (("basic", [1, 2]), ("soup", [1, 2, 3]), ("meat", [4, 7]))
    port = free_port()
    server = TCPServer("127.0.0.1", port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    rows: list[dict[str, object]] = []
    try:
        dataset_version = wait_until_ready(port)
        for scenario, ingredient_ids in scenarios:
            for algorithm in ("baseline", "proposed"):
                started = time.perf_counter()
                response = TCPClient(port=port).request(
                    "RECOMMEND",
                    {"ingredient_ids": ingredient_ids, "excluded_ids": [], "top_k": 5, "algorithm": algorithm},
                )
                elapsed = (time.perf_counter() - started) * 1000
                items = response.get("data", {}).get("items", []) if response.get("ok") else []
                rows.append({
                    "dataset_version": dataset_version,
                    "scenario": scenario,
                    "ingredient_ids": json.dumps(ingredient_ids, ensure_ascii=False),
                    "algorithm": algorithm,
                    "status": "PASS" if response.get("ok") else "FAIL",
                    "item_count": len(items),
                    "recipe_ids": json.dumps([item.get("recipe_id") for item in items]),
                    "scores": json.dumps([item.get("score") for item in items]),
                    "elapsed_ms": round(elapsed, 3),
                    "error_code": response.get("error", {}).get("code", "") if not response.get("ok") else "",
                })
    finally:
        server.shutdown()
        thread.join(timeout=3)

    fields = list(rows[0]) if rows else []
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with log.open("w", encoding="utf-8") as stream:
        stream.write(f"server=MySQL-backed TCPServer\nport={port}\nrows={len(rows)}\n")
        for row in rows:
            stream.write(",".join(f"{key}={value}" for key, value in row.items()) + "\n")
    print(f"comparison_csv={output}")
    print(f"comparison_log={log}")
    print(f"pass_rows={sum(row['status'] == 'PASS' for row in rows)}")
    return 0 if rows and all(row["status"] == "PASS" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
