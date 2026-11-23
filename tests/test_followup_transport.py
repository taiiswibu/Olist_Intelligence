import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage

from olist import followups as f, followup_transport as t, followup_evaluation as e, followup_privacy as p
from test_followup_privacy import sensitive_payload
from test_followups import payload


@pytest.fixture
def virtual_time(monkeypatch):
    clock = [1000.0]
    waits = []
    async def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(t, "now", lambda: clock[0])
    monkeypatch.setattr(t, "sleep", sleep)
    return waits


def install(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(f.llm, "providers", lambda: [SimpleNamespace(name=name, model="fixture", key="SECRET_KEY", base="https://example.invalid/"+name) for name in ("groq", "gemini")])


def success(body):
    envelope = p.CloudInput.model_validate_json(body["messages"][1]["content"])
    result = {"valid": True, "findings": []} if envelope.draft else f.rules_draft(envelope.cases).model_dump()
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})


def test_both_stages_retry_transient_failure_with_same_minimized_http_body(monkeypatch, virtual_time):
    bodies, attempts = [], {}
    def handle(request):
        body = json.loads(request.content)
        assert not any(s in request.content.decode() for s in ("PERSON_PRIVATE_CANARY", "SECRET_QUOTE_CANARY", "837251.46", "client_omega@example.invalid"))
        key = request.url.path
        attempts[key] = attempts.get(key, 0) + 1
        bodies.append(body)
        if attempts[key] == 1:
            return httpx.Response(503, headers={"Retry-After": "2", "X-Private": "SECRET_HEADER"}, json={"error": "SECRET_BODY"})
        return success(body)
    install(monkeypatch, handle)
    result = asyncio.run(f.analyze_strategy(f.AnalysisRequest.model_validate(sensitive_payload()), "pipeline", request_policy=t.Policy(2, 0)))
    assert len(bodies) == 4 and bodies[0] == bodies[1] and bodies[2] == bodies[3]
    assert virtual_time == [2, 2]
    assert [x["attempt"] for x in result["trace"]] == [1, 2, 1, 2]
    assert [x["status"] for x in result["trace"]] == ["failed", "done", "failed", "done"]
    assert all(x["privacy"]["requests_checked"] == 1 for x in result["trace"])
    assert "SECRET" not in str(result)


@pytest.mark.parametrize("status,attempts", [(400, 1), (401, 1), (403, 1), (429, 3), (503, 3)])
def test_retry_count_is_bounded_and_client_errors_are_not_retried(monkeypatch, virtual_time, status, attempts):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, headers={"Retry-After": "1"})
    install(monkeypatch, handle)
    with pytest.raises(f.AnalysisFailure) as caught:
        asyncio.run(f.analyze_strategy(f.AnalysisRequest.model_validate(payload()), "groq", request_policy=t.Policy(3, 0)))
    assert len(calls) == len(caught.value.trace) == attempts
    assert caught.value.trace[-1]["retry_scheduled"] is False


def test_long_retry_after_defers_other_jobs_without_sending_or_waiting_forever(monkeypatch, virtual_time):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "3600"})
    install(monkeypatch, handle)
    async def run():
        errors = []
        for _ in range(2):
            try:
                await f.analyze_strategy(f.AnalysisRequest.model_validate(payload()), "groq", request_policy=t.Policy(2, 0))
            except f.AnalysisFailure as exc: errors.append(exc)
        return errors
    first, second = asyncio.run(run())
    assert len(calls) == 1 and virtual_time == []
    assert first.trace[0]["retry_after_seconds"] == 3600 and not first.trace[0]["retry_scheduled"]
    assert second.reason == "ProviderCooldown" and second.trace[0]["privacy"]["requests_checked"] == 0
    record = {"strategy": "groq", "completed": False, "contract_pass": False, "elapsed_ms": 0,
              "trace": second.trace, "error": second.reason, "estimated_cost": None}
    assert e.summarize([record])["groq"]["model_calls"] == 0


def test_same_provider_is_serialized_and_respects_spacing(monkeypatch, virtual_time):
    source = SimpleNamespace(name="groq", model="fixture", base="test")
    starts = []
    async def call():
        async with t.scheduled(source, t.Policy(1, 5)):
            starts.append(t.now())
            await asyncio.sleep(0)
    async def run(): await asyncio.gather(call(), call(), call())
    asyncio.run(run())
    assert starts == [1000, 1005, 1010]
    assert virtual_time == [5, 5]


def test_cancelled_waiter_does_not_poison_provider_lock():
    source = SimpleNamespace(name="groq", model="fixture", base="test")
    policy = t.Policy(1, 0)
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def hold():
            async with t.scheduled(source, policy):
                entered.set(); await release.wait()
        async def waiter():
            async with t.scheduled(source, policy): pass
        first = asyncio.create_task(hold()); await entered.wait()
        second = asyncio.create_task(waiter()); await asyncio.sleep(0)
        second.cancel()
        with pytest.raises(asyncio.CancelledError): await second
        release.set(); await first
        await asyncio.wait_for(waiter(), .5)
    asyncio.run(run())


def test_analysis_deadline_preserves_interrupted_attempt_trace(monkeypatch):
    from contextlib import asynccontextmanager
    original = asyncio.timeout
    @asynccontextmanager
    async def quick_timeout(seconds):
        async with original(.01): yield
    class SlowModel:
        def __init__(self, *args, **kw): pass
        async def ainvoke(self, messages): await asyncio.sleep(10)
    monkeypatch.setattr(f.asyncio, "timeout", quick_timeout)
    monkeypatch.setattr(f, "TeamModel", SlowModel)
    monkeypatch.setattr(f.llm, "providers", lambda: [SimpleNamespace(name="groq", model="fixture", key="", base="test")])
    with pytest.raises(f.AnalysisFailure) as caught:
        asyncio.run(f.analyze_strategy(f.AnalysisRequest.model_validate(payload()), "groq"))
    assert caught.value.reason == "AnalysisDeadlineExceeded"
    assert len(caught.value.trace) == 1 and caught.value.trace[0]["status"] == "interrupted"


def test_retries_require_budget_before_any_model_call(tmp_path):
    with pytest.raises(ValueError, match="vượt"):
        asyncio.run(e.run(tmp_path / "budget", ("pipeline",), limit=1, live=True, max_model_calls=2, request_policy=t.Policy(2, 0)))
    assert not (tmp_path / "budget").exists()


@pytest.mark.parametrize("value", ["not-a-delay", "nan", "inf", "-1", ""])
def test_untrusted_retry_after_cannot_disable_bounds(value):
    assert 1 <= t.retry_delay({"retry-after": value}, 1) <= 2


def test_retry_after_http_date_and_configuration_validation(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    header = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=10), usegmt=True)
    assert 8 <= t.retry_delay({"retry-after": header}, 1) <= 10
    with pytest.raises(ValueError): t.Policy(0)
    with pytest.raises(ValueError): t.Policy(2, float("nan"))
    monkeypatch.setenv("FOLLOWUP_MAX_ATTEMPTS", "99")
    with pytest.raises(ValueError): t.configured_policy()
