# Danh sách ứng viên chuẩn hóa nguyên liệu từ pilot 5 món

**Ngày đối chiếu:** 08/11/2026  
**Phạm vi:** đọc `docs/data-normalization-pilot-5.md`, Admin ingredient form/API và User catalog hiện tại từ public repository trên MySQL. Truy vấn catalog chỉ đọc. Không tạo/sửa/xóa dữ liệu, không tạo migration.

## Kết quả đối chiếu

User catalog hiện trả **50 nguyên liệu đang hoạt động**, dùng ID legacy ban đầu. Admin ingredient form hiện có thể thêm/sửa **tên** và bật/ngừng hoạt động; không có form nhập alias, nhóm, dạng nguyên liệu, đơn vị, bằng chứng nguồn hoặc trạng thái xác minh. API create/update chỉ nhận `name`; logic kiểm tra tên trùng chuẩn hóa chữ hoa/thường/dấu cách, không phải công cụ xác minh hai tên khác nhau là cùng một nguyên liệu.

Trong năm hồ sơ có 14 tên khớp trực tiếp ID hiện có (13 tên dùng trong các phiên bản nguồn và Mắm ruốc ID 26 trong snapshot Admin hiện tại), 11 ứng viên tên chuẩn chưa thấy trong catalog 50, và 3 nhóm có thể là alias của identity hiện có cần xác minh trước khi tạo mới. Những con số đếm theo khái niệm nguyên liệu; “Gia vị thông dụng 1 ít” là nhóm chưa tách thành từng thành phần nên không đếm là ingredient.

User public projection hiện lấy 50 ID legacy làm nền; Admin dùng chế độ catalog `shared` trên cùng danh sách và có thể hiện các identity được Admin chủ động tạo. ID legacy vẫn giữ nguyên; identity v2 có public ID riêng khi không crosswalk/khớp tên. Việc thêm tên vào catalog User không đồng nghĩa recipe đã được duyệt hoặc tự thêm ingredient vào mọi công thức.

## A. Đã có trong catalog — dùng lại ID gốc

| ID | Tên chuẩn đang dùng | Xuất hiện trong pilot | Ghi chú |
|---:|---|---|---|
| 1 | Trứng | Trứng kho nước mắm nguồn | Dùng ID này cho trứng; trứng vịt/gà có thể cần form/loại riêng, không tạo ID mới ngay |
| 2 | Cà chua | Đậu phụ sốt cà chua chay | Giữ ID hiện tại |
| 3 | Hành | Chỉ là ứng viên có thể liên quan “hành khô” | Chưa xác nhận đồng nghĩa; xem nhóm B |
| 5 | Đậu phụ | Đậu phụ sốt cà chua chay | `đậu hũ` là cách gọi có thể là alias; cần xác nhận để tìm kiếm, không tạo ID mới |
| 6 | Rau muống | Rau muống xào tỏi | Lượng/đơn vị khác nguồn không đổi identity |
| 7 | Tỏi | Rau muống, cá kho | `tỏi băm/xay` là dạng sơ chế, không phải nguyên liệu khác |
| 8 | Gừng | Cá kho, canh gà | Dùng cùng ID; lượng theo đúng revision |
| 9 | Nấm hương | Canh gà | Nguồn có thể gọi nấm đông cô; cần thống nhất alias theo dạng tươi/khô |
| 10 | Cà rốt | Canh gà | Giữ ID hiện tại |
| 13 | Cá basa | Cá basa kho gừng | Giữ ID hiện tại |
| 14 | Thịt gà | Canh gà nấm hương | Dùng chung ID; phần thịt/form (đùi, nguyên con, lọc xương) thuộc dạng hoặc mô tả dòng |
| 17 | Hành lá | Canh gà, tofu garnish, trứng kho | Nguồn ghi đúng tên; không gộp với `Hành` ID 3 |
| 23 | Ớt | Cá kho, trứng kho | Dùng ID cho ớt tươi; không gộp với tương ớt |
| 24 | Nước mắm | Cá kho, canh, trứng kho nước mắm | Giữ tách biệt với Mắm ruốc và Nước mắm chay |
| 26 | Mắm ruốc | Snapshot món Admin `trứng kho` hiện có | Giữ nguyên cho phiên bản đang lưu; không thay bằng ID 24 |

## B. Có khả năng là tên đồng nghĩa/dạng khác — cần xác minh trước khi tạo ID

| Tên gặp trong nguồn | Ứng viên có thể liên quan | Phân loại | Đề xuất tên hiển thị/nhóm | Đơn vị thường gặp để cân nhắc | Quyết định chưa được phép tự động |
|---|---|---|---|---|---|
| Hành khô | `Hành` ID 3 hoặc hành tím | Danh tính mơ hồ: hành khô thường chỉ hành tím khô, nhưng ID 3 chỉ ghi chung “Hành” | Nếu xác nhận là hành tím: `Hành tím`, nhóm rau củ/gia vị thơm | g, củ | Không tạo alias hoặc dùng ID 3 cho tới khi xác nhận loại hành mà recipe source muốn nói |
| Hành tím | Hành khô; có thể nhưng chưa chắc là `Hành` ID 3 | Chưa thấy trong năm nguồn như một dòng định lượng độc lập ngoài cách gọi hành khô; người dùng yêu cầu kiểm tra tên này | `Hành tím`, nhóm rau củ/gia vị thơm | g, củ | Nếu ID 3 thực sự là hành tím, chỉ thêm alias đã duyệt; nếu là hành tây/hành củ khác thì cần identity riêng |
| Tiêu xay / hạt tiêu | `Tiêu` (chưa có ID) | Cùng nguyên liệu ở dạng xay có khả năng là form, không nên tạo ID riêng chỉ vì cách xay | Tên chuẩn đề xuất `Tiêu`; form `xay` nếu hệ thống hỗ trợ | g, muỗng cà phê theo nguồn | Chốt liệu catalog chỉ cần identity Tiêu và lưu form trên dòng công thức |
| Nước màu kho cá | Nước màu / nước hàng | Có thể là cùng loại nước màu thắng đường nhưng cách làm/sản phẩm có thể khác | Tên chuẩn tạm `Nước màu`; nhóm gia vị/sốt | ml, muỗng canh nếu nguồn định rõ | Xác nhận thành phần và cách làm trước khi đặt synonym `nước hàng` |
| Đậu hũ | `Đậu phụ` ID 5 | Đồng nghĩa tiếng Việt phổ biến; cùng nguồn gọi đậu hũ trong khi catalog dùng đậu phụ | Giữ `Đậu phụ`, alias ứng viên `đậu hũ` | miếng, g | Kiểm tra alias chưa tồn tại rồi mới thêm ở công cụ hỗ trợ alias; hiện Admin không có chức năng này |
| Nấm đông cô | `Nấm hương` ID 9 | Tên thường được dùng cho cùng loại nấm, nhưng nguồn có thể là tươi/khô | Giữ `Nấm hương`, alias ứng viên `nấm đông cô`; dạng tươi/khô là form | g, cái | Không gộp khác dạng vật lý nếu phép tính khẩu phần cần phân biệt khô/tươi |
| Dầu ăn / dầu thực vật | Chưa có identity trong catalog 50 | “Dầu thực vật” có thể chỉ nhóm dầu, không phải mọi loại dầu ăn tương đương | Tên chuẩn ứng viên `Dầu ăn`, nhóm dầu/chất béo | ml; giữ đơn vị nguồn như muỗng canh nếu chưa có quy tắc đổi | Chốt có chấp nhận dầu thực vật làm alias chung hay chỉ alias theo loại dầu cụ thể |
| Muối ăn | Chưa có identity; không đồng nghĩa với Bột canh | Cùng nhóm gia vị nhưng hai sản phẩm/định lượng khác nhau | Tên chuẩn `Muối`; nhóm gia vị cơ bản | g, nhúm hoặc muỗng cà phê theo nguồn | Không map sang Bột canh; chốt có chuẩn hóa “muối ăn” thành alias không |
| Đường cát | Chưa có identity | `Đường` là tên chuẩn tổng quát; đường phèn/thốt nốt khác công dụng và tính chất | Tên chuẩn ứng viên `Đường`; nhóm gia vị cơ bản | g, muỗng cà phê/muỗng canh theo nguồn | Nguồn pilot ghi “đường” hoặc “đường” không rõ loại; không tự gán là đường cát |
| Bột ngọt / mì chính | Chưa có identity | Hai tên thường được dùng cho MSG; vẫn cần thống nhất tên/alias trong catalog | Tên chuẩn đề xuất `Bột ngọt`; nhóm gia vị | g, muỗng cà phê theo nguồn | Xác minh quy ước tên và alias; không nhập hai bản ghi |
| Hạt nêm / bột nêm | Chưa có identity | Tên có thể khác thương hiệu/thành phần; không giả định mọi loại có cùng profile | Tên chuẩn ứng viên `Hạt nêm`; nhóm gia vị phối trộn | g hoặc lượng gói; ghi nguyên đơn vị nguồn | Cần dữ liệu nhãn thành phần nếu dùng cho xác minh Chay |
| Hành lá / hành xanh / scallion | `Hành lá` ID 17 | `Hành lá` đã có alias `spring onion`; các tên Việt khác vẫn cần xác nhận | Giữ `Hành lá` | g, nhánh/cây | Không gộp vào `Hành` ID 3 |

## C. Chưa có trong catalog — ứng viên cần Admin bổ sung sau khi được duyệt

Đây là tên chuẩn **đề xuất**, chưa tạo dữ liệu và chưa được chủ sở hữu duyệt. Đơn vị là lựa chọn thiết kế để xem xét, không chuyển đổi lượng của nguồn.

| Tên chuẩn đề xuất | Nhóm | Nguồn/món dùng | Đơn vị nên hỗ trợ | Tên đồng nghĩa/biến thể cần xem xét | Ghi chú xác minh |
|---|---|---|---|---|---|
| Dầu ăn | Gia vị cơ bản / dầu | Cá basa; rau muống; đậu hũ chay; trứng kho nước mắm | ml; có thể lưu muỗng canh như đơn vị nguồn | Dầu thực vật (phải giới hạn loại dầu) | Không đồng nghĩa dầu hào; nguồn rau muống còn có dầu hào riêng |
| Muối | Gia vị cơ bản | Rau muống; đậu hũ chay; sơ chế canh | g; nhúm/muỗng cà phê nếu giữ nguyên đơn vị nguồn | Muối ăn | Không gộp Bột canh |
| Đường | Gia vị cơ bản | Cá kho; rau muống (nhóm gia vị); các nguồn khác | g; muỗng cà phê/canh | Đường cát chỉ khi nguồn xác nhận loại | Không tự thêm vào từng công thức chỉ vì thường gặp |
| Tiêu | Gia vị khô | Cá kho; canh gà; tofu garnish; trứng kho | g; muỗng cà phê | Tiêu xay/hạt tiêu là alias hoặc form cần duyệt | Không có ID hiện tại; tách khỏi Ớt ID 23 |
| Hạt nêm | Gia vị phối trộn | Cá kho; canh; rau muống | g, muỗng cà phê hoặc lượng gói | Bột nêm (chờ xác minh) | Không chứng nhận Chay nếu chưa kiểm tra thành phần sản phẩm |
| Hạt nêm chay | Gia vị phối trộn chay | Phiên bản nguồn đậu hũ sốt cà chua chay | g, muỗng cà phê | Không alias sang Hạt nêm thường | Tên nhãn “chay” không thay thế kiểm tra bằng chứng thành phần |
| Bột ngọt | Gia vị | Rau muống; đậu hũ chay; trứng kho | g, muỗng cà phê | Mì chính (alias cần duyệt) | Khác hạt nêm |
| Bột canh | Gia vị phối trộn | Canh gà nấm hương | g, muỗng cà phê | Không gộp Muối | Nguồn không ghi lượng; ingredient ID riêng nếu được duyệt |
| Dầu hào | Nước sốt/gia vị | Rau muống xào tỏi nguồn | ml, muỗng canh | Oyster sauce | Thành phần hàu/động vật thông thường; cấm dùng nhãn Chay cho công thức này |
| Nước màu kho cá | Gia vị/sốt nấu kho | Cá basa kho gừng nguồn | ml, muỗng canh | Nước màu/nước hàng chỉ sau khi xác nhận cùng loại | Công thức nguồn có 1 muỗng nhưng không rõ đơn vị canh/cà phê |
| Tương ớt | Nước sốt/gia vị | Trứng kho nước mắm nguồn | g, ml, muỗng cà phê | Chili sauce (alias đa ngôn ngữ nếu cần) | Khác Ớt tươi ID 23 |

### Không tạo thành nguyên liệu catalog trong lượt này

| Tên/nhóm xuất hiện | Cách xử lý đề xuất |
|---|---|
| “Gia vị thông dụng 1 ít” | Là nhóm gộp, không phải một nguyên liệu. Chỉ tách thành từng thành phần khi nguồn xác nhận; không sinh các lượng giả |
| Nước lọc/nước nấu | Có thể là chất lỏng tham gia công thức nhưng thường không cần đưa vào picker User; thống nhất riêng cách lưu thành phần nước và cách tính mua sắm trước khi tạo ID |
| Nước mắm chay, dầu hào chay | Không có trong 5 hồ sơ chọn để nhập. Không tự tạo; nếu nguồn món khác có thì phải identity riêng với sản phẩm thông thường và kiểm chứng nhãn |
| Mắm ruốc | Đã có ID 26. Giữ ở phiên bản Admin `trứng kho` hiện tại; không đồng nhất với Nước mắm ID 24 |

## Admin hiện quản lý được gì và còn thiếu gì

| Thuộc tính | Hiện có | Ghi chú |
|---|---|---|
| Tên nguyên liệu | Có | Chuẩn hóa Unicode NFC, khoảng trắng và kiểm tra trùng tên chuẩn hóa |
| Tạo/sửa trạng thái hoạt động | Có | API thao tác qua FastAPI → TCP → MySQL; dữ liệu User dùng cùng public catalog |
| Số công thức đang dùng / khả năng sửa | Hiển thị theo danh sách Admin | Dùng để cảnh báo trước khi ngừng hoạt động |
| Alias/tên đồng nghĩa | Có một số alias legacy đọc ra, nhưng form Admin không tạo/sửa alias | Không thể giải quyết nhóm “cần xác minh” chỉ bằng cách thêm một tên mới an toàn |
| Nhóm nguyên liệu | Không | Không có trường/API trong form thêm/sửa hiện tại |
| Form/dạng: sống, khô, xay, băm | Không | Schema phần recipe có form cho dòng nguyên liệu, nhưng Admin ingredient CRUD hiện không quản lý forms |
| Đơn vị chuẩn/đơn vị thường dùng | Không | Không gắn unit catalog với identity nguyên liệu qua form Admin |
| Nguồn, bằng chứng, review | Không trên form CRUD thông thường | Không có cách đánh dấu tên/alias được xác minh từ giao diện này |
| Thành phần động vật/nhãn Chay | Không | Không suy diễn từ tên; nhãn Chay phải qua workflow bằng chứng riêng |

Vì vậy, Admin hiện đủ để thêm/sửa tên và trạng thái một identity được xác định rõ, nhưng chưa đủ để nhập toàn bộ bản ghi chuẩn hóa (alias, nhóm, form, đơn vị, bằng chứng). Không tạo các nguyên liệu ứng viên chỉ để lấp chỗ trống công thức trước khi quyết định cách lưu các thuộc tính còn thiếu.

## Ảnh hưởng lên B0/P1 nếu thêm gia vị

`RECOMMEND`/ranking so khớp các ingredient ID được chọn với `required_ids`; `all_ids` dùng để loại món khi người dùng loại trừ một nguyên liệu. B0 đếm số nguyên liệu bắt buộc khớp; P1 tính độ phủ và mức sử dụng đầu vào, đồng thời trả phần bắt buộc còn thiếu. Vì vậy:

- Thêm gia vị **bắt buộc** vào công thức làm thay đổi tập `required_ids`, số thiếu, điểm và có thể đổi thứ tự kết quả. Nguyên liệu User không chọn vẫn ảnh hưởng `missing_ids`/coverage.
- Thêm gia vị **tùy chọn** không làm tăng required coverage, nhưng vẫn nằm trong `all_ids`; nếu người dùng loại trừ gia vị đó, món có thể bị loại.
- Thêm ingredient ID vào danh mục User không tự động thay đổi B0/P1 nếu chưa gắn vào recipe, nhưng mở rộng lựa chọn đầu vào. Mỗi lần thêm cần kiểm tra dataset version/cache và luồng RECOMMEND.
- Không gán gia vị thường gặp thành optional hàng loạt để giữ điểm gợi ý. Requirement phải phản ánh đúng phiên bản công thức đã kiểm chứng.

Không đề xuất sửa thuật toán. Trước khi triển khai, nên so sánh B0/P1 trên fixture TEST_ONLY cho mỗi thay đổi ingredient/recipe và ghi lại tập ID, required/optional cùng kết quả.

## Các quyết định cần duyệt

1. Chấp thuận danh sách ứng viên nhóm C, từ chối, hoặc đánh dấu từng mục `NEEDS_VERIFICATION` để hoàn thiện bằng nguồn sản phẩm/công thức.
2. Chọn tên chuẩn cho “Hành khô/Hành tím” và xác nhận có dùng ID `Hành` 3 hay cần identity khác; không tạo trước khi phân xử.
3. Chọn alias chính thức: `đậu hũ` ↔ `Đậu phụ` 5; `nấm đông cô` ↔ `Nấm hương` 9; `mì chính` ↔ `Bột ngọt` (ứng viên mới). Alias không được ghi nếu còn nhập nhằng về dạng.
4. Quy định các đơn vị được hỗ trợ và đơn vị gốc được lưu; không tự quy đổi muỗng canh/cà phê sang ml/g nếu chưa duyệt quy tắc.
5. Quyết định “Gia vị thông dụng 1 ít” và nước lọc được mô hình hóa ra sao mà không làm bẩn picker User.
6. Giữ tách bản ghi `trứng kho` Mắm ruốc ID 26 với ứng viên `trứng kho nước mắm` ID 24; cần chủ sở hữu chốt có tạo công thức revision khác hay không.

**Trạng thái:** danh sách này là đề xuất để duyệt. Không có nguyên liệu mới nào được tạo hoặc dữ liệu nào bị thay đổi.
