-- Extend Admin-owned legacy recipe links to the shared public ingredient catalog.
-- Keep the original legacy FK intact; each line references exactly one identity.
ALTER TABLE v2_admin_legacy_recipe_override_ingredients
  MODIFY COLUMN ingredient_id INT UNSIGNED NULL,
  ADD COLUMN v2_ingredient_id BIGINT UNSIGNED NULL AFTER ingredient_id,
  ADD UNIQUE KEY uq_v2_admin_legacy_override_v2_ingredient (recipe_id,v2_ingredient_id),
  ADD CONSTRAINT fk_v2_admin_legacy_override_v2_ingredient
    FOREIGN KEY (v2_ingredient_id) REFERENCES v2_ingredients(id) ON DELETE RESTRICT,
  ADD CONSTRAINT ck_v2_admin_legacy_override_one_ingredient
    CHECK ((ingredient_id IS NOT NULL) <> (v2_ingredient_id IS NOT NULL));
