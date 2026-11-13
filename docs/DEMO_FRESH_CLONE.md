# Demo công khai sau khi clone

Gói `data/demo/` chứa 216 món ăn và 10 đồ uống công khai (226 bản ghi),
224 nguyên liệu được tham chiếu, 1.853 dòng nguyên liệu, 847 bước nấu,
49 taxonomy và 174 ảnh upload. Các ảnh fallback cũ ở `source/web/static/`
cũng phải được giữ. `manifest.json` lưu số lượng và SHA-256.

Không có dữ liệu tài khoản, password hash, lịch sử chỉnh sửa, thành quả,
bình luận, góp ý, phiên đăng nhập hoặc bản ghi món ẩn/đã xóa trong gói demo.
Các bảng tương ứng được tạo rỗng. Không có tài khoản Admin dùng chung.

## Cài trên bản clone mới

1. Tạo `.venv` và cài `requirements.txt` như README. Cần MySQL 8.0.16+.
2. Trong MySQL Workbench, dùng tài khoản quản trị để tạo **database mới rỗng**
   `goiy_demo_test`, charset `utf8mb4`. Chọn nó làm default schema.
   Không dùng database hiện có hoặc database demo gốc của máy tác giả.
3. Mở và chạy toàn bộ `data/demo/catalog.sql` trên schema rỗng đó.
   Không chạy chuỗi seed 50 món hay migration legacy cùng gói này.
   SQL có DDL (không rollback hoàn toàn khi lỗi), vì vậy nếu import lỗi,
   giữ schema lỗi để kiểm tra và dùng một schema mới khác để thử lại.
4. Tạo tài khoản MySQL riêng và cấp `SELECT, INSERT, UPDATE, DELETE` trên
   `goiy_demo_test.*`. Chọn mật khẩu riêng, không dùng root cho runtime.
   Đây là quyền cho demo unified có chức năng Admin, đăng ký, góp ý và thành quả.
   Ví dụ trên MySQL mới, thay mật khẩu minh họa bằng mật khẩu riêng:

   ```sql
   CREATE USER 'goiy_demo'@'127.0.0.1' IDENTIFIED BY 'REPLACE_WITH_YOUR_OWN_PASSWORD';
   GRANT SELECT, INSERT, UPDATE, DELETE ON goiy_demo_test.* TO 'goiy_demo'@'127.0.0.1';
   ```
5. Chỉ trên bản clone mới, sao chép `.env.demo.example` thành `.env`, thay
   mật khẩu MySQL và `ADMIN_SESSION_SECRET`. Tạo secret bằng:

   ```powershell
   .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

6. Khởi chạy bản portable bằng `start_public_demo.bat`, hoặc:

   ```powershell
   .\.venv\Scripts\python.exe scripts/run_public_demo.py
   ```

   Launcher kiểm tra checksum, sao chép ảnh còn thiếu vào
   `statics/runtime/public-demo/recipe-images`, giữ nguyên ảnh runtime đã có,
   rồi chạy web/TCP theo cấu hình. Nó không khởi tạo/import MySQL, sửa `.env`
   hoặc tắt dịch vụ khác. Dùng `--env-file PATH` nếu cần cấu hình riêng.
   Có thể đặt `WEB_HOST`, `WEB_PORT`, `TCP_PORT`, `GOIY_DEMO_RUNTIME_DIR`
   trong file cấu hình riêng; không cần đổi cấu hình local đang sử dụng.

7. Nếu muốn chạy hai terminal thay vì launcher portable, trước tiên sao chép
   ảnh vào `statics/runtime/recipe-images/` trên clone mới, rồi chạy từ gốc repo:

   ```powershell
   .\.venv\Scripts\python.exe -m source.server.main
   ```

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn source.web.main:app --host 127.0.0.1 --port 8000
   ```

8. Mở `http://127.0.0.1:8000/`, đăng ký tài khoản riêng. Để dùng Admin,
   quản trị viên MySQL có thể đổi role của đúng tài khoản vừa đăng ký trong
   bảng `users` thành `ADMIN`; đăng xuất/đăng nhập lại rồi mở `/admin`.
   Không đưa tài khoản hoặc mật khẩu đó vào repository. Launcher portable cũng
   hỗ trợ cặp `ADMIN_USERNAME`/`ADMIN_PASSWORD` tùy chọn trong file `.env` riêng,
   giống cơ chế đăng nhập Admin cấu hình trên main; chỉ dùng mật khẩu riêng.

`start_demo.bat` và `scripts/run_demo.py` vẫn phục vụ môi trường cục bộ cũ:
chúng yêu cầu datadir TEST_ONLY đã tồn tại trên máy tác giả và không phải
launcher cho bản clone mới. `.env.example` và chuỗi seed 50 món trong README
là cấu hình legacy. Dùng hướng dẫn và `.env.demo.example` ở đây cho demo mới.
Chế độ unified hiện chỉ chấp nhận MySQL loopback và tên database kết thúc `_test`.

## Kiểm tra

```sql
SELECT COUNT(*) FROM recipes; -- 226, trong đó 216 món ăn và 10 đồ uống
SELECT COUNT(*) FROM recipes WHERE role='drink'; -- 10
SELECT COUNT(*) FROM recipe_images; -- 174
SELECT COUNT(*) FROM users; -- 0 ngay sau import, trước khi đăng ký
```

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_demo_package.py -q
```

Gói có kiểm thử import/end-to-end riêng trong `tests/test_public_demo_mysql.py`.
Đặt `MYSQL_V2_MYSQLD` tới MySQL Server binary để chạy kiểm thử này trên instance
tạm mới; nó không dùng database/cấu hình cá nhân. Nếu chạy script xuất lại,
dùng thư mục đích mới, cung cấp kết nối nguồn và `--image-root` tường minh.
Script chỉ SELECT trong consistent snapshot, không xuất nguyên database,
không ghi đè gói đã có.

Kiểm thử migration từ backup lịch sử là tùy chọn vì backup riêng không thuộc
repository. Khi không có backup, test đó skip; nếu cần chạy, đặt
`GOIY_MIGRATION_TEST_BACKUP` tới file backup đúng SHA-256 mà test yêu cầu.
Backup chỉ được restore vào instance MySQL thử nghiệm do fixture tạo.
