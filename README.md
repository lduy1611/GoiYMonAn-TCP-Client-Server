# Hôm nay ăn gì? — Demo TCP Client–Server

Project gợi ý món ăn theo kiến trúc **Browser → FastAPI gateway → TCP Client → TCP Server → MySQL**.
Gateway gọi nghiệp vụ qua socket TCP thật; MySQL và TCP chỉ cần chạy tại máy demo.

Bản công khai có **216 món ăn + 10 đồ uống**, 224 nguyên liệu được tham chiếu,
1.853 dòng nguyên liệu, 847 bước nấu, 174 ảnh upload và 49 ảnh fallback local.
Ba món chưa có ảnh riêng tiếp tục dùng placeholder. Gói không có tài khoản,
password hash, lịch sử chỉnh sửa hoặc nội dung cá nhân của người dùng.

## Chức năng hiện tại

- Khám phá/tìm món, gợi ý theo nguyên liệu và thuật toán B0/P1.
- Lập mâm cơm, bốn mùa, đồ uống, ghim/đổi món, định lượng và danh sách đi chợ.
- Admin quản lý món, đồ uống, nguyên liệu, phân loại và trạng thái kiểm duyệt định lượng.
- Đăng ký/đăng nhập, Thành quả, bình luận và góp ý; Admin quản lý nội dung.
- Protocol JSON UTF-8 version 1, header độ dài 4 byte big-endian, body tối đa 65.536 byte.

## Clone và chạy demo mới

Cần Python 3.11+ (khuyến nghị 3.13), MySQL 8.0.16+ và Git.

```powershell
git clone https://github.com/lduy1611/GoiYMonAn-TCP-Client-Server.git
cd GoiYMonAn-TCP-Client-Server
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

1. Tạo database MySQL **mới, rỗng**, tên kết thúc _test, trên loopback.
2. Dùng MySQL Workbench nhập **chỉ** `data/demo/catalog.sql` vào schema rỗng đó.
   File đã gồm schema; không chạy thêm seed 50 món hoặc seed 201 món cũ.
3. Tạo tài khoản MySQL riêng với `SELECT, INSERT, UPDATE, DELETE` trên schema demo.
4. Chỉ trong clone mới, copy `.env.demo.example` thành `.env`, đặt mật khẩu riêng
   và cấu hình database. Không ghi đè `.env` đã có trên máy đang chạy.
5. Chạy `start_public_demo.bat` hoặc:

   ```powershell
   .\.venv\Scripts\python.exe scripts/run_public_demo.py
   ```

Mở <http://127.0.0.1:8000/>. Launcher portable xác minh checksum gói, sao chép
ảnh còn thiếu vào kho runtime riêng và khởi động web/TCP. Nó không tạo/reset/import
MySQL, không ghi `.env`, không ghi đè ảnh runtime đã có và không tắt dịch vụ khác.
Có thể dùng file cấu hình riêng: `scripts/run_public_demo.py --env-file PATH`.

Xem [hướng dẫn cài mới đầy đủ](docs/DEMO_FRESH_CLONE.md),
[cấu hình mẫu](.env.demo.example) và [manifest dữ liệu/ảnh](data/demo/manifest.json).

## Môi trường local đang chạy

`start_demo.bat`, `scripts/run_demo.py`, các cổng và datadir cũ được giữ nguyên.
Launcher này dành cho môi trường local đã có dữ liệu; không dùng cho clone mới.
`.env.example` vẫn là mẫu legacy; `.env.demo.example` là mẫu cho demo hiện tại.
[Hướng dẫn legacy](docs/LEGACY_SETUP.md) được giữ để tham khảo, không thay thế
hướng dẫn import catalog mới.

## Kiểm thử

Dùng checkout sạch riêng, chưa tạo `.env` và không mang các biến cấu hình
MySQL/TCP của môi trường đang chạy. Không sao chép cấu hình cá nhân sang checkout
kiểm thử. Lệnh dưới đây dành cho checkout đó:

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
```

MySQL integration tự tạo instance/datadir riêng khi đặt `MYSQL_V2_MYSQLD` tới
`mysqld.exe`; browser tests cần Node 22+ và Chrome/Edge. Test
`tests/test_public_demo_mysql.py` nhập toàn bộ SQL công khai trên instance mới,
kiểm tra HTTP → TCP → MySQL, 174 ảnh upload, 49 fallback và Admin.
Không dùng cấu hình database đang chạy để làm môi trường kiểm thử.
Test backup migration lịch sử skip nếu thiếu backup riêng; kiểm thử import
`data/demo/catalog.sql` độc lập và không cần backup của máy tác giả.

## Tài liệu

- [Mục lục](docs/README.md)
- [Meal Plan web](docs/MEAL_PLAN_WEB.md), [TCP](docs/MEAL_PLAN_TCP.md), [linh hoạt](docs/MEAL_PLAN_FLEX.md)
- [Schema unified](docs/unified-schema-v3-design.md)
- [Nguồn ảnh](docs/IMAGE_SOURCES_USED.md)
- [Rà soát hợp nhất main](docs/MAIN_INTEGRATION_REVIEW.md)

Source, tests, tài liệu, cấu hình mẫu và gói công khai được theo dõi bởi Git.
Môi trường ảo, cache, logs, `.env`, datadir MySQL, backups và output kiểm thử giữ local.
