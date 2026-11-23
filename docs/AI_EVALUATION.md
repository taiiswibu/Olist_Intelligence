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

Nếu chỉ có một người, điền các dòng `rater_a`, giữ dòng `rater_b` trống và chạy `score ... --raters 1`. Đây là `single_rater_exploratory`, không phải hai người chấm độc lập. Không điền hai tên cho cùng một người. Mặc định vẫn cần hai phiếu; compare không trộn chế độ một người và hai người. Đủ phiếu một người chỉ cho phép đối chiếu nhận xét thăm dò, `quality_claim_ready` vẫn false.

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

Đây là bộ lọc tiếng Việt theo mẫu, có thể bỏ sót cách diễn đạt khác hoặc chặn nhầm câu trích dẫn/giả định. `passed` chỉ nghĩa là qua bộ lọc đã biết, không phải được xác nhận đúng nghiệp vụ. Không tự sửa câu, thử lại nội dung hoặc thay bằng mẫu quy tắc khi bị chặn; lượt đó vẫn tính chưa hoàn tất.

Trace mới giữ HTTP status và nhóm lỗi (`rate_limited`, `request_rejected`, `provider_error`), không giữ body/header/URL lỗi nhà cung cấp. Lỗi 429 được ghi nhận là giới hạn tần suất/hạn mức từ dịch vụ, không tự kết luận cần mua thêm quota. Các lượt cũ thiếu status vẫn được báo là chưa phân loại. Manifest giữ phiên bản/hash bộ lọc; compare hiển thị phiên bản trước/sau vì bộ lọc chặt hơn có thể làm tỷ lệ hoàn tất giảm.

Lượt `dev-grounding-20261123` chạy trên commit đã khóa `6b85ed0`, cùng mười họ, seed và bốn baseline của lượt trước:

| Phương án | Hoàn tất trước | Hoàn tất sau |
|---|---:|---:|
| rules | 10/10 | 10/10 |
| Groq | 6/10 | 2/10 |
| Gemini | 9/10 | 2/10 |
| pipeline | 3/10 | 1/10 |

Lượt mới có 13 `GroundingRejected`, 6 HTTP 503, 5 HTTP 429 và một timeout. Khi phát lại 28 bản nháp cũ qua bộ chặn, cả 11 bản từng được assistant đánh dấu cần sửa đều bị chặn. Hai bản khác bị chặn theo phạm vi note rà việc hiện có đã siết lại. Đây là kiểm tra trên dữ liệu phát triển đã biết; không được dùng để tuyên bố độ chính xác trên mẫu mới. Một assistant đã đọc 15 đầu ra còn lại của lượt mới, gồm năm đầu ra cloud; chưa phải người dùng chấm mù.

**Đã có bằng chứng chặn lỗi đã biết; chưa có bằng chứng AI tốt hơn hoặc người bán làm nhanh hơn.** Bộ lọc chặt hơn và tình trạng dịch vụ đều khác lượt trước, nên không quy toàn bộ thay đổi cho prompt/model. Xem [bằng chứng và giới hạn của lượt sửa](../reports/followup_grounding_20261123.json). Kết quả cũ được giữ nguyên, không tự thử lại hoặc chọn lượt đẹp hơn.

Trước khi chạy tập dự phòng, cần ổn định truy cập dịch vụ và khóa bản phát triển. Sau đó hai người chấm riêng phiếu mù; đo thêm thời gian người bán từ mở báo giá đến duyệt xong trong Odoo, cả thời gian đọc/sửa/lỗi/chờ. So với thao tác thủ công và mẫu quy tắc, phân công thứ tự khác nhau giữa người tham gia để giảm ảnh hưởng học lại tình huống. Chốt tiêu chí trước lượt đo: giảm tổng thời gian mà không tăng lỗi nghiệp vụ; pilot chỉ để ước lượng biến động và chọn cỡ mẫu tiếp theo, không suy ra hiệu quả từ một vài người dùng. `edit_seconds` trong phiếu nội dung chỉ là thời gian đọc/sửa để chuẩn bị duyệt, không thay cho tổng thời gian làm việc trong Odoo.

## Hàng chờ và thử lại có giới hạn

`followup-request-policy-v1` chỉ áp dụng cho luồng chăm sóc đọc bản chụp. Mỗi provider/model trong một tiến trình được gọi nối tiếp. Mặc định ứng dụng cách nhau ít nhất mười hai giây giữa hai lần bắt đầu gọi cùng model, tối đa hai lần gửi cho mỗi bước. Chỉ thử lại HTTP 429/502/503/504, giữ nguyên payload đã lọc. Không thử lại lỗi nội dung/JSON, lỗi 400/401/403 hoặc timeout chưa rõ đã xử lý hay chưa.

Tôn trọng `Retry-After` dạng số giây hoặc HTTP-date; thiếu/sai thì dùng backoff có jitter. Nếu cần chờ quá ba mươi giây thì dừng lượt hiện tại, giữ cooldown cho lượt sau và báo `ProviderCooldown` thay vì gửi dồn. Tổng phân tích gồm hàng chờ vẫn bị giới hạn chín mươi giây. Đây không phải bảo đảm dịch vụ luôn sẵn sàng hoặc kiểm soát các ứng dụng khác dùng chung tài khoản. Cách xử lý dựa trên [giới hạn và header của Groq](https://console.groq.com/docs/rate-limits) và [hướng dẫn retry của Gemini](https://ai.google.dev/gemini-api/docs/troubleshooting).

Cấu hình ứng dụng bằng `FOLLOWUP_MAX_ATTEMPTS` (một đến ba), `FOLLOWUP_REQUEST_INTERVAL_SECONDS` (không đến sáu mươi). Mỗi attempt và lần chờ đều có trace; mọi request thực gửi vẫn phải qua kiểm tra riêng tư ở HTTP. Trace bị ngắt được giữ khi hết deadline. Không lưu body lỗi hay header tùy ý.

Benchmark mặc định vẫn một lần gửi, khoảng cách cấu hình bằng không; cooldown từ nhà cung cấp vẫn được tôn trọng. Muốn đo cả chính sách ứng dụng:

```powershell
.venv\Scripts\python.exe scripts/benchmark_followup.py run --live --strategies rules,groq,gemini,pipeline --limit 3 --max-attempts 2 --request-interval 12 --max-model-calls 24
```

Ngân sách tính cả số lần có thể thử lại trước khi gọi API. Summary đếm request thực gửi, retry và tác vụ chờ riêng; manifest/compare ghi chính sách từng lượt. So hai chính sách khác nhau chỉ là đối chiếu cả hệ thống, không được quy chênh lệch cho riêng model hoặc prompt.

Smoke ở commit `355ec19` dùng ba tình huống, bốn baseline và tối đa 24 request: thực gửi mười request, có một request thử lại; cả mười qua kiểm tra riêng tư HTTP. Rules hoàn tất 3/3, Gemini 2/3, Groq và pipeline 0/3 do bộ chặn nội dung. Hai lần HTTP 503 thuộc cùng một lượt Gemini vẫn thất bại. Không có 429 ở mẫu nhỏ này không chứng minh đã hết vấn đề hạn mức. Xem [bằng chứng công cụ pilot và smoke](../reports/followup_measurement_readiness_20261123.json); báo cáo không chứa số liệu thao tác thật của người dùng.

Phần đo và tự chấm một người đã có trong [addon Odoo](ODOO_AI_FOLLOWUP.md#đo-thao-tác-thực-tế). Mỗi kết quả tự chấm gắn với chính lượt thao tác và giữ thời điểm riêng; không dùng thời gian/điểm của browser test thay người tham gia. Báo cáo CSV luôn giữ trạng thái thăm dò, chưa đủ kết luận AI làm tốt hơn.

## Ranh giới dữ liệu

`followup-minimized-v1` chỉ cho mã tạm mỗi lượt, draft/sent, mã lý do hữu hạn, có việc hay chưa và allowed_actions ra API. Tên, mã thật, số tiền/tiền tệ, ngày cụ thể, người phụ trách và ghi chú giữ local. Ghép kết quả với ID Odoo tại máy. JSON đã serialize được kiểm tra trước transport ở cả Groq và Gemini; trường ngoài danh sách bị chặn. Bản nháp có số, email/URL hoặc hành động ngoài phạm vi bị chặn trước khi chuyển model thứ hai.

Canary test quan sát body HTTP với dữ liệu giả, không chỉ kiểm tra hàm tạo prompt. Đây là bằng chứng về tập kiểm thử/danh sách trường, không bảo đảm ẩn danh tuyệt đối. Backend bỏ payload tạm của lượt mới khi hoàn tất/lỗi/ngắt; Odoo vẫn giữ bản đối soát local. Lịch sử trước bản này không tự bị xóa. Log không lưu prompt/khóa.

Đặt `FOLLOWUP_AI_MODE=rules_only` rồi khởi động lại backend để chức năng chăm sóc không gọi API model. Mặc định `cloud_minimized` dùng hai model với dữ kiện tối thiểu. Việc này không tự thay đổi billing, logging hoặc ZDR trong tài khoản nhà cung cấp.

Phạm vi bảo vệ là **luồng chăm sóc của addon**. Chat ERP/RAG/công cụ khác có ngữ cảnh riêng, cần rà soát trước khi dùng dữ liệu khách thật.
