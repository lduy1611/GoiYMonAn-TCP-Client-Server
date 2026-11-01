# v1.2 — Tìm kiếm món ăn qua TCP

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

SessionStorage schema 3 lưu chế độ, query, nguyên liệu, bộ lọc, offset/limit, kết quả/trạng thái lỗi/rỗng, dataset_version và vị trí cuộn. Chữ ký cache bao gồm chế độ và tất cả tham số có ảnh hưởng đến kết quả. Thay query/bộ lọc/chế độ sẽ bỏ kết quả và về trang đầu. Cache lỗi hoặc khác phiên bản dataset không được hiển thị. Cache v1.1.2 được nâng cấp khi khớp chính xác điều kiện cũ. CSS/JS cùng phiên bản URL `ui-1.2.0` để tránh trộn asset cũ.

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

Kết quả thực tế ngày 01/11/2026 trên môi trường hiện tại: **105 passed, 0 failed, 0 skipped, 1 warning trong 43,27 giây**. Warning là deprecation Starlette/httpx có từ trước. Đã chạy Chrome thật ở 1280/390 px và kiểm tra tràn ngang 320 px, các luồng v1.1.2 và tìm kiếm v1.2; test MySQL không bị skip. Browser test kiểm tra console JavaScript, chuột/bàn phím, cache version, tìm có dấu/không dấu/NFD, kết quả không có score, bộ lọc kết hợp, phân trang, Back/reload, cache sai từ khóa/trang và nâng cấp cache v1.1.2. Đây là functional test, không phải benchmark E2.

## Điện thoại qua Wi-Fi

Chạy riêng Web bằng `--host 0.0.0.0`, giữ TCP_HOST=127.0.0.1 và TCP/MySQL trong máy chủ. Điện thoại cùng Wi-Fi mở `http://<IP-LAN-máy-chủ>:8000`. Nếu cần quyền firewall, chỉ cấu hình cho mạng riêng/cổng Web phù hợp. Không cần mở cổng MySQL/TCP cho điện thoại. Các URL API/asset là relative nên dùng cùng host.

Chưa có kết quả kiểm tra điện thoại vật lý trong tài liệu này; viewport Chrome 390/320 px không thay thế được kiểm tra Wi-Fi thực tế.
