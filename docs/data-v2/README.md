# Kế hoạch dữ liệu Mâm cơm thông minh 2.0 — Giai đoạn 1

**Trạng thái: CHỜ CHỦ PROJECT DUYỆT.** Ngày rà soát: 04/11/2026, Asia/Saigon.

Đây là hồ sơ đánh giá và thiết kế, không phải dataset v2 đã được phê duyệt. Chưa sửa dữ liệu, tạo nhãn công thức, chạy migration hoặc thay đổi thuật toán. Các số lượng bổ sung là mục tiêu thu thập đề xuất, không phải số món đã tìm được hoặc kiểm chứng.

## 1. Hồ sơ bàn giao và cách đọc

| Tài liệu | Nội dung |
|---|---|
| [recipes-review.csv](recipes-review.csv) | Đủ 50 món: hướng dẫn r1, nguyên liệu/định lượng gốc, nhóm cũ, nguồn đang lưu và ghi chú rà soát từng món |
| [ingredients-review.csv](ingredients-review.csv) | Đủ 50 nguyên liệu: tên chuẩn hóa, bí danh, số lần dùng, đơn vị và điểm cần xác minh |
| [relations-review.csv](relations-review.csv) | Đủ 252 quan hệ: lượng/cờ bắt buộc gốc, số/đơn vị đọc từ chuỗi; không phải định lượng đã duyệt |
| [findings-review.csv](findings-review.csv) | 20 món có thành phần được gọi tên trong văn bản nhưng chưa biểu diễn tương ứng trong quan hệ |
| [coverage-review.csv](coverage-review.csv) | Độ phủ nhóm, vùng, chế độ ăn, dịp, khẩu phần và định lượng |
| [coverage-targets.csv](coverage-targets.csv) | 18 ô mục tiêu vùng × chế độ ăn × ba vai trò; chỉ là chỉ tiêu thiết kế |
| [SCHEMA_AND_MIGRATION.md](SCHEMA_AND_MIGRATION.md) | Thiết kế bảng, khóa, vòng đời duyệt và migration bổ sung |
| [VALIDATION_PLAN.md](VALIDATION_PLAN.md) | Kiểm tra đã thực hiện và bộ test dự kiến trước khi phát hành v2 |
| [audit-summary.json](audit-summary.json) | Số liệu máy đọc được, đối chiếu SQL và hash các file nền liên quan |

CSV dùng UTF-8, trường văn bản được đặt trong dấu nháy; có trường hướng dẫn nhiều dòng. Nếu Excel không nhận đúng tiếng Việt, nhập qua Data → From Text/CSV và chọn UTF-8. Không đếm số dòng vật lý để tính số bản ghi.

### Ba mức dữ liệu phải tách biệt

1. **ĐANG CÓ:** hàng thực tế trong MySQL và SQL gốc; được giữ nguyên trong các bảng rà soát.
2. **ĐÃ ĐỐI CHIẾU:** cấu trúc, khóa, nội dung khớp nguồn nội bộ; mapping vai trò cũ đã được duyệt trong phạm vi meal-plan-v1. Việc khớp seed không chứng minh công thức chuẩn về ẩm thực, khẩu phần hoặc vùng miền.
3. **CHƯA XÁC MINH / CẦN BỔ SUNG:** vùng, chế độ ăn, dịp, khẩu phần, thành phần chế phẩm, định lượng để tính theo người và các sửa đổi công thức. Chỉ được đưa vào v2 sau khi có bằng chứng và quyết định duyệt.

`UNKNOWN` không có nghĩa là “không thuộc vùng/chế độ/dịp đó”. `OBSERVED_GAP_PENDING_REVIEW` chỉ xác nhận khoảng trống giữa văn bản và quan hệ, chưa xác định lượng, nguyên liệu thay thế hoặc cờ bắt buộc.

## 2. Phạm vi và phương pháp kiểm tra

- Truy vấn đủ năm bảng hiện có bằng một transaction MySQL nhất quán, chỉ đọc; rollback và đóng kết nối sau khi lấy dữ liệu. Không gọi TCP để tránh ghi log runtime; không chạy script audit cũ vốn xuất vào statics/results.
- Đối chiếu đủ ID, tên, hướng dẫn, phút, source_url, source_note, nguyên liệu, quan hệ và bí danh với `mysql_seed.sql`, `mysql_expanded_seed.sql` và bản cập nhật hướng dẫn `mysql_recipe_instructions_update.sql`.
- Với ID 1–10, dùng hướng dẫn sau cập nhật r1, không dùng hướng dẫn ngắn trong seed ban đầu để kết luận.
- Đối chiếu đủ 50 ID/tên với `data/recipe_categories.json`; đọc từng hướng dẫn cùng toàn bộ quan hệ và ghi nhận tại recipes-review.csv.
- Kiểm tra khóa ngoại, trùng cặp quan hệ, cờ bắt buộc, lượng rỗng, số/đơn vị trong chuỗi, nguyên liệu chưa được dùng và độ phủ metadata.
- Không xác minh trực tuyến các nguồn công thức trong lượt này. Các nhận xét ẩm thực cần nguồn mới được ghi là yêu cầu rà soát, không phải kết luận đã duyệt.
- Không chạy benchmark, seed, migration hoặc bộ pytest; đây là rà soát dữ liệu chỉ đọc và kiểm tra tính nhất quán của hồ sơ bàn giao.

## 3. Kết quả nền dữ liệu

| Hạng mục | Kết quả |
|---|---:|
| Dataset MySQL | vi-v2-50-recipes-r1 |
| Công thức / nguyên liệu / quan hệ | 50 / 50 / 252 |
| Bí danh nguyên liệu | 12 |
| Quan hệ bắt buộc / tùy chọn | 151 / 101 |
| Công thức có đủ ba bước được đánh số | 50 |
| Định lượng rỗng | 0 |
| Chuỗi lượng có số dương và đơn vị đọc được | 252 |
| Dòng dùng g / ml | 82 / 3 |
| Dòng dùng đơn vị khác | 167 |
| Công thức có khẩu phần gốc | 0 |
| Quan hệ có định lượng cấu trúc đã duyệt | 0 |
| URL nguồn đang lưu / URL NULL | 40 / 10 |

Toàn bộ dữ liệu đối chiếu khớp SQL tương ứng. Không phát hiện ID thiếu, khóa ngoại hỏng hoặc cặp quan hệ trùng. Các kết quả này không xóa bỏ các bất nhất nội dung bên dưới.

40 URL đều trỏ tới cùng một trang giới thiệu ẩm thực của Vietnam Tourism; source_note ghi biên soạn/tham khảo văn hóa. Chúng chưa là bằng chứng riêng cho thành phần, gram, khẩu phần, vùng hoặc dịp của từng món. 10 URL NULL vẫn có source_note tự biên soạn; không diễn giải là hoàn toàn không có thông tin xuất xứ. Chưa có nguồn công thức cụ thể nào được xác minh cho v2 trong lần rà soát này.

### Độ phủ nhóm và thời gian hiện có

| Nhóm mapping cũ | Tổng | ≤30 phút theo trường minutes | ≤45 phút |
|---|---:|---:|---:|
| main | 23 | 12 | 19 |
| vegetable | 4 | 4 | 4 |
| soup | 6 | 2 | 4 |
| starch | 15 | 2 | 5 |
| other | 2 | 0 | 2 |

Đây là thời gian đang lưu, chưa phải đo nấu thực tế hoặc thời gian tăng theo số người. Mâm ba món hiện có tối đa 552 tổ hợp trước lọc; không lấy 552 làm số mâm đạt mọi bộ lọc.

Mapping cũ khớp toàn bộ ID/tên, chưa tìm thấy bằng chứng để kết luận một nhãn vai trò đã duyệt là sai. Có **hạn chế về mô hình** cần xử lý: `main` không có nghĩa “ăn mặn”; `starch` đang gộp món hoàn chỉnh như phở/bún/cơm, không thể coi toàn bộ là tinh bột ăn kèm. Món có nhiều thành phần không được đếm vào hai vị trí trên cùng một mâm.

### Độ phủ vùng, chế độ ăn và dịp

| Chiều lọc | Lựa chọn cần hỗ trợ | Nhãn đã xác minh hiện tại | Trạng thái 50 món |
|---|---|---:|---|
| Vùng | Bắc, Trung, Nam | 0 | Chưa có metadata |
| Chế độ ăn | Chay, mặn với quy tắc được duyệt | 0 | Chưa được xác minh |
| Dịp | Hằng ngày, cuối tuần, đãi khách, sinh nhật, Tết, cúng gia tiên | 0 | Chưa có metadata/mẫu mâm |
| Khẩu phần | Cơ sở tính cho người lớn/trẻ em | 0 | Chưa có khẩu phần gốc |

Các con số 0 là **số nhãn/khẩu phần đủ bằng chứng đang có trong hệ thống**, không phải khẳng định 50 món không phù hợp với bất kỳ lựa chọn nào. Một món có thể thuộc nhiều vùng hoặc nhiều dịp sau khi được xác minh; các số đếm không cộng như nhóm độc quyền.

## 4. Các vấn đề cần xử lý trước khi đưa vào v2

Chi tiết từng món nằm trong recipes-review.csv; bảng findings-review.csv giữ dấu vết văn bản cho 20 món có khoảng trống thành phần. Đây là rà soát nội bộ, chưa chứng nhận công thức nào đầy đủ để phát hành v2.

| Vấn đề | Ví dụ/ID | Kết luận trong lượt này |
|---|---|---|
| Thành phần được gọi tên nhưng thiếu biểu diễn trong quan hệ | 1, 2, 5, 7, 8, 11, 12, 16, 17, 20, 22, 23, 24, 25, 26, 28, 37, 39, 44, 46 | Xác nhận khoảng trống văn bản–quan hệ; chưa tự thêm dữ liệu |
| Phần cơm chưa được biểu diễn | 22–25 | Không tự chọn Gạo tẻ, cơm chín hoặc lượng thay thế |
| Quan hệ có Bún trong món tên/hướng dẫn cơm | 24, 25 | Bất nhất nội bộ; cần revision có nguồn |
| Có Trứng 200 g nhưng hướng dẫn không dùng trứng | 2 | Cần xác minh; gram cho trứng không tự nó là sai và chưa được phép xóa quan hệ |
| Dạng nguyên liệu chưa khớp rõ quy trình | 16 dùng Thịt heo xay nhưng hướng dẫn luộc/thái mỏng; 27, 37 cần kiểm tra dạng thịt | Không tự thay bằng một phần thịt khác |
| Cờ tùy chọn chưa được giải thích trong các bước | Hành ở 3; cà rốt ở 10; ớt ở 34; me ở 39 và nhiều trường hợp khác | Cần duyệt ý nghĩa required/optional hoặc viết biến thể, không tự đảo cờ |
| Tên dễ gây suy luận chay sai | 32, 44, 45, 47 có Nước mắm bắt buộc | Chặn suy luận nhãn chay từ tên; chưa cấp chứng nhận chế độ ăn |
| Thành phần hỗn hợp/khái quát | Thịt, Rau thơm, Sa tế, Mắm ruốc, Giò sống, nước dùng/nước chấm | Cần thành phần, dạng và nguồn cụ thể |
| Đơn vị phụ thuộc kích thước | Miếng, muỗng, phần, củ, nhánh… | Không suy gram/ml hoặc số người từ tên đơn vị |

Ví dụ không được làm: thêm một lượng đường vào món 39; đổi nước mắm thành nước tương ở món 32; gán nhãn miền Trung vì tên có Huế; gán 2 khẩu phần cho món chỉ vì có 2 phần bún. Tất cả cần nguồn và quyết định riêng.

Nước nấu, dầu, gia vị “nêm vừa ăn” cũng cần chính sách biểu diễn. Chỉ những thành phần được nêu rõ mới được ghi nhận như khoảng trống quan sát; không tự suy mọi món chiên/xào đều thiếu cùng một lượng dầu hoặc muối. Một số món không có bất nhất gọi tên rõ ràng vẫn chưa thể xác nhận đủ thành phần.

Ba nguyên liệu chưa được dùng là ID 29 Giò sống, 32 Đậu xanh, 33 Gạo tẻ. Đây không phải lỗi khóa ngoại và không phải lý do xóa hoặc tự gắn chúng vào món.

## 5. Quy tắc dữ liệu v2 cần thống nhất

- **Vai trò:** tách món chính, rau ăn kèm, canh, tinh bột ăn kèm, món hoàn chỉnh, khai vị/món khác. Một revision có thể được duyệt cho nhiều vai trò, nhưng khi ghép mâm mỗi món chỉ chiếm một vị trí. Không tự chuyển 15 món starch sang một vai trò mới.
- **Vùng:** quan hệ nhiều–nhiều; lưu ý nghĩa nhãn “phù hợp mâm miền…” hay “xuất xứ”, không dùng hai khái niệm thay nhau. Mỗi khẳng định cần bằng chứng và người duyệt. Chưa rõ thì không có khẳng định đã duyệt.
- **Chế độ ăn:** trước hết duyệt profile chay cụ thể: thuần thực vật, cho phép trứng/sữa hay quy tắc khác; yêu cầu kiêng hành/tỏi nếu có phải là profile riêng. “Mặn” cũng cần định nghĩa, không lấy phủ định của một profile chay hoặc lấy nhãn main. Kiểm tra toàn bộ thành phần/chế phẩm và lựa chọn tùy chọn đang bật.
- **Dịp:** một món có thể dùng nhiều dịp. Mẫu mâm xác định số món/vai trò và phạm vi áp dụng; “cúng gia tiên”/Tết cần ghi vùng/phong tục/ngữ cảnh, không khẳng định phù hợp mọi gia đình.
- **Khẩu phần:** lượng công thức phải gắn với khẩu phần gốc, dạng nguyên liệu và nguồn. Không mặc định trẻ em bằng nửa người lớn; quy tắc quy đổi riêng chỉ được dùng khi đã duyệt/được người dùng xác nhận và không mang ý nghĩa tư vấn dinh dưỡng.
- **Định lượng:** giữ cả văn bản gốc lẫn cấu trúc. Số đọc được từ chuỗi chỉ là draft; đơn vị đếm là hợp lệ nếu định nghĩa rõ. Chỉ cần quy đổi gram khi tính năng thực sự cần, không bắt ép mọi củ/quả sang gram thiếu căn cứ.
- **Phê duyệt:** draft → submitted → approved/rejected → superseded; approved không được sửa tại chỗ. Sửa nội dung tạo revision mới. Không để cùng lượt nhập tự cấp trạng thái approved cho tất cả nhãn.

Khi món có tùy chọn không tương thích profile ăn, chỉ có thể dùng biến thể được duyệt và đã xác định rõ phần bị bỏ/thay. Không tự bỏ nguyên liệu ở runtime để biến công thức thành chay.

## 6. Mục tiêu mở rộng và số lượng dự kiến

Ưu tiên tăng độ phủ **rau/canh và giao bộ lọc**, thay vì chỉ tăng tổng số món. Những con số sau là đề nghị phân bổ công việc, chưa phải danh sách món mới hoặc cam kết mọi bộ lọc đều ra mâm.

### Mốc thí điểm

Chọn và xác minh tối thiểu 12 revision: 4 chính, 4 rau, 4 canh để thử toàn bộ quy trình nguồn → định lượng → duyệt → ghép mâm. Có thể dùng revision được rà soát từ 50 món hoặc công thức mới có nguồn. Mốc này không tuyên bố đã phủ đủ ba miền/chay/sáu dịp.

### Mốc mở rộng đề xuất: tối đa khoảng 60 công thức mới

| Nhóm ưu tiên | Chỉ tiêu công thức mới dự kiến | Phân bổ nghiên cứu, chưa gán nhãn |
|---|---:|---|
| Chính | 18 | 3 vùng × 2 profile ăn × 3 công thức/ô |
| Rau ăn kèm | 18 | Cùng cơ cấu, ưu tiên khắc phục pool rau hiện chỉ có 4 |
| Canh | 18 | Cùng cơ cấu, ưu tiên cả phương án nhanh và profile chay đã duyệt |
| Tinh bột ăn kèm | 6 | Công thức có khẩu phần rõ, tách khỏi món hoàn chỉnh |
| **Tổng dự trù** | **60** | Tối đa khoảng 110 danh tính món nếu cả 60 là món mới khác nhau |

Đây là ngân sách thu thập sơ bộ. Nếu món hiện có được xác minh và lấp ô, số cần bổ sung giảm; nếu một công thức mới có nhiều nhãn có căn cứ thì không đếm thành nhiều món mới. Ngược lại, bổ sung 60 món nhưng không đủ từng ô thì chưa đạt độ phủ. Không lấy số revision sửa lỗi làm số món mới.

Mục tiêu cốt lõi là **≥3 ứng viên đã duyệt cho mỗi ô vùng × profile ăn × vai trò chính/rau/canh**: 18 ô. Ba ứng viên cho phép chọn 1–2 món trong nhóm và còn cơ hội đổi một món trước các lọc bổ sung; nếu cho chọn k món và cần phương án đổi, mục tiêu phải là ít nhất k+1 ứng viên tương thích. Không bảo đảm khi thêm loại trừ/thời gian/ngân sách.

Đề nghị mỗi ô có ít nhất một công thức ≤30 phút theo thời gian đã xác minh; đây là chỉ tiêu tìm nguồn, không được sửa trường minutes để đạt. Dữ liệu hiện chỉ có hai canh ≤30 phút trước các bộ lọc khác.

### Dịp và mẫu mâm

- Phát hành lần lượt: hằng ngày/cuối tuần → đãi khách/sinh nhật → Tết/cúng gia tiên.
- Mốc đầu đề nghị 4 mẫu chung cho bốn dịp đầu, không gán tính truyền thống vùng nếu chưa có chứng cứ.
- Với Tết và cúng gia tiên, dự trù 12 mẫu: 2 dịp × 3 miền × 2 profile ăn đã thống nhất; chỉ công bố những mẫu thực sự đủ bằng chứng.
- Mục tiêu cuối kiểm tra 6 dịp × 3 miền × 2 profile = 36 tình huống. Một bộ mẫu có thể tái sử dụng cấu trúc, nhưng phạm vi áp dụng và ứng viên vẫn phải được duyệt.
- Cần đo từng giao dịp × vùng × profile × vai trò; số 60 món không tự chứng minh đủ 36 tình huống. Không nhân cơ học thành 324 món, và không gán hàng loạt tất cả dịp để đủ chỉ tiêu.

Chưa đề xuất số nguyên liệu mới cố định. Mỗi công thức được duyệt sẽ cho biết thiếu danh tính nguyên liệu nào; tạo ID v2 mới sau rà soát trùng, dạng chế phẩm và đơn vị. Đặc biệt không tự tạo dòng dầu, đường, tiêu, đậu phộng hay cơm trong giai đoạn này.

## 7. Điều kiện mở tính năng dựa trên dữ liệu

Một công thức chỉ tham gia tính năng có đủ dữ liệu tương ứng:

| Tính năng | Điều kiện bắt buộc |
|---|---|
| Tìm kiếm/nguyên liệu v2 | Revision đã duyệt, danh tính nguyên liệu và nội dung nhất quán |
| Ghim/đổi và cấu trúc nhóm | Vai trò được duyệt; đủ ứng viên theo nhóm và bộ lọc |
| Miền/chay/dịp | Khẳng định đúng chiều lọc được duyệt trên revision đang phát hành |
| Nhân khẩu phần | Khẩu phần cơ sở và các lượng cần nhân đã duyệt; chính sách định lượng không tuyến tính |
| Đi chợ cộng định lượng | Đơn vị/dạng tương thích; các mục chưa quy đổi phải được hiển thị riêng |
| Tính lượng cần mua | Có thêm lượng tồn hoặc xác nhận đủ; không lấy checkbox có sẵn làm số lượng |

Không trả con số đầy đủ cho toàn mâm nếu còn thành phần bắt buộc chưa định lượng. Có thể cho xem công thức với nhãn giới hạn, nhưng không đưa vào chế độ tính lượng chính xác đang bắt buộc đầy đủ.

Tài khoản/Admin và Thành quả cộng đồng là giai đoạn sau. Schema dự kiến có dấu vết tác giả/người duyệt và liên kết revision để mở rộng; lượt này không tạo tài khoản, bảng bài cộng đồng hoặc quyền xuất bản. Công thức cộng đồng sau này phải đi qua cùng cổng duyệt nếu muốn vào nguồn gợi ý chính thức.

## 8. Trình tự triển khai sau khi duyệt

1. Duyệt thuật ngữ, profile ăn, phạm vi nhãn vùng/dịp và các chỉ tiêu độ phủ trong hồ sơ này.
2. Duyệt schema/migration bổ sung ở SCHEMA_AND_MIGRATION.md; thử trên bản sao, chứng minh không thay dữ liệu cũ.
3. Nhập snapshot 50 món/50 nguyên liệu/252 quan hệ vào vùng draft v2, giữ đầy đủ dấu vết nguồn; không tự duyệt trường thiếu.
4. Rà soát 20 khoảng trống và các quan sát còn lại, thu thập nguồn công thức cụ thể, chọn 12 revision thí điểm.
5. Chạy test và duyệt release thí điểm; mở từng tính năng theo độ đủ dữ liệu.
6. Bổ sung theo khoảng trống các ô, hướng đến dự trù 60 món mới và bộ mẫu dịp.

Giữ FastAPI → TCP Client → TCP Server → MySQL; sau này việc đọc revision, kiểm tra eligibility và tính lượng thuộc TCP Server. Không chuyển nghiệp vụ vào FastAPI. B0/P1 và meal-plan-v1 tiếp tục dùng dữ liệu cũ, không đọc các bảng v2 cho đến khi có thay đổi riêng được phê duyệt.

## 9. Những mục cần chủ project duyệt trước khi triển khai

- Phân biệt vai trò mới và cách xử lý 15 món starch/2 món other.
- Profile chay/mặn cụ thể, có cần kiêng hành/tỏi hay cho phép trứng/sữa không.
- Ý nghĩa nhãn vùng: phù hợp mâm vùng hay xuất xứ; không đánh đồng hai loại bằng chứng.
- Phạm vi mẫu Tết/cúng gia tiên và người đủ thẩm quyền duyệt nội dung.
- Mốc 12 revision thí điểm, dự trù khoảng 60 món mới và tiêu chuẩn ≥3 ứng viên/ô.
- Chính sách nguồn, quyền sử dụng nội dung và người duyệt; ngân sách thời gian cho việc xác minh khẩu phần.
- Schema mở rộng riêng, release có phiên bản và cơ chế không phát hành dữ liệu chưa đủ.

Chưa tạo file SQL migration thực thi; chưa sửa seed, dataset, mapping, B0/P1, meal-plan-v1, báo cáo Word, tag v1.0-report hoặc log thực nghiệm. Các file trong thư mục này là tài liệu và bảng rà soát mới, không phải số liệu thực nghiệm thay thế bản đã nộp.

### Kiểm tra hồ sơ trước bàn giao

19/19 kiểm tra nhất quán hồ sơ đạt: số bản ghi 50/50/252, 20 bản ghi khoảng trống, 18 ô mục tiêu, tính duy nhất, số đếm nhóm/đơn vị/required, alias, ghi chú từng món, trạng thái chưa xác minh, liên kết nội bộ và không có file SQL thực thi. Đã đối chiếu lại các trường dữ liệu gốc trong ba CSV chính với MySQL; metadata và alias cũng giữ nguyên. Đây là kiểm tra hồ sơ, không phải chạy bộ test schema/migration v2.

So sánh SHA-256 trước/sau cho 251 file đang được Git theo dõi và 123 file trong bộ tài liệu báo cáo/lưu trữ cho kết quả không đổi; tag v1.0-report vẫn trỏ tới 4a2afc1041515cdfada9145dbda4b5de47dd140a. Baseline được lấy trên trạng thái làm việc hiện có, bao gồm các thay đổi từ trước lượt này; không reset chúng về HEAD. Chưa stage, commit hoặc push.
