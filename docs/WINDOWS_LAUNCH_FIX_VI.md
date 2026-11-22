# Sửa lỗi khởi động trên Windows / VS Code

Ngày 22/11/2026. Gói này dành cho ứng dụng HTML Web v0.2, có thể áp dụng trước hoặc sau gói Odoo Agent. Không cần cài lại Odoo hay nhập lại dữ liệu.

## Áp dụng

Đóng cửa sổ START_WINDOWS.bat vừa báo lỗi. Giải nén các file của gói vào thư mục chứa `run.py`, cho phép thay file mã nguồn cùng tên. Giữ nguyên `.env`, `.venv`, data, models và Docker volumes.

Launcher mới ưu tiên Python `.venv` của chính dự án khi bạn vô tình bấm Run Code bằng Python khác; stdout/stderr dùng UTF-8. START_WINDOWS.bat cũng đặt UTF-8. Nếu `.venv` vẫn thiếu thư viện, thông báo chỉ rõ tên thư viện và Python đang chạy; launcher không tự tải dependencies.

## 1. Kiểm tra cổng 8000 trước khi mở thêm bản ứng dụng

Mở `http://127.0.0.1:8000/` trong trình duyệt. Nếu đúng Olist đang chạy bình thường, tiếp tục dùng phiên đó. Nếu muốn khởi động lại với mã mới, quay về terminal đã chạy nó và nhấn Ctrl+C.

Nếu không tìm được terminal, dùng **PowerShell** để xem tiến trình:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

Lấy số `OwningProcess`, thay `12345` trong lệnh sau:

```powershell
Get-CimInstance Win32_Process -Filter "ProcessId = 12345" |
    Select-Object ProcessId, ExecutablePath, CommandLine
```

Chỉ khi đường dẫn/lệnh xác nhận đó là Olist cũ (`run.py` hoặc `olist.api:app` của dự án), mới dừng đúng PID:

```powershell
Stop-Process -Id 12345
```

`12345` là ví dụ, không phải PID thực tế của máy bạn. Nếu là chương trình khác hoặc chưa xác định được, giữ nguyên và gửi thông tin nhận diện để xử lý. Không dùng lệnh dừng tất cả python.exe. Launcher không tự dừng bất kỳ tiến trình nào. Lỗi bind do quyền Windows được thông báo riêng, không mặc định coi là có app cũ.

## 2. Dùng đúng Python và dependencies

Mở terminal PowerShell, không phải khung Output của Code Runner:

```powershell
cd D:\Code\project_AI\Olist_Intelligence
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable); import uvicorn; print('uvicorn OK')"
```

Nếu `.venv\Scripts\python.exe` chưa tồn tại, chạy `SETUP_WINDOWS.bat`. Nếu kiểm tra báo thiếu uvicorn/thư viện khác, cài **toàn bộ** dependencies vào chính venv:

```powershell
.\.venv\Scripts\python.exe -m pip install --timeout 180 --retries 10 -r requirements.txt
```

Lệnh cài phải hoàn thành thành công. Không dùng `pip install uvicorn` bằng Python toàn cục để vá từng gói; Code Runner và launcher đang có thể dùng hai Python khác nhau.

## 3. Khởi động đúng một lần

```powershell
.\START_WINDOWS.bat
```

Mở `http://127.0.0.1:8000/` nếu trình duyệt không tự mở. Nếu hiện màn hình yêu cầu token, lấy APP_TOKEN trong `.env` nhập tại máy, không gửi vào chat.

Trong VS Code, dùng **Python: Select Interpreter**, chọn `.venv\Scripts\python.exe` của dự án, rồi chạy bằng terminal hoặc START_WINDOWS.bat. Nút Run Code của extension Code Runner có thể dùng cấu hình Python riêng. Vẫn có thể bị lỗi ở các script khác nếu gọi bằng interpreter toàn cục; gói này chỉ sửa launcher web.

## Đã kiểm tra / chưa kiểm tra

Kiểm tra tự động trên Linux: giả lập pipe cp1258 nghiêm ngặt với uvicorn không có, kiểm tra chuyển sang interpreter venv, tránh lặp chuyển interpreter, phân biệt cổng bận và lỗi quyền. Không có quyền truy cập laptop Windows của bạn và chưa chạy native Windows.

Nguồn: https://docs.python.org/3.12/library/sys.html · https://docs.python.org/3.12/using/cmdline.html · https://learn.microsoft.com/en-us/powershell/module/nettcpip/get-nettcpconnection · https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/get-ciminstance
