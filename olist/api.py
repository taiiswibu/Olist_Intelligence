import hmac
import json
from pathlib import Path
from typing import Annotated, Literal
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from . import __version__, analytics, agent, rag, ml, erp, llm
from .config import ROOT, settings
from .database import ready, operational
from .schemas import Quotation

app = FastAPI(title="Olist Intelligence Local API", version=__version__)


def auth(x_app_token: Annotated[str | None, Header()] = None):
    expected = settings().app_token
    if not expected or not x_app_token or not hmac.compare_digest(expected.encode(), x_app_token.encode()):
        raise HTTPException(401, "APP_TOKEN không hợp lệ")


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
