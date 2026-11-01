# GoiYMonAnTCP — Hệ thống gợi ý món ăn theo nguyên liệu

Đồ án TCP Client–Server bằng Python. Chọn nguyên liệu đang có, nguyên liệu loại trừ, thời gian nấu và top K để nhận gợi ý cùng nguyên liệu còn thiếu.

```text
Trình duyệt → FastAPI Web gateway → TCP Server → MySQL
CLI TCP client ───────────────────→ TCP Server
```

Web dùng socket TCP thật, không truy cập database hoặc chạy ranking trực tiếp. Protocol version 1 dùng JSON UTF-8, header độ dài 4 byte big-endian, body tối đa 65.536 byte và UUID request ID. Các operation: `PING`, `LIST_INGREDIENTS`, `GET_RECIPE`, `RECOMMEND`.

- B0 (`baseline`): số nguyên liệu bắt buộc khớp.
- P1 (`proposed`): `0.7 * coverage + 0.3 * input_use`.
- Giao diện mặc định dùng P1, có trang chi tiết công thức và trạng thái tải/lỗi/rỗng.

v1.2 bổ sung chế độ **Tìm món theo tên** qua TCP `SEARCH_RECIPES` và HTTP `POST /api/search`: tìm có dấu/không dấu không cần chọn nguyên liệu, lọc thời gian/loại trừ/số nguyên liệu bắt buộc thiếu, phân trang và khôi phục kết quả khi Back/reload. Chế độ RECOMMEND và B0/P1 giữ nguyên. Xem [hợp đồng, giới hạn và hướng dẫn kiểm tra v1.2](docs/V1_2_SEARCH.md). Không cần nạp lại database để dùng tính năng này.

## 1. Yêu cầu

- Python 3.11 trở lên; bằng chứng kiểm thử hiện có dùng **Python 3.13.7 trên Windows**. Các phiên bản khác chưa được xác minh trong project này.
- MySQL 8.0 trở lên; MySQL Workbench hoặc công cụ chạy SQL tương đương.
- Git và Internet để clone/cài dependency.
- Chạy lệnh từ thư mục gốc repository. Ví dụ dưới đây dùng PowerShell trên Windows.

## 2. Clone và cài dependency

Thay URL ví dụ bằng URL repository thực tế:

```powershell
git clone https://github.com/YOUR_ACCOUNT/GoiYMonAnTCP.git
cd GoiYMonAnTCP
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Nếu không có Python Launcher `py`, dùng `python -m venv .venv` sau khi kiểm tra `python --version`. Các lệnh dùng trực tiếp interpreter trong venv, không cần activate hoặc đổi execution policy.

`requirements.txt` chứa dependency chạy ứng dụng, pytest/httpx cho kiểm thử và matplotlib cho các script vẽ biểu đồ từ CSV. Cài dependency không chạy SQL hoặc benchmark.

## 3. Nạp dữ liệu MySQL cho lần cài mới

**Chỉ thực hiện trên database mới dành riêng cho project.** Không chạy lại trên database có dữ liệu cần giữ: `mysql_seed.sql` và utility migration SQLite → MySQL có lệnh `DELETE` trước khi nạp fixture.

Trong Workbench, dùng tài khoản có quyền tạo schema/nạp dữ liệu; chạy từng file đúng thứ tự và kiểm tra thành công trước bước tiếp theo:

| Thứ tự | File | Vai trò |
|---|---|---|
| 1 | [database.sql](source/database/database.sql) | Tạo database `goiy_mon_an` và 5 bảng |
| 2 | [mysql_seed.sql](source/database/mysql_seed.sql) | Xóa dữ liệu cũ trong các bảng, nạp fixture 15 nguyên liệu, 10 món, 29 quan hệ |
| 3 | [mysql_expanded_seed.sql](source/database/mysql_expanded_seed.sql) | Bổ sung nguyên liệu 16–50, món 11–50 và quan hệ; phiên bản `vi-v2-50-recipes` |
| 4 | [mysql_recipe_instructions_update.sql](source/database/mysql_recipe_instructions_update.sql) | Hoàn thiện hướng dẫn món 1–10; phiên bản cuối `vi-v2-50-recipes-r1` |

Chạy đủ bốn file trên database mới để có **50 nguyên liệu, 50 món và 252 quan hệ**. `schema.sql`/`seed.py` phục vụ SQLite hồi quy, không thuộc chuỗi MySQL. SQLite cục bộ không được Git theo dõi; clone mới không cần file này và không cần chạy utility migration.

Các file MySQL dùng database `goiy_mon_an`. Nếu chọn tên khác, đồng bộ câu `CREATE DATABASE`/`USE` trong các file và `MYSQL_DATABASE` trước khi thực hiện trên môi trường mới.

Xác nhận bằng truy vấn chỉ đọc:

```sql
USE goiy_mon_an;
SELECT value AS dataset_version FROM metadata WHERE `key` = 'dataset_version';
SELECT COUNT(*) AS ingredients FROM ingredients;              -- 50
SELECT COUNT(*) AS recipes FROM recipes;                      -- 50
SELECT COUNT(*) AS recipe_ingredients FROM recipe_ingredients; -- 252
```

Tài khoản runtime chỉ cần `SELECT`. Ví dụ tạo tài khoản mới bằng tài khoản quản trị, thay mật khẩu minh họa bằng mật khẩu riêng trước khi chạy. Nếu tài khoản đã tồn tại, cấu hình bằng Workbench thay vì chạy lại `CREATE USER`:

```sql
CREATE USER 'goiy_app'@'localhost' IDENTIFIED BY 'REPLACE_WITH_YOUR_OWN_PASSWORD';
GRANT SELECT ON goiy_mon_an.* TO 'goiy_app'@'localhost';
```

Không dùng tài khoản runtime chỉ có `SELECT` để nạp SQL. Các bước nạp cần quyền tạo schema/bảng, `INSERT`, `UPDATE`, `DELETE` phù hợp.

## 4. Cấu hình

Chỉ copy nếu chưa có `.env`; giữ nguyên cấu hình cục bộ đã tồn tại:

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
```

Sửa `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` trong `.env` cho khớp MySQL. Không commit `.env` hoặc mật khẩu thật; `.env.example` chỉ chứa giá trị minh họa.

Repository MySQL tự đọc `.env`. Các tùy chọn TCP được đọc từ biến môi trường của process; đặt `$env:TCP_HOST`, `$env:TCP_PORT`, `$env:TCP_LOG_PATH` trước khi chạy để cấu hình nhất quán. Web gateway không tự đọc `.env`.

## 5. Chạy chương trình

Terminal 1 — TCP Server, giữ terminal đang chạy:

```powershell
$env:TCP_HOST = '127.0.0.1'
$env:TCP_PORT = '9000'
$env:TCP_LOG_PATH = 'statics/runtime/tcp_server.jsonl'
.\.venv\Scripts\python.exe -m source.server.main
```

Terminal 2 — Web gateway, cũng tại thư mục gốc:

```powershell
$env:TCP_HOST = '127.0.0.1'
$env:TCP_PORT = '9000'
.\.venv\Scripts\python.exe -m uvicorn source.web.main:app --host 127.0.0.1 --port 8000
```

Mở <http://127.0.0.1:8000/>; API health: <http://127.0.0.1:8000/api/health>. Dừng từng process bằng `Ctrl+C`.

Terminal 3 — CLI TCP:

```powershell
.\.venv\Scripts\python.exe -m source.client.cli --host 127.0.0.1 --port 9000 --op PING
.\.venv\Scripts\python.exe -m source.client.cli --host 127.0.0.1 --port 9000 --op LIST_INGREDIENTS
```

Nếu HTTP trả 503, kiểm tra TCP Server, host/port giữa hai process, cấu hình và quyền MySQL. Nếu cổng bận, chọn cổng TCP khác ở cả hai terminal và `--port` của CLI.

Đường dẫn log trên tách log mới khỏi bằng chứng báo cáo. Nếu không đặt `TCP_LOG_PATH` trước khi chạy server/pytest, code mặc định ghi nối vào `statics/results/tcp_server.jsonl` đang được Git theo dõi.

## 6. Kiểm thử

Từ thư mục gốc, sau khi cài dependency. Test tự tạo server trên cổng tạm; không cần khởi chạy TCP/Web riêng:

```powershell
$env:TCP_LOG_PATH = 'statics/runtime/pytest_tcp_server.jsonl'
.\.venv\Scripts\python.exe -m pytest tests --import-mode=importlib -p no:cacheprovider -q -rs
```

`--import-mode=importlib` chuẩn hóa import khi thu thập test. `-p no:cacheprovider` tắt plugin tạo `.pytest_cache`; `-p no` đơn lẻ không có nghĩa tắt toàn bộ plugin. `-rs` hiển thị lý do skip.

Chỉ chạy MySQL integration:

```powershell
$env:TCP_LOG_PATH = 'statics/runtime/pytest_mysql_tcp_server.jsonl'
.\.venv\Scripts\python.exe -m pytest tests/test_mysql_integration.py --import-mode=importlib -p no:cacheprovider -q -rs
```

Test MySQL chỉ đọc database đã cấu hình, sẽ **skip** nếu thiếu cấu hình hoặc không kết nối được. Test khác tạo SQLite fixture trong thư mục tạm. Skip không xác nhận MySQL hoạt động.

Log lịch sử ngày 29/10/2026 ghi nhận full suite 16 passed và focused MySQL/Web 5 passed, có warning Starlette/httpx. Đây là kết quả đã lưu, không xác nhận cho máy vừa clone hoặc lệnh mới trên.

## 7. Bằng chứng báo cáo và giới hạn

- Commit báo cáo: `4a2afc1`; tag `v1.0-report` giữ mốc đã nộp. Hướng dẫn cài đặt mới có thể nằm ở commit sau trên `main`.
- [EXPERIMENT_RESULTS.md](EXPERIMENT_RESULTS.md) phân tích thực nghiệm; CSV, JSON audit và biểu đồ ở [statics/results/](statics/results/).
- E2 cuối: `e2_raw_20261029_114105.csv` và `e2_summary_20261029_114105.csv`, 7.560 dòng raw, 24 summary PASS theo file lưu. Các lần trước, kể cả lần lỗi, được giữ lại.
- E2 đo loopback trên một máy. Script hiện tính cả warmup trong mẫu số throughput; chưa thể diễn giải như throughput chỉ đo pha measured. Log `receive_ms`/`send_ms` hiện bằng 0.
- B0/P1 chưa có nhãn relevance độc lập, P@5/nDCG@5 hoặc đánh giá A1; chưa chứng minh thuật toán nào tốt hơn. LAN/mobile, Wireshark và tái lập máy sạch chưa có đủ bằng chứng.
- Script benchmark, audit và vẽ biểu đồ có thể tạo/ghi đè artifact. Không cần chạy chúng để dùng ứng dụng; không chạy lại trên đường dẫn bằng chứng báo cáo. File `.log` bị Git bỏ qua nên clone mới không có các log được tài liệu cũ liên kết tới.
- `SPEC.md`/`TEST_PLAN.md` được tài liệu cũ nhắc đến nhưng chưa có trong repository. Xem thêm [MIGRATION_REPORT.md](MIGRATION_REPORT.md), [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md), [CHANGES_FROM_SPEC.md](CHANGES_FROM_SPEC.md).

## 8. Cấu trúc

```text
source/common/    Framing và validation protocol
source/server/    TCP Server, handler, repository, B0/P1
source/client/    TCP client và CLI
source/web/       FastAPI, templates, JavaScript, CSS
source/database/ Schema, seed, utility migration
tests/           Unit/integration tests
scripts/         Audit, benchmark, vẽ biểu đồ
data/            Manifest fixture; SQLite cục bộ không theo dõi bằng Git
statics/results/ Bằng chứng thực nghiệm đã lưu
statics/runtime/ Log chạy mới, bị Git bỏ qua
```
