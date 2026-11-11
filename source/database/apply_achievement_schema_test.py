"""Apply the achievements schema only to the known unified v3 TEST_ONLY DB."""
from __future__ import annotations

import os
import re
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env", override=False)
    expected = "goiy_v3_quality_final_20261110_test"
    # This one-off updater is deliberately pinned to the named local rehearsal DB;
    # it does not infer its target from whichever app process happens to be running.
    connection = mysql.connector.connect(
        host="127.0.0.1", port=63900,
        user=os.getenv("UNIFIED_MYSQL_USER", "root"), password=os.getenv("UNIFIED_MYSQL_PASSWORD", ""),
        database=expected, charset="utf8mb4", connection_timeout=5,
    )
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT DATABASE(),@@port")
        identity = cursor.fetchone()
        if identity != (expected, 63900):
            raise SystemExit("Refusing schema change: connected database identity did not match TEST_ONLY.")
        sql = (root / "source/database/migrations/unified_v3_002_achievements.sql").read_text(encoding="utf-8")
        sql = re.sub(r"(?m)^\s*--.*$", "", sql)
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                cursor.execute(statement)
        connection.commit()
        cursor.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_name IN ('achievement_posts','achievement_images','achievement_comments') ORDER BY table_name", (expected,))
        tables = [row[0] for row in cursor.fetchall()]
        if tables != ["achievement_comments", "achievement_images", "achievement_posts"]:
            raise RuntimeError("Achievement schema verification failed.")
        print("Achievement schema applied and verified on designated TEST_ONLY database.")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
