-- Add the text field required by Admin's revision DRAFT editor.
-- Existing rows receive an empty description; no approval/release state changes.
ALTER TABLE v2_recipe_revisions
  ADD COLUMN description VARCHAR(1000) NOT NULL DEFAULT '' AFTER title;
