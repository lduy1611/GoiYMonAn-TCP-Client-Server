from pathlib import Path
import os
import shutil
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from source.web.main import app
from tests.test_web_meal_plan import meal_web


@pytest.mark.parametrize("width", [1280,390], ids=["desktop","mobile"])
def test_meal_plan_browser_journey(meal_web, tmp_path: Path, width):
    node = shutil.which("node")
    browser = next((path for root in (os.getenv("PROGRAMFILES"),os.getenv("PROGRAMFILES(X86)")) if root
                    for relative in ("Google/Chrome/Application/chrome.exe","Microsoft/Edge/Application/msedge.exe")
                    if (path := Path(root)/relative).is_file()), None)
    if not node or not browser:
        pytest.skip("Meal UI tests require Node 22+ and installed Chrome/Edge")
    capability = subprocess.run([node,"-e","process.exit(typeof WebSocket==='function'&&typeof fetch==='function'?0:1)"],capture_output=True,timeout=10)
    if capability.returncode:
        pytest.skip("Meal UI tests require built-in Node WebSocket/fetch")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=port,log_level="error"))
    thread = threading.Thread(target=server.run,daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        profile = tmp_path/"chrome"
        profile.mkdir()
        result = subprocess.run([node,str(Path(__file__).with_name("browser_meal_plan.mjs")),str(browser),
                                 f"http://127.0.0.1:{port}",str(profile),str(width)],
                                capture_output=True,text=True,encoding="utf-8",timeout=120)
        assert result.returncode == 0, result.stdout+result.stderr
        print(result.stdout.encode("ascii",errors="backslashreplace").decode("ascii"))
    finally:
        server.should_exit = True
        thread.join(timeout=5)
