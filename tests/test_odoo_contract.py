import pytest
from olist.erp import Odoo


def fake_adapter(monkeypatch):
    monkeypatch.setenv("ODOO_PASSWORD", "test-secret")
    monkeypatch.setenv("ODOO_URL", "http://127.0.0.1:8069")
    odoo = Odoo()
    odoo.uid = 1
    return odoo


def test_quotation_draft_has_currency_tax_and_origin(monkeypatch):
    odoo = fake_adapter(monkeypatch)
    calls = []
    def call(model, method, args=None, kwargs=None):
        calls.append((model, method, args))
        if (model,method)==("sale.order","search"): return []
        if (model,method)==("res.partner","search"): return [10]
        if (model,method)==("product.product","search"): return [20]
        if (model,method)==("res.currency","search"): return [30]
        if (model,method)==("product.pricelist","search"): return [40]
        return 50
    monkeypatch.setattr(odoo, "call", call)
    r = odoo.quotation({"partner_id":10,"product_id":20,"quantity":2,"unit_price":12.5}, "OLIST-ACTION:abc")
    assert r["state"] == "draft"
    values = next(a[0] for m,op,a in calls if (m,op)==("sale.order","create"))
    assert values["pricelist_id"] == 40
    assert values["origin"] == "OLIST-ACTION:abc"
    assert values["order_line"][0][2]["tax_ids"] == [(6,0,[])]
    assert not any("confirm" in op for m,op,a in calls)


def test_non_demo_record_is_rejected(monkeypatch):
    odoo = fake_adapter(monkeypatch)
    monkeypatch.setattr(odoo, "call", lambda *a, **k: [])
    with pytest.raises(ValueError, match="demo"):
        odoo.quotation({"partner_id":10,"product_id":20,"quantity":2,"unit_price":12.5}, "OLIST-ACTION:abc")


def test_origin_recovery_does_not_create_second_order(monkeypatch):
    odoo = fake_adapter(monkeypatch)
    calls = []
    def call(model, method, *args, **kwargs):
        calls.append((model,method))
        return [99]
    monkeypatch.setattr(odoo, "call", call)
    assert odoo.quotation({}, "OLIST-ACTION:abc")["reused"]
    assert calls == [("sale.order","search")]


def test_seed_freight_is_valid_product_line(monkeypatch, db):
    from scripts import seed_odoo
    calls = []
    class Adapter:
        def call(self, model, method, args=None, kwargs=None):
            calls.append((model,method,args))
            return [] if method=="search" else 123
        def brl_pricelist(self): return 40
    monkeypatch.setattr(seed_odoo,"Odoo",Adapter)
    seed_odoo.seed(1)
    values = next(a[0] for m,op,a in calls if (m,op)==("sale.order","create"))
    assert len(values["order_line"])==4
    assert all(line[2]["product_id"] for line in values["order_line"])
    assert sum(line[2]["price_unit"] for line in values["order_line"])==35
