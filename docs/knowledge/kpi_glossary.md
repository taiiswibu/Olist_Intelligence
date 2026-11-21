# Từ điển KPI của dự án
Tài liệu do dự án biên soạn từ schema Olist công khai. Không phải quy định kế toán hay tài liệu nội bộ Olist.
Nguồn: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

## GMV hàng hóa và doanh thu
Product GMV = tổng price của item thuộc các đơn có order_status='delivered', lọc theo ngày mua và bang khách hàng. Không bao gồm freight_value. Đây là giá trị hàng hóa, không phải doanh thu ròng của Olist. Không có commission, chi phí hay hoàn tiền chi tiết để tính lợi nhuận. Tiền tệ hiển thị BRL, ký hiệu R$.

## AOV hàng hóa
Product AOV = GMV hàng hóa / số order_id delivered trong cùng phạm vi. Mẫu số là đơn, không phải item hay payment. Không có đơn thì hiển thị không đủ dữ liệu, không chia cho 0. AOV này chưa gồm phí vận chuyển. Không dùng tổng payment_value làm cùng một metric.

## Tỷ lệ giao trễ
Late-delivery rate = số đơn giao sau NGÀY hẹn / số đơn delivered có cả ngày giao thực tế và ngày hẹn. So sánh ngày lịch, không so giờ với 00:00 của ngày hẹn. Giao bất kỳ giờ nào trong ngày hẹn vẫn đúng hạn. Đơn hủy, đơn chưa giao, đơn thiếu một trong hai ngày không nằm trong mẫu số. Bộ lọc thời gian dựa ngày mua; tỷ lệ chỉ phản ánh các đơn có kết quả đã biết trong snapshot.

## Tỷ lệ hủy
Cancellation rate = số đơn order_status='canceled' / tất cả đơn trong phạm vi. Status unavailable là trạng thái riêng, không tự gộp vào canceled. Hủy theo tháng mua, không phải tháng có sự kiện hủy vì CSV không có timestamp hủy.

## Seller, ngành hàng và số đơn
Số đơn = COUNT DISTINCT order_id. Bảng seller lấy các seller có ít nhất 20 đơn trong phạm vi, xếp theo số đơn trễ giảm dần, lấy tối đa 20 seller. Cột giao trễ của seller là kết quả đơn hàng có seller tham gia, không chứng minh seller là nguyên nhân gây trễ; một đơn có thể có nhiều seller. Bảng ngành hàng chỉ tính item của đơn delivered. Bang là customer_state, không phải seller_state.

## Grain và chống nhân đôi số tiền
Order_fact có một dòng mỗi đơn. Item_fact có một dòng mỗi (order_id, order_item_id). Item và payment được tổng hợp riêng về order_id trước khi join; không join raw item với raw payment rồi SUM vì sẽ nhân số tiền. Geolocation có nhiều dòng mỗi ZIP prefix nên không join raw vào facts. Muốn tính khách mua lại dùng customer_unique_id, không dùng customer_id.
