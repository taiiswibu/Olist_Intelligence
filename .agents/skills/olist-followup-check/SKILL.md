---
name: olist-followup-check
description: Kiểm tra bản nháp giao việc chăm sóc khách so với bản chụp Odoo trước khi trình người dùng duyệt. Chỉ kiểm tra, không tạo hoạt động hoặc gửi nội dung cho khách.
---

Đối chiếu mỗi đề xuất với đúng báo giá trong nguồn. Chấp nhận chỉ khi lý do nằm trong các mã lý do được cung cấp và nội dung không bịa sự kiện.

Đối chiếu bằng case_id tạm và các dữ kiện tối thiểu. Không có danh tính, số tiền hoặc ghi chú khách trong nguồn cloud; không suy đoán hoặc yêu cầu khôi phục các thông tin đó. Action phải thuộc allowed_actions.

- Không coi ngày cập nhật báo giá là ngày liên hệ khách. Không biến việc quá hạn thành bằng chứng khách từ chối hay sắp mua.
- Rà việc đã có để tránh gợi ý tạo việc trùng; có thể gợi ý xem lại việc đang hẹn.
- no_activity không chứng minh chưa nhận phản hồi. has_activity không chứng minh lịch việc tương tự hoặc đã thực hiện. Từ chối lời khẳng định về các sự kiện không có trong nguồn.
- Với action review_existing_activity, note phải hướng dẫn xem lại công việc/hoạt động hiện có; chỉ nói rà báo giá hoặc soạn lời liên hệ khách là chưa đúng phạm vi.
- Không chấp nhận lời khẳng định đã tạo việc, đã gọi điện, đã gửi email, xác nhận đơn hoặc hóa đơn.
- Báo giá draft chưa chứng minh đã gửi cho khách. Không chấp nhận suy diễn thành đơn hàng đã chốt, việc giao hàng hoặc ký hợp đồng từ trạng thái này.
- Không suy diễn tỷ lệ chốt, doanh thu tương lai hoặc mức giảm giá mới. Số liệu chỉ được hiển thị từ nguồn, không đưa số vào văn bản model soạn.
- Trả valid=false và findings ngắn nếu thiếu căn cứ; không tự sửa dữ liệu nguồn hoặc thay phạm vi người dùng.
- Với draft, cả "chuẩn bị gửi lại" cũng thiếu căn cứ về lịch sử gửi. Các trạng thái unknown là chưa biết, không phải chưa xảy ra. Câu hỏi như "Khách đã phản hồi chưa?" không khẳng định khách đã phản hồi; vẫn đối chiếu phần còn lại của câu với action.

Luồng lựa chọn hữu hạn dùng skill `olist-followup-plan` riêng; hướng dẫn trên áp dụng cho benchmark văn bản.
