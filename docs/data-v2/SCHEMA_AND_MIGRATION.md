# Thiết kế schema và kế hoạch migration dữ liệu v2

**BẢN ĐỀ XUẤT, CHƯA THỰC THI.** Đọc cùng [kế hoạch chính](README.md). Tên bảng/cột dưới đây cần được duyệt trước khi tạo migration SQL. Không có file SQL thực thi trong hồ sơ này.

## 1. Ranh giới tương thích

Giữ nguyên năm bảng cũ: metadata, ingredients, ingredient_aliases, recipes, recipe_ingredients. Không đổi tên/cột, không UPDATE/DELETE/TRUNCATE hàng cũ, không chạy lại seed và không thay dataset_version gốc. Giữ nguyên mapping meal-categories-v1 và các file B0/P1, meal-plan-v1.

Các bảng mới dùng tiền tố v2_. V1 tiếp tục đọc bảng cũ. V2 đọc release riêng qua repository trên TCP Server. FastAPI không chọn phiên bản công thức, kiểm tra thành phần, phân loại hoặc tính định lượng.

ID v2 là namespace riêng. Luôn lưu legacy_recipe_id/legacy_ingredient_id khi có liên hệ; không giả định ID số của hai namespace tương đương. API/operation v2 sau này phải phân biệt rõ ID danh mục v2 và ID v1.

Không lưu giá, tài khoản, bài cộng đồng hoặc logic gợi ý vào các bảng nền gốc để tiện triển khai nhanh.

## 2. Nhóm bảng đề xuất

### A. Nguồn, bằng chứng và duyệt

| Bảng | Cột chính dự kiến | Quy tắc |
|---|---|---|
| v2_sources | id BIGINT PK; source_kind; title; url NULL; document_ref NULL; author_or_publisher NULL; accessed_at NULL; content_hash NULL; usage_note; verification_status | URL không phải mặc định đã xác minh; tài liệu nội bộ có mã tham chiếu/checksum thay URL |
| v2_evidence | id PK; source_id FK; locator; excerpt_or_observation; claim_scope; captured_at; content_hash | Ghi vị trí/bằng chứng cho đúng khẳng định; không dùng một trang văn hóa chung để chứng minh gram/khẩu phần |
| v2_evidence_sets | id PK; description | Một tập bằng chứng có thể dùng nhiều nguồn |
| v2_evidence_set_members | evidence_set_id FK; evidence_id FK; PK hai cột | Không có phần tử trùng |
| v2_review_decisions | id PK; decision; reviewer_ref; decided_at; rationale; evidence_set_id FK | reviewer_ref phải là người thực hiện việc duyệt; không tự điền tên giả |
| v2_review_events | id PK; entity_type; entity_key; action; actor_ref; occurred_at; before_hash; after_hash | Lịch sử truy vết, không thay bằng trạng thái duy nhất hiện tại |

`claim_scope` phân biệt ingredient_identity, composition, recipe_content, quantity, servings, role, region, diet, occasion, template hoặc unit_conversion. Một nguồn có thể hỗ trợ nhiều claim nếu thực sự có nội dung tương ứng, nhưng việc duyệt một claim không tự duyệt các claim khác.

Vòng đời nội dung: draft → submitted → approved/rejected → superseded. UNKNOWN là kết quả tri thức, không phải tên người duyệt hoặc một quyết định approved. Quyết định duyệt là bản ghi bất biến; sửa nội dung phải có phiên bản và quyết định mới.

Có thể dùng reviewer_ref độc lập với hệ thống tài khoản ở giai đoạn đầu; sau này liên kết tới user/admin bằng bảng ánh xạ. Chưa tạo user giả để thỏa khóa ngoại.

### B. Danh tính nguyên liệu và công thức

| Bảng | Cột chính dự kiến | Quy tắc |
|---|---|---|
| v2_ingredients | id BIGINT PK; legacy_ingredient_id INT UNSIGNED NULL UNIQUE FK; canonical_name; normalized_name; identity_status; evidence_set_id NULL; review_decision_id NULL | Nguyên liệu mới không cần INSERT vào ingredients cũ; tên gần giống không tự hợp nhất |
| v2_ingredient_aliases | id PK; ingredient_id FK; locale; alias_raw; alias_normalized; evidence_set_id; review_decision_id | Không tạo alias gây nhập nhằng giữa loài, dạng hoặc chế phẩm |
| v2_ingredient_forms | id PK; ingredient_id FK; form_code; description; status; evidence_set_id; review_decision_id | Tươi/khô, nguyên miếng/xay, thô/chín/chế phẩm; không áp một dạng cho mọi cách dùng |
| v2_ingredient_composition_versions | id PK; ingredient_form_id FK; version; completeness_status; evidence_set_id; review_decision_id | Hỗn hợp/chế phẩm có thể chưa đủ thành phần; không tự coi là thực vật |
| v2_ingredient_composition_lines | composition_id FK; line_no; component_ingredient_id FK; detail; PK(composition_id,line_no) | Chặn vòng thành phần, tự tham chiếu và vòng gián tiếp |
| v2_recipes | id BIGINT PK; legacy_recipe_id INT UNSIGNED NULL UNIQUE FK; variant_of_recipe_id NULL FK; origin_kind; author_ref NULL | Một món có nhiều revision; biến thể thay thành phần/chế độ ăn có thể là danh tính riêng liên kết variant_of |
| v2_recipe_revisions | id BIGINT PK; recipe_id FK; revision_no; title; instructions; minutes; base_servings DECIMAL(10,3) NULL; serving_basis; servings_evidence_set_id NULL; content_evidence_set_id NULL; status; content_review_id NULL; servings_review_id NULL; legacy_snapshot_hash NULL | UNIQUE(recipe_id,revision_no); không sửa revision đã approved/phát hành |
| v2_recipe_ingredient_lines | revision_id FK; line_no; ingredient_id FK; form_id NULL FK; composition_version_id NULL FK; quantity_raw; amount_kind; amount_min DECIMAL(18,6) NULL; amount_max DECIMAL(18,6) NULL; unit_id NULL FK; requirement; purpose; measurement_basis; quantity_evidence_set_id NULL; quantity_review_id NULL; legacy_relation_hash NULL | PK(revision_id,line_no); giữ cả văn bản nguồn và cấu trúc |

Một nguyên liệu có thể xuất hiện ở nhiều dòng cùng revision (ví dụ hai công đoạn khác nhau). Không dùng UNIQUE(revision_id,ingredient_id) làm mất các lượng riêng. Khi tính tổng phải xét công đoạn, dạng và đơn vị, không nhân đôi snapshot quan hệ cũ.

Nếu identity tên nguyên liệu cần sửa đáng kể sau duyệt, tạo danh tính/form mới hoặc phiên bản riêng; không sửa tên đã được release dùng để làm biến đổi lịch sử. Snapshot release phải lưu cả thông tin định danh/phiên bản phụ thuộc.

`origin_kind` phân biệt legacy_import, curated_new, curated_variant; để mở rộng community ở giai đoạn sau. Nguồn cộng đồng không mặc định đủ điều kiện gợi ý công khai.

### C. Định lượng và khẩu phần

| Bảng | Cột chính dự kiến | Quy tắc |
|---|---|---|
| v2_units | id PK; code UNIQUE; dimension; symbol; definition; status | mass, volume, count, source_defined; không coi mọi “muỗng” là một thể tích chuẩn |
| v2_unit_conversions | id PK; from_unit_id FK; to_unit_id FK; factor DECIMAL(18,9); ingredient_id NULL FK; form_id NULL FK; evidence_set_id; review_decision_id | Cùng dimension mới được đổi chuẩn; đổi khác dimension cần dữ liệu nguyên liệu/dạng cụ thể |
| v2_portion_policy_versions | id PK; policy_code; version; description; status; evidence_set_id; review_decision_id | Tách quy tắc khẩu phần khỏi công thức và khỏi B0/P1 |
| v2_portion_policy_rules | policy_version_id FK; rule_no; subject_group; input_definition; equivalent_servings NULL; scaling_mode; parameters; evidence_set_id; review_decision_id | Không tự sinh hệ số trẻ em; dữ liệu chưa duyệt không được dùng để tính |

`amount_kind`: exact, range, to_taste, as_needed, unknown. `requirement`: required, optional, unknown; draft không phải ép trường thiếu thành optional. `purpose`: consumed, cooking_medium, garnish, unknown. `measurement_basis`: gross, edible, prepared, unknown.

- Exact: amount_min > 0, amount_max bằng amount_min hoặc để NULL theo một quy ước được chốt; unit_id phải có.
- Range: 0 < amount_min ≤ amount_max, unit_id phải có; runtime phải giữ khoảng, không âm thầm lấy trung bình.
- To_taste/as_needed/unknown: giữ quantity_raw; không thay lượng chưa biết bằng 0. Không dùng để khẳng định danh sách đi chợ đã đủ định lượng.
- base_servings là số dương nếu có; NULL cho nguồn chưa ghi. Không có DEFAULT 1/2/4 để điền chỗ trống.
- serving_basis phân biệt source_servings và adult_equivalent; có khẩu phần nguồn chưa đồng nghĩa có quy tắc quy đổi trẻ em.
- Đơn vị đếm được chấp nhận nếu công thức/nguồn định nghĩa rõ; không bắt buộc quy đổi toàn bộ sang gram để được duyệt công thức.
- Lượng nấu môi trường như nước dừa hấp phải có chính sách tính mua/tiêu hao, không tự gộp với lượng ăn vào.
- Cần chính sách phân bổ khẩu phần khi có nhiều món cùng nhóm và chính sách nhân tuyến tính/không tuyến tính cho gia vị. Nếu chưa có thì chưa bật tính năng tương ứng.

### D. Vai trò, vùng và chế độ ăn

| Bảng | Cột chính dự kiến | Quy tắc |
|---|---|---|
| v2_roles | id PK; code UNIQUE; name; description; taxonomy_version | Phân biệt món hoàn chỉnh với món ăn kèm |
| v2_recipe_roles | revision_id FK; role_id FK; decision; evidence_set_id; review_decision_id; PK(revision_id,role_id) | Một món có thể phù hợp nhiều vai trò, nhưng chỉ được chọn vào một vị trí trong mâm |
| v2_regions | id PK; code UNIQUE; name | Taxonomy Bắc/Trung/Nam không tự sinh nhãn món |
| v2_recipe_regions | revision_id FK; region_id FK; relation_kind; decision; evidence_set_id; review_decision_id; PK(revision_id,region_id,relation_kind) | relation_kind tách origin và suitable_for_meal; nhiều–nhiều |
| v2_diet_profile_versions | id PK; code; version; scope; definition; status; evidence_set_id; review_decision_id | Quy định rõ chế độ ăn, thành phần và lựa chọn tùy chọn |
| v2_recipe_diet_assertions | revision_id FK; profile_version_id FK; decision; completeness_status; evidence_set_id; review_decision_id; PK(revision_id,profile_version_id) | decision = compatible/incompatible/unknown; approved phải có căn cứ trên đủ thành phần |

Tất cả nhãn gắn **revision**, không chỉ recipe_id: thay nguyên liệu có thể làm thay đổi tính tương thích. Không có assertion không đồng nghĩa incompatible. Chưa được duyệt không được tính vào độ phủ đã xác minh.

Đặc biệt, chế độ “mâm mặn” không được ép từng món rau/canh phải chứa động vật. Cần chủ project chốt giữa: (a) không yêu cầu chay, cho phép cả món thực vật; hoặc (b) mâm có ít nhất một món động vật được xác minh. Profile cấp món và policy cấp mâm tách riêng. Tương tự, ba nhãn vùng không có nghĩa một món phải bị gán duy nhất một miền.

Chứng nhận chay phải xét composition của chế phẩm và cấu hình tùy chọn thực dùng. Không tự bỏ nước mắm/đổi nước chấm để làm assertion compatible; cần revision/biến thể được duyệt.

### E. Dịp và mẫu mâm

| Bảng | Cột chính dự kiến | Quy tắc |
|---|---|---|
| v2_occasions | id PK; code UNIQUE; name; description | Sáu loại dịp chỉ là taxonomy, chưa phải nhãn món |
| v2_recipe_occasions | revision_id FK; occasion_id FK; applicability_context; decision; evidence_set_id; review_decision_id | Nhiều–nhiều; có thể hạn chế theo vùng/phong tục |
| v2_meal_template_versions | id PK; template_code; version; occasion_id FK; title; applicability_context; region_policy; diet_policy; status; evidence_set_id; review_decision_id | Phiên bản bất biến khi approved; không nhận định mọi gia đình dùng cùng mâm cúng |
| v2_meal_template_groups | template_version_id FK; group_no; role_id FK; min_count; default_count; max_count; PK(template_version_id,group_no) | 0 ≤ min ≤ default ≤ max; ít nhất một món trên toàn template |
| v2_template_regions | template_version_id FK; region_id FK; evidence_set_id; review_decision_id; PK hai ID | Phạm vi vùng được duyệt |
| v2_template_diet_profiles | template_version_id FK; profile_version_id FK; evidence_set_id; review_decision_id; PK hai ID | Phạm vi chế độ ăn được duyệt |

Độ phủ template được tính từ ứng viên thực tế của release sau khi giao các assertion, không chỉ từ số hàng trong taxonomy hoặc số nhóm của template.

### F. Release và triển khai

| Bảng | Cột chính dự kiến | Quy tắc |
|---|---|---|
| v2_data_releases | id PK; code UNIQUE; legacy_dataset_version; legacy_baseline_hash; status; approved_at NULL; manifest_hash; coverage_report_ref | Không thay metadata.dataset_version gốc |
| v2_release_recipes | release_id FK; recipe_id FK; revision_id FK; PK(release_id,recipe_id) | Một revision được chọn cho mỗi danh tính món trong release |
| v2_release_dependencies | release_id FK; manifest_ref; dependency_hash | Chốt taxonomy, assertions, ingredient/form/composition, policy, template và nguồn/quyết định dùng trong release |
| v2_migration_history | version PK; checksum; applied_at; execution_result | Ghi đúng các migration thực hiện, không ghi trước trong lượt thiết kế |

Một release phải tái lập được nội dung và điều kiện đủ dữ liệu, kể cả khi sau này có metadata mới. Có thể bổ sung bảng thành viên có FK cho từng loại phụ thuộc khi viết DDL; manifest không thay thế validation khóa ngoại của dữ liệu nghiệp vụ.

Tài khoản/Admin, saved plans, sharing và Thành quả cộng đồng chưa được tạo ở giai đoạn dữ liệu này. Thiết kế author_ref/reviewer_ref/origin_kind và revision bất biến giữ chỗ tích hợp sau; không cần tạo sẵn toàn bộ schema xã hội.

## 3. Ràng buộc và index cần có trong DDL sau duyệt

- PK/FK dùng cùng kiểu/unsigned với bảng được tham chiếu; legacy FK chỉ đọc, ON DELETE RESTRICT, không cascade sửa/xóa hàng gốc.
- UNIQUE cho các mã/version, mapping legacy, membership và assertion theo revision/loại.
- CHECK cho lượng dương, khoảng lượng hợp lệ, base_servings, min/default/max và trạng thái cho phép. Bật strict SQL mode trong môi trường kiểm thử.
- Kiểm tra form thuộc đúng ingredient, revision thuộc đúng recipe, bằng chứng đủ phạm vi, không có vòng composition và các điều kiện approved: thực hiện ở TCP/admin importer trong transaction. CHECK đơn hàng không thay thế được kiểm tra nhiều bảng.
- Index các khóa tra cứu: recipe_id/revision_no, revision_id của dòng nguyên liệu, ingredient_id, (role_id,revision_id), (region_id,relation_kind,revision_id), (profile_version_id,decision,revision_id), (occasion_id,revision_id), các cột review/status và release membership.
- Không tạo index/xóa index trên bảng gốc chỉ để triển khai v2 trong migration ban đầu.
- Không đặt UNIQUE toàn cục cho tên món như cách chặn mọi biến thể. Tách chuẩn hóa để tìm trùng với quyết định hợp nhất có người duyệt.

## 4. Kế hoạch migration SQL bổ sung

Các tên dưới đây là **tên dự kiến**, không phải file đã tạo/chạy.

| Thứ tự | Migration dự kiến | Nội dung | Cổng kiểm tra |
|---|---|---|---|
| 001 | v2_create_provenance_and_catalog.sql | Bảng nguồn, bằng chứng, duyệt, ingredient/form/composition, recipe/revision, đơn vị/khẩu phần | Schema tạo được trên bản sao; bảng cũ/hash không đổi |
| 002 | v2_create_taxonomies_and_templates.sql | Vai trò, vùng, profile ăn, dịp, assertion và mẫu mâm | FK/index/constraint và trạng thái UNKNOWN đúng |
| 003 | v2_create_release_registry.sql | Release, membership, manifest phụ thuộc, lịch sử migration | Tái lập release và so sánh hash |
| 004 | v2_import_legacy_drafts.sql | Copy có đối chiếu 50 danh tính món, 50 nguyên liệu, 252 dòng sang draft; giữ nội dung r1 và source snapshot | Không tự tạo servings, nhãn vùng/dịp/chay hoặc approval |
| 005 | v2_import_reviewed_pilot.sql | Chỉ nhập các revision/assertion đã được người duyệt ký nhận trong lô thí điểm | Bằng chứng đầy đủ, test eligibility/coverage đạt |
| 006+ | v2_import_reviewed_batch_N.sql | Bổ sung công thức mới/biến thể đã xác minh, không ghi seed gốc | Đối chiếu delta, không trùng danh tính vô ý, báo cáo độ phủ |

Importer cần dùng kết nối riêng và transaction cho dữ liệu. Với raw text đọc được, có thể giữ gợi ý parse trong staging/draft; trạng thái vẫn unverified. Nếu dùng chuẩn g/ml có sẵn trong registry cũng không được tự nâng quantity_review hoặc serving_review lên approved.

Số quantity/raw parse không được điền thành dữ liệu đã kiểm chứng, không lấy CSV audit làm file import đã được chủ project duyệt.

### Trước khi áp dụng bất kỳ migration nào

1. Duyệt DDL/import manifest, xác nhận instance/schema đích và phiên bản MySQL hỗ trợ CHECK thực thi.
2. Tạo backup/snapshot và kiểm tra phục hồi trên môi trường riêng. Chốt hash dữ liệu nền, file seed, mapping, thuật toán, báo cáo và log trước thao tác.
3. Thử migration trên bản sao, không chạy lại mysql_seed.sql vì file đó có DELETE dữ liệu nền.
4. Dùng migration account riêng; runtime cũ giữ SELECT. Tài khoản đọc v2 chỉ cần SELECT các bảng liên quan; quyền nhập/duyệt dành cho tiến trình quản trị sau này.
5. Migration history có checksum: chạy lại cùng phiên bản phải là no-op đã xác nhận; khác checksum phải dừng. Không dựa riêng CREATE TABLE IF NOT EXISTS/INSERT IGNORE để che schema hoặc dữ liệu bị lệch.
6. Chạy toàn bộ test dữ liệu và so sánh baseline; chỉ đánh dấu release published khi cổng phát hành tương ứng đạt.

### Hoàn tác

- Chuyển feature flag/active release về v1 hoặc release v2 trước đó; không cần thay bảng gốc.
- Lô import lỗi bị cách ly/rejected; không sửa approved revision tại chỗ, không DROP/TRUNCATE dữ liệu đã được người dùng tham chiếu.
- DDL MySQL không được giả định rollback giống transaction INSERT. Migration phải chia bước, ghi trạng thái và phục hồi có kiểm soát; chạy thử trên bản sao trước.
- Nếu cần gỡ schema trong môi trường thử, chỉ gỡ bảng v2 không có tham chiếu và đã sao lưu, theo thứ tự phụ thuộc. Không đưa thao tác này vào script tự chạy của ứng dụng.
- Tag v1.0-report, log/báo cáo cũ và số liệu thực nghiệm không phải đối tượng migration hoặc rollback.

## 5. Điều kiện phê duyệt thiết kế

Chủ project cần chốt: từ vựng vai trò, ý nghĩa vùng, quy tắc profile ăn cấp món/cấp mâm, quy tắc khẩu phần, người duyệt và tiêu chuẩn nguồn, giới hạn số món/đơn vị để thiết kế contract/frame. Sau đó mới viết DDL cụ thể và test thực thi trên bản sao. Hồ sơ hiện tại không cấp quyền tự động chạy migration hoặc nhập dữ liệu.
