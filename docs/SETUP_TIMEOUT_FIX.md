# Khắc phục pip download timeout trên Windows

Log nhận ngày 21/11/2026 cho thấy tải NumPy bị dừng với `ReadTimeoutError` từ `files.pythonhosted.org`, dùng Python 3.12 và pip 24.0. Log không ghi nhận lỗi không tương thích phiên bản.

## Áp dụng bản sửa

Giải nén nội dung Olist_Windows_Setup_Timeout_Fix.zip vào thư mục dự án đang có, ví dụ `D:\Code\project_AI\Olist_Intelligence`. Cho phép ghi đè `scripts\setup.ps1`, sau đó chạy lại `SETUP_WINDOWS.bat` bằng File Explorer hoặc Terminal.

Chỉ script cài đặt được thay; không chứa `.env`, không xóa `.venv` hoặc pip cache. Timeout socket tăng lên 180 giây, retry kết nối 10 lần, thử lại lệnh cài tối đa 3 lần. Nếu pip có hỗ trợ `--resume-retries` thì bật thêm; pip 24 vẫn chạy được vì script kiểm tra tùy chọn trước. Đây không phải bảo đảm tải thành công khi đường truyền vẫn gián đoạn.

## Chạy lại bằng PowerShell mà không tải patch

```powershell
cd D:\Code\project_AI\Olist_Intelligence
.\.venv\Scripts\python.exe -m pip install --timeout 180 --retries 10 --progress-bar off -r requirements.txt
if ($LASTEXITCODE -eq 0) {
    .\.venv\Scripts\python.exe manage.py setup
    if ($LASTEXITCODE -eq 0) { .\START_WINDOWS.bat }
}
```

Nếu vẫn timeout, kiểm tra hoặc đổi kết nối mạng rồi chạy lại; không cần cài lại Python. Không thêm `--no-cache-dir`, vì các gói đã tải đầy đủ có thể được dùng lại. Bản pip cũ không nhất thiết tiếp tục được phần file đang tải dở.

Nguồn tùy chọn pip: https://pip.pypa.io/en/stable/cli/pip/

## Xác minh bản sửa

Tùy chọn timeout/retries/progress-bar được kiểm tra với pip 25.0.1 trên Linux. Các tùy chọn này cũng được pip 24 hỗ trợ; riêng resume-retries chỉ được thêm khi pip thực tế có hỗ trợ. Script PowerShell được rà soát và đóng gói, chưa thực thi trên Windows thật trong môi trường sửa lỗi.
