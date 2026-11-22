from copy import deepcopy
from decimal import Decimal
import json

import pytest
from fastapi.testclient import TestClient

from olist import erp, sales
from olist.api import app


@pytest.fixture
def adapter(db, monkeypatch):
    class FakeOdoo:
        def __init__(self):
            self.calls = []
            self.orders = {}
            self.timeout_after_create = False
            self.quantity_digits = 2
            self.products = {pid: {"id": pid, "name": name, "default_code": f"OLIST-DEMO:{pid}",
                "list_price": 25, "currency_id": [31, "USD"], "uom_id": [1, "Units"], "type": "service",
                "categ_id": [1, "Services"], "description_sale": ""} for pid, name in [(20, "Dịch vụ A"), (21, "Dịch vụ B")]}

        def call(self, model, method, args=None, kwargs=None):
            self.calls.append((model, method, deepcopy(args), deepcopy(kwargs)))
            args, kwargs = args or [], kwargs or {}
            assert method in {"search", "search_read", "fields_get", "create"}
            if method == "create":
                assert model == "sale.order"
                values = args[0]
                lines = []
                for i, (_, _, line) in enumerate(values["order_line"]):
                    subtotal = sales.amount(Decimal(str(line["product_uom_qty"])) * Decimal(str(line["price_unit"])))
                    lines.append({"id": 100+i, "sequence": 10, "name": "Dịch vụ", "product_id": [line["product_id"], self.products[line["product_id"]]["name"]],
                        "product_uom_qty": line["product_uom_qty"], "price_unit": line["price_unit"], "discount": line["discount"], "tax_ids": [],
                        "price_subtotal": float(subtotal), "price_tax": 0, "price_total": float(subtotal)})
                self.orders[99] = {"id": 99, "name": "S00099", "origin": values["origin"], "partner_id": [values["partner_id"], "DEMO Khách"],
                    "state": "draft", "pricelist_id": [40, "OLIST DEMO BRL"], "currency_id": [30, "BRL"],
                    "amount_untaxed": sum(l["price_subtotal"] for l in lines), "amount_tax": 0,
                    "amount_total": sum(l["price_total"] for l in lines), "lines": lines}
                if self.timeout_after_create:
                    self.timeout_after_create = False
                    raise TimeoutError("do-not-expose-canary")
                return 99
            if model == "sale.order.line" and method == "fields_get":
                return {"product_uom_qty": {"digits": [16, self.quantity_digits]}}
            if model == "res.partner":
                assert ("ref", "=like", "OLIST-DEMO:%") in args[0]
                if any(t[0] == "id" and t[2] != 10 for t in args[0] if isinstance(t, tuple)):
                    return []
                return [{"id": 10, "name": "DEMO Khách", "ref": "OLIST-DEMO:10", "email": False, "phone": False, "city": "Demo"}]
            if model == "product.product":
                assert ("default_code", "=like", "OLIST-DEMO:%") in args[0]
                ids = next((t[2] for t in args[0] if isinstance(t, tuple) and t[0] == "id"), list(self.products))
                if isinstance(ids, int): ids = [ids]
                return [deepcopy(self.products[pid]) for pid in ids if pid in self.products]
            if model == "product.pricelist":
                return [{"id": 40, "name": "OLIST DEMO BRL", "currency_id": [30, "BRL"], "company_id": False}]
            if model == "res.currency":
                return [{"id": 30, "name": "BRL", "rounding": .01}]
            if model == "sale.order" and method == "search":
                return [oid for oid, order in self.orders.items() if order["origin"] == args[0][0][2]]
            if model == "sale.order" and method == "search_read":
                assert ("partner_id.ref", "=like", "OLIST-DEMO:%") in args[0]
                oid = args[0][0][2]
                return [{k: v for k, v in self.orders[oid].items() if k != "lines"}] if oid in self.orders else []
            if model == "sale.order.line":
                return deepcopy(self.orders[args[0][0][2]]["lines"])
            raise AssertionError((model, method))

    instance = FakeOdoo()
    monkeypatch.setattr(erp, "Odoo", lambda: instance)
    return instance


@pytest.fixture
def client(adapter):
    return TestClient(app, headers={"X-App-Token": "local-test-token"})


def payload():
    return {"partner_id": 10, "lines": [{"product_id": 20, "quantity": ".5", "unit_price": ".01"},
                                        {"product_id": 21, "quantity": "2", "unit_price": "12.35"}], "request_id": "a"*32}


def test_review_is_read_only_and_rounds_each_line_in_brl(client, adapter):
    body = payload();body.pop("request_id")
    response = client.post("/erp/quotation-preview", json=body)
    assert response.status_code == 200
    review = response.json()
    assert review["lines"][0]["subtotal"] == "0.01"
    assert review["total"] == "24.71" and review["tax"] == "0.00" and review["currency"] == "BRL"
    assert adapter.orders == {} and erp.list_actions() == []
    assert not any(method == "create" for _, method, _, _ in adapter.calls)


def test_pending_is_immutable_idempotent_and_approval_writes_once(client, adapter):
    first = client.post("/actions", json=payload()).json()
    assert first["state"] == "pending" and not adapter.orders
    calls_before = len(adapter.calls)
    assert client.post("/actions", json=payload()).json() == first
    assert len(adapter.calls) == calls_before
    altered = payload();altered["lines"][0]["quantity"] = 2
    assert client.post("/actions", json=altered).status_code == 422
    assert client.put("/actions/"+first["id"], json=altered).status_code == 405
    response = client.post(f"/actions/{first['id']}/approve")
    assert response.status_code == 200 and response.json()["verified"]
    assert response.json()["amount_total"] == 24.71
    assert client.post(f"/actions/{first['id']}/approve").status_code == 422
    assert len(adapter.orders) == 1
    details = client.get(f"/actions/{first['id']}").json()
    assert details["review"] == first["review"]
    assert [e["event"] for e in details["history"]] == ["action_proposed", "action_approving", "action_approved"]
    assert client.get("/erp/quotations/99").json()["lines"][1]["product_id"][0] == 21
    assert sum(method == "create" for _, method, _, _ in adapter.calls) == 1
    values = next(args[0] for _, method, args, _ in adapter.calls if method == "create")
    assert all(line[2]["tax_ids"] == [(6, 0, [])] and line[2]["discount"] == 0 for line in values["order_line"])


def test_timeout_after_odoo_create_recovers_same_origin_without_second_write(client, adapter):
    action = client.post("/actions", json=payload()).json()
    adapter.timeout_after_create = True
    assert client.post(f"/actions/{action['id']}/approve").status_code == 422
    assert len(adapter.orders) == 1
    recovered = client.post(f"/actions/{action['id']}/approve")
    assert recovered.status_code == 200 and recovered.json()["reused"] and recovered.json()["verified"]
    assert sum(method == "create" for _, method, _, _ in adapter.calls) == 1
    detail = client.get(f"/actions/{action['id']}").json()
    assert any(e["event"] == "action_failed" for e in detail["history"])
    assert "do-not-expose-canary" not in json.dumps(detail)


def test_changed_master_data_blocks_write_and_wrong_existing_order_is_not_reused(client, adapter):
    action = client.post("/actions", json=payload()).json()
    adapter.products[20]["name"] = "Đã đổi tên"
    assert client.post(f"/actions/{action['id']}/approve").status_code == 422
    assert adapter.orders == {}
    adapter.products[20]["name"] = "Dịch vụ A"
    adapter.timeout_after_create = True
    assert client.post(f"/actions/{action['id']}/approve").status_code == 422
    adapter.orders[99]["amount_total"] = 999
    assert client.post(f"/actions/{action['id']}/approve").status_code == 422
    assert erp.action_detail(action["id"])["state"] == "failed"
    adapter.orders[99]["amount_total"] = 24.71
    adapter.orders[99]["lines"][0]["price_unit"] = .0101
    assert client.post(f"/actions/{action['id']}/approve").status_code == 422
    assert sum(method == "create" for _, method, _, _ in adapter.calls) == 1


def test_rejection_and_live_precision_validation_do_not_write(client, adapter):
    adapter.quantity_digits = 0
    assert client.post("/actions", json=payload()).status_code == 422
    assert not erp.list_actions()
    adapter.quantity_digits = 2
    action = client.post("/actions", json=payload()).json()
    assert client.post(f"/actions/{action['id']}/reject").status_code == 200
    history = client.get(f"/actions/{action['id']}").json()["history"]
    assert [e["event"] for e in history] == ["action_proposed", "action_rejected"]
    assert client.post(f"/actions/{action['id']}/approve").status_code == 422
    assert not adapter.orders


@pytest.mark.parametrize("change", [
    {"lines": []}, {"lines": [{"product_id": 20, "quantity": 1, "unit_price": "1.001"}]},
    {"lines": [{"product_id": 20, "quantity": ".333", "unit_price": "1"}]},
    {"lines": [{"product_id": 20, "quantity": "NaN", "unit_price": 1}]},
    {"lines": [{"product_id": 999, "quantity": 1, "unit_price": 1}]},
    {"lines": [{"product_id": 20, "quantity": 1, "unit_price": 1, "tax_method": "arbitrary"}]},
    {"partner_id": 999}, {"method": "action_confirm"},
])
def test_invalid_payload_or_non_demo_id_has_no_side_effect(client, adapter, change):
    body = {**payload(), **change}
    assert client.post("/actions", json=body).status_code == 422
    assert not adapter.orders and erp.list_actions() == []


def test_search_is_scoped_paginated_and_protected(client, adapter):
    result = client.get("/erp/search/products", params={"q": "dịch", "limit": 1}).json()
    assert len(result["rows"]) == 1 and result["has_more"]
    domain = adapter.calls[-1][2][0]
    assert ("default_code", "=like", "OLIST-DEMO:%") in domain and "|" in domain
    assert client.get("/erp/search/products?limit=501").status_code == 422
    assert client.get("/erp/records/products/20").json()["currency_id"][1] == "USD"
    assert client.get("/erp/records/products/999").status_code == 422
    assert TestClient(app).get("/erp/search/partners").status_code == 401
    cookie = TestClient(app);cookie.post("/session", json={"key": "local-test-token"})
    assert cookie.post("/actions", json=payload()).status_code == 403
