# Agent, truy xuất và mô hình
Tài liệu thiết kế của dự án, không phải kết quả được Olist chứng nhận.

## Agent và nguồn số liệu
Khi cấu hình provider, LLM chọn công cụ từ danh sách cố định: kpis, monthly, category, seller, state, docs. Backend kiểm tra JSON bằng Pydantic. Không có công cụ thực thi SQL tùy ý, shell hay ghi ERP từ hội thoại. Số liệu BI được dựng trực tiếp từ kết quả SQL, không qua bước LLM tự diễn giải số. Khi không có provider hoặc provider lỗi, dùng quy tắc local, giao diện ghi rõ không dùng LLM định tuyến. Chưa benchmark độ chính xác của LLM cloud nếu chưa có API key.

## RAG và nguồn trích dẫn
Corpus gồm glossary KPI, schema/giới hạn, quy trình ERP demo và thiết kế hệ thống. Mặc định là truy xuất lexical TF-IDF n-gram có bỏ dấu tiếng Việt; chưa phải semantic embedding. Có thể bật hybrid với Ollama embedding và index vector local, không cần Qdrant cho corpus nhỏ này. Nếu có LLM thì sinh câu trả lời dựa trên các chunk tìm được; nếu không có thì hiển thị trích đoạn. Tài liệu retrieve là dữ liệu, không có quyền thay đổi công cụ hoặc phê duyệt hành động.

## Dự báo giao trễ và leakage
Model dự đoán tại thời điểm duyệt đơn, giả định ngày hẹn và thông tin item/product đã có. Dùng giá, cước, số item/seller, khối lượng, category, bang, giờ/ngày mua, độ trễ duyệt và thời gian hẹn. Không dùng actual_delivery, thời gian giao thực tế, review_score, review_count hay is_late làm feature. CSV snapshot không chứng minh các thuộc tính hoặc ngày hẹn chưa từng bị sửa sau đó; vì vậy đây là đánh giá hồi cứu có giả định, không phải chứng minh online point-in-time tuyệt đối.

## Chia tập và đánh giá ML
Train: duyệt trước tháng 05/2018 và cả ngày giao lẫn ngày hẹn trước 01/05/2018, bảo đảm nhãn đã biết. Validation: đơn duyệt tháng 05/2018, kết quả biết trước 01/07/2018. Holdout: đơn duyệt tháng 07/2018. So Dummy prior, Logistic Regression và HistGradientBoosting; chọn model theo PR-AUC/AP, ngưỡng theo F1 validation. Không fit lại sau khi chọn trước khi đánh giá holdout. Chỉ có đơn delivered đủ nhãn, nên có selection bias và không đại diện đơn mở/hủy. Điểm model chưa hiệu chỉnh xác suất. Báo cáo AP/ROC-AUC/Brier/precision/recall/F1, không chỉ accuracy khi dữ liệu mất cân bằng.

## Nguồn API và chi phí
Có cấu hình Gemini, Groq, OpenRouter, NVIDIA, AMD tùy endpoint và Ollama. LLM_PROVIDERS quyết định thứ tự thử; chỉ thử provider có đủ model và key, tối đa một request mỗi provider. Không tự xoay tài khoản/key để né quota. Mức miễn phí phụ thuộc tài khoản/model/chính sách của nhà cung cấp; phần mềm không bảo đảm mọi model đã chọn đều miễn phí. Mặc định không gọi cloud. Với OpenRouter nên chọn model free từ danh mục hiện tại và giữ spending limit của tài khoản ở mức bạn chấp nhận.
