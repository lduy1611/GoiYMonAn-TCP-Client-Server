# B3 — Nhập 15 ảnh AI gốc

## Trạng thái

**B3 đã tích hợp:** 15/15 ảnh gốc do chủ project cung cấp đã được kiểm tra tên, giải mã và xem nội dung; tạo thêm 45 WebP. Mapping chính có **50/50 món dùng ảnh minh họa riêng, 0 mục placeholder**, gồm 35 ảnh B2 và 15 ảnh B3; tổng **150 WebP**. SVG chung vẫn phục vụ fallback khi ảnh lỗi. Bản gốc và 105 WebP B2 được giữ nguyên, không crop hoặc ghi đè.

Chỉ xử lý các ID: **1, 2, 3, 7, 8, 9, 10, 20, 21, 32, 38, 41, 45, 47, 48**. Giữ nguyên từng mục mapping và 105 file WebP của 35 món agni.vn còn lại. Tình trạng bằng chứng quyền phân phối lại bộ ảnh B2 không thay đổi; xem [IMAGE_SOURCE_APPROVAL.md](IMAGE_SOURCE_APPROVAL.md).

Chủ project đã cho phép ID 2 dùng ảnh minh họa phù hợp tên “Món thịt rau củ”, không cần thể hiện chính xác mọi bước chế biến. Sau khi xem ảnh, đã báo các khác biệt ở ID 20, 21, 32, 41, 48; chủ project **chấp nhận làm ảnh minh họa và yêu cầu ghi rõ khác biệt**. Không sửa nguyên liệu, hướng dẫn hoặc database để khớp ảnh.

## Kết quả xem nội dung 15 ảnh

Không thấy chữ/watermark rõ trong bộ ảnh. Nhận xét dưới đây là quan sát ảnh minh họa AI, không chứng minh chính xác thành phần thực phẩm.

| ID | Nhận xét / giới hạn |
|---|---|
| 1 | Trứng đảo cùng cà chua, phù hợp loại món. |
| 2 | Thịt xào rau củ, có cà rốt và rau xanh; không thấy trứng. Chấp nhận theo ngoại lệ tên món của chủ project. |
| 3 | Trứng xào với hành xanh, phù hợp loại món; có bát cơm/đạo cụ ở nền. |
| 7 | Cá cắt khúc kho với gừng, phù hợp loại món; không xác minh được loài cá chỉ bằng ảnh. |
| 8 | Bún, thịt xào, hành và dưa leo, phù hợp loại món. |
| 9 | Khoai tây, cà rốt xào với hành, phù hợp loại món. |
| 10 | Trứng cuộn có cà rốt/hành, phù hợp loại món; có lá xà lách trang trí ngoài công thức. |
| 20 | Sợi cao lầu to, bánh giòn và rau xà lách; dataset ghi Bún và không liệt kê bánh giòn. Chủ project chấp nhận khác biệt. |
| 21 | Mì vàng, thịt miếng thay thịt heo xay, thêm trứng, bánh đa và lạc; dataset ghi Bún, tôm, thịt heo xay. Chủ project chấp nhận khác biệt. |
| 32 | Canh đậu phụ với nấm tròn nâu trông gần nấm mỡ; chưa xác định được chủng nấm bằng ảnh. Có hành lá/rau mùi ngoài công thức. Chủ project chấp nhận khác biệt. |
| 38 | Thịt băm chưng trứng mặt vàng, phù hợp loại món; có ớt/rau trang trí ngoài công thức. |
| 41 | Mực xào dứa, có ớt chuông và rau mùi ngoài công thức. Chủ project chấp nhận khác biệt. |
| 45 | Nấm dạng nấm rơm xào với sả, tỏi và ớt, phù hợp loại món. |
| 47 | Dưa leo/cà rốt thái sợi trộn nộm, phù hợp loại món. |
| 48 | Cuốn thịt heo, có cà rốt/xà lách ngoài công thức. Chủ project chấp nhận khác biệt. |

Ảnh giúp nhận diện món, không thay thế danh sách nguyên liệu, thông tin loại trừ hoặc hướng dẫn do API trả về. Không suy ra nguyên liệu thực tế từ đồ trang trí trên ảnh.

## Đưa ảnh gốc vào thư mục

Từ thư mục gốc repository, thư mục nhận ảnh là:

```text
statics/runtime/b3-ai-originals/
```

Trên workspace hiện tại: `D:\Project\lap trinh mang\statics\runtime\b3-ai-originals\`.

Thư mục đã được tạo trên máy này. Toàn bộ `statics/runtime/` được `.gitignore` loại trừ nên ảnh gốc và script/artifact tạm không được đưa vào commit. Khi clone sang máy khác, có thể tạo lại bằng `New-Item -ItemType Directory -Force statics/runtime/b3-ai-originals` từ gốc repository.

- Mỗi ID có đúng **một ảnh gốc**. Dùng `recipe-NN.png`, với ID hai chữ số; có thể thay `.png` bằng `.jpg`, `.jpeg` hoặc `.webp` đúng định dạng thực tế.
- Tên và phần mở rộng dùng chữ thường. Không dùng `recipe-1.png`, tên tiếng Việt, hậu tố `(1)`, `-final`, `-320` hoặc nhiều bản cho cùng ID. Không đổi đuôi để giả định dạng; đổi tên không chuyển đổi ảnh.
- Đưa ảnh trực tiếp vào thư mục, không tạo thư mục con. Thư mục chỉ chứa 15 ảnh gốc, không kèm ghi chú, shortcut hoặc symlink.
- Khuyến nghị bản gốc ngang tỷ lệ 8:5, tối thiểu 960 px chiều rộng **sau crop**. Ưu tiên 1536×960 hoặc lớn hơn. Chưa crop/ghi đè bản gốc trong bước nhập.
- Dùng phong cách nhất quán: món Việt Nam, góc 45 độ hoặc hơi từ trên xuống, ánh sáng tự nhiên, bát/đĩa gốm, nền trung tính, không chữ/watermark. Không thêm nguyên liệu chính chỉ để trang trí.

| recipe_id | Tên món | Tên file gợi ý |
|---|---|---|
| 1 | Trứng sốt cà chua | `recipe-01.png` |
| 2 | Món thịt rau củ | `recipe-02.png` |
| 3 | Trứng xào hành | `recipe-03.png` |
| 7 | Cá basa kho gừng | `recipe-07.png` |
| 8 | Bún thịt xào | `recipe-08.png` |
| 9 | Khoai tây xào cà rốt | `recipe-09.png` |
| 10 | Trứng cuộn rau củ | `recipe-10.png` |
| 20 | Cao lầu Hội An | `recipe-20.png` |
| 21 | Mì Quảng tôm thịt | `recipe-21.png` |
| 32 | Canh nấm rơm đậu phụ | `recipe-32.png` |
| 38 | Thịt băm chưng trứng | `recipe-38.png` |
| 41 | Mực xào dứa | `recipe-41.png` |
| 45 | Nấm xào sả | `recipe-45.png` |
| 47 | Nộm dưa leo cà rốt | `recipe-47.png` |
| 48 | Bánh tráng cuốn thịt heo | `recipe-48.png` |

## Kiểm tra tên file

Chạy từ thư mục gốc repository:

```powershell
.\.venv\Scripts\python.exe -B scripts/check_b3_image_inputs.py
```

Nếu dùng thư mục khác, chỉ định rõ đường dẫn:

```powershell
.\.venv\Scripts\python.exe -B scripts/check_b3_image_inputs.py --input-dir 'D:\Project\lap trinh mang\statics\runtime\b3-ai-originals'
```

Exit code `0`: đủ đúng 15 tên file, không trùng ID hoặc tên lạ. Exit code `1`: còn thiếu/trùng/tên sai, chưa sẵn sàng. Exit code `2`: không đọc được thư mục. Lần nhập B3 này đạt **15/15**, exit code `0`; mỗi ID có một PNG thật, chiều rộng 1585 hoặc 1586 px, chiều cao 992 px.

Công cụ **chỉ đọc tên file**; không sửa/đổi tên/xóa/copy/chuyển ảnh, không đổi manifest và không kết nối TCP/MySQL. Kết quả đạt không xác nhận file là ảnh hợp lệ hay ảnh đúng món. Một ảnh đặt nhầm ID vẫn có thể vượt kiểm tra tên, nên cần xem từng ảnh ở bước sau.

## Quy trình tích hợp B3

1. Kiểm tra đủ tên file, giải mã định dạng ảnh, kích thước và xem trực tiếp từng ảnh theo ID. Đối chiếu món/nguồn gốc, không suy ra nội dung từ tên file. Ghi lại công cụ tạo, prompt và điều kiện sử dụng nếu được cung cấp; không bịa tác giả, URL hoặc giấy phép mở.
2. Sau khi ảnh được duyệt, tạo **45 WebP** mới trong `source/web/static/images/recipes/`: `recipe-01-ai-320.webp`, `recipe-01-ai-640.webp`, `recipe-01-ai-960.webp` và tương tự cho 14 ID còn lại. Giữ bản gốc; không ghi đè 105 file của B2. Nếu ảnh thiếu độ phân giải, báo để bổ sung thay vì tự phóng lớn rồi tuyên bố đạt chất lượng.
3. Chỉ cập nhật 15 mục tương ứng trong `recipe-images.json`, khi asset đã tồn tại và hợp lệ. Ghi nguồn **“Minh họa AI tạo riêng cho project”**, `source_type=project_ai`, `generated_ai=true`, alt theo đúng món, các biến thể 320/640/960 và trạng thái không còn placeholder. `source_url`/`source_image_url` để `null`; SHA-256, kích thước và tên file gốc lưu trong mapping. Chưa có tên công cụ tạo, prompt thực tế hoặc điều khoản công cụ; không tự khẳng định giấy phép mở. 35 mục B2 không đổi.
4. Loader frontend đã hỗ trợ nguồn AI nội bộ bằng văn bản, không tạo link giả và không mượn URL agni.vn. Ảnh B3 dùng `object-fit: contain` để giữ trọn ảnh trong khung, file WebP giữ tỷ lệ gốc, không crop. Giữ cách ghi công 35 ảnh B2. Tests ảnh phân biệt hai loại nguồn. CSS/JS/manifest đồng bộ cache URL `ui-1.2.3`; manifest version `images-1.2.3`.
5. Kiểm tra ảnh trên RECOMMEND, SEARCH_RECIPES, chi tiết, Back/reload và ảnh lỗi về SVG placeholder. Kiểm tra lazy loading, `srcset`, `sizes`, kích thước thực tế, không tràn ngang ở Chrome 1280/390/320 px. Cập nhật tài liệu nguồn và kết quả kiểm thử theo thực tế.
6. Chạy test liên quan và toàn bộ pytest sau tích hợp; log/ảnh chụp/artifact mới chỉ trong `statics/runtime/`. Không thay backend, FastAPI, TCP v1, MySQL, B0/P1, dataset; không seed, migration, benchmark, commit, push hoặc merge.

Lệnh kiểm thử sau khi tích hợp:

```powershell
$env:TCP_LOG_PATH = 'statics/runtime/b3_tcp.jsonl'
.\.venv\Scripts\python.exe -m pytest tests --import-mode=importlib -p no:cacheprovider -q -rs
```

45 WebP mới dùng quality 76, rộng 320/640/960 px, tổng 2.025.852 byte (khoảng 1,93 MiB). Các file được đặt `recipe-NN-ai-SIZE.webp` để tách khỏi tên file B2. Bản gốc vẫn ở thư mục runtime do chủ project cung cấp; không cần đưa bản gốc vào repository để chạy ứng dụng.

## Kết quả kiểm thử B3

Kết quả thực tế ngày 01/11/2026:

- Nhóm liên quan (nhập ảnh, mapping/static, contract frontend, Chrome): **24 passed, 0 failed, 0 skipped, 1 warning**, 36,89 giây.
- Toàn bộ pytest: **124 passed, 0 failed, 0 skipped, 1 warning**, 60,98 giây. JUnit: `statics/runtime/b3-pytest.xml`. Warning duy nhất là `StarletteDeprecationWarning` về `httpx` trong TestClient. Lần chạy toàn bộ có `-W error::pytest.PytestUnhandledThreadExceptionWarning`.
- Chrome thật headless ở 1280/390 px, kiểm tra thêm 320 px. Đã kiểm tra tìm kiếm, gợi ý, chi tiết, Back/reload, chuột/bàn phím, nguồn B2/B3, `srcset`/`currentSrc`, lazy loading, ảnh mất/mapping lỗi và không tràn ngang. Browser test còn mount ảnh cho toàn bộ 50 ID từ catalog và kiểm tra tải thành công, đúng đường dẫn ID, 15 nguồn AI nội bộ; bước component này không tạo dữ liệu món hay thay API. Hành trình API/TCP giao diện dùng SQLite fixture tạm 10 món; test MySQL trong suite chỉ đọc.
- Không có exception JavaScript chưa xử lý hoặc `console.error` từ ứng dụng; request ảnh/mapping cố tình gây lỗi trong test fallback có thể có thông báo HTTP lỗi của trình duyệt.
- Ảnh chụp/metrics: `statics/runtime/b3-preview/`, gồm `results-1280.png`, `recipe-390.png`, `recipe-320.png`, `search-1280.png`, `search-390.png` và các ảnh khác. Ảnh chụp dùng fixture kiểm thử, không phải thao tác trên MySQL đang dùng.
- Checksum sau kiểm thử khớp baseline trước B3 cho 15 ảnh gốc, 105 WebP B2, backend/TCP Client/FastAPI, database file, `.env` và `statics/results/`; so sánh nguyên từng mục mapping xác nhận 35 mục B2 giữ nguyên. Không sửa log thực nghiệm cũ, không chạy migration/seed MySQL hoặc benchmark, không stage/commit/push/merge.

## Kiểm tra thủ công B3 qua Wi-Fi

Giữ TCP ở localhost, chạy gateway theo README với `--host 0.0.0.0 --port 8000`. Điện thoại cùng Wi-Fi mở `http://<IPv4-LAN-laptop>:8000/`; nếu cần, cho phép Python trên mạng Private ở firewall. Không mở cổng TCP/MySQL ra ngoài.

Tìm `trung`, `nam xao sa` hoặc `mi quang` để xem ảnh B3; tìm `dau phu` để kiểm tra ảnh B2 và link nguồn cũ. Trong chế độ gợi ý, chọn Trứng/Cà chua; mở công thức rồi Back/reload để kiểm tra ảnh, bộ lọc và kết quả. B3 phải ghi “Minh họa AI tạo riêng cho project” không kèm link agni.vn. Có thể chặn một file ảnh qua DevTools để kiểm tra fallback SVG và bỏ link ghi công cũ khi ảnh lỗi.

Chủ project đã xác nhận điện thoại vật lý qua Wi-Fi với **B2** trước đây. Chưa có xác nhận kiểm tra lại **B3** trên điện thoại vật lý; Chrome viewport 390/320 px được báo riêng với kết quả tự động, không thay thế kiểm thử đó.

## Checkout độc lập

Ứng dụng chỉ cần mapping, loader, CSS/templates và đủ 150 WebP cùng placeholder SVG trong repository; không cần 15 ảnh PNG gốc, script chuyển đổi tạm hoặc artifact ở `statics/runtime/`. Công cụ `scripts/check_b3_image_inputs.py` và test của công cụ được giữ trong repository. Khi chưa có nhu cầu nhập lại ảnh, không cần tạo thư mục ảnh gốc để chạy ứng dụng hoặc pytest; các test nhập ảnh tạo fixture riêng trong thư mục tạm.

Thiết lập Python/requirements và MySQL theo README, tự tạo `.env` từ `.env.example`; cấu hình cá nhân không nằm trong commit. Tests ảnh không đọc ảnh gốc runtime hoặc kết nối MySQL; browser test chế độ mặc định không cần stylesheet lịch sử của lần chụp “before”. MySQL integration cần database đã cấu hình, chỉ đọc và có thể skip nếu môi trường chưa có cấu hình. Mọi log/test artifact mới phải trỏ vào `statics/runtime/`.
