"""Additive user-account schema migration identity for migration 005."""
from hashlib import sha256
from pathlib import Path
import json
import re

VERSION = "005_user_accounts"
TABLES = {"v2_user_accounts"}
SQL_PATH = Path(__file__).with_name("migrations") / f"{VERSION}.sql"


def checksum():
    return sha256(SQL_PATH.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def statements():
    text = re.sub(r"(?m)^\s*--.*$", "", SQL_PATH.read_text(encoding="utf-8"))
    return [part.strip() for part in text.split(";") if part.strip()]


def schema_hash(connection):
    cursor = connection.cursor()
    try:
        cursor.execute("SHOW CREATE TABLE v2_user_accounts")
        return sha256(json.dumps(cursor.fetchone()[1], ensure_ascii=True).encode()).hexdigest()
    finally:
        cursor.close()


def schema_hash_matches(connection, expected_hash):
    """Accept the recorded DDL hash across normal AUTO_INCREMENT growth only."""
    cursor = connection.cursor()
    try:
        cursor.execute("SHOW CREATE TABLE v2_user_accounts")
        ddl = cursor.fetchone()[1]
    finally:
        cursor.close()
    variants = {ddl}
    variants.add(re.sub(r"\sAUTO_INCREMENT=\d+", "", ddl))
    variants.add(re.sub(r"AUTO_INCREMENT=\d+", "AUTO_INCREMENT=1", ddl))
    hashes = {sha256(json.dumps(value, ensure_ascii=True).encode()).hexdigest() for value in variants}
    return expected_hash in hashes
