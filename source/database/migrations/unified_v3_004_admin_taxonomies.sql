-- Add Admin-managed recipe types and classifications to an existing unified-v3 schema.
-- Apply only to a verified TEST_ONLY clone first. Never run automatically at application startup.
ALTER TABLE recipe_tags
  MODIFY tag_type ENUM('diet','region','season','occasion','dish_type','weather','cooking_method','main_ingredient') NOT NULL,
  ADD COLUMN description TEXT NULL,
  ADD COLUMN is_core BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN deleted_at DATETIME(6) NULL,
  ADD KEY ix_recipe_tag_lifecycle (tag_type,deleted_at,normalized_label);

INSERT INTO recipe_tags(tag_type,code,label,normalized_label,description,is_core)
VALUES
  ('dish_type','main','Món chính','món chính','Vai trò cốt lõi trong cấu trúc mâm cơm.',TRUE),
  ('dish_type','vegetable','Món rau','món rau','Vai trò cốt lõi trong cấu trúc mâm cơm.',TRUE),
  ('dish_type','soup','Món canh','món canh','Vai trò cốt lõi trong cấu trúc mâm cơm.',TRUE),
  ('dish_type','side','Món ăn kèm','món ăn kèm','Loại món cốt lõi của danh mục công thức.',TRUE),
  ('dish_type','drink','Đồ uống','đồ uống','Loại món cốt lõi của danh mục công thức.',TRUE),
  ('dish_type','starch','Món tinh bột','món tinh bột','Loại món cốt lõi của danh mục công thức.',TRUE),
  ('dish_type','other','Khác','khác','Loại món cốt lõi của danh mục công thức.',TRUE)
ON DUPLICATE KEY UPDATE is_core=TRUE;

INSERT IGNORE INTO recipe_tag_links(recipe_id,tag_id)
SELECT r.recipe_id,t.tag_id FROM recipes r JOIN recipe_tags t
  ON t.tag_type='dish_type' AND t.code=r.role AND t.is_core=TRUE;
