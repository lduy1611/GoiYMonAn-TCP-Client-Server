-- Unified v3 additive migration; apply to TEST_ONLY before any deployment.
ALTER TABLE recipe_ingredients
  ADD COLUMN ingredient_form VARCHAR(120) NULL,
  ADD COLUMN measurement_basis ENUM('gross','edible','prepared','unknown') NOT NULL DEFAULT 'unknown',
  ADD COLUMN scaling_mode ENUM('linear','fixed','unknown') NOT NULL DEFAULT 'unknown';
