-- Demo data matching the SQLite fixture IDs exactly.
USE goiy_mon_an;
SET FOREIGN_KEY_CHECKS=0;
DELETE FROM recipe_ingredients;
DELETE FROM recipes;
DELETE FROM ingredient_aliases;
DELETE FROM ingredients;
DELETE FROM metadata;
SET FOREIGN_KEY_CHECKS=1;

INSERT INTO metadata (`key`, value) VALUES ('dataset_version', 'fixture-v1');
INSERT INTO ingredients (id, name, normalized_name) VALUES
(1,'Trứng','trứng'),(2,'Cà chua','cà chua'),(3,'Hành','hành'),(4,'Thịt','thịt'),
(5,'Đậu phụ','đậu phụ'),(6,'Rau muống','rau muống'),(7,'Tỏi','tỏi'),(8,'Gừng','gừng'),
(9,'Nấm hương','nấm hương'),(10,'Cà rốt','cà rốt'),(11,'Khoai tây','khoai tây'),
(12,'Dưa leo','dưa leo'),(13,'Cá basa','cá basa'),(14,'Thịt gà','thịt gà'),(15,'Bún','bún');
INSERT INTO ingredient_aliases (alias_norm, ingredient_id) VALUES ('tomato',2);

INSERT INTO recipes (id,title,instructions,minutes,source_url,source_note) VALUES
(1,'Trứng sốt cà chua','Đánh trứng, nấu cùng cà chua.',15,NULL,'Tự biên soạn cho đồ án, dùng cho mục đích minh họa.'),
(2,'Món thịt rau củ','Nấu chín thịt và rau củ.',30,NULL,'Tự biên soạn cho đồ án, dùng cho mục đích minh họa.'),
(3,'Trứng xào hành','Xào trứng với hành.',10,NULL,'Tự biên soạn cho đồ án, dùng cho mục đích minh họa.'),
(4,'Đậu phụ sốt cà chua','Chiên áp chảo đậu phụ, thêm cà chua và nêm vừa ăn.',20,NULL,'Tự biên soạn cho đồ án, dùng cho mục đích minh họa.'),
(5,'Rau muống xào tỏi','Chần rau muống, xào nhanh với tỏi băm.',12,NULL,'Tự biên soạn cho đồ án, dùng cho mục đích minh họa.'),
(6,'Canh gà nấm hương','Nấu gà với gừng, cà rốt và nấm hương đến khi chín mềm.',35,NULL,'Tự biên soạn cho đồ án, dùng cho mục đích minh họa.'),
(7,'Cá basa kho gừng','Áp chảo cá, thêm gừng và kho nhỏ lửa.',30,NULL,'Tự biên soạn cho đồ án, dùng cho mục đích minh họa.'),
(8,'Bún thịt xào','Xào thịt với hành, dùng cùng bún và dưa leo.',25,NULL,'Tự biên soạn cho đồ án, dùng cho mục đích minh họa.'),
(9,'Khoai tây xào cà rốt','Xào khoai tây và cà rốt với hành đến khi mềm.',25,NULL,'Tự biên soạn cho đồ án, dùng cho mục đích minh họa.'),
(10,'Trứng cuộn rau củ','Đánh trứng, cuộn cùng cà rốt và hành trên chảo.',18,NULL,'Tự biên soạn cho đồ án, dùng cho mục đích minh họa.');

INSERT INTO recipe_ingredients (recipe_id,ingredient_id,quantity,is_required) VALUES
(1,1,'2 quả',1),(1,2,'2 quả',1),(2,1,'200 g',1),(2,2,'1 quả',1),(2,3,'1 củ',1),(2,4,'200 g',1),
(3,1,'2 quả',1),(3,3,'1 củ',0),(4,2,'2 quả',1),(4,5,'2 miếng',1),(4,7,'1 tép',0),
(5,6,'300 g',1),(5,7,'2 tép',1),(6,8,'1 nhánh',1),(6,9,'50 g',1),(6,10,'1 củ',1),(6,14,'300 g',1),
(7,8,'1 nhánh',1),(7,13,'300 g',1),(8,3,'1 củ',1),(8,4,'200 g',1),(8,12,'1 quả',1),(8,15,'2 phần',1),
(9,3,'1 củ',1),(9,10,'1 củ',1),(9,11,'2 củ',1),(10,1,'2 quả',1),(10,3,'1 củ',1),(10,10,'1 củ',0);
