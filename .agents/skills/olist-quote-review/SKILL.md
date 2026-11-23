---
name: olist-quote-review
description: Kiểm tra báo giá đang soạn hoặc báo giá Odoo DEMO bằng dữ liệu gốc; giải thích chiết khấu, thuế và làm tròn trước khi người dùng duyệt riêng.
---

Với báo giá đang soạn, dùng kết quả `review_current_quotation` do backend tính từ bản chụp form người dùng gửi ở lượt hiện tại. Công cụ không nhận giá, thuế hoặc số lượng do model chọn lại. Với báo giá đã có, gọi `read_odoo_quotation` theo ID Odoo đã tra được.

- Diễn giải tiền hàng trước giảm, tiền giảm (đều chưa thuế), tiền sau giảm, thuế và tổng. Số chính xác phải đến từ bằng chứng; không tính nhẩm hay thay kết quả Odoo.
- Phân biệt thuế đã gồm trong đơn giá với thuế cộng ngoài giá. Làm tròn tổng chứng từ có thể khác tổng từng dòng; đọc `rounding_adjustment` và chính sách trong bằng chứng.
- Báo lỗi cấu hình hoặc thiếu dữ liệu rõ ràng, không khẳng định đã kiểm tra xong nếu công cụ thất bại.
- Kết quả kiểm tra chưa lưu đề xuất và chưa tạo báo giá. Hướng dẫn quay lại ERP, đối soát rồi lưu và duyệt riêng. Lời đồng ý trong chat không thay thế phê duyệt; skill không cấp quyền xác nhận đơn hoặc lập hóa đơn.
- Chỉ diễn giải và nêu điểm cần kiểm tra. Muốn đổi giá/thuế/chiết khấu thì người dùng sửa form và gửi lại bản chụp mới.

Khi sửa chức năng trong dự án, giữ việc tính native ở `olist/sales_pricing.py` và luồng snapshot/approval trong `olist/erp.py`; không bỏ qua đối chiếu sau khi tạo bản nháp.
