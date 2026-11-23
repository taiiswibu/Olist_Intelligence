"""Local report drafts built from parameterized BI tools, never client-supplied figures."""
import json
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import analytics, database

LABELS = {
    "product_gmv": "GMV hàng hóa (BRL)", "orders": "Số đơn", "delivered_orders": "Đơn đã giao",
    "product_aov": "AOV hàng hóa (BRL)", "late_delivery_rate": "Tỷ lệ giao trễ",
    "late_eligible": "Đơn đủ ngày giao", "late_orders": "Đơn giao trễ", "late_rate": "Tỷ lệ giao trễ",
    "canceled_orders": "Đơn hủy", "cancellation_rate": "Tỷ lệ hủy", "freight": "Cước (BRL)",
    "month": "Tháng", "category": "Ngành hàng", "state": "Bang", "seller_id": "Người bán",
}
DIMENSIONS = {"monthly": "month", "category": "category", "state": "state", "seller": "seller_id"}
KINDS = {"monthly": "Theo tháng", "category": "Ngành hàng", "state": "Bang", "seller": "Người bán"}
LIMITS = [
    "Dữ liệu lịch sử Olist 2016–2018; ngày lọc là ngày mua, bang là bang khách hàng. Tiền tệ BRL.",
    "GMV/AOV chỉ tính hàng hóa của đơn delivered, không gồm cước; không phải doanh thu ròng.",
    "Giao trễ so theo ngày lịch, trên đơn delivered đủ ngày giao thực tế và ngày hẹn.",
    "Ngành hàng: top 15 GMV. Seller: top 20 số đơn trễ, tối thiểu 20 đơn; không phải xếp hạng tỷ lệ trễ. Bang: tối thiểu 20 đơn đủ ngày giao.",
    "Các nhóm có giới hạn và có thể chồng lấn đơn hàng; không cộng bảng seller/ngành hàng thành tổng số đơn.",
    "Nhận xét là nội dung có thể chỉnh sửa, cần đối chiếu bằng chứng; không chứng minh nguyên nhân giao trễ.",
]


class Chart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["monthly", "category", "state", "seller"] = "monthly"
    metric: Literal["product_gmv", "orders", "late_rate"] = "product_gmv"
    chart_type: Literal["line", "bar"] = "line"
    title: str = Field(default="GMV theo tháng", min_length=1, max_length=120)

    @model_validator(mode="after")
    def supported(self):
        if self.kind == "category" and self.metric == "late_rate":
            raise ValueError("Bảng ngành hàng không có tỷ lệ giao trễ.")
        if self.kind != "monthly" and self.chart_type == "line":
            raise ValueError("Biểu đồ đường chỉ dùng cho dữ liệu theo tháng.")
        return self


class Definition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="Báo cáo kinh doanh Olist", min_length=1, max_length=160)
    filters: analytics.Filters = Field(default_factory=analytics.Filters)
    notes: str = Field(default="", max_length=8000)
    charts: list[Chart] = Field(default_factory=lambda: [Chart(), Chart(kind="category", chart_type="bar", title="GMV theo ngành hàng")], max_length=6)
    include_tables: bool = True

    @model_validator(mode="after")
    def printable_text(self):
        for text in [self.title, self.notes, *[c.title for c in self.charts]]:
            if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                raise ValueError("Nội dung chứa ký tự điều khiển không được hỗ trợ.")
        if not self.title.strip() or any(not c.title.strip() for c in self.charts):
            raise ValueError("Tiêu đề không được để trống.")
        return self


class Create(Definition):
    source_run_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class Update(Definition):
    version: int = Field(ge=1)


class Conflict(ValueError):
    pass


def _storage():
    conn = database.operational()
    conn.execute("""CREATE TABLE IF NOT EXISTS report_drafts (
        id TEXT PRIMARY KEY, definition TEXT NOT NULL, snapshot TEXT NOT NULL,
        source TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, version INTEGER NOT NULL)""")
    conn.commit()
    return conn


def _decode(row):
    return {"id": row["id"], **json.loads(row["definition"]), "snapshot": json.loads(row["snapshot"]),
            "source": json.loads(row["source"]) if row["source"] else None,
            "created_at": row["created_at"], "updated_at": row["updated_at"], "version": row["version"],
            "limits": LIMITS}


def get(report_id):
    conn = _storage()
    try:
        row = conn.execute("SELECT * FROM report_drafts WHERE id=?", (report_id,)).fetchone()
        if not row:
            raise KeyError("Không tìm thấy báo cáo.")
        return _decode(row)
    finally:
        conn.close()


def list_drafts():
    conn = _storage()
    try:
        rows = conn.execute("SELECT id,definition,updated_at,version FROM report_drafts ORDER BY updated_at DESC LIMIT 100").fetchall()
        return [{"id": r["id"], "title": json.loads(r["definition"])["title"],
                 "filters": json.loads(r["definition"])["filters"], "updated_at": r["updated_at"], "version": r["version"]} for r in rows]
    finally:
        conn.close()


def snapshot(definition):
    datasets = {kind: analytics.breakdown(kind, definition.filters) for kind in dict.fromkeys(c.kind for c in definition.charts)}
    return {"generated_at": database.now(), "kpis": analytics.kpis(definition.filters), "datasets": datasets}


def _chat_source(run_id):
    from .agent_team import _storage as team_storage
    with team_storage() as conn:
        row = conn.execute("SELECT r.result,t.question FROM team_runs r JOIN team_turns t USING(run_id) WHERE r.run_id=?", (run_id,)).fetchone()
    if not row or not row["result"]:
        raise ValueError("Lượt chat chưa có kết quả để tạo báo cáo.")
    result = json.loads(row["result"])
    if not any(e["tool"] in {"business_kpis", "business_breakdown"} for e in result.get("evidence", [])):
        raise ValueError("Lượt chat chưa có bằng chứng BI. Hãy hỏi KPI hoặc bảng phân tích trước.")
    documents = [s for e in result.get("evidence", []) if e["tool"] == "search_business_docs"
                 for s in e["result"].get("sources", [])]
    documents = list({s["id"]: s for s in documents}.values())
    return result, {"run_id": run_id, "question": row["question"], "status": result["status"],
                    "filters": result["filters"], "documents": documents}


def create(payload):
    definition = Definition.model_validate(payload.model_dump(exclude={"source_run_id"}))
    source = None
    if payload.source_run_id:
        result, source = _chat_source(payload.source_run_id)
        definition.filters = analytics.Filters.model_validate(result["filters"])
        if not definition.notes:
            definition.notes = "".join(c for c in result["answer"][:8000] if ord(c) >= 32 or c in "\n\r\t")
    saved = snapshot(definition)
    report_id, stamp = uuid.uuid4().hex, database.now()
    conn = _storage()
    try:
        with conn:
            conn.execute("INSERT INTO report_drafts VALUES (?,?,?,?,?,?,?)", (report_id, definition.model_dump_json(),
                json.dumps(saved, ensure_ascii=False), json.dumps(source, ensure_ascii=False) if source else None, stamp, stamp, 1))
    finally:
        conn.close()
    database.audit("report_created", {"report_id": report_id, "source_run_id": payload.source_run_id})
    return get(report_id)


def update(report_id, payload):
    current = get(report_id)
    if current["version"] != payload.version:
        raise Conflict("Báo cáo đã thay đổi ở nơi khác. Mở lại trước khi sửa tiếp.")
    definition = Definition.model_validate(payload.model_dump(exclude={"version"}))
    saved = current["snapshot"]
    if definition.filters.model_dump(mode="json") != current["filters"] or any(c.kind not in saved["datasets"] for c in definition.charts):
        saved = snapshot(definition)
    conn = _storage()
    try:
        with conn:
            changed = conn.execute("UPDATE report_drafts SET definition=?,snapshot=?,updated_at=?,version=version+1 WHERE id=? AND version=?",
                (definition.model_dump_json(), json.dumps(saved, ensure_ascii=False), database.now(), report_id, payload.version)).rowcount
            if not changed:
                raise Conflict("Báo cáo đã thay đổi ở nơi khác. Mở lại trước khi sửa tiếp.")
    finally:
        conn.close()
    return get(report_id)


def series(report, chart):
    dimension = DIMENSIONS[chart["kind"]]
    return [(str(row[dimension]), row[chart["metric"]]) for row in report["snapshot"]["datasets"][chart["kind"]]["rows"]]


def formatted(value, metric):
    if value is None:
        return "Chưa đủ dữ liệu"
    if "rate" in metric:
        return f"{value * 100:.2f}%"
    if metric in {"product_gmv", "product_aov", "freight"}:
        return f"R$ {value:,.2f}"
    return f"{value:,.0f}" if isinstance(value, (int, float)) else str(value)
