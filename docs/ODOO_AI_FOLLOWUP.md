# AI hỗ trợ bán hàng trong Odoo

## Kiểm tra rủi ro báo giá

Mở báo giá DEMO nháp/đã gửi → **Kiểm tra rủi ro**. Odoo đối chiếu hạn hiệu lực (sắp hết trong ba ngày), dòng sản phẩm, số lượng, đơn giá, chiết khấu, thuế đã chọn, trạng thái sản phẩm và điều khoản thanh toán. Mỗi cờ kèm bằng chứng tại máy và mức cần xem; đây chưa phải đánh giá tín dụng, lợi nhuận hoặc kết luận tuân thủ thuế.

Chiết khấu dương, giá bằng không hoặc chưa chọn thuế có thể đúng chủ đích; cần người bán đối chiếu. Khoảng chiết khấu kỹ thuật là không đến một trăm phần trăm, chưa thay chính sách phê duyệt của công ty. Không tự tính lại thuế, tổng tiền hoặc dùng giá Olist lịch sử. Tối đa một trăm dòng sản phẩm; vượt giới hạn thì báo rõ và chưa kiểm tra một phần.

**AI gợi ý câu hỏi đối chiếu** là bước tùy chọn: Groq soạn, Gemini kiểm tra từ danh mục mã cờ và mã tạm. Tên khách, sản phẩm, số tiền, ngày cụ thể và ghi chú không đi vào request model. Mỗi mã có đúng một câu hỏi; câu chứa số, liên hệ, nhiều câu hoặc mã ngoài danh sách bị chặn. Kiểm tra cấu trúc và reviewer chưa bảo đảm đúng ngữ nghĩa; bạn vẫn đọc lại trước khi dùng. API lỗi thì giữ nguyên cờ local, không tự thay bằng kết quả AI khác. `FOLLOWUP_AI_MODE=rules_only` trả câu hỏi mẫu và không gọi model.

Bản kiểm tra giữ nguyên nguồn và lịch sử. Khi dòng hàng, hiệu lực, cấu hình được kiểm tra hoặc ngày đối chiếu thay đổi, màn hình báo **Nguồn đã đổi**; bấm **Kiểm tra lại** để tạo bản mới. Nhân viên xem báo giá của mình, quản lý xem nhóm mình, trong công ty đang chọn. Chức năng không tạo Activity, gửi tin, xác nhận đơn hay xuất hóa đơn. Mọi thay đổi chứng từ thực hiện và duyệt riêng trong Odoo.

Kiểm thử riêng: `tests/test_quote_risks.py` kiểm tra tại HTTP của cả hai model; addon `tests/test_risk.py` kiểm tra quy tắc, nguồn cũ, quyền và không ghi nghiệp vụ. Browser runner `tests/browser_quote_risks.py` chỉ nhận database tạm có dấu sở hữu từ `scripts/test_odoo_ai.py --keep-database`; không đưa dữ liệu fixture vào database đang sử dụng. Chưa có kết quả người bán chấm hoặc bằng chứng AI phát hiện rủi ro tốt hơn quy tắc.

### Ghi nhận và kiểm tra lại

Bấm **Ghi nhận xử lý**, chọn **Cần sửa**, **Đúng chủ đích** hoặc **Cần quản lý xem** cho cờ cần xử lý và nhập lý do (tối đa một nghìn ký tự). Các cờ chưa chọn được giữ nguyên. Nhận xét áp dụng cho toàn bộ bằng chứng của mã cờ trong bản đang xem; người bán tự ghi nhận, quản lý xem theo quyền nhóm. **Đúng chủ đích** vẫn giữ cờ và chưa thay cho phê duyệt chứng từ. Bộ lọc **Cần quản lý xem** dùng lựa chọn mới nhất của từng cờ, không tạo Activity hoặc gửi thông báo.

Desktop nhập trực tiếp trong bảng. Trên điện thoại, chạm thẻ cảnh báo để chọn trạng thái và nhập lý do, lưu thẻ rồi bấm **Lưu ghi nhận**. Nếu nút xử lý nằm trong menu dấu ba chấm trên thanh công cụ thì mở menu này để chọn.

Mỗi thay đổi lưu người ghi, thời điểm server và lý do vào **Lịch sử xử lý**. Không sửa/xóa lịch sử; ghi lại cùng lựa chọn và lý do không tạo thêm dòng. Nếu có người vừa ghi nhận cùng cờ khi bạn đang nhập, cửa sổ yêu cầu mở lại để đối chiếu. Nguồn đã đổi thì phải kiểm tra lại trước khi ghi nhận.

**Kiểm tra lại** liên kết bản mới với bản đang xem; kiểm tra từ báo giá liên kết với bản gần nhất được phép đọc. Tab **Trước/sau** hiển thị bằng chứng và ba nhóm: mới xuất hiện, vẫn xuất hiện, không còn xuất hiện. Sửa một phần dòng hàng mà cùng mã vẫn còn thì tiếp tục ghi là vẫn xuất hiện. Cờ biến mất có thể do dữ liệu/trạng thái thay đổi, chưa tự chứng minh nghiệp vụ đã đúng. Bản mới bắt đầu **Chưa ghi nhận**, không tự nhận lý do hay xác nhận từ bản cũ.

Các lý do chỉ lưu trong model ghi nhận tại Odoo, không đưa vào prompt hoặc ghi chú gửi khách. Luồng này hoạt động khi không có API model. Mốc thời gian dùng truy vết, chưa phải thời gian lao động hoặc bằng chứng tiết kiệm thời gian. Chỉnh giá, thuế và điều khoản trên form Odoo rồi kiểm tra lại; module không tự sửa S00021 hay chứng từ khác.

### Tải báo cáo xử lý rủi ro

Mở một bản kiểm tra → **Tải báo cáo PDF** hoặc **Tải báo cáo Excel** (trên điện thoại có thể nằm trong menu dấu ba chấm). File lấy bằng chứng đã lưu của bản đang xem và bản trước được liên kết, kèm ghi nhận, lý do, người ghi, thời điểm và các điểm cần đối chiếu tiếp. Nhận xét bản trước được giữ riêng; bản mới chưa ghi nhận thì file cũng ghi đúng trạng thái đó. Mỗi mã chỉ đếm một cờ dù xuất hiện ở nhiều dòng hàng.

Excel có ba trang **Tổng quan**, **Đối chiếu**, **Lịch sử**; nội dung nhập được lưu dưới dạng chữ, không chạy công thức/link. PDF dùng mẫu báo cáo Odoo, có thời điểm xuất và múi giờ. Khi nguồn đã đổi, file ghi cảnh báo và giữ bằng chứng cũ; xuất lại từ bản mới sau khi kiểm tra lại nếu cần đối chiếu dữ liệu hiện tại. Chưa có bản trước hoặc chưa có AI/ghi nhận thì hiển thị rõ, không tự bổ sung.

Xuất file chỉ đọc dữ liệu theo quyền báo giá/công ty hiện có, không gọi model, tạo ghi nhận, sửa chứng từ hoặc gửi file cho người khác. Lịch sử trong file gồm đúng hai bản được đối chiếu, tối đa một nghìn ghi nhận; vượt giới hạn thì báo lỗi và chưa xuất một phần. Các file có lý do và tên người ghi chỉ được tải qua phiên đăng nhập Odoo, không đưa lên Git hoặc dịch vụ tạo báo cáo bên ngoài.

Xem thêm [baseline và bảo vệ dữ liệu](AI_EVALUATION.md). Luồng chăm sóc mặc định chỉ gửi mã tạm, trạng thái và dấu hiệu nghiệp vụ; tên khách, số tiền và ghi chú giữ local. Có thể đặt `FOLLOWUP_AI_MODE=rules_only` rồi khởi động lại backend để không gọi API model cho luồng này.

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

## Đo thao tác thực tế

Sau khi nâng addon lên `19.0.1.2.0`, mở một báo giá DEMO và bấm **Bắt đầu lượt đo**. Server luân phiên soạn tay, mẫu quy tắc và AI theo cấu hình; lệch thứ tự khởi đầu giữa các tài khoản. Đây là lịch luân phiên để chạy pilot, chưa phải phân nhóm ngẫu nhiên hay bằng chứng nhân quả.

- **Soạn tay**: bản nháp trống, đối chiếu vẫn lấy từ Odoo; không gọi backend/model.
- **Mẫu quy tắc**: yêu cầu riêng `rules_only`, không gọi API model dù ứng dụng đang bật AI.
- **AI theo cấu hình**: dùng chế độ đang cấu hình. Nếu hệ thống đặt `FOLLOWUP_AI_MODE=rules_only`, kết quả thực tế vẫn là rules; CSV giữ cả cách được phân công và strategy thực chạy, không được tính lượt đó thành AI.

Mỗi người chỉ có một lượt đang mở trong công ty hiện tại. Bấm lại cùng báo giá sẽ mở lượt cũ; không đặt lại đồng hồ hoặc gọi model mới. Đồng hồ tính từ lúc bấm bắt đầu đến khi **Duyệt tạo việc**, lỗi phân tích hoặc **Bỏ qua**, gồm cả chờ model, đọc, sửa, rời màn hình và xác nhận. Không diễn giải thành thời gian chú ý thuần. Thời điểm kết thúc đầu tiên và kết quả đầu tiên được giữ, kể cả sau khi bỏ qua một lượt đã lỗi. Phê duyệt vẫn tạo Activities theo luồng có xác nhận, không dùng nút duyệt chỉ để dừng giờ nếu chưa muốn giao việc.

Mở **AI hỗ trợ bán hàng → Lượt đo thao tác**, chọn đủ các lượt cần so, gồm lỗi/bỏ qua/chưa xong → **Tải CSV lượt đo**. Bản tải riêng cho người xuất và quản trị viên, không chứa tên khách, tên nhân viên, mã báo giá, số tiền hoặc nội dung liên hệ. Dữ liệu chỉ lưu local; mã người tham gia/tình huống là mã ngẫu nhiên, không phải bảo đảm ẩn danh tuyệt đối. Thời gian của lượt chưa xong để trống, không thay bằng không. Lượt soạn tay/mẫu/AI vẫn dùng chung kiểm tra nguồn cũ, quyền và phê duyệt.

Một người vẫn chạy được pilot: kết thúc lượt, mở lại dòng ở **Lượt đo thao tác**, chọn **Tự chấm: Dùng được / Cần sửa / Không dùng được** rồi xác nhận. Chỉ người thực hiện tự chấm, không sửa thời gian hoặc ghi đè lựa chọn đầu. Lượt chưa có nội dung chỉ được đánh dấu không dùng được. Chấm kết quả cuối sau khi đọc/sửa, không coi đó là độ đúng của bản nháp nguyên gốc từ model. Thời gian tự chấm sau lượt đo tách khỏi thời gian làm việc. Đây là tự báo cáo, chưa phải đánh giá độc lập.

Đo trên tình huống đã thống nhất và chấm nghiệp vụ riêng. Sau khi tạo Activities, nguồn thay đổi; mã tình huống mới sẽ được cấp cho bản chụp khác. Không ghép hai bản chụp khác nhau thành cặp giống hệt. Chưa có người tham gia thì phiếu và thời gian thực tế vẫn là chưa thu thập; kiểm thử tự động không thay người dùng.

Đối chiếu CSV đã tải, giữ cả lượt lỗi/chưa xong:

```powershell
.venv\Scripts\python.exe scripts/benchmark_followup.py trials --csv path_to_export.csv --out data/processed/trial-summary.json
```

Lệnh kiểm tra mã lặp, thứ tự, thời điểm UTC và phép trừ thời gian trước khi tính. Báo riêng tỷ lệ duyệt, thời gian các lượt đã duyệt, tất cả lượt kết thúc, tự chấm và strategy thực chạy. CSV v2 giữ nguồn đánh giá `self`; CSV v1 vẫn đọc được nhưng phần tự chấm để chưa có dữ liệu. Không điền thời gian cho lượt chưa xong; không ghi đè báo cáo đã có. Thời gian ngắn do lỗi không được coi là làm việc nhanh. Báo cáo chỉ mô tả pilot và luôn giữ `benefit_claim_ready=false` vì chưa có điểm nghiệp vụ độc lập hoặc bằng chứng cỡ mẫu đủ để kết luận.

## Kiểm tra và lỗi kết nối

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/test_odoo_ai.py
```

Lệnh thứ hai cài addon và kiểm tra phân quyền/duyệt trên database mới có tiền tố `olist_ai_test_`; tự xóa đúng database thử khi kết thúc. Cần Docker/Odoo đang chạy. Không chạy trên `olist_demo`.

Khi mất kết nối, mở lại cùng đề xuất và lấy kết quả. Mặc định mỗi bước soạn/kiểm tra được gửi tối đa hai lần với lỗi HTTP tạm thời, từng lần được ghi trace; lỗi nội dung không tự soạn lại. Tổng lượt có deadline gồm cả hàng chờ, không tự giao việc. Xem [chính sách gọi model](AI_EVALUATION.md#hàng-chờ-và-thử-lại-có-giới-hạn). Nếu chưa thấy dữ liệu, kiểm tra mã khách `OLIST-DEMO:`, origin `OLIST-`, trạng thái nháp/đã gửi, người phụ trách, trưởng nhóm và công ty đang chọn. Không thêm dữ liệu giả vào nguồn Olist để làm đầy màn hình.
