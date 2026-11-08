# Kế hoạch kiểm tra dữ liệu v2 và cổng phát hành

**TRẠNG THÁI: THIẾT KẾ TEST, CHƯA TRIỂN KHAI MIGRATION/TEST SUITE V2.** Không nhầm kết quả rà soát chỉ đọc bên dưới với kết quả thực nghiệm của báo cáo cũ.

## 1. Kiểm tra đã thực hiện trong giai đoạn phân tích

| ID | Kiểm tra trên snapshot MySQL | Kết quả |
|---|---|---|
| A01 | 50 recipes và 50 ingredients có đúng tập ID 1–50 | Đạt |
| A02 | 252 cặp (recipe_id,ingredient_id) duy nhất, không mồ côi | Đạt |
| A03 | 12 alias trỏ nguyên liệu tồn tại | Đạt |
| A04 | is_required chỉ là 0/1; đếm required/optional | Đạt: 151/101 |
| A05 | quantity không rỗng, có số dương và đơn vị đọc được | Đạt: 252; chưa xác nhận cấu trúc/ý nghĩa lượng |
| A06 | ID/tên/phút/nguồn/nội dung công thức khớp SQL và hướng dẫn r1 | Đạt: 50 |
| A07 | Nguyên liệu, alias, quan hệ khớp SQL | Đạt: 50/12/252 |
| A08 | ID/tên mapping 50 món khớp recipes; đúng số nhóm cũ | Đạt: 23/4/6/15/2 |
| A09 | Mỗi hướng dẫn có ba bước được đánh số | Đạt: 50; không chứng nhận nội dung đầy đủ |
| A10 | Kiểm tra định lượng g/ml so với các đơn vị còn lại | 85/167 |
| A11 | Độ phủ trường khẩu phần, vùng, chế độ ăn, dịp, lượng cấu trúc | Chưa có dữ liệu đã duyệt; không được đánh dấu đạt v2 |
| A12 | Đọc từng công thức cùng quan hệ, ghi 50 nhận xét | Hoàn thành; 20 món có khoảng trống thành phần được gọi tên |

Không tạo dữ liệu chạy thử vào MySQL, không khởi động TCP Server, không chạy pytest hoặc benchmark trong lượt này. audit-summary.json ghi các kiểm tra cấu trúc máy đọc được; CSV là bằng chứng đối chiếu nội bộ. Test tự động cho schema mới chỉ được viết và chạy sau khi chủ project duyệt thiết kế.

## 2. Nguyên tắc tổ chức bộ test sau duyệt

- Tách test bảo toàn legacy, test schema/import, test dữ liệu thật đã duyệt và test hành vi thuật toán v2.
- Test schema/migration chạy trên MySQL bản sao hoặc database test riêng được chỉ định; không chạy SQL nhập/xóa trên database hiện tại.
- Có thể dùng fixture tối thiểu để kiểm tra các trường hợp invalid trong test riêng, ghi rõ đó là fixture; không đưa thành phần/nhãn/nguồn giả vào catalog thật hoặc hồ sơ “đã kiểm chứng”. Lượt này chưa tạo những fixture đó.
- V1 dùng fixture/baseline hiện có. Mọi log, XML và báo cáo chạy mới phải ở statics/runtime/data-v2-tests hoặc đường dẫn test riêng; tuyệt đối không ghi statics/results.
- Không chạy compare_algorithms/benchmark để viết lại số liệu đã nộp. Giữ kết quả kiểm thử mới tách khỏi báo cáo thực nghiệm cũ.
- Runtime chỉ đọc; test nhập/duyệt dùng tài khoản chuyên biệt cho database test. Schema migration được kiểm tra riêng khỏi dữ liệu nghiệp vụ.

## 3. Test bảo toàn dữ liệu và migration

| ID | Tình huống | Kỳ vọng |
|---|---|---|
| L01 | Chạy migrations tạo bảng v2 trên bản sao | Năm bảng cũ và mọi giá trị không đổi; hash canonical trước/sau bằng nhau |
| L02 | Import 50/50/252 hàng legacy vào draft | ID legacy được ánh xạ duy nhất, nội dung r1 và quantity_raw giữ nguyên, không phát sinh nhãn/servings/approval |
| L03 | Chạy lại migration có cùng version/checksum | No-op có xác nhận; không nhân đôi dữ liệu |
| L04 | Cùng version nhưng khác checksum hoặc schema lệch | Dừng và giải thích, không dùng INSERT IGNORE để che lỗi |
| L05 | Lỗi giữa lô import dữ liệu | Transaction dữ liệu rollback; không có release published một phần |
| L06 | Lỗi giữa các bước DDL | Được nhận diện từ migration history/schema; có quy trình phục hồi, không tuyên bố DDL đã rollback toàn bộ |
| L07 | Bỏ runtime feature v2/chọn release cũ | V1 hoạt động độc lập; dữ liệu v2 và dữ liệu đã lưu không bị xóa |
| L08 | Runtime v1 truy vấn recipes_for_ranking | Kết quả và kiểu dữ liệu không thay vì có bảng v2 |
| L09 | Hash file seed, mapping, ranking, meal-plan-v1, báo cáo/log và tag | Giữ nguyên baseline được chốt trước thao tác |

Canonical hash phải dùng cùng thứ tự bảng/hàng/cột, biểu diễn NULL/DECIMAL/Unicode và timestamp; không dùng số dòng hoặc file size thay cho so sánh dữ liệu. Lưu manifest baseline riêng cho lượt migration mới, không ghi đè audit/benchmark gốc.

## 4. Test schema, revision, bằng chứng và duyệt

| ID | Tình huống | Kỳ vọng |
|---|---|---|
| S01 | Legacy mapping trùng hoặc FK không tồn tại | Bị từ chối |
| S02 | revision_no trùng trong một recipe hoặc release trỏ revision sai recipe | Bị từ chối |
| S03 | Hai dòng cùng ingredient nhưng khác công đoạn | Được giữ riêng theo line_no; cộng lượng có kiểm soát, không mất dữ liệu |
| S04 | form thuộc nguyên liệu khác | Bị từ chối qua validation transaction |
| S05 | Composition tự tham chiếu hoặc có vòng gián tiếp | Bị từ chối; không đệ quy vô hạn |
| S06 | Đổi nội dung revision approved/published | Bị chặn; yêu cầu revision mới |
| S07 | Approved nhưng thiếu người duyệt, thời điểm, bằng chứng đúng scope | Không được publish |
| S08 | URL chung/nguồn chưa kiểm chứng được dùng làm bằng chứng lượng hoặc vùng | Không tự cấp approval; cần quyết định có căn cứ và đúng claim |
| S09 | Khẳng định chưa có/unknown/rejected | Không được tính là compatible/approved trong coverage |
| S10 | Metadata duyệt ở revision cũ, revision mới thay thành phần | Revision mới không tự kế thừa chứng nhận chế độ ăn/định lượng |
| S11 | Thay taxonomy/policy/composition sau khi release phát hành | Release cũ vẫn tái lập theo dependency manifest; không thay ngầm |
| S12 | Tác giả cộng đồng gửi nội dung | Chỉ draft/submitted; không tự xuất bản vào catalog dùng cho meal-plan |

CHECK đơn bảng, FK và kiểm tra liên bảng đều cần test riêng trên MySQL mục tiêu; không kết luận chúng đã hoạt động chỉ vì SQLite test pass.

## 5. Test nội dung và định lượng

| ID | Tình huống | Kỳ vọng |
|---|---|---|
| Q01 | Lượng âm, bằng 0, không hữu hạn; khoảng min > max | Từ chối với loại lượng yêu cầu số dương |
| Q02 | Chuỗi “nêm vừa ăn”, “nếu có”, lượng chưa biết | Không biến thành 0; giữ raw text và trạng thái chưa tính được |
| Q03 | Có lượng số nhưng chưa có khẩu phần gốc | Không tính nhân theo người; chưa đạt serving-ready |
| Q04 | Có “2 phần bún” nhưng không có base_servings | Không suy ra 2 người cho công thức |
| Q05 | Cộng cùng nguyên liệu/dạng g với kg hoặc ml với l | Đúng hệ số chuẩn đã duyệt; không mất độ chính xác Decimal |
| Q06 | Cộng g với miếng, muỗng với ml, nguyên liệu tươi với khô | Không đổi khi thiếu conversion/form được duyệt; giữ nhóm chưa quy đổi riêng |
| Q07 | Conversion khác dimension hoặc có factor không hợp lệ | Chặn; conversion theo nguyên liệu/dạng cần đúng phạm vi bằng chứng |
| Q08 | base_servings NULL/0/âm hoặc serving_basis chưa rõ | NULL giữ draft; dữ liệu invalid bị từ chối; không mặc định khẩu phần |
| Q09 | Cùng nguyên liệu ở nhiều món/công đoạn | Tổng đúng một lần mỗi use; không double count sau import |
| Q10 | Nguyên liệu tùy chọn bật/tắt | Tổng cần mua và kiểm tra chế độ ăn theo đúng lựa chọn đã duyệt |
| Q11 | Nguyên liệu dùng làm môi trường nấu | Phân biệt consumed/cooking_medium; không tính theo giả định không ghi trong policy |
| Q12 | Lượng tồn nhỏ hơn/đủ/lớn hơn lượng cần dùng | Mua = max(0,need-stock) sau quy đổi hợp lệ; checkbox không thay số lượng |
| Q13 | Nhiều món chính cho cùng số người | Dùng policy phân bổ đã duyệt; không tự nhân toàn bộ mỗi món hoặc chia đều thiếu căn cứ |
| Q14 | Trẻ em theo profile chưa duyệt hoặc thiếu thông tin | Không tự dùng hệ số 0,5; thông báo chưa hỗ trợ phép tính đó |

### Các case nội dung thực tế phải được theo dõi

- ID 1: nước mắm/hành có trong hướng dẫn nhưng thiếu quan hệ.
- ID 2: trứng có trong quan hệ nhưng không được dùng trong hướng dẫn; không tự xóa hoặc khẳng định 200 g là sai.
- ID 16: thịt xay so với luộc/thái mỏng, cần quyết định revision dựa nguồn.
- ID 17: nấm hương thiếu quan hệ; không tự gán lượng.
- ID 22–25: cơm và quan hệ thiếu/lệch; không lấy Gạo tẻ chưa dùng để tự vá.
- ID 32/44/45/47: tên thực vật không đủ điều kiện cấp nhãn chay; Nước mắm phải được xử lý trong bộ thành phần/rule thực tế.
- ID 37/39: tiêu/đường được gọi tên nhưng chưa có trong danh mục/quan hệ.
- ID 46: đậu phộng tùy chọn được nhắc nhưng chưa định lượng/biểu diễn; không báo danh sách mua/dị ứng đã đầy đủ.

Các case này kiểm tra rằng hệ thống **nhận ra giới hạn**, không yêu cầu bộ dữ liệu cũ phải tự thay đổi để test pass. Sau khi có revision mới được duyệt, test so sánh revision đó với evidence/import manifest, đồng thời khẳng định bản legacy vẫn nguyên vẹn.

## 6. Test độ phủ và mâm khả thi

| ID | Tình huống | Kỳ vọng |
|---|---|---|
| C01 | Đếm vai trò | Đếm revision đang phát hành, không đếm mọi revision/lịch sử; một món không tạo bản sao để tăng coverage |
| C02 | Đếm vùng/dịp nhiều–nhiều | Báo số món duy nhất mỗi ô; tổng các ô có thể lớn hơn tổng món và được giải thích |
| C03 | Ma trận 3 vùng × 2 chế độ mâm × 3 vai trò | Tính từ giao assertion đã duyệt trên cùng revision; không nhân các số đếm riêng lẻ |
| C04 | Ăn mặn | Không bắt mọi món rau/canh chứa động vật; áp policy cấp mâm đã chốt |
| C05 | Mâm chay | Mọi món/biến thể được chọn tương thích profile chay và thành phần đầy đủ; không tự thay nguyên liệu |
| C06 | Mỗi ô mục tiêu ≥3 ứng viên | Chỉ là gate hỗ trợ chọn 1–2/đổi một món trước lọc bổ sung; không tuyên bố mọi mâm đều khả thi |
| C07 | Chọn k món, ghim k-1 rồi đổi món còn lại | Cần có món mới khác tất cả món hiện tại, cùng các điều kiện; báo thiếu khi không có |
| C08 | Ghim hết món hoặc yêu cầu nhiều hơn pool | Không lặp món để lấp chỗ; không báo đã đổi thành công khi không đổi |
| C09 | Loại trừ và thời gian làm một nhóm rỗng | Trả nhóm thiếu, số yêu cầu/còn phù hợp; không tự nới ràng buộc |
| C10 | Mẫu hằng ngày/cuối tuần/đãi khách/sinh nhật/Tết/cúng | Kiểm tra cấu trúc nhóm và ứng viên đúng phạm vi; mẫu chưa duyệt không được coi là hỗ trợ |
| C11 | 36 tình huống dịp × vùng × chế độ mâm | Xuất bảng pass/insufficient/unverified riêng; không lấy một mâm thành công chứng minh cả bộ |
| C12 | Tổng thời gian và nguyên liệu dùng chung | Tính ở cấp tổ hợp, không chỉ kiểm tra từng món; không tự dùng thời gian nấu song song |

Gate “đủ dữ liệu” và gate “có nghiệm dưới bộ lọc” là hai việc khác nhau. Bộ dữ liệu sạch vẫn có thể không đủ món khi người dùng loại trừ nhiều nguyên liệu; kết quả đúng lúc đó là trạng thái không đủ món có giải thích.

Chỉ tiêu thời gian dự kiến: mỗi ô cốt lõi có ít nhất một ứng viên ≤30 phút đã xác minh. Khi chưa đạt phải ghi shortage, không giảm số minutes để làm test đạt.

## 7. Test tích hợp cần bổ sung khi nối runtime v2

- Browser → FastAPI → TCP Client → TCP Server → MySQL đọc đúng release; FastAPI không tự phân loại/tính lượng.
- Server không biết operation v2: lỗi tương thích rõ ràng; v1 vẫn dùng được.
- MySQL lỗi, TCP tắt/timeout, request sai trường/ID/revision/profile: giữ đầu vào và món ghim; không lưu kết quả một phần như thành công.
- Chỉ phản hồi mới nhất được cập nhật UI/cache; AbortController không được coi là đã dừng công việc trên TCP.
- Response nhiều món/uses vẫn nằm trong frame 65.536 byte hoặc bị từ chối có kiểm soát; không tự tăng giới hạn protocol.
- Back/reload/chi tiết/quay về meal-plan giữ điều kiện/món ghim; cache v1 và v2 tách biệt; thay release không dùng kết quả tính theo phiên bản cũ.
- Giữ nguyên bộ kiểm thử B0/P1, RECOMMEND, SEARCH_RECIPES và meal-plan-v1; log chạy mới ở runtime riêng.

## 8. Tiêu chí nghiệm thu dữ liệu

Một release v2 có thể chỉ chứa tập thí điểm, không bắt buộc tất cả 50 món đều đủ tính năng. Báo cáo phải ghi mẫu số là số recipe/revision nào, phần chưa phát hành và phần dữ liệu chưa xác minh.

1. **Bảo toàn:** baseline schema/hàng cũ, seed, mapping, thuật toán, báo cáo/log và tag không đổi.
2. **Nguồn và duyệt:** nội dung đưa vào release có bằng chứng đủ scope và quyết định duyệt thực tế.
3. **Nhất quán:** không còn khoảng trống thành phần trọng yếu chưa giải quyết trong revision được tuyên bố đầy đủ; flag tùy chọn được giải thích bằng công thức/biến thể.
4. **Định lượng:** phép tính khẩu phần/mua chỉ dùng lượng, đơn vị, dạng, cơ sở khẩu phần và policy đã duyệt; phần không tính được không bị giấu.
5. **Độ phủ:** chỉ mở bộ lọc khi các ô/phạm vi công bố đạt chỉ tiêu; báo thiếu thay vì gán nhãn để đạt số lượng.
6. **Tái lập:** release manifest và dữ liệu phụ thuộc có hash, so sánh được giữa môi trường thử và môi trường chạy.

Chưa có test/migration v2 nào được tuyên bố pass chỉ từ tài liệu này. Bước hiện tại chỉ hoàn tất kiểm tra nền và thiết kế test để chủ project duyệt.
