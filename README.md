# Hôm nay ăn gì? — Demo unified v3

Website gợi ý món ăn với kiến trúc **Browser → FastAPI → TCP Client → TCP Server → MySQL**. Repository này dùng unified schema v3 và bộ dữ liệu demo đóng gói; không chứa database runtime, mật khẩu, tài khoản người dùng thật hoặc bài Thành quả cá nhân.

> Đây là cấu hình demo cô lập. Unified repository chỉ chấp nhận MySQL ở loopback và tên database kết thúc bằng _test. Không trỏ demo vào database production hoặc database có dữ liệu cần giữ.

## Chức năng

- **Khám phá:** tìm kiếm món, xem công thức và ảnh.
- **Tủ lạnh:** chọn nguyên liệu để tìm/gợi ý món.
- **Mâm cơm:** tạo mâm theo bộ lọc; tính khẩu phần và danh sách đi chợ khi dữ liệu cấu trúc cho phép.
- **Thành quả:** đăng ảnh món đã nấu, xem và bình luận.
- **Tài khoản:** đăng ký, đăng nhập và hồ sơ User.
- **Admin:** quản lý món, nguyên liệu và bài Thành quả.
- **B0/P1:** xếp hạng gợi ý hiện có; Meal Plan v1/v2 chạy qua TCP.

Dữ liệu SQL demo gồm **201 món công khai, 271 nguyên liệu, 1.735 dòng nguyên liệu, 803 bước nấu, 481 liên kết nhãn và 120 bản ghi ảnh món**. Seed không chứa tài khoản, lịch sử chỉnh sửa, món đã xóa hoặc bài/bình luận Thành quả. Có 152 file ảnh được đóng gói trong statics/demo/recipe-images/; seed hiện tạo 120 bản ghi ảnh món. ảnh fallback nằm trong source/web/static/images/recipes/. Ảnh upload và Thành quả phát sinh khi chạy được lưu dưới statics/runtime/, không thuộc dữ liệu seed.

## Kiến trúc TCP

    Browser → FastAPI gateway → TCP Client (socket) → TCP Server → MySQL

Browser gọi FastAPI bằng HTTP. Gateway chuyển nghiệp vụ qua TCP client; browser không truy cập MySQL và FastAPI không chạy trực tiếp thuật toán gợi ý. TCP client là module được FastAPI gọi, không cần chạy thành dịch vụ riêng.

Protocol hiện tại là version 1: JSON UTF-8, request_id, header độ dài 4 byte big-endian và body tối đa 65.536 byte. Các operation gồm PING, danh mục nguyên liệu, chi tiết công thức, tìm kiếm, RECOMMEND, Meal Plan, tài khoản, Admin và Thành quả. B0 đếm nguyên liệu bắt buộc khớp; P1 dùng điểm coverage/input-use. Chi tiết hợp đồng nằm trong [tài liệu tìm kiếm](docs/V1_2_SEARCH.md), [Meal Plan qua web](docs/MEAL_PLAN_WEB.md) và [Meal Plan qua TCP](docs/MEAL_PLAN_TCP.md).

## Yêu cầu

- Windows 10/11.
- Python 3.11 trở lên; khuyến nghị Python 3.13.
- MySQL Server 8.0.16 trở lên và MySQL Workbench (hoặc client SQL tương đương).
- Git. Chrome/Edge chỉ cần để chạy browser tests.

## Clone và cài đặt

Thay URL_REPOSITORY bằng URL repository bạn được cung cấp:

    git clone URL_REPOSITORY GoiYMonAn-Main-Publish
    cd GoiYMonAn-Main-Publish
    py -3.13 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Nếu py -3.13 không có, cài Python 3.13 hoặc dùng python -m venv .venv với Python 3.11+. Chạy lệnh từ thư mục gốc repository.

## Tạo database demo và nhập dữ liệu

Cài MySQL Server trên máy demo và khởi động dịch vụ. Tạo một database mới, rỗng, chỉ dành cho demo. Tên phải kết thúc bằng _test; ví dụ dưới đây dùng goiy_demo_v3_test. Không chạy lại import trên database đã có dữ liệu.

Trong MySQL Workbench, kết nối bằng tài khoản quản trị MySQL cục bộ và chạy đoạn SQL sau. Thay placeholder mật khẩu bằng mật khẩu riêng của máy; không đưa mật khẩu thật vào README, Git hoặc chat:

    CREATE DATABASE goiy_demo_v3_test
      CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

    CREATE USER 'goiy_demo_app'@'127.0.0.1'
      IDENTIFIED BY 'REPLACE_WITH_A_LOCAL_PASSWORD';
    GRANT SELECT, INSERT, UPDATE, DELETE
      ON goiy_demo_v3_test.* TO 'goiy_demo_app'@'127.0.0.1';

Tiếp tục trong Workbench, đặt goiy_demo_v3_test làm schema mặc định, rồi mở và chạy lần lượt đúng hai file sau trên schema mới:

1. [unified_schema.sql](source/database/unified_schema.sql) — tạo các bảng unified v3.
2. [unified_v3_demo_seed.sql](source/database/unified_v3_demo_seed.sql) — nạp catalog, quan hệ, bước nấu, nhãn và metadata ảnh demo.

Các file này không tự tạo database và seed chỉ dành cho schema mới, rỗng. Không dùng mysql_seed.sql hoặc mysql_expanded_seed.sql để cài unified v3; đó là fixture của kiến trúc cũ. Các migration legacy/v2 không thuộc quy trình cài mới này.

Sau khi import, có thể kiểm tra bằng Workbench:

    USE goiy_demo_v3_test;
    SELECT COUNT(*) AS recipes,
           SUM(is_public = 1 AND deleted_at IS NULL) AS public_recipes
    FROM recipes;
    SELECT COUNT(*) AS ingredients FROM ingredients;
    SELECT COUNT(*) AS recipe_ingredient_lines FROM recipe_ingredients;

Kết quả seed dự kiến: 201 món tổng cộng/công khai, 271 nguyên liệu, 1.735 dòng liên kết nguyên liệu, 803 bước nấu, 481 liên kết nhãn và 120 bản ghi ảnh. Không có tài khoản Admin/User được seed.

## Cấu hình và khởi chạy

Tạo cấu hình cục bộ từ mẫu, chỉ khi chưa có file .env:

    if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
    notepad .env

Điền thông tin kết nối database demo vừa tạo:

- UNIFIED_MYSQL_HOST=127.0.0.1
- UNIFIED_MYSQL_PORT=3306 (hoặc cổng MySQL bạn cài)
- UNIFIED_MYSQL_USER=goiy_demo_app
- UNIFIED_MYSQL_PASSWORD: mật khẩu cục bộ đã đặt khi tạo tài khoản.
- UNIFIED_MYSQL_DATABASE=goiy_demo_v3_test
- ADMIN_USERNAME và ADMIN_PASSWORD: tài khoản Admin riêng cho bản demo trên máy này.
- WEB_HOST=127.0.0.1, WEB_PORT=8000, TCP_HOST=127.0.0.1, TCP_PORT=9000.

Các placeholder phải được thay trước khi chạy. Không dùng lại mật khẩu từ môi trường khác và không chia sẻ .env. Launcher sinh hash PBKDF2 và session secret trong bộ nhớ; mật khẩu Admin không được ghi vào MySQL hoặc log.

Khởi động cả TCP Server và FastAPI bằng launcher:

    .\start_demo.bat

Launcher kiểm tra cấu hình/database, rồi chạy một cặp TCP/FastAPI. Nó không cài hoặc khởi động MySQL, không tạo/reset database và không dừng tiến trình khác. Nếu cổng 8000 hoặc 9000 đang bị chiếm, launcher dừng an toàn; hãy xác định dịch vụ đang dùng cổng trước khi xử lý. Để dừng stack do launcher chạy, nhấn Ctrl+C trong cửa sổ đó.

- User: http://127.0.0.1:8000/
- Admin: http://127.0.0.1:8000/admin
- Health: http://127.0.0.1:8000/api/health

WEB_HOST mặc định chỉ cho phép truy cập từ máy local. Để demo với thiết bị tin cậy cùng mạng LAN, đặt WEB_HOST=0.0.0.0 trong .env, cho phép cổng 8000 trên Windows Firewall mạng Private nếu cần, rồi mở http://IPV4-CUA-MAY:8000/. TCP và MySQL vẫn phải giữ ở loopback; không mở chúng ra LAN/Internet.

## Kiểm thử

Cài dependencies trước. Lệnh sau chạy suite hiện có:

    .\.venv\Scripts\python.exe -m pytest

Một số kiểm thử tích hợp cần MySQL TEST_ONLY; browser tests có thể cần Chromium/Node tùy test. Chỉ chạy test ghi/destructive trên database TEST_ONLY riêng, không dùng database demo có dữ liệu cần giữ.

## File dữ liệu và tài liệu

- source/database/unified_schema.sql: schema v3 cho database mới.
- source/database/unified_v3_demo_seed.sql: dữ liệu demo unified v3.
- statics/demo/recipe-images/: ảnh món gắn trong seed; giữ cùng repository để ảnh không bị thiếu.
- source/web/static/images/recipes/placeholder.svg: ảnh fallback.
- data/*.json: metadata phân loại/phục vụ Meal Plan hiện tại.
- .env.example: tên biến cấu hình, chỉ chứa giá trị mẫu.
- start_demo.bat và scripts/run_demo.py: launcher cho TCP Server + FastAPI.

Các tài liệu [thiết kế unified v3](docs/unified-schema-v3-design.md), [nguồn ảnh](docs/IMAGE_SOURCES_USED.md) và [mục lục tài liệu](docs/README.md) bổ sung chi tiết. Tài liệu v1/v2, migration và báo cáo thực nghiệm là hồ sơ lịch sử; chúng không phải các bước cài đặt unified v3 mới. Không chạy các SQL seed/migration cũ để tạo database demo này.
