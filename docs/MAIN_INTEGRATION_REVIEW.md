# Rà soát tích hợp main vào demo hiện tại

Tích hợp `origin/main` tại `f8a0574` vào feature sau commit `9ea9f14`.
Ưu tiên schema/API/thuật toán/UI và môi trường local đang hoạt động.
Việc hợp nhất được thực hiện trong worktree riêng, không ghi vào MySQL hiện có.

## Thay đổi tương thích được giữ từ main

- Tách launcher portable đọc cấu hình, kiểm tra cổng/health và dừng tiến trình do nó sở hữu sang `scripts/run_public_demo.py`.
- Giữ nguyên `scripts/run_demo.py` và `start_demo.bat` dùng local.
- Portable dùng `data/demo` mới, kiểm tra checksum rồi sao chép ảnh còn thiếu vào runtime; không ghi đè uploads hoặc cấu hình, không import SQL khi khởi động.
- Gộp ignore cho rotated logs, JSONL, SQLite sidecars, chứng thư và browser reports.
- README dẫn tới catalog hiện tại và cấu hình mẫu riêng; giữ hướng dẫn legacy.
- Thay gói 201 món/152 ảnh cũ bằng 216 món ăn, 10 đồ uống, 174 ảnh upload và 49 fallback. File gói cũ trong worktree được giữ local.
- Giữ 33 file fixture/scripts/tài liệu/kết quả còn được test và hồ sơ tham chiếu.

## Quyết định theo từng file conflict

Đã đối chiếu diff từng file và các định nghĩa Python. Không áp dụng chiến lược
ours/theirs cho toàn bộ cây. Launcher, tài liệu và ignore được tích hợp riêng;
schema/API và các chức năng mở rộng giữ đồng bộ với phiên bản feature hiện tại.

| File | Quyết định |
|---|---|
| `.gitignore` | Combine safe ignore extensions from main with feature exclusions; keep curated results tracked. |
| `README.md` | Use current full catalog and fresh-clone guide; integrate portable startup from main in separate launcher. |
| `docs/unified-schema-v3-design.md` | Expanded taxonomies and operational role semantics are already newer in feature. |
| `pytest.ini` | Keep discovery and fresh temp roots; main fixed basetemp could delete an earlier test root. |
| `scripts/run_demo.py` | Keep local datadir, ports and startup byte-identical; port main launcher separately. |
| `source/common/protocol.py` | Retain additional ASSESS_MEAL_PLAN, taxonomy and feedback operations. |
| `source/database/migrations/README.md` | Retain latest structured portions, feedback and taxonomy migration documentation. |
| `source/database/unified_catalog_migration.py` | Retain vocabulary-aware empty-target checks, private-content guards and drink/portion ranking. |
| `source/database/unified_schema.sql` | Keep portion evidence, expanded taxonomy lifecycle and feedback schema; no live migration. |
| `source/database/unified_v3_structured_portions.py` | Keep reviewed portion status helper in addition to shared main definitions. |
| `source/server/admin_recipes.py` | Keep beverage settings and reviewed portion validation. |
| `source/server/handler.py` | Keep current operation dispatch, delete confirmations, daily/season/drink and assessment handling. |
| `source/server/main.py` | Keep taxonomy-conflict error mapping; otherwise main behavior already included. |
| `source/server/meal_plan_calculation.py` | Keep current original daily quantities, shared group allocation and service verdicts. |
| `source/server/meal_plan_v2.py` | Keep current bounded daily/custom search, rotation, pairing and capacity engines. |
| `source/server/mysql_calculation_catalog.py` | Keep keyword field binding that fixes positional requirement/scaling mismatch. |
| `source/server/repository.py` | Retain taxonomy conflict class; shared repository methods unchanged. |
| `source/server/unified_repository.py` | Keep current catalog/read/write, taxonomy, drink, feedback, reference-safe delete semantics. |
| `source/web/main.py` | Keep API endpoints and DTOs aligned with current TCP contracts and delete confirmations. |
| `source/web/meal_plan_calculation_contract.py` | Keep daily/custom serving and service assessment response contracts. |
| `source/web/meal_plan_v2_contract.py` | Keep current expanded layouts, seasonal assessments and daily combo search. |
| `source/web/static/admin-shell.js` | Keep taxonomy and feedback navigation while preserving achievement panel. |
| `source/web/static/admin.css` | Feature adds taxonomy/feedback/portion/beverage styles to main styles. |
| `source/web/static/admin.js` | Keep current guarded deletes, role filters, beverage and portion editors. |
| `source/web/static/app.js` | Keep current meal entry and filter state handling. |
| `source/web/static/meal-plan-v2.js` | Keep current daily history, drink cards, portion allocation and preserved pins. |
| `source/web/static/meal-plan.css` | Keep expanded current presentation styles. |
| `source/web/templates/_user_header.html` | Keep feedback modal and current shared navigation. |
| `source/web/templates/account_auth.html` | Keep current shared CSS version. |
| `source/web/templates/account_profile.html` | Keep current shared CSS version. |
| `source/web/templates/achievements.html` | Keep current shared CSS version. |
| `source/web/templates/admin.html` | Keep taxonomy/feedback/beverage/portion markup and matching asset versions. |
| `source/web/templates/detail.html` | Keep current shared CSS version. |
| `source/web/templates/index.html` | Keep current CSS/JS versions and current home entry points. |
| `source/web/templates/meal_plan.html` | Keep current shared CSS version. |
| `source/web/templates/meal_plan_v2.html` | Keep current meal controls including drinks and current asset versions. |
| `tests/browser_meal_plan.mjs` | Keep navigation checks aligned to current shared header. |
| `tests/browser_meal_plan_people.mjs` | Only EOF whitespace differs; preserve cleaned current test. |
| `tests/browser_ui.mjs` | Keep browser-state and selector fixes; main includes stale page string assertions. |
| `tests/test_admin.py` | Keep isolated draft DTO fixture aligned with current validation. |
| `tests/test_frontend_contract.py` | Keep expanded regression tests and current guarded deletion/reference policy. |
| `tests/test_meal_plan_calculation.py` | All main test definitions are present; feature adds current daily/portion coverage. |
| `tests/test_meal_plan_v2.py` | Keep current search/rotation/pairing tests, shared main tests included. |
| `tests/test_mysql_calculation_v2.py` | Keep readonly fixture permissions and current calculation payload checks. |
| `tests/test_mysql_recipe_publication.py` | Keep current metadata semantics and real Playwright publication checks. |
| `tests/test_mysql_repository_transactions.py` | Keep current draft namespace/DTO regression expectations. |
| `tests/test_unified_catalog_migration.py` | Keep core taxonomy/schema checks and isolated image backup checks. |
| `tests/test_unified_http_tcp.py` | Keep expanded current end-to-end coverage and updated fixture data. |
| `tests/test_web_meal_plan.py` | Keep assertions aligned with current shared navigation. |

## Kiểm thử

`tests/test_public_demo_mysql.py` tạo MySQL riêng trên loopback/cổng ngẫu nhiên,
import SQL vào schema rỗng, kiểm tra số lượng và liên kết, chạy launcher portable
với tài khoản DML riêng, truy cập đủ 174 ảnh upload/49 fallback, bốn mùa,
định lượng và Admin qua HTTP/TCP/MySQL thật.

Kết quả suite/smoke test được ghi trong PR. Các datadir kiểm thử, credentials
tổng hợp và logs giữ local trong output; không dùng instance demo đang chạy.

Test backup migration cũ nay skip khi thiếu backup riêng trên bản clone và cho
phép chỉ định `GOIY_MIGRATION_TEST_BACKUP`. Nếu có backup vẫn bắt buộc đúng SHA-256
và chỉ restore trong instance fixture mới. Đã chạy riêng cả hai test migration
với backup đã xác minh; không cần đưa dữ liệu riêng vào Git để suite chạy được.

Kết quả xác minh bản tích hợp ngày 13/11/2026:

- Toàn bộ suite: **1.203 passed, 1 skipped**, không có failure/error.
- Skip duy nhất là backup lịch sử không phân phối; chạy riêng với backup đúng
  checksum: **2 passed** trên instance MySQL mới.
- Import SQL và launcher portable đạt trên MySQL riêng với tài khoản DML;
  đủ 174 ảnh upload/49 fallback truy cập qua HTTP, bốn mùa đều tạo mâm thực tế.
- `pip check`, kiểm tra whitespace và checksum SQL/ảnh đều đạt.
- Không phát hiện secret/token trong snapshot chuẩn bị push; không có cache,
  log, backup hoặc dữ liệu runtime riêng được theo dõi.
- Source/schema/catalog và launcher local trùng bản feature trước tích hợp;
  `.env` và `.env.admin.local` không đổi. Không chạy migration trên MySQL hiện có.
