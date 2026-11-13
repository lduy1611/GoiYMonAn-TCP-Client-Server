# Hồ sơ chuẩn hóa thử 5 món — chỉ chuẩn bị, chưa nhập

**Ngày lập:** 08/11/2026  
**Nguồn trạng thái hiện có:** kiểm kê `docs/data-normalization-audit-2026-11-08.md` và catalog User đọc ở chế độ chỉ đọc.  
**Quy tắc:** thông tin trong snapshot DB là dữ liệu đang lưu, không phải đã được xác minh nguồn. Thông tin từ trang công thức được chép vào một **ứng viên phiên bản riêng**, không ghép số liệu từ snapshot DB. `NEEDS_VERIFICATION` nghĩa là chưa đủ căn cứ để lưu thành dữ liệu chuẩn hoặc bật nhãn tương ứng.

## Chọn 5 đại diện

| Nhóm | Món và ID đang có | Trạng thái hồ sơ |
|---|---|---|
| Mặn/món chính | Cá basa kho gừng — legacy ID 7 | Có nguồn ứng viên; khác snapshot hiện tại và chưa có đủ lượng/khẩu phần/thời gian |
| Canh | Canh gà nấm hương — legacy ID 6 | Có nguồn cùng tên, khẩu phần 4; cần xác nhận phiên bản và thời gian chuẩn bị/nấu |
| Rau | Rau muống xào tỏi — legacy ID 5 | Có nguồn chi tiết, khẩu phần và thời gian; nguồn có dầu hào thường nên không phải công thức chay |
| Chay | Đậu phụ sốt cà chua — legacy ID 4 | Nguồn gọi rõ món chay; ứng viên nguồn khác snapshot DB, nhãn trong hệ thống vẫn chờ duyệt |
| Admin mới | trứng kho — ID 7980672317 | Snapshot chỉ có Mắm ruốc tùy chọn, thiếu lượng và hướng dẫn; nguồn tìm được là trứng kho **nước mắm**, không cùng công thức. Không được ghép hai phiên bản |

### Cách đọc hồ sơ

- **Snapshot hiện tại:** giá trị đúng theo catalog đang công khai tại thời điểm kiểm kê.
- **Ứng viên nguồn:** các trường được trang nguồn nêu cho một phiên bản riêng. URL và nội dung cùng nguồn được giữ cùng nhau.
- Các món legacy có mô tả, khẩu phần gốc, thời gian chuẩn bị và thời gian nấu riêng đều đang thiếu trong snapshot. Không lấy trường đó từ ứng viên nguồn rồi ghi đè snapshot.
- Vai trò legacy bên dưới là phân loại đang dùng; vai trò áp dụng cho combo vẫn cần người duyệt. Vùng miền, mùa, dịp và vai trò đã xác minh: `NEEDS_VERIFICATION` nếu nguồn không nói rõ.

## 1. Cá basa kho gừng — món mặn

**Định danh hiện tại:** legacy ID `7`; vai trò catalog `main`; tổng thời gian `30` phút; ảnh tĩnh; snapshot có Cá basa `300 g`, Gừng `1 nhánh`; hướng dẫn hiện có ba bước ngắn. Không có mô tả/khẩu phần.

**Ứng viên nguồn:** [CET — 7 cách làm cá basa kho](https://www.cet.edu.vn/cach-lam-ca-basa-kho), mục “Cá basa kho gừng”. Trang ghi cá basa `400 g`; liệt kê nước màu kho cá, hạt nêm, nước mắm, tiêu, đường, dầu ăn, tỏi, ớt, hành khô và hành lá; hướng dẫn dùng gừng nhưng danh sách nguyên liệu không ghi lượng gừng. Nguồn không nêu khẩu phần hoặc thời gian chuẩn bị/nấu riêng. Một số lượng “muỗng” trong hướng dẫn không chỉ rõ muỗng canh hay cà phê.

| Trường hồ sơ ứng viên | Giá trị được nguồn nêu | Trạng thái |
|---|---|---|
| Tên | Cá basa kho gừng | Có trong snapshot và tên mục nguồn |
| Mô tả | Chưa có mô tả định lượng/nội dung mô tả thống nhất từ nguồn | `NEEDS_VERIFICATION` |
| Vai trò | Món chính (vai trò catalog hiện tại) | `NEEDS_VERIFICATION` cho metadata chuẩn |
| Khẩu phần gốc | Không nêu | `NEEDS_VERIFICATION` |
| Chuẩn bị / nấu | Không tách thời gian; snapshot hiện tại chỉ có tổng 30 phút | `NEEDS_VERIFICATION` |
| Nguyên liệu | Cá basa 400 g; gừng, nước màu, hạt nêm, nước mắm, tiêu, đường, dầu ăn, tỏi, ớt, hành khô, hành lá | Danh sách nguồn có; nhiều lượng thiếu |
| Các lượng nguồn | Cá basa 400 g; ướp 15 phút; ½ muỗng hạt nêm, 1 muỗng đường, 1 muỗng nước mắm, 1 muỗng dầu, 1 muỗng nước màu | Đơn vị “muỗng” chưa được phân biệt; cần xác minh trước khi chuẩn hóa |
| Bước nguồn | Ướp cá; chia gừng thái sợi/giã cùng tỏi, hành khô, ớt; lót gừng, kho lửa nhỏ, thêm nước khi sôi, nêm lại; cho hành lá khi cá chín | Có thể tóm tắt từ cùng mục nguồn; thời gian kho và mức lửa chi tiết chưa nêu |
| Dấu hiệu hoàn thành | Nguồn ghi cá chín; snapshot ghi nước kho sánh | Cần người duyệt quy tắc quan sát |
| Mẹo/bảo quản | Không có dữ liệu lưu trữ được xác minh trong cùng mục nguồn | `NEEDS_VERIFICATION` |
| Chế độ ăn | Mặn/không chay do có cá và nước mắm | Có căn cứ thành phần; cần duyệt metadata |
| Vùng miền, mùa, dịp | Không gán từ tên món | `NEEDS_VERIFICATION` |

**Khác biệt cần quyết định:** nguồn dùng cá 400 g nhưng snapshot 300 g; nguồn thêm nhiều gia vị. Không lấy lượng nguồn để thay các dòng hiện tại. Cần chọn rõ có tạo một revision nguồn mới hay tiếp tục xác minh revision hiện có.

## 2. Canh gà nấm hương — món canh

**Định danh hiện tại:** legacy ID `6`; vai trò catalog `soup`; tổng thời gian `35` phút; snapshot: gừng `1 nhánh`, nấm hương `50 g`, cà rốt `1 củ`, thịt gà `300 g`; ba bước ngắn, không có khẩu phần/mô tả.

**Ứng viên nguồn:** [FPT Shop — Canh gà nấm hương](https://fptshop.com.vn/tin-tuc/dien-may/canh-ga-nam-huong-186663/). Nguồn ghi công thức cho 4 người: thịt gà `500 g`, nấm hương `300 g`, cà rốt `1 củ`, hành lá `3 nhánh`, gừng `1 nhánh`; gia vị gồm bột canh, tiêu, hạt nêm, nước mắm nhưng không có lượng cụ thể. Nguồn hướng dẫn ướp gà 30 phút; nấu gà trong 1 lít nước khoảng 20 phút, thêm nấm 10 phút, cà rốt thêm khoảng 3 phút; cuối cùng hành lá và nêm lại. Không có tách tổng thời gian chuẩn bị/nấu đáng tin cậy, vì bước ướp 30 phút cần được tính nhất quán.

| Trường hồ sơ ứng viên | Giá trị được nguồn nêu | Trạng thái |
|---|---|---|
| Tên | Canh gà nấm hương | Có trong snapshot và nguồn |
| Mô tả | Nguồn mô tả canh gà, nấm, cà rốt; chưa chốt câu mô tả biên tập | Đề xuất biên tập, chưa duyệt |
| Vai trò | Canh (vai trò catalog hiện tại) | `NEEDS_VERIFICATION` cho metadata chuẩn |
| Khẩu phần gốc | 4 người | Nguồn nêu rõ; cần ghi nhận phiên bản nguồn và duyệt |
| Chuẩn bị / nấu | Chuẩn bị không tách rõ; hướng dẫn có ướp 30 phút và nấu khoảng 33 phút theo các đoạn nguồn | Cần xác minh cách tính thời gian, không cộng/đổi thành một con số khác |
| Nguyên liệu | Thịt gà 500 g; nấm hương 300 g; cà rốt 1 củ; hành lá 3 nhánh; gừng 1 nhánh; bột canh, tiêu, hạt nêm, nước mắm | Các gia vị không định lượng |
| Bước nguồn | Sơ chế gà/nấm/cà rốt/gừng/hành; ướp gà với gừng, tiêu, bột canh 30 phút; nấu gà trong 1 lít nước khoảng 20 phút; thêm nấm 10 phút; cà rốt khoảng 3 phút; nêm và cho hành lá | Tóm tắt đúng một mục nguồn; bước đầu sơ chế cần đối chiếu dòng đầy đủ trước khi duyệt |
| Dấu hiệu hoàn thành | Gà mềm; nấm chín mềm; nguồn ghi canh có màu từ gà, hành, cà rốt, nấm | Có mô tả nguồn, chưa có kiểm tra nhiệt độ lõi |
| Mẹo/bảo quản | Nguồn khuyên hớt bọt để nước trong; không có thời hạn bảo quản | Mẹo nguồn có; bảo quản `NEEDS_VERIFICATION` |
| Chế độ ăn | Không chay: thịt gà và gia vị nước mắm | Có căn cứ thành phần; cần duyệt metadata |
| Vùng miền, mùa, dịp | Không gán theo tên/nguồn xuất bản | `NEEDS_VERIFICATION` |

**Khác biệt cần quyết định:** nguồn có thêm hành lá và gia vị; định lượng gà/nấm khác snapshot. Không trộn công thức hiện tại (300 g gà/50 g nấm) với khẩu phần 4 người từ nguồn này.

## 3. Rau muống xào tỏi — món rau

**Định danh hiện tại:** legacy ID `5`; vai trò catalog `vegetable`; tổng thời gian `12` phút; snapshot: rau muống `300 g`, tỏi `2 tép`; hướng dẫn nói chần rau, phi tỏi với dầu và xào lửa lớn; dầu chưa có dòng ingredient.

**Ứng viên nguồn:** [Điện máy XANH — Rau muống xào tỏi](https://www.dienmayxanh.com/vao-bep/cach-lam-rau-muong-xao-toi-ngon-thom-nuc-mui-dan-da-kho-cuong-09390). Nguồn ghi 2 người, chuẩn bị 15 phút, chế biến 15 phút; rau muống `500 g`, tỏi `2 củ`, dầu hào `1 muỗng canh`, dầu ăn `2 muỗng canh`, nhóm gia vị thông dụng một ít (đường/muối/hạt nêm/bột ngọt). Nguồn xào rau khoảng 5 phút trên lửa lớn, sau đó nêm; nguồn có thể nêm theo khẩu vị. Dầu hào thông thường có thành phần hàu, vì vậy profile này **không được gắn Chay**.

| Trường hồ sơ ứng viên | Giá trị được nguồn nêu | Trạng thái |
|---|---|---|
| Tên | Rau muống xào tỏi | Có trong snapshot và nguồn |
| Mô tả | Món rau xào tỏi; mô tả biên tập chưa duyệt | Đề xuất biên tập, chưa duyệt |
| Vai trò | Rau (vai trò catalog hiện tại) | `NEEDS_VERIFICATION` cho metadata chuẩn |
| Khẩu phần gốc | 2 người | Nguồn nêu rõ; cần duyệt |
| Chuẩn bị / nấu | 15 phút / 15 phút | Nguồn nêu rõ; snapshot tổng 12 phút là giá trị khác, không ghi đè |
| Nguyên liệu | Rau muống 500 g; tỏi 2 củ; dầu hào 1 muỗng canh; dầu ăn 2 muỗng canh; nhóm đường/muối/hạt nêm/bột ngọt “1 ít”; nước khoảng 1/4 chén trong hướng dẫn | Nhóm gia vị không có lượng từng món; cần tách và xác minh nếu muốn danh sách đi chợ chính xác |
| Bước nguồn | Nhặt/cắt, rửa và để ráo rau; sơ chế tỏi; phi tỏi; xào rau lửa lớn khoảng 5 phút, thêm nước rồi nêm gia vị; nêm lại theo khẩu vị | Có căn cứ cùng nguồn; không tự thêm lượng nêm |
| Dấu hiệu hoàn thành | Nguồn mô tả rau chín, xanh và giòn; tránh xào quá lâu | Nêu trong nguồn |
| Trình bày/mẹo | Dọn sau khi tắt bếp; nguồn khuyên thao tác nhanh/lửa lớn | Mẹo có căn cứ; thời gian giữ món `NEEDS_VERIFICATION` |
| Chế độ ăn | Không xác nhận chay do công thức có dầu hào thường | Không gắn Chay |
| Vùng miền, mùa, dịp | Không gán; nguồn nói món gia đình không đủ chứng minh metadata vùng/dịp | `NEEDS_VERIFICATION` |

**Khác biệt cần quyết định:** 500 g rau và 2 củ tỏi ở nguồn khác với 300 g/2 tép trong snapshot. “Gia vị thông dụng 1 ít” chưa đủ để tạo dòng định lượng cấu trúc cho từng gia vị.

## 4. Đậu phụ sốt cà chua — ứng viên món chay

**Định danh hiện tại:** legacy ID `4`; vai trò catalog `main`; tổng thời gian `20` phút; snapshot: cà chua `2 quả`, đậu phụ `2 miếng`, tỏi `1 tép` tùy chọn. Hướng dẫn snapshot có phi tỏi; đây là dấu hiệu cần xác minh thành phần của đúng phiên bản, không tự kết luận là Chay.

**Ứng viên nguồn:** [Điện máy XANH — Đậu hũ sốt cà chua chay, cách 1](https://www.dienmayxanh.com/vao-bep/cach-lam-dau-hu-sot-ca-chua-chay-don-gian-de-lam-cho-bua-com-10227). Nguồn gọi rõ món chay, khẩu phần `2–3 người`, chuẩn bị 20 phút, chế biến 15 phút; đậu hũ chiên `3 miếng`, cà chua `2 trái`, dầu ăn `2 muỗng canh`, hạt nêm chay `2 muỗng cà phê`, bột ngọt `2 muỗng cà phê`, muối `1 muỗng cà phê`. Hướng dẫn dùng lửa lớn để xào cà chua khoảng 5 phút; hạ lửa nhỏ, cho đậu vào, nêm và đảo khoảng 3 phút. Tiêu và hành lá được gợi ý như đồ rắc thêm nhưng không có định lượng.

| Trường hồ sơ ứng viên | Giá trị được nguồn nêu | Trạng thái |
|---|---|---|
| Tên | Đậu hũ sốt cà chua chay | Tên nguồn; catalog hiện không có hậu tố “chay” |
| Mô tả | Đậu hũ sốt cà chua; câu mô tả biên tập chưa duyệt | Đề xuất biên tập, chưa duyệt |
| Vai trò | Món chính theo catalog hiện tại | Cần duyệt xem phù hợp slot chính |
| Khẩu phần gốc | 2–3 người (khoảng, không phải một số chính xác) | Ghi khoảng hoặc yêu cầu xác minh; không tự chuyển thành 2 hay 3 |
| Chuẩn bị / nấu | 20 / 15 phút | Nguồn nêu rõ; snapshot tổng 20 phút là dữ liệu khác phiên bản |
| Nguyên liệu | Đậu hũ chiên 3 miếng; cà chua 2 trái; dầu ăn 2 muỗng canh; hạt nêm chay 2 muỗng cà phê; bột ngọt 2 muỗng cà phê; muối 1 muỗng cà phê; tiêu/hành lá tùy chọn không lượng | Các lượng chính có nguồn; tùy chọn không lượng |
| Bước nguồn | Cắt đậu hũ và cà chua; xào cà chua với dầu trên lửa lớn khoảng 5 phút; hạ lửa nhỏ, cho đậu; nêm và đảo khoảng 3 phút rồi dọn | Tóm tắt từ cùng phiên bản nguồn |
| Dấu hiệu hoàn thành | Sốt sệt; đậu thấm gia vị, bề mặt sốt đỏ; nguồn mô tả thành phẩm | Căn cứ mô tả nguồn |
| Trình bày/mẹo | Có thể rắc tiêu và hành lá; không có lượng | Nguồn nêu tùy chọn; bảo quản `NEEDS_VERIFICATION` |
| Chế độ ăn | Nguồn công bố phiên bản này là chay; chưa phê duyệt nhãn trong project, cần kiểm tra nhãn sản phẩm “hạt nêm chay” | `NEEDS_VERIFICATION` trong hệ thống |
| Vùng miền, mùa, dịp | Không gán | `NEEDS_VERIFICATION` |

**Khác biệt cần quyết định:** nguồn phiên bản chay không dùng tỏi, trong khi snapshot đang có tỏi tùy chọn và có hướng dẫn phi tỏi. Không thể phê duyệt snapshot hiện tại thành Chay chỉ nhờ tên. Nếu chọn nguồn này, cần một revision tách biệt, không trộn với snapshot hiện có.

## 5. trứng kho — món Admin mới

**Định danh hiện tại:** Admin ID `7980672317`; vai trò catalog `main`; tổng thời gian `30` phút; ảnh Admin. Snapshot có đúng một dòng `Mắm ruốc` tùy chọn, thiếu lượng; mô tả rỗng; hướng dẫn “sơ chế”. Snapshot này **không phải một công thức hoàn chỉnh**.

**Nguồn thay thế cần chủ sở hữu xác nhận:** [FPT Shop — Trứng kho nước mắm](https://fptshop.com.vn/tin-tuc/dien-may/trung-kho-nuoc-mam-154369/). Nguồn ghi 5 trứng vịt hoặc gà, hành lá 2 nhánh, ớt 1 trái, nước mắm 2 muỗng canh, tiêu 1 muỗng cà phê, bột ngọt 1/2 muỗng cà phê, dầu ăn 1 muỗng canh; không nêu khẩu phần, thời gian chuẩn bị hoặc tổng thời gian. Hướng dẫn: luộc trứng khoảng 10 phút; pha và làm nóng sốt; thêm tương ớt 1 thìa cà phê và 100 ml nước, kho đến khi sốt sánh và trứng nâu; dọn với hành lá/tiêu. Đây là phiên bản **trứng kho nước mắm**, không phải phiên bản mắm ruốc đang lưu.

| Trường hồ sơ ứng viên | Giá trị được nguồn nêu | Trạng thái |
|---|---|---|
| Tên | Trứng kho nước mắm | Không tự đổi tên món đang lưu; cần xác nhận định danh |
| Mô tả | Chưa có | `NEEDS_VERIFICATION` |
| Vai trò | Món chính (vai trò hiện tại) | `NEEDS_VERIFICATION` |
| Khẩu phần gốc | Không nêu, dù công thức liệt kê 5 quả trứng | Không suy ra số người từ số trứng |
| Chuẩn bị / nấu | Chuẩn bị không nêu; luộc trứng khoảng 10 phút, sau đó kho tới khi sốt sánh nhưng không có thời gian hoàn tất | Thời gian chưa đầy đủ |
| Nguyên liệu nguồn | Trứng 5 quả; hành lá 2 nhánh; ớt 1 trái; nước mắm 2 muỗng canh; tiêu 1 muỗng cà phê; bột ngọt 1/2 muỗng cà phê; dầu ăn 1 muỗng canh; tương ớt 1 thìa cà phê; nước 100 ml | Cùng một mục nguồn; không có dòng mắm ruốc |
| Bước nguồn | Luộc trứng khoảng 10 phút, ngâm nguội/bóc; pha sốt và làm nóng nhẹ với hành/ớt; thêm nước và tương ớt, cho trứng vào, kho đến sốt sánh/màu nâu; rắc hành/tiêu | Tóm tắt từ nguồn |
| Chế độ ăn | Không chay: có trứng và nước mắm | Nhãn cần duyệt |
| Vùng miền, mùa, dịp | Không gán | `NEEDS_VERIFICATION` |
| Mẹo/bảo quản | Nguồn khuyên không để chảo quá nóng khi làm sốt; thời gian bảo quản không nêu | Mẹo có nguồn; bảo quản `NEEDS_VERIFICATION` |

**Quyết định cần có:** xác nhận Admin ID này định mô tả `trứng kho nước mắm`, một món `trứng kho mắm ruốc` khác, hay bản ghi cần bỏ khỏi phạm vi pilot. Không thay dòng Mắm ruốc bằng nước mắm và không dùng lượng của nguồn FPT để lấp dữ liệu hiện tại nếu chưa có quyết định phiên bản.

## Đối chiếu nguyên liệu hiện có và danh sách cần bổ sung

Các ID chắc chắn khớp theo tên trong 50 nguyên liệu User: Trứng `1`, Cà chua `2`, Đậu phụ `5`, Rau muống `6`, Tỏi `7`, Gừng `8`, Nấm hương `9`, Cà rốt `10`, Cá basa `13`, Thịt gà `14`, Hành lá `17`, Ớt `23`, Nước mắm `24`, Mắm ruốc `26`. Các dòng “hành khô” không tự map vào `Hành` ID `3`; người duyệt cần xác nhận dạng nguyên liệu. Tương tự, “hạt nêm chay” không phải tên/ID của hạt nêm thường.

| Tên thấy trong các ứng viên nguồn, chưa có ID exact trong catalog 50 | Món/nguồn | Hành động đề xuất |
|---|---|---|
| Dầu ăn | 4/5 nguồn: cá basa, rau muống, đậu hũ chay, trứng kho | Ứng viên ingredient mới; xác minh trùng/alias trong DB trước khi tạo |
| Muối | Rau muống, tofu, canh; các nguồn khác | Ứng viên ingredient mới; giữ riêng với Bột canh |
| Đường | Cá kho, rau muống, trứng kho | Ứng viên ingredient mới |
| Tiêu / tiêu xay | Cá kho, canh, tofu garnish, trứng kho | Một khái niệm chuẩn hóa cần quyết định; không tạo ID riêng chỉ vì biến thể cách xay |
| Hạt nêm | Cá kho, canh, rau | Chưa có ID; xác minh sản phẩm và nhãn thành phần |
| Hạt nêm chay | Tofu chay | Không gộp với hạt nêm thường; nhãn sản phẩm phải được xác minh |
| Bột ngọt | Rau muống, tofu, trứng kho | Chưa có ID exact |
| Bột canh | Canh gà | Khác “muối”; không tự map |
| Dầu hào thường | Rau muống xào tỏi | Chưa có ID; thường có hàu, vì thế không được gắn nhãn chay |
| Nước màu kho cá | Cá basa kho gừng | Chưa có ID; xác minh thành phần/loại trước khi tạo |
| Tương ớt | Trứng kho | Chưa có ID; kiểm tra cách hệ thống mô hình hóa sản phẩm phối trộn |

Không đề xuất tạo ID cho nước, dụng cụ, hoặc nguyên liệu được nhắc trong bước làm sạch nếu chúng không phải thành phần tiêu thụ của món. Các nguồn ứng viên không nhắc thêm thịt/hải sản mới ngoài những thành phần đã liệt kê ở từng hồ sơ. Dầu hào thường là thành phần động vật; các công thức khác cũng cần rà nhãn sản phẩm phối trộn trước khi xác minh Chay.

## Cách lưu qua Admin/overlay mà không phá legacy

- 4 món legacy có thể tiếp tục được đọc/sửa qua **legacy recipe overlay** hiện có; overlay ghi đè tên, mô tả, hướng dẫn, tổng phút và danh sách ingredient/chuỗi quantity/required, không sửa bảng món legacy hay 252 quan hệ gốc.
- Overlay hiện không có các trường khẩu phần gốc, lượng số học/unit chuẩn, ingredient form, bằng chứng nguồn, thời gian chuẩn bị riêng, thời gian nấu riêng, mẹo/bảo quản hoặc metadata vùng/mùa/dịp. Không nhét các giá trị đó vào mô tả/hướng dẫn hoặc quantity chuỗi để giả lập.
- Schema v2 đã có revision, `base_servings`, các dòng nguyên liệu với `amount_kind`, min/max, `unit_id`, `form_id`, requirement, evidence và review. Đây là nơi phù hợp để chuẩn bị dữ liệu cấu trúc; phải dùng revision riêng, giữ dữ liệu cũ, gắn nguồn/bằng chứng và để trạng thái chưa duyệt cho đến khi reviewer quyết định.
- Form Admin đang quản lý món thông thường không đủ để nhập/duyệt toàn bộ metadata portion/evidence. Vì lượt này chỉ chuẩn bị, **không tạo draft, không sửa Admin UI và không nhập DB**. Khi triển khai, cần bảo đảm nguồn/portion approval riêng, không tự công khai nhãn Chay hay số lượng chưa xác minh.
- Món Admin `trứng kho` hiện đã công khai nhưng nguồn FPT là một phương án khác công thức Mắm ruốc hiện lưu. Không thay revision/catalog hiện tại trước khi chủ sở hữu quyết định dùng nguồn nào.

## Tác động dự kiến lên B0/P1 — không thay thuật toán

Trong `source/server/ranking.py`, B0/P1 tính khớp trên `required_ids`; mọi ingredient được đặt thành bắt buộc có thể đổi điểm, `missing_ids` và thứ tự gợi ý. Gia vị không có mặt trong bộ lọc User hiện nay—Dầu ăn, Muối, Đường, Tiêu, Hạt nêm—không thể được chọn làm filter cho đến khi có ID/catalog phù hợp. Khi thêm ingredient vào công thức qua overlay, nếu line thành `required`, nó cũng tham gia điều kiện/điểm B0/P1. Nếu line là optional, nó vẫn thuộc `all_ids` và có thể khiến món bị loại khi người dùng loại trừ ingredient đó. Không tự đánh dấu gia vị là optional để “làm đẹp” kết quả; requirement phải theo công thức nguồn và chính sách đã duyệt.

Đề xuất pilot không yêu cầu sửa B0/P1. Sau này chỉ thay dữ liệu trong TEST_ONLY, so sánh baseline/current với dataset fixture và kiểm tra cả lọc loại trừ trước khi xem xét đưa dữ liệu đã duyệt lên production.

## Các mục cần người duyệt quyết định trước khi nhập

1. Với mỗi món legacy, chọn giữ nguyên snapshot và tìm nguồn đúng phiên bản, hay tạo revision ứng viên mới từ một nguồn nêu ở đây. Không ghép lượng hai nguồn.
2. Chốt nguồn/phiên bản và lượng đơn vị cho các gia vị hiện chỉ ghi “một ít”, “muỗng” không rõ loại, hoặc chưa có lượng.
3. Chốt khẩu phần gốc/time split theo đúng nguồn; các trường còn trống ở trên tiếp tục `NEEDS_VERIFICATION`.
4. Xác minh ingredient IDs mới/alias, đặc biệt dầu ăn, muối, đường, tiêu, hạt nêm, bột ngọt và sản phẩm “chay”. Không tạo bản ghi trước khi biết catalog/runtime admin sẽ dùng identity nào.
5. Chốt role, diet, region, season, occasion riêng; chỉ bật nhãn có bằng chứng và review tương ứng.
6. Quyết định bản ghi Admin `trứng kho` có ý định là trứng kho nước mắm hay mắm ruốc. Không thay công thức đang công khai trong khi chưa có quyết định.

**Kết luận pilot:** nguồn công khai đủ chi tiết để tạo các hồ sơ ứng viên cho rau muống xào tỏi và phiên bản đậu hũ sốt cà chua chay; canh gà có khẩu phần/ingredient/steps nhưng nguồn chưa tách thời gian; cá basa và trứng kho còn các trường nguồn/đơn vị/identity phải xác minh. Không hồ sơ nào được tự động đánh dấu `APPROVED`, và báo cáo này chưa ghi dữ liệu vào MySQL.

