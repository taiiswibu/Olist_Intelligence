import pytest

pytest.importorskip("langchain")
pytest.importorskip("langchain_openai")
pytest.importorskip("langgraph.checkpoint.sqlite")

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import ValidationError

from olist import agent_lab as lab, erp


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def call(name, args, ident):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": ident, "type": "tool_call"}])


def test_real_graph_executes_multiple_tools_and_persists_restart(db, tmp_path):
    path = str(tmp_path / "checkpoints.sqlite")
    model = ToolModel(responses=[
        call("business_kpis", {"start": "2018-01-01", "end": "2018-01-31"}, "1"),
        call("business_breakdown", {"kind": "category", "start": "2018-01-01", "end": "2018-01-31"}, "2"),
        AIMessage(content="GMV 70 BRL; books 50, toys 20."),
    ])
    with SqliteSaver.from_conn_string(path) as saver:
        graph = lab.make_agent(model, saver)
        result = lab.run_turn(graph, "Phân tích KPI và ngành hàng tháng 1/2018", "test-thread")
        tools = [m for m in result["messages"] if m.type == "tool"]
        assert [m.name for m in tools] == ["business_kpis", "business_breakdown"]
        assert '"product_gmv": 70' in tools[0].content
    with SqliteSaver.from_conn_string(path) as saver:
        graph = lab.make_agent(ToolModel(responses=[AIMessage(content="Tôi còn lịch sử.")]), saver)
        restored = graph.get_state({"configurable": {"thread_id": "test-thread"}})
        assert restored.values["messages"][-1].content == result["messages"][-1].content
        next_turn = lab.run_turn(graph, "Nhắc lại kỳ phân tích", "test-thread")
        assert sum(m.type == "human" for m in next_turn["messages"]) == 2
        assert not graph.get_state({"configurable": {"thread_id": "other-thread"}}).values


def test_tool_permissions_and_validation():
    tools = {t.name: t for t in lab.build_tools()}
    assert "prepare_quotation" not in tools
    assert not set(tools) & {"approve", "action_confirm", "sql", "shell", "invoice"}
    with pytest.raises(ValidationError):
        tools["business_kpis"].invoke({"start": "2018-02-01", "end": "2018-01-01"})
    with pytest.raises(ValidationError):
        tools["business_breakdown"].invoke({"kind": "arbitrary_sql"})
    with pytest.raises(ValidationError):
        tools["lookup_historical_order"].invoke({"order_id": "' OR 1=1"})


def test_proposal_stays_pending_until_separate_human_approval(db, monkeypatch):
    calls = []
    class ReadOnlyOdoo:
        def call(self, model, method, args):
            calls.append(method)
            assert method == "search"
            return [args[0][0][2]]
    monkeypatch.setattr(erp, "Odoo", ReadOnlyOdoo)
    tool = {t.name: t for t in lab.build_tools(True)}["prepare_quotation"]
    result = tool.invoke({"partner_id": 1, "product_id": 2, "quantity": 3, "unit_price": 10})
    assert result["state"] == "pending" and calls == ["search", "search"]
    assert erp.list_actions()[0]["state"] == "pending"
    with pytest.raises(ValidationError):
        tool.invoke({"partner_id": 1, "product_id": 2, "quantity": 0, "unit_price": 10})


def test_loop_stops_at_model_budget(db, tmp_path):
    model = ToolModel(responses=[call("business_kpis", {"start": "2018-01-01", "end": "2018-01-31"}, "repeat")])
    with SqliteSaver.from_conn_string(str(tmp_path / "bounded.sqlite")) as saver:
        graph = lab.make_agent(model, saver)
        with pytest.raises(Exception) as exc:
            lab.run_turn(graph, "Lặp mãi", "bounded")
        assert type(exc.value).__name__ == "ModelCallLimitExceededError"


def test_parallel_tools_cannot_exceed_budget(db, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(lab.analytics, "kpis", lambda filters: calls.append(filters) or {"ok": True})
    request = AIMessage(content="", tool_calls=[
        {"name": "business_kpis", "args": {"start": "2018-01-01", "end": "2018-01-31"},
         "id": str(i), "type": "tool_call"} for i in range(7)
    ])
    with SqliteSaver.from_conn_string(str(tmp_path / "tools.sqlite")) as saver:
        graph = lab.make_agent(ToolModel(responses=[request]), saver)
        with pytest.raises(Exception) as exc:
            lab.run_turn(graph, "Gọi bảy công cụ", "tools")
        assert type(exc.value).__name__ == "ToolCallLimitExceededError"
        assert len(calls) <= 6


def test_non_demo_id_does_not_create_proposal(db, monkeypatch):
    class NoDemo:
        def call(self, model, method, args):
            assert method == "search"
            return []
    monkeypatch.setattr(erp, "Odoo", NoDemo)
    tool = {t.name: t for t in lab.build_tools(True)}["prepare_quotation"]
    result = tool.invoke({"partner_id": 99, "product_id": 2, "quantity": 1, "unit_price": 10})
    assert result["error"] == "InvalidDemoRecord"
    assert erp.list_actions() == []
