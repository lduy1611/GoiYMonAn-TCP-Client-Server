PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ingredients(id INTEGER PRIMARY KEY CHECK(id>0), name TEXT NOT NULL, normalized_name TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS ingredient_aliases(alias_norm TEXT PRIMARY KEY, ingredient_id INTEGER NOT NULL REFERENCES ingredients(id));
CREATE TABLE IF NOT EXISTS recipes(id INTEGER PRIMARY KEY CHECK(id>0), title TEXT NOT NULL, instructions TEXT NOT NULL, minutes INTEGER NOT NULL CHECK(minutes BETWEEN 1 AND 240), source_url TEXT, source_note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recipe_ingredients(recipe_id INTEGER NOT NULL REFERENCES recipes(id), ingredient_id INTEGER NOT NULL REFERENCES ingredients(id), quantity TEXT NOT NULL DEFAULT '', is_required INTEGER NOT NULL CHECK(is_required IN (0,1)), PRIMARY KEY(recipe_id,ingredient_id));
CREATE INDEX IF NOT EXISTS idx_ri_ingredient ON recipe_ingredients(ingredient_id);
CREATE INDEX IF NOT EXISTS idx_alias_ingredient ON ingredient_aliases(ingredient_id);
