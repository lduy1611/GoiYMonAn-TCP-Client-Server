"""Measure real TCP request handling at 1, 5, 10 and 20 clients.

The script starts the production MySQL-backed TCPServer and sends real socket
requests through TCPClient. It does not generate or estimate performance data.
"""
from __future__ import annotations

import argparse
import csv
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return round(ordered[index], 3)


def run_level(port: int, concurrency: int, dataset_version: str) -> dict[str, object]:
    def request_once(_: int) -> tuple[bool, float, str]:
        started = time.perf_counter()
        try:
            response = TCPClient(port=port).request(
                "RECOMMEND",
                {"ingredient_ids": [1, 2], "excluded_ids": [], "top_k": 5, "algorithm": "proposed"},
            )
            elapsed = (time.perf_counter() - started) * 1000
            if not response.get("ok"):
                return False, elapsed, str(response.get("error", {}).get("code", "UPSTREAM_ERROR"))
            return True, elapsed, ""
        except Exception as exc:  # noqa: BLE001 - benchmark records real failures
            return False, (time.perf_counter() - started) * 1000, type(exc).__name__

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        results = list(executor.map(request_once, range(concurrency)))
    total_ms = (time.perf_counter() - started) * 1000
    latencies = [elapsed for ok, elapsed, _ in results if ok]
    failures = [error for ok, _, error in results if not ok]
    successful = len(latencies)
    return {
        "dataset_version": dataset_version,
        "concurrency": concurrency,
        "requests": len(results),
        "successful": successful,
        "failed": len(failures),
        "status": "PASS" if successful == len(results) else "FAIL",
        "total_ms": round(total_ms, 3),
        "avg_ms": round(sum(latencies) / successful, 3) if latencies else "",
        "p50_ms": percentile(latencies, 0.50) if latencies else "",
        "p95_ms": percentile(latencies, 0.95) if latencies else "",
        "throughput_req_s": round(successful / (total_ms / 1000), 3) if total_ms else "",
        "errors": ";".join(failures),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="statics/results/benchmark_tcp.csv")
    parser.add_argument("--log", default="statics/results/benchmark_tcp.log")
    args = parser.parse_args()
    output = Path(args.output)
    log = Path(args.log)
    output.parent.mkdir(parents=True, exist_ok=True)
    log.parent.mkdir(parents=True, exist_ok=True)

    port = free_port()
    server = TCPServer("127.0.0.1", port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    rows: list[dict[str, object]] = []
    try:
        dataset_version = wait_until_ready(port)
        for concurrency in (1, 5, 10, 20):
            rows.append(run_level(port, concurrency, dataset_version))
    finally:
        server.shutdown()
        thread.join(timeout=3)

    fields = list(rows[0]) if rows else []
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with log.open("w", encoding="utf-8") as stream:
        stream.write(f"server=MySQL-backed TCPServer\nport={port}\n")
        for row in rows:
            stream.write(",".join(f"{key}={value}" for key, value in row.items()) + "\n")
    print(f"benchmark_csv={output}")
    print(f"benchmark_log={log}")
    print(f"levels={len(rows)}")
    print(f"pass_levels={sum(row['status'] == 'PASS' for row in rows)}")
    return 0 if all(row["status"] == "PASS" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
