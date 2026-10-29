import socket
import threading

from source.common.protocol import encode_frame, recv_frame


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
