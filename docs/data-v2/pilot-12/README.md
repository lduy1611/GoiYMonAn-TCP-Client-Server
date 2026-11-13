# Hồ sơ thí điểm 12 công thức — revision dữ liệu v2

**Trạng thái: PREPARATION_ONLY — CHỜ DUYỆT DANH SÁCH VÀ QUY TRÌNH KIỂM CHỨNG.** Bắt đầu lập: 04/11/2026; hoàn thiện: 05/11/2026, Asia/Saigon.

Đã lựa chọn 12 công thức hiện có theo kế hoạch [dữ liệu v2](../README.md): 4 món chính, 4 rau, 4 canh **theo mapping v1**. Đây là danh sách ứng viên chuẩn bị revision, không phải 12 revision đã tồn tại trong database hoặc đã được phê duyệt. Không ghi MySQL, chạy migration, tạo 60 món mới, sửa source/seed/dataset/thuật toán hoặc thay tài liệu giai đoạn trước.

## 1. Hồ sơ để duyệt

| File | Phạm vi |
|---|---|
| [pilot-recipes.csv](pilot-recipes.csv) | Bảng 12 món: lý do chọn, hướng dẫn/nguyên liệu gốc, trường cần kiểm chứng và trạng thái |
| [pilot-ingredient-lines.csv](pilot-ingredient-lines.csv) | 51 dòng quan hệ gốc: đối chiếu bước nấu, cờ tùy chọn và các trường định lượng v2 còn trống |
| [instruction-gaps.csv](instruction-gaps.csv) | Hai khoảng trống thành phần gọi tên rõ ràng: dầu ở món 5 và rau thơm ở món 28; không phải dòng nguyên liệu mới |
| [source-register.csv](source-register.csv) | 12 trang tham khảo ứng viên, gồm trạng thái truy cập, phần đã quan sát và khác biệt với legacy |
| [verification-tasks.csv](verification-tasks.csv) | 96 việc cần kiểm chứng: 8 nhóm trường × 12 món; chưa có người duyệt/giá trị được duyệt |
| [SOURCES_AND_REVIEW.md](SOURCES_AND_REVIEW.md) | Nguồn/bằng chứng, giới hạn sử dụng và quy trình duyệt |
| [CALCULATION_CHECKS.md](CALCULATION_CHECKS.md) | Kế hoạch kiểm tra khẩu phần, lượng cần dùng, lượng mua và trường hợp chưa đủ dữ liệu |
| [manifest.json](manifest.json) | Tập ID, số lượng, hash file đầu vào và trạng thái chỉ chuẩn bị hồ sơ |

CSV dùng UTF-8, có trường nhiều dòng đặt trong dấu nháy. Đếm bằng trình đọc CSV; không đếm dòng vật lý. Trường số/nhãn v2 để trống có nghĩa **chưa biết**, không phải 0 hoặc danh sách rỗng đã được xác nhận. Trạng thái bắt buộc cho thông tin chưa đủ căn cứ là `NEEDS_VERIFICATION`.

## 2. Nguyên tắc và danh sách lựa chọn

- Ưu tiên công thức có thành phần gọi tên khớp rõ với các bước; tránh phần cơm/sợi và dạng thịt đang bất nhất lớn ở ID 2, 16, 20–25, 27, 37 trong lô đầu.
- Chọn được các kiểu lượng khác nhau và nguyên liệu dùng chung để thử nghiệp vụ: gram, ml, quả/củ, miếng, nhánh/tép, cây và muỗng.
- Giữ đủ ba vai trò mà meal-plan-v1 đang hỗ trợ; không gán lại vai trò v2 tại bước chuẩn bị.
- Tìm nguồn bài công thức trực tiếp của đơn vị/người đăng để ưu tiên kiểm chứng, nhưng không coi cùng tên là cùng công thức.
- Có một số ca còn lỗi được giữ lại để kiểm tra cổng chặn dữ liệu: hai khoảng trống thành phần và trường hợp tên món dễ dẫn tới suy luận chay sai.
- Nhóm rau hiện chỉ có 4 món. Muốn giữ 4 rau từ dữ liệu hiện có thì phải chọn cả bốn; không thể cam kết cả bốn đều ít vấn đề hoặc đã có nguồn đầy đủ. Đây là lựa chọn có ràng buộc, không phải khẳng định 12 món có nguồn tốt nhất trong mọi công thức ngoài project.

| ID gốc | Công thức | Nhóm dùng chọn mẫu | Lý do chọn từng món | Nguồn ứng viên |
|---|---|---|---|---|
| 4 | Đậu phụ sốt cà chua | Chính (mapping cũ) | Ba quan hệ, ba bước dễ đối chiếu; kiểm tra đơn vị miếng/quả và gia vị nêm chưa định danh mà không phải xử lý món cơm/sợi bị lệch. | EXT-04 |
| 33 | Gà kho gừng | Chính (mapping cũ) | Các thành phần được gọi tên chính đều có quan hệ; gà có lượng gram, gừng/hành/nước mắm giúp thử đơn vị khác nhau và nguyên liệu dùng chung. | EXT-33 |
| 36 | Bò xào rau muống | Chính (mapping cũ) | Bốn quan hệ, rau và thịt có gram; dùng chung rau muống với món 5 để kiểm tra cộng lượng và một món chỉ chiếm một vai trò. | EXT-36 |
| 42 | Tôm hấp nước dừa | Chính (mapping cũ) | Bốn quan hệ, quy trình ngắn; có cả gram và ml, thích hợp kiểm tra lượng mua so với nguyên liệu dùng làm môi trường hấp. | EXT-42 |
| 5 | Rau muống xào tỏi | Rau (mapping cũ) | Hai quan hệ chính, quy trình ngắn; rau dùng chung với món 36. Là một trong bốn món rau hiện có và là ca nhận diện thành phần nêu trong hướng dẫn nhưng thiếu quan hệ. | EXT-05 |
| 9 | Khoai tây xào cà rốt | Rau (mapping cũ) | Ba thành phần chính được gọi tên đều có quan hệ; thử đơn vị củ, nước nấu và vai trò rau ăn kèm đã được duyệt ở v1. | EXT-09 |
| 45 | Nấm xào sả | Rau (mapping cũ) | Giữ đủ bốn món rau của catalog; kiểm tra chế phẩm nước mắm và việc tên nấm không đủ để kết luận chay. | EXT-45 |
| 47 | Nộm dưa leo cà rốt | Rau (mapping cũ) | Món trộn khác nhóm xào, có nhiều dòng tùy chọn; thử nước trộn, lượng mua và đối chiếu thành phần chưa nêu rõ trong bước. | EXT-47 |
| 29 | Canh bí đỏ hầm xương | Canh (mapping cũ) | Hai thành phần chính có gram, danh tính rõ; ưu tiên kiểm tra khẩu phần/đơn vị sau khi chốt cùng một phiên bản công thức. | EXT-29 |
| 30 | Canh rau ngót thịt bằm | Canh (mapping cũ) | Bốn quan hệ, thịt và rau có gram; quy trình ngắn, thuận lợi đối chiếu nguyên liệu có tên và kiểm tra lượng nước canh. | EXT-30 |
| 32 | Canh nấm rơm đậu phụ | Canh (mapping cũ) | Nấm/đậu phụ có cả gram và miếng, dùng chung đậu phụ với món 4; là ca chặn gán nhãn chay theo tên và đọc nhầm phần trong bài nhiều công thức. | EXT-32 |
| 28 | Canh chua cá | Canh (mapping cũ) | Đại diện món canh có cá; đủ dữ liệu để rà soát lỗi thiếu rau thơm, dạng me và nguồn tham khảo dùng loài cá khác. | EXT-28 |

Có thể ưu tiên rà soát nội dung đơn giản trước: 33, 36, 42, 9, 29, 30. Các món 4, 32, 45, 47 tăng độ phủ đơn vị, tùy chọn và kiểm tra nhãn ăn; 5 và 28 kiểm tra cách xử lý khoảng trống thành phần. Thứ tự này không thay thế ưu tiên nguồn: món có nguồn chưa truy cập đủ vẫn chờ xác minh.

### Mức độ sẵn sàng thực tế

| Hạng mục | Hiện có trong hồ sơ |
|---|---:|
| Công thức gốc đã chọn | 12 |
| Chính / rau / canh theo mapping cũ | 4 / 4 / 4 |
| Quan hệ gốc / nguyên liệu gốc khác nhau | 51 / 26 |
| Dòng bắt buộc / tùy chọn gốc | 34 / 17 |
| Dòng ghi g / ml | 14 / 1 |
| Dòng dùng đơn vị khác | 36 |
| Nguồn ngoài đã đọc trực tiếp phần liên quan | 8 |
| Nguồn mới đọc qua kết quả tìm kiếm, mở trang chưa thành công | 4 |
| Nguồn được duyệt để áp dụng cho revision hiện tại | 0 |
| Khẩu phần gốc được duyệt / dòng lượng v2 được duyệt | 0 / 0 |
| Nhãn vùng/chế độ ăn/dịp mới được gán | 0 |

Đây là phép đếm hồ sơ, không phải kết quả chạy thuật toán hay đo nấu. Không tính toán khẩu phần hoặc danh sách mua đầy đủ cho bộ pilot vào lúc này.

## 3. Đối chiếu hướng dẫn với danh sách nguyên liệu

Bảng pilot-ingredient-lines.csv giữ nguyên tên, lượng chuỗi, ID và cờ required/optional của 51 quan hệ. Mỗi dòng có tham chiếu bước và quan sát riêng. Quan sát được dùng là tên/danh mục trong văn bản, không phải chứng nhận đủ công thức.

| Nhóm phát hiện | Các món/điểm cần duyệt |
|---|---|
| Thành phần được gọi tên nhưng thiếu quan hệ | ID 5 nêu dầu; ID 28 nêu rau thơm. Chưa biết loại, lượng và cờ bắt buộc nên không thêm dòng mới |
| Quan hệ có nhưng chưa gọi riêng trong bước | Chanh ở 28; nấm hương ở 32 chỉ có từ nấm chung; cà chua/hành ở 47 |
| Tùy chọn nhưng các bước đang dùng | Tỏi ở 4/36; cà chua ở 28; gừng/nước mắm ở 29; hành ở 30/33; gừng ở 32; tỏi/ớt ở 45; ớt ở 47 |
| Gia vị chưa định danh | Nêm ở 4, 5, 9 chưa đủ căn cứ để lập danh sách thành phần đầy đủ |
| Nước và purpose chưa được chốt | Nước nấu/kho ở nhóm canh, 9/33; nước dừa dùng môi trường hấp ở 42 |
| Tên món không quyết định chế độ ăn | 32, 45, 47 có nước mắm bắt buộc theo dữ liệu gốc; không gán chay vì tên thực vật |
| Vai trò hỗn hợp | 36 có cả bò và rau nhưng mapping cũ chỉ là main; không đếm món này làm hai món của một mâm |

Không đổi optional thành required chỉ vì bước nấu có dùng; cần nguồn/biến thể mô tả cách bỏ thành phần. Không suy mỗi món áp chảo đều thiếu một lượng dầu giống nhau. Với nấm/cá trong văn bản gọi chung, phải xác minh loại theo đúng công thức thay vì coi đối chiếu tên là đủ.

## 4. Các trường cần xác minh cho cả 12 ứng viên

| Trường | Dữ liệu đang có | Bổ sung cần có trước khi dùng tính năng |
|---|---|---|
| Nội dung và thành phần | Ba bước r1 và các quan hệ gốc | Bộ thành phần đầy đủ cùng hướng dẫn, biến thể tùy chọn và giải quyết khoảng trống |
| Khẩu phần gốc | Chưa có | Số phần cơ sở, serving_basis, lượng ăn kèm/cấp mâm và bằng chứng cùng revision |
| Định lượng cấu trúc | Chuỗi lượng gốc, số/đơn vị đọc từ chuỗi | Amount/unit/form/gross-edible-prepared/purpose, cơ sở cân/đong, nguồn và người duyệt |
| Vai trò | Mapping v1 đã duyệt trong phạm vi cũ | Xác nhận vai trò v2, món ăn kèm hay món hoàn chỉnh, quy tắc không đếm đôi |
| Vùng miền | Chưa có metadata được duyệt | Phân biệt xuất xứ và phù hợp mâm miền; khẳng định có nguồn trên đúng revision |
| Chế độ ăn | Chưa có profile/assertion được duyệt | Quy tắc chay/mặn cấp món/cấp mâm, thành phần chế phẩm và cấu hình tùy chọn |
| Dịp | Chưa có | Ngữ cảnh và mẫu mâm đã duyệt; không suy mọi món cơm nhà hợp Tết/cúng |
| Thời gian | Minutes legacy | Thời gian/cơ sở đo cùng khẩu phần, không thay số phút theo nguồn khác công thức |

Tất cả nhóm trên vẫn là `NEEDS_VERIFICATION` trong bảng pilot. Giá trị v2 chưa được điền; không tạo revision ID, reviewer, ngày duyệt hoặc quyết định giả.

Quy tắc cho từng món, chẳng hạn kích thước miếng đậu, gà cân có xương hay phần ăn, đơn vị muỗng của me/nước mắm hoặc tôm có vỏ, được ghi cụ thể trong cột verification_questions và các task tương ứng.

## 5. Nguồn rõ ràng không đồng nghĩa công thức đã sẵn sàng

Các trang được tìm là **nguồn ứng viên mới**, không thay source_url cũ và không chứng minh chúng từng được dùng để viết dataset. Tác giả/đơn vị xuất bản được nhận diện giúp truy vết, nhưng không chứng nhận độ đúng của mọi thành phần/khẩu phần.

- PAGE_INSPECTED: đã đọc phần liên quan qua công cụ web, chưa phải approved; cần đối chiếu lại nếu trang thay đổi.
- SEARCH_RESULT_ONLY_*: chỉ có phần hiển thị ở kết quả tìm kiếm, chưa được dùng làm bằng chứng đầy đủ.
- Ngay cả khi nguồn có số người, trường base_servings của pilot vẫn trống. Giữ số người nguồn trong sổ nguồn để đối chiếu, không chuyển sang revision khác.
- Các khác biệt nguyên liệu/định lượng/cách nấu phải được chủ project quyết định: giữ công thức tự biên soạn và kiểm chứng thực tế, hoặc đề xuất revision/biến thể có nguồn. Không trộn lượng từ nhiều trang thành một công thức.
- Chưa lưu snapshot đầy đủ/hash trang web và chưa duyệt quyền sử dụng nội dung. Hồ sơ chỉ giữ URL, locator và ghi chú ngắn; không sao chép toàn bộ công thức ngoài vào bộ dữ liệu.

Xem [quy trình nguồn và duyệt](SOURCES_AND_REVIEW.md) cho 12 liên kết và trạng thái cụ thể. Chưa có nguồn nào được chấp nhận làm giá trị v2 chính thức.

## 6. Các nhóm còn thiếu trước khi mở rộng

1. **Rau và canh tương thích profile chay có căn cứ:** hiện không có chứng nhận chay trong pilot. Không tự đổi nước mắm hoặc bỏ gia vị để đạt chỉ tiêu.
2. **Độ phủ ba miền và sáu dịp:** không có nhãn đã duyệt cho 12 món; nguồn có cụm tên vùng chỉ nói về phiên bản nguồn, chưa nói về pilot.
3. **Tinh bột ăn kèm và món hoàn chỉnh:** pilot chỉ thử ba vai trò cũ, chưa chọn cơm/phở/bún hay món other. Cần lô riêng có loại sợi/gạo, trạng thái sống/chín và khẩu phần rõ, sau khi giải quyết các bất nhất đã rà soát.
4. **Canh nhanh và phương án thay thế dưới bộ lọc:** theo minutes legacy, chỉ 30/32 trong bốn canh ≤30 phút. Thêm vùng/profile/loại trừ có thể làm pool nhỏ hơn; không xem 4 món/nhóm là luôn đủ ghim/đổi.
5. **Tết/cúng và nhóm khai vị/món đặc thù:** cần mẫu có phạm vi vùng/phong tục và người duyệt phù hợp; pilot này chưa chứng minh đáp ứng.
6. **Cơ sở khẩu phần người lớn/trẻ em:** chưa có base_servings/policy được duyệt. Không mặc định một hệ số trẻ em hoặc suy từ số phần trên trang khác.
7. **Dạng chế phẩm và quy đổi:** muỗng, miếng, củ/quả, nấm tươi/khô, nguyên liệu có vỏ/xương và nước làm môi trường nấu cần đo/nguồn riêng.

Tối đa 4 × 4 × 4 = 64 tổ hợp theo vai trò là số tổ hợp danh tính trước lọc, không phải 64 mâm v2 khả thi/đã kiểm chứng. Mục tiêu mở rộng ≥3 ứng viên mỗi ô vùng × chế độ mâm × vai trò trong kế hoạch gốc chưa được đáp ứng chỉ nhờ chọn 12 món.

Không tự tạo lô 60 công thức mới trong bước này. Dùng kết quả kiểm chứng pilot để biết nguồn nào đủ tốt và ô nào thật sự thiếu, rồi đề xuất lô tiếp theo.

## 7. Trình tự sau khi chủ project duyệt hồ sơ

1. Duyệt danh sách và cách ưu tiên; chỉ định người xác minh thực tế, không tự gán danh tính người duyệt.
2. Hoàn thiện nguồn/cùng phiên bản cho từng ứng viên, nhất là 4 nguồn chưa truy cập đủ.
3. Điền hồ sơ thành phần, lượng, khẩu phần và các claim có căn cứ; giữ trạng thái không biết ở trường còn thiếu.
4. Kiểm chứng nấu/đong nếu nguồn chưa đủ và ghi biên bản cùng revision; không tự đặt kết quả.
5. Duyệt từng claim, không tự duyệt hàng loạt theo món. Chỉ mở phép tính/lọc có đủ điều kiện tương ứng.
6. Khi có tập được duyệt và migration đã được phép riêng, mới chuẩn bị import vào vùng draft v2 và kiểm thử trên database test. Hồ sơ hiện tại không tự cấp quyền nhập/chạy migration.

Có thể nghiệm thu nội dung/khẩu phần của một số món trong khi nhãn vùng/dịp còn chờ; khi đó không được công bố hỗ trợ các bộ lọc chưa đủ dữ liệu. Không cần gán nhãn thiếu căn cứ để hoàn thành một hàng CSV.

Giữ kiến trúc FastAPI → TCP Client → TCP Server → MySQL. Việc tính khẩu phần, kiểm tra điều kiện dữ liệu và lập danh sách mua thuộc TCP Server ở bước triển khai sau; hồ sơ này không thêm nghiệp vụ vào source code.

## 8. Kiểm tra hồ sơ trước bàn giao

27/27 kiểm tra nhất quán hồ sơ đạt: đủ 12 ID hiện có, đúng 4/4/4 theo mapping cũ, giữ nguyên 51 quan hệ và nội dung legacy, 26 nguyên liệu, số đếm 34/17, đối chiếu bước, 12 ref nguồn với phân biệt 8/4 trạng thái truy cập, 96 task, các trường v2 chưa được tự điền/duyệt, hash file đầu vào, liên kết nội bộ và định dạng UTF-8. Đây là kiểm tra tài liệu/CSV, không phải test khẩu phần thực tế hoặc test migration đã chạy.

So sánh SHA-256 trước/sau cho 385 file có sẵn trong phạm vi bảo vệ (file Git đang theo dõi, hồ sơ data-v2 trước đó, tài liệu/báo cáo lưu trữ và file test chưa theo dõi đã có) cho kết quả không đổi. Chỉ tạo 9 file mới trong pilot-12. Tag v1.0-report giữ nguyên; không reset các thay đổi đã có trước lượt này, không stage/commit/push. Không kết nối hoặc ghi MySQL trong lượt chuẩn bị pilot.

