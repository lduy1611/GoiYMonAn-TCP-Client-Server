-- Additive Admin overlay for legacy ingredient names and activation state.
-- Legacy ingredients and recipe_ingredients remain untouched.
CREATE TABLE v2_admin_legacy_ingredient_overrides (
 ingredient_id INT UNSIGNED PRIMARY KEY,
 name_override VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
 normalized_name VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL,
 is_active TINYINT UNSIGNED NOT NULL DEFAULT 1,
 updated_by VARCHAR(255) NOT NULL,
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 CONSTRAINT fk_v2_admin_legacy_ingredient_overrides_ingredient
   FOREIGN KEY (ingredient_id) REFERENCES ingredients(id) ON DELETE RESTRICT,
 CHECK (is_active IN (0,1)),
 CHECK ((name_override IS NULL AND normalized_name IS NULL)
     OR (name_override IS NOT NULL AND normalized_name IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
