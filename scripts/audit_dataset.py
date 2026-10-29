"""Audit the expanded MySQL dataset and save UTF-8 evidence files."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mysql.connector
from dotenv import load_dotenv


def mysql_connection():
    load_dotenv()
    return mysql.connector.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ["MYSQL_PORT"]),
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        database=os.environ["MYSQL_DATABASE"],
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
    )


def sha256_json(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def code_hash(project_root: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted(path for root in (project_root / "source", project_root / "scripts") for path in root.rglob("*.py"))
    for path in paths:
        digest.update(path.relative_to(project_root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="statics/results")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    output_dir = project_root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    connection = mysql_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT `key`, value FROM metadata ORDER BY `key`")
    metadata = {row["key"]: row["value"] for row in cursor.fetchall()}
    cursor.execute("SELECT COUNT(*) AS count FROM ingredients")
    ingredient_count = int(cursor.fetchone()["count"])
    cursor.execute("SELECT COUNT(*) AS count FROM recipes")
    recipe_count = int(cursor.fetchone()["count"])
    cursor.execute("SELECT COUNT(*) AS count FROM recipe_ingredients")
    relation_count = int(cursor.fetchone()["count"])
    cursor.execute("SELECT id, title, instructions, minutes FROM recipes ORDER BY id")
    recipes = cursor.fetchall()
    cursor.execute("SELECT recipe_id, ingredient_id, quantity, is_required FROM recipe_ingredients ORDER BY recipe_id, ingredient_id")
    relations = cursor.fetchall()
    cursor.close()
    connection.close()

    relation_map: dict[int, list[dict[str, object]]] = {}
    for relation in relations:
        relation_map.setdefault(int(relation["recipe_id"]), []).append({
            "ingredient_id": int(relation["ingredient_id"]),
            "quantity": relation["quantity"],
            "is_required": bool(relation["is_required"]),
        })
    recipe_rows: list[dict[str, object]] = []
    for recipe in recipes:
        instructions = str(recipe["instructions"])
        steps = [line.strip() for line in instructions.splitlines() if line.strip()]
        numbered_steps = [line for line in steps if line.casefold().startswith("bước")]
        recipe_rows.append({
            "recipe_id": int(recipe["id"]),
            "title": recipe["title"],
            "minutes": int(recipe["minutes"]),
            "instruction_line_count": len(steps),
            "step_count": len(numbered_steps),
            "ingredient_ids": json.dumps([item["ingredient_id"] for item in relation_map.get(int(recipe["id"]), [])]),
            "has_instructions": bool(instructions.strip()),
        })

    canonical = {"metadata": metadata, "recipes": recipes, "relations": relations}
    report = {
        "dataset_version": metadata.get("dataset_version"),
        "ingredient_count": ingredient_count,
        "recipe_count": recipe_count,
        "relation_count": relation_count,
        "expected_counts": {"ingredients": 50, "recipes": 50, "relations": 252},
        "all_recipe_ids_present": sorted(row["recipe_id"] for row in recipe_rows) == list(range(1, 51)),
        "all_recipes_have_at_least_three_steps": all(int(row["step_count"]) >= 3 for row in recipe_rows),
        "dataset_hash_sha256": sha256_json(canonical),
        "code_hash_sha256": code_hash(project_root),
        "recipe_rows": recipe_rows,
    }
    report["status"] = "PASS" if (
        report["dataset_version"] == "vi-v2-50-recipes-r1"
        and ingredient_count == 50
        and recipe_count == 50
        and relation_count == 252
        and report["all_recipe_ids_present"]
        and report["all_recipes_have_at_least_three_steps"]
    ) else "FAIL"

    (output_dir / "phase4_dataset_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    with (output_dir / "phase4_recipe_audit.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(recipe_rows[0]))
        writer.writeheader()
        writer.writerows(recipe_rows)
    (output_dir / "phase4_dataset_audit.log").write_text(
        "\n".join([
            "dataset_audit=real_mysql_query",
            f"status={report['status']}",
            f"dataset_version={report['dataset_version']}",
            f"ingredients={ingredient_count}",
            f"recipes={recipe_count}",
            f"recipe_ingredients={relation_count}",
            f"all_recipe_ids_present={report['all_recipe_ids_present']}",
            f"all_recipes_have_at_least_three_steps={report['all_recipes_have_at_least_three_steps']}",
            f"dataset_hash_sha256={report['dataset_hash_sha256']}",
            f"code_hash_sha256={report['code_hash_sha256']}",
        ]) + "\n",
        encoding="utf-8",
    )
    print(f"status={report['status']}")
    print(f"dataset_version={report['dataset_version']}")
    print(f"ingredients={ingredient_count}")
    print(f"recipes={recipe_count}")
    print(f"recipe_ingredients={relation_count}")
    print(f"dataset_hash_sha256={report['dataset_hash_sha256']}")
    print(f"code_hash_sha256={report['code_hash_sha256']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
