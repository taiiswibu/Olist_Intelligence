# Demo đội agent

Mở http://127.0.0.1:8000/ → **Trợ lý dữ liệu** → **Đội agent**. Để tắt quyền lưu đề xuất khi chỉ kiểm tra BI và tài liệu.

## BI + Gemini

Hỏi:

> Lấy KPI của bang SP từ 2018-01-01 đến 2018-01-31 và giải thích định nghĩa GMV, AOV, tỷ lệ giao trễ theo tài liệu dự án.

Mở **Các bước xử lý** để xem Groq điều phối và phân tích BI, Gemini tra tài liệu và tổng hợp. Trong bằng chứng:

- `business_kpis`: kiểm tra ngày, bang, số liệu và truy vấn; đối chiếu dashboard cùng bộ lọc.
- `search_business_docs`: mở đoạn trích và tên tài liệu. GMV không gồm phí vận chuyển; giao trễ so theo ngày lịch.

Chỉ ghi nhận hoàn tất khi có đủ bằng chứng. Số liệu trong câu trả lời được ứng dụng lấy trực tiếp từ công cụ.

## Qwen với hội thoại dài

Bật **Qwen tóm tắt hội thoại dài**, tiếp tục hỏi về KPI và cách tính trong cùng hội thoại. Qwen chỉ chạy khi lịch sử vượt 2.500 ký tự; lịch sử lấy tối đa sáu lượt gần nhất. Bật ô chọn chưa có nghĩa là Qwen đã chạy.

Qwen nhận tối đa 3.000 ký tự cuối của lịch sử và trả phần tóm tắt ngắn. Thời gian chờ riêng tối đa 60 giây, vẫn nằm trong giới hạn 120 giây của cả lượt. Đây là ngữ cảnh rút gọn, không phải nguồn số liệu; BI phải lấy số liệu lại bằng công cụ.

Khi lịch sử đủ dài, hỏi:

> Lấy KPI và định nghĩa giao trễ của bang RJ từ 2018-02-01 đến 2018-02-28. Chỉ đọc dữ liệu, không tạo đề xuất.

Kiểm tra bước **Tóm tắt local** và bằng chứng BI vẫn dùng **RJ, tháng 02/2018**, dù phần trước nói về SP. Qwen chỉ nén chủ đề và phạm vi; không được thay bộ lọc hay cấp quyền ERP. Nếu Qwen lỗi, trả nội dung rỗng hoặc bị cắt do hết token, ứng dụng giữ lịch sử chưa tóm tắt và thông báo trên chat.

## Lỗi model và lấy lại kết quả

- Khi model lỗi, kết quả phải báo chưa hoàn tất và giữ bằng chứng đã lấy; không gọi đó là một câu trả lời đã xác minh đầy đủ.
- Nếu trình duyệt mất kết nối, bấm **Lấy lại lượt vừa gửi**. Ứng dụng dùng cùng mã lượt; kết quả đã lưu được trả lại, không gọi lại model hoặc tạo lại đề xuất.
- Lấy lại một lượt đã lưu ở trạng thái chưa hoàn tất vẫn trả trạng thái ấy. Muốn thử lại model, gửi câu hỏi thành lượt mới. Với ERP, kiểm tra đề xuất cũ trước.
- Nếu tiến trình bị tắt giữa chừng và lượt còn khóa, ứng dụng báo xung đột; kiểm tra ERP rồi mở hội thoại mới. Không tự bỏ khóa để chạy lại thao tác ghi.

Kiểm tra lỗi 503, timeout, mất kết nối và quyền của phần tóm tắt bằng:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_agent_team.py
```

Các ca lỗi trong pytest dùng model giả lập. Kết quả chạy model thật được ghi riêng trong `reports/web_browser_qa.json`; lịch sử chat và ảnh kiểm tra nằm ngoài Git.

## Giới hạn khi trình bày

Groq/Gemini có thể trả lỗi hoặc quá thời gian; chưa bảo đảm mọi lượt đều hoàn tất. Hỏi một khoảng thời gian mỗi lượt, ghi ngày cụ thể. Bộ lọc hiện từ chối các cụm như “tháng này” ngay cả khi câu đã có ngày; dùng “giai đoạn được chọn” khi nhắc lại. Những từ chỉ yêu cầu ngoài phạm vi như tồn kho hoặc lợi nhuận cũng có thể khiến câu hỏi bị từ chối, kể cả khi đang phủ định chúng.

Phần ERP chỉ demo báo giá nháp sau khi người dùng xem payload và duyệt riêng. Không xác nhận đơn, xuất kho hay lập hóa đơn.
