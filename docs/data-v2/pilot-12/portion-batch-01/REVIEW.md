# Lô khẩu phần 01 — dữ liệu thực tế chờ duyệt

Ngày đối chiếu: 05/11/2026, Asia/Saigon. Chỉ tạo hồ sơ mới; không sửa hồ sơ 12 món cũ, seed hoặc MySQL.

Đã đọc trực tiếp ba bài nguồn, đối chiếu cả danh sách lẫn các bước. **Có ba bộ khẩu phần + lượng thuộc cùng bài để duyệt từng trường; chưa có món đủ điều kiện phát hành danh sách mua hoàn toàn có định lượng.** Không có quyết định APPROVED, quyền nhập hoặc kết quả thử nấu.

| ID liên hệ legacy | Vì sao chọn | Khẩu phần quan sát | Thông tin còn thiếu |
|---|---|---|---|
| 30 — Canh rau ngót thịt bằm | Nguồn có thịt, rau, nước và gia vị từng công đoạn | 3 phần; rau 200 g, thịt 150 g, nước 1 l | Tiêu rắc/nêm cuối; ID hành tím và nguyên liệu ngoài danh mục; cơ sở cân rau |
| 29 — Canh bí đỏ hầm xương | Nguồn có khẩu phần, lượng xương/nước; bước nấu bổ sung lượng gia vị | 4 phần; xương 300 g, bí 1 quả (khoảng 300 g), nước 1 l | Xương không đồng nhất sườn; bí chỉ có khối lượng xấp xỉ; lượng ngâm/rắc/nêm cuối |
| 9 — Khoai tây xào cà rốt | Bài tác giả trực tiếp, ngắn, có khẩu phần và khoảng lượng | 2 phần; khoai 2–3 củ, cà rốt 0,5–1 củ, nước 150 ml | Kích thước củ; gia vị chưa gọi tên; chất béo phi hành; ID hành tím/rau mùi |

Nguồn tương ứng:

- 30: [Điện máy XANH, bài 10653](https://www.dienmayxanh.com/vao-bep/cach-nau-canh-rau-ngot-thit-bam-thanh-mat-don-gian-cho-bua-10653), mục nguyên liệu và bước 1–2; bài ghi Trang Đinh, biên tập Trần Đặng Thùy Trang, ngày 10/06/2021. Đây là nguồn thay thế đề xuất, không phải EXT-30 Co.op cũ.
- 29: [Điện máy XANH, bài 10447](https://www.dienmayxanh.com/vao-bep/cach-nau-canh-bi-do-ham-xuong-ngon-ngot-hap-dan-cho-bua-com-10447), mục nguyên liệu và bước 1–3; bài dẫn Facebook Trang Đinh. Chưa đọc bài Facebook gốc.
- 9: [Cookpad, công thức 23877441 của Trần Nguyên](https://cookpad.com/vn/cong-thuc/23877441), mục Nguyên Liệu và hai bước; ngày đăng 21/06/2024.

Không chọn Gà kho gừng/Canh rau ngót ở Co.op cho dữ liệu lô này vì mở trang timeout; kết quả tìm kiếm không được nhập thay nội dung đọc trực tiếp. Tôm hấp có khoảng 4–6 người nên chưa thích hợp lô khẩu phần đơn trị đầu tiên. Lô này chưa có món chính; không dùng nó để tuyên bố đủ dữ liệu cho một mâm hoàn chỉnh.

## Tệp và quy ước đọc

- `proposed-revisions.json`: nguồn, locator bằng chứng, ba đề xuất và toàn bộ lượng quan sát được; chưa cấp revision ID trong database.
- `ingredient-lines.csv`: bản trải phẳng để xem/duyệt; bao gồm trạng thái từng trường và các dấu mốc thiếu dữ liệu.
- `manifest.json`: hash đầu vào/đầu ra, số đếm và ranh giới không được nhập.
- `validation-report.json`: kết quả kiểm tra cấu trúc hồ sơ; không phải kiểm thử thuật toán khẩu phần hoặc thử nấu.

`ingredient_id` trong tệp là ID legacy đề xuất ánh xạ, không phải FK v2 đã tồn tại. Chỉ điền các ID có đối tượng tương ứng rõ: 43 rau ngót, 38 thịt heo xay (nguồn ghi dạng băm, vẫn chờ duyệt), 44 bí đỏ, 11 khoai tây, 10 cà rốt. Hành tím để trống ID, ghi ứng viên 3; xương heo để trống, ghi ứng viên 39 nhưng không xác nhận đồng nhất. Nước, các gia vị, ngò gai/rau mùi chưa có danh tính phù hợp trong danh mục 50 nguyên liệu: giữ null, không ép vào Rau thơm.

Lượng và khẩu phần đều lấy từ đúng bài của đề xuất. Những khác biệt với legacy chỉ nằm ở ghi chú so sánh; không được dùng làm fallback. Mỗi đề xuất là **biến thể có nguồn chờ duyệt**, không khẳng định đã xác minh công thức legacy. Hướng dẫn nguồn cần được biên soạn/duyệt cùng biến thể trước import, không dùng lại ba bước legacy khi chúng khác thành phần.

Giữ 1 quả bí là một use; khoảng 300 g chỉ là cách mô tả thay thế xấp xỉ, không cộng thêm lần nữa. Hạt nêm ở ướp và nấu là các use riêng. Không cộng muỗng cà phê với muỗng canh hay đổi sang ml khi chưa duyệt quy đổi. Hai khoảng lượng món 9 không có `quantity_value` đơn trị; không chọn trung bình. Muối/nước ngâm món 29 được ghi riêng với giai đoạn `wash`, chưa tự loại khỏi nhu cầu hoặc coi bằng 0.

`unresolved_instruction` đánh dấu việc nêm chưa định danh; không phải nguyên liệu mới để INSERT. Null về lượng/dạng/cơ sở đo giữ `NEEDS_VERIFICATION`. Có lượng số trong nguồn không chứng minh dòng đó tăng tuyến tính. Không có hệ số trẻ em hay phân bổ giữa nhiều món được tạo.

## Phạm vi đề nghị duyệt

1. Duyệt việc dùng từng bài làm nguồn cho biến thể riêng, quan hệ với món legacy và các cặp khẩu phần–lượng đã đọc được.
2. Duyệt danh tính/dạng nguyên liệu, đặc biệt thịt băm/xay, hành tím, xương heo và các nguyên liệu cần danh tính v2 mới.
3. Xin tác giả hoặc kiểm chứng thực tế để hoàn thiện khoảng trống; lưu bằng chứng cùng biến thể. Trường thiếu vẫn NEEDS_VERIFICATION đến khi có bằng chứng, không tự thêm thành phần hoặc lượng.

Các giá trị quan sát có thể duyệt theo trường ngay. Chưa đề nghị duyệt toàn món cho tính khẩu phần/danh sách mua đầy đủ; chưa có bài nguồn nào tự chứng minh cơ sở cân, quy tắc tăng lượng và lượng nêm cuối. Trạng thái duyệt, người duyệt, ngày duyệt vẫn trống/chờ xác minh; `import_allowed=false`.

Nguồn được đọc qua trích xuất web có thể dùng bộ nhớ đệm. Không lưu HTML đầy đủ hoặc hash trang gốc; hash trong manifest chỉ chứng thực tệp hồ sơ đã tạo, không giả làm snapshot nguồn. Không sao chép bài/hình ảnh hoặc tự xác nhận quyền tái sử dụng. Phê duyệt nguồn và nội dung áp dụng vẫn cần người duyệt.
