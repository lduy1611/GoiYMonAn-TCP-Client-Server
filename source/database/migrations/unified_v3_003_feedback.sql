CREATE TABLE IF NOT EXISTS feedback_submissions (
  feedback_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  user_id BIGINT UNSIGNED NULL,
  category ENUM('bug','feature','other') NOT NULL,
  content VARCHAR(3000) NOT NULL,
  status ENUM('open','resolved') NOT NULL DEFAULT 'open',
  request_key CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  image_storage_key VARCHAR(100) CHARACTER SET ascii COLLATE ascii_bin NULL,
  image_media_type ENUM('image/jpeg','image/png','image/webp') NULL,
  image_byte_size INT UNSIGNED NULL,
  image_width SMALLINT UNSIGNED NULL,
  image_height SMALLINT UNSIGNED NULL,
  image_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_feedback_request_key (request_key),
  KEY ix_feedback_recent (created_at,feedback_id),
  KEY ix_feedback_status_recent (status,created_at,feedback_id),
  KEY ix_feedback_user (user_id,created_at),
  CONSTRAINT fk_feedback_user FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE RESTRICT,
  CONSTRAINT ck_feedback_content CHECK (CHAR_LENGTH(TRIM(content)) BETWEEN 1 AND 3000),
  CONSTRAINT ck_feedback_request_key CHECK (CHAR_LENGTH(request_key)=36),
  CONSTRAINT ck_feedback_image_metadata CHECK (
    (image_storage_key IS NULL AND image_media_type IS NULL AND image_byte_size IS NULL AND image_width IS NULL AND image_height IS NULL AND image_sha256 IS NULL)
    OR
    (image_storage_key IS NOT NULL AND image_media_type IS NOT NULL AND image_byte_size BETWEEN 1 AND 5242880
     AND image_width BETWEEN 1 AND 8000 AND image_height BETWEEN 1 AND 8000 AND image_width*image_height<=20000000
     AND image_sha256 IS NOT NULL)
  )
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
