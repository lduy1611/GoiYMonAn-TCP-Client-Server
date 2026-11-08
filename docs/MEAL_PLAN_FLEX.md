# Ghim món và mâm linh hoạt — meal-plan-v2

Triển khai ngày 05/11/2026. Đây là phiên bản **thuật toán/operation**, dùng nguyên dataset và mapping vai trò đã duyệt của v1; chưa triển khai schema/dataset v2, khẩu phần, vùng, chay/mặn, dịp hoặc giá.

## Phạm vi và giới hạn

- `/meal-plan`: giao diện mới, ghim/bỏ ghim từng món; cấu hình mỗi nhóm chính/rau/canh từ 0–2 món, tổng 1–6 món.
- `/meal-plan/v1`: giao diện ba món cũ và cache cũ vẫn sử dụng được. Có liên kết từ trang mới.
- API cũ `POST /api/meal-plan`, operation `GENERATE_MEAL_PLAN`, code thuật toán `meal_plan.py` và hợp đồng v1 giữ nguyên.
- API mới `POST /api/meal-plan/v2` chuyển tiếp `GENERATE_MEAL_PLAN_V2`. Nghiệp vụ chạy trên TCP Server qua repository MySQL chỉ đọc.
- Không cho trùng recipe ID trên cả mâm. Món chỉ được dùng theo vai trò đã duyệt; main nghĩa món chính, không phải phân loại chế độ ăn.
- Thời gian mỗi món tối đa 240 phút; tổng thời gian v2 tối đa 1.440 phút (6 × 240). Đây vẫn là cộng thời gian công thức, chưa tính nấu song song.
- Số loại thiếu là union nguyên liệu bắt buộc. Loại trừ áp dụng cả nguyên liệu tùy chọn, giống v1.
- Danh sách mua tái sử dụng build_shopping_lists, giữ từng chuỗi định lượng theo công thức. Chưa nhân theo người, cộng các đơn vị hoặc trừ tồn kho theo số lượng.

Giới hạn hai món mỗi nhóm giữ tìm kiếm toàn bộ tối đa C(23,2) × C(4,2) × C(6,2) = 22.770 tổ hợp trong catalog hiện tại; không cần cắt bỏ ứng viên theo heuristic. Cấu hình khác có ít tổ hợp hơn. Đây là giới hạn sản phẩm ở giai đoạn này, không phải tuyên bố mọi bộ lọc đều có đủ món.

## Hợp đồng TCP mới

Envelope không đổi: JSON UTF-8, protocol version 1, UUID request_id, header 4 byte, body tối đa 65.536 byte.

| Payload | Ý nghĩa/validation |
|---|---|
| ingredient_ids / excluded_ids | Tối đa 30 ID mỗi nhóm, nguyên dương tồn tại; không giao nhau; filter validation dùng lại v1 |
| max_minutes / max_missing | null hoặc lần lượt 1–240 / 0–50 |
| max_total_minutes | null hoặc 1–1440 |
| counts | Đủ main, vegetable, soup; mỗi giá trị nguyên 0–2, tổng ≥1; mặc định mỗi nhóm 1 |
| current_plan | Object vị trí → recipe ID; tối đa 6, không trùng công thức, vị trí liên tiếp trong nhóm; mặc định {} |
| locked_slots | Danh sách vị trí trong current_plan, không trùng, tối đa 6 |
| replace_slot | Vị trí cụ thể cần đổi; current_plan phải có cùng cấu trúc counts |
| action | generate (mặc định) hoặc regenerate |
| avoid_recipe_ids | Lịch sử theo nhóm main/vegetable/soup, tối đa tổng 50 ID; cần current_plan nếu có lịch sử |

Vị trí là main:1/main:2, vegetable:1/vegetable:2, soup:1/soup:2. ID phải tồn tại và đúng nhóm mapping; việc dùng dấu ':' không tạo taxonomy hay nhãn mới.

Ví dụ request đổi cả mâm, giữ món chính thứ nhất, các ID đều thuộc dữ liệu hiện có:

```json
{
  "version": 1,
  "request_id": "e35954bb-19f1-40a6-a8d2-77288ead8050",
  "op": "GENERATE_MEAL_PLAN_V2",
  "payload": {
    "action": "regenerate",
    "counts": {"main": 1, "vegetable": 1, "soup": 1},
    "current_plan": {"main:1": 1, "vegetable:1": 5, "soup:1": 29},
    "locked_slots": ["main:1"],
    "ingredient_ids": [1, 2, 6, 7],
    "excluded_ids": [],
    "max_minutes": 60
  }
}
```

Không chấp nhận các trường metadata/giá/khẩu phần chưa được triển khai. CLI đã thêm lựa chọn operation mới; `--payload` JSON và TCP Client hiện có được tái sử dụng.

## Quy tắc ghim, đổi và áp dụng điều kiện

1. Chọn tổ hợp theo nhóm, cố định các vị trí locked_slots, giữ các công thức còn sống ở vị trí cũ rồi điền các vị trí còn lại. Chỉ đảo vị trí hai công thức không được coi là đổi món.
2. Đổi một món: server tự khóa toàn bộ vị trí khác, kể cả khi client không gửi các vị trí đó trong locked_slots. Món đích đang ghim trả PINNED_TARGET.
3. Đổi cả mâm: action=regenerate bắt buộc có thay đổi nếu có current_plan, giữ mọi vị trí ghim. Ghim toàn bộ trả ALL_LOCKED, plan=null; giao diện giữ mâm.
4. Tạo/áp dụng điều kiện: action=generate có thể trả lại cùng mâm nếu đó là phương án hợp lệ; điều này cho phép xác nhận bộ lọc mới mà không báo đổi thành công giả. Món ghim vẫn bắt buộc giữ nguyên.
5. Khi thay counts, có thể gửi current_plan theo cấu trúc cũ để giữ pin. Nếu counts mới loại vị trí đang ghim, trả PINNED_SLOT_REMOVED, không chuyển vị trí hoặc bỏ ghim ngầm.
6. Món khóa bị loại bởi nguyên liệu loại trừ hoặc thời gian từng món trả LOCKED_RECIPE_INCOMPATIBLE. Tổng thời gian/max_missing cũng không được nới để giữ một mâm không hợp lệ.
7. Xếp hạng sau lọc: ưu tiên vị trí đổi sang món chưa thấy, số vị trí thực sự thay đổi, ít loại thiếu, nhiều loại có sẵn, ít lượt thiếu theo món, thời gian và bộ ID. Không gọi hoặc sửa B0/P1.
8. Giữ lịch sử theo nhóm để tránh lặp; khi hết ứng viên mới có thể dùng lại lịch sử với HISTORY_RECYCLED, nhưng vẫn phải có đổi thực sự khi yêu cầu regenerate/replace.

Response chứa algorithm=meal-plan-v2, classification_version cũ, dataset_version, counts, plan, changed_slots, warnings, reason. Các item/shopping fields dùng lại ý nghĩa v1 với tối đa 6 món/uses. changed_slots gồm cả vị trí thêm hoặc bỏ khi đổi counts; không chỉ các vị trí còn trong mâm mới.

## Lỗi và thiếu món

Thiếu phương án là business outcome `ok=true, plan=null`, không phải lỗi socket. reason gồm code, message, slots, groups (group/requested/available), suggestions.

| Code | Cách xử lý |
|---|---|
| INSUFFICIENT_GROUP | Hiển thị số cần/còn phù hợp; gợi ý giảm số món, tăng thời gian hoặc xem lại loại trừ |
| PINNED_SLOT_REMOVED | Tăng lại số món nhóm hoặc người dùng tự bỏ ghim |
| PINNED_TARGET / ALL_LOCKED | Người dùng bỏ ghim khi thật sự muốn đổi |
| LOCKED_RECIPE_INCOMPATIBLE | Nêu vị trí xung đột; điều chỉnh filter hoặc tự bỏ ghim |
| CONSTRAINTS_UNSATISFIED / NO_ALTERNATIVE | Tăng giới hạn/giảm số món/điều chỉnh ghim, không tự áp dụng gợi ý |
| RESULT_TOO_LARGE | Giảm số món; server trả response nhỏ trong frame hiện có |

Sau khi tạo shopping list, handler encode thử đúng envelope để kiểm tra frame. Nếu vượt giới hạn, thay bằng business outcome RESULT_TOO_LARGE, không gửi frame quá lớn hoặc để connection chết mà không có lý do. Các frame/operation cũ không đổi.

HTTP input lỗi: 422; TCP timeout: 504; upstream không sẵn sàng: 503; response schema/protocol lỗi: 502. Server cũ không biết v2 trả UNKNOWN_OPERATION; giao diện hướng dẫn khởi động server mới hoặc mở bản ba món cũ.

## Trạng thái trình duyệt

- Namespace mới goiy-meal-plan-v2, không ghi đè goiy-meal-plan-v1 hoặc goiy-selection-v1.
- Lưu counts, bộ lọc, mâm cùng điều kiện thực sự sinh mâm đó, pins, lịch sử, thông báo và vị trí cuộn.
- Đổi filter/counts giữ mâm và pin trước, hiện thông báo chưa áp dụng; tạm ẩn shopping list cũ để tránh hiểu là danh sách của bộ lọc mới.
- Kết quả mới chỉ được nhận nếu sequence và chữ ký điều kiện vẫn khớp; input hoặc thao tác ghim hủy HTTP cũ. Test vận chuyển cố ý bỏ qua abort vẫn phải không nhận phản hồi cũ.
- Lỗi/timeout/không có mâm mới không ghi đè mâm trước hoặc tự bỏ ghim. Retry giữ thao tác tương ứng khi còn ở trang.
- Back/reload khôi phục snapshot hợp lệ mà không tự POST. Cache hỏng/khác phiên bản dữ liệu được thông báo không thể khôi phục, không coi nội dung không hợp lệ là món ghim đáng tin cậy.
- Bản v1 tại /meal-plan/v1 giữ cache cũ; không tự chuyển snapshot v1 thành v2. Liên kết chi tiết chỉ nhận allowlist '/', '/meal-plan', '/meal-plan/v1'.

## File thay đổi trong lượt triển khai

| Nhóm | File |
|---|---|
| Thuật toán mới | source/server/meal_plan_v2.py |
| Đăng ký và dispatch | source/common/protocol.py; source/client/cli.py; source/server/handler.py |
| Transport/web | source/web/meal_plan_v2_contract.py; source/web/main.py |
| Giao diện mới | source/web/static/meal-plan-v2.js; source/web/templates/meal_plan_v2.html; source/web/static/meal-plan.css |
| Giữ đường về v1/cache assets | source/web/static/meal-plan.js; source/web/static/detail.js; source/web/templates/meal_plan.html; source/web/templates/detail.html |
| Test mới | tests/test_meal_plan_v2.py; tests/browser_meal_plan_v2.mjs |
| Test hồi quy cập nhật | tests/test_browser_meal_plan.py; tests/browser_meal_plan.mjs; tests/test_web_meal_plan.py; tests/test_mysql_integration.py |
| Tài liệu mới | docs/MEAL_PLAN_FLEX.md |

Các thay đổi search/homepage và log đã tồn tại trước lượt này được giữ nguyên, không được tính là thay đổi mới của chức năng ghim/số món.

## Kiểm thử và vận hành

Đã đạt 342 kiểm thử ngoài trình duyệt, gồm toàn bộ 26 cấu hình counts hợp lệ, ghim 1/nhiều/toàn bộ món, thay cấu trúc khi ghim, đổi riêng một món, thiếu nhóm, optional exclusions, tổng thời gian/missing, lịch sử/thứ tự ổn định, request invalid, MySQL và v1/RECOMMEND/SEARCH/B0/P1. Có kiểm tra response unicode vượt frame và socket vẫn dùng được, cùng tìm kiếm tổ hợp lớn nhất trong ngân sách transport.

Đã đạt 6 kiểm thử Chrome thực: trang tìm/gợi ý, mâm v1 và mâm v2 ở 1280/390 px; có kiểm tra tràn ngang 320 px. Bao gồm Back/reload, snapshot dirty khi giảm counts đang ghim, error/malformed/timeout, retry, phản hồi cũ thành công/lỗi đến muộn, cách ly cache. Đã xem ảnh chụp desktop/mobile. Đây là headless emulation, chưa phải kiểm tra trên điện thoại vật lý.

Ví dụ chạy lại trong PowerShell, dùng đường dẫn basetemp mới/chưa tồn tại và giữ log tách riêng:

```powershell
New-Item -ItemType Directory -Force -Path statics/runtime/meal-flex-tests | Out-Null
$env:TCP_LOG_PATH = 'statics/runtime/meal-flex-tests/recheck.jsonl'
.venv/Scripts/python.exe -m pytest tests -q --basetemp=statics/runtime/meal-flex-tests/recheck
```

Chrome headless cần chạy ngoài sandbox trong môi trường hiện tại. Các warning quan sát được là deprecation của thư viện web, không phải test thất bại. Không dùng số test/thời gian này thay số liệu báo cáo đã nộp.

Sau khi bổ sung case HTTP 504 vào hành trình v2, đã chạy lại cả desktop/mobile: 2 passed. Kiểm tra cú pháp JavaScript và diff whitespace đạt. So sánh hash với trạng thái đầu lượt xác nhận dataset/seed, docs/data-v2, báo cáo, log thực nghiệm, B0/P1, meal-plan-v1 và hợp đồng v1 không đổi; tag v1.0-report giữ nguyên. Đối chiếu MySQL sau test bằng transaction chỉ đọc: 50 món/50 nguyên liệu/252 quan hệ vẫn khớp SQL gốc và hướng dẫn r1. Không chạy migration hoặc cập nhật dữ liệu.

### Kiểm tra thủ công

1. Khởi động lại TCP Server và FastAPI theo README; đặt TCP_LOG_PATH ở statics/runtime, không ghi log gốc. Không chạy seed hoặc migration.
2. Mở /meal-plan, tạo mâm mặc định, ghim một món rồi Đổi cả mâm. Kiểm tra món ghim không thay.
3. Ghim hai món, đổi món còn lại; ghim hết rồi Đổi cả mâm, kiểm tra thông báo không có vị trí để đổi.
4. Tăng mỗi nhóm lên 2, tạo mâm 6 món và kiểm tra không trùng. Thử đặt một nhóm về 0, vẫn giữ tổng ít nhất 1.
5. Ghim món chính thứ hai rồi giảm số chính còn 1; kiểm tra mâm/ghim được giữ và có hướng dẫn tăng lại/bỏ ghim.
6. Chọn loại trừ có trong món ghim hoặc giảm thời gian dưới món ghim; kiểm tra xung đột, không có nới filter.
7. Dùng giới hạn thời gian rất thấp để thiếu rau/canh; kiểm tra thông tin số cần/còn phù hợp và gợi ý điều chỉnh.
8. Mở chi tiết rồi Back, reload và điều hướng về trang chủ; kiểm tra counts/pins/mâm và dữ liệu trang chủ giữ riêng.
9. Tắt TCP Server, thử đổi và retry; kiểm tra mâm, pins và filter vẫn còn. Khởi động server rồi thử lại.
10. Mở trên điện thoại thật cùng Wi-Fi, kiểm tra thao tác ghim, bàn phím số, cuộn, thông báo và các nút đổi.

### Hoàn tác chức năng

Dùng /meal-plan/v1 để quay về giao diện/API/cache cũ. Nếu muốn đổi trang mặc định, chỉ cần đổi lựa chọn template trong gateway sau khi kiểm tra; không cần reset Git, chạy SQL, sửa tag hoặc xóa dữ liệu. Không tự commit/push trong lượt triển khai này.
