"""Explain finite risk flags supplied by native Odoo. No ERP reads, prices or identities reach models."""
import asyncio
import json
import re
import secrets

from pydantic import Field, field_validator

from .config import ROOT
from . import followup_privacy as privacy, followup_transport as transport, agent_skills, llm

CATALOG = json.loads((ROOT / "odoo_addons/olist_sales_ai/data/risk_catalog.json").read_text(encoding="utf-8"))
PRIVACY_VERSION = "quote-risk-minimized-v1"


class AdviceItem(privacy.Strict):
    code: str
    question: str = Field(min_length=1, max_length=400)

    @field_validator("code")
    @classmethod
    def known_code(cls, value):
        if value not in CATALOG: raise ValueError("Mã rủi ro ngoài danh sách.")
        return value


class Advice(privacy.Strict):
    items: list[AdviceItem] = Field(max_length=len(CATALOG))


class RiskInput(privacy.Strict):
    case_id: str = Field(pattern=r"^CASE_[a-f0-9]{16}$")
    risk_codes: list[str] = Field(max_length=len(CATALOG))
    draft: Advice | None = None

    @field_validator("risk_codes")
    @classmethod
    def known_codes(cls, values):
        if len(set(values)) != len(values) or not set(values) <= CATALOG.keys():
            raise ValueError("Mã rủi ro không hợp lệ hoặc bị lặp.")
        return values


def validate_advice(advice, codes):
    if len(advice.items) != len(codes) or {i.code for i in advice.items} != set(codes):
        raise ValueError("Giải thích không khớp các cờ từ Odoo.")
    for item in advice.items:
        if (not item.question.endswith("?") or item.question.count("?") != 1 or
                re.search(r"\d|@|[.!;\r\n]|https?://|www\.", item.question, re.I)):
            raise ValueError("Chỉ dùng câu hỏi đối chiếu, không thêm số hoặc thông tin liên hệ.")


def wire_guard(messages, audit=None):
    def validate(content):
        envelope = RiskInput.model_validate_json(content)
        if envelope.draft is not None: validate_advice(envelope.draft, envelope.risk_codes)
    return privacy.pinned_guard(messages, validate, audit)


async def analyze(payload, *, local_only=False):
    from langchain_core.messages import SystemMessage, HumanMessage
    from .followups import _model_json, AnalysisFailure, Verification
    codes = payload.risk_codes
    trace = []
    strategy = "rules"
    advice = Advice(items=[AdviceItem(code=c, question=CATALOG[c]["question"]) for c in codes])
    if not local_only and codes:
        providers = {p.name:p for p in llm.providers()}
        if not {"groq", "gemini"} <= providers.keys(): raise ValueError("Chưa cấu hình đủ model giải thích rủi ro.")
        instructions = agent_skills.read("olist-risk-review")["instructions"]
        policy = transport.configured_policy()
        envelope = RiskInput(case_id="CASE_"+secrets.token_hex(8), risk_codes=codes)
        try:
            async with asyncio.timeout(90):
                advice = await _model_json(providers["groq"], [SystemMessage(content=instructions+
                    "\nDanh mục: "+json.dumps(CATALOG,ensure_ascii=False)+"\nTrả JSON: "+json.dumps(Advice.model_json_schema())),
                    HumanMessage(content=envelope.model_dump_json(exclude_none=True))], Advice, trace, policy,
                    guard_factory=wire_guard, privacy_version=PRIVACY_VERSION)
                try: validate_advice(advice, codes)
                except ValueError: raise AnalysisFailure(trace, "RiskAdviceRejected") from None
                envelope.draft = advice
                checked = await _model_json(providers["gemini"], [SystemMessage(content=instructions+
                    "\nKiểm tra các câu hỏi có đúng phạm vi mã rủi ro, không bịa lịch sử hay gợi ý tự đổi giá/thuế. "
                    "Danh mục: "+json.dumps(CATALOG,ensure_ascii=False)+"\nTrả JSON: "+json.dumps(Verification.model_json_schema())),
                    HumanMessage(content=envelope.model_dump_json())], Verification, trace, policy,
                    guard_factory=wire_guard, privacy_version=PRIVACY_VERSION)
                if not checked.valid: raise AnalysisFailure(trace, "ReviewRejected")
        except TimeoutError: raise AnalysisFailure(trace, "AnalysisDeadlineExceeded") from None
        strategy = "pipeline"
    return {"purpose":"risk", "items": advice.model_dump()["items"], "strategy":strategy, "trace":trace,
            "privacy_version":PRIVACY_VERSION, "skills":agent_skills.catalog(["olist-risk-review"])}
