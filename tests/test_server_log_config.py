"""Isolated startup/log checks: no real .env reads or database connections."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("case", ["default", "dotenv", "process_override", "dotenv_disabled"])
def test_server_loads_log_and_startup_settings_before_use(tmp_path, case):
    project = tmp_path / "project"
    module = project / "source/server/main.py"
    module.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "source/server/main.py", module)
    dotenv = project / ".env"
    if case != "default":
        dotenv.write_text(
            "TCP_LOG_PATH=custom/nested/from-file.jsonl\nTCP_HOST=localhost\nTCP_PORT=9101\n",
            encoding="utf-8",
        )
    before = dotenv.read_bytes() if dotenv.exists() else None
    env = os.environ.copy()
    for name in ("TCP_LOG_PATH", "TCP_HOST", "TCP_PORT", "TCP_MAX_CONNECTIONS", "PYTHON_DOTENV_DISABLED"):
        env.pop(name, None)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(TCP_DB_SCHEMA='legacy', TCP_DB_POOL_SIZE='4')
    if case == "process_override":
        env.update(TCP_LOG_PATH="override/deep/from-process.jsonl", TCP_HOST="127.0.0.1", TCP_PORT="9202")
    if case == "dotenv_disabled":
        env["PYTHON_DOTENV_DISABLED"] = "1"
    probe = r'''
import json, runpy, sys
from pathlib import Path
module = runpy.run_path(sys.argv[1], run_name="isolated_server_config")
path = module["LOG_PATH"]
assert not path.parent.exists(), "Runtime folder must be created on demand"
server = module["TCPServer"](repository=object())
server._log(marker="startup-config-test", request_id="00000000-0000-4000-8000-000000000001")
server._log(marker="append-test")
rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
assert rows[0]["marker"] == "startup-config-test" and rows[1]["marker"] == "append-test"
assert "timestamp_utc" in rows[0]
class StartupProbe:
    def __init__(self, host, port, *, max_connections):
        assert max_connections == 4
        self.host, self.port = host, port
    def serve_forever(self):
        print(json.dumps({"path": path.as_posix(), "host": self.host, "port": self.port}))
module["main"].__globals__["TCPServer"] = StartupProbe
module["main"]()
assert not Path("statics/results/tcp_server.jsonl").exists()
'''
    result = subprocess.run(
        [sys.executable, "-B", "-c", probe, str(module)], cwd=project, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    actual = json.loads(result.stdout)
    expected = {
        "default": ("statics/runtime/tcp_server.jsonl", "127.0.0.1", 9000),
        "dotenv": ("custom/nested/from-file.jsonl", "localhost", 9101),
        "process_override": ("override/deep/from-process.jsonl", "127.0.0.1", 9202),
        "dotenv_disabled": ("statics/runtime/tcp_server.jsonl", "127.0.0.1", 9000),
    }
    path, host, port = expected[case]
    assert actual == {"path": path, "host": host, "port": port}
    assert (dotenv.read_bytes() if dotenv.exists() else None) == before
