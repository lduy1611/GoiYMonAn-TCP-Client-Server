-- Unified catalog target for the TEST_ONLY migration rehearsal.
-- MySQL 8.0.16+. This file intentionally contains no CREATE DATABASE, USE,
-- legacy DML, seeds, review workflow, or release pointer.

CREATE TABLE IF NOT EXISTS users (
  user_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  normalized_username VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  password_hash VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  role ENUM('USER','ADMIN') NOT NULL DEFAULT 'USER',
  status ENUM('ACTIVE','LOCKED') NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  last_login_at DATETIME(6) NULL,
  UNIQUE KEY uq_users_normalized_username (normalized_username),
  KEY ix_users_status_created (status,created_at),
  CONSTRAINT ck_users_username CHECK (CHAR_LENGTH(username) BETWEEN 3 AND 32)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ingredients (
  ingredient_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  normalized_name VARCHAR(255) NOT NULL,
  group_name VARCHAR(80) NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY ix_ingredients_name (normalized_name),
  KEY ix_ingredients_active_name (is_active,normalized_name),
  CONSTRAINT ck_ingredients_active CHECK (is_active IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ingredient_aliases (
  alias_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  ingredient_id BIGINT UNSIGNED NOT NULL,
  alias VARCHAR(255) NOT NULL,
  normalized_alias VARCHAR(255) NOT NULL,
  KEY ix_ingredient_alias_name (normalized_alias),
  KEY ix_ingredient_alias_owner (ingredient_id),
  CONSTRAINT fk_ingredient_alias_owner FOREIGN KEY (ingredient_id)
    REFERENCES ingredients(ingredient_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS units (
  unit_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  code VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(80) NOT NULL,
  dimension ENUM('mass','volume','count','other') NOT NULL,
  base_unit_id SMALLINT UNSIGNED NULL,
  factor_to_base DECIMAL(20,10) NULL,
  UNIQUE KEY uq_units_code (code),
  CONSTRAINT fk_units_base FOREIGN KEY (base_unit_id)
    REFERENCES units(unit_id) ON DELETE RESTRICT,
  CONSTRAINT ck_units_factor CHECK (factor_to_base IS NULL OR factor_to_base > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recipes (
  recipe_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  normalized_title VARCHAR(255) NOT NULL,
  description TEXT NOT NULL,
  role ENUM('main','vegetable','soup','side','drink','starch','other') NOT NULL DEFAULT 'other',
  -- Legacy rows retain their original total. Do not infer prep/cook split.
  minutes_total SMALLINT UNSIGNED NOT NULL,
  minutes_prep SMALLINT UNSIGNED NULL,
  minutes_cook SMALLINT UNSIGNED NULL,
  servings DECIMAL(10,3) NULL,
  instructions_legacy TEXT NULL,
  fallback_image_url VARCHAR(600) NULL,
  source_url VARCHAR(1000) NULL,
  is_public BOOLEAN NOT NULL DEFAULT TRUE,
  deleted_at DATETIME(6) NULL,
  edit_version BIGINT UNSIGNED NOT NULL DEFAULT 1,
  created_by BIGINT UNSIGNED NULL,
  updated_by BIGINT UNSIGNED NULL,
  create_request_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NULL,
  create_payload_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  KEY ix_recipes_public_role (is_public,deleted_at,role),
  KEY ix_recipes_public_title (is_public,deleted_at,normalized_title),
  KEY ix_recipes_updated (updated_at),
  UNIQUE KEY uq_recipes_create_request (create_request_key),
  CONSTRAINT fk_recipes_creator FOREIGN KEY (created_by) REFERENCES users(user_id) ON DELETE SET NULL,
  CONSTRAINT fk_recipes_updater FOREIGN KEY (updated_by) REFERENCES users(user_id) ON DELETE SET NULL,
  CONSTRAINT ck_recipes_minutes CHECK (minutes_total BETWEEN 1 AND 1440
    AND (minutes_prep IS NULL OR minutes_prep <= 1440)
    AND (minutes_cook IS NULL OR minutes_cook <= 1440)),
  CONSTRAINT ck_recipes_servings CHECK (servings IS NULL OR servings > 0),
  CONSTRAINT ck_recipes_public CHECK (is_public IN (0,1)),
  CONSTRAINT ck_recipes_create_request CHECK ((create_request_key IS NULL AND create_payload_hash IS NULL)
    OR (create_request_key IS NOT NULL AND create_payload_hash IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recipe_ingredients (
  recipe_id BIGINT UNSIGNED NOT NULL,
  line_no SMALLINT UNSIGNED NOT NULL,
  ingredient_id BIGINT UNSIGNED NOT NULL,
  quantity_text VARCHAR(255) NOT NULL DEFAULT '',
  amount_kind ENUM('exact','range','to_taste','as_needed','unknown') NOT NULL DEFAULT 'unknown',
  amount_min DECIMAL(18,6) NULL,
  amount_max DECIMAL(18,6) NULL,
  unit_id SMALLINT UNSIGNED NULL,
  requirement ENUM('required','optional','unknown') NOT NULL DEFAULT 'required',
  purpose ENUM('main','seasoning','cooking_medium','garnish','unknown') NOT NULL DEFAULT 'unknown',
  ingredient_form VARCHAR(120) NULL,
  measurement_basis ENUM('gross','edible','prepared','unknown') NOT NULL DEFAULT 'unknown',
  scaling_mode ENUM('linear','fixed','unknown') NOT NULL DEFAULT 'unknown',
  PRIMARY KEY (recipe_id,line_no),
  KEY ix_recipe_ingredient_lookup (ingredient_id,recipe_id),
  CONSTRAINT fk_recipe_lines_recipe FOREIGN KEY (recipe_id) REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
  CONSTRAINT fk_recipe_lines_ingredient FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id) ON DELETE RESTRICT,
  CONSTRAINT fk_recipe_lines_unit FOREIGN KEY (unit_id) REFERENCES units(unit_id) ON DELETE RESTRICT,
  CONSTRAINT ck_recipe_line_no CHECK (line_no > 0),
  CONSTRAINT ck_recipe_amounts CHECK ((amount_min IS NULL OR amount_min > 0)
    AND (amount_max IS NULL OR amount_max > 0)
    AND (amount_min IS NULL OR amount_max IS NULL OR amount_min <= amount_max))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recipe_steps (
  recipe_id BIGINT UNSIGNED NOT NULL,
  step_no SMALLINT UNSIGNED NOT NULL,
  instruction TEXT NOT NULL,
  duration_minutes SMALLINT UNSIGNED NULL,
  heat_level VARCHAR(40) NULL,
  PRIMARY KEY (recipe_id,step_no),
  CONSTRAINT fk_recipe_steps_recipe FOREIGN KEY (recipe_id) REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
  CONSTRAINT ck_recipe_step_no CHECK (step_no > 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recipe_tags (
  tag_id SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  tag_type ENUM('diet','region','season','occasion') NOT NULL,
  code VARCHAR(48) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  label VARCHAR(100) NOT NULL,
  normalized_label VARCHAR(100) NOT NULL,
  UNIQUE KEY uq_recipe_tag_code (tag_type,code),
  KEY ix_recipe_tag_label (tag_type,normalized_label)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recipe_tag_links (
  recipe_id BIGINT UNSIGNED NOT NULL,
  tag_id SMALLINT UNSIGNED NOT NULL,
  PRIMARY KEY (recipe_id,tag_id),
  KEY ix_tag_recipes (tag_id,recipe_id),
  CONSTRAINT fk_recipe_tag_recipe FOREIGN KEY (recipe_id) REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
  CONSTRAINT fk_recipe_tag_tag FOREIGN KEY (tag_id) REFERENCES recipe_tags(tag_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recipe_images (
  recipe_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
  storage_key VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  media_type ENUM('image/jpeg','image/png','image/webp') NOT NULL,
  byte_size INT UNSIGNED NOT NULL,
  width SMALLINT UNSIGNED NOT NULL,
  height SMALLINT UNSIGNED NOT NULL,
  sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_recipe_image_storage_key (storage_key),
  CONSTRAINT fk_recipe_image_recipe FOREIGN KEY (recipe_id) REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
  CONSTRAINT ck_recipe_image_size CHECK (byte_size BETWEEN 1 AND 5242880),
  CONSTRAINT ck_recipe_image_dimensions CHECK (width BETWEEN 1 AND 8000 AND height BETWEEN 1 AND 8000
    AND width * height <= 20000000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recipe_edit_history (
  history_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  recipe_id BIGINT UNSIGNED NOT NULL,
  edit_version BIGINT UNSIGNED NOT NULL,
  actor_user_id BIGINT UNSIGNED NULL,
  snapshot JSON NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_recipe_history_version (recipe_id,edit_version),
  CONSTRAINT fk_recipe_history_recipe FOREIGN KEY (recipe_id) REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
  CONSTRAINT fk_recipe_history_actor FOREIGN KEY (actor_user_id) REFERENCES users(user_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Transition-only maps. Runtime APIs address recipes/ingredients directly.
CREATE TABLE IF NOT EXISTS recipe_id_map (
  source_kind ENUM('legacy','v2_link','v2_catalog') NOT NULL,
  source_id BIGINT UNSIGNED NOT NULL,
  recipe_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (source_kind,source_id),
  KEY ix_recipe_id_map_target (recipe_id),
  CONSTRAINT fk_recipe_id_map_target FOREIGN KEY (recipe_id) REFERENCES recipes(recipe_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS ingredient_id_map (
  source_kind ENUM('legacy','v2') NOT NULL,
  source_id BIGINT UNSIGNED NOT NULL,
  ingredient_id BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (source_kind,source_id),
  KEY ix_ingredient_id_map_target (ingredient_id),
  CONSTRAINT fk_ingredient_id_map_target FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Import ledger makes a completed conversion a safe no-op on repeat runs.
CREATE TABLE IF NOT EXISTS unified_import_runs (
  run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  source_database VARCHAR(64) NOT NULL,
  source_fingerprint CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  converter_version VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  status ENUM('APPLIED') NOT NULL DEFAULT 'APPLIED',
  report JSON NOT NULL,
  completed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_unified_import_source (source_database,source_fingerprint,converter_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- User achievement posts, their local image metadata, and comments.
CREATE TABLE IF NOT EXISTS achievement_posts (
  post_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  recipe_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  description TEXT NOT NULL,
  changed_ingredients VARCHAR(1000) NULL,
  request_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  payload_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_achievement_request (user_id,request_key),
  KEY ix_achievement_recent (created_at,post_id),
  KEY ix_achievement_recipe (recipe_id,created_at),
  KEY ix_achievement_user (user_id,created_at),
  CONSTRAINT fk_achievement_recipe FOREIGN KEY (recipe_id) REFERENCES recipes(recipe_id) ON DELETE RESTRICT,
  CONSTRAINT fk_achievement_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE RESTRICT,
  CONSTRAINT ck_achievement_description CHECK (CHAR_LENGTH(description) <= 3000),
  CONSTRAINT ck_achievement_request_key CHECK (CHAR_LENGTH(request_key)=36)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS achievement_images (
  image_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  post_id BIGINT UNSIGNED NOT NULL,
  storage_key VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  media_type ENUM('image/jpeg','image/png','image/webp') NOT NULL,
  byte_size INT UNSIGNED NOT NULL,
  width SMALLINT UNSIGNED NOT NULL,
  height SMALLINT UNSIGNED NOT NULL,
  sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_achievement_image_key (storage_key),
  KEY ix_achievement_image_post (post_id,image_id),
  CONSTRAINT fk_achievement_image_post FOREIGN KEY (post_id) REFERENCES achievement_posts(post_id) ON DELETE CASCADE,
  CONSTRAINT ck_achievement_image_size CHECK (byte_size BETWEEN 1 AND 5242880),
  CONSTRAINT ck_achievement_image_dimensions CHECK (width BETWEEN 1 AND 8000 AND height BETWEEN 1 AND 8000 AND width*height<=20000000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS achievement_comments (
  comment_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  post_id BIGINT UNSIGNED NOT NULL,
  user_id BIGINT UNSIGNED NOT NULL,
  body VARCHAR(2000) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  KEY ix_achievement_comment_post (post_id,created_at,comment_id),
  KEY ix_achievement_comment_user (user_id,created_at),
  CONSTRAINT fk_achievement_comment_post FOREIGN KEY (post_id) REFERENCES achievement_posts(post_id) ON DELETE CASCADE,
  CONSTRAINT fk_achievement_comment_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE RESTRICT,
  CONSTRAINT ck_achievement_comment_body CHECK (CHAR_LENGTH(body) BETWEEN 1 AND 2000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
