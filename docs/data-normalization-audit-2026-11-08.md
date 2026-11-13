# Kiểm kê và đề xuất chuẩn hóa dữ liệu công thức

**Ngày kiểm kê:** 08/11/2026  
**Phạm vi:** catalog User đang được repository công khai cung cấp từ MySQL `goiy_mon_an`; truy vấn chỉ đọc. Không ghi DB, không sửa seed, schema, migration hay thuật toán.

## 1. Tóm tắt catalog hiện tại

| Hạng mục | Quan sát |
|---|---:|
| Món công khai | 52: 50 món legacy và 2 món do Admin thêm |
| Nguyên liệu công khai | 50, tên hiển thị tiếng Việt |
| Liên kết món–nguyên liệu công khai | 255: 252 liên kết legacy và 3 liên kết ở 2 món Admin |
| Dòng nguyên liệu có chuỗi định lượng | 254/255; một dòng thiếu định lượng |
| Khẩu phần gốc | 0/52 có giá trị được cung cấp |
| Mô tả | 0/52 có mô tả |
| Thời gian | 52/52 có một trường tổng thời gian; chưa tách chuẩn bị và chế biến |
| Hướng dẫn | 50 món legacy có 3 bước ngắn; 2 món Admin chỉ có nội dung “sơ chế”, không thành các bước nấu |
| Ảnh | 49 món dùng ảnh tĩnh/fallback, 3 món có ảnh Admin |
| Vai trò món đang có | 25 chính, 4 rau, 6 canh, 15 món tinh bột, 2 món khác |

Định lượng đang được lưu dưới dạng chuỗi tự do, ví dụ `2 quả`, `300 g`, `2 muỗng`; chưa phải cặp số lượng–đơn vị chuẩn hóa. Vì thế có thể hiển thị để tham khảo nhưng chưa đủ cơ sở để tính khẩu phần chính xác hoặc cộng giỏ hàng giữa các công thức. Trường vùng miền, mùa, dịp và khẩu phần không xuất hiện trong dữ liệu catalog công khai của các hàng dưới đây. Nhãn vai trò hiện tại không đồng nghĩa với nhãn vùng miền hay dịp ăn đã xác minh.

Hai món Admin công khai cần được xác minh về chất lượng nội dung: `trứng kho` (ID `7980672317`) có một nguyên liệu tùy chọn “Mắm ruốc” nhưng thiếu định lượng; hướng dẫn chỉ là “sơ chế”; `món test` (ID `7980672321`) có hai nguyên liệu nhưng hướng dẫn cũng chỉ là “sơ chế”. Đây là ghi nhận trạng thái đang được User nhìn thấy, không phải đề nghị tự động ẩn/xóa.

## 2. Kiểm kê từng món đang công khai

Ký hiệu: `*` = nguyên liệu đang được đánh dấu tùy chọn; `?` = thiếu định lượng. Định lượng được chép nguyên trạng như API công khai trả về, không chuẩn hóa hay suy đoán. Cột bước đếm các đoạn `Bước N`/đánh số nhận diện được.

| ID | Tên món | Vai trò | Phút | Khẩu phần | Nguyên liệu và định lượng hiện có | Bước | Ảnh |
|---:|---|---|---:|---|---|---:|---|
| 1 | Trứng sốt cà chua | Chính | 15 | Chưa có | Trứng 2 quả; Cà chua 2 quả | 3 | Admin |
| 2 | Món thịt rau củ | Chính | 30 | Chưa có | Trứng 200 g; Cà chua 1 quả; Hành 1 củ; Thịt 200 g | 3 | Tĩnh |
| 3 | Trứng xào hành | Chính | 10 | Chưa có | Trứng 2 quả; Hành* 1 củ | 3 | Tĩnh |
| 4 | Đậu phụ sốt cà chua | Chính | 20 | Chưa có | Cà chua 2 quả; Đậu phụ 2 miếng; Tỏi* 1 tép | 3 | Tĩnh |
| 5 | Rau muống xào tỏi | Rau | 12 | Chưa có | Rau muống 300 g; Tỏi 2 tép | 3 | Tĩnh |
| 6 | Canh gà nấm hương | Canh | 35 | Chưa có | Gừng 1 nhánh; Nấm hương 50 g; Cà rốt 1 củ; Thịt gà 300 g | 3 | Tĩnh |
| 7 | Cá basa kho gừng | Chính | 30 | Chưa có | Gừng 1 nhánh; Cá basa 300 g | 3 | Tĩnh |
| 8 | Bún thịt xào | Tinh bột | 25 | Chưa có | Hành 1 củ; Thịt 200 g; Dưa leo 1 quả; Bún 2 phần | 3 | Tĩnh |
| 9 | Khoai tây xào cà rốt | Rau | 25 | Chưa có | Hành 1 củ; Cà rốt 1 củ; Khoai tây 2 củ | 3 | Tĩnh |
| 10 | Trứng cuộn rau củ | Chính | 18 | Chưa có | Trứng 2 quả; Hành 1 củ; Cà rốt* 1 củ | 3 | Tĩnh |
| 11 | Phở bò | Tinh bột | 90 | Chưa có | Bánh phở 200 g; Hành lá 2 nhánh; Quế 1 thanh; Hoa hồi 2 quả; Giá đỗ* 100 g; Rau thơm* 50 g; Chanh* 1 quả; Ớt* 1 quả; Thịt bò 250 g | 3 | Tĩnh |
| 12 | Phở gà | Tinh bột | 75 | Chưa có | Thịt gà 500 g; Bánh phở 200 g; Hành lá 2 nhánh; Quế* 1 thanh; Hoa hồi* 1 quả; Giá đỗ* 100 g; Rau thơm* 50 g; Chanh* 1 quả | 3 | Tĩnh |
| 13 | Bún chả | Tinh bột | 45 | Chưa có | Bún 2 phần; Hành lá* 2 nhánh; Giá đỗ* 100 g; Rau thơm 50 g; Chanh* 1 quả; Ớt* 1 quả; Nước mắm 3 muỗng; Thịt heo xay 300 g | 3 | Tĩnh |
| 14 | Bún bò Huế | Tinh bột | 120 | Chưa có | Bún 2 phần; Hành lá* 2 nhánh; Rau thơm* 50 g; Ớt* 1 quả; Sả 3 cây; Mắm ruốc 1 muỗng; Sa tế* 1 muỗng; Thịt bò 250 g | 3 | Tĩnh |
| 15 | Bún riêu cua | Tinh bột | 60 | Chưa có | Cà chua 3 quả; Bún 2 phần; Giá đỗ* 100 g; Rau thơm* 50 g; Nước mắm 2 muỗng; Cua đồng 300 g; Bắp chuối* 100 g | 3 | Tĩnh |
| 16 | Gỏi cuốn tôm thịt | Khác | 35 | Chưa có | Bún 2 phần; Giá đỗ* 100 g; Rau thơm 50 g; Chanh* 1 quả; Tôm 200 g; Thịt heo xay 150 g; Bánh tráng 10 cái | 3 | Tĩnh |
| 17 | Chả giò | Chính | 50 | Chưa có | Hành* 1 củ; Tỏi* 2 tép; Cà rốt* 1 củ; Nước mắm 2 muỗng; Thịt heo xay 300 g; Bánh tráng 10 cái | 3 | Tĩnh |
| 18 | Bánh xèo | Tinh bột | 40 | Chưa có | Giá đỗ* 100 g; Rau thơm* 50 g; Nước mắm 2 muỗng; Bột gạo 200 g; Tôm 200 g; Thịt heo xay* 150 g | 3 | Tĩnh |
| 19 | Bánh cuốn nhân thịt | Tinh bột | 55 | Chưa có | Hành* 1 củ; Tỏi* 2 tép; Nước mắm 2 muỗng; Bột gạo 250 g; Thịt heo xay 250 g | 3 | Tĩnh |
| 20 | Cao lầu Hội An | Tinh bột | 50 | Chưa có | Hành* 1 củ; Thịt 300 g; Dưa leo* 1 quả; Bún 2 phần; Rau thơm* 50 g; Nước mắm 2 muỗng | 3 | Tĩnh |
| 21 | Mì Quảng tôm thịt | Tinh bột | 55 | Chưa có | Bún 2 phần; Hành lá* 2 nhánh; Rau thơm* 50 g; Nước mắm 2 muỗng; Tôm 200 g; Thịt heo xay 200 g | 3 | Tĩnh |
| 22 | Cơm tấm sườn | Tinh bột | 60 | Chưa có | Hành* 1 củ; Tỏi* 2 tép; Hành lá* 2 nhánh; Nước mắm 2 muỗng; Sườn heo 400 g | 3 | Tĩnh |
| 23 | Cơm gà xối mỡ | Tinh bột | 70 | Chưa có | Hành* 1 củ; Tỏi* 2 tép; Gừng* 1 nhánh; Thịt gà 500 g; Nước mắm 2 muỗng | 3 | Tĩnh |
| 24 | Cơm chiên Dương Châu | Tinh bột | 30 | Chưa có | Trứng 2 quả; Hành* 1 củ; Cà rốt* 1 củ; Thịt gà* 100 g; Bún 2 phần; Bắp* 100 g | 3 | Tĩnh |
| 25 | Cơm chiên cá mặn | Tinh bột | 35 | Chưa có | Trứng* 1 quả; Hành* 1 củ; Cá basa 200 g; Bún 2 phần; Nước mắm* 1 muỗng | 3 | Tĩnh |
| 26 | Cá kho tộ | Chính | 50 | Chưa có | Hành* 1 củ; Tỏi* 2 tép; Cá basa 400 g; Nước mắm 3 muỗng; Nước dừa 300 ml | 3 | Tĩnh |
| 27 | Thịt kho trứng | Chính | 90 | Chưa có | Trứng 4 quả; Hành* 1 củ; Tỏi* 2 tép; Nước mắm 3 muỗng; Thịt heo xay 500 g; Nước dừa 500 ml | 3 | Tĩnh |
| 28 | Canh chua cá | Canh | 35 | Chưa có | Cà chua* 2 quả; Cá basa 300 g; Chanh* 1 quả; Nước mắm 2 muỗng; Dứa 150 g; Me 2 muỗng | 3 | Tĩnh |
| 29 | Canh bí đỏ hầm xương | Canh | 55 | Chưa có | Gừng* 1 nhánh; Nước mắm* 1 muỗng; Sườn heo 300 g; Bí đỏ 400 g | 3 | Tĩnh |
| 30 | Canh rau ngót thịt bằm | Canh | 25 | Chưa có | Hành* 1 củ; Nước mắm 1 muỗng; Thịt heo xay 150 g; Rau ngót 300 g | 3 | Tĩnh |
| 31 | Canh cải chua sườn | Canh | 60 | Chưa có | Gừng* 1 nhánh; Nước mắm 1 muỗng; Sườn heo 300 g; Cải chua 300 g | 3 | Tĩnh |
| 32 | Canh nấm rơm đậu phụ | Canh | 25 | Chưa có | Đậu phụ 2 miếng; Gừng* 1 nhánh; Nấm hương* 30 g; Nước mắm 1 muỗng; Nấm rơm 200 g | 3 | Tĩnh |
| 33 | Gà kho gừng | Chính | 45 | Chưa có | Hành* 1 củ; Gừng 1 nhánh; Thịt gà 500 g; Nước mắm 2 muỗng | 3 | Tĩnh |
| 34 | Gà xào sả ớt | Chính | 35 | Chưa có | Tỏi* 2 tép; Thịt gà 400 g; Ớt* 1 quả; Nước mắm 2 muỗng; Sả 2 cây | 3 | Tĩnh |
| 35 | Bò lúc lắc | Chính | 25 | Chưa có | Hành* 1 củ; Tỏi* 2 tép; Nước mắm 2 muỗng; Thịt bò 300 g | 3 | Tĩnh |
| 36 | Bò xào rau muống | Chính | 25 | Chưa có | Rau muống 300 g; Tỏi* 2 tép; Nước mắm 1 muỗng; Thịt bò 250 g | 3 | Tĩnh |
| 37 | Thịt heo kho tiêu | Chính | 45 | Chưa có | Hành* 1 củ; Tỏi* 2 tép; Ớt* 1 quả; Nước mắm 2 muỗng; Thịt heo xay 400 g | 3 | Tĩnh |
| 38 | Thịt băm chưng trứng | Chính | 40 | Chưa có | Trứng 3 quả; Hành* 1 củ; Cà rốt* 1 củ; Nước mắm 1 muỗng; Thịt heo xay 300 g | 3 | Tĩnh |
| 39 | Sườn xào chua ngọt | Chính | 50 | Chưa có | Hành* 1 củ; Tỏi* 2 tép; Nước mắm 2 muỗng; Sườn heo 500 g; Me* 2 muỗng | 3 | Tĩnh |
| 40 | Tôm rang me | Chính | 25 | Chưa có | Hành* 1 củ; Chanh* 1 quả; Nước mắm 1 muỗng; Tôm 400 g; Me 2 muỗng | 3 | Tĩnh |
| 41 | Mực xào dứa | Chính | 25 | Chưa có | Cà chua* 2 quả; Hành* 1 củ; Nước mắm 1 muỗng; Mực 300 g; Dứa 200 g | 3 | Tĩnh |
| 42 | Tôm hấp nước dừa | Chính | 20 | Chưa có | Chanh* 1 quả; Ớt* 1 quả; Tôm 400 g; Nước dừa 500 ml | 3 | Tĩnh |
| 43 | Đậu phụ nhồi thịt | Chính | 35 | Chưa có | Cà chua 3 quả; Hành* 1 củ; Đậu phụ 3 miếng; Nước mắm 2 muỗng; Thịt heo xay 200 g | 3 | Tĩnh |
| 44 | Đậu phụ kho nấm | Chính | 30 | Chưa có | Đậu phụ 3 miếng; Tỏi* 2 tép; Nấm hương* 30 g; Nước mắm 2 muỗng; Nấm rơm 150 g | 3 | Tĩnh |
| 45 | Nấm xào sả | Rau | 20 | Chưa có | Tỏi* 2 tép; Ớt* 1 quả; Nước mắm 1 muỗng; Sả 2 cây; Nấm rơm 300 g | 3 | Tĩnh |
| 46 | Gỏi gà rau răm | Chính | 35 | Chưa có | Gừng* 1 nhánh; Thịt gà 400 g; Hành lá* 1 nhánh; Chanh 1 quả; Nước mắm 2 muỗng; Rau răm 50 g | 3 | Tĩnh |
| 47 | Nộm dưa leo cà rốt | Rau | 15 | Chưa có | Cà chua* 1 quả; Hành* 1 củ; Cà rốt 1 củ; Dưa leo 2 quả; Chanh 1 quả; Ớt* 1 quả; Nước mắm 2 muỗng | 3 | Tĩnh |
| 48 | Bánh tráng cuốn thịt heo | Khác | 45 | Chưa có | Thịt 400 g; Gừng* 1 nhánh; Dưa leo* 1 quả; Bún* 2 phần; Rau thơm 50 g; Nước mắm 3 muỗng; Bánh tráng 8 cái | 3 | Tĩnh |
| 49 | Chả lá lốt | Chính | 35 | Chưa có | Hành* 1 củ; Tỏi* 2 tép; Nước mắm 2 muỗng; Thịt heo xay 300 g; Lá lốt 12 lá | 3 | Tĩnh |
| 50 | Miến gà | Tinh bột | 55 | Chưa có | Gừng* 1 nhánh; Nấm hương* 30 g; Thịt gà 400 g; Hành lá* 2 nhánh; Nước mắm 1 muỗng; Miến 200 g | 3 | Tĩnh |
| 7980672317 | trứng kho | Chính | 30 | Chưa có | Mắm ruốc* ? | 0 | Admin |
| 7980672321 | món test | Chính | 10 | Chưa có | Cà rốt 2 quả; Cà chua 1 quả | 0 | Admin |

## 3. Danh mục nguyên liệu và khoảng trống gia vị

Catalog User hiện có đúng 50 tên sau; số là ID công khai được API trả về:

| ID | Nguyên liệu | ID | Nguyên liệu | ID | Nguyên liệu |
|---:|---|---:|---|---:|---|
| 1 | Trứng | 18 | Quế | 35 | Tôm |
| 2 | Cà chua | 19 | Hoa hồi | 36 | Mực |
| 3 | Hành | 20 | Giá đỗ | 37 | Thịt bò |
| 4 | Thịt | 21 | Rau thơm | 38 | Thịt heo xay |
| 5 | Đậu phụ | 22 | Chanh | 39 | Sườn heo |
| 6 | Rau muống | 23 | Ớt | 40 | Nước dừa |
| 7 | Tỏi | 24 | Nước mắm | 41 | Dứa |
| 8 | Gừng | 25 | Sả | 42 | Me |
| 9 | Nấm hương | 26 | Mắm ruốc | 43 | Rau ngót |
| 10 | Cà rốt | 27 | Sa tế | 44 | Bí đỏ |
| 11 | Khoai tây | 28 | Cua đồng | 45 | Cải chua |
| 12 | Dưa leo | 29 | Giò sống | 46 | Nấm rơm |
| 13 | Cá basa | 30 | Bắp chuối | 47 | Bắp | 
| 14 | Thịt gà | 31 | Rau răm | 48 | Miến |
| 15 | Bún | 32 | Đậu xanh | 49 | Bánh tráng |
| 16 | Bánh phở | 33 | Gạo tẻ | 50 | Lá lốt |
| 17 | Hành lá | 34 | Bột gạo |  |  |

### Gia vị đề xuất kiểm tra và phân loại

| Gia vị thường gặp | Có tên trong catalog | Được liên kết với món | Ghi nhận |
|---|---:|---:|---|
| Dầu ăn | Không | 0 | Hướng dẫn nhắc dầu ở Rau muống xào tỏi, Chả giò, Cơm gà xối mỡ nhưng không có ingredient ID tương ứng |
| Muối | Không | 0 | Không thấy trong catalog hoặc hướng dẫn đã lưu |
| Đường | Không | 0 | Hướng dẫn Sườn xào chua ngọt có nhắc, chưa có nguyên liệu liên kết |
| Nước mắm | Có, ID 24 | 34/52 | Hướng dẫn nhắc ở 37 món; các món Trứng sốt cà chua, Món thịt rau củ, Cá basa kho gừng, Bún thịt xào, Gỏi cuốn tôm thịt và Cơm chiên Dương Châu nhắc nhưng chưa liên kết ID nước mắm |
| Tiêu | Không | 0 | Hướng dẫn nhắc ở Cá kho tộ và Thịt heo kho tiêu, chưa có nguyên liệu liên kết |
| Hành | Có, ID 3 | 25/52 | Phân biệt với Hành lá, ID 17; không gộp hai tên |
| Tỏi | Có, ID 7 | 16/52 | Có nhiều dòng hiện đánh dấu tùy chọn |
| Gừng | Có, ID 8 | 10/52 | Có nhiều dòng hiện đánh dấu tùy chọn |
| Sả | Có, ID 25 | 3/52 | Đã liên kết ở các món phù hợp hiện có |
| Ớt | Có, ID 23 | 8/52 | Thường được đánh dấu tùy chọn |
| Hạt nêm | Không | 0 | Không thấy trong catalog hoặc hướng dẫn đã lưu |

“Không có liên kết” không đồng nghĩa món chắc chắn thiếu gia vị trong cách nấu thực tế: nó có nghĩa bản ghi recipe hiện tại không có dòng nguyên liệu đó. Trước khi bổ sung cần đối chiếu phiên bản công thức/nguồn; không tạo nguyên liệu trùng, tự thêm định lượng hay suy ra mọi món đều dùng cùng gia vị. “Hành” và “hành lá”, “nước mắm” và “mắm ruốc” là các mục riêng, không tự hợp nhất.

## 4. B0/P1 và cách ghi gia vị

Trong `source/server/ranking.py`, cả B0 (`baseline`) và P1 (`proposed`) lấy tập `required_ids` làm căn cứ khớp nguyên liệu; `all_ids` dùng để loại món có nguyên liệu bị loại trừ. Món không được gợi ý nếu không khớp ít nhất một nguyên liệu bắt buộc đã chọn. B0 xếp theo số nguyên liệu bắt buộc khớp; P1 dùng độ phủ nguyên liệu bắt buộc, mức sử dụng đầu vào, số còn thiếu và thời gian. Các nguyên liệu bắt buộc chưa chọn được trả thành `missing_ids`; do đó thêm mọi gia vị phổ biến như bắt buộc có thể làm đổi điểm/thứ tự và giải thích món, dù thuật toán không yêu cầu người dùng phải chọn hết mọi `required_id`.

Đề xuất quản lý, không thay đổi trong giai đoạn này:

1. Ghi nguyên liệu thực sự có trong đúng phiên bản công thức, gồm gia vị và lượng nếu nguồn cung cấp.
2. Chỉ đánh dấu “tùy chọn” khi công thức nguồn hoặc người duyệt xác nhận có thể bỏ qua; không đánh dấu tùy chọn chỉ để tăng kết quả gợi ý.
3. Không tự đưa “muối, tiêu, dầu ăn” vào tất cả công thức. Nếu sau này cần chế độ “đã có gia vị căn bản”, thiết kế như lựa chọn rõ ràng của người dùng và kiểm thử tác động xếp hạng trước; không âm thầm đổi nghĩa `required_ids` hoặc B0/P1.
4. Giữ nguyên ID ingredient và định danh riêng cho các khái niệm khác nhau. Các mục gia vị thật sự thiếu chỉ được thêm qua Admin sau khi xác nhận chưa có alias/ID tương đương và có căn cứ dữ liệu.

## 5. Mẫu hồ sơ công thức chuẩn đề xuất

```yaml
recipe:
  name: ""
  description: ""
  role: main | vegetable | soup | starch | snack | dessert | drink | other
  prep_minutes: NEEDS_VERIFICATION
  cook_minutes: NEEDS_VERIFICATION
  base_servings: NEEDS_VERIFICATION
  source:
    url: ""
    version_or_published_at: ""
    evidence: []
    review_status: NEEDS_VERIFICATION
  ingredients:
    - ingredient_id: NEEDS_VERIFICATION
      ingredient_name_as_source: ""
      quantity_value: NEEDS_VERIFICATION
      quantity_max: null
      unit: NEEDS_VERIFICATION
      form: NEEDS_VERIFICATION # sơ chế / sống / chín / loại cắt...
      requirement: required | optional | NEEDS_VERIFICATION
      evidence_ref: ""
  instructions:
    - step_no: 1
      text: ""
      evidence_ref: ""
  tips: []
  storage: NEEDS_VERIFICATION
  metadata:
    diet: NEEDS_VERIFICATION
    regions: [] # mỗi nhãn cần bằng chứng và trạng thái duyệt riêng
    seasons: []
    occasions: []
    role_evidence: NEEDS_VERIFICATION
```

Giữ riêng trạng thái xuất bản công thức với trạng thái xác minh định lượng, vai trò, chế độ ăn, vùng miền, mùa và dịp. Một trường chưa có căn cứ phải giữ `NEEDS_VERIFICATION`; không suy diễn từ tên món. Lượng khoảng lưu cận dưới/trên thay vì gộp thành một số tùy tiện. Đơn vị thể tích/khối lượng chỉ quy đổi khi có quy tắc đã được xác nhận.

## 6. Đề xuất ít nhất 50 món để mở rộng

Đây là danh sách ứng viên cần chọn nguồn và kiểm chứng; **không phải dữ liệu đã thu thập, không phải nhãn vùng miền đã xác nhận, và chưa nhập vào hệ thống**. Có 60 gợi ý để hỗ trợ mâm gia đình, mâm chay, mùa, tiệc, ăn vặt, lễ Tết và đồ uống.

| Nhóm ưu tiên | Món ứng viên |
|---|---|
| Món mặn dùng làm món chính | 1. Thịt kho tàu; 2. Sườn non rim mặn; 3. Cá lóc kho tộ; 4. Cá thu sốt cà; 5. Gà hấp lá chanh; 6. Gà rang muối; 7. Bò kho; 8. Bò xào lúc lắc rau củ; 9. Tôm rim thịt; 10. Mực hấp gừng; 11. Chả cá sốt thì là; 12. Trứng hấp thịt; 13. Cá nục kho cà; 14. Thịt luộc cuốn bánh tráng; 15. Sườn nướng mật ong |
| Món rau và món ăn kèm | 16. Rau cải xào tỏi; 17. Bông cải xanh xào nấm; 18. Đậu que xào thịt; 19. Rau củ luộc chấm kho quẹt; 20. Cà tím nướng mỡ hành; 21. Gỏi ngó sen tôm thịt; 22. Dưa giá; 23. Cải thìa sốt nấm; 24. Bí xanh xào tỏi; 25. Salad rau củ kiểu Việt |
| Món canh | 26. Canh chua tôm; 27. Canh khổ qua nhồi thịt; 28. Canh chua sườn; 29. Canh bí xanh nấu tôm; 30. Canh cải nấu thịt bằm; 31. Canh mồng tơi cua; 32. Canh bầu nấu tôm; 33. Canh khoai mỡ; 34. Canh chua rau muống; 35. Canh gà lá giang |
| Món chay cần kiểm chứng thành phần đầy đủ | 36. Nấm kho tiêu; 37. Đậu hũ kho sả; 38. Cà tím kho đậu hũ; 39. Nấm đùi gà áp chảo; 40. Canh chua chay; 41. Canh rong biển đậu hũ; 42. Rau củ kho; 43. Chả giò chay; 44. Bún riêu chay; 45. Cơm chiên rau củ chay |
| Món theo mùa/lễ Tết/đãi khách | 46. Thịt đông; 47. Dưa hành; 48. Bánh chưng; 49. Bánh tét; 50. Gà luộc; 51. Nem rán; 52. Lẩu gà lá é; 53. Lẩu cá kèo; 54. Bò nhúng giấm; 55. Gỏi cuốn phiên bản có nguồn rõ |
| Ăn vặt, tráng miệng và đồ uống | 56. Bắp xào; 57. Bánh chuối hấp; 58. Chè đậu xanh; 59. Sữa bắp; 60. Nước sâm |

Thứ tự chọn nguồn nên ưu tiên nhóm món chính–rau–canh còn thiếu để ghép được mâm 4 món mặn + 1 canh; kế tiếp là một nhóm món chay có đủ chính–rau–canh và thành phần được xác minh; sau đó mới mở rộng món theo mùa/dịp và ăn vặt/đồ uống. Món ứng viên không tự động được gán vùng miền hay dịp chỉ từ tên gọi.

## 7. Cách cập nhật an toàn và thứ tự triển khai

1. **Chốt quy tắc hồ sơ:** thống nhất đơn vị, số khẩu phần gốc, cách ghi lượng khoảng, nguồn/bằng chứng, và phân biệt trường thiếu với lượng bằng 0.
2. **Ưu tiên làm rõ dữ liệu hiện có:** xác minh hai món Admin đang công khai nêu ở mục 1; đối chiếu các chỗ hướng dẫn có nhắc nước mắm/dầu/đường/tiêu nhưng thiếu dòng nguyên liệu. Không sửa 50 món legacy trực tiếp.
3. **Hoàn thiện theo overlay/Admin:** mọi chỉnh sửa legacy đi qua cơ chế overlay hiện có; món mới đi qua Admin catalog hiện hành. Lưu bản sửa có kiểm tra phiên bản, nguồn và trạng thái xác minh. Không nhập thẳng vào bảng seed/legacy.
4. **Bổ sung có kiểm soát:** chọn một tập nhỏ 5–10 món có nguồn rõ, đủ thành phần và hướng dẫn; đo độ phủ vai trò trước khi mở rộng lên danh sách 60 ứng viên.
5. **Kiểm tra chất lượng trước công khai:** đối chiếu nguyên liệu trong hướng dẫn với dòng ingredient; kiểm tra ingredient ID trùng tên/alias; rà lượng và đơn vị; bảo đảm món chưa đủ điều kiện vẫn bị chặn khỏi công khai theo cơ chế hiện có.
6. **Đánh giá combo sau khi dữ liệu đủ:** chỉ dùng vai trò/mùa/dịp/chế độ ăn đã có bằng chứng và trạng thái duyệt; thiếu món thì báo thiếu, không nới bộ lọc.

## 8. Giới hạn và phạm vi kiểm kê

Số liệu phản ánh catalog được repository công khai trả tại thời điểm kiểm kê, không phải bản sao lưu độc lập hay xác nhận từng công thức từ nguồn bên ngoài. Không truy cập nguồn công thức bên ngoài và không xác minh tính đúng đắn ẩm thực của nội dung hiện tại. Tên và nội dung trong bảng là trạng thái hệ thống đang cung cấp; các ứng viên bổ sung chỉ là đề xuất để nghiên cứu nguồn. Không có dữ liệu nào bị ghi hoặc thay đổi trong quá trình kiểm kê.
