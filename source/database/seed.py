from __future__ import annotations

import argparse
import sqlite3
import unicodedata
from pathlib import Path


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).casefold().split())


def seed(path: str | Path) -> None:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
        connection.executescript("DELETE FROM recipe_ingredients; DELETE FROM recipes; DELETE FROM ingredient_aliases; DELETE FROM ingredients; DELETE FROM metadata;")
        ingredients = [(1, "Trứng"), (2, "Cà chua"), (3, "Hành"), (4, "Thịt"), (5, "Đậu phụ"), (6, "Rau muống"), (7, "Tỏi"), (8, "Gừng"), (9, "Nấm hương"), (10, "Cà rốt"), (11, "Khoai tây"), (12, "Dưa leo"), (13, "Cá basa"), (14, "Thịt gà"), (15, "Bún")]
        connection.executemany("INSERT INTO ingredients(id,name,normalized_name) VALUES(?,?,?)", [(i, n, normalize(n)) for i, n in ingredients])
        connection.execute("INSERT INTO ingredient_aliases(alias_norm,ingredient_id) VALUES(?,?)", (normalize("tomato"), 2))
        recipes = [(1, "Trứng sốt cà chua", "Đánh trứng, nấu cùng cà chua.", 15, None, "Tự biên soạn cho đồ án, dùng cho mục đích minh họa."), (2, "Món thịt rau củ", "Nấu chín thịt và rau củ.", 30, None, "Tự biên soạn cho đồ án, dùng cho mục đích minh họa."), (3, "Trứng xào hành", "Xào trứng với hành.", 10, None, "Tự biên soạn cho đồ án, dùng cho mục đích minh họa."), (4, "Đậu phụ sốt cà chua", "Chiên áp chảo đậu phụ, thêm cà chua và nêm vừa ăn.", 20, None, "Tự biên soạn cho đồ án, dùng cho mục đích minh họa."), (5, "Rau muống xào tỏi", "Chần rau muống, xào nhanh với tỏi băm.", 12, None, "Tự biên soạn cho đồ án, dùng cho mục đích minh họa."), (6, "Canh gà nấm hương", "Nấu gà với gừng, cà rốt và nấm hương đến khi chín mềm.", 35, None, "Tự biên soạn cho đồ án, dùng cho mục đích minh họa."), (7, "Cá basa kho gừng", "Áp chảo cá, thêm gừng và kho nhỏ lửa.", 30, None, "Tự biên soạn cho đồ án, dùng cho mục đích minh họa."), (8, "Bún thịt xào", "Xào thịt với hành, dùng cùng bún và dưa leo.", 25, None, "Tự biên soạn cho đồ án, dùng cho mục đích minh họa."), (9, "Khoai tây xào cà rốt", "Xào khoai tây và cà rốt với hành đến khi mềm.", 25, None, "Tự biên soạn cho đồ án, dùng cho mục đích minh họa."), (10, "Trứng cuộn rau củ", "Đánh trứng, cuộn cùng cà rốt và hành trên chảo.", 18, None, "Tự biên soạn cho đồ án, dùng cho mục đích minh họa.")]
        connection.executemany("INSERT INTO recipes VALUES(?,?,?,?,?,?)", recipes)
        relations = [(1, 1, "2 quả", 1), (1, 2, "2 quả", 1), (2, 1, "200 g", 1), (2, 2, "1 quả", 1), (2, 3, "1 củ", 1), (2, 4, "200 g", 1), (3, 1, "2 quả", 1), (3, 3, "1 củ", 0), (4, 2, "2 quả", 1), (4, 5, "2 miếng", 1), (4, 7, "1 tép", 0), (5, 6, "300 g", 1), (5, 7, "2 tép", 1), (6, 8, "1 nhánh", 1), (6, 9, "50 g", 1), (6, 10, "1 củ", 1), (6, 14, "300 g", 1), (7, 8, "1 nhánh", 1), (7, 13, "300 g", 1), (8, 3, "1 củ", 1), (8, 4, "200 g", 1), (8, 12, "1 quả", 1), (8, 15, "2 phần", 1), (9, 3, "1 củ", 1), (9, 10, "1 củ", 1), (9, 11, "2 củ", 1), (10, 1, "2 quả", 1), (10, 3, "1 củ", 1), (10, 10, "1 củ", 0)]
        connection.executemany("INSERT INTO recipe_ingredients VALUES(?,?,?,?)", relations)
        connection.execute("INSERT INTO metadata VALUES('dataset_version','fixture-v1')")
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/recipes.db")
    seed(parser.parse_args().db)
