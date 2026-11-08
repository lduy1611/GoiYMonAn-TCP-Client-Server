-- Additive account table. Public registration can create USER accounts only.
CREATE TABLE v2_user_accounts (
  user_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  normalized_username VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  password_hash VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  role ENUM('USER','ADMIN') NOT NULL DEFAULT 'USER',
  account_status ENUM('ACTIVE','LOCKED') NOT NULL DEFAULT 'ACTIVE',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  last_login_at DATETIME(6) NULL,
  UNIQUE KEY uq_v2_user_accounts_normalized_username (normalized_username),
  KEY ix_v2_user_accounts_status_created (account_status, created_at),
  CONSTRAINT ck_v2_user_accounts_username CHECK (CHAR_LENGTH(username) BETWEEN 3 AND 32),
  CONSTRAINT ck_v2_user_accounts_role CHECK (role IN ('USER','ADMIN')),
  CONSTRAINT ck_v2_user_accounts_status CHECK (account_status IN ('ACTIVE','LOCKED'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
