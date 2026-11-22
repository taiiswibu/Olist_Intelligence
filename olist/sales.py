"""Read DEMO master data, review immutable proposals and create draft quotations only."""
from decimal import Decimal, ROUND_HALF_UP

from .schemas import SalesQuotation

FIELDS = {
    "partners": ("res.partner", "ref", ["id", "name", "ref", "email", "phone", "city", "street", "state_id", "country_id"]),
    "products": ("product.product", "default_code", ["id", "name", "default_code", "list_price", "currency_id", "uom_id", "type", "categ_id", "description_sale"]),
}


def canonical(payload):
    parsed = SalesQuotation.model_validate(payload)
    lines = []
    for line in parsed.lines:
        values = {"product_id": line.product_id, "quantity": format(line.quantity.normalize(), "f"), "unit_price": f"{line.unit_price:.2f}"}
        if line.discount:
            values["discount"] = f"{line.discount:.2f}"
        if line.tax_ids:
            values["tax_ids"] = line.tax_ids
        lines.append(values)
    return {"partner_id": parsed.partner_id, "lines": lines}


def search(client, kind, query="", offset=0, limit=20):
    model, marker, fields = FIELDS[kind]
    domain = [(marker, "=like", "OLIST-DEMO:%")]
    if query.strip():
        domain += ["|", ("name", "ilike", query.strip()), (marker, "ilike", query.strip())]
    rows = client.call(model, "search_read", [domain], {"fields": fields, "offset": offset, "limit": limit+1, "order": "name,id"})
    return {"rows": rows[:limit], "has_more": len(rows)>limit, "offset": offset, "limit": limit}


def record(client, kind, record_id):
    model, marker, fields = FIELDS[kind]
    rows = client.call(model, "search_read", [[("id", "=", record_id), (marker, "=like", "OLIST-DEMO:%")]], {"fields": fields, "limit": 1})
    if not rows:
        raise ValueError("Không tìm thấy bản ghi DEMO đang hoạt động.")
    return rows[0]


def amount(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def preview(client, payload):
    payload = canonical(payload)
    metadata = client.call("sale.order.line", "fields_get", [["product_uom_qty"]], {"attributes": ["digits"]})
    digits = metadata.get("product_uom_qty", {}).get("digits")
    if isinstance(digits, (list, tuple)) and len(digits) == 2:
        step = Decimal("1").scaleb(-int(digits[1]))
        if any(Decimal(line["quantity"]) != Decimal(line["quantity"]).quantize(step, rounding=ROUND_HALF_UP) for line in payload["lines"]):
            raise ValueError("Số lượng vượt độ chính xác đang cấu hình trong Odoo.")
    partner = record(client, "partners", payload["partner_id"])
    ids = sorted({line["product_id"] for line in payload["lines"]})
    model, marker, fields = FIELDS["products"]
    rows = client.call(model, "search_read", [[("id", "in", ids), (marker, "=like", "OLIST-DEMO:%")]], {"fields": fields, "limit": 20})
    products = {r["id"]: r for r in rows}
    if set(products) != set(ids):
        raise ValueError("Một sản phẩm không còn hoạt động hoặc không phải bản ghi DEMO.")
    lists = client.call("product.pricelist", "search_read", [[("name", "=", "OLIST DEMO BRL"), ("currency_id.name", "=", "BRL")]],
        {"fields": ["id", "name", "currency_id", "company_id"], "limit": 2})
    if len(lists) != 1:
        raise ValueError("Cần đúng một bảng giá OLIST DEMO BRL đang hoạt động. Kiểm tra cấu hình Odoo.")
    currencies = client.call("res.currency", "search_read", [[("id", "=", lists[0]["currency_id"][0])]], {"fields": ["id", "name", "rounding"], "limit": 1})
    if not currencies or currencies[0]["name"] != "BRL" or Decimal(str(currencies[0]["rounding"])) != Decimal("0.01"):
        raise ValueError("Bản demo yêu cầu BRL đang hoạt động và làm tròn đến 0,01.")
    lines = []
    for line in payload["lines"]:
        product = products[line["product_id"]]
        subtotal = amount(Decimal(line["quantity"]) * Decimal(line["unit_price"]))
        lines.append({**line, "name": product["name"], "code": product["default_code"],
                      "uom": product["uom_id"], "subtotal": f"{subtotal:.2f}"})
    total = sum((Decimal(line["subtotal"]) for line in lines), Decimal("0"))
    result = {"payload": payload, "partner": partner, "lines": lines, "pricelist": lists[0],
            "currency": "BRL", "subtotal": f"{total:.2f}", "tax": "0.00", "total": f"{total:.2f}",
            "policy": "Báo giá DEMO, không áp thuế hoặc chiết khấu. Đơn giá nhập riêng bằng BRL; giá trên thẻ sản phẩm chỉ để tham khảo."}
    if any(line.get("discount") or line.get("tax_ids") for line in payload["lines"]):
        from .sales_pricing import calculate
        return calculate(client, result, products)
    return result


def order_detail(client, order_id):
    orders = client.call("sale.order", "search_read", [[("id", "=", order_id), ("origin", "=like", "OLIST-%"),
                        ("partner_id.ref", "=like", "OLIST-DEMO:%")]],
        {"fields": ["id", "name", "partner_id", "state", "origin", "date_order", "pricelist_id", "currency_id", "company_id", "fiscal_position_id",
                    "amount_untaxed", "amount_tax", "amount_total"], "limit": 1})
    if not orders:
        raise ValueError("Không tìm thấy báo giá thuộc phạm vi Olist DEMO.")
    order = orders[0]
    order["lines"] = client.call("sale.order.line", "search_read", [[("order_id", "=", order_id), ("display_type", "=", False)]],
        {"fields": ["id", "sequence", "name", "product_id", "product_uom_qty", "price_unit", "discount", "tax_ids",
                    "price_subtotal", "price_tax", "price_total"], "limit": 501, "order": "sequence,id"})
    order["lines_truncated"] = len(order["lines"]) > 500
    order["lines"] = order["lines"][:500]
    tax_ids = sorted({tax for line in order["lines"] for tax in line["tax_ids"]})
    if tax_ids:
        names = client.call("account.tax", "search_read", [[("id", "in", tax_ids), ("company_id", "=", order["company_id"][0])]],
                            {"fields": ["id", "name"], "context": {"active_test": False}, "limit": 200})
        labels = {tax["id"]: tax["name"] for tax in names}
        for line in order["lines"]:
            line["tax_names"] = [labels.get(tax, f"#{tax}") for tax in line["tax_ids"]]
    return order


def _check_order(order, payload, review):
    lines = order["lines"]
    expected = review["lines"]
    if (order["state"] != "draft" or order["partner_id"][0] != payload["partner_id"]
            or order["currency_id"][1] != "BRL" or order["pricelist_id"][0] != review["pricelist"]["id"]
            or len(lines) != len(expected) or order.get("lines_truncated")
            or amount(order["amount_total"]) != Decimal(review["total"])
            or amount(order["amount_untaxed"]) != Decimal(review["subtotal"]) or amount(order["amount_tax"]) != Decimal(review["tax"])):
        raise ValueError("Báo giá Odoo chưa khớp đề xuất đã duyệt. Kiểm tra origin trước khi xử lý tiếp.")
    if review.get("pricing_version") == 2:
        if order["company_id"][0] != review["company"]["id"] or (order["fiscal_position_id"][0] if order["fiscal_position_id"] else False) != review["fiscal_position_id"]:
            raise ValueError("Công ty hoặc vị trí tài chính của báo giá không khớp đề xuất.")
    for actual, line in zip(lines, expected):
        if (actual["product_id"][0] != line["product_id"] or Decimal(str(actual["product_uom_qty"])) != Decimal(line["quantity"])
                or Decimal(str(actual["price_unit"])) != Decimal(line["unit_price"])
                or sorted(actual["tax_ids"]) != line.get("tax_ids", []) or Decimal(str(actual["discount"])) != Decimal(line.get("discount", "0"))
                or amount(actual["price_subtotal"]) != Decimal(line["subtotal"]) or amount(actual["price_tax"]) != Decimal(line.get("tax", "0"))
                or amount(actual["price_total"]) != Decimal(line.get("total", line["subtotal"]))):
            raise ValueError("Một dòng báo giá Odoo chưa khớp đề xuất. Kiểm tra origin trước khi xử lý tiếp.")


def create_quotation(client, payload, origin, review):
    payload = canonical(payload)
    if not review or review["payload"] != payload:
        raise ValueError("Thiếu nội dung đối soát đã lưu. Tạo lại đề xuất để duyệt.")
    existing = client.call("sale.order", "search", [[("origin", "=", origin)]], {"limit": 2})
    if len(existing) > 1:
        raise ValueError("Có nhiều báo giá cùng origin; cần đối soát thủ công.")
    if existing:
        order_id = existing[0]
    else:
        if preview(client, payload) != review:
            raise ValueError("Thông tin Odoo đã đổi từ lúc lập đề xuất. Chưa ghi báo giá; cần lập và duyệt đề xuất mới.")
        values = {"partner_id": payload["partner_id"], "origin": origin,
            "pricelist_id": review["pricelist"]["id"], "order_line": [(0, 0, {
                "product_id": line["product_id"], "product_uom_qty": float(line["quantity"]),
                "price_unit": float(line["unit_price"]), "discount": float(line.get("discount", 0)), "tax_ids": [(6, 0, line.get("tax_ids", []))]}) for line in payload["lines"]]}
        if review.get("pricing_version") == 2:
            values.update(company_id=review["company"]["id"], fiscal_position_id=review["fiscal_position_id"])
        order_id = client.call("sale.order", "create", [values])
    order = order_detail(client, order_id)
    if order["origin"] != origin:
        raise ValueError("Origin của báo giá đã thay đổi. Cần đối soát lại trong Odoo.")
    _check_order(order, payload, review)
    return {"odoo_id": order_id, "name": order["name"], "origin": origin, "reused": bool(existing),
            "state": order["state"], "currency": "BRL", "amount_total": order["amount_total"], "verified": True}
