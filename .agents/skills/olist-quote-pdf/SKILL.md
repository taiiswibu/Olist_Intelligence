---
name: olist-quote-pdf
description: Hỗ trợ tải PDF của báo giá DEMO đã tồn tại trong Odoo ở trạng thái nháp hoặc đã gửi, với số liệu đọc trực tiếp từ chứng từ.
---

Tra báo giá bằng `odoo_demo_quotations` rồi gọi `odoo_quotation_document` theo ID Odoo, không dùng ID đề xuất local thay thế. Công cụ trả thông tin chứng từ và nút tải do ứng dụng dựng. Có thể đọc chi tiết bằng `read_odoo_quotation` trước khi giải thích.

- PDF lấy trạng thái, dòng hàng, chiết khấu, thuế, tổng và tiền tệ từ Odoo tại thời điểm tải; không dùng nội dung model viết làm số liệu chứng từ.
- Chỉ xuất báo giá nháp/đã gửi thuộc phạm vi Olist DEMO. Không xuất tài liệu bị cắt mất dòng như thể đã đầy đủ.
- Đề xuất pending chưa có báo giá Odoo thì hướng dẫn duyệt riêng trên ERP trước; không tự duyệt hoặc tạo báo giá để lấy PDF.
- Nút tải không gửi email, không đánh dấu đã gửi và không xác nhận đơn/lập hóa đơn. Không tuyên bố đã gửi cho khách.
- Khi tải lỗi hoặc chứng từ đã đổi trạng thái, yêu cầu đọc lại; không tự dùng bản cũ thay thế mà không báo.

Endpoint tải có xác thực: `GET /erp/quotations/{order_id}/pdf`. Phần dựng file nằm ở `olist/sales_exports.py`, không gọi report action có thể ghi attachment trong Odoo.
