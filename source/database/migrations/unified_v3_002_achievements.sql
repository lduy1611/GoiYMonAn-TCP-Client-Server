-- Achievement posts for unified v3. Apply only to an explicitly isolated TEST_ONLY database.
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
