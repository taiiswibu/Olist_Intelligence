import json
import pytest
import httpx
from olist import agent, llm, rag
from olist.analytics import Filters


def test_no_key_mode_never_claims_llm(db):
    r = agent.ask("Tổng quan KPI năm 2018", Filters())
    assert r["routing"]["mode"] == "local_rules"
    assert r["routing"]["provider"] is None
    assert r["data"]["product_gmv"] == 70


def test_unsupported_inventory_cannot_be_routed_to_kpi(db):
    r = agent.ask("Cho biết tồn kho hiện có", Filters())
    assert r["tool"] == "unsupported"
    assert "data" not in r


def test_historical_dataset_rejects_today(db):
    with pytest.raises(ValueError, match="lịch sử"):
        agent.ask("GMV hôm nay", Filters())


def test_explicit_dates_and_month_year():
    r = agent.extract_filters("GMV tháng 2/2018", Filters())
    assert str(r.start) == "2018-02-01"
    assert str(r.end) == "2018-02-28"
    assert str(agent.extract_filters("GMV tháng 2 năm 2018", Filters()).end) == "2018-02-28"
    r = agent.extract_filters("từ 2017-03-01 đến 2017-04-01 bang SP", Filters())
    assert str(r.start) == "2017-03-01" and r.state == "SP"


def test_ambiguous_filters_do_not_silently_return_wrong_scope():
    for q in ["GMV tháng 2", "GMV từ 2017 đến 2018", "Top 3 category", "GMV 2018-01-01"]:
        with pytest.raises(ValueError):
            agent.extract_filters(q, Filters())


def test_rag_finds_late_definition():
    r = rag.retrieve("Tỷ lệ giao trễ được tính như thế nào?")
    assert any("Tỷ lệ giao trễ" in s["section"] for s in r["sources"])
    assert r["method"] in {"lexical_tfidf", "lexical_fallback"}


def test_provider_fallback_does_not_log_keys(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDERS", "groq,gemini")
    for name in ["GROQ", "GEMINI"]:
        monkeypatch.setenv(name+"_MODEL", "test-model")
        monkeypatch.setenv(name+"_API_KEY", "secret-test-never-log")
    calls = []
    def handler(req):
        calls.append(req.url.host)
        if "groq" in req.url.host:
            return httpx.Response(429, json={"detail": "secret-test-never-log"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    client = httpx.Client
    monkeypatch.setattr(llm.httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handler)))
    r = llm.complete([{"role":"user", "content":"hello"}])
    assert r["provider"] == "gemini"
    assert len(calls) == 2
    assert "secret-test-never-log" not in json.dumps(r)
    assert r["failures"] == [{"provider":"groq", "error":"HTTP 429"}]


def test_invalid_llm_tool_cannot_execute(monkeypatch, db):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: {"content":'{"tool":"run_shell","command":"rm -rf /"}', "provider":"fake","failures":[]})
    plan, route = agent.choose("Tổng quan KPI")
    assert plan.tool == "kpis"
    assert route["mode"] == "local_rules"
