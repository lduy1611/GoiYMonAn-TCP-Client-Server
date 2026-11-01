# Mâm cơm hôm nay — giai đoạn B: TCP và CLI

Đã triển khai phân loại, thuật toán và TCP `GENERATE_MEAL_PLAN`. Chưa có giao diện hoặc endpoint FastAPI cho chức năng này. Năm operation cũ, B0/P1, dataset, schema và seed giữ nguyên.

## Phân loại

[recipe_categories.json](../data/recipe_categories.json) là mapping riêng đã được chủ project duyệt: 23 `main` (mặn/món chính), 4 `vegetable` (rau), 6 `soup` (canh), 15 `starch`, 2 `other`; phiên bản `meal-categories-v1`. Mỗi ID chỉ có một nhóm. Nhóm mặn mô tả vai trò món chính, không phải độ mặn hoặc phân loại chay. Những ngoại lệ và điểm chưa nhất quán trong công thức được ghi chú trong mapping, không sửa dữ liệu gốc.

Loader kiểm tra đủ ID 1–50, không trùng và đúng số lượng nhóm. Test đối chiếu ID/tên với 50 công thức trong SQL được phân phối. Khi chạy, chỉ dùng công thức thực sự tồn tại trong repository và có mapping; vì vậy fixture SQLite 10 món vẫn có thể kiểm thử. Catalog được cache trong process; khi cập nhật mapping cần tăng `classification_version` và khởi động lại TCP Server.

## Request

Giữ JSON UTF-8, version 1, UUID, header 4 byte big-endian, body tối đa 65.536 byte và timeout hiện tại.

```json
{
  "version": 1,
  "request_id": "e35954bb-19f1-40a6-a8d2-77288ead8050",
  "op": "GENERATE_MEAL_PLAN",
  "payload": {
    "ingredient_ids": [1, 2, 6, 7],
    "excluded_ids": [],
    "max_minutes": 60,
    "max_total_minutes": 90,
    "max_missing": 2,
    "current_plan": null,
    "locked_slots": []
  }
}
```

| Trường | Mặc định và validation |
|---|---|
| `ingredient_ids` | `[]`; tối đa 30 ID nguyên dương tồn tại; ID trùng được gộp |
| `excluded_ids` | `[]`; cùng giới hạn; không giao với nhóm có sẵn |
| `max_minutes` | `null` hoặc số nguyên 1–240; giới hạn từng món |
| `max_total_minutes` | `null` hoặc số nguyên 1–720; tổng ba công thức |
| `max_missing` | `null` hoặc số nguyên 0–50; số ID bắt buộc thiếu duy nhất trên cả mâm |
| `current_plan` | `null` hoặc object đủ ba khóa `main`, `vegetable`, `soup`; ID tồn tại, khác nhau và đúng nhóm |
| `locked_slots` | `[]`; tối đa hai vai trò khác nhau; phải có `current_plan` nếu khóa món |
| `avoid_recipe_ids` | `{}`; object chỉ có khóa `main`, `vegetable`, `soup`, mỗi giá trị là danh sách ID món nguyên dương không trùng, tối đa 50 ID mỗi danh sách và tổng cộng; lịch sử không rỗng cần `current_plan`; mỗi ID phải tồn tại và đúng nhóm |

Từ chối trường lạ, boolean/số thực/chuỗi thay số nguyên, ID không tồn tại, vai trò lạ và khóa trùng. Lỗi trả `INVALID_PAYLOAD` và giữ `request_id`. Không chọn nguyên liệu vẫn tạo được mâm; mọi nguyên liệu bắt buộc đều được tính thiếu. `max_missing=null` không giới hạn ngầm.

## Thuật toán và đổi món

Thuật toán riêng `meal-plan-v1` không gọi hoặc sửa B0/P1. Lọc món có nguyên liệu bị loại trừ, kể cả tùy chọn, và lọc thời gian từng món. Ghép đúng ba món khác ID theo thứ tự `main`, `vegetable`, `soup`; kiểm tra tổng thời gian và số nguyên liệu bắt buộc thiếu duy nhất trước khi chọn.

Nếu có `current_plan`, ưu tiên số vị trí đổi sang món chưa có trong lịch sử, rồi số vị trí thực sự đổi. Sau đó ưu tiên lần lượt: ít loại nguyên liệu bắt buộc cần mua, nhiều loại nguyên liệu bắt buộc có sẵn, ít lượt thiếu cộng theo món, tổng thời gian thấp, bộ recipe_id tăng dần. Đây là thứ tự so sánh, không phải điểm B0/P1. Không gửi lịch sử tương đương lịch sử rỗng, giữ thứ tự cũ. Lịch sử là ưu tiên tạm thời, không phải loại trừ nguyên liệu hoặc điều kiện được phép nới lỏng.

Ví dụ đổi canh với lịch sử: `{"current_plan":{"main":1,"vegetable":5,"soup":30},"locked_slots":["main","vegetable"],"avoid_recipe_ids":{"soup":[29,30]}}`. Backend vẫn xét toàn bộ điều kiện bắt buộc; khi không còn món chưa dùng phù hợp, cho phép dùng lại món đã thấy nhưng phải khác món hiện tại, kèm warning `HISTORY_RECYCLED`. Nếu không có món khác, vẫn `plan=null`, không báo đổi thành công. CLI nhận trường mới qua `--payload` JSON hiện có; không cần flag hoặc operation mới.

- Đổi canh: `current_plan={"main":1,"vegetable":5,"soup":29}`, `locked_slots=["main","vegetable"]`. Món canh mới bắt buộc khác 29; hai món khóa giữ nguyên.
- Đổi cả mâm: gửi `current_plan`, `locked_slots=[]`. Ưu tiên đổi cả ba; nếu không được, cho phép đổi hai hoặc một món trong giới hạn đã chọn, kèm warning `PARTIAL_REGENERATION`.
- Không có cách đổi: `plan=null`; tuyệt đối không trả lại nguyên trạng và báo đổi thành công. Không tự nới bộ lọc hoặc thay món khóa.
- Không lưu phiên TCP hoặc ghi MySQL. Mỗi lần đổi phải gửi lại bộ lọc mong muốn; trường bị bỏ qua dùng giá trị mặc định, không kế thừa request trước.

## Response và danh sách mua

Envelope giữ nguyên `{version, request_id, ok, data, error}`. `data` gồm:

- `dataset_version`, `classification_version`, `algorithm="meal-plan-v1"`.
- `plan`: object hoặc `null`.
- `changed_slots`: vị trí thực sự đổi so với `current_plan`; `[]` khi tạo lần đầu hoặc không có mâm.
- `warnings` và `reason`: warning nghiệp vụ và lý do có cấu trúc khi không có kết quả.

`plan` gồm ba `items` có `slot`, `recipe_id`, `title`, `minutes`, `matched_ids`, `missing_ids`, `missing_count`; cùng `required_ids`, `matched_ids`, `missing_ids`, `missing_count`, `total_minutes`, `time_basis="sum_of_recipe_minutes"`, `shopping_list`, `optional_shopping_list`, `optional_missing_ids`. Không có score.

Tổng thời gian là tổng thời gian công thức nếu thực hiện tuần tự, không phải ước tính nấu song song. Nguyên liệu có sẵn chỉ là dấu chọn, chưa xác nhận đủ số lượng. Không có dữ liệu khẩu phần để tự nhân định lượng.

Danh sách mua nhóm theo ID. Mỗi mục giữ `ingredient_id`, `name`, `uses=[{recipe_id, quantity, is_required}]`. Nếu nguyên liệu bắt buộc ở ít nhất một món nhưng tùy chọn ở món khác, chỉ xuất hiện trong danh sách bắt buộc, với đầy đủ các dòng định lượng và cờ theo món. Chỉ nguyên liệu hoàn toàn tùy chọn mới vào danh sách tùy chọn. Không cộng các đơn vị dạng chuỗi hoặc suy diễn nguyên liệu từ hướng dẫn; chỉ đọc quan hệ trong database.

Không có kết quả vẫn `ok=true`, `plan=null`, `changed_slots=[]`, warning `NO_COMPLETE_MEAL_PLAN`. `reason.code` là `MISSING_CATEGORY`, `LOCKED_RECIPE_INCOMPATIBLE`, `CONSTRAINTS_UNSATISFIED` hoặc `NO_ALTERNATIVE`, có thông báo và danh sách vai trò liên quan. Đây không phải lỗi framing/TCP.

Server trước giai đoạn B chưa biết operation mới và trả `UNKNOWN_OPERATION`, giữ UUID. Test tương thích mô phỏng đúng allowlist cũ bằng validator/framing không thay đổi; không khẳng định đã triển khai thử binary server cũ riêng biệt.

## Demo và kiểm thử

Khởi động TCP Server theo [README](../README.md), luôn đặt `TCP_LOG_PATH` trong runtime. Không cần FastAPI để demo:

```powershell
$env:TCP_LOG_PATH = 'statics/runtime/meal_plan_server.jsonl'
.\.venv\Scripts\python.exe -m source.server.main
```

Terminal khác tại gốc repository:

```powershell
.\.venv\Scripts\python.exe -m source.client.cli --host 127.0.0.1 --port 9000 --op GENERATE_MEAL_PLAN
```

Payload mặc định là `{}`. CLI xuất JSON UTF-8, kể cả khi stdout được redirect trên Windows. Kiểm tra bộ lọc bằng TCP Client trực tiếp, không qua HTTP:

```powershell
.\.venv\Scripts\python.exe -X utf8 -c "import json; from source.client.tcp_client import TCPClient; print(json.dumps(TCPClient().request('GENERATE_MEAL_PLAN', {'ingredient_ids':[1,2,6,7], 'max_minutes':60, 'max_total_minutes':90, 'max_missing':2}), ensure_ascii=False, indent=2))"
```

Kiểm thử mới tạo SQLite trong thư mục tạm từ literal dữ liệu SQL; không thực thi MySQL SQL hoặc gọi seed/migration trên database thật:

```powershell
$env:TCP_LOG_PATH = 'statics/runtime/meal_plan_pytest.jsonl'
.\.venv\Scripts\python.exe -m pytest tests/test_meal_plan.py tests/test_meal_plan_integration.py --import-mode=importlib -p no:cacheprovider -q -rs
.\.venv\Scripts\python.exe -m pytest tests --import-mode=importlib -p no:cacheprovider -q -rs
```

Không cần chạy benchmark. Bằng chứng báo cáo, tag `v1.0-report`, năm operation cũ và giao diện v1.2.3 giữ nguyên.
