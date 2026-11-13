-- Phase 4 recipe instruction refinement.
-- Safe update: preserves recipe_id, ingredients, relations and minutes; no rows are deleted or inserted.
USE goiy_mon_an;
START TRANSACTION;

UPDATE recipes
SET instructions = CASE id
    WHEN 1 THEN CONCAT('Bước 1: Đập trứng vào bát, đánh tan với một ít nước mắm.', CHAR(10), 'Bước 2: Cắt cà chua thành múi nhỏ, phi hành rồi xào cà chua đến khi mềm.', CHAR(10), 'Bước 3: Đổ trứng vào chảo, đảo nhẹ đến khi trứng vừa chín và dùng nóng.')
    WHEN 2 THEN CONCAT('Bước 1: Thái thịt thành miếng vừa ăn, cắt cà chua và hành rồi ướp thịt với nước mắm.', CHAR(10), 'Bước 2: Phi hành, xào thịt đến khi săn rồi cho cà chua vào đảo mềm.', CHAR(10), 'Bước 3: Thêm ít nước, đun nhỏ lửa đến khi thịt chín và nêm lại trước khi dùng.')
    WHEN 3 THEN CONCAT('Bước 1: Đập trứng vào bát, đánh tan và nêm nhẹ.', CHAR(10), 'Bước 2: Thái hành, phi thơm trên chảo nóng.', CHAR(10), 'Bước 3: Đổ trứng vào, đảo đến khi vừa chín, cuộn hoặc xới tơi rồi dùng ngay.')
    WHEN 4 THEN CONCAT('Bước 1: Cắt đậu phụ thành miếng, áp chảo đến khi vàng nhẹ.', CHAR(10), 'Bước 2: Cắt cà chua, phi tỏi rồi xào cà chua đến khi tạo thành sốt.', CHAR(10), 'Bước 3: Cho đậu phụ vào sốt, nêm vừa ăn và đun nhỏ lửa khoảng 5 phút.')
    WHEN 5 THEN CONCAT('Bước 1: Nhặt rau muống, rửa sạch và chần nhanh trong nước sôi.', CHAR(10), 'Bước 2: Phi tỏi với dầu nóng đến khi thơm.', CHAR(10), 'Bước 3: Cho rau muống vào xào lửa lớn, nêm vừa ăn rồi tắt bếp để rau còn giòn.')
    WHEN 6 THEN CONCAT('Bước 1: Chặt thịt gà, rửa nấm hương và thái cà rốt, đập dập gừng.', CHAR(10), 'Bước 2: Chần gà, rửa lại rồi nấu với gừng trong nồi nước sạch.', CHAR(10), 'Bước 3: Khi gà gần chín, cho cà rốt và nấm hương vào nấu mềm, nêm lại rồi dùng nóng.')
    WHEN 7 THEN CONCAT('Bước 1: Rửa cá basa, cắt khúc và ướp với gừng cùng nước mắm.', CHAR(10), 'Bước 2: Áp chảo cá cho săn hai mặt.', CHAR(10), 'Bước 3: Thêm ít nước, cho gừng vào và kho nhỏ lửa đến khi nước sánh, cá thấm vị.')
    WHEN 8 THEN CONCAT('Bước 1: Luộc hoặc trụng bún, rửa dưa leo và thái lát.', CHAR(10), 'Bước 2: Thái thịt, ướp nước mắm rồi xào cùng hành đến khi chín.', CHAR(10), 'Bước 3: Cho bún vào tô, thêm thịt xào và dưa leo, trộn nhẹ rồi dùng nóng.')
    WHEN 9 THEN CONCAT('Bước 1: Gọt khoai tây, cà rốt và thái miếng vừa ăn, thái hành.', CHAR(10), 'Bước 2: Phi hành, cho khoai tây và cà rốt vào xào sơ.', CHAR(10), 'Bước 3: Thêm ít nước, đậy nắp nấu đến khi rau củ mềm, nêm lại rồi dùng.')
    WHEN 10 THEN CONCAT('Bước 1: Bào hoặc thái cà rốt, thái hành và đập trứng vào bát đánh tan.', CHAR(10), 'Bước 2: Xào sơ cà rốt và hành, sau đó trộn cùng trứng.', CHAR(10), 'Bước 3: Đổ hỗn hợp vào chảo, cuộn từ từ đến khi trứng chín và cắt khoanh để dùng.')
END
WHERE id BETWEEN 1 AND 10;

INSERT INTO metadata (`key`, value) VALUES ('dataset_version', 'vi-v2-50-recipes-r1')
ON DUPLICATE KEY UPDATE value = VALUES(value);

COMMIT;
