-- Admin-authored publication and reversible visibility/deletion state.
-- Legacy content stays in its original tables; v2 content stays in revisions.
CREATE TABLE v2_admin_recipe_catalog_overrides (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  legacy_recipe_id INT UNSIGNED NULL UNIQUE,
  v2_recipe_id BIGINT UNSIGNED NULL UNIQUE,
  revision_id BIGINT UNSIGNED NULL,
  role_code VARCHAR(16) CHARACTER SET ascii NULL,
  direct_publication BOOLEAN NOT NULL DEFAULT FALSE,
  is_visible BOOLEAN NOT NULL DEFAULT TRUE,
  is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
  create_request_key CHAR(36) CHARACTER SET ascii NULL UNIQUE,
  create_payload_hash CHAR(64) CHARACTER SET ascii NULL,
  updated_by VARCHAR(255) NOT NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  FOREIGN KEY (legacy_recipe_id) REFERENCES recipes(id) ON DELETE RESTRICT,
  FOREIGN KEY (v2_recipe_id) REFERENCES v2_recipes(id) ON DELETE RESTRICT,
  FOREIGN KEY (revision_id, v2_recipe_id) REFERENCES v2_recipe_revisions(id, recipe_id) ON DELETE RESTRICT,
  CHECK ((legacy_recipe_id IS NOT NULL AND v2_recipe_id IS NULL AND revision_id IS NULL AND role_code IS NULL AND direct_publication=0)
      OR (legacy_recipe_id IS NULL AND v2_recipe_id IS NOT NULL AND revision_id IS NOT NULL)),
  CHECK (role_code IS NULL OR role_code IN ('main','vegetable','soup')),
  CHECK (direct_publication IN (0,1) AND is_visible IN (0,1) AND is_deleted IN (0,1)),
  CHECK ((create_request_key IS NULL AND create_payload_hash IS NULL)
      OR (create_request_key IS NOT NULL AND create_payload_hash IS NOT NULL)),
  CHECK (direct_publication=0 OR role_code IS NOT NULL)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
