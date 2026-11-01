# Mâm cơm hôm nay — giai đoạn C: FastAPI và Web

Trang `/meal-plan` có liên kết từ trang chủ. Hai chế độ tìm kiếm/gợi ý cũ giữ nguyên. Trang mâm cơm dùng HTML/CSS/JavaScript hiện có, không thêm framework hoặc dependency.

## Luồng xử lý

Browser → `POST /api/meal-plan` → TCP Client → `GENERATE_MEAL_PLAN` → TCP Server → repository MySQL chỉ đọc. Gateway kiểm tra payload/schema response và chuyển tiếp; không chọn món, tính lại thuật toán hoặc lập danh sách mua. Xem [hợp đồng giai đoạn B](MEAL_PLAN_TCP.md) cho schema TCP không thay đổi.

`POST /api/meal-plan` nhận payload JSON của operation, không nhận envelope TCP hoặc trường `servings`. Gateway tạo UUID, giữ UUID xuyên suốt response và header `X-Request-ID`. Lỗi input là HTTP 422, timeout 504, upstream không sẵn sàng 503, protocol/operation chưa được hỗ trợ hoặc schema response sai 502. Không có mâm phù hợp là HTTP 200, `ok=true`, `plan=null`, có lý do từ TCP.

`GET /meal-plan` phục vụ HTML mà không cần truy vấn MySQL. Gateway chỉ đọc `classification_version` của mapping cục bộ làm gợi ý kiểm tra cache, không phân loại món hoặc gửi toàn bộ mapping về trình duyệt.

## Tương tác

- Danh sách nguyên liệu lấy từ `/api/ingredients?limit=50` qua LIST_INGREDIENTS; mỗi nhóm có sẵn/loại trừ tối đa 30 ID, hai nhóm loại trừ nhau. Tìm trong danh sách nguyên liệu hỗ trợ không dấu.
- Có thể tạo mâm khi chưa chọn nguyên liệu. Các giới hạn mặc định để trống tương ứng `null`.
- Đổi riêng một món gửi đủ `current_plan`, toàn bộ bộ lọc và hai slot khóa còn lại. Đổi cả mâm gửi `current_plan`, `locked_slots=[]`.
- Chỉ nhận kết quả khi response hợp lệ và còn khớp điều kiện hiện tại. Không có phương án đổi: giữ mâm và danh sách mua hiện tại, hiển thị lý do. Response hỏng hoặc lỗi mạng cũng giữ mâm hợp lệ hiện tại và có nút thử lại.
- `PARTIAL_REGENERATION` được hiển thị bằng tiếng Việt, nêu đúng các vai trò đã đổi.
- Lịch sử theo từng slot gửi bằng `avoid_recipe_ids`, hoàn toàn tách khỏi `excluded_ids` nguyên liệu. Khi hết món chưa dùng phù hợp, hiển thị `HISTORY_RECYCLED` bằng tiếng Việt và bắt đầu vòng mới cho slot đó, tính cả món trước và sau lần đổi để tránh bật lại ngay. Đổi bộ lọc/nguyên liệu hoặc tạo mâm mới đặt lại lịch sử.
- Đổi nguyên liệu/bộ lọc sẽ hủy request đang chờ và bỏ hiệu lực mâm/danh sách mua cũ. Sequence token ngăn response cũ cập nhật UI; khóa nút khi chờ ngăn double click.
- Danh sách mua hiển thị đúng response, tách bắt buộc/tùy chọn; không cộng định lượng, tự thêm nguyên liệu hoặc nhân theo số người. Tổng phút là cộng thời gian công thức, chưa tính nấu song song.

## Lưu trạng thái và ảnh

Namespace sessionStorage riêng `goiy-meal-plan-v1`, schema 2: điều kiện, response đã kiểm tra, chữ ký điều kiện, vị trí cuộn và lịch sử món theo slot. Snapshot schema 1 được tiếp nhận và khởi tạo lịch sử từ ba món đang hiển thị. Lịch sử sai cấu trúc được đặt lại an toàn. Không ghi khóa `goiy-selection-v1` của trang chủ. Back/reload không tự POST tạo lại mâm.

Liên kết công thức từ mâm cơm có `return_to=/meal-plan`. Trang chi tiết chỉ chấp nhận một giá trị thuộc allowlist chính xác `/` hoặc `/meal-plan`; tham số thiếu, lạ, trùng hoặc URL ngoài đều về `/`. Nút quay lại trong giao diện là liên kết tới đích đã xác thực, không dùng `document.referrer` hoặc sửa history của trình duyệt. Trang gợi ý/tìm kiếm dùng đích mặc định `/`; mỗi trang tự khôi phục snapshot của mình. URL công thức sai ID có trang HTML lỗi với liên kết quay về an toàn, API công thức vẫn giữ validation cũ.

Trước khôi phục kết quả, tải danh sách nguyên liệu để đối chiếu `dataset_version` và so `classification_version` với gợi ý mapping cục bộ trong HTML. Khi không có gợi ý phân loại, không khôi phục kết quả cũ. Phiên bản không khớp/schema sai bỏ kết quả; JSON hỏng bỏ snapshot an toàn. Mỗi response live vẫn cung cấp phiên bản thực tế từ TCP; gợi ý cục bộ không phải một operation kiểm tra phiên bản phân loại trực tiếp trên TCP.

Ảnh tái sử dụng `recipe-images.js`, manifest và 150 WebP hiện có: lazy loading, `srcset`, alt, ghi công và placeholder khi lỗi. Không thêm hoặc tải ảnh. CSS riêng chỉ áp dụng `.meal-page`; giao diện desktop có sidebar và ba thẻ, mobile xếp dọc. Có skip link chỉ hiện khi focus, nhãn form và thông báo status/alert.

## Chạy và kiểm tra

Khởi động TCP Server/FastAPI theo [README](../README.md), với `TCP_LOG_PATH` trong `statics/runtime/`; mở `http://127.0.0.1:8000/meal-plan`.

Ví dụ PowerShell, cần TCP Server và gateway đang chạy:

```powershell
$mealBody = @{ ingredient_ids = @(1,2,6,7); excluded_ids = @(); max_minutes = 60; max_total_minutes = 90; max_missing = 2 } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/meal-plan -Method Post -ContentType 'application/json; charset=utf-8' -Body $mealBody
```

Kiểm tra thủ công:

1. Chọn Trứng, Cà chua, Rau muống, Tỏi; giới hạn 60/90/2. Tạo mâm và kiểm tra danh sách mua.
2. Đổi từng món, đổi cả mâm; thử giữ bộ lọc chặt để thấy thông báo không có phương án đổi và giữ mâm cũ.
3. Thay bộ lọc: các món và danh sách mua cũ phải biến mất trước khi tạo lại.
4. Xem công thức → Back → reload; mâm và điều kiện phải được khôi phục nếu phiên bản còn phù hợp.
5. Trở về trang chủ kiểm tra các chế độ gợi ý/tìm kiếm; state riêng không bị ghi đè.
6. Trên điện thoại cùng Wi-Fi, chạy Uvicorn `--host 0.0.0.0`, mở `http://<IPv4-LAN-laptop>:8000/meal-plan`. Giữ TCP/MySQL ở máy chủ. Đây là hướng dẫn, không tự xác nhận đã kiểm tra điện thoại vật lý.

```powershell
$env:TCP_LOG_PATH = 'statics/runtime/meal_plan_web_pytest.jsonl'
.\.venv\Scripts\python.exe -m pytest tests/test_web_meal_plan.py tests/test_browser_meal_plan.py --import-mode=importlib -p no:cacheprovider -q -rs
.\.venv\Scripts\python.exe -m pytest tests --import-mode=importlib -p no:cacheprovider -q -rs
```

Browser tests dùng Chrome/Edge thật qua CDP và Node 22+, kiểm tra 1280/390/320px. Chúng dùng FastAPI/TCP thật và SQLite 50 món tạm từ dữ liệu SQL; không chạy seed MySQL. Các response lỗi HTTP trong browser test và lỗi timeout ở unit gateway được mô phỏng có chủ đích; ca server dừng thực được kiểm tra riêng. Skip browser/MySQL không có nghĩa đã xác minh thành công.

Giai đoạn C không thay đổi mã nguồn chín file giai đoạn B, B0/P1, schema/seed, bằng chứng báo cáo hoặc tag `v1.0-report`. Chưa triển khai giai đoạn D.
