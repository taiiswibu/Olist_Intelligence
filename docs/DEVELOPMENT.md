# Quản lý mã nguồn

Ứng dụng đã có Git local, nhánh main. Các mốc đầu:

- `chore: import local Olist baseline and Windows setup fix`
- `feat: replace Streamlit with HTML dashboard and browser sessions`

Mỗi phần việc tiếp theo được kiểm tra rồi commit riêng. Không có tiến trình commit nền.

Tại lúc đóng gói v0.2, **chưa xác minh tạo/push repo GitHub**. Kết nối GitHub nhận đúng tài khoản `taiiswibu`, nhưng công cụ hiện không tạo được repository mới và trình duyệt đang cần hoàn tất đăng nhập. Không coi repo hoặc CI là đã tồn tại/thành công.

Gói ZIP kèm `olist_history.bundle` chứa lịch sử Git đã lưu, không chứa `.env`, CSV, database hay artifact ML. Có thể khôi phục một checkout có lịch sử:

```bash
git clone olist_history.bundle Olist_Intelligence_Git
```

Khi repo trên GitHub được tạo và được cấp quyền phù hợp, cấu hình remote theo URL được GitHub xác nhận rồi push. Không ghi token vào URL, file cấu hình dự án hoặc commit.
