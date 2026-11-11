-- Admin-owned overlays for legacy recipes. No legacy rows are updated or deleted.
CREATE TABLE v2_admin_legacy_recipe_overrides (
  recipe_id INT UNSIGNED NOT NULL PRIMARY KEY,
  title VARCHAR(255) NULL,
  description VARCHAR(1000) NULL,
  instructions TEXT NULL,
  minutes SMALLINT UNSIGNED NULL,
  is_visible BOOLEAN NOT NULL DEFAULT TRUE,
  ingredients_overridden BOOLEAN NOT NULL DEFAULT FALSE,
  updated_by VARCHAR(255) NOT NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_v2_admin_legacy_recipe_recipe FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE RESTRICT,
  CONSTRAINT ck_v2_admin_legacy_recipe_minutes CHECK (minutes IS NULL OR minutes BETWEEN 1 AND 240),
  CONSTRAINT ck_v2_admin_legacy_recipe_title CHECK (title IS NULL OR CHAR_LENGTH(TRIM(title)) BETWEEN 1 AND 255),
  CONSTRAINT ck_v2_admin_legacy_recipe_visibility CHECK (is_visible IN (0,1)),
  CONSTRAINT ck_v2_admin_legacy_recipe_ingredients CHECK (ingredients_overridden IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE v2_admin_legacy_recipe_override_ingredients (
  recipe_id INT UNSIGNED NOT NULL,
  line_no SMALLINT UNSIGNED NOT NULL,
  ingredient_id INT UNSIGNED NOT NULL,
  quantity VARCHAR(255) NOT NULL,
  is_required BOOLEAN NOT NULL,
  PRIMARY KEY (recipe_id,line_no),
  UNIQUE KEY uq_v2_admin_legacy_override_ingredient (recipe_id,ingredient_id),
  CONSTRAINT fk_v2_admin_legacy_override_recipe FOREIGN KEY (recipe_id)
    REFERENCES v2_admin_legacy_recipe_overrides(recipe_id) ON DELETE CASCADE,
  CONSTRAINT fk_v2_admin_legacy_override_ingredient FOREIGN KEY (ingredient_id)
    REFERENCES ingredients(id) ON DELETE RESTRICT,
  CONSTRAINT ck_v2_admin_legacy_override_line CHECK (line_no BETWEEN 1 AND 100),
  CONSTRAINT ck_v2_admin_legacy_override_required CHECK (is_required IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
