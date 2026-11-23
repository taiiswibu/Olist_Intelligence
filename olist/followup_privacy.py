"""Only this allowlist may leave the host in the Odoo follow-up workflow."""
import json
import secrets
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VERSION = "followup-minimized-v1"
Reason = Literal["overdue_activity", "expired_quotation", "expiring_quotation", "no_activity", "waiting"]
Action = Literal["review_quotation", "request_feedback", "review_existing_activity"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CloudCase(Strict):
    case_id: str = Field(pattern=r"^CASE_[a-f0-9]{16}$")
    quotation_state: Literal["draft", "sent"]
    reason_codes: list[Reason] = Field(min_length=1, max_length=4)
    has_activity: bool
    allowed_actions: list[Action] = Field(min_length=1, max_length=1)


class CloudItem(Strict):
    case_id: str = Field(pattern=r"^CASE_[a-f0-9]{16}$")
    reason_codes: list[Reason] = Field(min_length=1, max_length=4)
    action: Action
    activity_type: Literal["call", "todo"]
    summary: str = Field(min_length=1, max_length=120)
    note: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(min_length=1, max_length=800)


class CloudDraft(Strict):
    items: list[CloudItem] = Field(min_length=1, max_length=20)


class CloudInput(Strict):
    cases: list[CloudCase] = Field(min_length=1, max_length=20)
    draft: CloudDraft | None = None


def project(payload, reason_fn):
    cases, mapping = [], {}
    for quote in payload.orders:
        alias = "CASE_" + secrets.token_hex(8)
        action = "review_existing_activity" if quote.activities else "review_quotation" if quote.state == "draft" else "request_feedback"
        cases.append(CloudCase(case_id=alias, quotation_state=quote.state, reason_codes=reason_fn(quote, payload.today),
                               has_activity=bool(quote.activities), allowed_actions=[action]))
        mapping[alias] = quote.id
    return cases, mapping


def validate_draft(draft, cases):
    import re
    known = {case.case_id: case for case in cases}
    if len(draft.items) != len(known) or {item.case_id for item in draft.items} != set(known):
        raise ValueError("AI trả sai danh sách mã tạm.")
    for item in draft.items:
        case = known[item.case_id]
        if item.action not in case.allowed_actions or not set(item.reason_codes) <= set(case.reason_codes):
            raise ValueError("Đề xuất vượt dữ kiện hoặc hành động được phép.")
        prose = item.summary + item.note + item.explanation
        if re.search(r"\d|@|https?://|www\.", prose, re.I):
            raise ValueError("Văn bản AI chứa số liệu hoặc thông tin liên hệ không được phép.")


def wire_guard(messages, audit=None):
    """Pin approved messages and validate their public schema at the actual HTTP boundary."""
    expected = [{"role": "system" if m.type == "system" else "user", "content": m.content} for m in messages]
    if [m["role"] for m in expected] != ["system", "user"]:
        raise ValueError("Luồng chăm sóc chỉ gửi một chỉ dẫn cố định và dữ kiện tối thiểu.")
    envelope = CloudInput.model_validate_json(expected[1]["content"])
    if envelope.draft is not None:
        validate_draft(envelope.draft, envelope.cases)

    def check(wire):
        allowed = {"model", "messages", "temperature", "max_tokens", "stream", "response_format", "reasoning_effort"}
        if set(wire) - allowed or wire.get("messages") != expected:
            raise ValueError("Chặn request model bị thay đổi sau bước lọc dữ liệu.")
        CloudInput.model_validate_json(wire["messages"][1]["content"])
        if audit is not None:
            audit["requests_checked"] += 1
    return check
