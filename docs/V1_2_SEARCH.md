# v1.2 — Tìm kiếm món ăn qua TCP và tích hợp ảnh B2/B3

Luồng: trình duyệt → `POST /api/search` → `TCPClient` → `SEARCH_RECIPES` → repository chỉ đọc MySQL → tìm/lọc/phân trang trên TCP Server. Không tải toàn bộ danh mục món về trình duyệt để tìm kiếm cục bộ. Với dataset 50 món, server tái sử dụng truy vấn metadata và quan hệ nguyên liệu của repository; không cần migration, cột mới hoặc tải hướng dẫn vào kết quả tìm kiếm.

## Hợp đồng TCP

Giữ protocol version 1, UUID, JSON UTF-8, header 4 byte big-endian, giới hạn body 65.536 byte và timeout hiện tại. Thêm operation; không đổi payload hay response của bốn operation cũ. `source/server/ranking.py` không thay đổi.

```json
{
  "version": 1,
  "request_id": "e35954bb-19f1-40a6-a8d2-77288ead8050",
  "op": "SEARCH_RECIPES",
  "payload": {
    "query": "pho",
    "ingredient_ids": [],
    "excluded_ids": [],
    "max_minutes": 90,
    "max_missing": null,
    "limit": 12,
    "offset": 0
  }
}
```

| Trường | Mặc định / giới hạn |
|---|---|
| query | `""`; string tối đa 80 code point trước chuẩn hóa |
| ingredient_ids | `[]`; tối đa 30 ID nguyên dương tồn tại; ID trùng được gộp khi tính tập hợp |
| excluded_ids | `[]`; tối đa 30 ID hợp lệ; không giao với ingredient_ids |
| max_minutes | `null`; hoặc số nguyên 1–240 |
| max_missing | `null`; hoặc số nguyên 0–50 |
| limit | 12; số nguyên 1–20 |
| offset | 0; số nguyên không âm |

Không chấp nhận bool thay số nguyên, ép kiểu string/số thực, trường lạ hoặc ID không tồn tại. Payload sai trả `INVALID_PAYLOAD`, giữ UUID; HTTP tương ứng 422. Không có món phù hợp trả thành công với danh sách rỗng.

`data` chứa `dataset_version`, `items`, `total`, `limit`, `offset`, `has_more`, `warnings`. Mỗi item chỉ có `recipe_id`, `title`, `minutes`, `matched_ids`, `missing_ids`, `missing_count`; không có score/coverage/input_use của B0/P1. `total` đếm kết quả sau mọi bộ lọc, trước phân trang. Offset vượt total trả trang rỗng và `has_more=false`. `NO_MATCH` chỉ xuất hiện khi tổng kết quả bằng 0.

Tên tìm kiếm được casefold, chuẩn hóa NFD, bỏ dấu tổ hợp, đổi đ/Đ thành d, gom khoảng trắng. Tên gốc không bị sửa. Query được khớp như chuỗi literal; `%`, `_`, dấu nháy không phải SQL wildcard hoặc câu SQL. Thứ tự: khớp toàn bộ tên → tên bắt đầu bằng query → tên chứa query; mỗi nhóm tăng dần recipe_id. Query rỗng xếp theo recipe_id.

`missing_count = |required_ids - ingredient_ids|`. Không chọn nguyên liệu: tất cả nguyên liệu bắt buộc là thiếu; `max_missing=null` không áp giới hạn ngầm. Loại trừ áp dụng cả nguyên liệu bắt buộc và tùy chọn. Tất cả bộ lọc thực hiện trước `offset/limit`. SEARCH không loại bỏ món chỉ vì không có nguyên liệu khớp.

## Giao diện và cache

Giữ chế độ mặc định “Gợi ý theo nguyên liệu” của v1.1.2. Nút “Tìm món theo tên” cho phép tìm ngay khi chưa chọn nguyên liệu; query rỗng để duyệt. Mỗi trang tối đa 20 món. Không có điểm xếp hạng trên thẻ tìm kiếm; chuyển lại RECOMMEND vẫn có điểm P1 thật.

SessionStorage schema 3 lưu chế độ, query, nguyên liệu, bộ lọc, offset/limit, kết quả/trạng thái lỗi/rỗng, dataset_version và vị trí cuộn. Chữ ký cache bao gồm chế độ và tất cả tham số có ảnh hưởng đến kết quả. Thay query/bộ lọc/chế độ sẽ bỏ kết quả và về trang đầu. Cache lỗi hoặc khác phiên bản dataset không được hiển thị. Cache v1.1.2 được nâng cấp khi khớp chính xác điều kiện cũ. CSS/JS/URL manifest hiện cùng phiên bản cache `ui-1.2.3` sau B3 để tránh trộn asset cũ.

## Kiểm tra thủ công

Khởi động TCP/Web theo README, đặt `TCP_LOG_PATH=statics/runtime/v1_2_manual.jsonl` trong terminal TCP trước khi chạy. Không cần chạy bất kỳ SQL seed nào.

1. Mở trang, chọn “Tìm món theo tên”, để trống nguyên liệu.
2. Tìm `phở`/`pho` và `đậu`/`dau`; so sánh các tên trả về. Bật DevTools Network để thấy POST `/api/search`.
3. Để query rỗng, đặt số món mỗi trang = 2; thử Trang sau/Trang trước.
4. Chọn nguyên liệu 1, 2; loại trừ 7; query `trung`, thời gian 20, thiếu tối đa 0. Mọi điều kiện phải áp dụng đồng thời.
5. Mở công thức, dùng Back và reload; kiểm tra chế độ, query, bộ lọc, trang và kết quả còn nguyên. Đổi query: kết quả cũ phải biến mất ngay.
6. Chuyển về gợi ý nguyên liệu và kiểm tra luồng cũ. Tìm tên không tồn tại để kiểm tra trạng thái rỗng.

Ví dụ TCP trực tiếp (không phải benchmark):

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "from source.client.tcp_client import TCPClient; print(TCPClient().request('SEARCH_RECIPES', {'query':'pho','limit':12}))"
```

Kiểm thử:

```powershell
$env:TCP_LOG_PATH = 'statics/runtime/v1_2_pytest.jsonl'
.\.venv\Scripts\python.exe -m pytest tests --import-mode=importlib -p no:cacheprovider -q -rs
```

Browser test dùng Chrome/Edge và Node có WebSocket/fetch. Nếu thiếu thì skip có lý do; skip không xác nhận đã kiểm tra browser. Test tạo SQLite fixture tạm; MySQL integration hiện có chỉ đọc database cấu hình.

Kết quả tự động của giai đoạn A (lịch sử), ngày 01/11/2026: **105 passed, 0 failed, 0 skipped, 1 warning trong 43,27 giây**. Warning là deprecation Starlette/httpx có từ trước. Đã chạy Chrome thật ở 1280/390 px và kiểm tra tràn ngang 320 px, các luồng v1.1.2 và tìm kiếm v1.2; test MySQL không bị skip. Browser test kiểm tra console JavaScript, chuột/bàn phím, cache version, tìm có dấu/không dấu/NFD, kết quả không có score, bộ lọc kết hợp, phân trang, Back/reload, cache sai từ khóa/trang và nâng cấp cache v1.1.2. Đây là functional test, không phải benchmark E2.

Lần kiểm tra chất lượng tự động cuối B2 đã thực hiện ngày 01/11/2026: **110 passed, 0 failed, 0 skipped, 1 warning trong 52,55 giây**; JUnit ở `statics/runtime/b2-final-qa-pytest.xml`. Kiểm tra Chrome bổ sung bằng script tạm cho `srcset`, `currentSrc` và kích thước ảnh: **2 passed, 0 failed, 0 skipped, 1 warning trong 29,33 giây**. Đây là lần kiểm tra riêng, không cộng thành 112 test khác nhau của suite. Warning vẫn là deprecation Starlette/TestClient với `httpx`. Các kết quả này đã có từ đợt QA trước; lần cập nhật tài liệu này không chạy lại pytest hoặc benchmark.

## Điện thoại qua Wi-Fi

Chạy riêng Web bằng `--host 0.0.0.0`, giữ TCP_HOST=127.0.0.1 và TCP/MySQL trong máy chủ. Điện thoại cùng Wi-Fi mở `http://<IP-LAN-máy-chủ>:8000`. Nếu cần quyền firewall, chỉ cấu hình cho mạng riêng/cổng Web phù hợp. Không cần mở cổng MySQL/TCP cho điện thoại. Các URL API/asset là relative nên dùng cùng host.

**Xác nhận thủ công của chủ project, ngày 01/11/2026:** đã kiểm tra thành công B2 trên điện thoại thật qua Wi-Fi, gồm gợi ý theo nguyên liệu, tìm món, hiển thị ảnh và trang chi tiết công thức. Đây là thông tin chủ project cung cấp, không phải kết quả tự động hoặc thao tác do công cụ trực tiếp quan sát.

Chưa được cung cấp model điện thoại, hệ điều hành, phiên bản trình duyệt hoặc artifact của lần kiểm tra thủ công; không suy diễn thêm các thông số này hay những luồng chưa được xác nhận. Chrome headless với viewport 1280/390/320 px là bằng chứng tự động riêng, không thay thế xác nhận điện thoại vật lý.

## Phạm vi ảnh

**B2 và B3 đã triển khai trong workspace:** 35 món giữ nguyên ảnh minh họa AI từ **Ăn Gì? (agni.vn)**, 15 món có ảnh **“Minh họa AI tạo riêng cho project”** do chủ project cung cấp. Mapping chính có **50/50 món có ảnh riêng, 0 mục placeholder**; không có ảnh chụp món thật. Bộ ảnh gồm 150 WebP cục bộ (320/640/960 px), không hotlink; vẫn giữ `placeholder.svg` cho lỗi tải ảnh. Ảnh hiển thị trên thẻ RECOMMEND, SEARCH_RECIPES và trang chi tiết; có alt, ghi công, lazy loading cho card, `srcset`/`sizes` và fallback khi ảnh hoặc mapping lỗi.

Mapping `source/web/static/recipe-images.json` liên kết theo `recipe_id`, được dùng bởi `recipe-images.js`. Khi khôi phục kết quả từ sessionStorage, giao diện gắn lại ảnh theo ID. Việc tích hợp ảnh không thay đổi response TCP/API, schema MySQL, B0/P1 hoặc dữ liệu công thức.

Số lượng trên mô tả workspace hiện tại, không xác nhận bộ ảnh đã đủ điều kiện phân phối công khai. Cả 35 ảnh nguồn vẫn **chờ bằng chứng cấp quyền phân phối lại**: có xác nhận riêng của chủ project, nhưng chưa có nội dung/link cấp phép trong workspace; không khẳng định có giấy phép mở. Xem [IMAGE_SOURCE_APPROVAL.md](IMAGE_SOURCE_APPROVAL.md) và [IMAGE_SOURCES_USED.md](IMAGE_SOURCES_USED.md). Bảng [IMAGE_CANDIDATES.md](IMAGE_CANDIDATES.md) là lịch sử B1, không phải mapping B2 hiện hành.

15 ảnh B3 dùng `source_type=project_ai`, không có URL agni.vn; loader hiển thị nguồn bằng văn bản và giữ trọn ảnh bằng `object-fit: contain`. Không sửa nội dung ảnh gốc, công thức hoặc 35 mục B2. Chủ project chấp nhận ảnh minh họa có khác biệt với dataset ở ID 20, 21, 32, 41, 48; ID 2 có ngoại lệ phù hợp tên món. Chi tiết và hướng dẫn kiểm tra lại điện thoại ở [B3_AI_IMAGE_IMPORT.md](B3_AI_IMAGE_IMPORT.md). Xác nhận Wi-Fi B2 ở trên không được tự coi là đã kiểm thử lại B3 trên điện thoại vật lý.

Kiểm thử tự động B3 ngày 01/11/2026: **124 passed, 0 failed, 0 skipped, 1 warning trong 60,98 giây**; JUnit `statics/runtime/b3-pytest.xml`. Chrome thật kiểm tra 1280/390/320 px, nguồn ảnh riêng/ngoài, cả 50 ID ở component ảnh, tìm/gợi ý/chi tiết, Back/reload và fallback. Warning vẫn là deprecation Starlette/TestClient với `httpx`. Không chạy benchmark hoặc thay bằng chứng thực nghiệm cũ.
