import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage

from olist import followup_grounding as g, followup_privacy as p, followups as f
from test_followups import payload, bridge


def draft_case(state="draft", existing=False):
    case = p.CloudCase(case_id="CASE_0123456789abcdef", quotation_state=state,
        reason_codes=["waiting"] if existing else ["no_activity"], has_activity=existing,
        allowed_actions=["review_existing_activity" if existing else "review_quotation" if state == "draft" else "request_feedback"])
    return f.rules_draft([case]), case


@pytest.mark.parametrize("state,existing,field,text,code", [
    ("draft", False, "note", "Báo giá đã gửi nhưng chưa có phản hồi.", "unsupported_draft_send_history"),
    ("draft", False, "note", "Kiểm tra nội dung và gửi lại cho khách.", "unsupported_draft_send_history"),
    ("sent", False, "explanation", "Báo giá đã được gửi, chưa nhận phản hồi và sắp hết hạn.", "unknown_feedback_history"),
    ("sent", False, "summary", "Khách hàng vẫn chưa trả lời", "unknown_feedback_history"),
    ("sent", False, "explanation", "Đã nhận được phản hồi của khách.", "unknown_feedback_history"),
    ("draft", True, "note", "Kiểm tra lại các hoạt động đã thực hiện.", "unknown_activity_completion"),
    ("draft", True, "explanation", "Đã có lịch việc tương tự, cần rà soát lại.", "unknown_activity_similarity"),
    ("draft", True, "note", "Kiểm tra báo giá, cập nhật thông tin khách và điều kiện hợp đồng.", "existing_activity_review_missing"),
    ("draft", True, "note", "Xin chào quý khách, xin gửi lại thông tin báo giá quá hạn.", "existing_activity_review_missing"),
])
def test_observed_unsupported_claims_are_rejected(state, existing, field, text, code):
    for spelling in [text, g.normalize(text), text.upper(), text.replace(" ", "\u200b ")]:
        draft, case = draft_case(state, existing)
        setattr(draft.items[0], field, spelling)
        audit = g.audit(draft, [case])
        assert audit["status"] == "rejected"
        assert code in audit["findings"][0]["codes"]
        assert spelling not in str(audit)  # Diagnostics contain codes, not source prose.


@pytest.mark.parametrize("state,existing,note", [
    ("draft", False, "Kiểm tra nội dung trước khi chuẩn bị gửi cho khách."),
    ("sent", False, "Anh chị có thể phản hồi về báo giá đã gửi không?"),
    ("sent", False, "Xin hỏi anh chị đã nhận được báo giá chưa?"),
    ("sent", True, "Xem lại công việc đang hẹn để tránh tạo việc tương tự."),
    ("draft", True, "Đối chiếu hoạt động hiện có trước khi chuẩn bị liên hệ."),
])
def test_questions_and_supported_next_steps_remain_available(state, existing, note):
    draft, case = draft_case(state, existing)
    draft.items[0].note = note
    assert not g.issues(draft, [case])


@pytest.mark.parametrize("strategy", ["groq", "gemini", "pipeline"])
def test_known_fabrication_cannot_reach_user_or_second_model(monkeypatch, strategy):
    calls = []
    class Model:
        def __init__(self, provider, *args, **kwargs): self.provider = provider
        async def ainvoke(self, messages):
            calls.append(self.provider.name)
            case = p.CloudCase.model_validate(json.loads(messages[-1].content)["cases"][0])
            draft = f.rules_draft([case])
            draft.items[0].note = "Báo giá đã gửi nhưng chưa có phản hồi."
            return AIMessage(content=draft.model_dump_json())
    monkeypatch.setattr(f, "TeamModel", Model)
    monkeypatch.setattr(f.llm, "providers", lambda: [SimpleNamespace(name=s, model="fixture", key="") for s in ["groq", "gemini"]])
    with pytest.raises(f.AnalysisFailure) as caught:
        asyncio.run(f.analyze_strategy(f.AnalysisRequest.model_validate(payload()), strategy))
    assert caught.value.reason == "GroundingRejected"
    assert calls == ["gemini" if strategy == "gemini" else "groq"]
    trace = caught.value.trace
    assert trace[0]["status"] == "rejected" and trace[0]["grounding"]["status"] == "rejected"
    assert trace[0]["grounding"]["version"] == g.VERSION


@pytest.mark.parametrize("status,kind", [(401, "request_rejected"), (429, "rate_limited"), (503, "provider_error")])
def test_http_diagnostics_preserve_status_without_provider_secrets(monkeypatch, status, kind):
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(status, json={"error": "SECRET_PROVIDER_RESPONSE"}, headers={"X-Private": "SECRET_HEADER"})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handle), **kw))
    monkeypatch.setattr(f.llm, "providers", lambda: [SimpleNamespace(name="groq", model="fixture", key="SECRET_KEY", base="https://example.invalid")])
    with pytest.raises(f.AnalysisFailure) as caught:
        asyncio.run(f.analyze_strategy(f.AnalysisRequest.model_validate(payload()), "groq",
            request_policy=f.transport.Policy(max_attempts=1, min_interval_seconds=0)))
    trace = caught.value.trace
    assert caught.value.reason == "HTTPStatusError"
    assert len(seen) == 1  # No hidden retry.
    assert trace[0]["http_status"] == status and trace[0]["failure_kind"] == kind
    assert trace[0]["privacy"]["requests_checked"] == 1
    assert "SECRET" not in str(trace) and "https://" not in str(trace)


def test_fixed_templates_pass_all_development_scenarios():
    from olist.followup_evaluation import load_cases
    _, cases = load_cases("dev")
    for fixture in cases:
        source = f.AnalysisRequest.model_validate(fixture["payload"])
        cloud, _ = p.project(source, f.facts)
        assert not g.issues(f.rules_draft(cloud), cloud)


def test_job_reports_http_status_without_exception_message(bridge, monkeypatch):
    async def fail(source):
        raise f.AnalysisFailure([{"provider": "groq", "http_status": 429, "failure_kind": "rate_limited"}], "HTTPStatusError") from RuntimeError("SECRET_PROVIDER_BODY")
    monkeypatch.setattr(f, "analyze", fail)
    bridge.post("/odoo-ai/analyses", json=payload())
    result = bridge.get("/odoo-ai/analyses/" + "a"*32, params={"database": "odoo-test", "user_id": 11, "company_id": 2}).json()
    assert result["state"] == "failed" and "HTTP 429" in result["error"]
    assert "SECRET" not in json.dumps(result)
