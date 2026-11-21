# Dữ liệu và giới hạn
Tài liệu do dự án biên soạn. Nguồn dữ liệu gốc: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

## Nguồn dữ liệu, giấy phép và thời gian
Olist cung cấp dữ liệu thương mại đã ẩn danh trên Kaggle, khoảng 100.000 đơn giai đoạn 2016–2018, giấy phép CC BY-NC-SA 4.0. Đây là snapshot lịch sử, không có nguồn đơn hàng hiện tại. reports/data_quality.json lưu số dòng và SHA-256 của CSV thực tế đã tải. Không khẳng định timezone UTC; timestamp nguồn không có thông tin timezone. Dự án giữ timestamp naive.

## Các bảng CSV
orders: order_id, customer_id, trạng thái và các timestamp mua, duyệt, giao cho carrier, giao cho khách, ngày hẹn. customers: customer_id theo đơn, customer_unique_id nhận diện khách qua các đơn, ZIP/city/state. order_items: mỗi item có order_id, order_item_id, product_id, seller_id, price, freight_value. payments: có thể nhiều payment mỗi đơn. reviews: có thể nhiều review mỗi đơn, không giả định review_id duy nhất. products: category, chiều dài tên/mô tả, ảnh và kích thước/khối lượng; không có tên sản phẩm thực. sellers: vị trí seller. geolocation: nhiều điểm mỗi ZIP prefix. translation: category tiếng Bồ Đào Nha sang tiếng Anh.

## Giá trị thiếu và dữ liệu không có
Thiếu ngày giao có thể là chưa giao hoặc dữ liệu không đầy đủ; không tự tạo ngày giả. Category thiếu dùng unknown. Snapshot không có tồn kho, giá vốn, BOM, purchase orders hay nhà máy. Không được suy ra tồn kho từ số lượng bán. Sản phẩm trong Odoo được đặt tên DEMO từ category và mã rút gọn, không phải tên hàng thật trong Olist.
