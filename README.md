# Hôm nay ăn gì? — bản demo unified v3

Website gợi ý món ăn với kiến trúc **Browser → FastAPI → TCP Server → MySQL**. Repository gồm schema v3, catalog demo công khai và ảnh món ăn. Không đóng gói database runtime, tài khoản thật hay bài đăng Thành quả cá nhân.

## Chức năng

- User: Khám phá/tìm kiếm, Tủ lạnh, Mâm cơm, tài khoản và Thành quả.
- Admin: quản lý món, nguyên liệu và bài Thành quả.
- Gợi ý B0/P1 và Meal Plan v1/v2 qua TCP JSON framing.

## Yêu cầu

- Windows 10/11, Python 3.11 trở lên (khuyến nghị 3.13), Git.
- MySQL 8.0.16 trở lên và MySQL client `mysql.exe`.
- Web mặc định ở cổng 8000, TCP nội bộ ở cổng 9000. Cổng MySQL đặt trong `.env` (thường là 3306).

## Clone và cài Python

```powershell
git clone <URL-repository>
cd GoiYMonAn
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Tạo database demo riêng

Chạy các lệnh sau bằng tài khoản quản trị MySQL trên một instance MySQL dùng cho demo. Chọn mật khẩu cục bộ riêng; không dùng credential từ máy khác. Database phải kết thúc bằng `_test` vì ứng dụng v3 chỉ chấp nhận database TEST_ONLY.

```sql
CREATE DATABASE goiy_demo_v3_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER 'goiy_demo_app'@'127.0.0.1' IDENTIFIED BY 'REPLACE_WITH_A_LOCAL_PASSWORD';
GRANT ALL PRIVILEGES ON goiy_demo_v3_test.* TO 'goiy_demo_app'@'127.0.0.1';
```

Import schema rồi seed vào database trống:

```powershell
Get-Content -Raw .\source\database\unified_schema.sql | mysql --default-character-set=utf8mb4 -h 127.0.0.1 -P 3306 -u goiy_demo_app -p goiy_demo_v3_test
Get-Content -Raw .\source\database\unified_v3_demo_seed.sql | mysql --default-character-set=utf8mb4 -h 127.0.0.1 -P 3306 -u goiy_demo_app -p goiy_demo_v3_test
```

Seed chỉ gồm catalog công khai: **201 món, 271 nguyên liệu, 1.735 dòng nguyên liệu, 803 bước nấu, 481 nhãn liên kết và 152 ảnh công thức**. Món ẩn/đã xóa, tài khoản, lịch sử chỉnh sửa và bài/bình luận Thành quả cá nhân không được xuất. Người dùng có thể đăng ký và tạo nội dung mới trong database demo riêng.

Ảnh công thức được đóng gói trong `statics/demo/recipe-images/`; ảnh tĩnh minh họa nằm trong `source/web/static/images/recipes/`. Ảnh upload mới và ảnh Thành quả mới được lưu cục bộ dưới `statics/runtime/` (đã được Git ignore).

## Cấu hình và khởi chạy

```powershell
Copy-Item .env.example .env
notepad .env
```

Điền host/port, database, user/password MySQL demo và chọn username/mật khẩu Admin cục bộ. Đặt `UNIFIED_MYSQL_DATABASE=goiy_demo_v3_test`; đặt `WEB_PORT=8000`, `TCP_PORT=9000`. Không dùng mật khẩu thật từ môi trường khác. `.env` bị ignore. Launcher tạo hash PBKDF2 trong bộ nhớ và không ghi mật khẩu vào log.

```powershell
.\start_demo.bat
```

- User: <http://127.0.0.1:8000>
- Admin: <http://127.0.0.1:8000/admin>

`start_demo.bat` không khởi động, dừng hoặc reset MySQL. Nếu cổng 8000/9000 bận, launcher dừng và không tắt tiến trình khác. Dừng cặp dịch vụ demo bằng `Ctrl+C` trong cửa sổ launcher.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Một số test cần cấu hình MySQL TEST_ONLY hoặc Chromium/Node. Không trỏ test ghi/destructive vào database có dữ liệu cần giữ.

## Tệp dữ liệu và bảo mật

- `source/database/unified_schema.sql`: schema thống nhất v3 cho database mới.
- `source/database/unified_v3_demo_seed.sql`: catalog demo đã lọc; chỉ import vào schema trống.
- `data/*.json`: metadata phân loại cần thiết cho các chức năng Meal Plan tương thích.
- `.env.example`: tên biến và giá trị mẫu, không chứa credential thật.
- `.env`, `.env.admin.local`, runtime MySQL, log, cache và upload không thuộc repository.
- `mysql_seed.sql` và `mysql_expanded_seed.sql` là fixture của kiến trúc cũ, không dùng để nạp unified v3.

Tài liệu schema và ảnh: `docs/unified-schema-v3-design.md`, `docs/IMAGE_SOURCES_USED.md`, `docs/MEAL_PLAN_*` và `docs/V1_2_SEARCH.md`.
