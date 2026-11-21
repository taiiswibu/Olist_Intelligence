import json
import pytest
from fastapi.testclient import TestClient
from olist.api import app
from olist import erp
from olist.database import operational


@pytest.fixture
def client(db):
    return TestClient(app, headers={"X-App-Token":"local-test-token"})


def test_api_rejects_missing_auth(client):
    r = client.get("/status", headers={"X-App-Token":"wrong"})
    assert r.status_code == 401
    assert client.get("/health").status_code == 200


def test_api_kpi_and_agent_roundtrip(client):
    assert client.get("/analytics/kpis").json()["values"]["product_gmv"] == 70
    r = client.post("/agent/chat", json={"question":"Tổng quan KPI năm 2018"})
    assert r.status_code == 200
    assert r.json()["tool"] == "kpis"
    assert client.get("/analytics/unknown").status_code == 422


def test_no_sql_or_shell_endpoint(client):
    assert client.post("/sql", json={"sql":"DROP TABLE order_fact"}).status_code == 404
    assert client.get("/analytics/kpis").json()["values"]["orders"] == 3


def test_action_requires_approval_and_is_exactly_once_in_process(client, monkeypatch):
    calls = []
    class FakeOdoo:
        def quotation(self, payload, origin):
            calls.append((payload, origin))
            return {"odoo_id":123, "state":"draft"}
    monkeypatch.setattr(erp, "Odoo", FakeOdoo)
    body = {"partner_id":1,"product_id":2,"quantity":3,"unit_price":10}
    r = client.post("/actions", json=body)
    assert r.status_code == 200 and calls == []
    aid = r.json()["id"]
    assert client.post(f"/actions/{aid}/approve").status_code == 200
    assert len(calls) == 1
    assert client.post(f"/actions/{aid}/approve").status_code == 422
    assert len(calls) == 1


def test_action_failure_can_retry_same_origin(client, monkeypatch):
    calls = []
    class FakeOdoo:
        def quotation(self, payload, origin):
            calls.append(origin)
            if len(calls)==1:
                raise TimeoutError("simulated timeout")
            return {"odoo_id":123}
    monkeypatch.setattr(erp, "Odoo", FakeOdoo)
    aid = client.post("/actions", json={"partner_id":1,"product_id":2,"quantity":1,"unit_price":10}).json()["id"]
    assert client.post(f"/actions/{aid}/approve").status_code == 422
    assert client.post(f"/actions/{aid}/approve").status_code == 200
    assert calls[0] == calls[1]


def test_rejected_action_cannot_be_approved(client):
    aid = client.post("/actions", json={"partner_id":1,"product_id":2,"quantity":1,"unit_price":10}).json()["id"]
    assert client.post(f"/actions/{aid}/reject").status_code == 200
    assert client.post(f"/actions/{aid}/approve").status_code == 422


def test_invalid_payload_no_side_effect(client):
    r = client.post("/actions", json={"partner_id":1,"product_id":2,"quantity":-1,"unit_price":10,"method":"action_confirm"})
    assert r.status_code == 422
    assert client.get("/actions").json() == []


def test_ml_no_outcome_columns():
    from olist.ml import FEATURES
    assert not set(FEATURES) & {"actual_delivery", "actual_delivery_days", "is_late", "review_score", "review_count", "order_status"}
