from __future__ import annotations

import socket
import time
import uuid
from typing import Any

from source.common.protocol import CLIENT_TOTAL_BUDGET, ProtocolError, encode_frame, recv_frame


class TCPClientError(Exception):
    pass


class TCPClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 9000, persistent: bool = False):
        self.host, self.port, self.persistent = host, port, persistent
        self.sock: socket.socket | None = None

    def request(self, op: str, payload: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
        request_id = request_id or str(uuid.uuid4())
        request = {"version": 1, "request_id": request_id, "op": op, "payload": payload}
        frame = encode_frame(request)
        started = time.monotonic()
        sock = self.sock
        try:
            if sock is None:
                sock = socket.create_connection((self.host, self.port), timeout=min(1.0, CLIENT_TOTAL_BUDGET))
                if self.persistent:
                    self.sock = sock
            sock.settimeout(min(5.0, max(0.001, CLIENT_TOTAL_BUDGET - (time.monotonic() - started))))
            sock.sendall(frame)
            response, _ = recv_frame(sock, timeout=min(5.0, max(0.001, CLIENT_TOTAL_BUDGET - (time.monotonic() - started))))
            if response is None or response.get("request_id") != request_id:
                raise TCPClientError("UPSTREAM_PROTOCOL")
            return response
        except (OSError, TimeoutError) as exc:
            raise TCPClientError("UPSTREAM_UNAVAILABLE") from exc
        except ProtocolError as exc:
            raise TCPClientError(exc.code) from exc
        finally:
            if not self.persistent and sock is not None:
                sock.close()
            if time.monotonic() - started > CLIENT_TOTAL_BUDGET:
                self.close()

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None
