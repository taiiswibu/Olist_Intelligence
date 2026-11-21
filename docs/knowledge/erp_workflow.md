# Quy trình ERP demo
Tài liệu quy trình do người làm dự án tự thiết kế, không phải quy trình của Olist.
Nguồn phần mềm: https://www.odoo.com/documentation/19.0/administration.html

## Odoo Community miễn phí và phạm vi tích hợp
Odoo Community tự cài local là phần mềm mã nguồn mở LGPLv3. Dùng cùng PostgreSQL và Docker, không cần thuê VPS. Không đồng nhất bản này với gói Odoo Online One App Free; external API của các gói Online có giới hạn theo gói. Dự án gọi RPC của bản Community local. Adapter chỉ gọi các thao tác được lập trình sẵn, không nhận tên model hay method tùy ý từ người dùng hoặc LLM.

## Import dữ liệu Olist vào Odoo
Lệnh odoo-seed tạo khách demo từ customer_unique_id, sản phẩm demo từ product_id/category và báo giá nháp theo đơn lịch sử. Khách dùng ref OLIST-DEMO:, sản phẩm dùng default_code OLIST-DEMO:, đơn có origin OLIST-DEMO:. Giá và cước là BRL qua pricelist riêng. Không replay trạng thái delivered thành nghiệp vụ giao hàng thật; không tự xác nhận đơn, xuất kho, lập hóa đơn hoặc thu tiền.

## Duyệt tạo báo giá
Người dùng chọn khách và sản phẩm demo, nhập số lượng/đơn giá, lưu đề xuất pending. Chưa ghi báo giá vào Odoo tại bước này. Sau khi xem payload và đồng ý, người dùng nhấn duyệt. Backend chuyển trạng thái executing trước khi gọi Odoo, tạo sale.order draft với origin OLIST-ACTION:<id>, sau đó lưu kết quả done. Không gọi action_confirm. Từ chối chỉ áp dụng cho pending. Nếu mạng lỗi, duyệt lại dùng cùng origin để tìm báo giá đã tạo trước đó. Nếu tiến trình bị dừng ở executing, cần đối soát thủ công trước khi khôi phục; không tự phát lại lệnh.

## Giới hạn bản local
Chỉ bind API/UI trên localhost. Một người vận hành, APP_TOKEN chung giữa giao diện và backend; chưa có đăng nhập nhiều người hoặc RBAC doanh nghiệp. Adapter dùng tài khoản/API key của Odoo, không chia sẻ secret cho LLM. Chỉ thao tác trên bản demo Odoo, không kết nối ERP sản xuất. RPC XML-RPC còn dùng trong Odoo 19 nhưng đã được thông báo deprecated; adapter tách riêng để có thể thay bằng API mới.
