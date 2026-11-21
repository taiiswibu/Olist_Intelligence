from datetime import date
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import httpx
import pandas as pd
import plotly.express as px
import streamlit as st
from olist.config import settings

st.set_page_config(page_title="Olist Intelligence", page_icon="◈", layout="wide")
st.markdown("""<style>
.stApp {background:#f5f8f6; color:#172e26}
[data-testid="stSidebar"] {background:#103e32}
[data-testid="stSidebar"] * {color:#e4f0e9}
[data-testid="stMetric"] {background:white;border:1px solid #deebe3;border-radius:14px;padding:18px 20px}
[data-testid="stMetricLabel"] {color:#557365;font-size:13px}
[data-testid="stMetricValue"] {color:#124d39;font-size:28px}
.stTabs [data-baseweb="tab-list"] {gap:18px;border-bottom:1px solid #dbe8df}
.stTabs [aria-selected="true"] {color:#147153}
.block-container {padding-top:2rem;max-width:1500px}
div.stButton > button[kind="primary"] {background:#126849;border-color:#126849}
.eyebrow {font-size:12px;letter-spacing:2px;color:#5a7b69;font-weight:700}
.caption-bar {background:#e6f0e9;padding:12px 18px;border-radius:10px;color:#3b6050;font-size:13px}
</style>""", unsafe_allow_html=True)

cfg = settings()


def call(path, method="GET", body=None, params=None):
    try:
        r = httpx.request(method, cfg.api_url + path, json=body, params=params,
                          headers={"X-App-Token": cfg.app_token}, timeout=100, trust_env=False)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", "Yêu cầu thất bại")
            except ValueError:
                detail = "Máy chủ trả về lỗi"
            raise ValueError(str(detail))
        return r.json()
    except httpx.HTTPError as exc:
        raise ValueError("Chưa kết nối API local. Dừng ứng dụng và chạy python run.py") from exc


def show_answer(r):
    st.markdown(r["answer"])
    route = r.get("routing", {})
    label = f"{route.get('provider')}/{route.get('model')}" if route.get("provider") else "Quy tắc local · không dùng LLM định tuyến"
    st.caption(f"Công cụ: {r['tool']} · {label} · {r.get('elapsed_ms', 0)} ms")
    st.caption(f"Phạm vi: {r['filters']['start']} → {r['filters']['end']} · bang {r['filters'].get('state') or 'tất cả'}")
    if "data" in r:
        d = r["data"]
        st.dataframe(pd.DataFrame(d if isinstance(d, list) else [d]), width="stretch", hide_index=True)
    if r.get("sql"):
        with st.expander("Câu truy vấn đã chạy"):
            st.code(r["sql"], language="sql")
            st.json(r["filters"])
    if r.get("sources"):
        st.caption(f"Truy xuất: {r.get('retrieval')} · sinh câu trả lời: {r.get('generation_provider') or 'trích đoạn local'}")
        for source in r["sources"]:
            with st.expander(source["source"] + " · " + source["section"]):
                st.caption("Chunk " + source["id"] + " · score " + str(source["score"]))
                st.markdown(source["text"])
    if route.get("failures"):
        with st.expander("Trạng thái nguồn LLM"):
            st.json(route["failures"])


with st.sidebar:
    st.markdown("## ◈ Olist\nIntelligence workspace")
    st.caption("COMMERCE · KNOWLEDGE · ERP")
    st.divider()
    st.markdown("**Phạm vi dữ liệu**")
    start = st.date_input("Từ ngày", date(2017, 1, 1), min_value=date(2016, 1, 1), max_value=date(2018, 12, 31))
    end = st.date_input("Đến ngày", date(2018, 8, 31), min_value=date(2016, 1, 1), max_value=date(2018, 12, 31))
    state = st.selectbox("Bang khách hàng", ["Tất cả", "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"])
    st.divider()
    st.caption("Nguồn: Olist / Kaggle\n\nDữ liệu lịch sử 2016–2018\n\nCC BY-NC-SA 4.0 · BRL")
    if st.button("Làm mới kết nối", width="stretch"):
        st.cache_data.clear()
        st.rerun()

st.markdown('<div class="eyebrow">BUSINESS INTELLIGENCE / LOCAL WORKSPACE</div>', unsafe_allow_html=True)
st.title("Hiểu dữ liệu. Tra cứu. Hành động.")
st.markdown('<div class="caption-bar">Dữ liệu thương mại lịch sử Olist · Tài liệu quy trình demo · Thao tác ERP cần duyệt</div>', unsafe_allow_html=True)
st.write("")
if start > end:
    st.error("Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.")
    st.stop()
params = {"start": str(start), "end": str(end)}
if state != "Tất cả":
    params["state"] = state
try:
    status = call("/status")
except ValueError as exc:
    st.error(str(exc))
    st.code("python run.py")
    st.stop()
if not status["data_ready"]:
    st.info("Chưa có dữ liệu. Chạy bước setup trước khi mở ứng dụng.")
    st.code("python manage.py setup")
    st.stop()

tabs = st.tabs(["Tổng quan", "Hỏi dữ liệu", "Kho tri thức", "Rủi ro giao hàng", "ERP & Phê duyệt", "Kiểm chứng"])

with tabs[0]:
    data = call("/analytics/kpis", params=params)
    v = data["values"]
    fmt = lambda x: "—" if x is None else f"{x:,.2f}"
    pct = lambda x: "—" if x is None else f"{100*x:.2f}%"
    cols = st.columns(4)
    cols[0].metric("GMV hàng hóa · R$", fmt(v["product_gmv"]))
    cols[1].metric("Số đơn", f"{v['orders']:,}")
    cols[2].metric("AOV hàng hóa · R$", fmt(v["product_aov"]))
    cols[3].metric("Tỷ lệ giao trễ", pct(v["late_delivery_rate"]))
    st.caption(f"Đơn delivered: {v['delivered_orders']:,} · Mẫu tính giao trễ: {v['late_eligible']:,} · Tỷ lệ hủy: {pct(v['cancellation_rate'])}")
    monthly = pd.DataFrame(call("/analytics/monthly", params=params)["rows"])
    category = pd.DataFrame(call("/analytics/category", params=params)["rows"])
    c1, c2 = st.columns([1.4, 1])
    with c1:
        st.subheader("GMV theo tháng")
        if not monthly.empty:
            fig = px.area(monthly, x="month", y="product_gmv", color_discrete_sequence=["#217c58"], labels={"month": "Tháng mua", "product_gmv": "GMV (BRL)"})
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="white", margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("Không có đơn trong khoảng đã chọn.")
    with c2:
        st.subheader("Ngành hàng dẫn đầu")
        if not category.empty:
            fig = px.bar(category.head(8).iloc[::-1], x="product_gmv", y="category", orientation="h", color_discrete_sequence=["#67a481"], labels={"product_gmv": "GMV (BRL)", "category": ""})
            fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="white", margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch")
    st.caption(data["definition"])
    with st.expander("Bảng dữ liệu & xuất CSV"):
        kind = st.selectbox("Chọn bảng", ["monthly", "category", "seller", "state"])
        table = pd.DataFrame(call("/analytics/" + kind, params=params)["rows"])
        st.dataframe(table, width="stretch", hide_index=True)
        st.download_button("Tải CSV", table.to_csv(index=False).encode("utf-8-sig"), kind + ".csv", "text/csv")

with tabs[1]:
    st.subheader("Hỏi bằng tiếng Việt")
    st.caption("Hỗ trợ KPI, xu hướng tháng, ngành hàng, seller, bang và định nghĩa. Câu hỏi chưa hỗ trợ sẽ yêu cầu làm rõ.")
    configured = status["providers"]
    st.caption("Nguồn đã cấu hình: " + (", ".join(p["provider"] + "/" + p["model"] for p in configured) if configured else "chưa có · đang dùng quy tắc và trích đoạn local"))
    examples = ["Tổng quan KPI năm 2018", "GMV theo tháng năm 2017", "Tỷ lệ giao trễ được tính như thế nào?"]
    selected = None
    for col, example in zip(st.columns(3), examples):
        if col.button(example, width="stretch"):
            selected = example
    history = st.session_state.setdefault("chat_history", [])
    for msg in history:
        with st.chat_message("user"):
            st.write(msg["question"])
        with st.chat_message("assistant"):
            show_answer(msg["response"])
    prompt = st.chat_input("Ví dụ: GMV theo tháng năm 2018", max_chars=2000)
    question = selected or prompt
    if question:
        with st.chat_message("user"):
            st.write(question)
        with st.chat_message("assistant"):
            try:
                with st.spinner("Đang truy vấn dữ liệu và nguồn..."):
                    response = call("/agent/chat", "POST", {"question": question, "filters": params})
                show_answer(response)
                history.append({"question": question, "response": response})
                del history[:-12]
            except ValueError as exc:
                st.warning(str(exc))

with tabs[2]:
    st.subheader("Tài liệu có nguồn")
    st.caption("Corpus do dự án biên soạn; không phải tài liệu nội bộ của Olist. Mặc định tìm kiếm TF-IDF; có thể bật embedding Ollama.")
    with st.form("search"):
        query = st.text_input("Từ khóa hoặc câu hỏi", "GMV và AOV khác nhau thế nào?")
        submitted = st.form_submit_button("Tra cứu", type="primary")
    if submitted:
        try:
            result = call("/rag/search", "POST", {"question": query})
            st.caption("Phương pháp: " + result["method"])
            for source in result["sources"]:
                st.markdown(source["text"])
                st.caption(source["source"] + " · " + source["id"])
        except ValueError as exc:
            st.warning(str(exc))

with tabs[3]:
    st.subheader("Delivery Risk · mô hình thử nghiệm")
    st.info("Mô hình dùng đặc trưng tại thời điểm duyệt đơn. Điểm rủi ro chưa hiệu chỉnh xác suất; đơn lịch sử chỉ dùng minh họa.")
    if not status["model_ready"]:
        st.code("python manage.py train")
    with st.form("risk"):
        order_id = st.text_input("Mã order_id Olist (32 ký tự)", max_chars=32)
        predict = st.form_submit_button("Tính điểm rủi ro", disabled=not status["model_ready"])
    if predict:
        try:
            result = call("/ml/order/" + order_id, "POST")
            st.metric("Điểm rủi ro", f"{result['risk_score']:.3f}")
            st.write("Nguy cơ cao theo ngưỡng validation" if result["high_risk"] else "Dưới ngưỡng cảnh báo validation")
            st.caption(f"Model {result['model']} · ngưỡng {result['threshold']:.2f}")
        except ValueError as exc:
            st.warning(str(exc))
    if status["model_ready"]:
        try:
            report = call("/reports/ml_evaluation")
            winner = report["test"][report["winner"]]
            if winner["precision"] < .2 or winner["brier"] > report["test"]["prior"]["brier"]:
                st.warning("Kết quả holdout còn yếu: nhiều cảnh báo sai và Brier chưa tốt hơn baseline. Chưa phù hợp dùng tự động ra quyết định.")
            st.caption("Holdout tháng 07/2018 · model/ngưỡng chọn trên validation tháng 05/2018")
            st.dataframe(pd.DataFrame(report["test"]).T, width="stretch")
            with st.expander("Đặc trưng và giới hạn"):
                st.json({"features": report["features"], "split": report["split"], "limitations": report["limitations"]})
        except ValueError as exc:
            st.warning(str(exc))

with tabs[4]:
    st.subheader("Odoo Community · demo local")
    st.caption("Bản này chỉ thao tác trên khách và sản phẩm có mã OLIST-DEMO. Báo giá được tạo ở trạng thái nháp.")
    if not status["odoo_configured"]:
        st.info("Chưa cấu hình Odoo. Làm theo docs/ODOO_WINDOWS.md; BI và tra cứu tài liệu vẫn dùng được.")
    if st.button("Kết nối / tải dữ liệu Odoo"):
        try:
            st.session_state["erp_catalog"] = call("/erp/catalog")
            st.session_state["erp_quotes"] = call("/erp/quotations")
            st.success("Đã đọc dữ liệu Odoo.")
        except ValueError as exc:
            st.warning(str(exc))
    cat = st.session_state.get("erp_catalog", {})
    if cat.get("partners") and cat.get("products"):
        with st.form("quotation"):
            partner = st.selectbox("Khách hàng demo", cat["partners"], format_func=lambda x: x["name"])
            product = st.selectbox("Sản phẩm demo", cat["products"], format_func=lambda x: x["name"])
            qty = st.number_input("Số lượng", min_value=1., max_value=1000., value=1.)
            price = st.number_input("Đơn giá (BRL)", min_value=0., max_value=100000., value=100.)
            st.caption("Đơn giá nhập riêng cho demo; không tự lấy giá tồn kho hay tính thuế.")
            create = st.form_submit_button("Lưu đề xuất để xem và duyệt", type="primary")
        if create:
            try:
                proposal = call("/actions", "POST", {"partner_id": partner["id"], "product_id": product["id"], "quantity": qty, "unit_price": price})
                st.success("Đã lưu đề xuất " + proposal["id"] + ". Chưa ghi báo giá vào Odoo.")
            except ValueError as exc:
                st.warning(str(exc))
    elif cat:
        st.info("Chưa có dữ liệu demo. Chạy python manage.py odoo-seed --limit 10")
    if st.session_state.get("erp_quotes"):
        with st.expander("Báo giá đã đọc từ Odoo"):
            st.dataframe(pd.DataFrame(st.session_state["erp_quotes"]), width="stretch")
    for action in call("/actions"):
        with st.expander(action["id"][:10] + " · " + action["state"]):
            st.json(action["payload"])
            st.caption("Tổng trước thuế: R$ " + fmt(action["payload"]["quantity"] * action["payload"]["unit_price"]))
            if action["state"] in {"pending", "failed"}:
                confirm = st.checkbox("Tôi đã xem payload và đồng ý tạo báo giá nháp", key="confirm_" + action["id"])
                if st.button("Duyệt và tạo trong Odoo", key="approve_" + action["id"], disabled=not confirm):
                    try:
                        result = call("/actions/" + action["id"] + "/approve", "POST")
                        st.success("Đã tạo/khôi phục báo giá Odoo ID " + str(result["odoo_id"]))
                        st.rerun()
                    except ValueError as exc:
                        st.warning(str(exc))
                if action["state"] == "pending" and st.button("Từ chối", key="reject_" + action["id"]):
                    call("/actions/" + action["id"] + "/reject", "POST")
                    st.rerun()
            elif action["result"]:
                st.json(action["result"])

with tabs[5]:
    st.subheader("Kiểm chứng & trạng thái")
    st.json(status)
    try:
        quality = call("/reports/data_quality")
        st.dataframe(pd.DataFrame(quality["files"]).T, width="stretch")
        with st.expander("Đối soát dữ liệu"):
            st.json(quality["checks"])
    except ValueError as exc:
        st.warning(str(exc))
    with st.expander("Nhật ký thao tác"):
        st.dataframe(pd.DataFrame(call("/audit")), width="stretch")
    st.caption("Ghi nhận sự kiện, công cụ và thời gian. Không ghi API key hoặc mật khẩu vào audit log.")
