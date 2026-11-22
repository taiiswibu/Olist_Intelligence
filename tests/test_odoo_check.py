from types import SimpleNamespace

import httpx
import pytest

from scripts import check_odoo as doctor


@pytest.fixture
def connection(monkeypatch):
    cfg = SimpleNamespace(odoo_url="http://127.0.0.1:8069", odoo_password="secret-test-only")
    monkeypatch.setattr(doctor, "settings", lambda: cfg)
    monkeypatch.setattr(doctor.httpx, "get", lambda *a, **kw: httpx.Response(200, request=httpx.Request("GET", a[0])))
    return cfg


def test_missing_password_stops_before_auth(connection, monkeypatch):
    connection.odoo_password = ""
    monkeypatch.setattr(doctor, "Odoo", lambda: pytest.fail("must not authenticate"))
    assert doctor.check_odoo()["stage"] == "configuration"


def test_network_failure_is_sanitized(connection, monkeypatch):
    def fail(*a, **kw):
        raise httpx.ConnectError("secret-test-only")
    monkeypatch.setattr(doctor.httpx, "get", fail)
    result = doctor.check_odoo()
    assert result["stage"] == "http" and not result["ok"]
    assert "secret-test-only" not in str(result)


@pytest.mark.parametrize("stage", ["authentication", "sales", "ready"])
def test_read_only_diagnostic_stages(connection, monkeypatch, stage):
    calls = []
    class FakeOdoo:
        def authenticate(self):
            if stage == "authentication":
                raise ValueError("secret-test-only")
        def call(self, model, method, args, kwargs):
            calls.append((model, method))
            assert method == "search_read"
            return [] if stage == "sales" else [{"name": "sale"}]
        def catalog(self):
            return {"partners": [1], "products": [2, 3]}
        def quotations(self):
            return []
    monkeypatch.setattr(doctor, "Odoo", FakeOdoo)
    result = doctor.check_odoo()
    assert result["stage"] == stage
    assert result["ok"] is (stage == "ready")
    assert "secret-test-only" not in str(result)
    if stage == "ready":
        assert result["demo_products_returned"] == 2


def test_nonlocal_url_not_requested(connection, monkeypatch):
    connection.odoo_url = "https://example.org"
    monkeypatch.setattr(doctor.httpx, "get", lambda *a, **kw: pytest.fail("nonlocal URL"))
    assert doctor.check_odoo()["stage"] == "configuration"
