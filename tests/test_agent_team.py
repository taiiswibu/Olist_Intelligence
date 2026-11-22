import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("langchain")
pytest.importorskip("langchain_openai")

from langchain_core.messages import AIMessage, ToolMessage
from olist import agent_team as team, erp
from olist.api import app
from olist.analytics import Filters


def message(value):
    return AIMessage(content=json.dumps(value, ensure_ascii=False))


@pytest.fixture
def models(monkeypatch):
    providers = [SimpleNamespace(name=n, model=n + "-test", key="secret-never-expose", base="https://example.test")
                 for n in ("groq", "gemini", "ollama")]
    monkeypatch.setattr(team.llm, "providers", lambda: providers)
    calls = []

    class FakeModel:
        def __init__(self, provider):
            self.provider = provider
            self.tools = []

        def bind_tools(self, tools, **kwargs):
            assert kwargs["parallel_tool_calls"] is False
            self.tools = tools
            return self

        async def ainvoke(self, messages):
            calls.append((self.provider.name, messages, [t.name for t in self.tools]))
            if self.tools:
                if isinstance(messages[-1], ToolMessage):
                    return AIMessage(content="Đã lấy bằng chứng từ công cụ.")
                name = "business_kpis" if self.provider.name == "groq" else "search_business_docs"
                args = {} if name == "business_kpis" else {"query": "GMV và AOV là gì?"}
                return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "tool-1", "type": "tool_call"}])
            prompt = messages[1].content
            if "Chọn các agent" in prompt:
                return message({"agents": ["bi", "knowledge"], "clarification": ""})
            if "Tóm tắt hội thoại" in prompt:
                return AIMessage(content="Đang phân tích dữ liệu lịch sử.")
            return message({"status": "complete", "answer": "Đã lấy KPI và định nghĩa từ công cụ. [E1] [E2]",
                            "evidence_ids": ["E1", "E2"], "repair_agents": []})

    monkeypatch.setattr(team, "make_model", lambda p, timeout: FakeModel(p))
    return calls


def run(**kwargs):
    return asyncio.run(team.ask(team.TeamRequest(question="KPI và định nghĩa GMV tháng 1/2018", **kwargs)))


def test_real_graph_uses_two_models_tools_and_fixed_scope(db, models):
    events = []
    request = team.TeamRequest(question="KPI và định nghĩa GMV tháng 1/2018")
    result = asyncio.run(team.ask(request, events.append))
    assert result["status"] == "complete"
    assert result["model_calls"] == 6 and result["tool_calls"] == 2
    assert {p for p, _, _ in models} == {"groq", "gemini"}
    kpi = next(e for e in result["evidence"] if e["agent"] == "bi")
    assert kpi["result"]["values"]["product_gmv"] == 70
    assert kpi["result"]["filters"] == {"start": "2018-01-01", "end": "2018-01-31", "state": None}
    assert len(events) == len(result["trace"]) and all(e["type"] == "step" for e in events)
    assert "secret-never-expose" not in json.dumps(result)


def test_threads_persist_and_are_isolated(db, models):
    thread = "a" * 32
    first = run(thread_id=thread)
    models.clear()
    run(thread_id=thread)
    coordinator = next(messages for _, messages, tools in models if not tools)
    assert first["answer"] == json.loads(json.loads(coordinator[-1].content)["history"])[-1]["answer"]
    models.clear()
    run(thread_id="b" * 32)
    coordinator = next(messages for _, messages, tools in models if not tools)
    assert json.loads(coordinator[-1].content)["history"] == "[]"


def test_repeated_run_is_cached_and_conflicting_payload_rejected(db, models):
    run_id = "c" * 32
    thread = "d" * 32
    first = run(run_id=run_id, thread_id=thread)
    count = len(models)
    assert run(run_id=run_id, thread_id=thread) == first
    assert len(models) == count
    with pytest.raises(team.RunBusy):
        run(run_id=run_id, thread_id="e" * 32)


def test_scope_change_and_unauthorized_tools_are_rejected(db, models, monkeypatch):
    async def malicious(ctx, role, task, tools):
        tool = next(t for t in tools if t.name == "business_kpis")
        with pytest.raises(ValueError, match="phạm vi"):
            await ctx.tool("bi", tool, {"start": "2017-01-01"})
        return {"agent": role, "report": "Không có bằng chứng."}
    monkeypatch.setattr(team, "_specialist", malicious)
    result = run()
    assert result["status"] == "incomplete" and result["evidence"] == []


def test_review_rejects_invented_sources_and_numeric_prose():
    evidence = [{"id": "E1"}]
    for answer, ids in [("GMV là 999 BRL [E1]", ["E1"]), ("Nguồn [E9]", ["E9"])]:
        review = team.Review(status="complete", answer=answer, evidence_ids=ids)
        assert not team._review_valid(review, evidence)


def test_shared_budget_counts_concurrent_requests(db, models, monkeypatch):
    monkeypatch.setattr(team, "MAX_MODELS", 2)
    result = run()
    assert result["status"] == "incomplete"
    assert result["model_calls"] == 2
    monkeypatch.setattr(team, "MAX_TOOLS", 1)
    monkeypatch.setattr(team, "MAX_MODELS", 12)
    result = run()
    assert result["tool_calls"] <= 1 and result["status"] == "incomplete"


def test_one_repair_round_only(db, models, monkeypatch):
    original = team.make_model
    def factory(p, timeout):
        model = original(p, timeout)
        invoke = model.ainvoke
        async def repair(messages):
            if "Kiểm tra bằng chứng" in messages[1].content:
                return message({"status": "repair", "answer": "Cần bổ sung định nghĩa. [E1]",
                                "evidence_ids": ["E1"], "repair_agents": ["knowledge"]})
            return await invoke(messages)
        model.ainvoke = repair
        return model
    monkeypatch.setattr(team, "make_model", factory)
    result = run()
    assert result["status"] == "incomplete"
    assert len([e for e in result["evidence"] if e["agent"] == "knowledge"]) == 2


def test_provider_failure_is_sanitized_and_other_evidence_kept(db, models, monkeypatch):
    original = team.make_model
    def factory(p, timeout):
        if p.name == "gemini":
            raise RuntimeError("secret-never-expose")
        return original(p, timeout)
    monkeypatch.setattr(team, "make_model", factory)
    result = run()
    assert result["status"] == "incomplete" and result["evidence"]
    assert "R$ 70.00" in result["answer"]
    assert "secret-never-expose" not in json.dumps(result)


def test_optional_local_summary_only_for_long_history(db, models):
    run(local_summary=True, thread_id="f" * 32)
    assert not any(p == "ollama" for p, _, _ in models)
    with team._storage() as conn:
        conn.execute("INSERT INTO team_turns VALUES (?,?,?,?,?,?)", ("1" * 32, "f" * 32, "ngữ cảnh " * 400,
                     "câu trả lời", "{}", "2000-01-01"))
    run(local_summary=True, thread_id="f" * 32)
    assert any(p == "ollama" for p, _, _ in models)


def test_proposal_requires_explicit_current_fields():
    assert team.explicit_proposal("Đồng ý, xác nhận đơn đi") is None
    with pytest.raises(ValueError):
        team.explicit_proposal("Tạo báo giá cho khách quen")
    with pytest.raises(ValueError):
        team.explicit_proposal("Tạo báo giá partner_id=1 product_id=2 quantity=0 unit_price=10")


def test_proposal_pending_and_retry_does_not_repeat_it(db, models, monkeypatch):
    calls = []
    class ReadOdoo:
        def call(self, model, method, args):
            calls.append(method)
            assert method == "search"
            return [1]
    monkeypatch.setattr(erp, "Odoo", ReadOdoo)
    request = team.TeamRequest(question="Tạo đề xuất báo giá partner_id=1 product_id=2 quantity=3 unit_price=10",
                               allow_proposals=True)
    first = asyncio.run(team.ask(request))
    assert first["proposal"]["state"] == "pending" and calls == ["search", "search"]
    assert len(erp.list_actions()) == 1
    assert asyncio.run(team.ask(request)) == first
    assert len(erp.list_actions()) == 1


def test_api_stream_auth_and_json_roundtrip(db, models):
    c = TestClient(app)
    assert c.get("/agent/team").status_code == 401
    c.post("/session", json={"key": "local-test-token"})
    payload = {"question": "KPI và định nghĩa GMV tháng 1/2018"}
    assert c.post("/agent/team/stream", json=payload).status_code == 403
    response = c.post("/agent/team/stream", json=payload, headers={"X-Olist-Request": "1"})
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "result" and events[-1]["result"]["status"] == "complete"
    assert any(e["type"] == "step" for e in events)
    assert c.post("/agent/team/chat", json=payload, headers={"X-Olist-Request": "1", "Origin": "https://evil.test"}).status_code == 403


def test_unconfigured_team_and_invalid_dates_reject_before_run(db, monkeypatch):
    monkeypatch.setattr(team.llm, "providers", lambda: [])
    with pytest.raises(team.TeamUnavailable):
        run()
    c = TestClient(app, headers={"X-App-Token": "local-test-token"})
    assert c.post("/agent/team/chat", json={"question": "KPI"}).status_code == 503
    assert c.post("/agent/team/chat", json={"question": "KPI", "filters": {"start": "2018-02-01", "end": "2018-01-01"}}).status_code == 422


def test_gemini_signature_survives_tool_roundtrip(monkeypatch):
    import httpx
    from langchain_core.messages import HumanMessage
    from olist.team_model import TeamModel
    from olist.agent_lab import build_tools
    calls = []
    signature = {"google": {"thought_signature": "opaque-test-signature"}}
    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            response = {"role": "assistant", "content": None, "tool_calls": [{"id": "call-1", "type": "function",
                "function": {"name": "business_kpis", "arguments": "{}"}, "extra_content": signature}]}
        else:
            assert body["messages"][1]["tool_calls"][0]["extra_content"] == signature
            response = {"role": "assistant", "content": "Đã đọc công cụ."}
        return httpx.Response(200, json={"choices": [{"message": response}]})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    async def scenario():
        p = SimpleNamespace(name="gemini", model="test", key="test-key", base="https://example.test")
        model = TeamModel(p, 1).bind_tools(build_tools(False))
        user = HumanMessage(content="KPI")
        first = await model.ainvoke([user])
        await model.ainvoke([user, first, ToolMessage(content="{}", tool_call_id="call-1")])
    asyncio.run(scenario())
    assert len(calls) == 2


def test_deadline_stops_and_caches_incomplete_run(db, models, monkeypatch):
    monkeypatch.setattr(team, "MAX_SECONDS", .02)
    class Slow:
        async def ainvoke(self, messages):
            await asyncio.sleep(1)
    monkeypatch.setattr(team, "make_model", lambda *a: Slow())
    request = team.TeamRequest(question="KPI")
    result = asyncio.run(team.ask(request))
    assert result["status"] == "incomplete" and result["elapsed_ms"] < 500
    assert asyncio.run(team.ask(request)) == result


def test_cancellation_persists_interrupted_result(db, models, monkeypatch):
    async def blocked(*args):
        raise asyncio.CancelledError()
    monkeypatch.setattr(team, "_graph", blocked)
    request = team.TeamRequest(question="KPI")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(team.ask(request))
    assert asyncio.run(team.ask(request))["status"] == "interrupted"


def test_injected_tool_is_denied(db, models, monkeypatch):
    original = team.make_model
    def factory(p, timeout):
        model = original(p, timeout)
        invoke = model.ainvoke
        async def attack(messages):
            if model.tools and not isinstance(messages[-1], ToolMessage):
                return AIMessage(content="", tool_calls=[{"name": "approve", "args": {"id": "anything"},
                    "id": "evil", "type": "tool_call"}])
            return await invoke(messages)
        model.ainvoke = attack
        return model
    monkeypatch.setattr(team, "make_model", factory)
    result = run()
    assert result["status"] == "incomplete" and result["evidence"] == []
    assert erp.list_actions() == []


def test_request_storage_does_not_keep_credentials(db, models):
    request = team.TeamRequest(question="KPI secret-never-expose")
    asyncio.run(team.ask(request))
    with team._storage() as conn:
        saved = conn.execute("SELECT request,result FROM team_runs WHERE run_id=?", (request.run_id,)).fetchone()
        question = conn.execute("SELECT question FROM team_turns WHERE run_id=?", (request.run_id,)).fetchone()[0]
    assert "secret-never-expose" not in str(tuple(saved)) + question


def test_numeric_answer_comes_from_tools_instead_of_generated_prose(db, models, monkeypatch):
    original = team.make_model
    def factory(p, timeout):
        model = original(p, timeout)
        invoke = model.ainvoke
        async def wrong_number(messages):
            if "Kiểm tra bằng chứng" in messages[1].content:
                return message({"status": "complete", "answer": "GMV là 999 BRL. [E1] [E2]",
                                "evidence_ids": ["E1", "E2"], "repair_agents": []})
            return await invoke(messages)
        model.ainvoke = wrong_number
        return model
    monkeypatch.setattr(team, "make_model", factory)
    result = run()
    assert result["status"] == "complete" and "999" not in result["answer"]
    assert "R$ 70.00" in result["answer"]


def test_local_summary_failure_keeps_cloud_workflow_available(db, models, monkeypatch):
    thread = "9" * 32
    with team._storage() as conn:
        conn.execute("INSERT INTO team_turns VALUES (?,?,?,?,?,?)", ("8" * 32, thread, "hội thoại " * 400,
                     "câu trả lời", "{}", "2000-01-01"))
    original = team.make_model
    def factory(p, timeout):
        if p.name == "ollama":
            raise RuntimeError("secret-never-expose")
        return original(p, timeout)
    monkeypatch.setattr(team, "make_model", factory)
    result = run(thread_id=thread, local_summary=True)
    assert result["status"] == "complete"
    assert any(e["agent"] == "summary" and e["status"] == "failed" for e in result["trace"])
    assert "secret-never-expose" not in json.dumps(result)


def test_invalid_demo_record_does_not_create_team_proposal(db, models, monkeypatch):
    class Missing:
        def call(self, model, method, args):
            assert method == "search"
            return []
    monkeypatch.setattr(erp, "Odoo", Missing)
    request = team.TeamRequest(question="Tạo đề xuất báo giá partner_id=99 product_id=98 quantity=3 unit_price=10",
                               allow_proposals=True)
    result = asyncio.run(team.ask(request))
    assert result["status"] == "incomplete" and "proposal" not in result
    assert erp.list_actions() == []


def test_at_most_two_specialists_run_concurrently(db, models, monkeypatch):
    active = peak = 0
    original = team.make_model
    def factory(p, timeout):
        model = original(p, timeout)
        invoke = model.ainvoke
        async def dispatch(messages):
            if "Chọn các agent" in messages[1].content:
                return message({"agents": ["bi", "knowledge", "erp"], "clarification": ""})
            return await invoke(messages)
        model.ainvoke = dispatch
        return model
    async def worker(ctx, role, task, tools):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.02)
        active -= 1
        ctx.evidence.append({"id": "E" + str(len(ctx.evidence) + 1), "agent": role, "tool": "test_fixture", "result": {}})
        return {"agent": role, "report": "Đã có bằng chứng."}
    monkeypatch.setattr(team, "make_model", factory)
    monkeypatch.setattr(team, "_specialist", worker)
    assert run()["status"] == "complete"
    assert peak == 2


def test_qwen_summary_disables_thinking_and_bounds_context(monkeypatch):
    import httpx
    from langchain_core.messages import HumanMessage
    from olist.team_model import TeamModel
    def handler(request):
        payload = json.loads(request.content)
        assert request.url.path == "/api/chat" and payload["think"] is False
        assert payload["options"]["num_predict"] == 256 and payload["options"]["num_ctx"] == 4096
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "Tóm tắt."},
                                       "eval_count": 4, "prompt_eval_count": 8})
    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    model = TeamModel(SimpleNamespace(name="ollama", model="test", key="", base="http://localhost:11434"), 1)
    result = asyncio.run(model.ainvoke([HumanMessage(content="Tóm tắt hội thoại.")]))
    assert result.content == "Tóm tắt." and result.usage_metadata["total_tokens"] == 12
