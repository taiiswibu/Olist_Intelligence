# Baseline, đánh giá và riêng tư cho AI bán hàng

Kiểm thử phần mềm chứng minh quyền, dữ liệu và phê duyệt chạy đúng. Nội dung AI cần so baseline và có người hiểu nghiệp vụ chấm riêng. Thứ tự ưu tiên/allowed_actions do quy tắc xác định, không tính là thành tích suy luận của model.

## Bốn phương án

| Phương án | Cách làm |
|---|---|
| rules | Quy tắc + mẫu cố định, không gọi model |
| groq | Groq tự soạn |
| gemini | Gemini tự soạn |
| pipeline | Groq soạn, Gemini kiểm tra; bị từ chối vẫn tính chưa hoàn tất |

Cùng tình huống, dữ kiện tối thiểu, prompt soạn và giới hạn đầu ra. Không mặc định hai model tốt hơn một. Chỉ giữ bước kiểm tra khi lợi ích đủ bù thời gian/chi phí.

## Chạy và giữ bằng chứng

Fixture `tests/fixtures/followup_benchmark_v1.py` có **30 họ × 4 biến thể riêng tư = 120 mẫu**, không phải 120 tình huống nghiệp vụ độc lập. Có 10 họ/40 mẫu phát triển và 20 họ/80 mẫu dự phòng, không tách các biến thể của cùng họ sang hai tập. Dữ liệu tổng hợp chỉ ở test; không dùng để làm đầy ứng dụng hoặc Odoo.

Nhãn do kỹ thuật tự soạn, **chưa được chuyên gia xác nhận độc lập**. Không chỉnh prompt theo tập dự phòng rồi tiếp tục gọi đó là kiểm chứng độc lập. Giữ v1, thêm bộ v2 khi mở rộng nghiệp vụ.

```powershell
# Mặc định đủ 40 mẫu phát triển, không gọi API.
.venv\Scripts\python.exe scripts/benchmark_followup.py run
# Smoke test ba họ, tối đa 12 lần gọi API; có thể tốn quota/phí.
.venv\Scripts\python.exe scripts/benchmark_followup.py run --live --strategies rules,groq,gemini,pipeline --limit 3
# Chỉ chạy tập dự phòng sau khi khóa bản phát triển.
.venv\Scripts\python.exe scripts/benchmark_followup.py run --live --split holdout --strategies rules,groq,gemini,pipeline --repeats 3 --max-model-calls 960
```

Kết quả ở `data/processed/followup_evaluations/`, không vào Git và không ghi đè lượt cũ. Manifest giữ SHA fixture, hash code/skill, commit, model, seed, cấu hình và thời điểm. Model có thể là alias thay đổi phía nhà cung cấp. JSONL ghi từng mẫu, cả lỗi. Lượt bị ngắt giữ kết quả thô nhưng không được chấm/so sánh như đã hoàn tất.

Summary báo tỷ lệ hoàn tất, đạt hợp đồng đầu ra, thời gian máy p50/p95, token API báo và số request qua lọc tại HTTP. Lỗi/timeout ở trong mẫu số. **Đúng hợp đồng chưa chứng minh nội dung đúng/hữu ích.** Thời gian máy chưa bao gồm người đọc, sửa và duyệt. Mẫu nhỏ chỉ kiểm tra kết nối, không đủ kết luận phương án nào tốt hơn.

Muốn ước tính tiền, dùng `--pricing file.json`: cần `currency=USD`, `as_of`, `source`, và mục groq/gemini với đúng `model`, `input_per_million`, `output_per_million`. Không có giá thì để null. Đây là ước tính theo đơn giá người chạy cung cấp, không phải hóa đơn và chưa tính ưu đãi cache/phí phụ.

## Chấm mù và so sánh phiên bản

Hai người chấm độc lập đọc `blind_samples.csv`, không xem `results.jsonl` vì file đó có tên phương án. Điền `ratings.csv`: đúng nghiệp vụ/có căn cứ (0/1), mức dùng được (1–5), accept/edit/reject và `edit_seconds` là thời gian thực đo để đọc, sửa, chuẩn bị duyệt. Không điền thời gian ước đoán.

Lượt không có đầu ra phải tính không đạt, mức dùng được thấp nhất và reject. Phiếu trống vẫn là chưa chấm; không dùng model đang đánh giá tự chấm thay người. Mỗi mẫu cần đúng hai phiếu; danh tính/độc lập người chấm do người chạy khai báo. Đủ phiếu cho phép đối chiếu trên fixture, chưa chứng minh tác động doanh thu hoặc nhãn đã được chuyên gia xác nhận.

```powershell
.venv\Scripts\python.exe scripts/benchmark_followup.py score --run path_to_run --ratings ratings.csv
.venv\Scripts\python.exe scripts/benchmark_followup.py compare --before old_run --after new_run
```

Compare yêu cầu cùng SHA bộ tình huống, tập, mẫu, số lặp và baseline. Nếu cả hai có phiếu đầy đủ thì thêm chênh lệch điểm người chấm. Cần thẩm định nghiệp vụ và thử với người dùng thật trước khi khẳng định hiệu quả kinh doanh.

## Khi thêm chức năng có cần chứng minh lại?

| Thay đổi | Kiểm tra cần chạy |
|---|---|
| Chữ/bố cục | Giao diện và chức năng liên quan |
| Nghiệp vụ mới | Tình huống mới + bộ v1 hồi quy; không sửa nhãn v1 để làm kết quả đẹp hơn |
| Model/prompt/skill/thứ tự agent | Bốn baseline trên cùng tập đã khóa; so nội dung, lỗi, thời gian và token |
| Trường gửi model/lớp lọc | Toàn bộ kiểm thử riêng tư ở HTTP của cả hai model và benchmark liên quan |
| Quyền/thao tác ghi/phê duyệt | Phân quyền, ghi trái phép, dữ liệu cũ, tạo trùng trong Odoo thật |

Giữ bằng chứng cũ, đo phần thay đổi; không làm lại từ đầu và không suy ra tăng doanh thu từ điểm benchmark.

## Kết quả đọc thử ngày 23/11/2026

Lượt `dev-review-20261123` dùng mười họ phát triển, mỗi họ một biến thể và một lần chạy. Số lượt hoàn tất: rules 10/10, Gemini 9/10, Groq 6/10, pipeline 3/10. Cả lượt lỗi HTTP và lượt bị reviewer từ chối đều giữ trong mẫu số; không suy đoán nguyên nhân HTTP khi trace chưa có status code.

Một assistant đã đọc đủ 40 kết quả, thấy lỗi nội dung mà kiểm tra cấu trúc chưa phát hiện: báo giá nháp lại nói đã gửi; không có lịch việc lại suy ra chưa có phản hồi; action rà việc hiện có nhưng văn bản chủ yếu rà báo giá. Reviewer cũng để lọt một số câu cần sửa. Chưa có căn cứ khẳng định hai model tốt hơn một.

Đây là **nhận xét của một assistant có thấy tên phương án**, không phải hai người chấm mù hoặc xác nhận của chuyên gia. Điểm người chấm và thời gian sửa thực tế vẫn trống. Không đổi prompt, fixture hay cấu hình ứng dụng theo lượt này; tập dự phòng chưa chạy.

Xem [số liệu, lỗi và nhận xét từng trường hợp](../reports/followup_review_20261123.json). File đọc chi tiết ở `data/processed/followup_evaluations/dev-review-20261123/assistant_review.csv`; phiếu người chấm riêng vẫn là `ratings.csv`. Các file dữ liệu này chỉ lưu local.

## Chặn lỗi đã biết

`followup-grounding-v1` kiểm tra bản nháp của cả Groq, Gemini và pipeline trước khi trả về hoặc chuyển sang reviewer. Chặn các cách diễn đạt đã biết về lịch sử gửi của báo giá nháp, lịch sử phản hồi không có trong nguồn và việc đã hoàn tất/tương tự. Với `review_existing_activity`, note phải hướng dẫn xem lại công việc/hoạt động hiện có; chưa dùng note này để soạn lời liên hệ khách. Hai skill đã được cập nhật cùng phạm vi này.

Đây là bộ lọc tiếng Việt theo mẫu, có thể bỏ sót cách diễn đạt khác hoặc chặn nhầm câu trích dẫn/giả định. `passed` chỉ nghĩa là qua bộ lọc đã biết, không phải được xác nhận đúng nghiệp vụ. Không tự sửa câu, thử lại hoặc thay bằng mẫu quy tắc khi bị chặn; lượt đó vẫn tính chưa hoàn tất.

Trace mới giữ HTTP status và nhóm lỗi (`rate_limited`, `request_rejected`, `provider_error`), không giữ body/header/URL lỗi nhà cung cấp. Lỗi 429 được ghi nhận là giới hạn tần suất/hạn mức từ dịch vụ, không tự kết luận cần mua thêm quota. Các lượt cũ thiếu status vẫn được báo là chưa phân loại. Manifest giữ phiên bản/hash bộ lọc; compare hiển thị phiên bản trước/sau vì bộ lọc chặt hơn có thể làm tỷ lệ hoàn tất giảm.

## Ranh giới dữ liệu

`followup-minimized-v1` chỉ cho mã tạm mỗi lượt, draft/sent, mã lý do hữu hạn, có việc hay chưa và allowed_actions ra API. Tên, mã thật, số tiền/tiền tệ, ngày cụ thể, người phụ trách và ghi chú giữ local. Ghép kết quả với ID Odoo tại máy. JSON đã serialize được kiểm tra trước transport ở cả Groq và Gemini; trường ngoài danh sách bị chặn. Bản nháp có số, email/URL hoặc hành động ngoài phạm vi bị chặn trước khi chuyển model thứ hai.

Canary test quan sát body HTTP với dữ liệu giả, không chỉ kiểm tra hàm tạo prompt. Đây là bằng chứng về tập kiểm thử/danh sách trường, không bảo đảm ẩn danh tuyệt đối. Backend bỏ payload tạm của lượt mới khi hoàn tất/lỗi/ngắt; Odoo vẫn giữ bản đối soát local. Lịch sử trước bản này không tự bị xóa. Log không lưu prompt/khóa.

Đặt `FOLLOWUP_AI_MODE=rules_only` rồi khởi động lại backend để chức năng chăm sóc không gọi API model. Mặc định `cloud_minimized` dùng hai model với dữ kiện tối thiểu. Việc này không tự thay đổi billing, logging hoặc ZDR trong tài khoản nhà cung cấp.

Phạm vi bảo vệ là **luồng chăm sóc của addon**. Chat ERP/RAG/công cụ khác có ngữ cảnh riêng, cần rà soát trước khi dùng dữ liệu khách thật.
