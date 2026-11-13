# Hướng dẫn legacy và launcher local

Tài liệu dưới đây giữ cách chạy cũ cho môi trường đã có dữ liệu.
Khi clone mới, dùng [DEMO_FRESH_CLONE.md](DEMO_FRESH_CLONE.md).
Các lệnh bên dưới vẫn chạy từ gốc repository.

# Hôm nay ăn gì? — TCP Client–Server, UI v1.2.3

> Demo công khai mới có **216 món ăn + 10 đồ uống**, catalog và ảnh được đóng gói
> trong `data/demo/`. Khi clone mới, dùng [hướng dẫn demo unified](../docs/DEMO_FRESH_CLONE.md)
> và `.env.demo.example`. Các bước seed 50 món phía dưới là hướng dẫn legacy.

## Bản demo unified v3 hiện tại (Windows)

Khởi chạy website bằng `start_demo.bat` ở thư mục gốc. Launcher dùng database TEST_ONLY
`goiy_v3_quality_final_20261110_test` trên MySQL `127.0.0.1:63900`, FastAPI cố định ở
cổng `8000` và TCP Server cố định ở `127.0.0.1:9000`. Nó không tạo hoặc reset database;
nếu cổng đang thuộc dịch vụ khác, launcher dừng an toàn và không tự tắt tiến trình đó.

- User: <http://127.0.0.1:8000/>
- Admin: <http://127.0.0.1:8000/admin>
- Để dừng stack do launcher khởi chạy, nhấn `Ctrl+C` trong cửa sổ `start_demo.bat`.
- FastAPI bind `0.0.0.0:8000` để thiết bị cùng mạng có thể truy cập bằng IPv4 Wi-Fi của máy.
  TCP và MySQL chỉ bind loopback. Nếu Windows Firewall chặn máy khác trong mạng Private,
  chạy một lần trong PowerShell mở bằng quyền Administrator:

  ```powershell
  New-NetFirewallRule -DisplayName 'GoiYMonAn Demo Web 8000' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -Profile Private -RemoteAddress LocalSubnet
  ```

  Lệnh này chỉ cho phép cổng web trên mạng Private từ LocalSubnet.

Đồ án môn Lập trình mạng bằng Python, phục vụ học tập và demo. Phiên bản giao diện **v1.2.3** có **50 món, 50 ảnh minh họa riêng và 150 WebP** (320/640/960px). Có hai chế độ: gợi ý từ nguyên liệu và tìm món theo tên khi chưa chọn nguyên liệu. Kết quả, bộ lọc và trang được khôi phục khi Back/reload.

```text
Browser → FastAPI gateway → TCP Client (socket) → TCP Server → MySQL
CLI TCP Client ────────────────────────────────→ TCP Server
```

TCP Client là module được gateway gọi, không phải một dịch vụ phải khởi chạy riêng. Browser dùng HTTP để gọi FastAPI; FastAPI chuyển yêu cầu qua socket TCP thật, không truy cập database hoặc chạy ranking trực tiếp. Protocol **version 1** dùng JSON UTF-8, header độ dài **4 byte big-endian**, body tối đa **65.536 byte** và UUID `request_id`.

| TCP operation | Mục đích |
|---|---|
| `PING` | Kiểm tra server và phiên bản dataset |
| `LIST_INGREDIENTS` | Tìm/liệt kê nguyên liệu |
| `GET_RECIPE` | Xem công thức theo ID; ID không tồn tại trả `NOT_FOUND` |
| `RECOMMEND` | Gợi ý theo nguyên liệu có sẵn, loại trừ và thời gian |
| `SEARCH_RECIPES` | Tìm tên có/không dấu, lọc và phân trang trên backend |

- B0 (`baseline`): số nguyên liệu bắt buộc khớp.
- P1 (`proposed`): `0.7 * coverage + 0.3 * input_use`.
- Giao diện mặc định dùng P1, có trang chi tiết công thức và trạng thái tải/lỗi/rỗng.

v1.2 bổ sung chế độ **Tìm món theo tên** qua TCP `SEARCH_RECIPES` và HTTP `POST /api/search`: tìm có dấu/không dấu không cần chọn nguyên liệu, lọc thời gian/loại trừ/số nguyên liệu bắt buộc thiếu, phân trang và khôi phục kết quả khi Back/reload. Chế độ RECOMMEND và B0/P1 giữ nguyên. Xem [hợp đồng, giới hạn và hướng dẫn kiểm tra v1.2](../docs/V1_2_SEARCH.md). Không cần nạp lại database để dùng tính năng này.

Ảnh được liên kết bằng `recipe_id` trong manifest frontend: 35 ảnh B2 từ agni.vn và 15 ảnh AI B3 do chủ project cung cấp, không hotlink hoặc sửa schema MySQL. SVG placeholder vẫn được giữ khi ảnh tải lỗi. Nguồn/giới hạn của ảnh ở [IMAGE_SOURCES_USED.md](../docs/IMAGE_SOURCES_USED.md). Xem [mục lục tài liệu](../docs/README.md) để phân biệt hướng dẫn hiện tại và lịch sử báo cáo.

## 1. Yêu cầu

- **Khuyến nghị Python 3.13**; môi trường đã kiểm thử dùng **3.13.7 trên Windows**. Dependencies yêu cầu tối thiểu Python 3.11, nhưng các phiên bản Python khác chưa được xác minh trong project này.
- MySQL 8.0 trở lên; môi trường đã kiểm tra dùng **8.0.43**. Cần MySQL Workbench hoặc công cụ chạy SQL tương đương.
- Git và Internet để clone/cài dependency.
- Chạy lệnh từ thư mục gốc repository. Ví dụ dưới đây dùng PowerShell trên Windows.
- Chrome hoặc Edge và Node 22+ chỉ cần nếu muốn chạy browser test; không cần để khởi động ứng dụng. Chỉ kiểm thử viewport không thay thế kiểm tra điện thoại thật.

## 2. Clone và cài dependency

Nhánh mặc định `main` chứa phiên bản demo UI v1.2.3. Clone repository để lấy bản demo hiện tại:

```powershell
git clone https://github.com/lduy1611/GoiYMonAn-TCP-Client-Server.git
cd GoiYMonAn-TCP-Client-Server
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Nếu không có Python Launcher `py`, dùng `python -m venv .venv` sau khi kiểm tra `python --version`. Các lệnh dùng trực tiếp interpreter trong venv, không cần activate hoặc đổi execution policy.

`requirements.txt` chứa dependency chạy ứng dụng, pytest/httpx cho kiểm thử và matplotlib cho các script vẽ biểu đồ từ CSV. Cài dependency không chạy SQL hoặc benchmark.

## 3. Nạp dữ liệu MySQL cho lần cài mới

**Chỉ thực hiện trên database mới dành riêng cho project.** Không chạy lại trên database có dữ liệu cần giữ: `mysql_seed.sql` và utility migration SQLite → MySQL có lệnh `DELETE` trước khi nạp fixture.

Trong Workbench, dùng **tài khoản quản trị/import**, mở từng file SQL từ thư mục vừa clone và thực thi toàn bộ file theo đúng thứ tự. Kiểm tra thành công trước bước tiếp theo. Không dùng cú pháp chuyển hướng `< file.sql` của CMD trực tiếp trong PowerShell:

| Thứ tự | File | Vai trò |
|---|---|---|
| 1 | [database.sql](../source/database/database.sql) | Tạo database `goiy_mon_an` và 5 bảng |
| 2 | [mysql_seed.sql](../source/database/mysql_seed.sql) | Xóa dữ liệu cũ trong các bảng, nạp fixture 15 nguyên liệu, 10 món, 29 quan hệ |
| 3 | [mysql_expanded_seed.sql](../source/database/mysql_expanded_seed.sql) | Bổ sung nguyên liệu 16–50, món 11–50 và quan hệ; phiên bản `vi-v2-50-recipes` |
| 4 | [mysql_recipe_instructions_update.sql](../source/database/mysql_recipe_instructions_update.sql) | Hoàn thiện hướng dẫn món 1–10; phiên bản cuối `vi-v2-50-recipes-r1` |

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

Sau khi nạp, ứng dụng chỉ dùng tài khoản `goiy_app` trong `.env`, không dùng tài khoản quản trị. Nếu MySQL báo `Access denied`, kiểm tra mật khẩu và host được cấp quyền cho tài khoản; không thêm quyền ghi cho runtime chỉ để vượt lỗi import. Nếu database đã có đủ dữ liệu, bỏ qua cả bước import và tạo tài khoản đã tồn tại, chỉ kiểm tra các truy vấn trên.

## 4. Cấu hình

Chỉ copy nếu chưa có `.env`; giữ nguyên cấu hình cục bộ đã tồn tại:

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
```

Sửa `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` trong `.env` cho khớp MySQL. Không commit `.env` hoặc mật khẩu thật; `.env.example` chỉ chứa giá trị minh họa.

TCP Server nạp `.env` tại gốc project **trước khi** đọc `TCP_LOG_PATH` và cấu hình khởi động. Thứ tự ưu tiên: **biến môi trường process → `.env` → giá trị mặc định**. Repository MySQL cũng đọc cấu hình MySQL từ `.env`. Web gateway và CLI không tự đọc `.env`; cần đặt host/port hoặc truyền tham số như dưới đây.

Mặc định mới là `statics/runtime/tcp_server.jsonl`; thư mục cha tự tạo khi server ghi log đầu tiên. Đường dẫn tương đối tính từ thư mục đang chạy, vì vậy luôn chạy từ gốc repository. Nếu `.env` cũ còn trỏ vào `statics/results/`, đặt `$env:TCP_LOG_PATH` như Terminal 1 để ghi đè; không cần và không được tự động ghi đè cấu hình cá nhân.

## 5. Chạy chương trình

Terminal 1 — TCP Server, tại gốc repository, giữ terminal đang chạy:

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

Trong một terminal khác có thể kiểm tra: `Invoke-RestMethod http://127.0.0.1:8000/api/health`. Trên Web, tìm `pho` không cần chọn nguyên liệu; chuyển sang gợi ý, chọn Trứng/Cà chua, mở công thức rồi Back/reload để kiểm tra kết quả và ảnh.

Terminal 3 — CLI TCP, tại gốc repository. CLI gọi thẳng TCP Server, không cần FastAPI hoặc trình duyệt; có thể dừng FastAPI và chạy hai lệnh này để demo giao tiếp TCP độc lập:

```powershell
.\.venv\Scripts\python.exe -m source.client.cli --host 127.0.0.1 --port 9000 --op PING
.\.venv\Scripts\python.exe -m source.client.cli --host 127.0.0.1 --port 9000 --op LIST_INGREDIENTS
.\.venv\Scripts\python.exe -m source.client.cli --help
```

Nếu HTTP trả 503, kiểm tra TCP Server, host/port giữa hai process, cấu hình và quyền MySQL. Nếu cổng bận, chọn cổng TCP khác ở cả hai terminal và `--port` của CLI.

Nếu đổi TCP port, đồng bộ Terminal 1, Terminal 2 và `--port` của CLI. CLI nhận JSON qua `--payload`; schema và ví dụ gọi TCP bằng Python có trong [hợp đồng tìm kiếm](../docs/V1_2_SEARCH.md). `PING` và `LIST_INGREDIENTS` ở trên không cần xử lý dấu nháy JSON của PowerShell.

Log chạy mới ở runtime, không cần đọc hoặc sửa `statics/results/tcp_server.jsonl` để khởi động. Log thực nghiệm cũ vẫn được giữ nguyên và theo dõi trong Git ở giai đoạn này; chưa xóa hay bỏ theo dõi.

Demo điện thoại cùng Wi-Fi: thay host của Uvicorn bằng `--host 0.0.0.0`, mở `http://<IPv4-LAN-laptop>:8000/`. Nếu cần, cho phép Python qua firewall mạng Private. Giữ TCP/MySQL ở máy chủ, không mở hai cổng đó ra Internet.

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

**Lần kiểm thử mới nhất sau hoàn thiện hướng dẫn/log, ngày 01/11/2026: 128 passed, 0 failed, 0 skipped, 1 warning trong 64,86 giây.** Có thêm 4 test cấu hình log: giá trị mặc định, `.env`, ưu tiên biến process và tắt dotenv; mỗi test dùng project/`.env` tạm, không đọc `.env` cá nhân hoặc kết nối MySQL. Nhóm log/khởi động/TCP liên quan đạt **33 passed, 0 failed, 0 skipped, 0 warnings**. JUnit cục bộ ở `statics/runtime/demo-prepare-pytest.xml`, không phân phối qua Git. Warning của full suite là deprecation Starlette/TestClient với `httpx`, không phải test thất bại.

Mốc B2+B3 ngày **01/11/2026** giữ nguyên kết quả **124 passed, 0 failed, 0 skipped, 1 warning**. Bản xuất độc lập đã chạy đủ 124 test trong 52,25 giây bằng môi trường Python hiện có, cấu hình MySQL truyền qua môi trường; không cần ảnh gốc hoặc runtime cũ. Chrome thật kiểm tra 1280/390 px và tràn ngang 320 px, tìm/gợi ý/chi tiết/Back/reload/fallback. Xem [chi tiết B3](../docs/B3_AI_IMAGE_IMPORT.md).

Đã kiểm tra thực tế các entrypoint trong hướng dẫn trên môi trường hiện có, dùng cổng tạm: `python -m source.server.main`, Uvicorn, CLI `PING`/`LIST_INGREDIENTS`, trang chủ, HTTP health và tìm kiếm HTTP → TCP → MySQL đều đạt. Các process tạm đã được dừng; không import SQL/seed, migration hoặc chạy benchmark trong bước kiểm tra này.

Kết quả này không có nghĩa mọi máy clone đều chạy đủ bộ test: browser/MySQL tests có thể skip khi thiếu môi trường. Chưa kiểm chứng cài dependencies và import bốn SQL trên máy/VM hoàn toàn sạch. Bước nhập MySQL mới là hướng dẫn, không được chạy lại trên database hiện có khi kiểm thử.

### Kết quả kiểm thử lịch sử

Ngày 29/10/2026: full suite **16 passed**; focused MySQL/Web **5 passed**, có warning Starlette/httpx. Đây là số liệu của mốc báo cáo, không thay bằng số test hiện tại. Giữ phân tích và giới hạn thực nghiệm trong [EXPERIMENT_RESULTS.md](EXPERIMENT_RESULTS.md).

## 7. Bằng chứng báo cáo và giới hạn

- Phiên bản demo hiện tại UI v1.2.3 ở nhánh `main`. Commit báo cáo `4a2afc1` và tag `v1.0-report` giữ bản đã nộp ban đầu, không phải bản demo mới nhất.
- [EXPERIMENT_RESULTS.md](EXPERIMENT_RESULTS.md) phân tích thực nghiệm; CSV, JSON audit và biểu đồ ở [statics/results/](../statics/results/).
- E2 cuối: `e2_raw_20261029_114105.csv` và `e2_summary_20261029_114105.csv`, 7.560 dòng raw, 24 summary PASS theo file lưu. Các lần trước, kể cả lần lỗi, được giữ lại.
- E2 đo loopback trên một máy. Script hiện tính cả warmup trong mẫu số throughput; chưa thể diễn giải như throughput chỉ đo pha measured. Log `receive_ms`/`send_ms` hiện bằng 0.
- B0/P1 chưa có nhãn relevance độc lập, P@5/nDCG@5 hoặc đánh giá A1; chưa chứng minh thuật toán nào tốt hơn. Chủ project đã xác nhận thủ công B2 qua điện thoại Wi-Fi; chưa có xác nhận kiểm tra lại B3 trên điện thoại vật lý, bằng chứng Wireshark hoặc tái lập máy hoàn toàn sạch. Kiểm tra chức năng Wi-Fi không phải benchmark LAN.
- Script benchmark, audit và vẽ biểu đồ có thể tạo/ghi đè artifact. Không cần chạy chúng để dùng ứng dụng; không chạy lại trên đường dẫn bằng chứng báo cáo. Các file `.log` lịch sử bị Git bỏ qua: tài liệu chỉ ghi tên và giới hạn bằng chứng khi không phân phối file, không tạo log giả hoặc suy ra đã tái lập.
- `SPEC.md`/`TEST_PLAN.md` được tài liệu cũ nhắc đến nhưng chưa có trong repository. Xem thêm [MIGRATION_REPORT.md](MIGRATION_REPORT.md), [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md), [CHANGES_FROM_SPEC.md](CHANGES_FROM_SPEC.md).

Nếu cần truy xuất bản báo cáo ban đầu, clone tag vào **thư mục riêng** để giữ nguyên bản demo đang dùng:

```powershell
git clone --branch v1.0-report --single-branch https://github.com/lduy1611/GoiYMonAn-TCP-Client-Server.git GoiYMonAn-v1.0-report
cd GoiYMonAn-v1.0-report
```

Clone tag tạo trạng thái detached HEAD tại mốc báo cáo; dùng README đi kèm tag cho phiên bản đó.

## 8. Cấu trúc

```text
source/common/    Framing và validation protocol
source/server/    TCP Server, handler, repository, B0/P1
source/client/    TCP client và CLI
source/web/       FastAPI, templates, JavaScript, CSS
source/database/ Schema, seed, utility migration
tests/           Unit/integration tests
scripts/         Audit, benchmark, vẽ biểu đồ
docs/            Mục lục, hướng dẫn v1.2 và nguồn ảnh B2/B3
data/            Manifest fixture; SQLite cục bộ không theo dõi bằng Git
statics/results/ Bằng chứng thực nghiệm đã lưu
statics/runtime/ Log chạy mới, bị Git bỏ qua
```

Lộ trình đọc cho giảng viên: **README này → [mục lục tài liệu](../docs/README.md) → [giao thức/tìm kiếm hiện tại](../docs/V1_2_SEARCH.md) → [bằng chứng báo cáo](EXPERIMENT_RESULTS.md)**. Tài liệu migration và khảo sát ảnh là hồ sơ phát triển, không phải các bước bắt buộc để demo.


## Unified schema v3 (isolated TEST_ONLY)

The v3 repository is opt-in and is exercised against a separate MySQL database. Do not set these values in the production service environment. Point both processes at a disposable, already prepared `*_test` database; keep the old database intact for rollback.

TCP Server terminal:

```powershell
$env:TCP_DB_SCHEMA = 'unified_v3'
$env:MYSQL_DATABASE = 'goiy_v3_test'
$env:TCP_HOST = '127.0.0.1'
$env:TCP_PORT = '9012'
$env:TCP_LOG_PATH = 'statics/runtime/tcp_server_v3_test.jsonl'
.\.venv\Scripts\python.exe -m source.server.main
```

FastAPI terminal:

```powershell
$env:UNIFIED_SCHEMA_MODE = '1'
$env:MYSQL_DATABASE = 'goiy_v3_test'
$env:TCP_HOST = '127.0.0.1'
$env:TCP_PORT = '9012'
.\.venv\Scripts\python.exe -m uvicorn source.web.main:app --host 127.0.0.1 --port 8012
```

Open `http://127.0.0.1:8012/`. This mode keeps the existing Browser -> FastAPI -> TCP -> MySQL architecture and the TCP protocol. Structured portion calculation uses only numeric ingredient rows with a known unit and base servings; text such as ?to taste? stays incomplete. Unit totals are combined only when ingredient, form, measurement basis, purpose, unit, and required/optional status all match. No unit conversion is inferred.

The default runtime remains the existing schema until a separately approved production cutover. Legacy and v2 compatibility code is still used by that runtime and its regression tests, so it must not be removed yet. The isolated v3 integration test is `tests/test_unified_http_tcp.py`.
