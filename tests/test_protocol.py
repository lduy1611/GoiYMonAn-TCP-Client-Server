import socket
import threading

import pytest

from source.common.protocol import ProtocolError, encode_frame, recv_frame


def test_coalesced_frames_and_utf8():
    left, right = socket.socketpair()
    try:
        left.sendall(encode_frame({"text": "cà chua", "n": 1}) + encode_frame({"n": 2}))
        first, _ = recv_frame(right)
        second, _ = recv_frame(right)
        assert first == {"text": "cà chua", "n": 1}
        assert second == {"n": 2}
    finally:
        left.close(); right.close()


def test_header_can_arrive_one_byte_at_a_time():
    left, right = socket.socketpair()
    frame = encode_frame({"ok": True})
    thread = threading.Thread(target=lambda: [left.send(bytes([byte])) for byte in frame])
    try:
        thread.start()
        value, _ = recv_frame(right)
        thread.join()
        assert value == {"ok": True}
    finally:
        left.close(); right.close()


@pytest.mark.parametrize("wire", [b"\x00", b"\x00\x00\x00", b"\x00\x00\x00\x05", b"\x00\x00\x00\x05{"])
def test_eof_during_frame_is_truncated(wire):
    left, right = socket.socketpair()
    try:
        left.sendall(wire)
        left.shutdown(socket.SHUT_WR)
        with pytest.raises(ProtocolError) as error:
            recv_frame(right)
        assert error.value.code == "TRUNCATED_FRAME"
    finally:
        left.close()
        right.close()


def test_eof_between_frames_is_clean():
    left, right = socket.socketpair()
    left.close()
    try:
        assert recv_frame(right) == (None, 0)
    finally:
        right.close()


@pytest.mark.parametrize("wire", [b"", b"\x00", b"\x00\x00\x00\x05", b"\x00\x00\x00\x05{"])
def test_idle_or_incomplete_frame_has_read_deadline(wire):
    left, right = socket.socketpair()
    try:
        if wire:
            left.sendall(wire)
        with pytest.raises(ProtocolError) as error:
            recv_frame(right, timeout=0.05)
        assert error.value.code == "TIMEOUT"
    finally:
        left.close()
        right.close()
