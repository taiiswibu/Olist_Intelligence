# Olist Intelligence

Nếu VS Code báo thiếu `uvicorn`, lỗi tiếng Việt cp1258 hoặc cổng 8000 đang được dùng, xem [hướng dẫn khởi động Windows](docs/WINDOWS_LAUNCH_FIX_VI.md). Launcher ưu tiên Python `.venv` của dự án và xuất UTF-8; không tự dừng tiến trình đang giữ cổng.

Không gian dữ liệu thương mại chạy local: dashboard, hỏi bằng tiếng Việt, tra tài liệu có nguồn và tạo đề xuất báo giá trong Odoo Community.

**v0.2 — HTML / CSS / JavaScript + FastAPI.** Frontend được phục vụ cùng backend trên một địa chỉ. Không cần Node, frontend build hoặc VPS để chạy trên Windows. Biểu đồ SVG lấy số liệu thật từ API; không dùng số liệu mẫu thay thế khi chưa có dữ liệu.

## Chạy trên Windows

1. Cài **Python 3.12 64-bit**, giải nén/clone mã nguồn vào một thư mục.
2. Chạy **SETUP_WINDOWS.bat**. Bước này tạo `.venv`, cài requirements với timeout/retry, tạo `.env` và tải khoảng 45 MB CSV Olist chính thức.
3. Chạy **START_WINDOWS.bat**. Trình duyệt tự mở **http://127.0.0.1:8000/**.

Nếu trình duyệt không tự mở, truy cập địa chỉ trên và dùng giá trị `APP_TOKEN` trong `.env` để kết nối. Phiên trình duyệt dùng cookie HttpOnly, SameSite Strict; API key của các model không được đưa vào frontend. Link tự mở dùng ticket một lần trong URL fragment, được xóa khỏi thanh địa chỉ sau khi kết nối.

Bản cũ dùng cổng 8501; bản này dùng **8000**. Dừng tiến trình cũ trước khi chạy. Giữ cửa sổ Terminal mở; Ctrl+C để dừng.

### Dùng Terminal PowerShell

```powershell
cd D:\Code\project_AI\Olist_Intelligence
.\.venv\Scripts\python.exe -m pip install --timeout 180 --retries 10 --progress-bar off -r requirements.txt
.\.venv\Scripts\python.exe manage.py setup
.\.venv\Scripts\python.exe run.py
```

Chỉ chạy dòng tiếp theo sau khi dòng trước thành công. Lỗi thiếu `httpx` hoặc thư viện khác nghĩa là bước cài thư viện chưa hoàn tất hoặc đang dùng sai interpreter; dùng đúng `.venv\Scripts\python.exe`. Nếu pip timeout, giữ `.venv` và cache, chạy lại SETUP. Không dùng nút Run Code trong VSCode để chạy file batch; mở Terminal.

Nếu Kaggle không tải được, tải ZIP từ https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce và giải nén chín CSV trực tiếp vào `data/raw/`, rồi chạy `manage.py setup`.

## Các màn hình

| Màn hình | Chức năng |
|---|---|
| Tổng quan | KPI, xu hướng tháng, cơ cấu ngành hàng, bảng seller/bang/category, bộ lọc và xuất CSV |
| Trợ lý dữ liệu | Hỏi bằng tiếng Việt, xem công cụ, SQL, phạm vi và nguồn tài liệu |
| Kho tri thức | Tra định nghĩa KPI, từ điển dữ liệu, quy trình ERP và thiết kế ML |
| Rủi ro giao hàng | Chọn đơn lịch sử, chạy model thử nghiệm và đọc kết quả holdout |
| ERP & Phê duyệt | Kết nối Odoo, lưu đề xuất, xem payload và duyệt tạo báo giá nháp |
| Kiểm chứng dữ liệu | Đối soát CSV, checksum, báo cáo kiểm thử và nhật ký thao tác |

Frontend có bố cục responsive, thao tác bàn phím và không dùng CDN để tải thư viện biểu đồ/font. Các trang không bịa trạng thái tích hợp khi thiếu cấu hình.

## Dữ liệu và KPI

Nguồn: **Brazilian E-Commerce Public Dataset by Olist** trên Kaggle, chín CSV đã ẩn danh, giai đoạn 2016–2018. Snapshot đã chạy có **99.441 đơn và 112.650 item**. `reports/data_quality.json` ghi số dòng và SHA-256 thực tế. Setup tạo lại báo cáo theo file bạn tải.

- Mặc định dashboard lọc ngày mua **01/01/2017–31/08/2018**; không phải toàn bộ snapshot.
- Tiền tệ **BRL / R$**. GMV hàng hóa là tổng giá item của đơn delivered, chưa gồm cước; không phải doanh thu ròng/lợi nhuận Olist.
- AOV hàng hóa dùng số đơn delivered làm mẫu số, không dùng số item/payment.
- Giao trễ so sánh **ngày lịch**; giao trong ngày hẹn vẫn đúng hạn. Chỉ đơn delivered đủ ngày giao thực tế và ngày hẹn nằm trong mẫu số.
- Item/payment được aggregate riêng trước khi join để tránh nhân tiền. Customer mua lại phải dùng `customer_unique_id`.
- Không có tồn kho, giá vốn hoặc dữ liệu nhà máy trong nguồn này. Dữ liệu Odoo là các đối tượng demo chuyển đổi từ lịch sử, không phải ERP gốc của Olist.

Raw CSV, database, `.env` và artifact model không commit lên Git. Xem `DATA_LICENSE.md` cho CC BY-NC-SA 4.0 và attribution. Mã dự án có giấy phép riêng.

## Cấu hình LLM

Mở `.env` và điền provider/model bạn đang có quyền dùng, ví dụ:

```dotenv
LLM_PROVIDERS=groq,gemini,openrouter,nvidia,amd,ollama
GROQ_API_KEY=your_key
GROQ_MODEL=exact_model_id_available_to_your_account
GEMINI_API_KEY=your_key
GEMINI_MODEL=exact_model_id_available_to_your_account
```

Có sẵn endpoint cho Gemini, Groq, OpenRouter và NVIDIA. Với AMD, cung cấp `AMD_BASE_URL` theo đúng dịch vụ của bạn; chưa giả định nhà cung cấp. Model ID để trống có chủ đích vì chưa xác minh quota/model của tài khoản. Chỉ provider đủ key/model được gọi. Sửa `.env` xong cần khởi động lại.

```powershell
.\.venv\Scripts\python.exe manage.py models --provider groq
.\.venv\Scripts\python.exe manage.py models --provider gemini
.\.venv\Scripts\python.exe manage.py models --provider openrouter
.\.venv\Scripts\python.exe manage.py models --provider nvidia
```

Mặc định `LLM_PROVIDERS=` rỗng, không gọi cloud. Khi không có model/API, giao diện ghi rõ **quy tắc local / trích đoạn tài liệu**. Khi có LLM, model chọn công cụ từ danh sách cố định; số liệu BI vẫn dựng trực tiếp từ kết quả truy vấn, không để LLM tự viết lại số.

Fallback thử theo thứ tự khi lỗi, tối đa một lần mỗi provider. Không xoay key/tài khoản để né quota. Phần mềm không biết số dư và không bảo đảm model bạn chọn miễn phí; chọn đúng model/quota free trong console.

Nguồn endpoint: https://ai.google.dev/gemini-api/docs/openai · https://console.groq.com/docs/openai · https://openrouter.ai/docs/api/reference/overview · https://docs.api.nvidia.com/nim/reference/llm-apis

## Ollama và RAG

Cài Ollama từ https://ollama.com/download. Có thể bắt đầu bằng `ollama pull qwen3:4b`, đặt `LLM_PROVIDERS=ollama`. Chưa benchmark trên GTX 1650 của bạn; ứng dụng giới hạn context 4096 token, vẫn cần thêm bộ nhớ ngoài weights.

Corpus nằm trong `docs/knowledge/`, do dự án biên soạn; không phải tài liệu nội bộ Olist. Có truy xuất **hybrid TF-IDF + SQLite vector** với embedding Ollama local, kiểm tra index cũ và trả lời bằng trích đoạn có nguồn. Chạy `ollama pull embeddinggemma:300m`, đặt `EMBED_MODEL=embeddinggemma:300m`, chạy `python manage.py embed`, đặt `RAG_MODE=hybrid`. Xem [cách chạy và giới hạn RAG local](docs/RAG_LOCAL.md).

## Đội agent

Trong **Trợ lý dữ liệu**, chọn **Đội agent**. Groq điều phối, phân tích BI và đọc Odoo; Gemini tra tài liệu, kiểm tra và tổng hợp. Mở các mục bằng chứng để xem số liệu gốc và nguồn.

Cài phần phụ thuộc một lần:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-agent.txt
.\.venv\Scripts\python.exe manage.py agent-team
```

CLI nhận thêm `--thread ID` để tiếp tục hội thoại, `--local-summary` để bật Qwen, `--allow-proposals` để cho phép lưu đề xuất. Trên web có các ô chọn tương ứng. `OLLAMA_MODEL` phải khớp tên trong `ollama list`; máy hiện tại dùng `qwen3:4b-instruct-2507-q4_K_M`.

Qwen chỉ tóm tắt khi bật và lịch sử đủ dài. Groq/Gemini vẫn nhận ngữ cảnh cần dùng. Mỗi lượt tối đa 12 lần gọi model, 12 công cụ, 120 giây, hai agent cùng lúc và một vòng sửa. Phạm vi BI theo bộ lọc; chưa hỗ trợ so sánh nhiều kỳ trong một câu hỏi.

Muốn tạo đề xuất, bật quyền rồi ghi rõ: `Tạo đề xuất báo giá partner_id=1 product_id=2 quantity=3 unit_price=10`. Thay ID bằng bản ghi DEMO thật, giá theo BRL. Đề xuất chỉ ở trạng thái pending; xem và duyệt riêng trong ERP. Chat không xác nhận đơn hoặc lập hóa đơn.

Nếu mất kết nối, bấm **Lấy lại lượt vừa gửi** để lấy kết quả cùng mã, tránh tạo lại đề xuất. Hội thoại mới tạo thread riêng; lịch sử lưu local trong SQLite và không đưa lên Git. Bộ kiểm tra nguồn/số không bảo đảm mọi diễn giải của model đều đúng; cần đối chiếu bằng chứng.

Kịch bản kiểm tra BI, Gemini, Qwen và cách xử lý lỗi: [docs/DEMO_AGENT_VI.md](docs/DEMO_AGENT_VI.md).

## Báo cáo PDF / Excel

Mở **Báo cáo → Tạo báo cáo**, chọn phạm vi, sửa nhận xét và chọn biểu đồ đường/cột. Có thể thêm, bỏ, đổi thứ tự tối đa sáu biểu đồ, kèm bảng chi tiết. Kết quả BI của Đội agent có nút **Đưa vào báo cáo** để lấy đúng bộ lọc, nhận xét và tài liệu nguồn.

Bấm **Lưu bản nháp** để mở lại sau; **PDF / Excel** tự lưu thay đổi trước khi tải. PDF có font tiếng Việt, biểu đồ và nguồn; Excel có số liệu và biểu đồ gốc để chỉnh tiếp. Font PDF dùng Arial trên Windows hoặc DejaVu Sans/Liberation Sans trên Linux. Cập nhật thư viện bằng `python -m pip install -r requirements.txt`.

Số liệu được chụp từ công cụ BI và lưu local trong `data/processed/operations.db`, không đưa lên Git. Sửa nhận xét không tự đổi số liệu; đổi bộ lọc hoặc thêm nguồn biểu đồ mới sẽ truy vấn lại khi lưu. Nhận xét là nội dung có thể sửa, cần rà soát khi đổi phạm vi hoặc chat nguồn chưa hoàn tất. Bản đầu hỗ trợ một kỳ mỗi báo cáo, chưa so sánh hai kỳ; lịch sử hiển thị 100 bản nháp gần nhất.

## Odoo Community local

Module chạy trong Odoo: **[AI hỗ trợ bán hàng](docs/ODOO_AI_FOLLOWUP.md)** — xem khách cần chăm sóc, Groq/Gemini đề xuất việc và người dùng duyệt trước khi tạo Activities. Có phân quyền nhân viên/quản lý nhóm; bản đầu chỉ dùng Olist DEMO.

**Gợi ý theo ngân sách:** nhập nhu cầu, số lượng và ngân sách gồm thuế; Odoo tính giá BRL rồi lọc phương án. Groq/Gemini xếp hạng qua dữ kiện tối thiểu. Chọn sản phẩm để lập đề xuất và duyệt riêng trước khi tạo báo giá nháp.

**Kiểm tra rủi ro báo giá:** xem cờ hiệu lực, dòng hàng, chiết khấu, thuế và điều khoản ngay trên báo giá DEMO. AI chỉ nhận mã cờ để gợi ý câu hỏi đối chiếu; dữ liệu nguồn đổi thì cần kiểm tra lại. Chức năng không sửa báo giá.

**Ghi nhận xử lý:** chọn cần sửa/đúng chủ đích/cần quản lý xem, lưu lý do và lịch sử tại Odoo; kiểm tra lại để xem bằng chứng trước/sau. Bản mới không tự kế thừa xác nhận cũ.

**Tải báo cáo rủi ro PDF/Excel:** lấy bằng chứng và lịch sử của hai bản đối chiếu từ Odoo, có cảnh báo nguồn cũ và các điểm cần xem tiếp. Xuất file không gọi thêm model.

Đánh giá và riêng tư: **[Baseline, benchmark và dữ liệu gửi model](docs/AI_EVALUATION.md)**. Luồng chăm sóc chỉ gửi mã tạm và dữ kiện tối thiểu; có chế độ quy tắc không gọi cloud. Kết quả tự động tách riêng phiếu chấm nội dung của người dùng.

Hướng dẫn kết nối từ đầu và Agent đa công cụ tùy chọn: **[docs/ODOO_AGENT_GUIDE_VI.md](docs/ODOO_AGENT_GUIDE_VI.md)**. Có thêm `python manage.py odoo-check` để kiểm tra kết nối chỉ đọc. Agent Lab chạy CLI riêng, không thay Assistant web; cần cài `requirements-agent.txt`.

Xem **docs/ODOO_WINDOWS.md**. Compose chạy Odoo Community 19 và PostgreSQL; BI mặc định dùng SQLite nên không cần Docker để mở dashboard.

Luồng: nhập demo bằng `manage.py odoo-seed --limit 10` → đọc catalog qua RPC → lưu đề xuất trong ứng dụng → người dùng xem payload và duyệt → tạo `sale.order` draft → audit. Không xác nhận đơn, xuất kho, lập hóa đơn hoặc thu tiền.

Trong **ERP & Phê duyệt**, bấm **Đọc lại Odoo**, tìm khách/sản phẩm theo tên hoặc mã DEMO và mở chi tiết bản ghi. Chọn khách, thêm tối đa 20 dòng hàng, nhập số lượng, đơn giá BRL, chiết khấu 0–100% và chọn thuế → **Đối soát đề xuất** → **Lưu đề xuất chờ duyệt**. Các số nhập tối đa hai chữ số thập phân. Giá trên thẻ sản phẩm giữ tiền tệ gốc và không tự dùng làm đơn giá BRL.

Danh mục thuế lấy từ thuế bán hàng đang hoạt động của công ty kết nối Odoo. Ứng dụng dùng Odoo tính thử trên bản ghi trong bộ nhớ, không lưu báo giá khi đối soát. Bảng hiển thị tiền hàng trước giảm, tiền giảm (đều chưa thuế), tiền sau giảm, thuế và tổng thanh toán. Thuế đã gồm trong đơn giá và cách làm tròn dùng đúng cấu hình Odoo; nếu làm tròn theo tổng chứng từ, tổng thanh toán có thể lệch vài xu so với cộng các dòng và được ghi rõ. Đây là cấu hình hiện có của công ty, không tự đặt thuế theo tiền tệ BRL.

Khi duyệt, ứng dụng kiểm tra lại cấu hình và nội dung đã lưu rồi mới tạo bản nháp, sau đó đọc lại từng dòng và tổng tiền để đối chiếu. Cấu hình thay đổi thì cần lập đề xuất mới. Đề xuất cũ không có thuế/chiết khấu vẫn dùng được.

Đề xuất đã lưu giữ nguyên khách, từng dòng hàng và tổng tiền để duyệt riêng. Sửa nội dung trên form sẽ yêu cầu đối soát lại. Nếu thông tin Odoo thay đổi trước lúc duyệt, lượt ghi bị chặn để kiểm tra lại. Mất kết nối sau khi tạo báo giá thì thử lại cùng mã để tìm theo origin và đối chiếu từng dòng trước khi nhận kết quả. Luồng một sản phẩm từ chat vẫn được giữ.

**Chi tiết & lịch sử** hiển thị các lần lưu, duyệt, lỗi và từ chối. **Xem báo giá Odoo** đọc lại trạng thái, từng dòng, thuế và tổng tiền từ Odoo. “Đã ghi bản nháp” là trạng thái xử lý đề xuất trong ứng dụng; trạng thái chứng từ hiển thị riêng theo Odoo.

**Nhờ agent kiểm tra:** nhập đủ khách và các dòng hàng trên ERP, ghi câu hỏi nếu cần rồi bấm nút này. Trợ lý nhận bản chụp form, dùng Odoo đối soát và giải thích chiết khấu/thuế/làm tròn. Model không được đổi giá, số lượng hay thuế trong bản chụp. Kết quả có bảng số tiền và nguồn, chưa lưu đề xuất; quay về form để sửa, đối soát và duyệt riêng. Lấy lại cùng lượt chạy sau mất kết nối giữ nguyên bản chụp, không gọi model lại nếu kết quả đã lưu.

**Tải báo giá PDF:** mở chi tiết báo giá Odoo nháp/đã gửi rồi bấm **Tải báo giá PDF**. File đọc số liệu trực tiếp từ Odoo lúc tải, có khách, dòng hàng, chiết khấu, thuế, tổng và tiền tệ. Đề xuất pending chưa có chứng từ thì chưa tải PDF được. Tải file không đánh dấu đã gửi, không xác nhận đơn và không gửi email. Trong chat có thể hỏi “Cho xem báo giá Odoo DEMO và cách tải PDF”; agent tra chứng từ và đưa nút tải.

Bộ skill của agent ERP nằm ở [.agents/skills](.agents/skills): `olist-sales-lookup`, `olist-quote-review`, `olist-quote-pdf`. Ứng dụng tự nạp hướng dẫn khi gọi agent ERP và hiển thị skill đã nạp trong kết quả. Quyền công cụ được giới hạn trong mã nguồn, file skill không cấp thêm quyền ghi. Cần Groq/Gemini và `requirements-agent.txt` cho trợ lý; tải PDF trực tiếp không cần gọi model.

Luồng tạo báo giá nháp đã được kiểm tra với Odoo local thật, có đối chiếu payload và chặn tạo trùng; xem `reports/web_browser_qa.json`. Phạm vi kiểm tra chỉ gồm dữ liệu DEMO và báo giá nháp. Bản local một operator, chưa có RBAC doanh nghiệp. Không mở port ứng dụng ra Internet.

## ML giao trễ thử nghiệm

Nếu chưa có artifact (ví dụ clone từ Git):

```powershell
.\.venv\Scripts\python.exe manage.py train
```

Dùng CPU. So Dummy prior, Logistic Regression, HistGradientBoosting với chia tập thời gian. Model/ngưỡng chọn trên validation, không đổi theo kết quả test. Báo cáo tại `reports/ml_evaluation.json`.

**Kết quả hiện còn yếu.** Boosting được chọn trên validation có AP test khoảng 0,050; ROC-AUC khoảng 0,602; precision khoảng 4,6% và recall khoảng 45,1% ở ngưỡng 0,13. Brier kém baseline. Chưa dùng để tự động ra quyết định; điểm chưa hiệu chỉnh xác suất. Snapshot không chứng minh mọi thuộc tính chưa bị sửa sau thời điểm dự đoán; chỉ đánh giá trên đơn delivered đủ nhãn.

## Kiểm thử

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/verify_release.py
```

API docs: http://127.0.0.1:8000/docs. HTTP clients có thể dùng `X-App-Token`; frontend dùng cookie HttpOnly. Request ghi qua cookie cần kiểm tra same-origin và header riêng. Không có endpoint chạy SQL/shell tùy ý. SQL BI cố định và parameter binding; ghi ERP phải qua bước duyệt.

Node chỉ cần cho kiểm tra cú pháp JavaScript (`node --check frontend/assets/app.js`) hoặc preview trong môi trường phát triển; người dùng Windows không cần cài Node để chạy ứng dụng.

## Quản lý commit

Mã nguồn có lịch sử Git theo từng phần việc. Mỗi đợt sửa: xem diff → chạy kiểm tra phù hợp → commit thông điệp mô tả hành vi → push lên repo đã kết nối. Không tự động commit `.env`, data hoặc model. CI GitHub chỉ được ghi nhận thành công khi workflow thực sự chạy xong trên repo.

Việc commit tiếp theo được thực hiện trong các phiên làm việc được yêu cầu; không có tiến trình tự sửa mã hay push khi cuộc trò chuyện không hoạt động.
