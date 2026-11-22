# Odoo + AI Agent: hướng dẫn chạy và phát triển

Cập nhật 22/11/2026. Dành cho Windows, Docker Desktop đã cài, chưa có Odoo và chưa cấu hình LLM.

## 1. Bản này làm được gì?

Dashboard HTML/CSS vẫn chạy bằng FastAPI tại `http://127.0.0.1:8000`. Assistant trên web dùng bộ định tuyến một công cụ. **Agent Lab là CLI tùy chọn riêng**, dùng LangChain `create_agent` trên runtime LangGraph, có vòng lặp gọi nhiều công cụ và lưu hội thoại bằng SQLite. Chưa thay Assistant web bằng Agent Lab.

| Năng lực | Hiện trạng |
| --- | --- |
| BI Olist, công cụ truy vấn cố định | Có sẵn |
| Tra cứu tài liệu kèm nguồn | Có; mặc định TF-IDF, chưa phải semantic RAG |
| Kết nối Odoo và nhập báo giá DEMO | Có adapter; cần kiểm tra trên Odoo máy bạn |
| Kiểm tra kết nối theo từng bước | Mới: `manage.py odoo-check` |
| Agent đa công cụ, lịch sử qua lần mở lại | Mới: CLI `manage.py agent-lab` |
| Đề xuất báo giá chờ người duyệt | CLI tùy chọn; duyệt trên giao diện web |
| LLM đã fine-tune | Chưa có; không đổi tên prompt/RAG thành fine-tuning |
| Cloud API/Odoo thật được kiểm tra ở máy đóng gói | Chưa; kiểm thử công cụ dùng mock và dữ liệu fixture |

Đây là công cụ phần mềm có phạm vi và quyền cụ thể. Thêm nhiều framework không tự tạo ra trí thông minh tổng quát hay khả năng tự học an toàn.

## 2. Cài Odoo Community trên máy

Mở Docker Desktop, đợi engine sẵn sàng. Trong PowerShell:

```powershell
cd D:\Code\project_AI\Olist_Intelligence
docker compose up -d odoo-db odoo
docker compose ps
docker compose logs --tail 60 odoo
```

Compose có sẵn dùng `odoo:19.0` và `postgres:16`. Community tự host không cần mua giấy phép Odoo Enterprise. Chính sách gói Odoo Online không áp dụng như một giới hạn gói thuê bao cho bản Community local này. Docker Desktop có điều khoản sử dụng riêng; ở đây dùng bản Docker bạn đã cài.

Mở `http://127.0.0.1:8069`. Khi hiện Create Database:

1. Master Password: với cấu hình mặc định chưa sửa, Odoo dùng `admin`. Nếu máy bạn đã có cấu hình/volume khác, dùng giá trị `admin_passwd` của cấu hình đó. Khi trình cài đặt đề nghị đặt master password mới, lưu lại giá trị bạn chọn.
2. Database Name: `olist_demo`.
3. Email: email đăng nhập bạn tự đặt; ghi lại để cấu hình `ODOO_LOGIN`.
4. Password: mật khẩu tài khoản Odoo bạn tự đặt.
5. Country: Brazil nếu muốn demo theo dữ liệu Olist. Không bật dữ liệu mẫu mặc định.
6. Tạo database. Vào **Apps**, cài **Sales** (`sale_management`).

Ba loại mật khẩu khác nhau:

| Giá trị | Mục đích |
| --- | --- |
| Master password / `admin_passwd` | Quản lý tạo/xóa/sao lưu database; không dùng gọi công cụ nghiệp vụ |
| `ODOO_PG_PASSWORD` | Container Odoo đăng nhập PostgreSQL; không dùng đăng nhập giao diện |
| `ODOO_PASSWORD` | Mật khẩu hoặc API key của tài khoản Odoo để ứng dụng gọi RPC |

Ứng dụng chỉ bind Odoo ra localhost. Không đưa database manager hoặc ứng dụng demo ra Internet. Không chạy `docker compose down -v` nếu muốn giữ dữ liệu.

## 3. Kết nối ứng dụng Olist

Trong thư mục dự án, sửa `.env` bằng trình soạn thảo. Nếu chưa có file này, chạy `SETUP_WINDOWS.bat` trước.

```dotenv
ODOO_URL=http://127.0.0.1:8069
ODOO_DB=olist_demo
ODOO_LOGIN=email_ban_da_dung_khi_tao_database
ODOO_PASSWORD=mat_khau_hoac_api_key_cua_tai_khoan_odoo
```

Khuyến nghị tạo API key trong tài khoản Odoo: **My Profile/Preferences → Account Security → New API Key**; tên mục có thể thay đổi theo bản dịch. Dùng key thay password ở `ODOO_PASSWORD`, vẫn giữ login đúng. Nếu key có thời hạn, ghi lại hạn để chủ động đổi. Không gửi key vào chat hoặc commit `.env`.

Kiểm tra bằng Python của chính dự án:

```powershell
.\.venv\Scripts\python.exe manage.py odoo-check
```

Kết quả chỉ đọc, không tạo dữ liệu:

| `stage` | Ý nghĩa và cách xử lý |
| --- | --- |
| `http` | Chưa truy cập được Odoo; xem trạng thái container/log/cổng 8069 |
| `configuration` | Thiếu secret hoặc URL không phải localhost; sửa `.env` |
| `authentication` | Sai database/login/key hoặc tài khoản bị chặn |
| `sales` | Chưa cài Sales |
| `read_access` | Không đọc được nghiệp vụ/quyền chưa đủ; kiểm tra tài khoản |
| `ready` với `ok: true` | Đã xác thực và đọc được catalog/báo giá DEMO |

Số bản ghi trả về có giới hạn; không phải tổng toàn bộ Odoo. Tài khoản hạn chế quyền có thể không đọc được thông tin module; bản demo ban đầu dùng tài khoản bạn vừa tạo. Sau khi hoạt động mới tách tài khoản tích hợp và kiểm tra lại quyền theo từng tool.

Nhập dữ liệu mẫu từ CSV Olist thật đã ingest:

```powershell
.\.venv\Scripts\python.exe manage.py odoo-seed --limit 10
.\.venv\Scripts\python.exe manage.py odoo-check
```

Lệnh seed là thao tác ghi bạn chủ động chạy: tạo contact, sản phẩm DEMO dạng dịch vụ, pricelist BRL và báo giá nháp, tối đa 50 đơn/lần. Dòng sản phẩm/cước lấy theo đơn lịch sử; tên DEMO dùng category vì CSV không có tên hàng thật. Chạy tuần tự tránh nhập lại bằng origin; không giả lập tồn kho hoặc xác nhận đơn.

Mở lại `START_WINDOWS.bat` sau khi sửa `.env`. Trong **ERP & Phê duyệt**, kết nối và kiểm tra dữ liệu. Thử một đề xuất báo giá nhỏ: xem đúng khách, sản phẩm, số lượng, giá BRL rồi duyệt. Kiểm tra trong Odoo Sales: trạng thái **draft**, origin `OLIST-ACTION:<id>`, tổng tiền phù hợp. Chỉ container chạy chưa chứng minh import thành công.

Adapter hiện dùng XML-RPC. API này còn dùng được ở Odoo 19 nhưng đã deprecated; tài liệu hiện công bố loại bỏ ở Odoo 22 / Odoo Online 21.1. JSON-2 là hướng nâng cấp, **chưa được triển khai trong bản này**.

## 4. Cấu hình một nguồn LLM trước

Bắt đầu bằng Groq để giảm số biến cần xử lý. Model dưới đây được tài liệu Groq liệt kê hỗ trợ tool calling tại thời điểm viết. Model được phục vụ qua API, không tải 20B về GTX 1650.

```dotenv
LLM_PROVIDERS=groq
GROQ_API_KEY=key_cua_ban_dien_tren_may
GROQ_MODEL=openai/gpt-oss-20b
```

Kiểm tra danh sách model tài khoản truy cập được:

```powershell
.\.venv\Scripts\python.exe manage.py models --provider groq
.\.venv\Scripts\python.exe manage.py status
```

`status` chỉ xác nhận đủ cấu hình; `/models` cũng chưa chứng minh chat/tool calling hoạt động. Chạy câu hỏi trong bước 5 mới kiểm tra được luồng Agent. Quota miễn phí/quyền truy cập tùy tài khoản, không có cam kết miễn phí vô hạn. Xem quota trong console trước khi dùng.

Web cũ có fallback theo `LLM_PROVIDERS`. Agent Lab dùng **đúng một provider được chọn** để dễ đánh giá; chưa có fallback. Gemini/OpenRouter/NVIDIA có thể dùng endpoint OpenAI-compatible hiện có nhưng khả năng tool calling phụ thuộc model cụ thể. Với AMD cần endpoint/model chính xác của dịch vụ bạn có; không tự suy ra từ tên hãng.

API cloud nhận câu hỏi, lịch sử cùng dữ liệu các tool đưa vào ngữ cảnh. Demo dùng dữ liệu Olist; chỉ thêm tài liệu riêng khi bạn chấp nhận gửi nội dung đó tới nhà cung cấp. Nếu cần local hoàn toàn, dùng model Ollama có tool calling và kiểm tra tốc độ/bộ nhớ trước; chưa benchmark cấu hình GTX 1650 của bạn.

## 5. Chạy Agent Lab

Cài bổ sung một lần, sau khi bộ dependencies chính đã cài thành công:

```powershell
.\.venv\Scripts\python.exe -m pip install --timeout 180 --retries 10 -r requirements-agent.txt
.\.venv\Scripts\python.exe manage.py agent-lab --provider groq
```

Gõ:

> Phân tích KPI và ngành hàng theo GMV từ 2018-01-01 đến 2018-01-31. Nêu nguồn số liệu và định nghĩa GMV.

Chương trình in tên công cụ thực sự gọi trong lượt đó. Model có thể cần gọi `business_kpis`, `business_breakdown`; nếu trả lời số liệu mà không gọi tool thì chưa đạt yêu cầu đánh giá. Câu hỏi mơ hồ về thời gian phải được hỏi lại. Không coi câu trả lời trôi chảy là bằng chứng chính xác.

Kiểm tra một câu trực tiếp:

```powershell
.\.venv\Scripts\python.exe manage.py agent-lab --provider groq --question "Tra cứu tài liệu về định nghĩa giao trễ và trích ID nguồn"
```

CLI in `Thread: <id>`. Tiếp tục cùng hội thoại sau khi mở lại:

```powershell
.\.venv\Scripts\python.exe manage.py agent-lab --provider groq --thread ID_VUA_IN_RA
```

Checkpoint lưu tại `data/processed/agent_checkpoints.sqlite`, không commit Git. Đây là bộ nhớ hội thoại, không tự cập nhật trọng số model. Mỗi công việc nên dùng thread riêng; chưa có đăng nhập/phân quyền nhiều người. Hội thoại dài vẫn cần cơ chế tóm tắt/cắt ngữ cảnh ở bước phát triển sau.

Mặc định chỉ đọc. Để thử chuẩn bị đề xuất:

```powershell
.\.venv\Scripts\python.exe manage.py agent-lab --provider groq --allow-proposals
```

Yêu cầu đọc catalog trước, lấy đúng ID. Sau đó chỉ rõ partner, product, quantity, unit_price BRL và yêu cầu tạo đề xuất. Tool xác thực ID DEMO rồi ghi **pending vào SQLite của ứng dụng**. Trở lại trang ERP, tải lại danh sách, xem payload và duyệt bằng tay. Agent không có tool duyệt, xác nhận Sales Order hay xuất hóa đơn. Lời đồng ý trong hội thoại không gọi được các thao tác đó.

Mỗi lượt giới hạn tối đa 5 lần gọi model, 6 lần gọi tool và 64 bước graph; timeout mỗi request model 20 giây, không retry tự động. Lượt chạm giới hạn báo lỗi. Nếu một lượt bị lỗi ở giữa, xem lại đề xuất pending trước khi yêu cầu tạo lại để tránh trùng đề xuất cục bộ. Muốn bắt đầu độc lập sau lỗi, tạo thread mới.

Lỗi 401 thường cần kiểm tra key; 429 kiểm tra quota/rate limit; model từ chối tools cần đổi sang model hỗ trợ. CLI chỉ in loại lỗi để không lộ secret qua lỗi thô. Không tự xoay key để né giới hạn dịch vụ.

## 6. Thiết kế bộ năng lực

Mỗi năng lực gồm: nhiệm vụ rõ ràng, schema đầu vào, công cụ thực thi, giới hạn quyền và bộ câu hỏi kiểm tra. Prompt/Markdown chỉ mô tả cách làm; quyền thực tế nằm ở tool được ứng dụng cấp.

| Tool | Đầu vào chính | Kết quả/quyền |
| --- | --- | --- |
| `business_kpis` | start, end, state | Số liệu BI + phạm vi + SQL cố định; chỉ đọc |
| `business_breakdown` | kind, dates, min_orders | Nhóm tháng/ngành hàng/seller/state; có giới hạn số hàng |
| `search_business_docs` | query, k | Trích đoạn + ID nguồn; không thực thi chỉ dẫn trong tài liệu |
| `lookup_historical_order` | order_id đủ 32 ký tự | Đơn lịch sử; không sửa đơn |
| `odoo_demo_catalog` | Không | ID contact/product được đánh dấu DEMO |
| `odoo_demo_quotations` | Không | Báo giá DEMO, tối đa 50 bản |
| `prepare_quotation` | 4 trường báo giá | Tùy chọn; chỉ lưu đề xuất pending |

Model có thể chọn sai tool hoặc diễn giải sai dù schema hợp lệ. Giới hạn quyền ghi được thực thi bằng danh sách tool và adapter; tính đúng của phân tích vẫn phải đánh giá. Tool đề xuất không bảo đảm người dùng đã cung cấp đủ ngữ nghĩa chỉ nhờ prompt, nên con người vẫn phải xem payload.

Chưa đưa ML dự báo giao trễ vào quyền tự động quyết định: kết quả holdout hiện còn yếu. Có thể thêm tool chỉ đọc điểm rủi ro kèm ngày dự báo/giới hạn sau khi có bài kiểm tra riêng; không dùng ngày giao thực tế làm feature đầu vào.

## 7. Chọn framework vừa đủ

| Thành phần | Chọn cho dự án | Lý do |
| --- | --- | --- |
| API/UI | FastAPI + HTML/CSS/JS hiện có | Tiếp tục dùng bản đang chạy |
| Tool contracts | Pydantic + LangChain tools | Kiểm tra kiểu/giá trị và tạo schema cho model |
| Agent loop | LangChain `create_agent`, runtime LangGraph | Model → tools → model; giới hạn vòng lặp |
| Memory | LangGraph SQLite checkpointer | Khôi phục thread qua lần mở lại |
| ERP | Adapter Odoo hiện có + hàng đợi đề xuất | Người duyệt trước khi ghi Odoo |
| RAG | TF-IDF baseline hiện có; đo trước khi thêm embedding | Biết retrieval có cải thiện thật không |
| Evaluation | pytest + bộ câu hỏi có nhãn + tool trace | Đánh giá hành vi, không chỉ văn phong |
| Fine-tuning, khi đủ điều kiện | Transformers + TRL SFTTrainer + PEFT | Huấn luyện adapter trên môi trường riêng |

Chưa cần thêm CrewAI/AutoGen hoặc nhiều Agent cho cùng các tool này. MCP có ích khi cần chia sẻ tool giữa nhiều client; không phải điều kiện để một Agent hoạt động. Khi đưa graph lên web, cần phiên người dùng, hủy lượt, chống chạy trùng, hiển thị trace và khôi phục sau lỗi; chưa hoàn tất các phần đó trong patch này.

## 8. Fine-tuning: làm sau khi có baseline

Fine-tune giúp học cách chọn tool, tạo tham số và cách trả lời. Nó không thay database doanh thu đang đổi, không tạo quyền ERP và không thay RAG. Nếu chưa có nguồn LLM chạy được, chưa nên huấn luyện.

Quy trình đề xuất:

1. Chạy 50–100 tình huống được bạn kiểm tra để xác định lỗi: chọn tool, ngày, tham số, nguồn, xử lý lỗi, quyền ghi. Đây là mục tiêu thu thập mới, không phải benchmark đã hoàn tất.
2. Thu thập pilot khoảng 500–1.000 ví dụ có rà soát, tùy mức lặp nhiệm vụ. Không có số mẫu nào bảo đảm model tốt. Ghi `messages`, `tool_calls`, tool responses và `tools` JSON schema đúng format của base model/TRL; sửa mọi trace sai trước khi dùng.
3. Loại secret, dữ liệu riêng và câu trả lời tự bịa. Không cần lưu chuỗi suy nghĩ nội bộ; lưu yêu cầu, hành động tool và đáp án có thể kiểm chứng.
4. Chia theo nhóm mẫu nhiệm vụ/template trước khi tăng cường dữ liệu, ví dụ 80/10/10 train/validation/test. Các biến thể của cùng một tình huống không được rơi vào cả train và test. Giữ test kín khi chọn config.
5. Chạy SFT LoRA/QLoRA trên một model instruct nhỏ có template/tool calling phù hợp; so trực tiếp cùng base model trước và sau. Không mặc định fine-tune sẽ thắng model API lớn.
6. Chỉ đưa adapter vào dùng khi cải thiện bài kiểm tra và không tăng thao tác ngoài quyền.

Máy Ryzen 7 4800H, RAM 16 GB, GTX 1650 4 GB phù hợp làm app/ETL và thử model nhỏ. **Không cam kết train 4B/7B bằng QLoRA trên 4 GB.** Ngoài weights còn gradients, optimizer, activations và bộ nhớ context. Có thể làm pilot 0.6B–1.5B trên GPU Kaggle nếu tài khoản được cấp GPU; không bảo đảm quota miễn phí hay loại GPU.

Gợi ý thử nghiệm ban đầu, chưa benchmark: LoRA r=8 hoặc 16, alpha=16 hoặc 32, sequence 512–1024, batch 1, gradient accumulation 8, 1–2 epochs; learning rate phải chọn qua validation. Precision theo GPU được cấp, không mặc định mọi GPU hỗ trợ BF16. Dùng môi trường training riêng, không cài TRL/bitsandbytes chồng lên venv chạy app. Quantization khi inference không đồng nghĩa đã fine-tune.

| Chỉ số đánh giá | Cách kiểm tra |
| --- | --- |
| Tool/argument accuracy | Tool đúng, ngày/ID/đơn vị đúng so đáp án có nhãn |
| Execution success | Công cụ thực thi thành công, kết quả đúng kỳ |
| Grounding | Mọi số liệu/khẳng định có kết quả tool hoặc nguồn phù hợp |
| Retrieval | Recall@k và khả năng tìm đủ thông tin cần trả lời |
| Approval | Yêu cầu ghi không có tool ngoài quyền; đề xuất không tự được duyệt |
| Robustness | 401, 429, timeout, thiếu dữ liệu, prompt injection trong tài liệu |
| Hiệu năng | P50/P95 thời gian phản hồi, số request/token theo lượt |

Không có thao tác trái quyền trong bộ test chỉ chứng minh bộ test đó, không phải bảo đảm tuyệt đối. Lịch sử test router/RAG cũ không được gán thành kết quả Agent mới hay LLM đã fine-tune.

## 9. Thứ tự trong một tuần

| Ngày | Mốc cần hoàn tất |
| --- | --- |
| 1 | Odoo khởi động, `odoo-check` ready, import 10 báo giá; một LLM trả lời được |
| 2 | Chạy từng tool với dữ liệu thật; kiểm tra schema, ngày và ID |
| 3 | Agent đa công cụ + khôi phục thread; đối soát trace với kết quả BI |
| 4 | RAG có nguồn + đề xuất/duyệt Odoo từ đầu đến cuối |
| 5 | Bộ đánh giá có nhãn, kiểm thử lỗi và quyền; sửa lỗi quan trọng |
| 6 | Thu thập trace sạch; chỉ chạy fine-tune pilot nếu baseline/data đã sẵn sàng |
| 7 | Demo, ảnh minh chứng, tài liệu chạy và commit đã kiểm tra |

Nếu ngày 5 còn lỗi đúng/sai nghiệp vụ, dùng ngày 6 sửa lỗi. Một tuần ưu tiên chứng minh luồng hoạt động; không hứa có model fine-tune tốt khi chưa có dataset và đánh giá.

## 10. Kiểm thử và Git

```powershell
.\.venv\Scripts\python.exe -m pip install --timeout 180 --retries 10 -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Tests Agent Lab sẽ skip nếu chưa cài `requirements-agent.txt`. Model giả kiểm tra graph/tools/persistence không chứng minh API Groq đang chạy hoặc LLM trả lời chính xác. Odoo cần đối soát trên máy bạn theo các bước trên.

Lịch sử commit hiện lưu cục bộ. Chưa có remote GitHub được kết nối ở thời điểm viết; không có push/CI nào được xác nhận. Khi kết nối repo, chỉ push mã nguồn, không `.env`, checkpoint, data hay model. Chưa tạo tiến trình tự sửa/commit khi không có phiên làm việc.

## Nguồn chính thức

- [Odoo Community và Enterprise](https://www.odoo.com/documentation/19.0/administration.html)
- [Odoo Docker](https://github.com/odoo/docker)
- [Odoo system configuration](https://www.odoo.com/documentation/19.0/administration/on_premise/deploy.html)
- [Odoo external RPC và API key](https://www.odoo.com/documentation/19.0/developer/reference/external_rpc_api.html)
- [Odoo JSON-2 API](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html)
- [Groq GPT-OSS 20B](https://console.groq.com/docs/model/openai/gpt-oss-20b)
- [Groq tool use](https://console.groq.com/docs/tool-use/overview)
- [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents)
- [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [TRL SFTTrainer và tool calling](https://huggingface.co/docs/trl/sft_trainer)
- [PEFT quantization/QLoRA](https://huggingface.co/docs/peft/developer_guides/quantization)
