-- MySQL 8.0+ schema for GoiYMonAnTCP.
-- If MYSQL_DATABASE is changed in .env, replace the USE database below before running.
CREATE DATABASE IF NOT EXISTS goiy_mon_an CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE goiy_mon_an;

CREATE TABLE IF NOT EXISTS metadata (
    `key` VARCHAR(100) PRIMARY KEY,
    value VARCHAR(255) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ingredients (
    id INT UNSIGNED PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    normalized_name VARCHAR(255) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ingredient_aliases (
    alias_norm VARCHAR(255) PRIMARY KEY,
    ingredient_id INT UNSIGNED NOT NULL,
    KEY idx_alias_ingredient (ingredient_id),
    CONSTRAINT fk_alias_ingredient FOREIGN KEY (ingredient_id) REFERENCES ingredients(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS recipes (
    id INT UNSIGNED PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    instructions TEXT NOT NULL,
    minutes SMALLINT UNSIGNED NOT NULL,
    source_url VARCHAR(1000) NULL,
    source_note TEXT NOT NULL,
    CONSTRAINT chk_recipe_minutes CHECK (minutes BETWEEN 1 AND 240)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS recipe_ingredients (
    recipe_id INT UNSIGNED NOT NULL,
    ingredient_id INT UNSIGNED NOT NULL,
    quantity VARCHAR(255) NOT NULL DEFAULT '',
    is_required TINYINT(1) NOT NULL,
    PRIMARY KEY (recipe_id, ingredient_id),
    KEY idx_ri_ingredient (ingredient_id),
    CONSTRAINT fk_ri_recipe FOREIGN KEY (recipe_id) REFERENCES recipes(id),
    CONSTRAINT fk_ri_ingredient FOREIGN KEY (ingredient_id) REFERENCES ingredients(id),
    CONSTRAINT chk_ri_required CHECK (is_required IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

