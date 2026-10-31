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

from source.common.protocol import ProtocolError, encode_frame, error_response, recv_frame
from source.server.handler import dispatch
from source.server.repository import MySQLRepository, Repository

LOG_PATH = Path(os.getenv("TCP_LOG_PATH", "statics/results/tcp_server.jsonl"))


class TCPServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 9000, db_path: str | Path | None = None, max_connections: int = 32, repository: Any | None = None):
        self.host, self.port = host, port
        self.repository = repository or (Repository(db_path) if db_path is not None else MySQLRepository.from_env())
        self.max_connections = max_connections
        self.slots = threading.BoundedSemaphore(max_connections)
        self.stop_event = threading.Event()
        self.sock: socket.socket | None = None
        self.logger = logging.getLogger("tcp_server")
        self.logger.setLevel(logging.INFO)

    def _log(self, **data: object) -> None:
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
                if not self.slots.acquire(blocking=False):
                    client.close()
                    continue
                threading.Thread(target=self._handle, args=(client, address), daemon=True).start()

    def _handle(self, client: socket.socket, address: object) -> None:
        connection_id = str(uuid.uuid4())
        try:
            with client:
                while True:
                    started = time.monotonic()
                    request = None
                    try:
                        request, bytes_in = recv_frame(client)
                        if request is None:
                            return
                        response, op = dispatch(self.repository, request)
                        frame = encode_frame(response)
                        client.sendall(frame)
                        self._log(request_id=response["request_id"], op=op, connection_id=connection_id, outcome="ok", error_code=None, receive_ms=0, service_ms=round((time.monotonic() - started) * 1000, 3), send_ms=0, bytes_in=bytes_in, bytes_out=len(frame), dataset_version=response.get("data", {}).get("dataset_version"))
                    except ProtocolError as exc:
                        self._log(request_id=exc.request_id, op=None, connection_id=connection_id, outcome="error", error_code=exc.code, receive_ms=0, service_ms=round((time.monotonic() - started) * 1000, 3), send_ms=0, bytes_in=0, bytes_out=0, dataset_version=None)
                        recoverable = exc.code in {"UNKNOWN_OPERATION", "INVALID_PAYLOAD", "NOT_FOUND"} and exc.request_id is not None
                        if recoverable or exc.code in {"INVALID_REQUEST", "UNSUPPORTED_VERSION"}:
                            try:
                                client.sendall(encode_frame(error_response(exc.request_id, exc.code, exc.message)))
                            except OSError:
                                return
                            if recoverable:
                                continue
                        return
                    except (sqlite3.Error, mysql.connector.Error):
                        request_id = request.get("request_id") if isinstance(request, dict) else None
                        try:
                            client.sendall(encode_frame(error_response(request_id if isinstance(request_id, str) else None, "DB_ERROR", "database operation failed")))
                        except OSError:
                            return
                        continue
                    except (ConnectionError, OSError):
                        return
                    except Exception:
                        request_id = request.get("request_id") if isinstance(request, dict) else None
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
    TCPServer(os.getenv("TCP_HOST", "127.0.0.1"), int(os.getenv("TCP_PORT", "9000"))).serve_forever()


if __name__ == "__main__":
    main()
