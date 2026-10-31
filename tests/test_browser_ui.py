"""Optional real-browser UI tests; no additional Python/npm dependencies."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

import pytest
import uvicorn

from tests.test_web_integration import web_with_tcp
from source.web.main import app


@pytest.mark.parametrize("width", [1280, 390], ids=["desktop", "mobile"])
def test_browser_user_journey(web_with_tcp, tmp_path: Path, width: int):
    node = shutil.which("node")
    browser = next((p for root in (os.getenv("PROGRAMFILES"), os.getenv("PROGRAMFILES(X86)")) if root
                    for relative in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe")
                    if (p := Path(root) / relative).is_file()), None)
    if not node or not browser:
        pytest.skip("UI browser test requires Node 22+ and installed Chrome or Edge on Windows")
    supports_cdp = subprocess.run(
        [node, "-e", "process.exit(typeof WebSocket === 'function' && typeof fetch === 'function' ? 0 : 1)"],
        capture_output=True, timeout=10,
    )
    if supports_cdp.returncode:
        pytest.skip("Node must provide built-in WebSocket and fetch (Node 22+)")
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started, "HTTP server did not start"
        profile = tmp_path / "browser-profile"
        profile.mkdir()
        result = subprocess.run(
            [node, str(Path(__file__).with_name("browser_ui.mjs")), str(browser),
             f"http://127.0.0.1:{port}", str(profile), str(width),
             os.getenv("UI_TEST_MODE", "test"), str(Path("statics/runtime/ui-back-fix/legacy-styles.css").resolve())],
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout.encode("ascii", errors="backslashreplace").decode("ascii"))
    finally:
        server.should_exit = True
        thread.join(timeout=5)
