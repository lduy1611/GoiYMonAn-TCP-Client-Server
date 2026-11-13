# Kiểm toán 42 test thất bại — 13/11/2026

Trạng thái cuối: **1.156 pass / 0 fail / 0 error / 0 skip / 0 xfail**, đã xử lý 42 lỗi ban đầu. Full suite đầu sau sửa đạt 1.154 pass. Smoke thực tế phát hiện thêm lỗi chuyển Daily 7 món sang Custom 6 món; đã sửa và bổ sung hai regression, nhóm liên quan đạt 184 pass. Baseline full suite trước sửa: 1.111 pass, 42 fail. Bảng dưới bao gồm đủ từng test; mỗi tham số desktop/mobile/query là một test riêng.

## Kết quả full suite cuối và cách tiếp tục lượt bị ngắt

- Collection hiện tại có 1.156 node ID. Lượt cuối bị ngắt sau **844 test đã pass**, đúng cuối module `test_mysql_vegetarian_source_import.py`; log không có fail/error trước điểm ngắt.
- Chỉ chạy tiếp **312 test còn lại**, từ `test_protocol.py` đến `test_web_meal_plan.py`: **312 passed, 1 warning, 124,01 giây**. Không chạy lại 844 test đã đạt.
- Đối chiếu từng node ID của JUnit lượt tiếp tục với phần đuôi collection: không thiếu, không thừa; tổng phạm vi đầy đủ là **844 + 312 = 1.156**. Đây là kết quả toàn suite qua hai phần, không phải một tiến trình pytest duy nhất chạy tới cuối.
- Bằng chứng: [tổng hợp](../.test_runtime/audit42-final-summary.json), [log phần đầu](../.test_runtime/audit42-full-verified.log), [log phần tiếp tục](../.test_runtime/audit42-full-resume.log), [JUnit phần tiếp tục](../.test_runtime/audit42-resume-results.xml), [collection](../.test_runtime/audit42-final-nodeids.json). Lượt trước đạt 1.154 có [JUnit đầy đủ](../.test_runtime/audit42-final-results.xml).
- Từ baseline 1.153 test lên 1.156: một regression mùa/món ghim được bổ sung trong đợt sửa trước và hai regression chuyển tab; không xóa, skip hoặc xfail test để làm xanh.
- Cảnh báo còn lại: `StarletteDeprecationWarning` về httpx/TestClient. Không ảnh hưởng website hoặc kết quả assertion; chưa đổi dependency ngoài phạm vi chốt demo.

Không có baseline full suite trước đợt mùa nên không quy kết toàn bộ lỗi là hồi quy của mùa. Cả 42 request/test gốc không chọn mùa cụ thể; nhánh ALL đã có 11 baseline API đối chiếu từng trường. Các fixture Daily cũ không còn đáp ứng chính sách khẩu phần/cơ cấu đã chốt.

| # | Test | Nhóm | Nguyên nhân và xử lý |
|---:|---|---|---|
| 1 | `tests/test_admin.py::test_admin_draft_gateway_requires_csrf_and_validates_before_tcp` | Source: DTO nháp | DTO dùng chung từ chối unknown và gửi thêm trường structured trái contract TCP nháp. Tách DTO ba trường. |
| 2 | `tests/test_admin.py::test_admin_create_distinguishes_expired_session_csrf_and_writer_denial` | Source: DTO nháp | DTO dùng chung từ chối unknown và gửi thêm trường structured trái contract TCP nháp. Tách DTO ba trường. |
| 3 | `tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[legacy-desktop]` | Test selector header cũ | Legacy dùng header-link đã bỏ. Các journey khác giả định không có Tự chọn, control người cũ và Daily không cần dữ liệu. Chuyển thành hành trình Custom hiện tại + backend fixture định lượng rõ; Daily vẫn kiểm thử riêng MySQL. Phát hiện thêm lỗi restore Custom trong source. |
| 4 | `tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[legacy-mobile]` | Test selector header cũ | Legacy dùng header-link đã bỏ. Các journey khác giả định không có Tự chọn, control người cũ và Daily không cần dữ liệu. Chuyển thành hành trình Custom hiện tại + backend fixture định lượng rõ; Daily vẫn kiểm thử riêng MySQL. Phát hiện thêm lỗi restore Custom trong source. |
| 5 | `tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[flexible-desktop]` | Test nghiệp vụ/fixture UI cũ | Legacy dùng header-link đã bỏ. Các journey khác giả định không có Tự chọn, control người cũ và Daily không cần dữ liệu. Chuyển thành hành trình Custom hiện tại + backend fixture định lượng rõ; Daily vẫn kiểm thử riêng MySQL. Phát hiện thêm lỗi restore Custom trong source. |
| 6 | `tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[flexible-mobile]` | Test nghiệp vụ/fixture UI cũ | Legacy dùng header-link đã bỏ. Các journey khác giả định không có Tự chọn, control người cũ và Daily không cần dữ liệu. Chuyển thành hành trình Custom hiện tại + backend fixture định lượng rõ; Daily vẫn kiểm thử riêng MySQL. Phát hiện thêm lỗi restore Custom trong source. |
| 7 | `tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[people-desktop]` | Test nghiệp vụ/fixture UI cũ | Legacy dùng header-link đã bỏ. Các journey khác giả định không có Tự chọn, control người cũ và Daily không cần dữ liệu. Chuyển thành hành trình Custom hiện tại + backend fixture định lượng rõ; Daily vẫn kiểm thử riêng MySQL. Phát hiện thêm lỗi restore Custom trong source. |
| 8 | `tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[people-mobile]` | Test nghiệp vụ/fixture UI cũ | Legacy dùng header-link đã bỏ. Các journey khác giả định không có Tự chọn, control người cũ và Daily không cần dữ liệu. Chuyển thành hành trình Custom hiện tại + backend fixture định lượng rõ; Daily vẫn kiểm thử riêng MySQL. Phát hiện thêm lỗi restore Custom trong source. |
| 9 | `tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[vegetarian-desktop]` | Test nghiệp vụ/fixture UI cũ | Legacy dùng header-link đã bỏ. Các journey khác giả định không có Tự chọn, control người cũ và Daily không cần dữ liệu. Chuyển thành hành trình Custom hiện tại + backend fixture định lượng rõ; Daily vẫn kiểm thử riêng MySQL. Phát hiện thêm lỗi restore Custom trong source. |
| 10 | `tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[vegetarian-mobile]` | Test nghiệp vụ/fixture UI cũ | Legacy dùng header-link đã bỏ. Các journey khác giả định không có Tự chọn, control người cũ và Daily không cần dữ liệu. Chuyển thành hành trình Custom hiện tại + backend fixture định lượng rõ; Daily vẫn kiểm thử riêng MySQL. Phát hiện thêm lỗi restore Custom trong source. |
| 11 | `tests/test_browser_ui.py::test_browser_user_journey[desktop] - Asserti...` | Test harness Node/cache | location được dùng ngoài browser trong Node; sau sửa lộ giả định mọi asset cùng version dù app đã tách shell/widget. |
| 12 | `tests/test_browser_ui.py::test_browser_user_journey[mobile] - Assertio...` | Test harness Node/cache | location được dùng ngoài browser trong Node; sau sửa lộ giả định mọi asset cùng version dù app đã tách shell/widget. |
| 13 | `tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[-/] - As...` | Test header cũ | Back là link allowlist; nav dùng chung luôn trỏ /meal-plan và brand /. Kiểm tra từng chức năng thay selector header-link đã bỏ. |
| 14 | `tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=%2F-/]` | Test header cũ | Back là link allowlist; nav dùng chung luôn trỏ /meal-plan và brand /. Kiểm tra từng chức năng thay selector header-link đã bỏ. |
| 15 | `tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=%2Fmeal-plan-/meal-plan]` | Test header cũ | Back là link allowlist; nav dùng chung luôn trỏ /meal-plan và brand /. Kiểm tra từng chức năng thay selector header-link đã bỏ. |
| 16 | `tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=https%3A%2F%2Fevil.example-/]` | Test header cũ | Back là link allowlist; nav dùng chung luôn trỏ /meal-plan và brand /. Kiểm tra từng chức năng thay selector header-link đã bỏ. |
| 17 | `tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=%2F%2Fevil.example-/]` | Test header cũ | Back là link allowlist; nav dùng chung luôn trỏ /meal-plan và brand /. Kiểm tra từng chức năng thay selector header-link đã bỏ. |
| 18 | `tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=javascript%3Aalert(1)-/]` | Test header cũ | Back là link allowlist; nav dùng chung luôn trỏ /meal-plan và brand /. Kiểm tra từng chức năng thay selector header-link đã bỏ. |
| 19 | `tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=%2Fmeal-plan%3Fx%3D1-/]` | Test header cũ | Back là link allowlist; nav dùng chung luôn trỏ /meal-plan và brand /. Kiểm tra từng chức năng thay selector header-link đã bỏ. |
| 20 | `tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=%2Fmeal-plan&return_to=%2F-/]` | Test header cũ | Back là link allowlist; nav dùng chung luôn trỏ /meal-plan và brand /. Kiểm tra từng chức năng thay selector header-link đã bỏ. |
| 21 | `tests/test_mysql_calculation_v2.py::test_complete_actual_mysql_catalog_preserves_namespaces_and_ranges` | Source: adapter / fixture quyền | IngredientLine thêm requirement nhưng adapter còn gọi positional. Riêng SELECT-only còn thiếu quyền probe bảng optional chưa tồn tại. |
| 22 | `tests/test_mysql_calculation_v2.py::test_editing_approved_values_invalidates_their_review[UPDATE v2_units SET definition='EDITED_AFTER_REVIEW' WHERE id=1-UNIT_NOT_APPROVED]` | Source: adapter / fixture quyền | IngredientLine thêm requirement nhưng adapter còn gọi positional. Riêng SELECT-only còn thiếu quyền probe bảng optional chưa tồn tại. |
| 23 | `tests/test_mysql_calculation_v2.py::test_approved_but_invalid_or_unknown_quantities_are_still_incomplete` | Source: adapter / fixture quyền | IngredientLine thêm requirement nhưng adapter còn gọi positional. Riêng SELECT-only còn thiếu quyền probe bảng optional chưa tồn tại. |
| 24 | `tests/test_mysql_calculation_v2.py::test_disable_rolls_back_activation_without_deleting_data` | Source: adapter / fixture quyền | IngredientLine thêm requirement nhưng adapter còn gọi positional. Riêng SELECT-only còn thiếu quyền probe bảng optional chưa tồn tại. |
| 25 | `tests/test_mysql_calculation_v2.py::test_adapter_uses_consistent_snapshot_even_if_writer_changes_data` | Source: adapter / fixture quyền | IngredientLine thêm requirement nhưng adapter còn gọi positional. Riêng SELECT-only còn thiếu quyền probe bảng optional chưa tồn tại. |
| 26 | `tests/test_mysql_calculation_v2.py::test_real_mysql_tcp_http_with_select_only_runtime_and_database_error` | Source: adapter / fixture quyền | IngredientLine thêm requirement nhưng adapter còn gọi positional. Riêng SELECT-only còn thiếu quyền probe bảng optional chưa tồn tại. |
| 27 | `tests/test_mysql_calculation_v2.py::test_backup_restore_to_another_private_schema_retains_approved_release` | Source: adapter / fixture quyền | IngredientLine thêm requirement nhưng adapter còn gọi positional. Riêng SELECT-only còn thiếu quyền probe bảng optional chưa tồn tại. |
| 28 | `tests/test_mysql_integration.py::test_mysql_multiclient_and_http_outage` | Môi trường/fixture socket | Windows có thể trả connect timeout cho cổng đóng. Cô lập nhánh ConnectionRefused để kiểm tra đúng mapping 503; test timeout riêng giữ nguyên. |
| 29 | `tests/test_mysql_recipe_publication.py::test_legacy_outputs_identical_with_publication_active_or_inactive` | Test metadata version | Release thay classification_version có chủ đích như dataset_version. Kiểm tra version đổi rồi đối chiếu nguyên nội dung còn lại. |
| 30 | `tests/test_mysql_recipe_publication.py::test_published_v2_browser_after_50_legacy_ingredients[desktop]` | Môi trường/harness headless | Extension dump-dom không chạy marker ổn định trong Edge. Dùng Playwright tương tác thật, giữ kiểm tra fingerprint/card/overflow/JS. |
| 31 | `tests/test_mysql_recipe_publication.py::test_published_v2_browser_after_50_legacy_ingredients[mobile]` | Môi trường/harness headless | Extension dump-dom không chạy marker ổn định trong Edge. Dùng Playwright tương tác thật, giữ kiểm tra fingerprint/card/overflow/JS. |
| 32 | `tests/test_mysql_repository_transactions.py::test_draft_crosswalk_uses_schema_default_without_extra_status_grant_test_only` | Source: DTO nháp | DTO dùng chung từ chối unknown và gửi thêm trường structured trái contract TCP nháp. Tách DTO ba trường. |
| 33 | `tests/test_server_log_config.py::test_server_loads_log_and_startup_settings_before_use[default]` | Fixture mock startup | StartupProbe thiếu keyword max_connections; cô lập env pool và kiểm tra keyword đúng 4. |
| 34 | `tests/test_server_log_config.py::test_server_loads_log_and_startup_settings_before_use[dotenv]` | Fixture mock startup | StartupProbe thiếu keyword max_connections; cô lập env pool và kiểm tra keyword đúng 4. |
| 35 | `tests/test_server_log_config.py::test_server_loads_log_and_startup_settings_before_use[process_override]` | Fixture mock startup | StartupProbe thiếu keyword max_connections; cô lập env pool và kiểm tra keyword đúng 4. |
| 36 | `tests/test_server_log_config.py::test_server_loads_log_and_startup_settings_before_use[dotenv_disabled]` | Fixture mock startup | StartupProbe thiếu keyword max_connections; cô lập env pool và kiểm tra keyword đúng 4. |
| 37 | `tests/test_unified_catalog_migration.py::test_backup_import_is_repeatable_and_keeps_effective_public_catalog_test_only` | Source migrator + fixture thiếu ảnh | Bảy core taxonomy do schema tạo bị coi là dữ liệu lạ. Cho phép đúng vocabulary chuẩn, vẫn chặn dữ liệu khác. Backup SQL không kèm ảnh: kiểm tra fail-closed rồi dùng ảnh synthetic chỉ trong bản restore cô lập. |
| 38 | `tests/test_unified_http_tcp.py::test_daily_combo_history_roundtrips_http_tcp_mysql_test_only` | Fixture Daily/semantics thống kê | Fixture thiếu định lượng, chỉ một main cho 4 người. Cung cấp đúng một combo 2+1+1 bằng dữ liệu TEST_ONLY. found đếm phương án mới xét, không đếm combo cũ bị loại trước qualification. |
| 39 | `tests/test_unified_http_tcp.py::test_unified_http_tcp_admin_user_and_meal_flows` | Fixture/chính sách Daily | Request mặc định Daily nay giữ nguyên công thức, còn test đòi scale. Chỉ rõ layout custom, khai báo dữ liệu estimated có căn cứ TEST_ONLY. |
| 40 | `tests/test_unified_http_tcp.py::test_unified_admin_to_user_browser_flow` | Test tương tác UI cũ | Mở details trước nhập trường nâng cao, đợi navigation/ready; fixture không đủ dữ liệu Daily nên kiểm thử cơ cấu Custom, tăng người không tự thêm món. |
| 41 | `tests/test_unified_http_tcp.py::test_portion_display_playwright_unified_mysql` | Test nhãn/async Custom | Vào Custom trực tiếp, đợi đúng kết quả người mới trước assertion; cập nhật nhãn hiện tại nhưng giữ số liệu và trạng thái thiếu dữ liệu. |
| 42 | `tests/test_unified_http_tcp.py::test_admin_permanent_recipe_delete_playwright_desktop_and_mobile` | Test cache token Admin | Test giữ cache key cũ; đối chiếu đúng key asset hiện tại, không thay nghiệp vụ xóa. |

## Lỗi source thực tế và phạm vi sửa

- `source/server/mysql_calculation_catalog.py::_catalog`: tham số positional bị dịch sau khi `IngredientLine` thêm `requirement`; dùng keyword cho measurement/purpose/requirement/review/scaling. Không đổi phép tính hay cơ chế kiểm duyệt.
- `source/web/main.py::AdminDraftIngredientLine`: tách DTO nháp đúng ba trường TCP, chấp nhận `unknown` cho nháp legacy; không mở rộng DTO lưu món unified. Kiểm tra CSRF, hết phiên, quyền writer và payload TCP chính xác.
- `source/database/unified_catalog_migration.py::_empty_target`: chấp nhận đúng bảy loại món lõi chuẩn giống vocabulary đơn vị; vẫn từ chối tag khác/đã đổi/xóa hoặc dữ liệu nghiệp vụ, kể cả Thành quả/Góp ý. Chỉ thử trên DB cô lập, không chạy migration demo.
- `source/web/static/meal-plan-v2.js::restore`: biến household không che `groups`; phiên Custom không bị đổi thành bộ lọc Daily legacy. Kiểm tra deep equality view/conditions/pins/history sau reload, cùng định lượng trước/sau.
- `source/web/static/app.js::loadIngredients/restoreSelection/saveSelection`: preset Explore/Lunch chỉ áp khi đổi ngữ cảnh; Back/reload giữ query và phân trang. Bổ sung context phiên tương thích snapshot cũ; không thay tìm kiếm/ranking.
- `source/server/meal_plan_v2.py::validate` và `source/web/meal_plan_v2_contract.py::Request`: chấp nhận đúng hình dạng mâm Daily cũ 5 chính + 1 rau + 1 canh làm trạng thái chuyển tab. Desired counts của Custom vẫn tối đa 6; pin bị mất vị trí trả `PINNED_SLOT_REMOVED`, không cắt ngầm. Payload thật được lưu trước 422 và sau 200/6 món.

Không sửa công thức trong `meal_plan_calculation.py`, mô hình `daily_demo_portions.py` hay chính sách `daily_seasons.py`. Các thay đổi gần đây ở Daily giải thích vì sao fixture 1 chính + 1 rau + 1 canh không có định lượng và request calculate mặc định Daily không còn có kết quả/scale như test cũ; các test phân bổ phải chỉ rõ Custom và căn cứ số suất. Không có bằng chứng quy 42 lỗi cho mùa; không tạo baseline bằng reset/checkout/restore.

Các sửa test không bỏ ca kiểm thử: hành trình Legacy giữ nguyên API v1, đổi selector header; ba hành trình Custom chuyển sang Playwright + HTTP/TCP thật với fixture định lượng TEST_ONLY. Chúng kiểm tra số món, pin/thay món, đáp số g/ml, XSS, race response, outage, chay/Không ăn, restore. Daily automatic/season được kiểm tra qua MySQL riêng và localhost. Assertion `aria-pressed`/`aria-expanded` dùng true/false, `aria-current` dùng page; ID hết catalog bị lọc và cảnh báo, không giả làm dữ liệu mới. Phiên cache được thử ở đúng URL ngữ cảnh; ảnh được chờ cả mount/upload lookup, không chỉ catalog.

## Bằng chứng nghiệm thu localhost

`start_demo.bat`, FastAPI 8000 / TCP 9000 / MySQL 63900. Kết quả chi tiết: `../.test_runtime/audit42-smoke-results.json`.

Lượt xác nhận cuối trên source sau sửa chuyển tab: [smoke desktop/mobile](../.test_runtime/audit42-finish-smoke.json) và [stale/Console/danh sách Admin](../.test_runtime/audit42-edge-smoke.json).

- Cả hai viewport 1365 và 390: bốn mùa, ghim và Đổi cả mâm, khẩu phần và shopping hiển thị; Daily 12 người với 7 món chuyển sang Custom 6 món thành công, không còn 422 do previous-plan.
- Custom giữ cùng recipe IDs và pin khi đổi qua 2/4/6/8/12 người. Khẩu phần và shopping không mất; Back từ chi tiết công thức và reload giữ chính xác `conditions`, `pins`, `view` (bao gồm toàn bộ response và danh sách món).
- Khám phá: tìm `canh`, hai món/trang, chuyển trang 2; Back từ chi tiết và reload giữ query và đúng các tiêu đề món của trang 2.
- Admin: Quản lý món/Loại món/Phân loại món trả 200; các bảng render thật ở cả hai viewport: món 20 dòng/trang, nguyên liệu 20 dòng/trang, loại món 9 dòng, phân loại 34 dòng. Form tạo nháp kiểm tra thiếu tên và thời gian không hợp lệ đúng trường; request nháp không CSRF trả 403, body sai trả 422. Không gửi bản nháp hợp lệ để lưu lên demo.
- Trường hợp bộ lọc thời gian 1 phút không có mâm: card mâm cũ và shopping cũ đều ẩn, không xuất hiện như kết quả mới.
- **0 HTTP 5xx, 0 JavaScript exception, 0 Console error ứng dụng.** Có một cảnh báo resource riêng: trình duyệt desktop tự yêu cầu `/favicon.ico`, server trả 404. Không che cảnh báo này hoặc quy nó thành lỗi JS; chưa thêm asset ngoài phạm vi.
- Sau tất cả kiểm thử cuối, so sánh lại **17/17 bảng: count và SHA256 không đổi, changed_tables = []**. Bằng chứng baseline trong `../.test_runtime/audit42-demo-baseline.json` và kết quả so sánh trong smoke cuối.

Kết luận: **sẵn sàng demo cho các luồng đã nghiệm thu** trên 8000/9000/63900. Không còn test fail hoặc lỗi chức năng đã biết trong phạm vi này. Hai tồn tại không chặn demo: favicon 404 và cảnh báo deprecation TestClient nêu trên. Không thay thuật toán mùa/khẩu phần, schema hay dữ liệu demo trong lượt hoàn tất; không reset/checkout/restore/commit/push.

- Desktop 1365 và mobile 390: năm lựa chọn mùa, Daily 2/5/8/12 người, pin/đổi combo đều đạt, không JS error/HTTP 5xx.
- Bốn combo năm người và điểm mùa/phần bữa ăn khớp nguyên báo cáo trước: SPRING 6 / 5.006035; SUMMER 10 / 5.003972; AUTUMN 12 / 5.118215; WINTER 16 / 5.147715; recipe IDs cũng trùng hoàn toàn.
- Custom 2/4/6/8/12 người: toàn bộ response tính toán trùng baseline API cùng payload, không đổi món/cơ cấu; reload giữ chính xác view, conditions, pins. Ví dụ cùng mâm: cá basa 150 g cho 4 người, 225 g cho 6 người.
- 1.184 kiểm tra dòng nguyên liệu từ SELECT độc lập: Daily factor một, Custom theo nhóm số suất gốc, fixed giữ nguyên; phép làm tròn ra ngoài khi không biểu diễn hữu hạn, tổng shopping từ raw fractions, không cộng khác đơn vị/yêu cầu.
- Cả 17 bảng demo khớp count và SHA256 trước/sau. Không thay schema, dữ liệu, ảnh, tài khoản hay Thành quả; tất cả fixture ghi dữ liệu nằm trên instance TEST_ONLY/cổng ngẫu nhiên.

## Các file kiểm thử và cấu hình được sửa trong đợt kiểm toán

Đây là danh sách theo phạm vi kiểm toán, không phải toàn bộ `git diff` của project: repository đã có nhiều thay đổi chưa commit từ các đợt trước.

| File/nhóm file | Mục đích |
|---|---|
| `pytest.ini` | Giới hạn collection ở tests, cache trong runtime; bỏ basetemp cố định có thể bị pytest xóa khi dùng lại. |
| `tests/test_admin.py`, `test_mysql_repository_transactions.py` | Kiểm chứng DTO/payload TCP nháp chính xác và chẩn đoán response. |
| `tests/test_mysql_calculation_v2.py` | Fixture quyền SELECT theo schema, vẫn kiểm tra denial đúng bảng và lỗi adapter. |
| `tests/test_mysql_integration.py`, `test_server_log_config.py` | Cô lập env, pool startup và ConnectionRefused; giữ test TCP thật/timeout riêng. |
| `tests/test_mysql_recipe_publication.py` | Phân biệt version chủ đích với nội dung nghiệp vụ; Playwright thay harness extension không ổn định. |
| `tests/test_unified_catalog_migration.py` | Kiểm chứng schema hiện tại, fail-closed khi thiếu ảnh; ảnh synthetic chỉ trong fixture cô lập. |
| `tests/test_browser_meal_plan.py`, `browser_meal_plan.mjs`, `test_meal_plan_ux.py` | Selector navigation hiện tại; hành trình Custom đầy đủ với dữ liệu TEST_ONLY và số liệu đối chiếu. |
| `tests/browser_ui.mjs` | Đúng URL/context cache, ARIA và thời điểm ảnh mount; không bỏ assertion nội dung. |
| `tests/test_unified_http_tcp.py` | Fixture Daily có căn cứ, Custom phân bổ tách riêng, thao tác tab/form và chờ response đúng số người. |
| `tests/test_daily_seasons.py`, `test_daily_meal_recommendation.py` | Hai regression cho trạng thái chuyển Daily 7 món sang Custom, gồm HTTP/TCP/MySQL cô lập và bảo vệ pin bị mất slot. |
| `tests/test_frontend_contract.py`, `test_meal_plan_v2.py`, `test_web_meal_plan.py` | Cache token khớp template; không sửa công thức hay chính sách. |
| `source/web/templates/index.html`, `meal_plan_v2.html` | Cache token cho các sửa restore và chuyển tab. |

Những lỗi mới phát hiện ngoài danh sách 42: restore Custom bị shadow biến/đổi nhầm context; Explore mất query/page khi Back/reload; chuyển Daily 7 món sang Custom bị giới hạn previous-plan 6. Đã sửa nguyên nhân source và kiểm thử hồi quy; không sửa season ranking, công thức khẩu phần hoặc dữ liệu demo.

## Traceback baseline lưu từ lượt full suite

Giữ traceback thực tế để đối chiếu; dòng cuối ghi 42 failed / 1111 passed. Đây là log TEST_ONLY, không phải dữ liệu demo.

```text
.................................................................. [ 93%]
........................................................................ [ 99%]
.                                                                        [100%]
================================== FAILURES ===================================
_______ test_admin_draft_gateway_requires_csrf_and_validates_before_tcp _______
tests\test_admin.py:138: in test_admin_draft_gateway_requires_csrf_and_validates_before_tcp
    assert client.post("/api/admin/revisions",json=body).status_code==403
E   AssertionError: assert 422 == 403
E    +  where 422 = <Response [422 Unprocessable Entity]>.status_code
E    +    where <Response [422 Unprocessable Entity]> = post('/api/admin/revisions', json={'title': 'TEST_ONLY', 'description': '', 'instructions': 'TEST_ONLY steps', 'minutes': None, ...})
E    +      where post = <starlette.testclient.TestClient object at 0x0000027EA9D0A9E0>.post
___ test_admin_create_distinguishes_expired_session_csrf_and_writer_denial ____
tests\test_admin.py:173: in test_admin_create_distinguishes_expired_session_csrf_and_writer_denial
    assert expired.status_code == 401 and expired.json()["error"]["code"] == "ADMIN_UNAUTHORIZED"
E   assert (422 == 401)
E    +  where 422 = <Response [422 Unprocessable Entity]>.status_code
_______________ test_meal_plan_browser_journey[legacy-desktop] ________________
tests\test_browser_meal_plan.py:47: in test_meal_plan_browser_journey
    assert result.returncode == 0, result.stdout+result.stderr
E   AssertionError: file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan.mjs:50
E       evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
E                                                                                                                                                        ^
E
E     Error: {"exceptionId":1,"text":"Uncaught","lineNumber":0,"columnNumber":38,"scriptId":"61","stackTrace":{"callFrames":[{"functionName":"","scriptId":"61","url":"","lineNumber":0,"columnNumber":38}]},"exception":{"type":"object","subtype":"error","className":"TypeError","description":"TypeError: Cannot read properties of null (reading 'getAttribute')\n    at <anonymous>:1:39","objectId":"9213577736971461637.5.2"}}
E         at evaluate (file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan.mjs:50:148)
E         at async file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan.mjs:123:16
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_meal_plan.m...:50:148)\n    at async file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan.mjs:123:16\n\nNode.js v24.22.1\n').returncode
________________ test_meal_plan_browser_journey[legacy-mobile] ________________
tests\test_browser_meal_plan.py:47: in test_meal_plan_browser_journey
    assert result.returncode == 0, result.stdout+result.stderr
E   AssertionError: file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan.mjs:50
E       evaluate=async expression=>{const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;};
E                                                                                                                                                        ^
E
E     Error: {"exceptionId":1,"text":"Uncaught","lineNumber":0,"columnNumber":38,"scriptId":"61","stackTrace":{"callFrames":[{"functionName":"","scriptId":"61","url":"","lineNumber":0,"columnNumber":38}]},"exception":{"type":"object","subtype":"error","className":"TypeError","description":"TypeError: Cannot read properties of null (reading 'getAttribute')\n    at <anonymous>:1:39","objectId":"119452598524588246.5.2"}}
E         at evaluate (file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan.mjs:50:148)
E         at async file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan.mjs:123:16
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_meal_plan.m...:50:148)\n    at async file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan.mjs:123:16\n\nNode.js v24.22.1\n').returncode
______________ test_meal_plan_browser_journey[flexible-desktop] _______________
tests\test_browser_meal_plan.py:47: in test_meal_plan_browser_journey
    assert result.returncode == 0, result.stdout+result.stderr
E   AssertionError: node:internal/modules/run_main:107
E         triggerUncaughtException(
E         ^
E
E     AssertionError [ERR_ASSERTION]: No manual mode
E
E     3 !== 0
E
E         at file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_v2.mjs:109:10 {
E       generatedMessage: false,
E       code: 'ERR_ASSERTION',
E       actual: 3,
E       expected: 0,
E       operator: 'strictEqual',
E       diff: 'simple'
E     }
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_meal_plan_v...'ERR_ASSERTION',\n  actual: 3,\n  expected: 0,\n  operator: 'strictEqual',\n  diff: 'simple'\n}\n\nNode.js v24.22.1\n").returncode
_______________ test_meal_plan_browser_journey[flexible-mobile] _______________
tests\test_browser_meal_plan.py:47: in test_meal_plan_browser_journey
    assert result.returncode == 0, result.stdout+result.stderr
E   AssertionError: node:internal/modules/run_main:107
E         triggerUncaughtException(
E         ^
E
E     AssertionError [ERR_ASSERTION]: No manual mode
E
E     3 !== 0
E
E         at file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_v2.mjs:109:10 {
E       generatedMessage: false,
E       code: 'ERR_ASSERTION',
E       actual: 3,
E       expected: 0,
E       operator: 'strictEqual',
E       diff: 'simple'
E     }
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_meal_plan_v...'ERR_ASSERTION',\n  actual: 3,\n  expected: 0,\n  operator: 'strictEqual',\n  diff: 'simple'\n}\n\nNode.js v24.22.1\n").returncode
_______________ test_meal_plan_browser_journey[people-desktop] ________________
tests\test_browser_meal_plan.py:47: in test_meal_plan_browser_journey
    assert result.returncode == 0, result.stdout+result.stderr
E   AssertionError: file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_people.mjs:44
E         if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;
E                                     ^
E
E     Error: {"exceptionId":1,"text":"Uncaught","lineNumber":0,"columnNumber":38,"scriptId":"10","stackTrace":{"callFrames":[{"functionName":"","scriptId":"10","url":"","lineNumber":0,"columnNumber":38}]},"exception":{"type":"object","subtype":"error","className":"TypeError","description":"TypeError: Cannot read properties of null (reading 'textContent')\n    at <anonymous>:1:39","objectId":"-1410258950509439381.2.2"}}
E         at evaluate (file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_people.mjs:44:33)
E         at async file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_people.mjs:63:16
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_meal_plan_p...3)\n    at async file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_people.mjs:63:16\n\nNode.js v24.22.1\n').returncode
________________ test_meal_plan_browser_journey[people-mobile] ________________
tests\test_browser_meal_plan.py:47: in test_meal_plan_browser_journey
    assert result.returncode == 0, result.stdout+result.stderr
E   AssertionError: file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_people.mjs:44
E         if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;
E                                     ^
E
E     Error: {"exceptionId":1,"text":"Uncaught","lineNumber":0,"columnNumber":38,"scriptId":"10","stackTrace":{"callFrames":[{"functionName":"","scriptId":"10","url":"","lineNumber":0,"columnNumber":38}]},"exception":{"type":"object","subtype":"error","className":"TypeError","description":"TypeError: Cannot read properties of null (reading 'textContent')\n    at <anonymous>:1:39","objectId":"8019873826012258053.2.2"}}
E         at evaluate (file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_people.mjs:44:33)
E         at async file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_people.mjs:63:16
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_meal_plan_p...3)\n    at async file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_people.mjs:63:16\n\nNode.js v24.22.1\n').returncode
_____________ test_meal_plan_browser_journey[vegetarian-desktop] ______________
tests\test_browser_meal_plan.py:47: in test_meal_plan_browser_journey
    assert result.returncode == 0, result.stdout+result.stderr
E   AssertionError: node:internal/modules/run_main:107
E         triggerUncaughtException(
E         ^
E
E     AssertionError [ERR_ASSERTION]: Expected values to be strictly equal:
E
E     0 !== 3
E
E         at checkMeal (file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_vegetarian.mjs:105:56)
E         at async file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_vegetarian.mjs:113:16 {
E       generatedMessage: true,
E       code: 'ERR_ASSERTION',
E       actual: 0,
E       expected: 3,
E       operator: 'strictEqual',
E       diff: 'simple'
E     }
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_meal_plan_v...'ERR_ASSERTION',\n  actual: 0,\n  expected: 3,\n  operator: 'strictEqual',\n  diff: 'simple'\n}\n\nNode.js v24.22.1\n").returncode
______________ test_meal_plan_browser_journey[vegetarian-mobile] ______________
tests\test_browser_meal_plan.py:47: in test_meal_plan_browser_journey
    assert result.returncode == 0, result.stdout+result.stderr
E   AssertionError: node:internal/modules/run_main:107
E         triggerUncaughtException(
E         ^
E
E     AssertionError [ERR_ASSERTION]: Expected values to be strictly equal:
E
E     0 !== 3
E
E         at checkMeal (file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_vegetarian.mjs:105:56)
E         at async file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_vegetarian.mjs:113:16 {
E       generatedMessage: true,
E       code: 'ERR_ASSERTION',
E       actual: 0,
E       expected: 3,
E       operator: 'strictEqual',
E       diff: 'simple'
E     }
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_meal_plan_v...'ERR_ASSERTION',\n  actual: 0,\n  expected: 3,\n  operator: 'strictEqual',\n  diff: 'simple'\n}\n\nNode.js v24.22.1\n").returncode
_____________________ test_browser_user_journey[desktop] ______________________
tests\test_browser_ui.py:54: in test_browser_user_journey
    assert result.returncode == 0, result.stdout + result.stderr
E   AssertionError: file:///D:/Project/lap%20trinh%20mang/tests/browser_ui.mjs:103
E         await wait('performance.timeOrigin !== ' + previousDocument + ' && document.readyState === "complete" && location.pathname === ' + JSON.stringify(new URL(path, location.origin).pathname) + ' && location.search === ' + JSON.stringify(new URL(path, location.origin).search));
E                                                                                                                                                                         ^
E
E     ReferenceError: location is not defined
E         at navigate (file:///D:/Project/lap%20trinh%20mang/tests/browser_ui.mjs:103:165)
E         at async file:///D:/Project/lap%20trinh%20mang/tests/browser_ui.mjs:199:3
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_ui.mjs', 'C..._ui.mjs:103:165)\n    at async file:///D:/Project/lap%20trinh%20mang/tests/browser_ui.mjs:199:3\n\nNode.js v24.22.1\n').returncode
______________________ test_browser_user_journey[mobile] ______________________
tests\test_browser_ui.py:54: in test_browser_user_journey
    assert result.returncode == 0, result.stdout + result.stderr
E   AssertionError: file:///D:/Project/lap%20trinh%20mang/tests/browser_ui.mjs:103
E         await wait('performance.timeOrigin !== ' + previousDocument + ' && document.readyState === "complete" && location.pathname === ' + JSON.stringify(new URL(path, location.origin).pathname) + ' && location.search === ' + JSON.stringify(new URL(path, location.origin).search));
E                                                                                                                                                                         ^
E
E     ReferenceError: location is not defined
E         at navigate (file:///D:/Project/lap%20trinh%20mang/tests/browser_ui.mjs:103:165)
E         at async file:///D:/Project/lap%20trinh%20mang/tests/browser_ui.mjs:199:3
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_ui.mjs', 'C..._ui.mjs:103:165)\n    at async file:///D:/Project/lap%20trinh%20mang/tests/browser_ui.mjs:199:3\n\nNode.js v24.22.1\n').returncode
____________________ test_detail_return_link_allowlist[-/] ____________________
tests\test_meal_plan_ux.py:142: in test_detail_return_link_allowlist
    assert parser.links=={'back':expected,'header-link':expected}
E   AssertionError: assert {'back': '/'} == {'back': '/',...er-link': '/'}
E
E     Omitting 1 identical items, use -vv to show
E     Right contains 1 more item:
E     {'header-link': '/'}
E     Use -v to get more diff
_____________ test_detail_return_link_allowlist[?return_to=%2F-/] _____________
tests\test_meal_plan_ux.py:142: in test_detail_return_link_allowlist
    assert parser.links=={'back':expected,'header-link':expected}
E   AssertionError: assert {'back': '/'} == {'back': '/',...er-link': '/'}
E
E     Omitting 1 identical items, use -vv to show
E     Right contains 1 more item:
E     {'header-link': '/'}
E     Use -v to get more diff
____ test_detail_return_link_allowlist[?return_to=%2Fmeal-plan-/meal-plan] ____
tests\test_meal_plan_ux.py:142: in test_detail_return_link_allowlist
    assert parser.links=={'back':expected,'header-link':expected}
E   AssertionError: assert {'back': '/meal-plan'} == {'back': '/me... '/meal-plan'}
E
E     Omitting 1 identical items, use -vv to show
E     Right contains 1 more item:
E     {'header-link': '/meal-plan'}
E     Use -v to get more diff
_ test_detail_return_link_allowlist[?return_to=https%3A%2F%2Fevil.example-/] __
tests\test_meal_plan_ux.py:142: in test_detail_return_link_allowlist
    assert parser.links=={'back':expected,'header-link':expected}
E   AssertionError: assert {'back': '/'} == {'back': '/',...er-link': '/'}
E
E     Omitting 1 identical items, use -vv to show
E     Right contains 1 more item:
E     {'header-link': '/'}
E     Use -v to get more diff
_____ test_detail_return_link_allowlist[?return_to=%2F%2Fevil.example-/] ______
tests\test_meal_plan_ux.py:142: in test_detail_return_link_allowlist
    assert parser.links=={'back':expected,'header-link':expected}
E   AssertionError: assert {'back': '/'} == {'back': '/',...er-link': '/'}
E
E     Omitting 1 identical items, use -vv to show
E     Right contains 1 more item:
E     {'header-link': '/'}
E     Use -v to get more diff
____ test_detail_return_link_allowlist[?return_to=javascript%3Aalert(1)-/] ____
tests\test_meal_plan_ux.py:142: in test_detail_return_link_allowlist
    assert parser.links=={'back':expected,'header-link':expected}
E   AssertionError: assert {'back': '/'} == {'back': '/',...er-link': '/'}
E
E     Omitting 1 identical items, use -vv to show
E     Right contains 1 more item:
E     {'header-link': '/'}
E     Use -v to get more diff
____ test_detail_return_link_allowlist[?return_to=%2Fmeal-plan%3Fx%3D1-/] _____
tests\test_meal_plan_ux.py:142: in test_detail_return_link_allowlist
    assert parser.links=={'back':expected,'header-link':expected}
E   AssertionError: assert {'back': '/'} == {'back': '/',...er-link': '/'}
E
E     Omitting 1 identical items, use -vv to show
E     Right contains 1 more item:
E     {'header-link': '/'}
E     Use -v to get more diff
_ test_detail_return_link_allowlist[?return_to=%2Fmeal-plan&return_to=%2F-/] __
tests\test_meal_plan_ux.py:142: in test_detail_return_link_allowlist
    assert parser.links=={'back':expected,'header-link':expected}
E   AssertionError: assert {'back': '/'} == {'back': '/',...er-link': '/'}
E
E     Omitting 1 identical items, use -vv to show
E     Right contains 1 more item:
E     {'header-link': '/'}
E     Use -v to get more diff
_____ test_complete_actual_mysql_catalog_preserves_namespaces_and_ranges ______
tests\test_mysql_calculation_v2.py:93: in test_complete_actual_mysql_catalog_preserves_namespaces_and_ranges
    assert data["status"] == "COMPLETE" and data["totals_complete"]
E   AssertionError: assert ('INCOMPLETE' == 'COMPLETE'
E
E     - COMPLETE
E     + INCOMPLETE
E     ? ++)
_ test_editing_approved_values_invalidates_their_review[UPDATE v2_units SET definition='EDITED_AFTER_REVIEW' WHERE id=1-UNIT_NOT_APPROVED] _
tests\test_mysql_calculation_v2.py:136: in test_editing_approved_values_invalidates_their_review
    assert data["status"] == "INCOMPLETE" and expected in reasons(data)
E   AssertionError: assert ('INCOMPLETE' == 'INCOMPLETE'
E
E       INCOMPLETE and 'UNIT_NOT_APPROVED' in {'LINE_NOT_APPROVED'})
E    +  where {'LINE_NOT_APPROVED'} = reasons({'calculation_version': 'portion-v1', 'recipe_ids': [1, 2], 'people': 4, 'adults': 4, ...})
____ test_approved_but_invalid_or_unknown_quantities_are_still_incomplete _____
tests\test_mysql_calculation_v2.py:157: in test_approved_but_invalid_or_unknown_quantities_are_still_incomplete
    assert "INVALID_QUANTITY" in reasons(calculation(connection))
E   AssertionError: assert 'INVALID_QUANTITY' in {'LINE_NOT_APPROVED'}
E    +  where {'LINE_NOT_APPROVED'} = reasons({'calculation_version': 'portion-v1', 'recipe_ids': [1, 2], 'people': 4, 'adults': 4, ...})
E    +    where {'calculation_version': 'portion-v1', 'recipe_ids': [1, 2], 'people': 4, 'adults': 4, ...} = calculation(<mysql.connector.connection_cext.CMySQLConnection object at 0x0000027EAA453ED0>)
__________ test_disable_rolls_back_activation_without_deleting_data ___________
tests\test_mysql_calculation_v2.py:235: in test_disable_rolls_back_activation_without_deleting_data
    assert calculation(connection)["status"] == "COMPLETE"
E   AssertionError: assert 'INCOMPLETE' == 'COMPLETE'
E
E     - COMPLETE
E     + INCOMPLETE
E     ? ++
______ test_adapter_uses_consistent_snapshot_even_if_writer_changes_data ______
tests\test_mysql_calculation_v2.py:259: in test_adapter_uses_consistent_snapshot_even_if_writer_changes_data
    assert changed and data["status"] == "COMPLETE"
E   AssertionError: assert ([True] and 'INCOMPLETE' == 'COMPLETE'
E
E     - COMPLETE
E     + INCOMPLETE
E     ? ++)
____ test_real_mysql_tcp_http_with_select_only_runtime_and_database_error _____
tests\test_mysql_calculation_v2.py:295: in test_real_mysql_tcp_http_with_select_only_runtime_and_database_error
    assert response.status_code == 200 and response.json()["data"]["status"] == "COMPLETE"
E   assert (503 == 200)
E    +  where 503 = <Response [503 Service Unavailable]>.status_code
___ test_backup_restore_to_another_private_schema_retains_approved_release ____
tests\test_mysql_calculation_v2.py:334: in test_backup_restore_to_another_private_schema_retains_approved_release
    assert calculation(clone)['status'] == 'COMPLETE'
E   AssertionError: assert 'INCOMPLETE' == 'COMPLETE'
E
E     - COMPLETE
E     + INCOMPLETE
E     ? ++
___________________ test_mysql_multiclient_and_http_outage ____________________
tests\test_mysql_integration.py:104: in test_mysql_multiclient_and_http_outage
    assert response.status_code == 503
E   assert 504 == 503
E    +  where 504 = <Response [504 Gateway Timeout]>.status_code
______ test_legacy_outputs_identical_with_publication_active_or_inactive ______
tests\test_mysql_recipe_publication.py:320: in test_legacy_outputs_identical_with_publication_active_or_inactive
    assert active==inactive
E   AssertionError: assert [{'version': ...s': []}, ...}] == [{'version': ...s': []}, ...}]
E
E     At index 1 diff: {'version': 1, 'request_id': 'e35954bb-19f1-40a6-a8d2-77288ead8050', 'ok': True, 'data': {'classification_version': 'meal-categories-v1:v2:8f00aa6427457a7b', 'algorithm': 'meal-plan-v1', 'plan': {'items': [{'slot': 'main', 'recipe_id': 3, 'title': 'TEST_ONLY legacy recipe 3', 'minutes': 10, 'matched_ids': [], 'missing_ids': [], 'missing_count': 0}, {'slot': 'vegetable', 'recipe_id': 5, 'title': 'TEST_ONLY legacy recipe 5', 'minutes': 10, 'matched_ids': [], 'missing_ids': [], 'missing_count': 0}, {'slot': 'soup', 'recipe_id': 6, 'title': 'TEST_ONLY legac...
E
E     ...Full output truncated, use '-vv' to show
_______ test_published_v2_browser_after_50_legacy_ingredients[desktop] ________
tests\test_mysql_recipe_publication.py:480: in test_published_v2_browser_after_50_legacy_ingredients
    assert result.returncode==0,result.stdout+result.stderr
E   AssertionError: node:internal/modules/run_main:107
E         triggerUncaughtException(
E         ^
E
E     AssertionError [ERR_ASSERTION]: Browser interaction marker was written
E         at file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_admin_version.mjs:49:74 {
E       generatedMessage: false,
E       code: 'ERR_ASSERTION',
E       actual: null,
E       expected: true,
E       operator: '==',
E       diff: 'simple'
E     }
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_meal_plan_a...e: 'ERR_ASSERTION',\n  actual: null,\n  expected: true,\n  operator: '==',\n  diff: 'simple'\n}\n\nNode.js v24.22.1\n").returncode
________ test_published_v2_browser_after_50_legacy_ingredients[mobile] ________
tests\test_mysql_recipe_publication.py:480: in test_published_v2_browser_after_50_legacy_ingredients
    assert result.returncode==0,result.stdout+result.stderr
E   AssertionError: node:internal/modules/run_main:107
E         triggerUncaughtException(
E         ^
E
E     AssertionError [ERR_ASSERTION]: Browser interaction marker was written
E         at file:///D:/Project/lap%20trinh%20mang/tests/browser_meal_plan_admin_version.mjs:49:74 {
E       generatedMessage: false,
E       code: 'ERR_ASSERTION',
E       actual: null,
E       expected: true,
E       operator: '==',
E       diff: 'simple'
E     }
E
E     Node.js v24.22.1
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['C:\\Program Files\\nodejs\\node.EXE', 'D:\\Project\\lap trinh mang\\tests\\browser_meal_plan_a...e: 'ERR_ASSERTION',\n  actual: null,\n  expected: true,\n  operator: '==',\n  diff: 'simple'\n}\n\nNode.js v24.22.1\n").returncode
_ test_draft_crosswalk_uses_schema_default_without_extra_status_grant_test_only _
tests\test_mysql_repository_transactions.py:266: in test_draft_crosswalk_uses_schema_default_without_extra_status_grant_test_only
    assert saved.status_code == 200, saved.json()
E   AssertionError: {'version': 1, 'request_id': '71d478c3-1fc7-4c13-813b-40242b0e85ce', 'ok': False, 'data': None, ...}
E   assert 422 == 200
E    +  where 422 = <Response [422 Unprocessable Entity]>.status_code
_______ test_server_loads_log_and_startup_settings_before_use[default] ________
tests\test_server_log_config.py:62: in test_server_loads_log_and_startup_settings_before_use
    assert result.returncode == 0, result.stdout + result.stderr
E   AssertionError: Traceback (most recent call last):
E       File "<string>", line 18, in <module>
E         module["main"]()
E         ~~~~~~~~~~~~~~^^
E       File "D:\Project\lap trinh mang\.test_runtime\season-20261113\test_server_loads_log_and_star0\project\source\server\main.py", line 240, in main
E         TCPServer(os.getenv("TCP_HOST", "127.0.0.1"), int(os.getenv("TCP_PORT", "9000")),
E         ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E                   max_connections=configured_tcp_max_connections()).serve_forever()
E                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E     TypeError: StartupProbe.__init__() got an unexpected keyword argument 'max_connections'
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['D:\\Project\\lap trinh mang\\.venv\\Scripts\\python.exe', '-B', '-c', '\nimport json, runpy, s...^^^^^^^^^^^^^^^^^^^^^^^^\nTypeError: StartupProbe.__init__() got an unexpected keyword argument \'max_connections\'\n').returncode
________ test_server_loads_log_and_startup_settings_before_use[dotenv] ________
tests\test_server_log_config.py:62: in test_server_loads_log_and_startup_settings_before_use
    assert result.returncode == 0, result.stdout + result.stderr
E   AssertionError: Traceback (most recent call last):
E       File "<string>", line 18, in <module>
E         module["main"]()
E         ~~~~~~~~~~~~~~^^
E       File "D:\Project\lap trinh mang\.test_runtime\season-20261113\test_server_loads_log_and_star1\project\source\server\main.py", line 240, in main
E         TCPServer(os.getenv("TCP_HOST", "127.0.0.1"), int(os.getenv("TCP_PORT", "9000")),
E         ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E                   max_connections=configured_tcp_max_connections()).serve_forever()
E                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E     TypeError: StartupProbe.__init__() got an unexpected keyword argument 'max_connections'
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['D:\\Project\\lap trinh mang\\.venv\\Scripts\\python.exe', '-B', '-c', '\nimport json, runpy, s...^^^^^^^^^^^^^^^^^^^^^^^^\nTypeError: StartupProbe.__init__() got an unexpected keyword argument \'max_connections\'\n').returncode
___ test_server_loads_log_and_startup_settings_before_use[process_override] ___
tests\test_server_log_config.py:62: in test_server_loads_log_and_startup_settings_before_use
    assert result.returncode == 0, result.stdout + result.stderr
E   AssertionError: Traceback (most recent call last):
E       File "<string>", line 18, in <module>
E         module["main"]()
E         ~~~~~~~~~~~~~~^^
E       File "D:\Project\lap trinh mang\.test_runtime\season-20261113\test_server_loads_log_and_star2\project\source\server\main.py", line 240, in main
E         TCPServer(os.getenv("TCP_HOST", "127.0.0.1"), int(os.getenv("TCP_PORT", "9000")),
E         ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E                   max_connections=configured_tcp_max_connections()).serve_forever()
E                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E     TypeError: StartupProbe.__init__() got an unexpected keyword argument 'max_connections'
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['D:\\Project\\lap trinh mang\\.venv\\Scripts\\python.exe', '-B', '-c', '\nimport json, runpy, s...^^^^^^^^^^^^^^^^^^^^^^^^\nTypeError: StartupProbe.__init__() got an unexpected keyword argument \'max_connections\'\n').returncode
___ test_server_loads_log_and_startup_settings_before_use[dotenv_disabled] ____
tests\test_server_log_config.py:62: in test_server_loads_log_and_startup_settings_before_use
    assert result.returncode == 0, result.stdout + result.stderr
E   AssertionError: Traceback (most recent call last):
E       File "<string>", line 18, in <module>
E         module["main"]()
E         ~~~~~~~~~~~~~~^^
E       File "D:\Project\lap trinh mang\.test_runtime\season-20261113\test_server_loads_log_and_star3\project\source\server\main.py", line 240, in main
E         TCPServer(os.getenv("TCP_HOST", "127.0.0.1"), int(os.getenv("TCP_PORT", "9000")),
E         ~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E                   max_connections=configured_tcp_max_connections()).serve_forever()
E                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E     TypeError: StartupProbe.__init__() got an unexpected keyword argument 'max_connections'
E
E   assert 1 == 0
E    +  where 1 = CompletedProcess(args=['D:\\Project\\lap trinh mang\\.venv\\Scripts\\python.exe', '-B', '-c', '\nimport json, runpy, s...^^^^^^^^^^^^^^^^^^^^^^^^\nTypeError: StartupProbe.__init__() got an unexpected keyword argument \'max_connections\'\n').returncode
_ test_backup_import_is_repeatable_and_keeps_effective_public_catalog_test_only _
tests\test_unified_catalog_migration.py:104: in test_backup_import_is_repeatable_and_keeps_effective_public_catalog_test_only
    assert create_schema(target) == 14
E   assert 20 == 14
E    +  where 20 = create_schema(<mysql.connector.connection_cext.CMySQLConnection object at 0x0000027EC8C13B10>)
________ test_daily_combo_history_roundtrips_http_tcp_mysql_test_only _________
tests\test_unified_http_tcp.py:201: in test_daily_combo_history_roundtrips_http_tcp_mysql_test_only
    assert first["plan"] is not None
E   assert None is not None
_______________ test_unified_http_tcp_admin_user_and_meal_flows _______________
tests\test_unified_http_tcp.py:340: in test_unified_http_tcp_admin_user_and_meal_flows
    assert required["quantity_value"] == "10" and other_unit["quantity_value"] == "5" and optional["quantity_value"] == "1"
E   AssertionError: assert ('5' == '10'
E
E     - 10
E     + 5)
___________________ test_unified_admin_to_user_browser_flow ___________________
tests\test_unified_http_tcp.py:646: in test_unified_admin_to_user_browser_flow
    page.locator("#draft-lines .admin-line [data-form]").fill("TEST_ONLY cut")
.venv\Lib\site-packages\playwright\sync_api\_generated.py:11640: in fill
    self._sync(
.venv\Lib\site-packages\playwright\_impl\_locator.py:228: in fill
    return await self._frame.fill(self._selector, strict=True, **params)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv\Lib\site-packages\playwright\_impl\_frame.py:641: in fill
    await self._fill(**locals_to_params(locals()))
.venv\Lib\site-packages\playwright\_impl\_frame.py:653: in _fill
    await self._channel.send("fill", self._timeout, locals_to_params(locals()))
.venv\Lib\site-packages\playwright\_impl\_connection.py:78: in send
    return await self._connection.wrap_api_call(
.venv\Lib\site-packages\playwright\_impl\_connection.py:636: in wrap_api_call
    raise rewrite_error(error, f"{parsed_st['apiName']}: {error}") from None
E   playwright._impl._errors.TimeoutError: Locator.fill: Timeout 10000ms exceeded.
E   Call log:
E     - waiting for locator("#draft-lines .admin-line [data-form]")
E       - locator resolved to <input data-form="1" maxlength="120" placeholder="D\u1ea1ng s\u01a1 ch\u1ebf"/>
E       - fill("TEST_ONLY cut")
E     - attempting fill action
E       2 � waiting for element to be visible, enabled and editable
E         - element is not visible
E       - retrying fill action
E       - waiting 20ms
E       2 � waiting for element to be visible, enabled and editable
E         - element is not visible
E       - retrying fill action
E         - waiting 100ms
E       20 � waiting for element to be visible, enabled and editable
E          - element is not visible
E        - retrying fill action
E          - waiting 500ms
________________ test_portion_display_playwright_unified_mysql ________________
tests\test_unified_http_tcp.py:966: in test_portion_display_playwright_unified_mysql
    page.wait_for_function("document.querySelectorAll('[data-meal-slot]').length===3 && document.getElementById('meal-results').getAttribute('aria-busy')==='false'")
.venv\Lib\site-packages\playwright\sync_api\_generated.py:21235: in wait_for_function
    self._sync(
.venv\Lib\site-packages\playwright\_impl\_page.py:1158: in wait_for_function
    return await self._main_frame.wait_for_function(**locals_to_params(locals()))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
.venv\Lib\site-packages\playwright\_impl\_frame.py:945: in wait_for_function
    await self._channel.send("waitForFunction", self._timeout, params)
.venv\Lib\site-packages\playwright\_impl\_connection.py:78: in send
    return await self._connection.wrap_api_call(
.venv\Lib\site-packages\playwright\_impl\_connection.py:636: in wrap_api_call
    raise rewrite_error(error, f"{parsed_st['apiName']}: {error}") from None
E   playwright._impl._errors.TimeoutError: Page.wait_for_function: Timeout 30000ms exceeded.
______ test_admin_permanent_recipe_delete_playwright_desktop_and_mobile _______
tests\test_unified_http_tcp.py:1346: in test_admin_permanent_recipe_delete_playwright_desktop_and_mobile
    assert page.locator('script[src="/static/admin.js?v=permanent-delete-errors-20261111"]').count() == 1
E   assert 0 == 1
E    +  where 0 = count()
E    +    where count = <Locator frame=<Frame name= url='http://127.0.0.1:63010/admin'> selector='script[src="/static/admin.js?v=permanent-delete-errors-20261111"]'>.count
E    +      where <Locator frame=<Frame name= url='http://127.0.0.1:63010/admin'> selector='script[src="/static/admin.js?v=permanent-delete-errors-20261111"]'> = locator('script[src="/static/admin.js?v=permanent-delete-errors-20261111"]')
E    +        where locator = <Page url='http://127.0.0.1:63010/admin'>.locator
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  D:\Project\lap trinh mang\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv\Lib\site-packages\_pytest\cacheprovider.py:487
  D:\Project\lap trinh mang\.venv\Lib\site-packages\_pytest\cacheprovider.py:487: PytestCacheWarning: could not create cache path D:\Project\lap trinh mang\.pytest_cache\v\cache\nodeids: [WinError 5] Access is denied: 'D:\\Project\\lap trinh mang\\.pytest_cache\\v\\cache'
    config.cache.set("cache/nodeids", sorted(str(n) for n in self.cached_nodeids))

.venv\Lib\site-packages\_pytest\cacheprovider.py:439
  D:\Project\lap trinh mang\.venv\Lib\site-packages\_pytest\cacheprovider.py:439: PytestCacheWarning: could not create cache path D:\Project\lap trinh mang\.pytest_cache\v\cache\lastfailed: [WinError 5] Access is denied: 'D:\\Project\\lap trinh mang\\.pytest_cache\\v\\cache'
    config.cache.set("cache/lastfailed", current_lastfailed)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ===========================
FAILED tests/test_admin.py::test_admin_draft_gateway_requires_csrf_and_validates_before_tcp
FAILED tests/test_admin.py::test_admin_create_distinguishes_expired_session_csrf_and_writer_denial
FAILED tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[legacy-desktop]
FAILED tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[legacy-mobile]
FAILED tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[flexible-desktop]
FAILED tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[flexible-mobile]
FAILED tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[people-desktop]
FAILED tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[people-mobile]
FAILED tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[vegetarian-desktop]
FAILED tests/test_browser_meal_plan.py::test_meal_plan_browser_journey[vegetarian-mobile]
FAILED tests/test_browser_ui.py::test_browser_user_journey[desktop] - Asserti...
FAILED tests/test_browser_ui.py::test_browser_user_journey[mobile] - Assertio...
FAILED tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[-/] - As...
FAILED tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=%2F-/]
FAILED tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=%2Fmeal-plan-/meal-plan]
FAILED tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=https%3A%2F%2Fevil.example-/]
FAILED tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=%2F%2Fevil.example-/]
FAILED tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=javascript%3Aalert(1)-/]
FAILED tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=%2Fmeal-plan%3Fx%3D1-/]
FAILED tests/test_meal_plan_ux.py::test_detail_return_link_allowlist[?return_to=%2Fmeal-plan&return_to=%2F-/]
FAILED tests/test_mysql_calculation_v2.py::test_complete_actual_mysql_catalog_preserves_namespaces_and_ranges
FAILED tests/test_mysql_calculation_v2.py::test_editing_approved_values_invalidates_their_review[UPDATE v2_units SET definition='EDITED_AFTER_REVIEW' WHERE id=1-UNIT_NOT_APPROVED]
FAILED tests/test_mysql_calculation_v2.py::test_approved_but_invalid_or_unknown_quantities_are_still_incomplete
FAILED tests/test_mysql_calculation_v2.py::test_disable_rolls_back_activation_without_deleting_data
FAILED tests/test_mysql_calculation_v2.py::test_adapter_uses_consistent_snapshot_even_if_writer_changes_data
FAILED tests/test_mysql_calculation_v2.py::test_real_mysql_tcp_http_with_select_only_runtime_and_database_error
FAILED tests/test_mysql_calculation_v2.py::test_backup_restore_to_another_private_schema_retains_approved_release
FAILED tests/test_mysql_integration.py::test_mysql_multiclient_and_http_outage
FAILED tests/test_mysql_recipe_publication.py::test_legacy_outputs_identical_with_publication_active_or_inactive
FAILED tests/test_mysql_recipe_publication.py::test_published_v2_browser_after_50_legacy_ingredients[desktop]
FAILED tests/test_mysql_recipe_publication.py::test_published_v2_browser_after_50_legacy_ingredients[mobile]
FAILED tests/test_mysql_repository_transactions.py::test_draft_crosswalk_uses_schema_default_without_extra_status_grant_test_only
FAILED tests/test_server_log_config.py::test_server_loads_log_and_startup_settings_before_use[default]
FAILED tests/test_server_log_config.py::test_server_loads_log_and_startup_settings_before_use[dotenv]
FAILED tests/test_server_log_config.py::test_server_loads_log_and_startup_settings_before_use[process_override]
FAILED tests/test_server_log_config.py::test_server_loads_log_and_startup_settings_before_use[dotenv_disabled]
FAILED tests/test_unified_catalog_migration.py::test_backup_import_is_repeatable_and_keeps_effective_public_catalog_test_only
FAILED tests/test_unified_http_tcp.py::test_daily_combo_history_roundtrips_http_tcp_mysql_test_only
FAILED tests/test_unified_http_tcp.py::test_unified_http_tcp_admin_user_and_meal_flows
FAILED tests/test_unified_http_tcp.py::test_unified_admin_to_user_browser_flow
FAILED tests/test_unified_http_tcp.py::test_portion_display_playwright_unified_mysql
FAILED tests/test_unified_http_tcp.py::test_admin_permanent_recipe_delete_playwright_desktop_and_mobile
42 failed, 1111 passed, 3 warnings in 570.48s (0:09:30)

```
