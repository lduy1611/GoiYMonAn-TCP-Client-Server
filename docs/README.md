# Mục lục tài liệu

Đọc theo mục tiêu dưới đây. Tài liệu lịch sử và số liệu thực nghiệm được giữ nguyên vị trí; không cần chạy benchmark, migration hoặc khảo sát ảnh để demo.

## 1. Chạy demo

- [README chính](../README.md): clone mặc định nhánh `main` để chạy demo UI v1.2.3, Python/requirements, bốn SQL cho **database mới**, hai loại tài khoản MySQL, `.env`, TCP Server, FastAPI, CLI và kiểm thử.
- [Thứ tự SQL và cách đếm dataset](../README.md#3-nạp-dữ-liệu-mysql-cho-lần-cài-mới): mục tiêu 50 nguyên liệu, 50 món, 252 quan hệ, `vi-v2-50-recipes-r1`. Không chạy lại trên database có dữ liệu cần giữ.
- [Kiểm tra thủ công v1.2](V1_2_SEARCH.md#kiểm-tra-thủ-công): tìm có/không dấu, bộ lọc, phân trang và Back/reload.

Ứng dụng có đủ ảnh WebP cục bộ; không cần ảnh PNG gốc hoặc các file trong `statics/runtime/`. Log mới mặc định ở `statics/runtime/tcp_server.jsonl`, bị Git bỏ qua. Web gateway/CLI cần host/port khớp TCP Server, không cần quyền truy cập MySQL trực tiếp.

## 2. Kỹ thuật hiện tại

- [Tìm kiếm qua TCP và cache UI v1.2](V1_2_SEARCH.md): schema SEARCH_RECIPES, validation, lọc/phân trang, sessionStorage và giao thức v1 được giữ nguyên.
- [Nguồn 50 ảnh B2/B3](IMAGE_SOURCES_USED.md): mapping theo ID, 150 WebP, ghi công, placeholder fallback và kết quả kiểm thử ảnh.
- [Căn cứ sử dụng ảnh](IMAGE_SOURCE_APPROVAL.md): phân biệt xác nhận của chủ project và bằng chứng quyền sử dụng chưa được cung cấp; không suy ra giấy phép mở.
- [Nhập ảnh AI B3](B3_AI_IMAGE_IMPORT.md): quy ước tên gốc, công cụ kiểm tra, chuyển đổi, nhận xét nội dung ảnh, tests và hướng dẫn Wi-Fi. Đây là luồng phát triển, không phải bước bắt buộc để chạy demo.

Phiên bản **UI v1.2.3** là phiên bản giao diện/cache asset; giao thức TCP vẫn **v1**. Metadata phiên bản ứng dụng FastAPI hiện là `1.2.0`; các số này không phải cùng một loại phiên bản.

## 3. Lịch sử phát triển và báo cáo

- [Thực nghiệm đã nộp](../EXPERIMENT_RESULTS.md): CSV/JSON/biểu đồ E2, B0/P1, giới hạn phương pháp và kết quả kiểm thử tại thời điểm báo cáo.
- [Migration SQLite → MySQL](../MIGRATION_REPORT.md): hồ sơ phase 3, gồm fixture 10 món; không dùng chuỗi cài đặt cũ này thay hướng dẫn bốn SQL hiện tại.
- [Tổng kết phase 1–4](../IMPLEMENTATION_SUMMARY.md) và [khác biệt với đặc tả cũ](../CHANGES_FROM_SPEC.md): giữ kết quả lịch sử 16/5 test và các giới hạn tại mốc báo cáo. Các tên `SPEC.md`/`TEST_PLAN.md` trong hồ sơ là tham chiếu lịch sử; hai file đó chưa được phân phối trong repository.
- [Khảo sát ảnh B1](IMAGE_CANDIDATES.md), [bảng CSV B1](image_candidates.csv): ứng viên ban đầu, không phải mapping 50 ảnh hiện hành.
- [Bằng chứng đã theo dõi](../statics/results/): giữ cả các lần E2 trước và lần lỗi. `phase4_dataset_audit.json` còn được tests ảnh và script E2 tham chiếu, không di chuyển cả thư mục khi dọn repository.

Commit báo cáo `4a2afc1`, tag `v1.0-report` giữ nguyên bản đã nộp ban đầu; bản demo hiện tại nằm trên `main`. Xem [cách clone riêng tag báo cáo](../README.md#7-bằng-chứng-báo-cáo-và-giới-hạn) khi cần đối chiếu lịch sử. File `.log` lịch sử được nêu bằng tên vì không được Git phân phối; các tài liệu liên kết CSV/JSON có thật khi phù hợp, không tạo log giả hoặc thay đổi số liệu. Log TCP cũ vẫn được theo dõi trong Git ở giai đoạn này, chưa xóa/bỏ theo dõi. Không chạy script benchmark/audit/vẽ biểu đồ lên đường dẫn bằng chứng nếu chỉ muốn demo.
