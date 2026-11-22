"""Read-only Odoo diagnostics; no credentials or raw RPC faults in output."""
from urllib.parse import urlparse

import httpx

from olist.config import settings
from olist.erp import Odoo


def check_odoo():
    cfg = settings()
    if urlparse(cfg.odoo_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        return {"ok": False, "stage": "configuration", "hint": "Bản này chỉ kết nối Odoo localhost."}
    try:
        response = httpx.get(cfg.odoo_url.rstrip("/") + "/web/login", timeout=10,
                             follow_redirects=False, trust_env=False)
        response.raise_for_status()
    except Exception as exc:
        return {"ok": False, "stage": "http", "error": type(exc).__name__,
                "hint": "Chạy docker compose ps và docker compose logs --tail 60 odoo."}
    if not cfg.odoo_password:
        return {"ok": False, "stage": "configuration", "hint": "Điền ODOO_DB, ODOO_LOGIN, ODOO_PASSWORD trong .env."}
    try:
        client = Odoo()
        client.authenticate()
    except Exception as exc:
        return {"ok": False, "stage": "authentication", "error": type(exc).__name__,
                "hint": "Kiểm tra tên database, email đăng nhập và API key/password của tài khoản Odoo."}
    try:
        modules = client.call("ir.module.module", "search_read", [[("name", "=", "sale"), ("state", "=", "installed")]],
                              {"fields": ["name"], "limit": 1})
        if not modules:
            return {"ok": False, "stage": "sales", "hint": "Cài ứng dụng Sales trong Odoo rồi kiểm tra lại."}
        catalog = client.catalog()
        quotations = client.quotations()
    except Exception as exc:
        return {"ok": False, "stage": "read_access", "error": type(exc).__name__,
                "hint": "Kiểm tra quyền đọc Sales/Contacts/Products của tài khoản kết nối."}
    return {"ok": True, "stage": "ready", "demo_partners_returned": len(catalog["partners"]),
            "demo_products_returned": len(catalog["products"]), "demo_quotations_returned": len(quotations),
            "hint": "Kết nối đọc thành công. Nếu chưa có demo, chạy manage.py odoo-seed --limit 10.",
            "limits": {"partners": 100, "products": 100, "quotations": 50}}
