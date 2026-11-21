import hmac
import json
import hashlib
import os
import time
from pathlib import Path
from typing import Annotated, Literal
from fastapi import FastAPI, Depends, Header, HTTPException, Request, Cookie, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from . import __version__, analytics, agent, rag, ml, erp, llm
from .config import ROOT, settings
from .database import ready, operational
from .schemas import Quotation

app = FastAPI(title="Olist Intelligence", version=__version__)
app.mount("/assets", StaticFiles(directory=ROOT / "frontend/assets"), name="assets")


def same_origin(request):
    from urllib.parse import urlparse
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Yêu cầu khác nguồn bị từ chối")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Yêu cầu khác nguồn bị từ chối")


def session_signature(expiry):
    return hmac.new(settings().app_token.encode(), ("web-session:" + expiry).encode(), hashlib.sha256).hexdigest()


def valid_session(value):
    if not value or not settings().app_token:
        return False
    try:
        expiry, signature = value.split(".", 1)
        return int(expiry) > time.time() and hmac.compare_digest(signature, session_signature(expiry))
    except (ValueError, TypeError):
        return False


def auth(request: Request, x_app_token: Annotated[str | None, Header()] = None,
         olist_session: Annotated[str | None, Cookie()] = None):
    expected = settings().app_token
    if expected and x_app_token and hmac.compare_digest(expected.encode(), x_app_token.encode()):
        return
    if valid_session(olist_session):
        same_origin(request)
        if request.method not in {"GET", "HEAD"} and request.headers.get("x-olist-request") != "1":
            raise HTTPException(403, "Thiếu xác thực nguồn yêu cầu")
        return
    raise HTTPException(401, "Phiên làm việc hết hạn hoặc chưa kết nối")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "frontend/index.html", headers={"Cache-Control": "no-store"})


class SessionRequest(BaseModel):
    ticket: SecretStr | None = None
    key: SecretStr | None = None


@app.post("/session", include_in_schema=False)
def open_session(payload: SessionRequest, request: Request, response: Response):
    same_origin(request)
    cfg = settings()
    ticket = os.getenv("OLIST_BROWSER_TICKET", "")
    ticket_ok = bool(ticket and payload.ticket and not getattr(app.state, "ticket_used", False)
                     and hmac.compare_digest(ticket.encode(), payload.ticket.get_secret_value().encode()))
    key_ok = bool(cfg.app_token and payload.key and hmac.compare_digest(cfg.app_token.encode(), payload.key.get_secret_value().encode()))
    if not cfg.app_token or not (ticket_ok or key_ok):
        raise HTTPException(401, "Mã kết nối không hợp lệ. Chạy lại START_WINDOWS.bat hoặc dùng APP_TOKEN trong .env")
    if ticket_ok:
        app.state.ticket_used = True
    expiry = str(int(time.time()) + 14400)
    response.set_cookie("olist_session", expiry + "." + session_signature(expiry), httponly=True,
                        secure=request.url.scheme == "https", samesite="strict", max_age=14400)
    return {"authenticated": True}


@app.delete("/session", include_in_schema=False)
def close_session(request: Request, response: Response):
    same_origin(request)
    response.delete_cookie("olist_session")
    return {"authenticated": False}


def need_data():
    if not ready():
        raise HTTPException(503, "Chưa có dữ liệu. Chạy python manage.py setup")


@app.exception_handler(ValueError)
async def value_error(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


secured = [Depends(auth)]
data_secured = [Depends(auth), Depends(need_data)]


@app.get("/status", dependencies=secured)
def status():
    return {"version": __version__, "data_ready": ready(), "database": "sqlite" if settings().database_url.startswith("sqlite") else "postgresql",
            "providers": llm.provider_status(), "model_ready": ml.MODEL.exists(), "odoo_configured": bool(settings().odoo_password),
            "range": analytics.date_range() if ready() else None}


@app.get("/orders", dependencies=data_secured)
def order_samples():
    from .database import rows
    return rows("SELECT order_id, purchase_date, customer_state, product_gmv, order_status FROM order_fact WHERE purchase_month='2018-07' AND order_status='delivered' ORDER BY order_id LIMIT 8")


@app.get("/analytics/kpis", dependencies=data_secured)
def get_kpis(filters: Annotated[analytics.Filters, Depends()]):
    return analytics.kpis(filters)


@app.get("/analytics/{kind}", dependencies=data_secured)
def get_breakdown(kind: Literal["monthly", "category", "seller", "state"], filters: Annotated[analytics.Filters, Depends()]):
    return analytics.breakdown(kind, filters)


class Chat(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    filters: analytics.Filters = Field(default_factory=analytics.Filters)


@app.post("/agent/chat", dependencies=data_secured)
def chat(payload: Chat):
    return agent.ask(payload.question, payload.filters)


class Search(BaseModel):
    question: str = Field(min_length=2, max_length=2000)


@app.post("/rag/search", dependencies=secured)
def search(payload: Search):
    return rag.retrieve(payload.question)


@app.get("/orders/{order_id}", dependencies=data_secured)
def order(order_id: str):
    if len(order_id) != 32:
        raise HTTPException(422, "Mã đơn Olist gồm 32 ký tự")
    return analytics.lookup_order(order_id)


@app.post("/ml/order/{order_id}", dependencies=data_secured)
def predict_order(order_id: str):
    r = analytics.lookup_order(order_id)
    if not r:
        raise HTTPException(404, "Không tìm thấy đơn")
    return ml.predict(r[0])


@app.get("/reports/{name}", dependencies=secured)
def report(name: Literal["data_quality", "ml_evaluation", "verification"]):
    path = ROOT / "reports" / (name + ".json")
    if not path.exists():
        raise HTTPException(404, "Chưa có báo cáo")
    return json.loads(path.read_text(encoding="utf-8"))


def erp_read(which):
    try:
        odoo = erp.Odoo()
        return odoo.catalog() if which == "catalog" else odoo.quotations()
    except ValueError:
        raise
    except Exception as exc:
        raise HTTPException(503, "Chưa kết nối được Odoo. Xem docs/ODOO_WINDOWS.md và cấu hình .env") from exc


@app.get("/erp/{kind}", dependencies=secured)
def get_erp(kind: Literal["catalog", "quotations"]):
    return erp_read(kind)


@app.get("/actions", dependencies=secured)
def actions():
    return erp.list_actions()


@app.post("/actions", dependencies=secured)
def propose(payload: Quotation):
    return erp.propose(payload.model_dump())


@app.post("/actions/{action_id}/approve", dependencies=secured)
def approve(action_id: str):
    return erp.approve(action_id)


@app.post("/actions/{action_id}/reject", dependencies=secured)
def reject(action_id: str):
    return erp.reject(action_id)


@app.get("/audit", dependencies=secured)
def audit_events():
    with operational() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY created_at DESC LIMIT 100")]
