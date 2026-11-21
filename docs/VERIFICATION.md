# Phạm vi đã xác minh của bản 0.1

Ngày chạy: 21/11/2026. Môi trường: Linux, Python 3.12. Không đồng nhất kết quả này với hiệu năng trên laptop Windows của người dùng.

## Dữ liệu thật

Tải chín CSV từ endpoint Kaggle chính thức, không dùng dữ liệu mô phỏng để chạy ứng dụng. Có 99.441 orders và 112.650 items. Tổng price của items gốc **13.591.643,70 BRL** khớp order_fact. Tổng payment_value gốc **16.008.872,12 BRL** cũng khớp sau khi tổng hợp riêng. Đây là tổng toàn snapshot, khác GMV delivered của bộ lọc dashboard.

Kiểm tra độc lập trên CSV gốc đối với cohort năm 2018, bang SP: số đơn, GMV delivered, số mẫu giao hàng và số giao trễ khớp kết quả API. Số liệu/chữ ký file cụ thể nằm trong `reports/data_quality.json` và `reports/verification.json`.

## Kiểm thử phần mềm

**27 tests passed**: nhân bản item/payment, tổng hợp review, key trùng, giao đúng ngày hẹn, mẫu số KPI, filter bang/ngày, tập rỗng, đếm đơn seller, từ chối thiếu token, routing khi không có key, provider fallback mô phỏng HTTP 429, tool name không hợp lệ, không có API SQL/shell tùy ý, đề xuất không tự ghi ERP, approve/retry/reject, kiểm tra payload và hợp đồng Odoo draft/currency/tax/freight.

API được khởi chạy thật bằng uvicorn và gọi HTTP trong môi trường kiểm thử. Streamlit AppTest đã kiểm tra render dashboard, nhấn câu hỏi mẫu, form tra tài liệu, form dự báo và filter bang SP. Không có lỗi exception trong các bước này. Đây là kiểm thử ứng dụng, **không phải kiểm tra ảnh chụp giao diện qua trình duyệt**.

## Truy xuất và định tuyến

Trên 17 câu hỏi có nguồn gán nhãn thủ công: TF-IDF Recall@1 = **14/17 (82,35%)**, Recall@3 = **16/17 (94,12%)**, MRR@5 ≈ **0,882**. Bộ nhỏ do chính dự án biên soạn, không đại diện toàn bộ câu hỏi ngoài thực tế. Xem từng câu trong báo cáo JSON.

Quy tắc local chọn đúng tool cho 12/12 câu kiểm tra đã định nghĩa. Đây **không phải độ chính xác của Agent dùng LLM**. Khi chưa có provider/key, ứng dụng hiển thị rõ chế độ local rules/trích đoạn.

## ML thực nghiệm

Train: 65.486 đơn. Validation: 6.418 đơn. Holdout tháng 07/2018: 6.047 đơn, tỷ lệ trễ khoảng 3,19%. HistGradientBoosting được chọn theo AP validation. Ngưỡng 0,13 được chọn theo F1 validation trước khi đánh giá test.

| Model | Test AP | Test ROC-AUC | Test Brier |
|---|---:|---:|---:|
| Prior baseline | 0,0319 | 0,5000 | 0,0328 |
| Logistic Regression | 0,0658 | 0,6109 | 0,0370 |
| HistGradientBoosting được chọn trên validation | 0,0500 | 0,6022 | 0,0415 |

Boosting: precision ≈ **4,56%**, recall ≈ **45,08%**, F1 ≈ **0,0828** ở ngưỡng đã chọn. Brier kém baseline; kết quả chưa đủ tốt cho tự động vận hành. Logistic có AP test cao hơn nhưng không được đổi thành model được chọn sau khi nhìn test. Cải thiện phải là vòng nghiên cứu mới và có holdout mới/thiết kế đánh giá rõ ràng.

Model không dùng actual delivery/review làm feature, nhưng vẫn có giới hạn snapshot và selection bias của các đơn đã giao. Không khẳng định khả năng dự đoán chính xác dữ liệu hiện tại, không trình bày điểm model như xác suất đã hiệu chỉnh.

## Chưa được xác minh trực tiếp

| Phần | Trạng thái |
|---|---|
| Odoo Community + Docker server thật | Chưa chạy; có adapter, Compose, hướng dẫn và tests mock |
| PostgreSQL analytics server thật | Chưa chạy; kiểm thử dữ liệu/API hiện dùng SQLite |
| Gemini / Groq / OpenRouter / NVIDIA | Có cấu hình endpoint và fallback; chưa gọi model thật vì không có key |
| AMD | Cần endpoint/model tương ứng tài khoản; adapter OpenAI-compatible tùy chỉnh |
| Ollama Qwen và embedding thật | Chưa có model server để benchmark |
| Windows + GTX 1650 | Chưa chạy; có script setup/start cho Windows |
| CI GitHub remote | Có workflow; chưa có repo/commit/CI remote được tạo |
| Trình duyệt kiểm tra ảnh giao diện | Chưa chạy; đã kiểm tra bằng Streamlit AppTest |

Không được mô tả các hàng trên là đã triển khai thành công chỉ dựa vào source hoặc mock test. Bản này là ứng dụng local có phần cốt lõi đã chạy và bộ tích hợp để xác minh tiếp trên môi trường của người dùng.
