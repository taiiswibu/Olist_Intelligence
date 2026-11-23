---
name: olist-product-advice
description: Xếp hạng lựa chọn sản phẩm đã được Odoo tính giá và lọc ngân sách, chỉ dùng mã tạm và nhóm nhu cầu; không tự định giá hoặc tạo báo giá.
---

Đầu vào chỉ có nhóm nhu cầu, nhóm hàng hữu hạn và mức ngân sách tương đối. Odoo đã tính tổng và lọc các ứng viên; không biết tên khách, nhu cầu nguyên văn, giá hoặc tồn kho.

- Chọn tối đa ba mã ứng viên khác nhau từ đầu vào. Không tạo mã mới, không thêm sản phẩm ngoài danh sách.
- Chỉ trả mã lý do `category_match`, `lower_cost` hoặc `alternative`. `lower_cost` chỉ dùng với mức `low`; `category_match` chỉ dùng khi nhóm hàng khớp nhóm nhu cầu trong danh mục.
- Ưu tiên đúng nhóm nhu cầu; khi tương đương, chọn chi phí thấp hơn và tránh các lựa chọn trùng nhóm hàng nếu có lựa chọn phù hợp khác.
- Nhóm hàng DEMO không cho biết cấu hình, độ bền, hiệu quả, tồn kho hoặc khả năng giao hàng. Không suy ra các đặc tính này.
- Reviewer kiểm tra mã, nhóm hàng và lý do; không sửa giá, thuế, ngân sách hay số lượng. Việc tạo báo giá cần người dùng chọn phương án và duyệt đề xuất riêng trong Odoo.
