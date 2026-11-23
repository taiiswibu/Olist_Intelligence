# AI hỗ trợ bán hàng trong Odoo

Addon Odoo Community 19 dùng Sales và Activities. Bản đầu chỉ đọc khách/báo giá Olist DEMO nháp hoặc đã gửi; không cần CRM/Project.

## Cài đặt

Từ thư mục dự án, sau khi cài môi trường Python:

```powershell
.venv\Scripts\python.exe scripts/configure_odoo_ai.py
docker compose up -d --no-deps odoo
```

Khởi động lại `START_WINDOWS.bat`. Khóa kết nối riêng được giữ trong `.env` và biến môi trường của Odoo; không nhập vào chat hoặc đưa lên Git. Backend vẫn dùng `127.0.0.1:8000`. Container gọi qua `host.docker.internal:8000`, không cần mở backend ra mạng LAN.

Đăng nhập Odoo bằng quản trị viên, bật chế độ nhà phát triển trong Settings. Mở **Apps → Update Apps List**, bỏ bộ lọc Apps nếu cần, tìm **AI hỗ trợ bán hàng** (`olist_sales_ai`) rồi **Install**. Việc cài vào database đang dùng do quản trị viên thực hiện sau khi xem thay đổi. Không xóa volume hoặc tạo lại database.

## Sử dụng

- **AI hỗ trợ bán hàng → Khách cần chăm sóc**: xem báo giá trong phạm vi được phép, lý do cần xem, hạn báo giá và lịch việc.
- Ưu tiên việc quá hạn, báo giá hết/sắp hết hạn trong ba ngày, chưa có lịch chăm sóc, rồi đến các báo giá còn lại. Số tiền và ngày lấy từ Odoo, không phải dự đoán của AI.
- Chọn tối đa hai mươi báo giá → **Phân tích AI**. Groq soạn đề xuất, Gemini kiểm tra. Màn hình tự lấy kết quả hoặc dùng **Lấy kết quả**. Có thể rời màn hình và mở lại cùng đề xuất, không tạo lượt AI khác.
- Ở **Đề xuất chờ duyệt**, đọc dữ liệu đối chiếu, lý do, nội dung nháp; sửa tên việc, loại việc, người phụ trách, ngày hẹn. Đánh dấu đã kiểm tra rồi bấm **Duyệt tạo việc** và xác nhận.
- Việc xuất hiện trên báo giá trong Activities. Mở và đánh dấu hoàn tất bằng chức năng gốc Odoo. **Công việc và lịch sử** giữ người duyệt, thời điểm, nội dung đã duyệt và liên kết tới việc.

Nhân viên chỉ dùng báo giá do mình phụ trách. Quản lý dùng báo giá của mình hoặc các nhóm do mình làm trưởng nhóm, trong công ty đang chọn. Chỉ giao việc cho bản thân hoặc thành viên các nhóm mình quản lý. Các tài khoản cần có quyền Sales tương ứng; quyền All Documents không mở rộng phạm vi module này cho nhân viên.

Phân tích chỉ lập đề xuất; chưa tạo Activities, chưa gửi nội dung liên hệ. Chứng từ thay đổi thì phân tích lại. Lượt duyệt lặp không tạo thêm việc. Việc cùng loại/người/báo giá đã có sẽ chặn tạo trùng. Module không xác nhận đơn hoặc lập hóa đơn.

## Kiểm tra và lỗi kết nối

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/test_odoo_ai.py
```

Lệnh thứ hai cài addon và kiểm tra phân quyền/duyệt trên database mới có tiền tố `olist_ai_test_`; tự xóa đúng database thử khi kết thúc. Cần Docker/Odoo đang chạy. Không chạy trên `olist_demo`.

Khi mất kết nối, mở lại cùng đề xuất và lấy kết quả. Một lượt có tối đa hai lần gọi model; lượt bị ngắt được báo chưa hoàn tất, không tự chạy lại hoặc tự giao việc. Tạo đề xuất mới sau khi đã kiểm tra cấu hình. Nếu chưa thấy dữ liệu, kiểm tra mã khách `OLIST-DEMO:`, origin `OLIST-`, trạng thái nháp/đã gửi, người phụ trách, trưởng nhóm và công ty đang chọn. Không thêm dữ liệu giả vào nguồn Olist để làm đầy màn hình.
