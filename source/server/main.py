from __future__ import annotations

import json
import logging
import os
import socket
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import mysql.connector
from dotenv import load_dotenv

from source.common.protocol import ProtocolError, encode_frame, error_response, recv_frame
from source.server.handler import dispatch
from source.server.repository import MySQLRepository, Repository

# Read TCP settings before import-time constants and main() startup arguments.
# Explicit process variables take precedence over the repository's local .env.
load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
LOG_PATH = Path(os.getenv("TCP_LOG_PATH", "statics/runtime/tcp_server.jsonl"))


def configured_tcp_max_connections() -> int:
    """Keep TCP worker concurrency within the eagerly opened MySQL pool."""
    unified = os.getenv("TCP_DB_SCHEMA", "legacy").casefold() == "unified_v3"
    pool_variable = "UNIFIED_TCP_DB_POOL_SIZE" if unified else "TCP_DB_POOL_SIZE"
    try:
        pool_size = int(os.getenv(pool_variable, "4"))
        requested = int(os.getenv("TCP_MAX_CONNECTIONS", str(pool_size)))
    except ValueError:
        raise RuntimeError("TCP pool and connection limits must be integers") from None
    if not 1 <= pool_size <= 64 or not 1 <= requested <= pool_size:
        raise RuntimeError("TCP_MAX_CONNECTIONS must be between 1 and the configured MySQL pool size")
    return requested


class TCPServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 9000, db_path: str | Path | None = None, max_connections: int = 32, repository: Any | None = None):
        self.host, self.port = host, port
        if repository is not None:
            self.repository = repository
        elif db_path is not None:
            self.repository = Repository(db_path)
        elif os.getenv("TCP_DB_SCHEMA", "legacy").casefold() == "unified_v3":
            from source.server.unified_repository import UnifiedMySQLRepository
            self.repository = UnifiedMySQLRepository.from_env()
        else:
            self.repository = MySQLRepository.from_env()
        self.max_connections = max_connections
        self.slots = threading.BoundedSemaphore(max_connections)
        self.stop_event = threading.Event()
        self.sock: socket.socket | None = None
        self._log_lock = threading.Lock()
        self.logger = logging.getLogger("tcp_server")
        self.logger.setLevel(logging.INFO)

    def _log(self, **data: object) -> None:
        with self._log_lock:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **data}, ensure_ascii=False) + "\n")

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            self.sock = server_socket
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.bind((self.host, self.port))
            server_socket.listen(64)
            server_socket.settimeout(1.0)
            while not self.stop_event.is_set():
                try:
                    client, address = server_socket.accept()
                except socket.timeout:
                    continue
                except OSError:
                    if self.stop_event.is_set():
                        break
                    raise
                # Backpressure instead of accepting and immediately closing
                # clients when all workers are busy. Pending sockets wait in
                # the bounded OS listen backlog.
                admission_started = time.monotonic()
                acquired = False
                while not self.stop_event.is_set():
                    if self.slots.acquire(timeout=0.1):
                        acquired = True
                        break
                if not acquired:
                    client.close()
                    break
                wait_ms = round((time.monotonic() - admission_started) * 1000, 3)
                worker = threading.Thread(target=self._handle, args=(client, address, wait_ms), daemon=True)
                try:
                    worker.start()
                except Exception:
                    self.slots.release()
                    client.close()
                    raise

    def _handle(self, client: socket.socket, address: object, admission_wait_ms: float = 0) -> None:
        connection_id = str(uuid.uuid4())
        try:
            with client:
                while True:
                    started = time.monotonic()
                    request = None
                    op = None
                    stage = "receive"
                    dispatch_started = None
                    receive_ms = dispatch_ms = encode_ms = send_ms = 0.0
                    bytes_in = bytes_out = 0
                    try:
                        receive_started = time.monotonic()
                        request, bytes_in = recv_frame(client)
                        receive_ms = round((time.monotonic() - receive_started) * 1000, 3)
                        if request is None:
                            return
                        op = request.get("op") if isinstance(request.get("op"), str) else None
                        stage = "dispatch"
                        dispatch_started = time.monotonic()
                        response, op = dispatch(self.repository, request)
                        dispatch_ms = round((time.monotonic() - dispatch_started) * 1000, 3)
                        stage = "encode"
                        encode_started = time.monotonic()
                        frame = encode_frame(response)
                        encode_ms = round((time.monotonic() - encode_started) * 1000, 3)
                        stage = "send"
                        send_started = time.monotonic()
                        client.sendall(frame)
                        send_ms = round((time.monotonic() - send_started) * 1000, 3)
                        bytes_out = len(frame)
                        self._log(request_id=response["request_id"], op=op, connection_id=connection_id,
                                  outcome="ok", error_code=None, stage="complete", admission_wait_ms=admission_wait_ms,
                                  receive_ms=receive_ms, dispatch_ms=dispatch_ms, encode_ms=encode_ms,
                                  service_ms=round((time.monotonic() - started) * 1000, 3), send_ms=send_ms,
                                  bytes_in=bytes_in, bytes_out=bytes_out,
                                  dataset_version=response.get("data", {}).get("dataset_version"))
                    except ProtocolError as exc:
                        if stage == "dispatch" and dispatch_started is not None:
                            dispatch_ms = round((time.monotonic() - dispatch_started) * 1000, 3)
                        request_id = exc.request_id or (request.get("request_id") if isinstance(request, dict) else None)
                        self._log(request_id=request_id, op=op, connection_id=connection_id,
                                  outcome="error", error_code=exc.code, stage=stage,
                                  admission_wait_ms=admission_wait_ms, receive_ms=receive_ms,
                                  dispatch_ms=dispatch_ms, encode_ms=encode_ms, send_ms=send_ms,
                                  mysql_errno=getattr(exc, "mysql_errno", None),
                                  diagnostic_code=getattr(exc, "diagnostic_code", None),
                                  service_ms=round((time.monotonic() - started) * 1000, 3),
                                  bytes_in=bytes_in, bytes_out=bytes_out, dataset_version=None)
                        recoverable = exc.code in {
                            "UNKNOWN_OPERATION", "UNSUPPORTED_OPERATION", "INVALID_PAYLOAD", "NOT_FOUND",
                            "ADMIN_UNAUTHORIZED", "ADMIN_WRITE_DENIED", "ADMIN_DRAFT_CONFLICT", "ADMIN_RECIPE_CONFLICT",
                            "ADMIN_INGREDIENT_CONFLICT", "ADMIN_RECIPE_DELETE_BLOCKED", "ADMIN_INGREDIENT_DELETE_BLOCKED",
                            "ADMIN_TAXONOMY_CONFLICT",
                            "ADMIN_WRITE_UNAVAILABLE", "ADMIN_SCHEMA_UNAVAILABLE",
                            "FORBIDDEN", "ACHIEVEMENT_CONFLICT",
                            "DB_UNAVAILABLE", "ADMIN_RECIPE_CONSTRAINT", "ADMIN_RECIPE_INVALID_DATA",
                            "USER_ACCOUNT_CONFLICT", "USER_ACCOUNT_UNAVAILABLE", "USER_UNAUTHORIZED", "USER_LOCKED",
                        } and exc.request_id is not None
                        if recoverable or exc.code in {"INVALID_REQUEST", "UNSUPPORTED_VERSION"}:
                            try:
                                send_started = time.monotonic()
                                error_frame = encode_frame(error_response(exc.request_id, exc.code, exc.message))
                                client.sendall(error_frame)
                                send_ms = round((time.monotonic() - send_started) * 1000, 3)
                                self._log(request_id=request_id, op=op, connection_id=connection_id,
                                          outcome="error_response_sent", error_code=exc.code, stage="send",
                                          admission_wait_ms=admission_wait_ms, receive_ms=receive_ms,
                                          dispatch_ms=dispatch_ms, send_ms=send_ms,
                                          service_ms=round((time.monotonic() - started) * 1000, 3),
                                          bytes_in=bytes_in, bytes_out=len(error_frame), dataset_version=None)
                            except OSError:
                                return
                            if recoverable:
                                continue
                        return
                    except (sqlite3.Error, mysql.connector.Error) as exc:
                        if stage == "dispatch" and dispatch_started is not None:
                            dispatch_ms = round((time.monotonic() - dispatch_started) * 1000, 3)
                        request_id = request.get("request_id") if isinstance(request, dict) else None
                        op = request.get("op") if isinstance(request, dict) and isinstance(request.get("op"), str) else None
                        self._log(request_id=request_id if isinstance(request_id, str) else None,
                                  op=op, connection_id=connection_id, outcome="error", error_code="DB_ERROR",
                                  stage=stage, admission_wait_ms=admission_wait_ms,
                                  mysql_errno=getattr(exc, "errno", None), mysql_sqlstate=getattr(exc, "sqlstate", None),
                                  receive_ms=receive_ms, dispatch_ms=dispatch_ms,
                                  service_ms=round((time.monotonic() - started) * 1000, 3), send_ms=0,
                                  bytes_in=bytes_in, bytes_out=0, dataset_version=None)
                        try:
                            error_frame = encode_frame(error_response(request_id if isinstance(request_id, str) else None, "DB_ERROR", "database operation failed"))
                            send_started = time.monotonic()
                            client.sendall(error_frame)
                            self._log(request_id=request_id if isinstance(request_id, str) else None, op=op,
                                      connection_id=connection_id, outcome="error_response_sent", error_code="DB_ERROR",
                                      stage="send", admission_wait_ms=admission_wait_ms,
                                      send_ms=round((time.monotonic() - send_started) * 1000, 3),
                                      service_ms=round((time.monotonic() - started) * 1000, 3),
                                      bytes_in=bytes_in, bytes_out=len(error_frame), dataset_version=None)
                        except OSError:
                            return
                        continue
                    except (ConnectionError, OSError) as exc:
                        request_id = request.get("request_id") if isinstance(request, dict) else None
                        self._log(request_id=request_id if isinstance(request_id, str) else None, op=op,
                                  connection_id=connection_id, outcome="error", error_code="TRANSPORT_ERROR",
                                  stage=stage, admission_wait_ms=admission_wait_ms,
                                  os_error=getattr(exc, "errno", None), receive_ms=receive_ms,
                                  dispatch_ms=dispatch_ms, encode_ms=encode_ms, send_ms=send_ms,
                                  service_ms=round((time.monotonic() - started) * 1000, 3),
                                  bytes_in=bytes_in, bytes_out=bytes_out, dataset_version=None)
                        return
                    except Exception as exc:
                        request_id = request.get("request_id") if isinstance(request, dict) else None
                        self._log(request_id=request_id if isinstance(request_id, str) else None, op=op,
                                  connection_id=connection_id, outcome="error", error_code="INTERNAL_ERROR",
                                  stage=stage, admission_wait_ms=admission_wait_ms,
                                  exception_type=type(exc).__name__, receive_ms=receive_ms,
                                  dispatch_ms=dispatch_ms, encode_ms=encode_ms, send_ms=send_ms,
                                  service_ms=round((time.monotonic() - started) * 1000, 3),
                                  bytes_in=bytes_in, bytes_out=bytes_out, dataset_version=None)
                        try:
                            client.sendall(encode_frame(error_response(request_id if isinstance(request_id, str) else None, "INTERNAL_ERROR", "internal server error")))
                        except OSError:
                            return
                        return
        finally:
            self.slots.release()

    def shutdown(self) -> None:
        self.stop_event.set()
        if self.sock is not None:
            self.sock.close()


def main() -> None:
    TCPServer(os.getenv("TCP_HOST", "127.0.0.1"), int(os.getenv("TCP_PORT", "9000")),
              max_connections=configured_tcp_max_connections()).serve_forever()


if __name__ == "__main__":
    main()
