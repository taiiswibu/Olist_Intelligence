"""Read-only Odoo virtual form calculations, including document-level tax rounding."""
from decimal import Decimal

TAX_FIELDS = ["id", "name", "amount", "amount_type", "type_tax_use", "active", "company_id",
              "price_include", "include_base_amount", "is_base_affected", "sequence", "children_tax_ids",
              "tax_scope", "country_id", "fiscal_position_ids", "write_date"]
LINE_FIELDS = ["product_id", "product_uom_qty", "price_unit", "discount", "tax_ids",
               "price_subtotal", "price_tax", "price_total"]


def relation_id(value):
    return value[0] if isinstance(value, (list, tuple)) else value.get("id") if isinstance(value, dict) else value


def context(client, pricelist):
    if client.uid is None:
        client.authenticate()
    user = client.call("res.users", "read", [[client.uid]], {"fields": ["company_id"]})[0]
    company_id = user["company_id"][0]
    if pricelist.get("company_id") and pricelist["company_id"][0] != company_id:
        raise ValueError("Bảng giá DEMO không thuộc công ty đang kết nối.")
    company = client.call("res.company", "read", [[company_id]], {"fields": ["name", "currency_id",
                          "tax_calculation_rounding_method", "account_fiscal_country_id", "domestic_fiscal_position_id"]})[0]
    return {"id": company["id"], "name": company["name"], "currency_id": company["currency_id"],
            "rounding_method": company["tax_calculation_rounding_method"], "fiscal_country_id": company["account_fiscal_country_id"],
            "domestic_fiscal_position_id": company["domestic_fiscal_position_id"]}


def tax_catalog(client):
    lists = client.call("product.pricelist", "search_read", [[("name", "=", "OLIST DEMO BRL"), ("currency_id.name", "=", "BRL")]],
                        {"fields": ["id", "company_id", "currency_id"], "limit": 2})
    if len(lists) != 1:
        raise ValueError("Cần đúng một bảng giá OLIST DEMO BRL đang hoạt động.")
    company = context(client, lists[0])
    rows = client.call("account.tax", "search_read", [[("company_id", "=", company["id"]),
                      ("active", "=", True), ("type_tax_use", "=", "sale")]],
                      {"fields": TAX_FIELDS, "limit": 201, "order": "sequence,id"})
    return {"company": company, "rows": rows[:200], "truncated": len(rows) > 200}


def tax_definitions(client, company_id, selected):
    if not selected:
        return []
    roots = client.call("account.tax", "search_read", [[("id", "in", selected), ("company_id", "=", company_id),
                        ("active", "=", True), ("type_tax_use", "=", "sale")]], {"fields": TAX_FIELDS, "limit": 200})
    if {r["id"] for r in roots} != set(selected):
        raise ValueError("Thuế phải là thuế bán hàng đang hoạt động trong công ty đang kết nối.")
    records = {r["id"]: r for r in roots}
    pending = {child for r in roots for child in r["children_tax_ids"]} - set(records)
    while pending:
        if len(records) + len(pending) > 200:
            raise ValueError("Cấu hình nhóm thuế vượt giới hạn đối soát của bản local.")
        children = client.call("account.tax", "search_read", [[("id", "in", sorted(pending)), ("company_id", "=", company_id)]],
                               {"fields": TAX_FIELDS, "limit": 200, "context": {"active_test": False}})
        if {r["id"] for r in children} != pending:
            raise ValueError("Chưa đọc đủ cấu hình thuế con trong cùng công ty.")
        records.update({r["id"]: r for r in children})
        pending = {child for r in children for child in r["children_tax_ids"]} - set(records)
    if any(r["amount_type"] not in {"percent", "fixed", "division", "group"} for r in records.values()):
        raise ValueError("Loại thuế tùy biến chưa được hỗ trợ trong bản local.")
    return [records[key] for key in sorted(records)]


def _onchange(client, model, values, names, spec, company_id):
    result = client.call(model, "onchange", [[], values, names, spec], {"context": {"allowed_company_ids": [company_id]}})
    if result.get("warning"):
        raise ValueError("Odoo có cảnh báo khi tính báo giá. Kiểm tra cấu hình trên Odoo trước khi tiếp tục.")
    if not isinstance(result.get("value"), dict):
        raise ValueError("Odoo chưa trả kết quả tính toán hợp lệ.")
    return result["value"]


def _tax_ids(commands):
    selected = set()
    for command in commands or []:
        if isinstance(command, int):
            selected.add(command)
        elif command[0] == 4:
            selected.add(command[1])
        elif command[0] == 6:
            selected = set(command[2])
        elif command[0] == 5:
            selected.clear()
        elif command[0] in {2, 3}:
            selected.discard(command[1])
        else:
            raise ValueError("Odoo trả thay đổi thuế chưa hỗ trợ; chưa lưu đề xuất.")
    return sorted(selected)


def calculate(client, review, products):
    from .sales import amount
    payload = review["payload"]
    company = context(client, review["pricelist"])
    selected = sorted({tax for line in payload["lines"] for tax in line.get("tax_ids", [])})
    definitions = tax_definitions(client, company["id"], selected)
    taxes = {t["id"]: t for t in definitions}
    header = {"partner_id": payload["partner_id"], "company_id": company["id"],
              "pricelist_id": review["pricelist"]["id"], "currency_id": review["pricelist"]["currency_id"][0]}
    head_spec = {key: {} for key in [*header, "fiscal_position_id", "tax_country_id"]}
    defaults = _onchange(client, "sale.order", dict(header), [], head_spec, company["id"])
    if any(relation_id(defaults.get(key)) != value for key, value in header.items()):
        raise ValueError("Odoo thay đổi khách/công ty/bảng giá/tiền tệ. Đối soát lại cấu hình.")
    header["fiscal_position_id"] = relation_id(defaults.get("fiscal_position_id")) or False
    effective_position = header["fiscal_position_id"] or relation_id(company["domestic_fiscal_position_id"])
    lines, commands = [], []
    for original, line in zip(review["lines"], payload["lines"]):
        ids = line.get("tax_ids", [])
        for tax_id in ids:
            tax = taxes[tax_id]
            if tax["tax_scope"] and tax["tax_scope"] != products[line["product_id"]]["type"]:
                raise ValueError("Phạm vi thuế không khớp loại sản phẩm.")
            if tax["fiscal_position_ids"] and effective_position not in tax["fiscal_position_ids"]:
                raise ValueError("Thuế không thuộc vị trí tài chính hiện tại của khách.")
            country = relation_id(defaults.get("tax_country_id"))
            if tax["country_id"] and country and tax["country_id"][0] != country:
                raise ValueError("Quốc gia của thuế không khớp báo giá Odoo.")
        values = {"product_id": line["product_id"], "product_uom_qty": float(line["quantity"]),
                  "price_unit": float(line["unit_price"]), "discount": float(line.get("discount", 0)), "tax_ids": [(6, 0, ids)]}
        native = _onchange(client, "sale.order.line", {**values, "order_id": dict(header)}, [],
                           {key: {} for key in LINE_FIELDS}, company["id"])
        if (relation_id(native.get("product_id")) != line["product_id"]
                or any(Decimal(str(native[key])) != Decimal(str(values[key])) for key in ["product_uom_qty", "price_unit", "discount"])
                or _tax_ids(native.get("tax_ids")) != ids):
            raise ValueError("Odoo thay đổi sản phẩm, giá, số lượng, chiết khấu hoặc thuế đã chọn. Chưa lưu đề xuất.")
        subtotal, total = amount(native["price_subtotal"]), amount(native["price_total"])
        if subtotal < 0 or total < 0:
            raise ValueError("Cấu hình đưa tiền dòng hàng về số âm; kiểm tra lại trên Odoo.")
        lines.append({**original, "discount": f"{Decimal(str(values['discount'])):.2f}", "tax_ids": ids,
                      "tax_names": [taxes[tid]["name"] for tid in ids], "subtotal": f"{subtotal:.2f}",
                      "tax": f"{amount(native['price_tax']):.2f}", "total": f"{total:.2f}"})
        commands.append((0, 0, values))

    def totals(items):
        spec = {key: {} for key in [*header, "amount_untaxed", "amount_tax", "amount_total"]}
        spec["order_line"] = {"fields": {key: {} for key in LINE_FIELDS}}
        values = _onchange(client, "sale.order", {**header, "order_line": items}, ["order_line"], spec, company["id"])
        return {key: amount(values.get(key, 0)) for key in ["amount_untaxed", "amount_tax", "amount_total"]}

    final = totals(commands)
    baseline = totals([(0, 0, {**cmd[2], "discount": 0}) for cmd in commands]) if any(Decimal(line["discount"]) for line in lines) else final
    if final["amount_untaxed"] + final["amount_tax"] != final["amount_total"] or final["amount_total"] < 0:
        raise ValueError("Tổng tiền Odoo chưa đối soát được; chưa lưu đề xuất.")
    return {**review, "pricing_version": 2, "company": company, "fiscal_position_id": header["fiscal_position_id"],
            "tax_definitions": definitions, "lines": lines, "gross": f"{baseline['amount_untaxed']:.2f}",
            "discount_amount": f"{baseline['amount_untaxed'] - final['amount_untaxed']:.2f}",
            "subtotal": f"{final['amount_untaxed']:.2f}", "tax": f"{final['amount_tax']:.2f}", "total": f"{final['amount_total']:.2f}",
            "rounding_adjustment": f"{final['amount_total'] - sum(Decimal(line['total']) for line in lines):.2f}",
            "policy": "Đối soát tính toán từ Odoo, chưa ghi báo giá. Tiền hàng và giảm giá hiển thị chưa thuế; thuế có thể gồm trong đơn giá theo cấu hình. Tổng chứng từ có thể khác tổng các dòng do làm tròn thuế."}
