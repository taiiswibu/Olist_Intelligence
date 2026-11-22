from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

import pytest

from test_sales import adapter, client
from olist import erp


@pytest.fixture
def financial(adapter):
    original = adapter.call
    adapter.uid = 1
    adapter.adjust_input = False
    adapter.tax_config = {}
    for tid, rate, included, usage, company, active in [(101, 10, False, "sale", 1, True), (102, 20, True, "sale", 1, True),
            (103, 10, False, "purchase", 1, True), (104, 10, False, "sale", 2, True),
            (105, 10, False, "sale", 1, False), (106, 5, False, "none", 1, True)]:
        adapter.tax_config[tid] = {"id": tid, "name": f"Tax {tid}", "amount": rate, "amount_type": "percent", "type_tax_use": usage,
            "active": active, "company_id": [company, "Company"], "price_include": included, "include_base_amount": False,
            "is_base_affected": True, "sequence": tid, "children_tax_ids": [], "tax_scope": False, "country_id": [1, "Country"],
            "fiscal_position_ids": [10], "write_date": "2026-11-22 00:00:00"}

    def rounded(value):
        return value.quantize(Decimal(".01"), rounding=ROUND_HALF_UP)

    def expanded(ids):
        result = []
        for tid in ids:
            tax = adapter.tax_config[tid]
            result.extend(expanded(tax["children_tax_ids"]) if tax["amount_type"] == "group" else [tax])
        return result

    def calc(values):
        taxes = expanded(values["tax_ids"][0][2])
        net = Decimal(str(values["price_unit"])) * Decimal(str(values["product_uom_qty"])) * (1-Decimal(str(values["discount"]))/100)
        included = sum((Decimal(str(t["amount"]))/100 for t in taxes if t["price_include"]), Decimal(0))
        base = net/(1+included)
        tax_amounts = {t["id"]: base*Decimal(str(t["amount"]))/100 for t in taxes}
        total = base+sum(tax_amounts.values())
        row = {"product_id": values["product_id"], "product_uom_qty": values["product_uom_qty"], "price_unit": values["price_unit"],
            "discount": values["discount"], "tax_ids": [[4, tid, {"id": tid}] for tid in values["tax_ids"][0][2]],
            "price_subtotal": float(rounded(base)), "price_total": float(rounded(total)), "price_tax": float(rounded(total)-rounded(base))}
        return row, base, tax_amounts

    def total(commands):
        base = Decimal(0); groups = {}
        for command in commands:
            _, raw_base, tax_amounts = calc(command[2]);base += raw_base
            for tid, value in tax_amounts.items():groups[tid] = groups.get(tid, Decimal(0))+value
        base = rounded(base);tax = sum((rounded(v) for v in groups.values()), Decimal(0))
        return {"amount_untaxed": float(base), "amount_tax": float(tax), "amount_total": float(base+tax)}

    def call(model, method, args=None, kwargs=None):
        args, kwargs = args or [], kwargs or {}
        if model in {"res.users", "res.company", "account.tax"} or method == "onchange":
            adapter.calls.append((model, method, deepcopy(args), deepcopy(kwargs)))
        if model == "res.users":return [{"id": 1, "company_id": [1, "Company"]}]
        if model == "res.company":return [{"id": 1, "name": "Company", "currency_id": [31, "USD"],
                "tax_calculation_rounding_method": "round_globally", "account_fiscal_country_id": [1, "Country"], "domestic_fiscal_position_id": [10, "Domestic"]}]
        if model == "account.tax":
            rows = list(adapter.tax_config.values())
            for key, op, value in args[0]:
                if op == "in":rows = [r for r in rows if r[key] in value]
                elif op == "=":rows = [r for r in rows if (r[key][0] if key == "company_id" else r[key]) == value]
            return deepcopy(rows)
        if method == "onchange":
            assert args[0] == []  # New in-memory records; never an existing order or persisted preview.
            values = args[1]
            if model == "sale.order.line":
                row = calc(values)[0]
                if adapter.adjust_input:row["discount"] = 99
                return {"value": row}
            if "order_line" not in values:return {"value": {**values, "fiscal_position_id": False, "tax_country_id": 1}}
            return {"value": total(values["order_line"])}
        if model == "sale.order" and method == "create":
            try:
                return original(model, method, args, kwargs)
            finally:
                if 99 in adapter.orders:
                    order = adapter.orders[99];values=args[0]
                    order.update(total(values["order_line"]), company_id=[values["company_id"], "Company"], fiscal_position_id=False)
                    for row, command in zip(order["lines"], values["order_line"]):
                        native = calc(command[2])[0]
                        row.update({key: native[key] for key in ["discount", "price_subtotal", "price_tax", "price_total"]})
                        row["tax_ids"] = list(command[2]["tax_ids"][0][2])
        return original(model, method, args, kwargs)

    adapter.call = call
    return adapter


def body(discount="10", taxes=None, price="100", quantity="1"):
    return {"partner_id": 10, "lines": [{"product_id": 20, "quantity": quantity, "unit_price": price,
            "discount": discount, "tax_ids": taxes if taxes is not None else [101]}], "request_id": "b"*32}


@pytest.mark.parametrize("tax_ids,price,expected", [([101], "100", ("100.00", "10.00", "90.00", "9.00", "99.00")),
    ([102], "120", ("100.00", "10.00", "90.00", "18.00", "108.00")),
    ([], "100", ("100.00", "10.00", "90.00", "0.00", "90.00"))])
def test_native_calculation_preview_and_verified_write(client, financial, tax_ids, price, expected):
    payload = body(taxes=tax_ids, price=price)
    response = client.post("/erp/quotation-preview", json={k:v for k,v in payload.items() if k!='request_id'})
    assert response.status_code == 200, response.text
    review = response.json()
    assert tuple(review[key] for key in ["gross", "discount_amount", "subtotal", "tax", "total"]) == expected
    assert not financial.orders and erp.list_actions() == []
    action = client.post("/actions", json=payload).json()
    approved = client.post(f"/actions/{action['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["verified"] and approved.json()["amount_total"] == float(expected[-1])
    order = client.get("/erp/quotations/99").json()
    assert order["lines"][0]["discount"] == 10 and order["lines"][0]["tax_ids"] == tax_ids
    assert all(method not in {"action_confirm", "_create_invoices", "write"} for _,method,_,_ in financial.calls)


def test_global_rounding_uses_document_result_not_sum_of_line_tax(client, financial):
    payload = body(discount="0", price=".03")
    payload["lines"] *= 3
    action = client.post("/actions", json=payload).json()
    review = action["review"]
    assert review["subtotal"] == "0.09" and review["tax"] == "0.01" and review["total"] == "0.10"
    assert sum(Decimal(line["tax"]) for line in review["lines"]) == 0
    assert review["rounding_adjustment"] == "0.01"
    assert client.post(f"/actions/{action['id']}/approve").json()["verified"]


def test_tax_change_blocks_write_and_timeout_recovery_preserves_discount_taxes(client, financial):
    action = client.post("/actions", json=body()).json()
    financial.tax_config[101]["amount"] = 11
    assert client.post(f"/actions/{action['id']}/approve").status_code == 422
    assert not financial.orders
    financial.tax_config[101]["amount"] = 10
    financial.timeout_after_create = True
    assert client.post(f"/actions/{action['id']}/approve").status_code == 422
    recovered = client.post(f"/actions/{action['id']}/approve")
    assert recovered.status_code == 200 and recovered.json()["reused"] and recovered.json()["verified"]
    assert sum(method == "create" for _,method,_,_ in financial.calls)==1


def test_group_tax_captures_child_settings_and_invalid_native_input_is_rejected(client, financial):
    financial.tax_config[110] = {**financial.tax_config[101], "id":110,"name":"Group", "amount_type":"group", "children_tax_ids":[106]}
    action = client.post("/actions", json=body(taxes=[110])).json()
    assert {t['id'] for t in action['review']['tax_definitions']}=={106,110}
    financial.tax_config[106]['write_date']='2026-11-23 00:00:00'
    assert client.post(f"/actions/{action['id']}/approve").status_code==422
    assert not financial.orders
    financial.adjust_input=True
    assert client.post('/erp/quotation-preview',json={k:v for k,v in body().items() if k!='request_id'}).status_code==422


@pytest.mark.parametrize("changes", [{"discount":"100.001"},{"discount":"-1"},{"discount":"NaN"},
    {"tax_ids":[101,101]},{"tax_ids":[99]},{"tax_ids":[103]},{"tax_ids":[104]},{"tax_ids":[105]}])
def test_invalid_discount_or_unavailable_tax_creates_no_proposal(client, financial, changes):
    payload=body();payload['lines'][0].update(changes)
    assert client.post('/actions',json=payload).status_code==422
    assert not financial.orders and erp.list_actions()==[]


def test_catalog_only_lists_active_company_sales_taxes_and_idempotency_includes_discount(client, financial):
    catalog=client.get('/erp/sales/taxes').json()
    assert {t['id'] for t in catalog['rows']}=={101,102}
    action=client.post('/actions',json=body()).json()
    assert client.post('/actions',json=body()).json()==action
    assert client.post('/actions',json=body(discount='11')).status_code==422
    plain={'partner_id':10,'lines':[{'product_id':20,'quantity':1,'unit_price':1}],'request_id':'c'*32}
    old=client.post('/actions',json=plain).json()
    plain['lines'][0].update(discount='0.00',tax_ids=[])
    assert client.post('/actions',json=plain).json()==old
