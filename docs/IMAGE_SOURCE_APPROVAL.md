# B2/B3 — Căn cứ sử dụng ảnh

## Nguồn và phạm vi xác nhận

- Nguồn do chủ project chỉ định: **Ăn Gì? — https://agni.vn/**, sản phẩm của veasy.
- Chủ project đã xác nhận tác giả cho sử dụng ảnh miễn phí. Sau khi được thông báo về điều khoản công khai, chủ project xác nhận **có sự cho phép riêng** cho phạm vi tải ảnh bằng công cụ, lưu và phân phối lại trong repository GitHub của đồ án.
- Nội dung/link của sự cho phép riêng **chưa được cung cấp trong workspace**. Đây là thông tin do chủ project xác nhận, không phải giấy phép mở đã được kiểm chứng độc lập. Cần lưu bổ sung bằng chứng cho phép và điều kiện kèm theo trước khi phát hành bộ ảnh công khai.
- Không gán giấy phép Creative Commons, public domain hoặc giấy phép của mã nguồn cho ảnh của agni.vn.

**Trạng thái kiểm chứng hiện tại:** chưa có ảnh nguồn nào trong bộ 35 ảnh được kiểm chứng độc lập là có quyền phân phối lại trong repository. Cả 35 ảnh, gồm 105 bản WebP đã thu nhỏ, đều **chờ bằng chứng cấp quyền phân phối lại**. Xác nhận dùng giao diện thành công trên điện thoại không bổ sung hay thay thế bằng chứng quyền sử dụng ảnh. Placeholder SVG là tài sản trung tính do project tự tạo, tách khỏi bộ ảnh nguồn này.

## Điều đã kiểm chứng từ website

Đã đọc [Điều khoản sử dụng](https://agni.vn/dieu-khoan) (trang ghi phiên bản 2026-10-13) và [Giới thiệu](https://agni.vn/gioi-thieu):

- Điều khoản ghi nội dung/hình ảnh thuộc Ăn Gì?, yêu cầu hỏi trước khi sử dụng ngoài phạm vi xem/nấu/in/chia sẻ link cá nhân. Điều khoản cũng hạn chế thu thập tự động và sao chép hàng loạt. Vì vậy, việc dùng lại trong project này dựa trên **sự cho phép riêng do chủ project xác nhận**, không dựa vào một tuyên bố cho phép tải ảnh miễn phí trên website.
- Trang giới thiệu xác nhận ảnh món, ảnh bước nấu và video là **AI tạo để minh họa, không phải ảnh chụp món nấu thật**. Alt trên ảnh nguồn cũng ghi tính chất này. Giao diện phải ghi rõ “Minh họa AI”.
- Ghi công nguồn/đơn vị: **Ăn Gì? (agni.vn), veasy**. Chưa xác định tác giả riêng cho từng ảnh; không tự gán tên cá nhân.

Bản đọc HTML và thông tin đối chiếu được lưu ở `statics/runtime/agni-*` trên máy thực hiện, thuộc artifact bỏ qua bởi Git. Không đưa HTML, nội dung công thức hay dữ liệu website nguồn vào dataset của đồ án.

## Cách sử dụng trong project

- Chỉ liên kết ảnh phù hợp với món hiện hữu qua `recipe_id`, giữ nguyên tên, nguyên liệu, định lượng và công thức của project.
- Lưu bản WebP tối ưu cục bộ. Không hotlink; link ngoài chỉ dùng cho ghi công.
- Giữ `source_url`, `source_image_url`, `source_name`, `generated_ai`, `license_note` trong mapping; danh sách thực tế ở [IMAGE_SOURCES_USED.md](IMAGE_SOURCES_USED.md).
- Món chưa có ảnh phù hợp dùng placeholder SVG trung tính do project tự tạo. Placeholder không phải ảnh món ăn.
- Nếu không có quyền phân phối lại phù hợp hoặc quyền bị thu hồi, chuyển mục tương ứng về placeholder và gỡ các bản ảnh liên quan theo quy trình kiểm tra của chủ project.

## Bằng chứng cho phép riêng cần bổ sung

Chủ project bổ sung bản trích hoặc link do tác giả cung cấp, ghi rõ bên cấp phép, ảnh/phạm vi được phép dùng, việc chuyển định dạng/thu nhỏ, phân phối lại trong GitHub, yêu cầu ghi công và các giới hạn. Không lưu thông tin liên hệ riêng tư hoặc toàn bộ trao đổi cá nhân khi chưa được phép công bố.

## Phạm vi commit tích hợp B2/B3

Theo yêu cầu hiện tại của chủ project, chuẩn bị **stage một bộ thay đổi tích hợp B2 + B3**: code frontend, mapping 50 món, 150 WebP, placeholder SVG, công cụ kiểm tra đầu vào B3, tests và tài liệu nguồn. Chưa tạo commit, push hoặc merge. Hai bảng khảo sát B1 được giữ như tài liệu lịch sử vì các tài liệu hiện hành có tham chiếu; không phải mapping đang sử dụng.

Việc stage bản làm việc tích hợp không xác minh giấy phép, không làm thay đổi trạng thái 35 ảnh B2 chờ bằng chứng cấp quyền phân phối lại hoặc thông tin công cụ tạo ảnh B3 chưa được cung cấp. Không coi đây là xác nhận bộ ảnh có giấy phép mở hay đã được duyệt phát hành công khai.

Phương án tách code/placeholder khỏi bộ ảnh từng được đề xuất trước đây nhưng chưa thực hiện. Nếu cần quay lại phương án đó, phải chuẩn bị manifest và tests tương ứng: không chỉ bỏ WebP khỏi staging rồi giữ nguyên mapping/tests đang yêu cầu đủ 150 file. Không xóa hay ghi đè bộ ảnh hiện tại để chuẩn bị commit.

Bộ stage phải loại `.env`, `statics/runtime/`, script kiểm tra/tải ảnh tạm và thay đổi của `statics/results/tcp_server.jsonl`. Log/bằng chứng đã được commit từ trước vẫn giữ nguyên phiên bản trong Git. Backend, MySQL, protocol TCP v1, B0/P1, dataset, benchmark và bằng chứng thực nghiệm cũ giữ nguyên.

## B3 — 15 ảnh AI do chủ project cung cấp

- ID: 1, 2, 3, 7, 8, 9, 10, 20, 21, 32, 38, 41, 45, 47, 48. Ghi nguồn **“Minh họa AI tạo riêng cho project”**; không phải ảnh tải từ agni.vn và không kế thừa ghi công/giấy phép của B2.
- Chủ project cung cấp ảnh gốc và yêu cầu tích hợp, đồng thời chấp nhận những khác biệt minh họa ở ID 20, 21, 32, 41, 48 và ngoại lệ ID 2. Bảng nhận xét ở [B3_AI_IMAGE_IMPORT.md](B3_AI_IMAGE_IMPORT.md).
- Chưa cung cấp tên công cụ, prompt thực tế hoặc điều khoản của công cụ tạo ảnh. Không tự gán tác giả cụ thể, giấy phép mở hoặc quyền phân phối lại đã kiểm chứng độc lập. Tích hợp kỹ thuật không thay thế việc kiểm tra điều kiện phát hành ảnh.
- Bản gốc được giữ nguyên trong runtime; mapping ghi SHA-256, kích thước và tên file để đối chiếu. 45 WebP chỉ thu nhỏ/chuyển định dạng, không sửa nội dung. Các trường nguồn URL để `null`, giao diện ghi công bằng văn bản.
- Trạng thái **35 ảnh B2 chờ bằng chứng cấp quyền phân phối lại** vẫn giữ nguyên; việc bổ sung ảnh B3 không xác minh hay mở rộng quyền của B2.
