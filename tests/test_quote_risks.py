import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from olist import followups as f, quote_risks as risk, followup_transport as transport
from test_followups import bridge, payload, scope
from test_followup_privacy import sensitive_payload


def risk_payload():
    return {**sensitive_payload(), "purpose": "risk", "risk_codes": ["expired", "missing_tax"]}


def model_transport(monkeypatch, mutate=None, approved=True):
    requests = []
    def handle(request):
        body = json.loads(request.content)
        canaries = ["PERSON_PRIVATE_CANARY", "SECRET_QUOTE_CANARY", "837251.46", "client_omega@example.invalid",
                    "+84 900 765 432", "SECRET_ADDRESS_CANARY", "SUMMARY_PRIVATE_CANARY", "2026-11-21", "odoo-test"]
        assert not any(c in request.content.decode() for c in canaries)
        envelope = risk.RiskInput.model_validate_json(body["messages"][1]["content"])
        assert set(json.loads(body["messages"][1]["content"])) <= {"case_id", "risk_codes", "draft"}
        requests.append(body)
        if envelope.draft is None:
            result = {"items": [{"code": code, "question": risk.CATALOG[code]["question"]} for code in envelope.risk_codes]}
            if mutate: mutate(result)
        else:
            result = {"valid": approved, "findings": []}
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": json.dumps(result)}, "finish_reason": "stop"}]})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(f.llm, "providers", lambda: [SimpleNamespace(name=n, model=n+"-fixture", key="fixture", base="https://example.invalid") for n in ("groq", "gemini")])
    monkeypatch.setattr(transport, "configured_policy", lambda: transport.Policy(1, 0))
    monkeypatch.setenv("FOLLOWUP_AI_MODE", "cloud_minimized")
    return requests


def test_risk_pipeline_checks_actual_wire_to_both_providers(monkeypatch):
    requests = model_transport(monkeypatch)
    result = asyncio.run(f.analyze(f.AnalysisRequest.model_validate(risk_payload())))
    assert result["purpose"] == "risk" and result["strategy"] == "pipeline"
    assert len(requests) == 2 and len(result["items"]) == 2
    assert all(t["privacy"] == {"version": risk.PRIVACY_VERSION, "requests_checked": 1} for t in result["trace"])
    assert json.loads(requests[0]["messages"][1]["content"])["risk_codes"] == ["expired", "missing_tax"]
    assert json.loads(requests[1]["messages"][1]["content"])["draft"]["items"] == result["items"]


@pytest.mark.parametrize("change", [
    {"risk_codes": ["unknown"]}, {"risk_codes": ["expired", "expired"]},
    {"purpose": "followup"}, {"orders": payload()["orders"]*2},
])
def test_request_rejects_wrong_scope_and_unapproved_codes(change):
    with pytest.raises(ValueError): f.AnalysisRequest.model_validate({**risk_payload(), **change})


def test_wire_guard_rejects_customer_fields_and_changed_messages():
    source = {"case_id": "CASE_"+"a"*16, "risk_codes": ["expired"]}
    for change in [{"name": "Private"}, {"risk_codes": ["private@example.invalid"]}, {"case_id": "CUSTOMER_123"}]:
        with pytest.raises(ValueError): risk.RiskInput.model_validate({**source, **change})
    messages = [SystemMessage(content="Fixed instructions"), HumanMessage(content=json.dumps(source))]
    guard = risk.wire_guard(messages)
    wire = {"model": "fixture", "messages": [{"role": "system", "content": messages[0].content}, {"role": "user", "content": messages[1].content}]}
    guard(wire)
    for change in [{"tools": []}, {"customer": "Secret"}]:
        with pytest.raises(ValueError): guard({**wire, **change})
    changed = deepcopy(wire); changed["messages"][0]["content"] += " altered"
    with pytest.raises(ValueError): guard(changed)


@pytest.mark.parametrize("bad", ["number", "contact", "assertion", "two_sentences", "missing", "duplicate", "unknown"])
def test_invalid_advice_blocked_before_reviewer(monkeypatch, bad):
    def mutate(result):
        item = result["items"][0]
        if bad == "number": item["question"] = "Có giảm thêm 50% không?"
        elif bad == "contact": item["question"] = "Có gửi tới private@example.invalid không?"
        elif bad == "assertion": item["question"] = "Khách đã đồng ý"
        elif bad == "two_sentences": item["question"] = "Khách đã đồng ý. Có cần kiểm tra không?"
        elif bad == "missing": result["items"].pop()
        elif bad == "duplicate": result["items"][1] = item.copy()
        else: item["code"] = "made_up_history"
    requests = model_transport(monkeypatch, mutate)
    with pytest.raises(ValueError): asyncio.run(f.analyze(f.AnalysisRequest.model_validate(risk_payload())))
    assert len(requests) == 1


def test_reviewer_rejection_is_failure_without_content_retry(monkeypatch):
    requests = model_transport(monkeypatch, approved=False)
    with pytest.raises(f.AnalysisFailure, match="ReviewRejected"):
        asyncio.run(f.analyze(f.AnalysisRequest.model_validate(risk_payload())))
    assert len(requests) == 2


@pytest.mark.parametrize("change,global_mode", [({}, "rules_only"), ({"mode": "rules_only"}, "cloud_minimized"), ({"risk_codes": []}, "cloud_minimized")])
def test_local_and_empty_results_need_no_provider_or_network(monkeypatch, change, global_mode):
    monkeypatch.setenv("FOLLOWUP_AI_MODE", global_mode)
    monkeypatch.setattr(f.llm, "providers", lambda: [])
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("Local risk review must not open model network"))
    source = f.AnalysisRequest.model_validate({**risk_payload(), **change})
    result = asyncio.run(f.analyze(source))
    assert result["strategy"] == "rules" and result["trace"] == []
    assert len(result["items"]) == len(source.risk_codes)
    risk.validate_advice(risk.Advice.model_validate({"items": result["items"]}), source.risk_codes)


def test_risk_bridge_idempotency_tenant_binding_and_snapshot_removal(bridge, monkeypatch):
    monkeypatch.setenv("FOLLOWUP_AI_MODE", "rules_only")
    source = risk_payload()
    assert bridge.post("/odoo-ai/analyses", json=source).status_code == 200
    url = "/odoo-ai/analyses/"+source["request_id"]
    result = bridge.get(url, params=scope()).json()
    assert result["state"] == "complete" and result["purpose"] == "risk"
    assert bridge.post("/odoo-ai/analyses", json=source).json() == result
    for changed in [{"user_id": 12}, {"company_id": 3}, {"database": "other"}]:
        assert bridge.get(url, params={**scope(), **changed}).status_code == 404
    assert bridge.post("/odoo-ai/analyses", json=payload()).status_code == 422
    assert bridge.post("/odoo-ai/analyses", json={**source, "risk_codes": ["expired"]}).status_code == 422
    with f._connection() as conn:
        row = conn.execute("SELECT payload FROM odoo_ai_jobs WHERE request_id=?", (source["request_id"],)).fetchone()
        assert row["payload"] == ""
