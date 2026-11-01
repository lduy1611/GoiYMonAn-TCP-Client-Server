# B2/B3 — Ảnh đang sử dụng

Đối chiếu theo 50 `recipe_id`/tên món trong `statics/results/phase4_dataset_audit.json`, không sửa dữ liệu công thức. Bảng B1 trong `IMAGE_CANDIDATES.md` và `image_candidates.csv` chỉ là lịch sử ứng viên; bảng dưới cùng `source/web/static/recipe-images.json` phản ánh ảnh B2/B3 thực tế.

**50/50 món có ảnh minh họa riêng: 35 từ Ăn Gì? (B2), 15 ảnh AI do chủ project cung cấp (B3); 0 mục placeholder trong mapping chính; 0 ảnh chụp món thật.** Đã xem bộ ảnh để kiểm tra loại món. Ảnh chỉ minh họa, không cam kết mọi chi tiết trang trí/cách bày khớp công thức của project. Ngoại lệ ID 2 và những khác biệt ID 20, 21, 32, 41, 48 đã được chủ project chấp nhận; nhận xét từng ảnh ở [B3_AI_IMAGE_IMPORT.md](B3_AI_IMAGE_IMPORT.md).

Nguồn 35 ảnh B2: **Ăn Gì? (agni.vn), veasy**. Chưa có tên tác giả riêng cho từng ảnh. Quyền sử dụng: sự cho phép riêng do chủ project xác nhận, nội dung/link bằng chứng chưa được cung cấp; **không phải giấy phép mở công khai**. Xem [căn cứ và phần cần bổ sung](IMAGE_SOURCE_APPROVAL.md).

Trạng thái áp dụng cho **tất cả 35 ảnh B2 và 105 bản WebP B2** trong danh sách: **chờ bằng chứng cấp quyền phân phối lại**. Hiện chưa có ảnh B2 nào được kiểm chứng độc lập về quyền này. 15 ảnh B3 ghi nguồn **“Minh họa AI tạo riêng cho project”**, không có URL nguồn ngoài; chủ project cung cấp ảnh và yêu cầu tích hợp, nhưng chưa cung cấp tên công cụ tạo, prompt thực tế hoặc điều khoản công cụ. Không suy ra giấy phép mở cho nhóm ảnh nào. Placeholder SVG do project tự tạo được quản lý riêng.

Mỗi ảnh có ba bản WebP cục bộ rộng 320/640/960px, giữ tỷ lệ gốc, quality 76, bỏ metadata khi mã hóa lại. Tổng **150 WebP, 7.372.074 byte (khoảng 7,03 MiB)**, gồm 105 file B2 giữ nguyên và 45 file B3 thêm mới (2.025.852 byte). Trình duyệt chọn một bản qua `srcset`/`sizes`. Card dùng lazy loading, ảnh chi tiết eager, khung 8:5 có kích thước cố định. B2 giữ CSS cũ; riêng B3 dùng `object-fit: contain` để không crop món ăn. Mapping B2 giữ URL CDN/SHA-256; mapping B3 ghi tên file gốc, kích thước, SHA-256 và URL `null`. Không hotlink hay đưa ảnh gốc runtime vào ứng dụng.

Placeholder chung: `source/web/static/images/recipes/placeholder.svg`, SVG trung tính do project tự tạo, vẫn giữ để fallback khi file ảnh/mapping lỗi. Việc chấp nhận ảnh B3 chỉ áp dụng cho minh họa; không sửa hoặc suy ra nguyên liệu công thức từ ảnh.

## Danh sách

Đường dẫn dưới đây tính từ `source/web/static/images/recipes/`. B2 dùng `recipe-NN-640.webp`, B3 dùng `recipe-NN-ai-640.webp` làm bản mặc định; mỗi món có thêm bản 320/960px tương ứng. 35 mục nguồn B2 giữ nguyên.

| recipe_id | Tên món trong project | File mặc định | Trang nguồn | Đối chiếu / trạng thái |
|---|---|---|---|---|
| 1 | Trứng sốt cà chua | `recipe-01-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 2 | Món thịt rau củ | `recipe-02-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 3 | Trứng xào hành | `recipe-03-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 4 | Đậu phụ sốt cà chua | `recipe-04-640.webp` | [source](https://agni.vn/mon/dau-phu-sot-ca-chua) | AI; dau-phu-sot-ca-chua-e031a31c1214 |
| 5 | Rau muống xào tỏi | `recipe-05-640.webp` | [source](https://agni.vn/mon/rau-muong-xao-toi) | AI; rau-muong-xao-toi-565d0fee9c3d |
| 6 | Canh gà nấm hương | `recipe-06-640.webp` | [source](https://agni.vn/mon/canh-ga-nam-huong) | AI; canh-ga-nam-huong-5d6730efc70b |
| 7 | Cá basa kho gừng | `recipe-07-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 8 | Bún thịt xào | `recipe-08-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 9 | Khoai tây xào cà rốt | `recipe-09-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 10 | Trứng cuộn rau củ | `recipe-10-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 11 | Phở bò | `recipe-11-640.webp` | [source](https://agni.vn/mon/pho-bo) | AI; pho-bo-30ba26e7f588 |
| 12 | Phở gà | `recipe-12-640.webp` | [source](https://agni.vn/mon/pho-ga) | AI; pho-ga-bff59dc2e3dc |
| 13 | Bún chả | `recipe-13-640.webp` | [source](https://agni.vn/mon/bun-cha) | AI; bun-cha-8e475d1153e3 |
| 14 | Bún bò Huế | `recipe-14-640.webp` | [source](https://agni.vn/mon/bun-bo-hue) | AI; bun-bo-hue-c8aa5696e2e2 |
| 15 | Bún riêu cua | `recipe-15-640.webp` | [source](https://agni.vn/mon/bun-rieu-cua) | AI; bun-rieu-cua-3c6ed06257a6 |
| 16 | Gỏi cuốn tôm thịt | `recipe-16-640.webp` | [source](https://agni.vn/mon/goi-cuon) | AI; goi-cuon-98a124204231 |
| 17 | Chả giò | `recipe-17-640.webp` | [source](https://agni.vn/mon/nem-ran) | AI; nem-ran-f01101878347 |
| 18 | Bánh xèo | `recipe-18-640.webp` | [source](https://agni.vn/mon/banh-xeo) | AI; banh-xeo-36abbd7fa406 |
| 19 | Bánh cuốn nhân thịt | `recipe-19-640.webp` | [source](https://agni.vn/mon/banh-cuon) | AI; banh-cuon-3a18b6df718b |
| 20 | Cao lầu Hội An | `recipe-20-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 21 | Mì Quảng tôm thịt | `recipe-21-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 22 | Cơm tấm sườn | `recipe-22-640.webp` | [source](https://agni.vn/mon/com-tam-suon-nuong) | AI; com-tam-suon-nuong-b98ee1745f57 |
| 23 | Cơm gà xối mỡ | `recipe-23-640.webp` | [source](https://agni.vn/mon/com-ga-xoi-mo) | AI; com-ga-xoi-mo-5ae68b336bf7 |
| 24 | Cơm chiên Dương Châu | `recipe-24-640.webp` | [source](https://agni.vn/mon/com-rang-duong-chau) | AI; com-rang-duong-chau-4db31951300a |
| 25 | Cơm chiên cá mặn | `recipe-25-640.webp` | [source](https://agni.vn/mon/com-rang-ca-man) | AI; com-rang-ca-man-36e0c7b90d3d |
| 26 | Cá kho tộ | `recipe-26-640.webp` | [source](https://agni.vn/mon/ca-kho-to) | AI; ca-kho-to-8f56b69b52be |
| 27 | Thịt kho trứng | `recipe-27-640.webp` | [source](https://agni.vn/mon/thit-kho-trung) | AI; thit-kho-trung-7176e82aba19 |
| 28 | Canh chua cá | `recipe-28-640.webp` | [source](https://agni.vn/mon/canh-chua-ca) | AI; canh-chua-ca-fd74f874da6b |
| 29 | Canh bí đỏ hầm xương | `recipe-29-640.webp` | [source](https://agni.vn/mon/canh-bi-do-nau-suon) | AI; canh-bi-do-nau-suon-63842ef2b111 |
| 30 | Canh rau ngót thịt bằm | `recipe-30-640.webp` | [source](https://agni.vn/mon/canh-rau-ngot-nau-thit-bam) | AI; canh-rau-ngot-nau-thit-bam-c039ff029838 |
| 31 | Canh cải chua sườn | `recipe-31-640.webp` | [source](https://agni.vn/mon/canh-suon-nau-dua-chua) | AI; canh-suon-nau-dua-chua-8ea463d4b402 |
| 32 | Canh nấm rơm đậu phụ | `recipe-32-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 33 | Gà kho gừng | `recipe-33-640.webp` | [source](https://agni.vn/mon/ga-kho-gung) | AI; ga-kho-gung-d0295981c2d9 |
| 34 | Gà xào sả ớt | `recipe-34-640.webp` | [source](https://agni.vn/mon/ga-xao-sa-ot) | AI; ga-xao-sa-ot-2edbe553384f |
| 35 | Bò lúc lắc | `recipe-35-640.webp` | [source](https://agni.vn/mon/bo-luc-lac) | AI; bo-luc-lac-06df7a7ba6e4 |
| 36 | Bò xào rau muống | `recipe-36-640.webp` | [source](https://agni.vn/mon/rau-muong-xao-thit-bo) | AI; rau-muong-xao-thit-bo-7b276092ff2d |
| 37 | Thịt heo kho tiêu | `recipe-37-640.webp` | [source](https://agni.vn/mon/thit-kho-tieu) | AI; thit-kho-tieu-e181de982ea7 |
| 38 | Thịt băm chưng trứng | `recipe-38-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 39 | Sườn xào chua ngọt | `recipe-39-640.webp` | [source](https://agni.vn/mon/suon-xao-chua-ngot) | AI; suon-xao-chua-ngot-105c9104cbd5 |
| 40 | Tôm rang me | `recipe-40-640.webp` | [source](https://agni.vn/mon/tom-rang-me) | AI; tom-rang-me-a24596c65cc8 |
| 41 | Mực xào dứa | `recipe-41-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 42 | Tôm hấp nước dừa | `recipe-42-640.webp` | [source](https://agni.vn/mon/tom-hap-nuoc-dua) | AI; tom-hap-nuoc-dua-bd6e2955f375 |
| 43 | Đậu phụ nhồi thịt | `recipe-43-640.webp` | [source](https://agni.vn/mon/dau-phu-nhoi-thit-sot-ca-chua) | AI; dau-phu-nhoi-thit-sot-ca-chua-c3e450e027cf |
| 44 | Đậu phụ kho nấm | `recipe-44-640.webp` | [source](https://agni.vn/mon/dau-phu-kho-nam-rom) | AI; dau-phu-kho-nam-rom-0650a5d4fc90 |
| 45 | Nấm xào sả | `recipe-45-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 46 | Gỏi gà rau răm | `recipe-46-640.webp` | [source](https://agni.vn/mon/nom-ga-rau-ram) | AI; nom-ga-rau-ram-f1b61b00b1ff |
| 47 | Nộm dưa leo cà rốt | `recipe-47-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 48 | Bánh tráng cuốn thịt heo | `recipe-48-ai-640.webp` | Minh họa AI tạo riêng cho project | AI B3; chủ project cung cấp; xem bảng nhận xét B3 |
| 49 | Chả lá lốt | `recipe-49-640.webp` | [source](https://agni.vn/mon/cha-la-lot) | AI; cha-la-lot-741e72b99c07 |
| 50 | Miến gà | `recipe-50-640.webp` | [source](https://agni.vn/mon/mien-ga) | AI; mien-ga-0d38b1c10f2a |

## Tích hợp và kiểm tra

- `recipe-images.json` chỉ là metadata trình bày; không thay đổi response TCP/API hay schema MySQL.
- `recipe-images.js` được dùng chung cho kết quả RECOMMEND, SEARCH_RECIPES và trang công thức. Chỉ chấp nhận đường dẫn ảnh cục bộ, kiểm tra `recipe_id`, ghi công bằng text/link an toàn. Không thêm metadata ảnh vào sessionStorage; khi Back/reload, ảnh được gắn lại theo ID của kết quả đã khôi phục.
- Mất mapping, mapping lỗi, ảnh thiếu hoặc đường dẫn ảnh ngoài miền: hiển thị placeholder; thao tác tìm/gợi ý/chi tiết vẫn tiếp tục.
- Kiểm thử ảnh gồm kiểm tra mapping/asset cục bộ, HTTP static và Chrome thật qua CDP. Fixture SVG trong browser test chỉ là dữ liệu kiểm thử trung tính, không được đưa vào mapping sản phẩm hoặc gọi là ảnh đã cấp phép.

Chạy kiểm thử bằng PowerShell:

```powershell
$env:TCP_LOG_PATH = 'statics/runtime/images_b2_tcp.jsonl'
.\.venv\Scripts\python.exe -m pytest tests --import-mode=importlib -p no:cacheprovider -q -rs
```

Kết quả thực tế của lần chạy toàn bộ sau B2: **110 passed, 0 failed, 0 skipped, 1 warning**, thời gian 53,62 giây. Warning là `StarletteDeprecationWarning` về `httpx` trong TestClient; không thay dependency của project để xử lý cảnh báo ngoài phạm vi B2. JUnit: `statics/runtime/images-b2-pytest.xml`. Lần chạy này còn đặt `-W error::pytest.PytestUnhandledThreadExceptionWarning` để lỗi thread không bị bỏ qua.

Chrome thật chạy headless trên Windows, dùng dữ liệu SQLite tạm cho hành trình giao diện, viewport desktop 1280px/mobile 390px và kiểm tra 320px. Kiểm tra chuột/bàn phím, cả hai loại card, ảnh chi tiết, ảnh theo ID, ghi công/nhãn AI, ảnh mất/mapping lỗi/URL ngoài miền, Back/reload, bộ lọc và trạng thái rỗng đều đạt; không có exception JavaScript hoặc `console.error` do ứng dụng. Những request ảnh/mapping cố tình làm lỗi trong test fallback có thể tạo thông báo HTTP lỗi của trình duyệt. Các ảnh chụp ở `statics/runtime/images-b2-preview/`, gồm `photo-search-1280.png`, `photo-results-390.png`, `photo-recipe-320.png` và các kích thước tương ứng. Ảnh chụp dùng fixture kiểm thử, không phải ảnh chụp thao tác trên database MySQL đang dùng.

Test MySQL trong toàn bộ suite chỉ đọc; không chạy migration/seed MySQL hay benchmark. Checksum của backend, database file, `.env` và `statics/results/` giữ nguyên so với đầu công việc B2. File log cũ đã có thay đổi chưa commit từ trước B2 được giữ nguyên, không khôi phục hoặc ghi thêm. Đây là kết quả tự động; xác nhận điện thoại thật của chủ project được ghi riêng ở mục dưới.

Lần QA tự động tiếp theo đã thực hiện trước lần cập nhật tài liệu này: **110 passed, 0 failed, 0 skipped, 1 warning trong 52,55 giây**, JUnit `statics/runtime/b2-final-qa-pytest.xml`. Kiểm tra Chrome riêng bằng script tạm cho `srcset`/`currentSrc` và kích thước ảnh đạt **2 passed, 0 failed, 0 skipped, 1 warning trong 29,33 giây**; không cộng hai lần chạy thành 112 test khác nhau. Các script/artifact này chỉ ở `statics/runtime/`, không đưa vào Git. Không chạy lại test hoặc benchmark trong lần sửa tài liệu này.

## Kiểm thử điện thoại vật lý qua Wi-Fi — xác nhận thủ công

Ngày 01/11/2026, **chủ project xác nhận** đã kiểm tra thành công trên điện thoại thật qua Wi-Fi: gợi ý theo nguyên liệu, tìm kiếm món, hiển thị ảnh và trang chi tiết công thức. Đây là xác nhận thủ công do chủ project cung cấp, tách biệt với Chrome headless và kết quả pytest tự động ở trên; công cụ không trực tiếp quan sát điện thoại.

Chưa có thông tin model/OS/phiên bản trình duyệt hoặc artifact cho lần kiểm tra điện thoại. Không tự bổ sung kết quả cho các luồng chưa được chủ project xác nhận. Xác nhận chức năng hoạt động không phải bằng chứng cấp quyền phân phối lại 35 ảnh.

## Hướng dẫn kiểm tra lại

Kết quả **B3** mới nhất: nhóm liên quan **24 passed, 0 failed, 0 skipped, 1 warning** (36,89 giây); toàn bộ pytest **124 passed, 0 failed, 0 skipped, 1 warning** (60,98 giây), JUnit `statics/runtime/b3-pytest.xml`. Warning vẫn là deprecation Starlette/TestClient với `httpx`. Chrome thật kiểm tra 1280/390/320 px, toàn bộ 50 ID ở lớp component ảnh và hành trình gợi ý/tìm/chi tiết/Back/reload/fallback; artifact ở `statics/runtime/b3-preview/`. B2 và B3 được hiển thị nguồn riêng, B3 không có link agni.vn. Checksum xác nhận 35 mục mapping B2, 105 WebP B2 và ảnh gốc không thay đổi. Chi tiết xem [kết quả B3](B3_AI_IMAGE_IMPORT.md).

Xác nhận điện thoại thật ở mục trên là **B2**, không tự coi là xác nhận đã kiểm tra lại B3. Cần chủ project thử B3 theo hướng dẫn dưới đây trên điện thoại cùng Wi-Fi.

Kiểm tra thủ công: tìm `dau phu`/`phở bò` để thấy ảnh; tìm `trung` để thấy placeholder; mở công thức rồi Back/reload để kiểm tra bộ lọc và kết quả. Trong chế độ gợi ý, chọn Đậu phụ + Cà chua và kiểm tra món Đậu phụ sốt cà chua. Kiểm tra DevTools Network: ảnh phải đến từ `/static/images/recipes/`, không gọi CDN nguồn. Có thể chặn một file ảnh qua DevTools rồi tải lại để kiểm tra fallback.

Trên điện thoại cùng Wi-Fi, giữ TCP Server ở localhost và chạy gateway bằng `--host 0.0.0.0 --port 8000` như README (thay host); mở `http://<IPv4-LAN-của-laptop>:8000/`. Nếu cần, cho phép Python qua firewall mạng Private. Không mở cổng MySQL hoặc TCP ra Internet. Kiểm thử viewport Chrome không thay thế kiểm tra trên điện thoại vật lý/mạng Wi-Fi thực tế.
