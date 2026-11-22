# Sửa khởi động Olist Web v0.2 trên Windows

Gói này là bản vá cho Olist_Intelligence_Web_v0_2; không phải bộ cài độc lập. Có thể áp dụng trước hoặc sau gói Odoo Agent.

Đóng launcher vừa báo lỗi; nếu có ứng dụng cũ đang chạy, dừng tại terminal bằng Ctrl+C trước khi khởi động mã mới. Sao lưu mã nguồn nếu bạn đã tự sửa. Giải nén nội dung gói vào thư mục có run.py và START_WINDOWS.bat, cho phép thay các file cùng tên. Giữ nguyên .env, .venv, data, models và Docker volumes.

Đọc docs/WINDOWS_LAUNCH_FIX_VI.md. Mở http://127.0.0.1:8000/ để kiểm tra ứng dụng hiện tại trước khi dừng tiến trình. Gói không tự tắt tiến trình đang giữ cổng.

Launcher tự chọn .venv của dự án nếu đã có; hỗ trợ stdout/stderr UTF-8; không tự cài dependencies. START_WINDOWS.bat cũng đặt UTF-8. Khi cần cài dependencies, dùng Python trong .venv và requirements.txt.

51 kiểm thử đã qua trên Linux, có mô phỏng lỗi cp1258; chưa chạy native Windows và chưa kiểm tra trực tiếp máy bạn.
Commit cục bộ: a717f5a4941643a0766eef6dbbb3a85e692e7df9
