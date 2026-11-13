# MySQL v2: khẩu phần — migration 001

Đây là DDL bổ sung, chưa áp dụng lên database đang dùng. Không có seed, import
công thức hoặc thao tác duyệt thật. Thiết kế gốc: `docs/data-v2/SCHEMA_AND_MIGRATION.md`.

## Phạm vi và điều kiện

- MySQL >= 8.0.16, InnoDB, strict SQL mode; giữ nguyên năm bảng legacy.
- `001_portion_catalog.sql` tạo nguồn/bằng chứng/quyết định duyệt, nguyên liệu/dạng,
  đơn vị, công thức/revision/dòng lượng, chính sách khẩu phần, release và cấu hình.
  Runner tạo riêng `v2_migration_history`; không sửa `metadata.dataset_version`.
- Chưa tạo vùng miền, chế độ ăn, quy đổi đơn vị, tài khoản hoặc nhập bộ thí điểm.
- Chỉ chạy bằng runner. Nó dùng advisory lock, version, SHA-256 SQL (UTF-8, newline LF) và hash
  cấu trúc bảng/trigger; chạy lại đúng bản là no-op, checksum/schema lệch sẽ dừng.
- DDL MySQL tự commit. Lỗi giữa chừng để `FAILED` hoặc `APPLYING`; runner không
  tự xóa bảng, bỏ qua lỗi, sửa marker hoặc tiếp tục một migration dang dở.
- Tài khoản migration cần SELECT, CREATE, INSERT, UPDATE, REFERENCES và TRIGGER
  trên đúng schema; tài khoản runtime chỉ cần SELECT. Không tăng quyền tài khoản
  ứng dụng để thực hiện migration. Không dùng chương trình migrate SQLite/seed cũ.

## Sao lưu và thử phục hồi trước khi duyệt áp dụng

Các lệnh sau là hướng dẫn cho người vận hành, chưa được tự chạy trên database thật.
Chọn đúng host/schema và tài khoản backup; `--password` yêu cầu nhập mật khẩu,
không ghi mật khẩu vào command line hoặc Git. Thay `YOUR_MIGRATION_USER` bằng tài khoản được cấp.

```powershell
New-Item -ItemType Directory -Force statics/runtime/backups | Out-Null
& 'C:/Program Files/MySQL/MySQL Server 8.0/bin/mysqldump.exe' --host=127.0.0.1 --port=3306 --user=YOUR_MIGRATION_USER --password --single-transaction --triggers --no-tablespaces --set-gtid-purged=OFF --result-file=statics/runtime/backups/before-portions-v2.sql goiy_mon_an
if ($LASTEXITCODE -ne 0) { throw 'Backup failed' }
Get-FileHash statics/runtime/backups/before-portions-v2.sql -Algorithm SHA256
```

Dùng `--result-file`, tránh chuyển hướng PowerShell làm đổi encoding dump. Không
dùng `--databases` để dump có thể phục hồi vào schema thử khác, không chứa `USE`
đổi về database gốc. Trong thời gian backup/áp dụng, không chạy DDL/import khác.

Tạo schema phục hồi **riêng** rồi nạp dump bằng mysql client; kiểm tra host/schema
trước khi chạy. Ví dụ tên đích `goiy_v2_restore_test`:

```powershell
& 'C:/Program Files/MySQL/MySQL Server 8.0/bin/mysql.exe' --host=127.0.0.1 --port=3306 --user=YOUR_MIGRATION_USER --password --execute="CREATE DATABASE goiy_v2_restore_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
& 'C:/Program Files/MySQL/MySQL Server 8.0/bin/mysql.exe' --host=127.0.0.1 --port=3306 --user=YOUR_MIGRATION_USER --password --database=goiy_v2_restore_test --execute="SOURCE statics/runtime/backups/before-portions-v2.sql"
if ($LASTEXITCODE -ne 0) { throw 'Restore failed' }
```

Chốt số đếm/hash trước và sau; với database hiện tại là 50 recipes, 50 ingredients,
252 recipe_ingredients. Kiểm tra cả nội dung, aliases, metadata và hoạt động v1,
không chỉ số đếm. Giữ backup ở vị trí riêng theo quy trình của project.

## Kiểm tra và áp dụng khi được duyệt

Runner đọc host/port từ cấu hình MySQL hiện có, nhưng **bắt buộc** chỉ rõ database.
Dùng `MYSQL_MIGRATION_USER`, `MYSQL_MIGRATION_PASSWORD` trong môi trường riêng của
terminal vận hành; không sửa `.env` của ứng dụng, không ghi secret vào file dự án.
Mật khẩu có thể nhập bằng Read-Host, chuyển SecureString sang chuỗi để truyền cho connector.

```powershell
$env:MYSQL_MIGRATION_USER = Read-Host 'Migration user'
$migrationSecret = Read-Host 'Migration password' -AsSecureString
$env:MYSQL_MIGRATION_PASSWORD = [Net.NetworkCredential]::new('', $migrationSecret).Password
.venv/Scripts/python.exe -B -m source.database.migrate_v2 --database goiy_v2_restore_test --action check
.venv/Scripts/python.exe -B -m source.database.migrate_v2 --database goiy_v2_restore_test --action apply
.venv/Scripts/python.exe -B -m source.database.migrate_v2 --database goiy_v2_restore_test --action check
```

Chỉ sau khi thử bản sao và duyệt DDL/backup/đích kết nối, mới chạy cùng chuỗi lệnh
với `--database goiy_mon_an`. Không có migration tự chạy lúc khởi động TCP/FastAPI.
Giữ nguyên file SQL sau khi áp dụng; thay đổi tiếp theo cần migration mới.

Áp dụng DDL xong **chưa bật tính thật**: mọi bảng nghiệp vụ v2 vẫn rỗng. Cần bước
nhập/duyệt riêng, có nguồn và người duyệt thật, trước khi chốt release và đặt
`v2_calculation_settings.active_release_id`. Lượt triển khai này không cung cấp
importer/auto-approver hoặc tự tạo settings/release/unit/recipe.

## Quy tắc adapter và duyệt dữ liệu sau này

- Input `recipe_ids` vẫn là ID legacy; release ánh xạ sang revision v2 bằng FK.
  Revision/nguyên liệu v2 là namespace riêng; không lấy ID legacy làm ID v2.
- Chỉ release `PUBLISHED`, đúng dataset_version, có manifest/review hợp lệ được đọc.
  Release ghim revision cụ thể; không chọn revision mới nhất. Policy được ghim
  theo `selection_key`: ID legacy sắp tăng, nối dấu phẩy, ví dụ `1,2`.
- Mỗi claim gắn scope/entity, bằng chứng cùng scope/entity, nguồn APPROVED đã truy
  cập, người duyệt/thời điểm và `subject_hash`. `claims(snapshot)` cùng
  `subject_hash(scope,payload)` trong adapter định nghĩa canonical hash v1. Đây là
  công cụ tạo/kiểm tra digest, **không** tạo quyết định duyệt. Importer sau này phải
  dùng chính snapshot của nội dung người duyệt đã xác nhận.
- `release.manifest_hash` bằng digest claim release, bao gồm membership/ánh xạ và
  policy bindings. Review quyết định là append-only, có trigger chặn UPDATE/DELETE.
  Sửa số lượng/khẩu phần/đơn vị hoặc membership sau duyệt sẽ làm proof không khớp.
- Revision/content, servings, ingredient identity, form, quantity, unit, scaling,
  policy và từng allocation đều phải đủ phê duyệt. Dòng nháp không bị lọc bỏ khỏi
  bộ thành phần để giả thành đủ; kết quả là INCOMPLETE với lý do của bộ tính cũ.
- Tất cả dòng trong revision là bộ nguyên liệu đang tính, kể cả optional; chưa có
  đầu vào bật/tắt optional. Không tự bỏ gia vị hoặc suy lượng tồn kho. Chỉ hỗ trợ
  policy `person/per_person`; không tự tạo hệ số trẻ em hay phân bổ giữa các món.
- Tất cả đọc trong một transaction REPEATABLE READ, read-only, consistent snapshot;
  runtime không ghi dữ liệu. Chưa migration/sai version hoặc chưa active release
  trả APPROVED_DATA_UNAVAILABLE. MySQL lỗi/quyền thiếu sau marker hợp lệ vẫn DB_ERROR.

## Rollback an toàn

Rollback vận hành bằng cách tắt active release, giữ mọi dữ liệu:

```powershell
.venv/Scripts/python.exe -B -m source.database.migrate_v2 --database goiy_mon_an --action disable
```

`disable` chỉ đặt pointer v2 về NULL; v1/RECOMMEND/SEARCH/GENERATE_MEAL_PLAN_V2 tiếp
tục dùng bảng cũ. Không DROP/TRUNCATE hoặc sửa revision đã dùng để phục vụ người dùng.
Không có script down tự động xóa dữ liệu. Nếu DDL dang dở, giữ tính năng tắt và
phục hồi backup lên schema khác để kiểm tra/cutover có kiểm soát; không đánh dấu
APPLIED bằng tay, chạy lại seed hoặc xóa bảng gốc để chữa lỗi.

## Kiểm thử riêng

`tests/test_mysql_calculation_v2.py` khởi tạo instance mysqld riêng, random port,
database `goiy_v2_test_<random>`. Không đọc credential MYSQL_* để kết nối, không
kết nối database ứng dụng. Tất cả công thức, lượng và review fixture mang TEST_ONLY.
Trên máy thiếu mysqld, suite này skip có lý do; unit/TCP/HTTP tests vẫn chạy.

```powershell
$env:MYSQL_V2_MYSQLD = 'C:/Program Files/MySQL/MySQL Server 8.0/bin/mysqld.exe'
$env:TCP_LOG_PATH = 'statics/runtime/mysql-v2-tests/tcp.jsonl'
$env:PYTHONDONTWRITEBYTECODE = '1'
New-Item -ItemType Directory -Force statics/runtime/mysql-v2-tests | Out-Null
$testRoot = Join-Path (Get-Location) ('statics/runtime/mysql-v2-tests/run-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -B -m pytest -p no:cacheprovider "--basetemp=$testRoot" tests/test_mysql_calculation_v2.py tests/test_meal_plan_calculation.py tests/test_meal_plan_calculation_integration.py -q
```

Temp root mới nằm trong workspace; fixture chỉ DROP database do nó vừa tạo trên
instance riêng, rồi dừng process riêng. Không dừng service MySQL80 đang sử dụng.
# Unified v3 TEST_ONLY additions

`unified_v3_002_achievements.sql` adds user achievement posts, local image metadata,
and comments. It is applied to the named local rehearsal database with
`python -m source.database.apply_achievement_schema_test`; that helper is pinned
to `127.0.0.1:63900/goiy_v3_quality_final_20261110_test` and refuses any other
database identity. Do not use this helper for production.


## Feedback for unified v3

`unified_v3_003_feedback.sql` adds `feedback_submissions` for guest and signed-in
feedback. It stores category, text, processing status, optional `user_id`, and optional
local-image metadata. Image bytes remain under `statics/runtime/feedback-images/`; they
are not stored in MySQL or the repository. Fresh unified-v3 databases also receive the
table from `source/database/unified_schema.sql`.

This is an additive DDL migration and is not applied automatically by the application.
Before applying it to an existing database, create and verify a database backup, confirm
the target database identity, then execute this one file with an authorized MySQL
administrator. Do not apply it to production without a separate deployment decision.
The isolated integration tests apply the unified schema only to a private temporary
MySQL instance.

## Admin recipe taxonomies for unified v3

`unified_v3_004_admin_taxonomies.sql` extends `recipe_tags` with dish-type,
weather, cooking-method and main-ingredient groups plus description, core and
soft-delete metadata. It inserts the protected built-in dish types and links each
existing recipe to its current `recipes.role`. Recipe records and role values are
not modified. The current meal algorithm continues reading `recipes.role`.

This migration is not automatic and has no destructive down migration. Apply it
only to a verified TEST_ONLY clone first, then verify tag counts and recipe links.
Do not run it against `127.0.0.1:63900` or any demo/production schema from this
feature branch. The CRUD integration tests use a separate private mysqld instance.
