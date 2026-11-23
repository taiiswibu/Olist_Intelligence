import asyncio
import json
from decimal import Decimal

import pytest
from langchain_core.messages import AIMessage

from test_sales import adapter, client
from test_sales_pricing import financial, body
from test_agent_team import models
from olist import agent_team as team, agent_lab, agent_skills, erp


@pytest.fixture
def erp_models(models, monkeypatch):
    calls = []

    class Model:
        def __init__(self):
            self.tools = []

        def bind_tools(self, tools, **kwargs):
            self.tools = tools
            return self

        async def ainvoke(self, messages):
            calls.append((messages, [t.name for t in self.tools]))
            if self.tools:
                return AIMessage(content="Đã đọc bản đối soát. Chưa ghi báo giá.")
            if "Chọn các agent" in messages[1].content:
                return AIMessage(content=json.dumps({"agents": ["erp"], "clarification": ""}))
            return AIMessage(content=json.dumps({"status": "complete", "answer": "Đã kiểm tra từ Odoo; xem bảng đối soát. [E1]",
                "evidence_ids": ["E1"], "repair_agents": []}))

    monkeypatch.setattr(team, "make_model", lambda p, timeout: Model())
    return calls


def request(**kwargs):
    payload = body();payload.pop("request_id")
    return team.TeamRequest(question="Kiểm tra báo giá đang soạn; không tự đổi giá hoặc lưu đề xuất.", sales_draft=payload, **kwargs)


def test_team_loads_real_skills_and_calculates_only_current_form(client, financial, erp_models):
    result = asyncio.run(team.ask(request()))
    assert result["status"] == "complete" and not financial.orders and erp.list_actions() == []
    evidence = next(e for e in result["evidence"] if e["tool"] == "review_current_quotation")
    assert evidence["result"]["total"] == "99.00" and "99.00 BRL" in result["answer"]
    assert {s["name"] for s in result["skills"]} == set(agent_skills.SKILLS)
    specialist, tools = next((messages, tools) for messages, tools in erp_models if tools)
    assert "review_current_quotation" in tools and "prepare_quotation" not in tools
    assert agent_skills.read("olist-quote-review")["instructions"] in specialist[1].content
    task = json.loads(specialist[-1].content)
    assert task["sales_draft"]["lines"][0]["discount"] == "10"
    assert task["current_quotation_review"]["result"] == evidence["result"]


def test_snapshot_is_captured_and_model_cannot_replace_prices(financial):
    draft = body();draft.pop("request_id")
    tools = {t.name: t for t in agent_lab.build_tools(False, sales_draft=draft)}
    draft["lines"][0]["unit_price"] = "999"
    first = tools["review_current_quotation"].invoke({})
    assert first["total"] == "99.00"
    assert tools["review_current_quotation"].args == {}
    assert "review_current_quotation" not in {t.name for t in agent_lab.build_tools(False)}
    assert not financial.orders and erp.list_actions() == []


def test_form_review_retry_is_cached_and_conflicting_snapshot_rejected(client, financial, erp_models):
    req = request()
    result = asyncio.run(team.ask(req)); count = len(financial.calls)
    assert asyncio.run(team.ask(req)) == result and len(financial.calls) == count
    req.sales_draft.lines[0].unit_price = Decimal("101")
    with pytest.raises(team.RunBusy):
        asyncio.run(team.ask(req))


def test_review_cannot_enable_proposals_and_native_failure_never_completes(client, financial, erp_models):
    with pytest.raises(ValueError, match="không lưu đề xuất"):
        asyncio.run(team.ask(request(allow_proposals=True)))
    financial.adjust_input = True
    result = asyncio.run(team.ask(request()))
    assert result["status"] == "incomplete"
    assert not any(e["tool"] == "review_current_quotation" for e in result["evidence"])
    assert not financial.orders and erp.list_actions() == []


def test_registered_skills_use_only_bounded_read_tools(financial):
    draft = body();draft.pop("request_id")
    available = {t.name for t in agent_lab.build_tools(False, sales_draft=draft)}
    assert agent_skills.tools() <= available
    assert not agent_skills.tools() & {"prepare_quotation", "approve", "action_confirm", "write", "invoice"}
    with pytest.raises(ValueError):
        agent_skills.read("../../.env")


def test_document_tool_returns_only_existing_scoped_quote_without_creation(client, financial):
    tools = {t.name: t for t in agent_lab.build_tools(False)}
    assert "error" in tools["odoo_quotation_document"].invoke({"order_id": 99})
    action = client.post("/actions", json=body()).json()
    assert client.post(f"/actions/{action['id']}/approve").status_code == 200
    financial.calls.clear()
    document = tools["odoo_quotation_document"].invoke({"order_id": 99})
    assert document["download_path"] == "/erp/quotations/99/pdf" and document["total"] == 99
    assert all(method == "search_read" for _,method,_,_ in financial.calls)
    financial.orders[99]["state"] = "sale"
    assert "error" in tools["odoo_quotation_document"].invoke({"order_id": 99})
