# Pilot 5 món — công thức demo biên soạn và cách nhập qua Admin

**Trạng thái:** nội dung đề xuất, chưa ghi MySQL. Đây là các phiên bản công thức do project biên soạn lại cho demo từ thông tin nguồn công khai và cách nấu phổ biến; không phải nguyên bản legacy, không phải bản chép nguyên văn bài viết. Không nhập hàng loạt lên MySQL chính.

## Cách dùng hồ sơ

- Mỗi recipe dưới đây là một công thức demo cho **4 người**, với định lượng mới thống nhất để minh họa danh sách đi chợ. Các số này là đề xuất biên soạn của project, không được trình bày là khẩu phần/định lượng gốc trong legacy.
- Các recipe legacy dùng ID món hiện tại và dự kiến lưu qua Admin legacy overlay. Bảng gốc cùng 252 quan hệ không bị ghi trực tiếp.
- Bản `trứng kho mắm ruốc` giữ mắm ruốc riêng; công thức tham khảo `trứng kho nước mắm` không được nhập vào recipe này.
- Admin hiện lưu một trường thời gian tổng, một dòng quantity dạng văn bản và đánh dấu mọi dòng nguyên liệu là bắt buộc. Mỗi dòng bên dưới vì vậy là thành phần bắt buộc; không có dòng tùy chọn ẩn.
- Nhãn vùng/mùa/dịp bên dưới là nhãn demo đề xuất. Form Admin hiện tại không có ô nhập các metadata này; chúng chưa được bật làm filter User trong lượt chuẩn bị này.

## Danh sách 4 nguyên liệu cần tạo qua catalog chung

Đối chiếu catalog live hiện có 50 nguyên liệu hoạt động. Bốn tên sau chưa có ID exact trong catalog:

| Tên chuẩn đề xuất | Nhóm | Đơn vị gợi ý | Xuất hiện trong món |
|---|---|---|---|
| Dầu ăn | Gia vị cơ bản / dầu | ml | Cá basa, rau muống, đậu phụ, trứng mắm ruốc |
| Muối | Gia vị cơ bản | g | Canh gà, rau muống, đậu phụ |
| Đường | Gia vị cơ bản | g | Cá basa, rau muống, đậu phụ, trứng mắm ruốc |
| Tiêu | Gia vị khô | g | Cá basa, canh gà, đậu phụ |

`Hành tím` được dùng trong một số công thức nhưng chưa tạo đề xuất ID mới: trước tiên cần quyết định nó có phải alias của `Hành` ID 3 hay là identity riêng. Không nhập dòng hành tím trước khi xác nhận để tránh duplicate. Không đưa hạt nêm, bột ngọt, bột canh, dầu hào hay tương ớt vào các phiên bản demo này; chúng không cần thiết cho công thức đã chọn. Riêng dầu hào thường được bỏ khỏi phiên bản rau muống để recipe có thể dùng làm món chay.

Các ingredient ID dùng lại:

| Tên | ID |
|---|---:|
| Trứng | 1 |
| Cà chua | 2 |
| Hành | 3 |
| Đậu phụ | 5 |
| Rau muống | 6 |
| Tỏi | 7 |
| Gừng | 8 |
| Nấm hương | 9 |
| Cà rốt | 10 |
| Cá basa | 13 |
| Thịt gà | 14 |
| Hành lá | 17 |
| Ớt | 23 |
| Nước mắm | 24 |
| Mắm ruốc | 26 |

## 1. Cá basa kho gừng — legacy ID 7

**Mô tả:** Cá basa kho mềm trong nước mắm, gừng và tiêu; nước kho sánh, hợp ăn cùng cơm nóng.  
**Vai trò:** Món chính. **Chế độ:** Mặn. **Vùng:** Miền Nam (đề xuất demo, gắn với cá basa và phong cách kho). **Mùa:** Mùa mưa/lạnh. **Dịp:** Hằng ngày, bữa cơm gia đình.  
**Khẩu phần:** 4. **Chuẩn bị:** 20 phút. **Nấu:** 30 phút. **Tổng nhập Admin:** 50 phút.

| Nguyên liệu bắt buộc | Định lượng cho 4 người | Catalog |
|---|---:|---|
| Cá basa | 600 g | ID 13 |
| Gừng tươi | 25 g | ID 8 |
| Tỏi | 10 g | ID 7 |
| Hành tím | 20 g | Chờ xác nhận alias/ID; chưa nhập |
| Nước mắm | 30 ml | ID 24 |
| Dầu ăn | 15 ml | Đề xuất ID mới |
| Đường | 12 g | Đề xuất ID mới |
| Tiêu xay | 1 g | Đề xuất ID mới; form xay |
| Ớt tươi | 5 g | ID 23 |
| Nước lọc | 100 ml | Thành phần nấu; không đưa vào picker User |

**Cách làm**

1. Rửa cá, thấm khô, cắt khúc dày khoảng 3–4 cm. Gừng cạo vỏ, một nửa thái lát, một nửa thái sợi; tỏi đập dập, ớt thái lát.
2. Ướp cá với nước mắm, đường và một nửa gừng trong 15 phút. Trở nhẹ để cá không vỡ.
3. Làm nóng nồi, cho dầu; thêm tỏi và gừng, đảo đến khi thơm nhưng chưa cháy.
4. Xếp cá vào nồi, áp nhẹ hai mặt khoảng 1–2 phút cho mặt cá săn. Thêm nước và ớt.
5. Đun sôi rồi hạ lửa nhỏ, kho hé nắp khoảng 20–25 phút. Lắc nồi thay vì đảo mạnh; trở cá một lần nếu cần.
6. Khi thịt cá đục hoàn toàn, tách thớ dễ dàng và nước kho áo quanh mặt cá, nêm lại theo công thức, rắc tiêu rồi tắt bếp.
7. Dọn nóng cùng cơm; chan phần nước kho lên cá. Không có thời hạn bảo quản được đề xuất trong hồ sơ này.

**Mẹo:** Dùng nồi đáy dày và lắc nồi để giữ khúc cá nguyên.  
**Nguồn tham khảo ý tưởng:** [CET — Cá basa kho gừng](https://www.cet.edu.vn/cach-lam-ca-basa-kho). Công thức và lượng phía trên là phiên bản demo của project, không chép định lượng nguồn.

## 2. Canh gà nấm hương — legacy ID 6

**Mô tả:** Nước canh gà thanh, thơm gừng và nấm hương, có cà rốt tạo vị ngọt tự nhiên.  
**Vai trò:** Canh. **Chế độ:** Mặn. **Vùng:** Bắc/Trung/Nam (món gia đình phổ biến, đề xuất demo). **Mùa:** Quanh năm; hợp ngày mát. **Dịp:** Hằng ngày, cuối tuần.  
**Khẩu phần:** 4. **Chuẩn bị:** 15 phút. **Nấu:** 40 phút. **Tổng nhập Admin:** 55 phút.

| Nguyên liệu bắt buộc | Định lượng cho 4 người | Catalog |
|---|---:|---|
| Thịt gà có xương | 600 g | ID 14; dạng ghi trong dòng |
| Nấm hương tươi | 200 g | ID 9; dạng tươi |
| Cà rốt | 150 g | ID 10 |
| Gừng | 15 g | ID 8 |
| Hành lá | 20 g | ID 17 |
| Muối | 5 g | Đề xuất ID mới |
| Nước mắm | 15 ml | ID 24 |
| Tiêu xay | 1 g | Đề xuất ID mới; form xay |
| Nước lọc | 1.5 lít | Chất lỏng nấu; không đưa vào picker User |

**Cách làm**

1. Chặt gà miếng vừa ăn, rửa sạch và để ráo. Nấm cắt bỏ chân cứng; cà rốt thái lát; gừng đập dập; hành lá cắt khúc.
2. Ướp gà với một phần muối, nước mắm, tiêu và gừng trong 10 phút.
3. Đun sôi nồi nước, cho gà vào; hớt bọt, hạ lửa nhỏ và nấu khoảng 20 phút.
4. Thêm nấm hương, nấu 10 phút; cho cà rốt vào nấu thêm 5–7 phút đến khi vừa mềm.
5. Nêm phần muối/nước mắm còn lại trong tổng lượng đã ghi. Kiểm tra miếng gà dày nhất đã chín và cà rốt mềm nhưng còn nguyên miếng.
6. Thêm hành lá, tắt bếp, múc ra tô và dùng nóng.

**Mẹo:** Hớt bọt khi nước vừa sôi để nước canh trong; tránh đun sôi mạnh kéo dài.  
**Nguồn tham khảo ý tưởng:** [FPT Shop — Canh gà nấm hương](https://fptshop.com.vn/tin-tuc/dien-may/canh-ga-nam-huong-186663/). Công thức và lượng ở đây là phiên bản demo, không ghép lượng với snapshot legacy.

## 3. Rau muống xào tỏi — legacy ID 5

**Mô tả:** Rau muống xanh giòn xào nhanh với tỏi thơm, nêm nhẹ để giữ vị rau.  
**Vai trò:** Món rau. **Chế độ:** Chay thực vật theo phiên bản demo, không dùng dầu hào/nước mắm. **Vùng:** Bắc/Trung/Nam (món phổ biến, đề xuất demo). **Mùa:** Mùa hè/nóng. **Dịp:** Hằng ngày.  
**Khẩu phần:** 4. **Chuẩn bị:** 10 phút. **Nấu:** 10 phút. **Tổng nhập Admin:** 20 phút.

| Nguyên liệu bắt buộc | Định lượng cho 4 người | Catalog |
|---|---:|---|
| Rau muống | 500 g | ID 6 |
| Tỏi | 15 g | ID 7 |
| Dầu ăn | 25 ml | Đề xuất ID mới |
| Muối | 4 g | Đề xuất ID mới |
| Đường | 2 g | Đề xuất ID mới |
| Nước lọc | 40 ml | Dùng tạo hơi khi xào; không đưa vào picker User |

**Cách làm**

1. Nhặt bỏ lá úa, cắt rau thành khúc 5–6 cm, rửa sạch và để ráo kỹ. Tỏi bóc vỏ, đập dập rồi băm thô.
2. Đun nồi nước sôi, chần rau khoảng 30–45 giây; vớt ra để ráo. Nếu cần giữ màu lâu, làm nguội nhanh bằng nước lạnh rồi để ráo thật kỹ.
3. Làm nóng chảo rộng, cho dầu và tỏi; phi lửa vừa đến khi tỏi thơm vàng nhạt.
4. Tăng lửa lớn, cho rau vào đảo nhanh 1–2 phút. Rưới lượng nước đã ghi, thêm muối và đường, đảo đến khi rau vừa chín.
5. Nếm, tắt bếp khi cọng rau còn giòn và màu xanh; dọn ra đĩa ngay.

**Mẹo:** Không chất quá nhiều rau trong chảo nhỏ; chia mẻ để rau xào thay vì bị om. Công thức demo này bỏ dầu hào để giữ phiên bản chay; không dùng lại thành phần động vật từ một nguồn khác.  
**Nguồn tham khảo ý tưởng:** [Điện máy XANH — Rau muống xào tỏi](https://www.dienmayxanh.com/vao-bep/cach-lam-rau-muong-xao-toi-ngon-thom-nuc-mui-dan-da-kho-cuong-09390). Lượng và phiên bản chay là nội dung riêng của project.

## 4. Đậu phụ sốt cà chua chay — legacy ID 4

**Mô tả:** Đậu phụ áp chảo nhẹ, áo sốt cà chua tỏi chua ngọt dịu; dùng với cơm nóng.  
**Vai trò:** Món chính. **Chế độ:** Chay thực vật theo phiên bản demo; không dùng nước mắm, dầu hào hoặc hạt nêm chưa rõ thành phần. **Vùng:** Bắc/Trung/Nam (món phổ biến, đề xuất demo). **Mùa:** Quanh năm. **Dịp:** Hằng ngày, bữa chay.  
**Khẩu phần:** 4. **Chuẩn bị:** 15 phút. **Nấu:** 20 phút. **Tổng nhập Admin:** 35 phút.

| Nguyên liệu bắt buộc | Định lượng cho 4 người | Catalog |
|---|---:|---|
| Đậu phụ trắng | 600 g | ID 5 |
| Cà chua | 400 g | ID 2 |
| Tỏi | 8 g | ID 7 |
| Hành lá | 15 g | ID 17 |
| Dầu ăn | 20 ml | Đề xuất ID mới |
| Muối | 4 g | Đề xuất ID mới |
| Đường | 3 g | Đề xuất ID mới |
| Tiêu xay | 0.5 g | Đề xuất ID mới; form xay |
| Nước lọc | 100 ml | Nước sốt; không đưa vào picker User |

**Cách làm**

1. Đậu phụ để ráo, cắt miếng dày khoảng 2 cm. Cà chua rửa sạch, bỏ cuống, thái hạt lựu; tỏi băm, hành lá cắt nhỏ.
2. Làm nóng chảo với một nửa lượng dầu, áp chảo đậu ở lửa vừa đến khi hai mặt vàng nhạt; gắp ra.
3. Thêm phần dầu còn lại, phi tỏi ở lửa vừa đến thơm. Cho cà chua vào, đảo đến khi mềm và ra nước.
4. Thêm nước, muối và đường; đun nhỏ lửa 3–5 phút để sốt hòa quyện.
5. Cho đậu vào chảo, lật nhẹ để sốt phủ đều; om lửa nhỏ khoảng 5 phút đến khi sốt sánh và đậu nóng thấm vị.
6. Rắc tiêu và hành lá, tắt bếp, dọn nóng.

**Nhận biết hoàn thành:** Cà chua mềm thành sốt, sốt bám quanh miếng đậu; đậu nóng đều nhưng không nát.  
**Nguồn tham khảo ý tưởng:** [Điện máy XANH — Đậu hũ sốt cà chua chay](https://www.dienmayxanh.com/vao-bep/cach-lam-dau-hu-sot-ca-chua-chay-don-gian-de-lam-cho-bua-com-10227). Công thức này là bản demo riêng và khác snapshot legacy có tỏi tùy chọn; không gán nhãn chay cho snapshot cũ nếu chưa thay nội dung qua Admin.

## 5. Trứng kho mắm ruốc — Admin ID hiện tại 7980672317

**Mô tả:** Trứng kho lửa nhỏ với mắm ruốc pha loãng, tỏi và ớt; mặn thơm, ăn cùng cơm trắng và rau luộc.  
**Vai trò:** Món chính. **Chế độ:** Mặn, có trứng và mắm ruốc. **Vùng:** Miền Trung (đề xuất demo cho phiên bản mắm ruốc, không phải tuyên bố độc quyền vùng). **Mùa:** Quanh năm. **Dịp:** Hằng ngày.  
**Khẩu phần:** 4. **Chuẩn bị:** 15 phút. **Nấu:** 25 phút. **Tổng nhập Admin:** 40 phút.

| Nguyên liệu bắt buộc | Định lượng cho 4 người | Catalog |
|---|---:|---|
| Trứng gà | 6 quả | ID 1 |
| Mắm ruốc | 20 g | ID 26, giữ riêng |
| Tỏi | 8 g | ID 7 |
| Ớt tươi | 3 g | ID 23 |
| Đường | 10 g | Đề xuất ID mới |
| Dầu ăn | 15 ml | Đề xuất ID mới |
| Hành tím | 15 g | Chờ xác nhận alias/ID; chưa nhập |
| Nước lọc | 120 ml | Pha mắm/kho; không đưa vào picker User |

**Cách làm**

1. Luộc trứng từ nước nguội; khi sôi, hạ lửa và luộc khoảng 9–10 phút. Ngâm nước nguội, bóc vỏ, dùng dao khía nhẹ vài đường quanh quả.
2. Hòa mắm ruốc với nước, khuấy kỹ rồi để lắng cặn thô; dùng phần hỗn hợp đã hòa. Băm tỏi, thái ớt; hành tím thái mỏng.
3. Làm nóng nồi, cho dầu; phi hành tím và tỏi ở lửa nhỏ đến thơm, không để cháy.
4. Cho hỗn hợp mắm ruốc và đường vào, đun sôi nhẹ. Thêm trứng, đảo/lắc nồi để sốt phủ đều.
5. Kho lửa nhỏ khoảng 12–15 phút, trở trứng nhẹ giữa chừng. Thêm ớt trong vài phút cuối.
6. Tắt bếp khi sốt bám mặt trứng và có độ sánh nhẹ. Dọn nóng với cơm.

**Mẹo:** Mắm ruốc mặn theo nhãn sản phẩm; không tự thêm nước mắm vào công thức này. Nêm theo đúng lượng dự kiến và thử mẻ demo trước khi đổi định lượng.  
**Tách phiên bản:** Đây là bản `trứng kho mắm ruốc`, giữ ID 26. Nguồn tham khảo [FPT Shop — Trứng kho nước mắm](https://fptshop.com.vn/tin-tuc/dien-may/trung-kho-nuoc-mam-154369/) là phiên bản khác dùng Nước mắm ID 24; không ghép nguyên liệu hoặc hướng dẫn của nguồn đó vào recipe này.

## Nhập qua Admin: trường nào dùng được

| Trường chuẩn bị | Cách nhập hiện tại | Hạn chế |
|---|---|---|
| Tên, mô tả, vai trò | Form Thêm/Sửa món | Có thể lưu trực tiếp qua Admin; role recipe hiện chỉ có các slot mà editor hỗ trợ |
| Thời gian chuẩn bị + nấu | Ghi trong hướng dẫn/mô tả; nhập tổng vào `Thời gian` | Form chỉ có một `minutes`; các phút tách riêng không có cột lưu riêng |
| Nguyên liệu + lượng | Chọn ID chung trong picker; nhập chuỗi như `600 g`, `25 ml` | Quantity hiện là chuỗi tự do; không nhập `quantity_value/unit_id` riêng qua form |
| Mọi dòng nguyên liệu | Mỗi dòng lưu bắt buộc | UI không còn tùy chọn/optional; không thêm garnish không thiết yếu thành dòng riêng |
| Cách nấu | Dán các bước đánh số vào ô hướng dẫn | Có thể lưu chi tiết 4–8 bước |
| Ảnh | Giữ ảnh đang có; thay qua khu vực ảnh trong form nếu cần | Lượt này không upload ảnh; chỉ dùng ảnh đã có/fallback |
| Khẩu phần, vùng, chế độ ăn, mùa, dịp | Chưa có ô nhập tương ứng trên form món thông thường | Không thể nhập đầy đủ metadata qua Admin hiện tại; để trong hồ sơ ứng viên đến khi có trường hỗ trợ. Không hardcode cho User |

## Tác động tới B0/P1 và cách kiểm tra riêng

Không thay đổi B0/P1. Khi ingredient mới được tạo trong catalog chung, User có thể chọn ID đó. Khi ingredient được gắn vào recipe với hành vi hiện tại là bắt buộc, nó tham gia `required_ids`, làm thay đổi coverage, `missing_ids` và thứ tự xếp hạng. Ingredient nằm trong `all_ids` cũng có thể làm recipe bị loại nếu người dùng loại trừ nó.

Trước khi đưa bất kỳ profile nào vào catalog hoạt động, cần chạy trên TEST_ONLY: danh sách 50 legacy vẫn giữ ID, tạo ingredient mới qua Admin, tạo/sửa recipe qua overlay, xem lại recipe User, rồi đối chiếu RECOMMEND B0/P1 với và không có các seasoning ID mới. Không chạy thử ghi trên MySQL chính trong giai đoạn chuẩn bị này.

## Trạng thái triển khai

- 5 công thức chi tiết đã được chuẩn bị dưới dạng nội dung demo riêng.
- 4 ingredient mới đề xuất: Dầu ăn, Muối, Đường, Tiêu.
- Hành tím đang chờ quyết định mapping với ID 3; chưa tạo ID.
- Không thay đổi legacy, công thức công khai, MySQL, schema, migration hoặc thuật toán.
- Chưa nhập các công thức/nguyên liệu lên MySQL chính; chưa commit/push.
