"""Read checked-in SQL literals; build temporary SQLite test data only, never run MySQL SQL."""
from __future__ import annotations

import ast
from contextlib import contextmanager
from pathlib import Path
import re
import socket
import sqlite3
import threading
import time

from source.client.tcp_client import TCPClient, TCPClientError
from source.server.main import TCPServer
from source.server.repository import Repository

ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "e35954bb-19f1-40a6-a8d2-77288ead8050"


def sql_rows(table):
    text = "\n".join((ROOT / "source/database" / name).read_text(encoding="utf-8")
                     for name in ("mysql_seed.sql", "mysql_expanded_seed.sql"))
    result = []
    for block in re.findall(rf"INSERT(?: IGNORE)? INTO {table}\s*\([^)]*\)\s*VALUES\s*(.*?);", text, re.S):
        for row in re.findall(r"\((?:'(?:\\.|''|[^'])*'|[^()'])*\)", block):
            result.append(ast.literal_eval(re.sub(r"(?<=[,(])\s*NULL(?=[,)])", "None", row)))
    return result


def full_dataset():
    names = {row[0]: row[1] for row in sql_rows("ingredients")}
    relations = sql_rows("recipe_ingredients")
    recipes, details = [], []
    for rid, title, instructions, minutes, url, _ in sql_rows("recipes"):
        ingredients = [{"id": iid, "name": names[iid], "quantity": quantity, "is_required": bool(required)}
                       for recipe_id, iid, quantity, required in relations if recipe_id == rid]
        recipes.append({"id": rid, "title": title, "minutes": minutes,
                        "required_ids": {i["id"] for i in ingredients if i["is_required"]},
                        "all_ids": {i["id"] for i in ingredients}})
        details.append({"id": rid, "title": title, "instructions": instructions, "minutes": minutes,
                        "source_url": url, "ingredients": ingredients})
    return recipes, details


def sqlite_repository(path):
    with sqlite3.connect(path) as connection:
        connection.executescript((ROOT / "source/database/schema.sql").read_text(encoding="utf-8"))
        connection.executemany("INSERT INTO ingredients VALUES(?,?,?)", sql_rows("ingredients"))
        connection.executemany("INSERT INTO recipes VALUES(?,?,?,?,?,?)", sql_rows("recipes"))
        connection.executemany("INSERT INTO recipe_ingredients VALUES(?,?,?,?)", sql_rows("recipe_ingredients"))
        connection.execute("INSERT INTO metadata VALUES('dataset_version','meal-test-50')")
    return Repository(path)


@contextmanager
def running_repository(repository):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = TCPServer("127.0.0.1", port, repository=repository)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            try:
                assert TCPClient(port=port).request("PING", {})["ok"]
                break
            except (OSError, TCPClientError):
                if not thread.is_alive():
                    raise
                time.sleep(0.01)
        else:
            raise AssertionError("TCP server did not start")
        yield server, port
    finally:
        server.shutdown()
        thread.join(timeout=2)
