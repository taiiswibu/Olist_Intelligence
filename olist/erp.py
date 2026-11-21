"""Odoo Community RPC adapter. Fixed operations, demo records, explicit approvals."""
import json
import uuid
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
        return self.call("sale.order", "search_read", [[("origin", "=like", "OLIST-%")]],
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
    from .schemas import Quotation
    validated = Quotation.model_validate(payload).model_dump()
    action_id = uuid.uuid4().hex
    with operational() as conn:
        conn.execute("INSERT INTO actions VALUES (?,?,?,?,?,?)", (action_id, now(), json.dumps(validated), "pending", None, now()))
    audit("action_proposed", {"action_id": action_id})
    return {"id": action_id, "state": "pending", "payload": validated}


def list_actions():
    with operational() as conn:
        records = [dict(r) for r in conn.execute("SELECT * FROM actions ORDER BY created_at DESC LIMIT 50")]
    for r in records:
        r["payload"] = json.loads(r["payload"])
        r["result"] = json.loads(r["result"]) if r["result"] else None
    return records


def approve(action_id):
    with operational() as conn:
        r = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if not r:
            raise ValueError("Không tìm thấy đề xuất")
        if r["state"] not in {"pending", "failed"}:
            raise ValueError("Đề xuất đã xử lý hoặc đang xử lý")
        changed = conn.execute("UPDATE actions SET state='executing', updated_at=? WHERE id=? AND state IN ('pending','failed')", (now(), action_id)).rowcount
        if not changed:
            raise ValueError("Đề xuất đang được xử lý ở phiên khác")
    try:
        result = Odoo().quotation(json.loads(r["payload"]), "OLIST-ACTION:" + action_id)
    except Exception as exc:
        with operational() as conn:
            conn.execute("UPDATE actions SET state='failed',result=?,updated_at=? WHERE id=?", (json.dumps({"error": type(exc).__name__}), now(), action_id))
        audit("action_failed", {"action_id": action_id, "error": type(exc).__name__})
        raise ValueError("Gọi Odoo thất bại. Kiểm tra kết nối/cấu hình; có thể duyệt lại an toàn bằng cùng mã đề xuất.") from exc
    with operational() as conn:
        conn.execute("UPDATE actions SET state='done',result=?,updated_at=? WHERE id=?", (json.dumps(result), now(), action_id))
    audit("action_approved", {"action_id": action_id, "odoo_id": result["odoo_id"]})
    return result


def reject(action_id):
    with operational() as conn:
        n = conn.execute("UPDATE actions SET state='rejected',updated_at=? WHERE id=? AND state='pending'", (now(), action_id)).rowcount
    if not n:
        raise ValueError("Chỉ từ chối được đề xuất đang chờ")
    audit("action_rejected", {"action_id": action_id})
    return {"state": "rejected"}
