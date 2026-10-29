"""Run the TEST_PLAN E2 TCP and HTTP benchmark with raw per-request evidence."""
from __future__ import annotations

import argparse
import csv
import http.client
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from source.common.protocol import encode_frame, recv_frame
from source.server.main import TCPServer


CONCURRENCIES = (1, 5, 10, 20)
RUNS = (1, 2, 3)
WARMUP_REQUESTS = 5
MEASURE_REQUESTS = 30
REQUEST_PAYLOAD = {"ingredient_ids": [1, 2], "excluded_ids": [], "top_k": 5, "algorithm": "proposed"}
RAW_FIELDS = (
    "protocol", "run_id", "dataset_version", "worker", "phase", "sequence", "request_id", "response_request_id",
    "scenario", "algorithm", "concurrency", "connection_mode", "elapsed_ms", "connect_ms",
    "status", "error_code", "bytes_in", "bytes_out", "http_status",
)


def free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def percentile(values: list[float], fraction: float) -> float | str:
    if not values:
        return ""
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) * fraction + 0.999999999) - 1)))
    return round(ordered[index], 3)


def make_base_row(protocol: str, run_id: str, dataset_version: str, worker: int, phase: str, sequence: int, concurrency: int) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    return {
        "protocol": protocol,
        "run_id": run_id,
        "dataset_version": dataset_version,
        "worker": worker,
        "phase": phase,
        "sequence": sequence,
        "request_id": request_id,
        "response_request_id": "",
        "scenario": "RECOMMEND",
        "algorithm": "proposed",
        "concurrency": concurrency,
        "connection_mode": "new_per_request",
        "elapsed_ms": "",
        "connect_ms": "",
        "status": "exception",
        "error_code": "",
        "bytes_in": "",
        "bytes_out": "",
        "http_status": "",
    }


def tcp_request(port: int, row: dict[str, Any]) -> dict[str, Any]:
    request = {"version": 1, "request_id": row["request_id"], "op": "RECOMMEND", "payload": REQUEST_PAYLOAD}
    frame = encode_frame(request)
    started = time.perf_counter_ns()
    sock: socket.socket | None = None
    try:
        connect_started = time.perf_counter_ns()
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        row["connect_ms"] = round((time.perf_counter_ns() - connect_started) / 1_000_000, 3)
        sock.settimeout(10)
        sock.sendall(frame)
        response, bytes_out = recv_frame(sock, timeout=10)
        row["bytes_in"] = len(frame)
        row["bytes_out"] = bytes_out
        if response is None:
            row["error_code"] = "UPSTREAM_EOF"
        elif response.get("request_id") != row["request_id"]:
            row["response_request_id"] = response.get("request_id", "")
            row["status"] = "response_error"
            row["error_code"] = "UPSTREAM_PROTOCOL"
        elif response.get("ok") is True:
            row["status"] = "success"
        else:
            row["status"] = "response_error"
            row["error_code"] = str((response.get("error") or {}).get("code", "UPSTREAM_ERROR"))
    except Exception as exc:  # noqa: BLE001 - raw benchmark must retain failures
        row["error_code"] = type(exc).__name__
        row["bytes_in"] = len(frame)
    finally:
        if sock is not None:
            sock.close()
        row["elapsed_ms"] = round((time.perf_counter_ns() - started) / 1_000_000, 3)
    return row


def http_request(port: int, row: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(REQUEST_PAYLOAD, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    started = time.perf_counter_ns()
    connection: http.client.HTTPConnection | None = None
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        connect_started = time.perf_counter_ns()
        connection.connect()
        row["connect_ms"] = round((time.perf_counter_ns() - connect_started) / 1_000_000, 3)
        connection.request("POST", "/api/recommend", body=body, headers={"Content-Type": "application/json", "X-Request-ID": row["request_id"]})
        response = connection.getresponse()
        response_body = response.read()
        row["http_status"] = response.status
        row["bytes_in"] = len(body)
        row["bytes_out"] = len(response_body)
        try:
            decoded = json.loads(response_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = {}
        row["response_request_id"] = decoded.get("request_id", "") if isinstance(decoded, dict) else ""
        if response.status == 200 and isinstance(decoded, dict) and decoded.get("ok") is True:
            row["status"] = "success"
        else:
            row["status"] = "response_error"
            row["error_code"] = str((decoded.get("error") or {}).get("code", f"HTTP_{response.status}"))
    except Exception as exc:  # noqa: BLE001 - raw benchmark must retain failures
        row["error_code"] = type(exc).__name__
        row["bytes_in"] = len(body)
    finally:
        if connection is not None:
            connection.close()
        row["elapsed_ms"] = round((time.perf_counter_ns() - started) / 1_000_000, 3)
    return row


def run_protocol(protocol: str, port: int, dataset_version: str, concurrency: int, run_number: int, request_fn: Callable[[int, dict[str, Any]], dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    run_id = f"{protocol.lower()}-c{concurrency}-r{run_number}"
    barrier = threading.Barrier(concurrency)

    def worker(worker_id: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for sequence in range(1, WARMUP_REQUESTS + 1):
            row = make_base_row(protocol, run_id, dataset_version, worker_id, "warmup", sequence, concurrency)
            rows.append(request_fn(port, row))
        barrier.wait(timeout=30)
        for sequence in range(1, MEASURE_REQUESTS + 1):
            row = make_base_row(protocol, run_id, dataset_version, worker_id, "measure", sequence, concurrency)
            rows.append(request_fn(port, row))
        return rows

    started = time.perf_counter_ns()
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        grouped = list(executor.map(worker, range(1, concurrency + 1)))
    wall_seconds = (time.perf_counter_ns() - started) / 1_000_000_000
    return [row for group in grouped for row in group], wall_seconds


def wait_for_tcp(port: int) -> str:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=1)
            request_id = str(uuid.uuid4())
            frame = encode_frame({"version": 1, "request_id": request_id, "op": "PING", "payload": {}})
            sock.sendall(frame)
            response, _ = recv_frame(sock, timeout=2)
            sock.close()
            if response and response.get("ok"):
                return str(response["data"]["dataset_version"])
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("TCP Server did not become ready")


def start_http(port: int, tcp_port: int, log_path: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["TCP_HOST"] = "127.0.0.1"
    env["TCP_PORT"] = str(tcp_port)
    stream = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "source.web.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=stream,
        stderr=subprocess.STDOUT,
        text=True,
    )
    setattr(process, "_benchmark_stream", stream)
    return process


def wait_for_http(port: int, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("FastAPI/Uvicorn process exited before readiness")
        try:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
            connection.request("GET", "/api/health")
            response = connection.getresponse()
            response.read()
            connection.close()
            if response.status == 200:
                return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("FastAPI did not become ready")


def summarize(rows: list[dict[str, Any]], wall_seconds: float) -> dict[str, Any]:
    measured = [row for row in rows if row["phase"] == "measure"]
    successful = [row for row in measured if row["status"] == "success"]
    latencies = [float(row["elapsed_ms"]) for row in successful]
    attempted = len(measured)
    success_count = len(successful)
    failed = attempted - success_count
    return {
        "protocol": rows[0]["protocol"],
        "run_id": rows[0]["run_id"],
        "dataset_version": rows[0]["dataset_version"],
        "concurrency": rows[0]["concurrency"],
        "warmup_requests_per_worker": WARMUP_REQUESTS,
        "measure_requests_per_worker": MEASURE_REQUESTS,
        "attempted": attempted,
        "successful": success_count,
        "failed": failed,
        "error_rate": round(failed / attempted, 6) if attempted else "",
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "throughput_req_s": round(success_count / wall_seconds, 3) if wall_seconds else "",
        "wall_s": round(wall_seconds, 6),
        "status": "PASS" if failed == 0 and attempted == rows[0]["concurrency"] * MEASURE_REQUESTS else "FAIL",
    }


def load_identity(root: Path) -> tuple[str, str]:
    report = json.loads((root / "statics/results/phase4_dataset_audit.json").read_text(encoding="utf-8"))
    return str(report["dataset_hash_sha256"]), str(report["code_hash_sha256"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="statics/results")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output_dir = root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = output_dir / f"e2_raw_{stamp}.csv"
    summary_path = output_dir / f"e2_summary_{stamp}.csv"
    log_path = output_dir / f"e2_run_{stamp}.log"
    http_log_path = output_dir / f"e2_uvicorn_{stamp}.log"
    dataset_hash, code_hash = load_identity(root)

    tcp_port = 0
    http_port = free_port()
    tcp_server: TCPServer | None = None
    tcp_thread: threading.Thread | None = None
    http_process: subprocess.Popen[str] | None = None
    all_rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    log_lines = [
        "experiment=TEST_PLAN_E2",
        f"timestamp_utc={datetime.now(timezone.utc).isoformat()}",
        f"python={sys.version.split()[0]}",
        f"platform={platform.platform()}",
        "bind_host=127.0.0.1",
        "tcp_port=dynamic",
        f"http_port={http_port}",
        f"dataset_hash_sha256={dataset_hash}",
        f"code_hash_sha256={code_hash}",
        f"warmup_requests_per_worker={WARMUP_REQUESTS}",
        f"measure_requests_per_worker={MEASURE_REQUESTS}",
        f"independent_runs={len(RUNS)}",
    ]
    try:
        dataset_version = ""
        for _ in range(10):
            tcp_port = free_port()
            tcp_server = TCPServer("127.0.0.1", tcp_port)
            tcp_thread = threading.Thread(target=tcp_server.serve_forever, daemon=True)
            tcp_thread.start()
            try:
                dataset_version = wait_for_tcp(tcp_port)
                break
            except RuntimeError:
                tcp_server.shutdown()
                tcp_thread.join(timeout=2)
                tcp_server = None
                tcp_thread = None
        if not dataset_version or tcp_server is None or tcp_thread is None:
            raise RuntimeError("TCP Server did not become ready after port retries")
        if dataset_version != "vi-v2-50-recipes-r1":
            raise RuntimeError(f"unexpected dataset_version={dataset_version}")
        log_lines.append(f"actual_tcp_port={tcp_port}")
        for concurrency in CONCURRENCIES:
            for run_number in RUNS:
                rows, wall_seconds = run_protocol("TCP", tcp_port, dataset_version, concurrency, run_number, tcp_request)
                all_rows.extend(rows)
                summaries.append(summarize(rows, wall_seconds))

        http_process = start_http(http_port, tcp_port, http_log_path)
        wait_for_http(http_port, http_process)
        for concurrency in CONCURRENCIES:
            for run_number in RUNS:
                rows, wall_seconds = run_protocol("HTTP", http_port, dataset_version, concurrency, run_number, http_request)
                all_rows.extend(rows)
                summaries.append(summarize(rows, wall_seconds))
        log_lines.append(f"dataset_version={dataset_version}")
        log_lines.append(f"raw_rows={len(all_rows)}")
        log_lines.append(f"summary_rows={len(summaries)}")
        log_lines.append(f"pass_rows={sum(row['status'] == 'PASS' for row in summaries)}")
    finally:
        if http_process is not None:
            http_process.terminate()
            try:
                http_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                http_process.kill()
                http_process.wait(timeout=5)
            stream = getattr(http_process, "_benchmark_stream", None)
            if stream is not None:
                stream.close()
        if tcp_server is not None:
            tcp_server.shutdown()
        if tcp_thread is not None:
            tcp_thread.join(timeout=3)

    with raw_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=RAW_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    summary_fields = list(summaries[0]) if summaries else []
    with summary_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=summary_fields)
        writer.writeheader()
        writer.writerows(summaries)
    log_lines.extend([f"raw_csv={raw_path}", f"summary_csv={summary_path}", f"http_log={http_log_path}"])
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"raw_csv={raw_path}")
    print(f"summary_csv={summary_path}")
    print(f"run_log={log_path}")
    print(f"http_log={http_log_path}")
    print(f"raw_rows={len(all_rows)}")
    print(f"summary_rows={len(summaries)}")
    print(f"pass_rows={sum(row['status'] == 'PASS' for row in summaries)}")
    return 0 if summaries and all(row["status"] == "PASS" for row in summaries) else 1


if __name__ == "__main__":
    raise SystemExit(main())
