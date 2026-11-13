# Kiểm tra khẩu phần và danh sách đi chợ trên bộ pilot

**Đây là thiết kế kiểm chứng và test, chưa phải phép tính đã chạy trên dữ liệu được duyệt.** Không ghi khẩu phần, định lượng mới hoặc kết quả nấu giả vào hồ sơ. Không sửa thuật toán/source code hiện tại và không chạy bộ pytest trong lượt này.

## 1. Điều kiện trước khi tính

Tại thời điểm chuẩn bị, cả 12 món chưa có base_servings được duyệt, 51 dòng chưa có cấu trúc lượng được duyệt; 2 thành phần được gọi tên còn thiếu quan hệ. Vì thế kết quả đúng hiện tại là **NEEDS_VERIFICATION**, không phải một danh sách mua có lượng đầy đủ hoặc tổng bằng 0.

Một công thức chỉ dùng trong kiểm thử tính thực tế khi:

1. Chốt đúng revision và bộ thành phần, kể cả gia vị/phần dùng kèm/tùy chọn thực bật.
2. Có base_servings và serving_basis cùng bộ lượng đã duyệt; không mượn số người của công thức khác.
3. Các dòng cần tính có amount/unit/form/measurement_basis/purpose tương thích và có policy nhân lượng.
4. Policy phân bổ lượng giữa nhiều món của mâm và quy tắc trẻ em đã được duyệt nếu người dùng yêu cầu.
5. Chốt conversion/rounding và dữ liệu tồn kho; checkbox có sẵn không được dùng như lượng đã đủ.

Không cần hoàn tất nhãn vùng/dịp nếu chỉ kiểm tra phép tính lượng của công thức đã đủ điều kiện. Tuy nhiên, không được sử dụng nó để chứng minh bộ lọc vùng/dịp đã hoạt động.

## 2. Công thức kiểm tra, chưa gán giá trị

Ký hiệu cho một revision r và dòng nguyên liệu i:

```text
S_r  = khẩu phần cơ sở được duyệt, có serving_basis xác định
T_r  = khẩu phần đích được phân bổ cho món r theo cùng serving_basis
f_r  = T_r / S_r
q_ri = lượng cơ sở đã duyệt của dòng i
need_ri = q_ri × f_r   (chỉ khi scaling_mode cho phép tuyến tính)

need_i = tổng các need_ri sau quy đổi hợp lệ về cùng unit/form/basis/purpose
buy_i  = max(0, need_i − stock_i)
purchase_i = làm tròn lượng mua theo đơn vị bán/quy tắc được duyệt
```

Các dòng range giữ khoảng; lượng to_taste/as_needed/unknown không bị đổi thành 0. Các lượng không tuyến tính phải theo policy riêng hoặc ghi chưa tính được. Không tự nhân lượng nước hấp, nước canh hoặc gia vị bằng cùng một hệ số nếu chưa có căn cứ.

Người lớn/trẻ em chỉ tạo T_r sau khi có policy phù hợp. Không mặc định mọi trẻ bằng 0,5 người lớn; không lấy T_r bằng tổng số người cho mọi món chính khi người dùng chọn nhiều món cùng nhóm. Cũng không tự chia đều lượng giữa các món thiếu cơ sở.

## 3. Các bộ món dùng làm kịch bản kiểm tra

Các bộ dưới đây chỉ chọn ID hiện có theo vai trò v1 để thiết kế test; chưa là mâm v2 được duyệt về dinh dưỡng, vùng, chế độ ăn hoặc dịp.

| Bộ ID | Mục tiêu kiểm tra | Điểm phải chặn khi chưa xác minh |
|---|---|---|
| 33, 9, 30 | Đơn vị g/nhánh/củ/muỗng; gia vị và nước nấu dùng chung | Không có S_r và chưa xác minh lượng nước/policy |
| 36, 5, 29 | Rau muống dùng ở hai món, cộng nguyên liệu dùng chung; dầu thiếu ở 5 | Không tuyên bố danh sách đầy đủ khi thiếu dầu; không đếm đôi use |
| 4, 47, 32 | Đậu phụ dùng ở hai món, đơn vị miếng và nước trộn/canh; guard nhãn ăn | Không quy miếng sang g, không tự gán chay hoặc bỏ nước mắm |
| 42, 45, 28 | Gram/ml, nước dừa làm môi trường hấp, me dạng chưa rõ và rau thơm thiếu | Không đổi muỗng thành ml, không thêm rau thơm có lượng giả |

Không khẳng định các bộ này đạt một giới hạn tổng thời gian chưa được nêu. Nếu triển khai test ghim/đổi sau này, giữ vai trò/món ghim đã được xác nhận và tính lại lượng từ các món thực sự còn trong mâm; không thay một món ghim để làm phép tính hết lỗi.

## 4. Bộ test đề xuất sau khi có dữ liệu đủ điều kiện

| ID | Case | Kết quả mong đợi |
|---|---|---|
| P-C01 | Cả 12 ứng viên hiện tại chưa có S_r được duyệt | Từ chối khẳng định lượng theo người; trả NEEDS_VERIFICATION cùng trường thiếu |
| P-C02 | Công thức có S_r, đặt T_r = S_r với cùng basis | Lượng tuyến tính giữ nguyên từng dòng; không làm tròn sai ngay từ đầu |
| P-C03 | Công thức đủ điều kiện, đặt T_r = 2 × S_r | Các dòng được phép tuyến tính tăng đúng hệ số; dòng policy khác không bị nhân tùy tiện |
| P-C04 | Thay số người nhưng giữ món | Tính lại từ lượng cơ sở, không nhân tiếp kết quả đã scale gây lũy kế |
| P-C05 | Có trẻ em nhưng policy chưa được duyệt/thiếu dữ liệu cần thiết | Không dùng một hệ số mặc định; giữ đầu vào và giải thích chưa hỗ trợ |
| P-C06 | Nhập số người âm, boolean, số không đúng kiểu; tổng bằng 0 | Lỗi validation; không trả mâm/khẩu phần hợp lệ |
| P-C07 | Chọn nhiều món cùng nhóm khi thiếu allocation policy | Không nhân toàn bộ công thức hay chia đều ngầm; cần xác minh policy |
| P-C08 | Rau muống ở 36 và 5 cùng form/basis/unit đã được duyệt | Cộng hai use một lần; giữ provenance từng món; nếu form/basis khác thì không tự gộp |
| P-C09 | Đậu phụ ở 4 và 32 đều ghi miếng nhưng chưa có định nghĩa kích thước | Không suy trọng lượng hoặc coi mọi miếng tương đương; giữ riêng/cảnh báo |
| P-C10 | Me/nước mắm ghi muỗng; chưa rõ loại muỗng và dạng | Không quy sang ml/g; không dùng conversion của nguyên liệu khác |
| P-C11 | g/kg hoặc ml/l cùng dimension và cùng form/basis, conversion chuẩn đã duyệt | Quy đổi chính xác bằng Decimal, giữ sai số/quy tắc làm tròn được chấp nhận |
| P-C12 | Nước dừa 42 dùng môi trường hấp | Áp policy purpose đã duyệt cho lượng mua/tiêu hao; không coi toàn bộ là lượng ăn |
| P-C13 | Tùy chọn bật/tắt ở 29/32/45/47 | Danh sách lượng phản ánh đúng cấu hình đã duyệt; không đảo required legacy để test đạt |
| P-C14 | Dầu ở 5 và rau thơm ở 28 chưa được xác minh | Không tạo ID/amount/required giả; báo thành phần còn thiếu |
| P-C15 | Nguồn ngoài có số người nhưng bộ lượng/thành phần khác legacy | Không dùng số người nguồn để scale bộ lượng legacy |
| P-C16 | Lượng tồn thiếu/đủ/dư, cùng đơn vị và form được xác nhận | buy không âm; không vượt lượng cần khi không có lý do đóng gói; đủ thì không mua thêm |
| P-C17 | Lượng tồn chưa biết hoặc chỉ có checkbox | Không tự trừ toàn bộ; hiển thị cần xác nhận lượng đủ/thiếu |
| P-C18 | Cùng nguyên liệu vừa required ở món này vừa optional ở món khác | Không xuất trùng vào hai nhóm; vẫn giữ đủ uses và cấu hình optional |
| P-C19 | Đổi một món trong mâm | Loại use của món cũ, thêm use món mới, tính lại từ cơ sở; use món ghim vẫn còn |
| P-C20 | Lượng range/to_taste, form hoặc conversion chưa có | Trả giới hạn rõ; không báo tổng đủ hoặc giá trị 0 cho phần chưa biết |
| P-C21 | Trước/sau làm tròn mua | Cộng nhu cầu và trừ tồn ở độ chính xác chuẩn trước khi làm tròn theo quy tắc bán, tránh làm tròn từng use gây mua dư |
| P-C22 | Metadata/revision nguồn thay đổi | Kết quả/cache cũ bị nhận diện bằng version/hash; không áp policy của revision mới cho số liệu cũ |

### Oracle kiểm tra

- Người duyệt chuẩn bị bảng tính độc lập từ **dữ liệu đã xác minh**, có source/revision/units, dùng làm oracle. Không lấy chính kết quả thuật toán làm expected.
- Trước khi có oracle đó, chỉ chạy được kiểm tra cấu trúc hồ sơ và logic chặn dữ liệu thiếu; không tuyên bố độ đúng khẩu phần thực tế.
- Có thể dùng kiểm thử toán học trên các giá trị raw đã lưu để kiểm tra bộ cộng số độc lập, nhưng phải ghi rõ đó không phải định lượng món được duyệt. Không đưa kết quả toán học ấy vào proposed_amount hoặc catalog.
- Không lấy đơn vị text giống nhau làm bằng chứng form/basis giống nhau. Kiểm tra số món/nguyên liệu trùng bằng ID namespace đã chốt, không chỉ tên hiển thị.

## 5. Các phép đối chiếu cần làm khi nấu thử

1. Ghi lượng đầu vào trước/sau sơ chế và lượng thực dùng theo từng dòng, không giả định tỷ lệ hao hụt.
2. Ghi phần bỏ đi/còn lại và mục đích dùng; phân biệt nguyên liệu ăn, nước/medium và trang trí.
3. Chia thành phẩm theo khẩu phần nguồn đã chốt, ghi sản lượng/thể tích thực chia và số phần quan sát được; không tạo kết quả này trước buổi thử.
4. Kiểm tra cùng policy khi thay lượng; nếu kết quả không tuyến tính, ghi giới hạn áp dụng và đề xuất policy riêng.
5. Một lần nấu không tự chứng minh mọi số người, trẻ em hoặc số món đều phù hợp. Phạm vi nghiệm thu phải ghi đúng điều kiện đã kiểm chứng.

Các thông tin cần điền nằm trong phiếu tại [SOURCES_AND_REVIEW.md](SOURCES_AND_REVIEW.md); người thực hiện và người duyệt vẫn để trống cho chủ project chỉ định.

## 6. Cổng nghiệm thu pilot

Không yêu cầu hoàn tất tất cả 96 task mới được nhận xét một phần dữ liệu, nhưng không được công bố một tính năng chưa đủ điều kiện:

- **Content-ready:** thành phần/hướng dẫn nhất quán, optional có cách dùng/bỏ rõ, nguồn/diff được duyệt.
- **Serving-ready:** thêm S_r, serving_basis và các lượng/policy cần nhân của đúng revision.
- **Shopping-ready:** thêm đơn vị/form/basis/purpose, conversion khi cần, quy tắc làm tròn và cách xử lý phần chưa biết/tồn kho.
- **Filter-ready:** chỉ mở chiều vùng/profile ăn/dịp có assertion được duyệt cho đúng revision và báo cáo coverage đạt phạm vi công bố.
- **Import-ready:** manifest dữ liệu và migration được phép riêng, thử trên DB test; không phát sinh quyền chạy migration từ hồ sơ này.

Số lượng hiện tại ở mỗi cổng v2 trên là 0 được phê duyệt. Đây là trạng thái đang chờ kiểm chứng, không phải một lần test runtime thất bại hoặc khẳng định các món không thể dùng được.
