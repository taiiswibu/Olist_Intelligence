"""Repeatable real-data/API/HTML checks. No cloud credentials or ERP writes."""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import platform
import re
import socket
import subprocess
import time
from datetime import datetime, timezone
import httpx
import numpy as np
import pandas as pd
import yaml
from olist.config import ROOT, init_env, settings
from olist import analytics, agent, rag
from olist.database import ready, rows

GOLD = [
    ("GMV hàng hóa gồm phí vận chuyển không?", "GMV hàng hóa"),
    ("AOV hàng hóa tính như thế nào?", "AOV hàng hóa"),
    ("Giao trong ngày hẹn có bị tính giao trễ?", "Tỷ lệ giao trễ"),
    ("Tỷ lệ hủy có gộp unavailable không?", "Tỷ lệ hủy"),
    ("Join item với payment có nhân đôi tiền?", "Grain"),
    ("Dữ liệu nguồn có timezone UTC không?", "Nguồn dữ liệu"),
    ("Olist có tồn kho và giá vốn không?", "Giá trị thiếu"),
    ("Chín CSV gồm bảng nào?", "Các bảng CSV"),
    ("Duyệt tạo báo giá Odoo ra sao?", "Duyệt tạo báo giá"),
    ("Import dữ liệu Olist vào ERP tạo trạng thái gì?", "Import dữ liệu"),
    ("Odoo Community miễn phí khác Odoo Online?", "Odoo Community"),
    ("Bản local có phân quyền RBAC không?", "Giới hạn bản local"),
    ("Không có API thì Agent dùng gì?", "Agent và nguồn"),
    ("RAG mặc định có semantic embedding không?", "RAG và nguồn"),
    ("Dự báo giao trễ tránh leakage thế nào?", "Dự báo giao trễ"),
    ("Chia tập ML theo thời gian và chọn ngưỡng ra sao?", "Chia tập"),
    ("API free có được bảo đảm không?", "Nguồn API"),
]
ROUTES = [
    ("Tổng quan KPI", "kpis"), ("GMV theo tháng năm 2018", "monthly"),
    ("Doanh số theo ngành hàng", "category"), ("Hiệu suất seller", "seller"),
    ("Bang nào giao trễ nhiều", "state"), ("Định nghĩa AOV", "docs"),
    ("Công thức tỷ lệ hủy", "docs"), ("Tồn kho còn bao nhiêu", "unsupported"),
    ("Lợi nhuận Olist", "unsupported"), ("Tạo báo giá Odoo", "erp"),
    ("Tỷ lệ giao trễ", "kpis"), ("Xu hướng GMV", "monthly"),
]


def main():
    os.chdir(ROOT)
    init_env()
    os.environ["LLM_PROVIDERS"] = ""
    os.environ["RAG_MODE"] = "lexical"
    os.environ['RAG_ANSWER_MODEL'] = ''
    os.environ['OLLAMA_MODEL'] = ''
    os.environ["ODOO_PASSWORD"] = ""
    if not ready():
        raise SystemExit("Run python manage.py setup first")
    run = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True)
    print(run.stdout)
    if run.returncode:
        raise SystemExit("Unit tests failed: " + run.stderr[-1000:])
    tests = int(re.search(r"(\d+) passed", run.stdout).group(1))
    recalls1, recalls3, reciprocal = [], [], []
    retrieval_cases = []
    for question, label in GOLD:
        found = rag.retrieve(question, 5)["sources"]
        rank = next((n+1 for n,x in enumerate(found) if label in x["section"]), None)
        recalls1.append(rank == 1)
        recalls3.append(rank is not None and rank <= 3)
        reciprocal.append(1/rank if rank else 0)
        retrieval_cases.append({"question":question,"relevant_section_contains":label,"rank":rank})
    tools = [{"question":q,"expected":t,"actual":agent.local_plan(q).tool} for q,t in ROUTES]
    latency = []
    for q,_ in ROUTES:
        start = time.monotonic()
        agent.ask(q, analytics.Filters())
        latency.append(1000*(time.monotonic()-start))
    # Independent calculation from raw CSV, without using build_facts.
    raw = ROOT / "data/raw"
    orders = pd.read_csv(raw / "olist_orders_dataset.csv")
    items = pd.read_csv(raw / "olist_order_items_dataset.csv")
    customers = pd.read_csv(raw / "olist_customers_dataset.csv")
    o = orders.merge(customers[["customer_id","customer_state"]], on="customer_id")
    mask = o.order_purchase_timestamp.between("2018-01-01", "2018-12-31 23:59:59") & (o.customer_state=="SP")
    scope = o[mask]
    delivered = scope[scope.order_status=="delivered"]
    expected_gmv = float(items[items.order_id.isin(delivered.order_id)].price.sum())
    actual = analytics.kpis(analytics.Filters(start="2018-01-01",end="2018-12-31",state="SP"))["values"]
    assert actual["orders"] == len(scope)
    assert abs(expected_gmv - actual["product_gmv"]) < .001
    known = delivered.dropna(subset=["order_delivered_customer_date","order_estimated_delivery_date"])
    expected_late = int((pd.to_datetime(known.order_delivered_customer_date).dt.date > pd.to_datetime(known.order_estimated_delivery_date).dt.date).sum())
    assert actual["late_orders"] == expected_late and actual["late_eligible"] == len(known)
    with socket.socket() as s:
        s.bind(("127.0.0.1",0))
        port = s.getsockname()[1]
    os.environ["API_URL"] = f"http://127.0.0.1:{port}"
    cfg = settings()
    # Windows drops empty environment values when creating a process. Set the
    # offline overrides inside the child, before dotenv can load local secrets.
    child = ("import os,uvicorn; os.environ.update(LLM_PROVIDERS='',ODOO_PASSWORD='',"
             "RAG_MODE='lexical',RAG_ANSWER_MODEL='',OLLAMA_MODEL=''); "
             f"uvicorn.run('olist.api:app',host='127.0.0.1',port={port},log_level='warning')")
    p = subprocess.Popen([sys.executable,'-c',child], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    checks = []
    ui = {}
    try:
        for _ in range(100):
            try:
                if httpx.get(cfg.api_url+"/health",trust_env=False,timeout=.5).status_code==200:
                    break
            except httpx.HTTPError:
                time.sleep(.1)
        else:
            raise RuntimeError("API did not start")
        headers = {"X-App-Token":cfg.app_token}
        with httpx.Client(base_url=cfg.api_url,headers=headers,trust_env=False,timeout=30) as c:
            for path in ["/status","/analytics/kpis","/analytics/monthly","/analytics/category","/analytics/seller","/analytics/state","/actions","/audit"]:
                r = c.get(path)
                assert r.status_code==200, (path,r.text)
                checks.append({"path":path,"status":r.status_code})
            r=c.post("/agent/chat",json={"question":"GMV năm 2018"})
            assert r.status_code==200 and r.json()["routing"]["mode"]=="local_rules", (r.status_code,r.json().get('routing',{}).get('mode'))
            r=c.post("/rag/search",json={"question":"Tỷ lệ giao trễ tính như thế nào?"})
            assert r.status_code==200 and r.json()["sources"]
            assert httpx.get(cfg.api_url+"/status",trust_env=False).status_code==401
            assert c.get("/erp/catalog").status_code==422 # no credentials: clear failure, no fake ERP
        with httpx.Client(base_url=cfg.api_url,trust_env=False,timeout=30) as web:
            html=web.get('/')
            assert html.status_code==200 and 'text/html' in html.headers['content-type']
            assert cfg.app_token not in html.text
            assert web.get('/assets/app.js').status_code==200
            assert web.get('/assets/styles.css').status_code==200
            assert web.get('/status').status_code==401
            session=web.post('/session',json={'key':cfg.app_token})
            assert session.status_code==200 and 'httponly' in session.headers['set-cookie'].lower()
            assert web.get('/status').status_code==200
            assert web.post('/agent/chat',json={'question':'Tổng quan KPI năm 2018'},headers={'X-Olist-Request':'1'}).status_code==200
            ui={"html":"passed","javascript_asset":"passed","stylesheet_asset":"passed","http_only_session":"passed","cookie_authenticated_chat":"passed"}
    finally:
        p.terminate()
        p.wait(timeout=10)
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    assert compose["services"]["odoo"]["ports"]==["127.0.0.1:8069:8069"]
    report = {"verified_at_utc":datetime.now(timezone.utc).isoformat(),"platform":platform.platform(),"python":platform.python_version(),
        "unit_tests_passed":tests,"cloud_llm_tested":False,"odoo_server_tested":False,"postgres_server_tested":False,
        "windows_executed":platform.system()=='Windows',"hybrid_embedding_model_tested":False,"browser_visual_tested":False,
        "api_http_checks":checks,"html_web_checks":ui,"compose_structure":"passed; daemon not checked by this script",
        "raw_csv_reconciliation_2018_SP":{"orders":len(scope),"gmv":expected_gmv,"late_eligible":len(known),"late_orders":expected_late,"passed":True},
        "lexical_retrieval":{"cases":len(GOLD),"recall_at_1":float(np.mean(recalls1)),"recall_at_3":float(np.mean(recalls3)),"mrr_at_5":float(np.mean(reciprocal)),"details":retrieval_cases},
        "local_rule_router":{"cases":len(tools),"accuracy":sum(x["actual"]==x["expected"] for x in tools)/len(tools),"details":tools},
        "offline_agent_latency_ms":{"p50":float(np.percentile(latency,50)),"p95":float(np.percentile(latency,95)),"note":"host CPU, no LLM requests; not a load test"}}
    (ROOT / "reports/verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"unit_tests_passed":tests,"ui":ui,"retrieval":{k:v for k,v in report["lexical_retrieval"].items() if k!="details"},"router_accuracy":report["local_rule_router"]["accuracy"]},ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
