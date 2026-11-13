# Nguồn tham khảo, bằng chứng và quy trình kiểm chứng pilot

**Chỉ là hồ sơ chuẩn bị. Không có quyết định approved hoặc quyền import được tạo trong lượt này.** Danh sách nguồn được tìm/đọc ngày 04/11/2026 theo Asia/Saigon; ngày hoàn thiện hồ sơ: 05/11/2026.

## 1. Phân biệt nguồn gốc nội bộ và nguồn tham khảo mới

### Nguồn nội bộ đã có

- [recipes-review.csv](../recipes-review.csv) giữ hướng dẫn r1, source_url/source_note và lượng nguồn của các ứng viên.
- [relations-review.csv](../relations-review.csv) giữ các cặp recipe_id/ingredient_id và cờ required/optional.
- [recipe_categories.json](../../../data/recipe_categories.json) là mapping vai trò cũ đã duyệt; chỉ dùng làm bằng chứng trong phạm vi v1.
- Các file SQL seed và bản cập nhật hướng dẫn được dẫn bằng tên file/hash trong [manifest](manifest.json). Không chạy lại các file đó.
- [audit-summary.json](../audit-summary.json) ghi kết quả đối chiếu MySQL của giai đoạn 1. Lượt chuẩn bị pilot này chỉ đọc hồ sơ/file, **không mở kết nối MySQL mới**.

Ba ứng viên 4/5/9 có source_url cũ NULL và source_note tự biên soạn. Chín ứng viên còn lại đang trỏ cùng trang giới thiệu văn hóa Vietnam Tourism. Không xóa thông tin đó, không thay bằng URL mới để tạo ấn tượng nguồn ngoài chính là nguồn gốc của legacy.

Hash nội bộ chứng minh bản đọc không thay đổi, không chứng minh độ đúng ẩm thực hoặc quyền sử dụng nội dung ngoài.

### Nguồn tham khảo mới được tìm

| Ref | ID legacy | Đơn vị/người đăng và liên kết gốc | Truy cập qua công cụ | Số phần quan sát ở nguồn, KHÔNG phải pilot |
|---|---|---|---|---|
| EXT-04 | 4 | [Cookpad / Nhà Vân](https://cookpad.com/vn/cong-thuc/24193529) | PAGE_INSPECTED | 2 người |
| EXT-33 | 33 | [Co.op Online](https://cooponline.vn/cong-thuc-nau-an/ga-kho-gung-mon-an-truyen-thong-suoi-am-bua-com-viet-trong-ngay-mua/) | SEARCH_RESULT_ONLY_PAGE_TIMEOUT | NEEDS_VERIFICATION |
| EXT-36 | 36 | [Barona](https://barona.vn/thit-bo-xao-rau-muong) | PAGE_INSPECTED | NEEDS_VERIFICATION |
| EXT-42 | 42 | [VnExpress Cooking / Bùi Thủy](https://vnexpress.net/doi-song-cooking-tom-hap-nuoc-dua-kieu-nam-bo-4878272.html) | PAGE_INSPECTED | 4-6 người |
| EXT-05 | 5 | [VnExpress Cooking / Bùi Thủy](https://vnexpress.net/doi-song-cooking-rau-muong-xao-toi-kieu-nam-bo-4760643.html) | PAGE_INSPECTED | 4-5 người |
| EXT-09 | 9 | [Cookpad / Trần Nguyên](https://cookpad.com/vn/cong-thuc/23877441) | PAGE_INSPECTED | 2 người |
| EXT-45 | 45 | [Cookpad / Nguyen Quy](https://cookpad.com/vn/cong-thuc/13268683) | SEARCH_RESULT_ONLY_PAGE_CACHE_MISS | NEEDS_VERIFICATION |
| EXT-47 | 47 | [Sendo Farm](https://farm.sendo.vn/2022/11/3-buoc-nom-dua-leo-ca-rot-gion-am-vi.html) | SEARCH_RESULT_ONLY_PAGE_HTTP_429 | NEEDS_VERIFICATION |
| EXT-29 | 29 | [Điện máy XANH](https://www.dienmayxanh.com/vao-bep/cach-nau-canh-bi-do-ham-xuong-ngon-ngot-hap-dan-cho-bua-com-10447) | PAGE_INSPECTED | 4 người |
| EXT-30 | 30 | [Co.op Online](https://cooponline.vn/cong-thuc-nau-an/canh-rau-ngot-thit-bam-mon-canh-thanh-mat-de-nau-va-giau-dinh-duong/) | SEARCH_RESULT_ONLY_PAGE_TIMEOUT | NEEDS_VERIFICATION |
| EXT-32 | 32 | [Đào Tạo Bếp Trưởng Á Âu / Nguyễn Tân](https://daotaobeptruong.vn/nam-rom-dau-hu) | PAGE_INSPECTED | NEEDS_VERIFICATION |
| EXT-28 | 28 | [VnExpress Cooking](https://vnexpress.net/canh-chua-ca-nam-bo-4311352.html) | PAGE_INSPECTED | NEEDS_VERIFICATION |

Số phần nêu trong bảng chỉ ghi lại biểu diễn ở trang được đọc. Khoảng không được đổi thành trung bình hoặc số nguyên tùy chọn. Trường trống trong CSV nguồn có nghĩa chưa thấy/chưa kiểm chứng trong phạm vi truy cập, không kết luận trang chắc chắn không có.

PAGE_INSPECTED nghĩa đã đọc phần công thức liên quan; không có nghĩa đã xác minh thực nghiệm, tác giả chứng nhận dataset hoặc chủ project đã duyệt. Nội dung công cụ có thể là bản thu thập của công cụ; cần đọc/capture lại khi phê duyệt chính thức. SEARCH_RESULT_ONLY_* không được nâng thành bằng chứng đầy đủ chỉ dựa snippet.

Các tác giả Cookpad là người đăng công thức, nguồn sơ cấp cho phiên bản họ công bố. Điều đó không tự biến phiên bản đó thành tiêu chuẩn chung hoặc thành công thức hiện tại của project. Tên vùng/nơi ở tài khoản/nhãn tự ghi trên nguồn không được chuyển thẳng sang metadata pilot.

Không dùng các bài sức khỏe, tin sự kiện, thực đơn bán hàng hoặc giá bán món chế biến sẵn để điền khẩu phần, chế độ ăn hay chi phí nguyên liệu cho pilot.

## 2. Khác biệt cần giữ nguyên dấu vết

Chi tiết được ghi một lần theo từng ref trong source-register.csv. Các điểm sau là kết luận **so sánh hai phiên bản**, không phải đề nghị tự vá công thức:

- EXT-04/09: bài cùng tên của người đăng khác vẫn dùng bộ gia vị/thành phần và cách ghi lượng khác legacy. Không lấy số người của bài cho lượng đang lưu.
- EXT-05/42: nguồn mang mô tả vùng riêng, có bộ thành phần/cách làm riêng. Chưa đủ căn cứ gán nhãn vùng hoặc số phần của nguồn cho món gốc.
- EXT-36: cần đối chiếu cả danh sách lẫn từng bước của nguồn; một bài có định lượng không đồng nghĩa mọi gia vị trong bài đã đầy đủ.
- EXT-29: có khẩu phần tại trang nguồn nhưng bộ lượng/thành phần khác; đây là dữ liệu để người duyệt so sánh, không phải base_servings của món 29.
- EXT-28: dùng loài cá và nhóm rau khác. Chưa thể coi tương đương công thức cá basa trong project.
- EXT-32: phải chọn đúng mục canh trong bài nhiều công thức. Mục đó có thịt băm, không lấy một mục khác mang mô tả chay để chứng nhận món 32.
- EXT-33/30/45/47: cần mở và kiểm tra lại trang trước khi ghi bằng chứng định lượng/khẩu phần; lần truy cập hiện tại chưa đủ.

Không trộn danh sách gia vị của nguồn A, lượng của nguồn B và khẩu phần của nguồn C. Nếu cần áp dụng một phiên bản khác, phải có bản diff và đề nghị revision/biến thể riêng.

## 3. Cách lưu nguồn/bằng chứng khi triển khai schema đã duyệt

| Đối tượng | Trường cần lưu | Trạng thái ở hồ sơ hiện tại |
|---|---|---|
| Source | Loại nguồn, URL/document_ref, tiêu đề, publisher/author, ngày nguồn nếu có, ngày truy cập, quyền sử dụng, hash bản chụp | Có URL/locator/ghi chú quan sát; hash trang và quyền sử dụng chưa được xác minh |
| Evidence | Source ID, locator tới đúng mục/đoạn/bảng, claim_scope, ghi chú ngắn, revision dự kiến, hash/phiên bản bản chụp | Chưa tạo assertion có hiệu lực; observations chỉ hỗ trợ chuẩn bị |
| Evidence set | Các evidence hỗ trợ cùng một quyết định | Chưa tạo bộ bằng chứng approved |
| Decision | Reviewer thực, thời điểm, compatible/không/chưa rõ hoặc approve/reject nội dung, rationale | Để trống reviewer/thời điểm, trạng thái NEEDS_VERIFICATION |
| Revision | Liên kết legacy, nội dung đầy đủ, phiếu lượng/khẩu phần, diff và nguồn | Chưa tạo revision DB/ID v2 |
| Release | Revision và phụ thuộc đã chốt, báo cáo coverage/hash | Chưa phát hành |

Ánh xạ dự kiến đúng [schema đã đề xuất](../SCHEMA_AND_MIGRATION.md): sources → v2_sources; evidence → v2_evidence; tập → v2_evidence_sets/members; quyết định → v2_review_decisions/events; nội dung → v2_recipe_revisions/ingredient_lines; các nhãn có quyết định riêng theo revision.

Không lấy candidate_key P01–P12 hay ref EXT-* làm ID MySQL thật. CSV source-register không phải file SQL hoặc lô import được duyệt.

### Phạm vi bằng chứng

- `recipe_content`: thành phần và hướng dẫn đầy đủ của đúng phiên bản.
- `quantity`: amount, đơn vị, dạng, cơ sở cân và purpose của dòng cụ thể.
- `servings`: số phần và serving_basis ứng với toàn bộ lượng của cùng công thức.
- `role`: vai trò trong mâm theo taxonomy đã chốt.
- `region`: xuất xứ hoặc phù hợp mâm miền, phân biệt hai loại.
- `diet`: profile ăn với đầy đủ thành phần/chế phẩm và tùy chọn.
- `occasion`: ngữ cảnh, mẫu mâm và phạm vi phong tục.
- `timing`: thời gian và điều kiện/khẩu phần tương ứng.
- `unit_conversion`: conversion có dimension, ingredient/form nếu cần, không suy từ một ảnh món ăn.

Duyệt quantity không tự duyệt servings/diet/region. Việc đã đọc đúng một trang không thay thế quyết định áp dụng cho một claim.

## 4. Quy trình kiểm chứng từng ứng viên

1. **Khóa bản tham chiếu:** dùng hash của hồ sơ giai đoạn 1 và bản legacy trong pilot. Nếu nội dung đầu vào lệch, dừng để chốt snapshot mới; không sửa ngầm.
2. **Chọn hướng xác minh:** (a) tác giả/chủ project xác nhận công thức tự biên soạn và tổ chức đo/nấu; hoặc (b) đề xuất revision dựa trên nguồn cụ thể, ghi toàn bộ khác biệt. Bước này chưa chọn thay cho người duyệt.
3. **Đọc đầy đủ nguồn:** kiểm tra đúng mục, tác giả/đơn vị, phần lượng, số phần, gia vị ngoài danh sách, thành phần chế phẩm, tùy chọn và ghi nhận hạn chế.
4. **Lập bảng đối chiếu:** cho mỗi thành phần chỉ rõ có trong danh sách/bước nào, dùng/bỏ khi nào, dạng và định lượng từ đâu. Giải quyết hai khoảng trống 5/28 bằng bằng chứng, không bằng tự suy.
5. **Chuẩn hóa có kiểm soát:** giữ raw, điền cấu trúc đề xuất riêng, ghi source/claim. Không tự quy muỗng/miếng thành ml/g hoặc gán một serving mặc định.
6. **Đo/nấu khi cần:** người thực hiện ghi dữ liệu theo phiếu ở mục 5; hồ sơ chưa có kết quả thử hoặc người thực hiện.
7. **Duyệt từng nhóm trường:** nội dung, quantity, servings, role và mỗi nhãn có quyết định riêng; reviewer có thể yêu cầu sửa/reject. Không coi sự đồng ý với thiết kế là phê duyệt các giá trị chưa được kiểm chứng.
8. **Kiểm tra điều kiện tính năng:** chỉ những claim đã đủ mới cho phép dùng vào phép tính/bộ lọc tương ứng. Nội dung có thể được duyệt trong khi region/diet/occasion còn NEEDS_VERIFICATION.
9. **Chuẩn bị lô nhập sau này:** chỉ sau khi dữ liệu và migration được cho phép riêng; không import từ hồ sơ hiện tại.

## 5. Phiếu kiểm chứng thực tế cần thu thập

Chưa tạo các giá trị giả vào phiếu. Khi có người thực hiện, cần ghi:

| Nhóm | Thông tin thực tế cần ghi |
|---|---|
| Danh tính lần kiểm chứng | ID ứng viên, phiên bản/diff dự kiến, người thực hiện, ngày giờ, thiết bị và điều kiện |
| Dạng đầu vào | Loại/cut, tươi/khô, sống/chín, còn vỏ/xương hay phần ăn; nhãn/thành phần chế phẩm |
| Mỗi lần cân/đong | Dụng cụ, đơn vị, số thực đo, phần bỏ đi, lượng thực dùng, lượng thừa, công đoạn dùng |
| Gia vị/medium | Lượng dùng ban đầu, phần còn lại, consumed/cooking_medium/garnish và lý do |
| Thành phẩm | Khối lượng/thể tích thành phẩm và số phần thực chia, cách xác định phần ăn và món đi kèm |
| Tùy chọn | Bật/tắt thành phần nào; cách làm tương ứng; phần khác biệt cần revision riêng |
| Thời gian | Chuẩn bị, nấu, chờ và tổng; không suy nấu song song của cả mâm từ một món |
| Bằng chứng | Tài liệu, ảnh do người kiểm chứng tạo nếu có, locator, hash; quyền dùng và người duyệt |

Nếu nguồn chỉ cho khoảng người ăn, ghi khoảng và hạn chế thay vì chốt một base_servings. Nếu cần chia theo người lớn/trẻ em, policy chuyển đổi và phân bổ giữa nhiều món phải được duyệt riêng; không suy từ một bài có số phần.

## 6. Hồ sơ duyệt và trách nhiệm

Các trường assignee/reviewer/reviewed_at/approved_value/decision_ref đang để trống. Chủ project có thể chỉ định người xác minh và người duyệt; không giả định có tài khoản Admin hoặc tự tạo người dùng để thỏa FK.

Một quyết định phải nêu: ứng viên/revision nào, claim nào, giá trị nào, evidence nào, lý do và thời điểm. Nếu từ chối, giữ nguồn và lý do; nếu thay đổi sau duyệt, tạo revision/quyết định mới, không sửa lịch sử.

Chưa có nguồn/claim nào trong lô này mang trạng thái approved. Toàn bộ 12 ứng viên vẫn không được nhập hoặc phát hành chỉ nhờ hồ sơ chuẩn bị này.

