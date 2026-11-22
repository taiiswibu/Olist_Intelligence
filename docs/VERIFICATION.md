# Xác minh bản 0.2

## Bổ sung launcher Windows / Code Runner — 22/11/2026

Launcher cấu hình stdout/stderr UTF-8 và chọn Python venv của dự án nếu có; batch đặt UTF-8 trước khi khởi động. Thông báo phân biệt cổng bận và lỗi quyền, không tự dừng tiến trình. Các regression tests giả lập pipe cp1258 nghiêm ngặt khi thiếu uvicorn, chuyển interpreter, tránh chuyển lặp và hai nhánh lỗi bind. Bộ kiểm thử sau bổ sung: **51 tests** khi đã cài dependencies Agent. Native Windows và cổng 8000 trên máy người dùng chưa được kiểm tra trực tiếp.

## Bổ sung Odoo diagnostics và Agent Lab — 22/11/2026

Agent Lab là CLI tùy chọn, không thay router của Assistant web. Kiểm thử framework thực thi qua LangChain/LangGraph với model giả, dữ liệu fixture và SQLite thật: nhiều lượt tool, khôi phục sau đóng/mở checkpoint, tách thread, schema sai, giới hạn model/tool, đề xuất chỉ pending và từ chối ID ngoài DEMO. Doctor kiểm tra các nhánh kết nối/xác thực/Sales bằng mock và không in lỗi chứa secret.

Toàn bộ suite với dependencies Agent đã cài: **46 tests**. Luồng HTTP HTML/assets/cookie/chat và đối soát dữ liệu vẫn kiểm tra bằng `scripts/verify_release.py`. Những phép kiểm tra này không chứng minh chất lượng model cloud, tốc độ trên Windows, hoặc Odoo server thật. Chưa huấn luyện LLM, chưa kiểm tra Groq thật, chưa push GitHub.

Dependencies Agent được tách trong `requirements-agent.txt`; app cơ bản vẫn không bắt buộc cài LangChain. Không có endpoint web mới cho Agent Lab trong lần bổ sung này.

Ngày kiểm tra: 21/11/2026. Môi trường Linux, Python 3.12; không đồng nhất kết quả với laptop Windows của người dùng.

## Phần đã chạy

- **34 kiểm thử tự động đã qua**: grain/đối soát item-payment, key trùng, ngày giao lịch, KPI/filter, auth, routing/fallback giả lập, approval/retry/reject và hợp đồng Odoo.
- API thật qua uvicorn: HTML/CSS/JS trả thành công, phiên cookie HttpOnly hoạt động, API từ chối thiếu auth, chat qua cookie hoạt động. Không đưa APP_TOKEN vào HTML/JS.
- Trình duyệt Chrome: xem dashboard bằng Olist thật, lọc SP, chuyển biểu đồ giao trễ, hỏi KPI, tìm tài liệu có nguồn, chạy form ML và kiểm tra lỗi rõ ràng khi Odoo chưa cấu hình. Chi tiết `reports/web_browser_qa.json`.
- JavaScript kiểm tra cú pháp bằng Node; Python compile và Git whitespace check đã qua.

## Dữ liệu và benchmark

Snapshot chín CSV chính thức có 99.441 đơn, 112.650 item. Tổng giá item gốc 13.591.643,70 BRL và tổng payment 16.008.872,12 BRL khớp analytical facts. Đối chiếu độc lập cohort 2018/SP cũng khớp API. Xem `reports/data_quality.json` và `reports/verification.json`.

Truy xuất lexical trên 17 câu tự biên soạn: Recall@1 14/17, Recall@3 16/17, MRR@5 khoảng 0,882. Quy tắc routing đúng 12/12 câu đã định nghĩa; không phải benchmark LLM cloud.

## ML vẫn là thử nghiệm

Không train/chọn lại model khi đổi frontend. HistGradientBoosting đã được chọn trên validation; holdout tháng 07/2018 có 6.047 đơn, AP khoảng 0,050, ROC-AUC khoảng 0,602, precision khoảng 4,56%, recall khoảng 45,08% tại ngưỡng 0,13. Brier kém baseline, nhiều cảnh báo sai. UI luôn ghi rõ giới hạn và chưa dùng để tự động quyết định. Không đổi sang Logistic sau khi xem test dù AP test của Logistic cao hơn.

## Giới hạn kiểm chứng

| Phần | Trạng thái |
|---|---|
| Frontend HTML/CSS/JS trên desktop Chrome | Đã xem và thao tác với API/dữ liệu thật |
| Cookie session, CSRF, một lần dùng ticket | Có kiểm thử tự động |
| Windows và script PowerShell | Chưa thực thi trên Windows thật |
| Odoo / analytical PostgreSQL server thật | Chưa chạy; adapter/Compose và tests mock |
| Gemini / Groq / OpenRouter / NVIDIA | Có cấu hình/fallback; chưa gọi model thật vì không có key |
| AMD | Cần endpoint/model theo tài khoản |
| Ollama LLM/embedding thật | Chưa benchmark |
| Responsive CSS | Đã triển khai; chưa kiểm tra viewport mobile thật |
| CI GitHub remote | Chỉ ghi nhận sau khi repo được tạo và workflow thực sự chạy |

Workflow GitHub và lịch sử Git cục bộ không tự chứng minh đã push hoặc CI thành công. Không có tiến trình tự commit nền khi phiên làm việc không hoạt động.
