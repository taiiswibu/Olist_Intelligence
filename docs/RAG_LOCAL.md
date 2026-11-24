# Tra cứu tri thức bằng model local

Kho tri thức nằm trong `docs/knowledge/`, do dự án biên soạn. Đây là tài liệu thiết kế và nghiệp vụ DEMO, chưa phải dữ liệu nội bộ của một doanh nghiệp.

Tài liệu riêng của công ty có thể đặt dạng Markdown trong `data/knowledge/` rồi lập lại index. Thư mục này đã được loại khỏi Git. Kho tri thức và trợ lý tài liệu local đọc được các file đó; công cụ tra tài liệu của Đội agent/Agent Lab chỉ đọc `docs/knowledge/`, không nhận các file riêng này. Không đặt tài liệu mật vào thư mục tài liệu công khai của repository.

Chạy Ollama, tải model embedding rồi lập index:

```powershell
ollama pull embeddinggemma:300m
python manage.py embed
```

Đặt trong `.env`: `RAG_MODE=hybrid`, `EMBED_MODEL=embeddinggemma:300m` và `RAG_ANSWER_MODEL` là tên model hội thoại local đã có trong `ollama list`. Khởi động lại backend sau khi đổi cấu hình. Không tải model hay lập lại index tự động khi người dùng mở web.

SQLite với extension `sqlite-vec` lưu vector và các đoạn nguồn trong `data/processed/knowledge.sqlite`. Tài liệu dài được chia đoạn có phần chồng lấp. Index ghi SHA-256 nội dung corpus, model và digest model; thay tài liệu/model thì phải chạy lại `manage.py embed`. Quá trình lập index dùng file tạm rồi thay thế một lần, không xóa index cũ khi lỗi.

Mở **Kho tri thức**, nhập câu hỏi rồi bấm **Tra cứu**. Hệ thống kết hợp điểm TF-IDF và cosine từ tìm kiếm vector, loại các nguồn dưới ngưỡng. Model hội thoại local chọn các trích đoạn nguyên văn; backend kiểm tra từng đoạn và mã nguồn trước khi hiển thị. Không có nguồn đủ điểm hoặc model trả danh sách trống thì trả lời chưa đủ bằng chứng. Model lỗi hoặc trích dẫn không hợp lệ thì chỉ cho đối chiếu nguồn, không hiển thị nội dung model tự viết.

Embedding và câu trả lời ở `/rag/answer` chỉ gọi HTTP loopback, không theo redirect và không dùng proxy từ môi trường. Luồng hỏi tài liệu được nhận diện bằng quy tắc trong trợ lý cơ bản cũng đi qua đường này. Chế độ Đội agent/Agent Lab vẫn có ngữ cảnh cloud riêng; hướng dẫn này không khẳng định toàn bộ ứng dụng chạy offline.

`GET /rag/status` cho biết index có phù hợp tài liệu/model hiện tại không. `POST /rag/search` chỉ tra nguồn, `POST /rag/answer` thêm câu trả lời; cả ba yêu cầu xác thực của ứng dụng. Thiếu index, Ollama lỗi hoặc model đổi sẽ hiện `lexical_fallback` và lý do trên giao diện.

Đo truy xuất và câu trả lời local:

```powershell
python scripts/benchmark_rag.py --split dev --answers --out data/processed/rag-dev.json
python scripts/benchmark_rag.py --split test --answers --out data/processed/rag-test.json
```

Bộ câu hỏi có nguồn kỳ vọng và câu ngoài phạm vi, nằm trong tests. Nhãn do dự án biên soạn; hit@k, MRR, tỷ lệ từ chối và kiểm tra trích dẫn không thay cho đánh giá nghiệp vụ độc lập. Chỉ chỉnh trên dev, giữ kết quả test kể cả thất bại. Không đụng tập holdout của ML giao trễ.

Trích đoạn đúng nguyên văn chứng minh xuất xứ, chưa chứng minh đoạn đó trả lời đầy đủ câu hỏi. Corpus nhỏ và ngưỡng hiện tại không đủ để khẳng định vận hành ở quy mô doanh nghiệp.

Tham khảo triển khai: [sqlite-vec Python](https://alexgarcia.xyz/sqlite-vec/python.html), [KNN](https://alexgarcia.xyz/sqlite-vec/features/knn.html), [Ollama embed](https://docs.ollama.com/api/embed), [EmbeddingGemma](https://ollama.com/library/embeddinggemma).
