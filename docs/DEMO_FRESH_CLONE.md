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
5. Chỉ trên bản clone mới, sao chép `.env.demo.example` thành `.env`, thay
   mật khẩu MySQL và `ADMIN_SESSION_SECRET`. Tạo secret bằng:

   ```powershell
   .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

6. Khôi phục ảnh vào kho runtime mới (không chạy đè kho ảnh đang dùng):

   ```powershell
   New-Item -ItemType Directory -Path statics/runtime/recipe-images
   Copy-Item -Path data/demo/recipe-images/* -Destination statics/runtime/recipe-images/
   ```

7. Chạy hai terminal từ gốc repository:

   ```powershell
   .\.venv\Scripts\python.exe -m source.server.main
   ```

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn source.web.main:app --host 127.0.0.1 --port 8000
   ```

8. Mở `http://127.0.0.1:8000/`, đăng ký tài khoản riêng. Để dùng Admin,
   quản trị viên MySQL có thể đổi role của đúng tài khoản vừa đăng ký trong
   bảng `users` thành `ADMIN`; đăng xuất/đăng nhập lại rồi mở `/admin`.
   Không đưa tài khoản hoặc mật khẩu đó vào repository.

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

Gói đã được đối chiếu checksum ảnh và phạm vi dữ liệu. Việc import/chạy end-to-end
trên MySQL của máy clone vẫn cần xác minh riêng; quá trình dọn Git không ghi vào
MySQL hiện có. Nếu chạy script xuất lại, dùng thư mục đích mới, cung cấp kết nối
nguồn và `--image-root` tường minh. Script chỉ SELECT trong consistent snapshot,
không xuất nguyên database, không ghi đè gói đã có.
