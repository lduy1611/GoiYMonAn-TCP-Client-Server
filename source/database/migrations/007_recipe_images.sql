CREATE TABLE v2_recipe_image_overrides (
  recipe_id BIGINT UNSIGNED NOT NULL,
  catalog_kind ENUM('legacy','v2') NOT NULL,
  legacy_recipe_id INT UNSIGNED NULL,
  v2_recipe_id BIGINT UNSIGNED NULL,
  storage_key VARCHAR(48) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  media_type ENUM('image/jpeg','image/png','image/webp') NOT NULL,
  byte_size INT UNSIGNED NOT NULL,
  width SMALLINT UNSIGNED NOT NULL,
  height SMALLINT UNSIGNED NOT NULL,
  sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  updated_by VARCHAR(255) NOT NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (recipe_id),
  UNIQUE KEY uq_v2_recipe_image_legacy_recipe (legacy_recipe_id),
  UNIQUE KEY uq_v2_recipe_image_v2_recipe (v2_recipe_id),
  UNIQUE KEY uq_v2_recipe_image_storage_key (storage_key),
  CONSTRAINT fk_v2_recipe_image_legacy_recipe FOREIGN KEY (legacy_recipe_id) REFERENCES recipes(id) ON DELETE RESTRICT,
  CONSTRAINT fk_v2_recipe_image_v2_recipe FOREIGN KEY (v2_recipe_id) REFERENCES v2_recipes(id) ON DELETE RESTRICT,
  CONSTRAINT chk_v2_recipe_image_identity CHECK (
    (catalog_kind='legacy' AND legacy_recipe_id IS NOT NULL AND v2_recipe_id IS NULL AND recipe_id=legacy_recipe_id) OR
    (catalog_kind='v2' AND v2_recipe_id IS NOT NULL AND legacy_recipe_id IS NULL AND recipe_id=v2_recipe_id+4294967296 AND recipe_id BETWEEN 4294967297 AND 8589934591)
  ),
  CONSTRAINT chk_v2_recipe_image_dimensions CHECK (
    width BETWEEN 1 AND 8000 AND height BETWEEN 1 AND 8000 AND width * height <= 20000000
  ),
  CONSTRAINT chk_v2_recipe_image_size CHECK (byte_size BETWEEN 1 AND 5242880)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
