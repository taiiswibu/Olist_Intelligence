# Cập nhật Odoo và Agent Lab cho Olist Web v0.2

1. Tắt ứng dụng đang chạy. Gói này bổ sung vào bản Olist_Intelligence_Web_v0_2, không phải bản cài độc lập.
2. Sao lưu các file mã nguồn bạn đã tự sửa nếu có. Giải nén các file trong gói vào đúng thư mục dự án chứa run.py, cho phép thay các file mã nguồn cùng tên. Các thư mục docs, olist, scripts, tests cần gộp vào thư mục sẵn có.
3. Giữ nguyên .env, .venv, data và models của bạn. Gói không chứa hay thay các file đó.
4. Đọc docs/ODOO_AGENT_GUIDE_VI.md: hướng dẫn cài Odoo Docker, cấu hình .env, kiểm tra và nhập 10 báo giá DEMO.
5. PowerShell tại thư mục dự án:

   .\.venv\Scripts\python.exe -m pip install --timeout 180 --retries 10 -r requirements-agent.txt
   .\.venv\Scripts\python.exe manage.py odoo-check
   .\.venv\Scripts\python.exe manage.py agent-lab --provider groq

   Agent Lab chỉ chạy khi đã cấu hình nguồn LLM; odoo-check cần Odoo đã khởi động và đúng tài khoản.
6. Agent Lab là CLI riêng. START_WINDOWS.bat vẫn mở web hiện có; Assistant web chưa chuyển sang Agent Lab.
7. git-history/Olist_Agent_History.bundle là bản sao lịch sử Git cục bộ để khôi phục khi cần, không phải xác nhận đã có repo GitHub. Không cần chép bundle vào dự án để chạy.

Đã qua 46 tests và kiểm tra HTTP HTML/assets/cookie/chat trên Linux Python 3.12. Chưa xác minh Windows, Odoo server hoặc cloud API thật. Chưa fine-tune LLM.
Commit: 2333e0de7abc0504a2034d414cee0033048e3f66
