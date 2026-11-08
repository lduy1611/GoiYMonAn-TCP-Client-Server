-- Add Admin activation state without modifying legacy ingredients or v2 identity/review data.
CREATE TABLE v2_ingredient_admin_state (
 ingredient_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
 is_active TINYINT(1) NOT NULL DEFAULT 1,
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 CONSTRAINT fk_v2_ingredient_admin_state_ingredient
   FOREIGN KEY (ingredient_id) REFERENCES v2_ingredients(id) ON DELETE RESTRICT,
 CHECK (is_active IN (0,1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO v2_ingredient_admin_state (ingredient_id, is_active)
SELECT id, 1 FROM v2_ingredients;
