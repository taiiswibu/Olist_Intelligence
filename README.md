# Olist Intelligence

Ứng dụng chạy trên máy cá nhân để xem BI từ dữ liệu Olist, hỏi bằng tiếng Việt, tra tài liệu có nguồn và tích hợp Odoo Community local.

**Bản 0.1:** dashboard + FastAPI + công cụ BI + truy xuất tài liệu + cấu hình nhiều nguồn LLM + quy trình duyệt báo giá Odoo + model giao trễ thử nghiệm. Không cần thuê VPS. Chế độ mặc định không gọi API cloud, không cần Docker để mở BI.

## Chạy trên Windows

1. Cài **Python 3.12 64-bit**. Bản này đã kiểm thử bằng Python 3.12 trên Linux; script Windows được cung cấp nhưng chưa chạy trên Windows thật. Nếu được hỏi, chọn thêm Python vào PATH.
2. Giải nén dự án vào một thư mục, ví dụ `D:\Code\Olist_Intelligence`.
3. Chạy **SETUP_WINDOWS.bat**. Lần đầu cài thư viện, tạo `.env` với token ngẫu nhiên, tải khoảng 45 MB CSV Olist chính thức và tạo database SQLite. Cần Internet ở bước này.
4. Chạy **START_WINDOWS.bat**, mở **http://127.0.0.1:8501**. Nếu trình duyệt không tự mở, dán địa chỉ vào Chrome.

Giữ cửa sổ chạy ứng dụng mở. Nhấn Ctrl+C để dừng. Không cần mở VSCode hay bật Docker để xem dashboard.

Nếu tải Kaggle lỗi: tải ZIP tại https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce, giải nén chín CSV trực tiếp vào `data/raw/`, chạy lại SETUP_WINDOWS.bat. Nếu chỉ cần tạo lại dữ liệu:

```powershell
.\.venv\Scripts\python.exe manage.py setup
```

## Cài bằng terminal / Linux

```bash
python3 -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell thay dòng trên bằng: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py setup
python run.py
```

Luôn chạy lệnh từ thư mục có README này. Nếu PowerShell chặn activate, dùng thẳng `.\.venv\Scripts\python.exe`, không cần thay policy toàn máy. Nếu port 8000/8501 bị chiếm, dừng bản ứng dụng cũ trước khi chạy lại.

## Dữ liệu nào đang dùng?

- Nguồn: **Brazilian E-Commerce Public Dataset by Olist**, chín CSV chính thức trên Kaggle, dữ liệu lịch sử đã ẩn danh.
- Snapshot đã chạy: **99.441 đơn, 112.650 item**. `reports/data_quality.json` ghi số dòng, hash và đối soát CSV; setup trên máy bạn tạo lại báo cáo theo file thực tế đã tải.
- Mặc định dashboard lọc **01/01/2017–31/08/2018**, không phải toàn bộ snapshot. Đổi bộ lọc ở sidebar nếu muốn xem toàn bộ.
- Tiền tệ **BRL (R$)**. GMV hàng hóa dùng đơn delivered, không gồm cước; không gọi là doanh thu ròng hay lợi nhuận.
- Giao trễ so sánh **ngày lịch**: giao trong ngày hẹn vẫn đúng hạn. Chỉ đơn delivered có đủ actual/estimated date mới nằm trong mẫu số.
- Không có tồn kho, giá vốn, BOM hoặc dữ liệu sản xuất. Các đối tượng trong Odoo là demo chuyển đổi từ lịch sử, không phải ERP gốc của Olist.

CSV và database không đưa vào gói mã nguồn/Git. Setup tải từ nguồn chính thức. Giấy phép dữ liệu **CC BY-NC-SA 4.0**, xem `DATA_LICENSE.md`; giấy phép mã dự án tách riêng.

## Gemini, Groq, OpenRouter, NVIDIA, AMD

Mở `.env` bằng VSCode/Notepad. Chỉ điền key trên máy của bạn, không đưa `.env` lên GitHub.

```dotenv
LLM_PROVIDERS=groq,gemini,openrouter,nvidia,amd,ollama
GROQ_API_KEY=your_key
GROQ_MODEL=exact_model_id_available_to_your_account
GEMINI_API_KEY=your_key
GEMINI_MODEL=exact_model_id_available_to_your_account
```

Tương tự cho `OPENROUTER_*`, `NVIDIA_*`. Với AMD, thêm `AMD_BASE_URL` từ đúng dịch vụ bạn đang dùng; không có một endpoint AMD được giả định sẵn. Model ID để trống có chủ đích vì chưa biết model/quota của tài khoản bạn. Có thể liệt kê model:

```powershell
.\.venv\Scripts\python.exe manage.py models --provider groq
.\.venv\Scripts\python.exe manage.py models --provider gemini
.\.venv\Scripts\python.exe manage.py models --provider openrouter
.\.venv\Scripts\python.exe manage.py models --provider nvidia
```

Sau khi sửa `.env`, dừng và chạy lại ứng dụng. Chỉ provider có đủ model/key mới được gọi. Chuyển nguồn theo thứ tự trên khi lỗi; một lần thử mỗi nguồn, không xoay key/tài khoản để né quota. Ứng dụng **không biết số dư hoặc bảo đảm model bạn chọn miễn phí**. Chọn model/quota free trong console; không thêm nguồn trả phí nếu không muốn phát sinh phí. Mặc định `LLM_PROVIDERS=` rỗng.

Không có key: dashboard vẫn đầy đủ, hội thoại dùng quy tắc, tài liệu trả trích đoạn. Giao diện ghi rõ chế độ, không giả làm kết quả LLM.

Nguồn tài liệu endpoint:

- Gemini: https://ai.google.dev/gemini-api/docs/openai
- Groq: https://console.groq.com/docs/openai
- OpenRouter: https://openrouter.ai/docs/api/reference/overview
- NVIDIA: https://docs.api.nvidia.com/nim/reference/llm-apis

## Chạy LLM local bằng Ollama

Cài Ollama từ https://ollama.com/download, sau đó:

```bash
ollama pull qwen3:4b
```

Sửa `.env`: `LLM_PROVIDERS=ollama`, `OLLAMA_MODEL=qwen3:4b`. Bản quantized khoảng 2,5 GB; RAM/VRAM chạy còn có runtime và context. Chưa benchmark trên GTX 1650 của bạn. Nếu chậm hoặc thiếu bộ nhớ có thể chọn model nhỏ hơn và đổi tên trong `.env`. Giới hạn context của ứng dụng là 4096 token; không cần fine-tune.

## RAG

Corpus `docs/knowledge/` do dự án viết từ schema công khai và các định nghĩa/quy trình demo. Mỗi kết quả có tên file, section và chunk ID. Mặc định **TF-IDF lexical**, không được gọi là semantic embedding.

Tùy chọn hybrid dùng embedding Ollama local:

```bash
ollama pull qwen3-embedding:0.6b
```

Đặt `EMBED_MODEL=qwen3-embedding:0.6b`, chạy `python manage.py embed`, đặt `RAG_MODE=hybrid`, khởi động lại. Nếu model/tag không có trong Ollama của bạn, chọn embedding model đang hỗ trợ `/api/embed`. Chế độ này chưa kiểm thử với model thật trong môi trường đóng gói. Corpus nhỏ nên chưa cần dịch vụ vector database riêng.

## Tích hợp ERP Odoo miễn phí

Làm theo **[docs/ODOO_WINDOWS.md](docs/ODOO_WINDOWS.md)**. Dùng Odoo Community 19 local, không đăng ký Odoo Online. Bước nhập demo là lệnh riêng, không tự ghi ERP khi mở dashboard. Chưa kiểm thử server Odoo/Docker thật trong môi trường xây dựng vì không có Docker.

Luồng: nhập demo → đọc khách/sản phẩm qua RPC → lưu đề xuất → người dùng xem và duyệt → tạo `sale.order` nháp → lưu audit. Không xác nhận đơn, giao hàng, xuất hóa đơn hoặc thu tiền.

## ML giao trễ — thử nghiệm

Gói phát hành kèm artifact đã train bằng dữ liệu thật và phiên bản thư viện trong requirements. Nếu không có artifact hoặc phiên bản khác, train lại:

```powershell
.\.venv\Scripts\python.exe manage.py train
```

So sánh Dummy prior, Logistic Regression và HistGradientBoosting. Model/ngưỡng chọn trên validation; holdout tháng 07/2018 không dùng để chỉnh lại. `reports/ml_evaluation.json` ghi đầy đủ cấu hình, features, split và kết quả.

**Kết quả hiện còn yếu.** Boosting được chọn trên validation, holdout AP khoảng 0,050 và ROC-AUC khoảng 0,602. Ở ngưỡng 0,13, precision khoảng 4,6%, recall khoảng 45,1%; Brier kém baseline. Giữ model để minh họa pipeline và giới hạn, **chưa dùng để tự động ra quyết định**. Không chọn lại Logistic chỉ vì đã nhìn kết quả test.

Không dùng ngày giao thực tế hay review làm feature. Snapshot không chứng minh ngày hẹn/product attributes chưa bị cập nhật sau lúc duyệt đơn. Chỉ đánh giá trên đơn delivered đủ nhãn; không đại diện đơn chưa hoàn tất/hủy, không chứng minh hiệu quả với dữ liệu hiện tại. Điểm rủi ro chưa hiệu chỉnh xác suất.

## Kiểm thử và API

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python scripts/verify_release.py
```

API docs: http://127.0.0.1:8000/docs. Trừ `/health`, các endpoint yêu cầu header `X-App-Token` lấy từ `.env`. Swagger chưa có ô Authorize riêng; có thể dùng trường header của từng request.

`/analytics/kpis`, `/analytics/monthly`, `/analytics/category`, `/analytics/seller`, `/analytics/state`, `/agent/chat`, `/rag/search`, `/ml/order/{id}`, `/erp/catalog`, `/erp/quotations`, `/actions`, `/audit`.

Không có API thực thi SQL tùy ý. Truy vấn BI dùng SQL cố định và parameter binding. Bản local dùng một operator/token, **chưa có RBAC nhiều người**, không công bố port ra Internet. Trong hội thoại, khoảng ngày có thể ghi `năm 2018`, `tháng 2/2018`, `tháng 2 năm 2018`, hoặc hai ngày ISO; bộ lọc thực tế luôn hiển thị. Các ngưỡng/top tùy ý chưa hỗ trợ sẽ yêu cầu làm rõ.

Xem `reports/verification.json` và `docs/VERIFICATION.md` để biết chính xác phần nào đã chạy, phần nào chỉ được kiểm tra qua mock. Workflow GitHub được cung cấp nhưng chưa có kết quả CI remote khi chưa tạo/push repo.

## Cấu trúc

```text
app.py                  Giao diện Streamlit
run.py                  Chạy API và UI local
manage.py               Setup, ingest, train, seed Odoo, embedding
olist/                  ETL, BI, Agent, RAG, ML, adapter ERP, API
scripts/                Setup Windows, seed ERP, xác minh phát hành
docs/knowledge/         Corpus tri thức do dự án biên soạn
tests/                  Kiểm thử grain, KPI, auth, routing, approvals
reports/                Kết quả đã chạy; không phải số liệu minh họa
models/                 Artifact ML thử nghiệm
docker-compose.yml      Odoo + PostgreSQL; analytical PostgreSQL tùy chọn
```

Lộ trình sau khi bản local chạy được: xác minh Odoo trên máy Windows → kiểm tra từng API/model bạn có → bổ sung bộ đánh giá hội thoại thật → cải thiện mô hình ở một vòng nghiên cứu mới, giữ riêng holdout mới → cân nhắc UI/auth nâng cao. Không cần thuê VPS ở bước này.
