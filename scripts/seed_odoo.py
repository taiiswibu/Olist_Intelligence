from olist.erp import Odoo
from olist.database import rows, audit


def seed(limit=10):
    """Explicit CLI import; idempotent drafts only, no invented inventory."""
    odoo = Odoo()
    freight_code = "OLIST-DEMO:FREIGHT"
    freight_found = odoo.call("product.product", "search", [[("default_code", "=", freight_code)]])
    freight_id = freight_found[0] if freight_found else odoo.call("product.product", "create", [{"name": "DEMO historical freight", "default_code": freight_code, "type": "service", "list_price": 0, "taxes_id": [(6,0,[])]}])
    source = rows("SELECT order_id,customer_unique_id FROM order_fact WHERE order_status='delivered' ORDER BY purchase_at,order_id LIMIT :n", {"n": limit})
    imported = []
    for r in source:
        origin = "OLIST-DEMO:" + r["order_id"]
        prior = odoo.call("sale.order", "search", [[("origin", "=", origin)]])
        if prior:
            imported.append({"source_order": r["order_id"], "odoo_id": prior[0], "reused": True})
            continue
        customer_ref = "OLIST-DEMO:" + r["customer_unique_id"]
        partners = odoo.call("res.partner", "search", [[("ref", "=", customer_ref)]])
        pid = partners[0] if partners else odoo.call("res.partner", "create", [{"name": "DEMO Olist customer " + r["customer_unique_id"][:8], "ref": customer_ref}])
        lines = []
        for item in rows("SELECT product_id,price,freight_value,category FROM item_fact WHERE order_id=:id ORDER BY order_item_id", {"id": r["order_id"]}):
            code = "OLIST-DEMO:" + item["product_id"]
            found = odoo.call("product.product", "search", [[("default_code", "=", code)]])
            product_id = found[0] if found else odoo.call("product.product", "create", [{"name": "DEMO " + item["category"] + " " + item["product_id"][:8], "default_code": code, "type": "service", "list_price": item["price"], "taxes_id": [(6,0,[])]}])
            lines.append((0, 0, {"product_id": product_id, "product_uom_qty": 1, "price_unit": item["price"], "tax_ids": [(6,0,[])]}))
            if item["freight_value"]:
                lines.append((0, 0, {"product_id": freight_id, "name": "DEMO historical freight", "product_uom_qty": 1, "price_unit": item["freight_value"], "tax_ids": [(6,0,[])]}))
        oid = odoo.call("sale.order", "create", [{"partner_id": pid, "origin": origin, "pricelist_id": odoo.brl_pricelist(), "order_line": lines}])
        imported.append({"source_order": r["order_id"], "odoo_id": oid, "reused": False})
    audit("odoo_seed", {"orders": len(imported)})
    return imported
