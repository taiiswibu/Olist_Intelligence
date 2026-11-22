"""Odoo Community RPC adapter. Fixed operations, demo records, explicit approvals."""
import json
import uuid
import hashlib
import xmlrpc.client
from urllib.parse import urlparse
import httpx
from .config import settings
from .database import operational, now, audit


class Odoo:
    def __init__(self):
        self.cfg = settings()
        parsed = urlparse(self.cfg.odoo_url)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Bản local chỉ kết nối Odoo trên localhost")
        if not self.cfg.odoo_password:
            raise ValueError("Chưa cấu hình ODOO_PASSWORD trong .env")
        self.uid = None

    def rpc(self, endpoint, method, args):
        body = xmlrpc.client.dumps(tuple(args), methodname=method, allow_none=True).encode()
        r = httpx.post(self.cfg.odoo_url.rstrip("/") + "/xmlrpc/2/" + endpoint,
                       content=body, headers={"Content-Type": "text/xml"}, timeout=30, trust_env=False)
        r.raise_for_status()
        return xmlrpc.client.loads(r.content)[0][0]

    def authenticate(self):
        self.uid = self.rpc("common", "authenticate", [self.cfg.odoo_db, self.cfg.odoo_login, self.cfg.odoo_password, {}])
        if not self.uid:
            raise ValueError("Odoo đăng nhập thất bại; kiểm tra database, tài khoản và API key/password")
        return self.uid

    def call(self, model, method, args=None, kwargs=None):
        if self.uid is None:
            self.authenticate()
        return self.rpc("object", "execute_kw", [self.cfg.odoo_db, self.uid, self.cfg.odoo_password, model, method, args or [], kwargs or {}])

    def catalog(self):
        return {
            "partners": self.call("res.partner", "search_read", [[("ref", "=like", "OLIST-DEMO:%")]], {"fields": ["id", "name", "ref"], "limit": 100}),
            "products": self.call("product.product", "search_read", [[("default_code", "=like", "OLIST-DEMO:%")]], {"fields": ["id", "name", "default_code", "list_price"], "limit": 100}),
        }

    def quotations(self):
        return self.call("sale.order", "search_read", [[("origin", "=like", "OLIST-%"), ("partner_id.ref", "=like", "OLIST-DEMO:%")]],
                         {"fields": ["id", "name", "partner_id", "state", "amount_total", "currency_id", "origin"], "limit": 50, "order": "id desc"})

    def brl_pricelist(self):
        currencies = self.call("res.currency", "search", [[("name", "=", "BRL")]], {"context": {"active_test": False}})
        if not currencies:
            raise ValueError("Không tìm thấy tiền tệ BRL trong Odoo")
        self.call("res.currency", "write", [currencies, {"active": True}])
        found = self.call("product.pricelist", "search", [[("name", "=", "OLIST DEMO BRL")]])
        return found[0] if found else self.call("product.pricelist", "create", [{"name": "OLIST DEMO BRL", "currency_id": currencies[0]}])

    def quotation(self, payload, origin):
        # Idempotent recovery after network failures. Never confirm, invoice or charge.
        existing = self.call("sale.order", "search", [[("origin", "=", origin)]])
        if existing:
            return {"odoo_id": existing[0], "origin": origin, "reused": True}
        partner = self.call("res.partner", "search", [[("id", "=", payload["partner_id"]), ("ref", "=like", "OLIST-DEMO:%")]])
        product = self.call("product.product", "search", [[("id", "=", payload["product_id"]), ("default_code", "=like", "OLIST-DEMO:%")]])
        if not partner or not product:
            raise ValueError("Chỉ cho phép khách hàng/sản phẩm demo đã import")
        oid = self.call("sale.order", "create", [{"partner_id": partner[0], "origin": origin,
            "pricelist_id": self.brl_pricelist(),
            "order_line": [(0, 0, {"product_id": product[0], "product_uom_qty": payload["quantity"],
                                   "price_unit": payload["unit_price"], "tax_ids": [(6, 0, [])]})]}])
        return {"odoo_id": oid, "origin": origin, "reused": False, "state": "draft"}


def propose(payload):
    if "lines" in payload:
        return propose_sales(payload)
    from .schemas import Quotation
    validated = Quotation.model_validate(payload).model_dump()
    action_id = uuid.uuid4().hex
    with operational() as conn:
        conn.execute("INSERT INTO actions VALUES (?,?,?,?,?,?)", (action_id, now(), json.dumps(validated), "pending", None, now()))
    audit("action_proposed", {"action_id": action_id})
    return {"id": action_id, "state": "pending", "payload": validated}


def _review_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS action_reviews (
        action_id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
        fingerprint TEXT NOT NULL, review TEXT NOT NULL)""")


def _event(conn, event, action_id, **detail):
    conn.execute("INSERT INTO audit VALUES (?,?,?,?)", (uuid.uuid4().hex, now(), event,
                 json.dumps({"action_id": action_id, **detail}, ensure_ascii=False)))


def _decode_action(row):
    record = dict(row)
    record["payload"] = json.loads(record["payload"])
    record["result"] = json.loads(record["result"]) if record["result"] else None
    record["review"] = json.loads(record["review"]) if record.get("review") else None
    return record


def propose_sales(payload):
    from .schemas import SalesProposal
    from .sales import canonical, preview
    parsed = SalesProposal.model_validate(payload)
    validated = canonical(parsed.model_dump(exclude={"request_id"}))
    fingerprint = hashlib.sha256(json.dumps(validated, sort_keys=True).encode()).hexdigest()

    def previous(conn):
        row = conn.execute("SELECT a.*,r.review,r.fingerprint FROM actions a JOIN action_reviews r ON a.id=r.action_id WHERE r.request_id=?", (parsed.request_id,)).fetchone()
        if not row:
            return None
        if row["fingerprint"] != fingerprint:
            raise ValueError("Mã lưu đề xuất đã dùng cho nội dung khác. Đối soát lại trước khi lưu.")
        decoded = _decode_action(row)
        return {key: decoded[key] for key in ("id", "state", "payload", "review")}

    conn = operational()
    try:
        _review_table(conn)
        conn.commit()
        cached = previous(conn)
        if cached:
            return cached
    finally:
        conn.close()
    review = preview(Odoo(), validated)  # Read-only; no pending record if validation fails.
    conn = operational()
    try:
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            cached = previous(conn)
            if cached:
                return cached
            action_id, stamp = uuid.uuid4().hex, now()
            conn.execute("INSERT INTO actions VALUES (?,?,?,?,?,?)", (action_id, stamp, json.dumps(validated), "pending", None, stamp))
            conn.execute("INSERT INTO action_reviews VALUES (?,?,?,?)", (action_id, parsed.request_id, fingerprint, json.dumps(review, ensure_ascii=False)))
            _event(conn, "action_proposed", action_id)
        return {"id": action_id, "state": "pending", "payload": validated, "review": review}
    finally:
        conn.close()


def list_actions():
    with operational() as conn:
        _review_table(conn)
        return [_decode_action(r) for r in conn.execute("SELECT a.*,r.review FROM actions a LEFT JOIN action_reviews r ON a.id=r.action_id ORDER BY a.created_at DESC LIMIT 50")]


def action_detail(action_id):
    with operational() as conn:
        _review_table(conn)
        row = conn.execute("SELECT a.*,r.review FROM actions a LEFT JOIN action_reviews r ON a.id=r.action_id WHERE a.id=?", (action_id,)).fetchone()
        if not row:
            raise ValueError("Không tìm thấy đề xuất.")
        result = _decode_action(row)
        result["history"] = [{**dict(e), "detail": json.loads(e["detail"])} for e in conn.execute(
            "SELECT created_at,event,detail FROM audit WHERE json_extract(detail,'$.action_id')=? ORDER BY created_at,id", (action_id,))]
        return result


def approve(action_id):
    with operational() as conn:
        _review_table(conn)
        r = conn.execute("SELECT a.*,rv.review FROM actions a LEFT JOIN action_reviews rv ON a.id=rv.action_id WHERE a.id=?", (action_id,)).fetchone()
        if not r:
            raise ValueError("Không tìm thấy đề xuất")
        if r["state"] not in {"pending", "failed"}:
            raise ValueError("Đề xuất đã xử lý hoặc đang xử lý")
        changed = conn.execute("UPDATE actions SET state='executing', updated_at=? WHERE id=? AND state IN ('pending','failed')", (now(), action_id)).rowcount
        if not changed:
            raise ValueError("Đề xuất đang được xử lý ở phiên khác")
        _event(conn, "action_approving", action_id)
    try:
        payload = json.loads(r["payload"])
        if "lines" in payload:
            from .sales import create_quotation
            result = create_quotation(Odoo(), payload, "OLIST-ACTION:" + action_id, json.loads(r["review"]) if r["review"] else None)
        else:
            result = Odoo().quotation(payload, "OLIST-ACTION:" + action_id)
    except Exception as exc:
        with operational() as conn:
            conn.execute("UPDATE actions SET state='failed',result=?,updated_at=? WHERE id=?", (json.dumps({"error": type(exc).__name__}), now(), action_id))
            _event(conn, "action_failed", action_id, error=type(exc).__name__)
        raise ValueError("Gọi Odoo thất bại. Kiểm tra kết nối/cấu hình; có thể duyệt lại an toàn bằng cùng mã đề xuất.") from exc
    with operational() as conn:
        conn.execute("UPDATE actions SET state='done',result=?,updated_at=? WHERE id=?", (json.dumps(result), now(), action_id))
        _event(conn, "action_approved", action_id, odoo_id=result["odoo_id"])
    return result


def reject(action_id):
    with operational() as conn:
        n = conn.execute("UPDATE actions SET state='rejected',updated_at=? WHERE id=? AND state='pending'", (now(), action_id)).rowcount
        if not n:
            raise ValueError("Chỉ từ chối được đề xuất đang chờ")
        _event(conn, "action_rejected", action_id)
    return {"state": "rejected"}
