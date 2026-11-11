from __future__ import annotations

import socket
import time
import uuid
from typing import Any

from source.common.protocol import CLIENT_TOTAL_BUDGET, ProtocolError, encode_frame, recv_frame


class TCPClientError(Exception):
    def __init__(self, code: str, *, phase: str | None = None, os_error: int | None = None):
        super().__init__(code)
        self.code = code
        self.phase = phase
        self.os_error = os_error


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
        phase = "connect"
        try:
            if sock is None:
                try:
                    sock = socket.create_connection((self.host, self.port), timeout=min(1.0, CLIENT_TOTAL_BUDGET))
                except (socket.timeout, TimeoutError) as exc:
                    raise TCPClientError("CONNECT_TIMEOUT", phase="connect") from exc
                except OSError as exc:
                    raise TCPClientError("UPSTREAM_UNAVAILABLE", phase="connect", os_error=getattr(exc, "errno", None)) from exc
                if self.persistent:
                    self.sock = sock
            sock.settimeout(min(5.0, max(0.001, CLIENT_TOTAL_BUDGET - (time.monotonic() - started))))
            phase = "send"
            sock.sendall(frame)
            phase = "receive"
            response, _ = recv_frame(sock, timeout=min(5.0, max(0.001, CLIENT_TOTAL_BUDGET - (time.monotonic() - started))))
            if response is None:
                raise TCPClientError("UPSTREAM_DISCONNECTED", phase="receive")
            if response.get("request_id") != request_id:
                raise TCPClientError("UPSTREAM_PROTOCOL", phase="receive")
            return response
        except (socket.timeout, TimeoutError) as exc:
            self.close()
            code = "CONNECT_TIMEOUT" if phase == "connect" else "TIMEOUT"
            raise TCPClientError(code, phase=phase) from exc
        except OSError as exc:
            self.close()
            code = "UPSTREAM_UNAVAILABLE" if phase == "connect" else "UPSTREAM_DISCONNECTED"
            raise TCPClientError(code, phase=phase, os_error=getattr(exc, "errno", None)) from exc
        except ProtocolError as exc:
            self.close()
            raise TCPClientError(exc.code, phase=phase) from exc
        except TCPClientError:
            self.close()
            raise
        finally:
            if not self.persistent and sock is not None:
                sock.close()
            if time.monotonic() - started > CLIENT_TOTAL_BUDGET:
                self.close()

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None
