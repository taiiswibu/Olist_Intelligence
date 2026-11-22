import hmac
import json
import hashlib
import os
import time
import asyncio
from pathlib import Path
from typing import Annotated, Literal
from fastapi import FastAPI, Depends, Header, HTTPException, Request, Cookie, Response, Query, Path as ApiPath
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr
from . import __version__, analytics, agent, rag, ml, erp, llm
from .config import ROOT, settings
from .database import ready, operational
from .schemas import Quotation, SalesQuotation, SalesProposal
from . import agent_team
from . import reporting, report_exports
from . import sales

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


@app.get("/report-drafts", dependencies=secured)
def report_list():
    return reporting.list_drafts()


@app.post("/report-drafts", dependencies=data_secured)
def report_create(payload: reporting.Create):
    return reporting.create(payload)


@app.get("/report-drafts/{report_id}", dependencies=secured)
def report_get(report_id: str):
    try:
        return reporting.get(report_id)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy báo cáo.") from None


@app.put("/report-drafts/{report_id}", dependencies=data_secured)
def report_update(report_id: str, payload: reporting.Update):
    try:
        return reporting.update(report_id, payload)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy báo cáo.") from None
    except reporting.Conflict as exc:
        raise HTTPException(409, str(exc)) from None


@app.get("/report-drafts/{report_id}/export/{file_format}", dependencies=secured)
def report_export(report_id: str, file_format: Literal["pdf", "xlsx"]):
    try:
        report = reporting.get(report_id)
    except KeyError:
        raise HTTPException(404, "Không tìm thấy báo cáo.") from None
    body = report_exports.pdf(report) if file_format == "pdf" else report_exports.excel(report)
    media = "application/pdf" if file_format == "pdf" else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(content=body, media_type=media, headers={"Content-Disposition": f'attachment; filename="olist_report_{report["id"][:8]}.{file_format}"', "Cache-Control": "no-store"})


@app.post("/agent/chat", dependencies=data_secured)
def chat(payload: Chat):
    return agent.ask(payload.question, payload.filters)


@app.get("/agent/team", dependencies=secured)
def team_configuration():
    return agent_team.team_status()


@app.post("/agent/team/chat", dependencies=data_secured)
async def team_chat(payload: agent_team.TeamRequest):
    try:
        return await agent_team.ask(payload)
    except agent_team.TeamUnavailable as exc:
        raise HTTPException(503, str(exc)) from None
    except agent_team.RunBusy as exc:
        raise HTTPException(409, str(exc)) from None


@app.post("/agent/team/stream", dependencies=data_secured)
async def team_stream(payload: agent_team.TeamRequest):
    # JSON lines over fetch keeps the existing cookie/CSRF headers and POST body.
    if not agent_team.team_status()["ready"]:
        raise HTTPException(503, "Đội agent chưa sẵn sàng. Kiểm tra cấu hình và requirements-agent.txt.")
    agent.extract_filters(payload.question, payload.filters)

    async def events():
        queue = asyncio.Queue()

        async def run():
            try:
                result = await agent_team.ask(payload, queue.put_nowait)
                queue.put_nowait({"type": "result", "result": result})
            except (agent_team.TeamUnavailable, agent_team.RunBusy, ValueError) as exc:
                queue.put_nowait({"type": "error", "message": str(exc)})
            except Exception:
                queue.put_nowait({"type": "error", "message": "Chưa hoàn tất lượt chạy. Kiểm tra trạng thái và ERP trước khi thử lại."})
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(run())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield json.dumps(event, ensure_ascii=False, default=str) + "\n"
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    return StreamingResponse(events(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


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


def sales_read(operation, *args):
    try:
        return operation(erp.Odoo(), *args)
    except ValueError:
        raise
    except Exception:
        raise HTTPException(503, "Chưa đọc được dữ liệu Odoo. Kiểm tra kết nối rồi thử lại.") from None


@app.get("/erp/search/{kind}", dependencies=secured)
def sales_search(kind: Literal["partners", "products"], q: str = Query(default="", max_length=120),
                 offset: int = Query(default=0, ge=0, le=10000), limit: int = Query(default=20, ge=1, le=50)):
    return sales_read(sales.search, kind, q, offset, limit)


@app.get("/erp/records/{kind}/{record_id}", dependencies=secured)
def sales_record(kind: Literal["partners", "products"], record_id: int = ApiPath(ge=1)):
    return sales_read(sales.record, kind, record_id)


@app.post("/erp/quotation-preview", dependencies=secured)
def sales_preview(payload: SalesQuotation):
    return sales_read(sales.preview, payload.model_dump())


@app.get("/erp/quotations/{order_id}", dependencies=secured)
def sales_order(order_id: int = ApiPath(ge=1)):
    return sales_read(sales.order_detail, order_id)


@app.get("/actions", dependencies=secured)
def actions():
    return erp.list_actions()


@app.post("/actions", dependencies=secured)
def propose(payload: SalesProposal | Quotation):
    try:
        return erp.propose(payload.model_dump())
    except ValueError:
        raise
    except Exception:
        raise HTTPException(503, "Chưa lưu được đề xuất. Kiểm tra kết nối rồi lấy lại bằng cùng mã yêu cầu.") from None


@app.get("/actions/{action_id}", dependencies=secured)
def action_detail(action_id: str):
    return erp.action_detail(action_id)


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
