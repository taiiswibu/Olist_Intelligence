# Odoo Community 19 trên Windows

Đây là hướng dẫn demo local. Compose và adapter đã được kiểm tra cấu trúc/mock, **chưa chạy Odoo server thật trong môi trường đóng gói**. Nếu xuất hiện lỗi, giữ log để xử lý; không coi import thành công chỉ vì container đã lên.

## 1. Chuẩn bị

Cài Docker Desktop phù hợp máy Windows, bật WSL2 theo hướng dẫn Docker. Sau khi Docker báo đang chạy, mở PowerShell tại thư mục dự án:

```powershell
docker compose up -d
docker compose ps
docker compose logs --tail 60 odoo
```

Compose dùng image chính thức `odoo:19.0`, `postgres:16`. Các tag có thể được cập nhật upstream; bản này chưa khóa digest image. Odoo nằm ở http://127.0.0.1:8069. Database PostgreSQL của Odoo không mở port ra host.

## 2. Tạo database demo

Mở http://127.0.0.1:8069 và tạo database riêng:

- Database: `olist_demo`.
- Email/login admin: dùng email bạn tự chọn, ghi đúng lại vào `.env`.
- Password: tự đặt; không gửi vào chat.
- Không bật dữ liệu demo có sẵn nếu muốn dễ đối soát dữ liệu dự án.

Nếu màn hình hỏi master password, dùng giá trị quản trị database của bản local; có thể tìm hướng dẫn trong log/tài liệu Odoo. Master password không phải `ODOO_PG_PASSWORD` và không dùng để gọi RPC. Không đưa database manager lên Internet.

Vào Apps, cài **Sales** (`sale_management`). Chưa cần Inventory/Accounting. Sau khi cài xong, cập nhật `.env`:

```dotenv
ODOO_URL=http://127.0.0.1:8069
ODOO_DB=olist_demo
ODOO_LOGIN=your_admin_email
ODOO_PASSWORD=your_local_password_or_api_key
```

Khuyến nghị dùng API key/tài khoản tích hợp riêng sau khi luồng demo đã chạy. `ODOO_PASSWORD` là secret cho người dùng Odoo, không phải mật khẩu PostgreSQL. Trong bản demo một operator, quyền ghi chỉ qua các method đã lập trình và bước duyệt; chưa triển khai đầy đủ phân quyền enterprise.

## 3. Import 10 đơn nháp từ Olist

Sau khi đã chạy SETUP_WINDOWS.bat:

```powershell
.\.venv\Scripts\python.exe manage.py odoo-seed --limit 10
```

Lệnh tạo khách/sản phẩm demo và quotation nháp, không xác nhận đơn. `origin` giữ mã đơn Olist để truy vết, tránh import lặp khi chạy lại tuần tự. Tên sản phẩm DEMO được tạo từ category vì CSV không có tên hàng thật. Một đơn có nhiều seller vẫn được biểu diễn bằng một quotation, không giả lập đầy đủ marketplace fulfillment.

Giá item/cước được đưa vào **pricelist BRL riêng**. Sản phẩm khai báo service để tránh giả lập số tồn; cước thành dòng dịch vụ riêng. Không dùng giá trên product card làm giá lịch sử mọi đơn; giá order line lấy từng item.

## 4. Dùng trên ứng dụng

Khởi động lại START_WINDOWS.bat sau khi sửa `.env`. Mở tab ERP & Phê duyệt → Kết nối → chọn khách/sản phẩm → nhập số lượng và đơn giá BRL → lưu đề xuất → kiểm tra payload → tick đồng ý → duyệt.

Trong Odoo Sales phải thấy báo giá draft mới có origin `OLIST-ACTION:<id>`. Kiểm tra tiền tệ BRL và tổng tiền. Chạy lại cùng action không tạo báo giá thứ hai trong cùng tiến trình. Nếu mạng timeout sau khi ghi, hệ thống tìm lại theo origin khi bạn duyệt lại; không bảo đảm exactly-once xuyên nhiều tiến trình nếu có thao tác ngoài ứng dụng. Không chạy nhiều instance trên cùng demo database.

Nếu action kẹt `executing` do tiến trình dừng, đối soát origin trong Odoo rồi mới khôi phục trạng thái thủ công; không sửa state hoặc phát lại yêu cầu khi chưa đối soát.

## 5. PostgreSQL phân tích tùy chọn

Mặc định BI dùng SQLite để giảm tài nguyên. Muốn chuyển sang PostgreSQL:

```powershell
docker compose --profile postgres up -d analytics-db
```

Sửa `.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://olist:olist_local_demo@127.0.0.1:5433/olist_analytics
```

Nếu đổi `ANALYTICS_PG_PASSWORD` hãy dùng password tương ứng trong URL (URL-encode ký tự đặc biệt). Sau đó:

```powershell
.\.venv\Scripts\python.exe manage.py ingest
```

Khởi động lại ứng dụng. Không dùng database nội bộ Odoo cho ETL; hai database tách biệt. Bản PostgreSQL chưa được kiểm thử với server thật trong môi trường phát hành.

## 6. Dừng

```powershell
docker compose stop
```

Dữ liệu nằm trong Docker volumes. Không dùng `down -v` nếu muốn giữ database.

Nguồn chính thức:

- https://www.odoo.com/documentation/19.0/administration.html
- https://www.odoo.com/documentation/19.0/developer/reference/external_rpc_api.html
- https://github.com/odoo/docker
