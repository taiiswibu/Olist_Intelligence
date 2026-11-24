"""Bounded AI planning; factual prose is rendered locally from the snapshot."""
import asyncio
import json
from typing import Literal

from pydantic import Field

from . import agent_skills, followup_privacy as privacy, followup_transport as transport, llm

VERSION = 'followup-plan-minimized-v1'
RENDER_VERSION = 'followup-plan-render-v1'
Focus = Literal['content', 'validity', 'terms', 'needs', 'receipt', 'status', 'deadline', 'next_step']


def allowed_focus(case):
    if case.allowed_actions == ['review_existing_activity']:
        return ['status', 'next_step']+(['deadline'] if 'overdue_activity' in case.reason_codes else [])
    if case.allowed_actions == ['review_quotation']:
        return ['content', 'terms']+(['validity'] if {'expired_quotation','expiring_quotation'} & set(case.reason_codes) else [])
    return ['needs', 'terms', 'receipt']


class PlanCase(privacy.CloudCase):
    allowed_focus: list[Focus] = Field(min_length=1, max_length=3)


class Choice(privacy.Strict):
    case_id: str = Field(pattern=r'^CASE_[a-f0-9]{16}$')
    focus: Focus
    activity_type: Literal['call', 'todo']


class Plan(privacy.Strict):
    items: list[Choice] = Field(min_length=1, max_length=20)


class Envelope(privacy.Strict):
    cases: list[PlanCase] = Field(min_length=1, max_length=20)
    draft: Plan | None = None


def validate(plan, cases):
    known={c.case_id:c for c in cases}
    if len(plan.items)!=len(known) or {c.case_id for c in plan.items}!=set(known):
        raise ValueError('PlanCaseMismatch')
    for item in plan.items:
        case=known[item.case_id]
        if item.focus not in allowed_focus(case) or (item.activity_type=='call' and case.allowed_actions!=['request_feedback']):
            raise ValueError('PlanScopeMismatch')


def wire_guard(messages,audit=None):
    def check(content):
        data=Envelope.model_validate_json(content)
        if any(c.allowed_focus!=allowed_focus(c) for c in data.cases):
            raise ValueError('ChangedFocusScope')
        if data.draft:validate(data.draft,data.cases)
    return privacy.pinned_guard(messages,check,audit)


def render(plan,cases):
    validate(plan,cases)
    known={c.case_id:c for c in cases}
    wording={
        ('review_quotation','content'):('Rà soát nội dung báo giá','Kiểm tra sản phẩm, số lượng và nội dung trước khi chuẩn bị gửi báo giá.'),
        ('review_quotation','terms'):('Đối chiếu điều khoản báo giá','Rà soát điều khoản cần làm rõ trước khi chuẩn bị gửi báo giá.'),
        ('review_quotation','validity'):('Kiểm tra hiệu lực báo giá','Đối chiếu hiệu lực đang ghi trên báo giá trước khi chuẩn bị gửi khách.'),
        ('request_feedback','needs'):('Hỏi nhu cầu cần làm rõ','Liên hệ hỏi khách còn nhu cầu nào cần làm rõ về báo giá đã gửi.'),
        ('request_feedback','terms'):('Hỏi điểm cần làm rõ','Liên hệ hỏi khách có điều khoản nào trong báo giá đã gửi cần trao đổi thêm.'),
        ('request_feedback','receipt'):('Kiểm tra khách nhận báo giá','Liên hệ hỏi khách đã nhận được báo giá chưa và có cần làm rõ nội dung nào không.'),
        ('review_existing_activity','status'):('Rà soát việc đang hẹn','Kiểm tra công việc chăm sóc đang hẹn và đối chiếu tình trạng xử lý trước khi sắp xếp thêm.'),
        ('review_existing_activity','next_step'):('Đối chiếu bước chăm sóc tiếp theo','Xem lại công việc đang hẹn trước khi lựa chọn bước chăm sóc tiếp theo.'),
        ('review_existing_activity','deadline'):('Kiểm tra hạn công việc','Rà soát hạn của công việc đang hẹn và hỏi người phụ trách về tình trạng xử lý.')}
    reasons={'overdue_activity':'Có công việc có ngày hẹn trước ngày đối chiếu; chưa biết tình trạng hoàn tất.',
        'expired_quotation':'Ngày hiệu lực báo giá đã qua.', 'expiring_quotation':'Báo giá gần đến ngày hiệu lực.',
        'no_activity':'Bản chụp không có công việc đang hẹn; chưa biết lịch sử liên hệ hoặc phản hồi.',
        'waiting':'Bản chụp có công việc đang hẹn, không có cờ quá hạn hoặc hiệu lực cần ưu tiên.'}
    items=[]
    for choice in plan.items:
        case=known[choice.case_id]; action=case.allowed_actions[0]
        summary,note=wording[action,choice.focus]
        items.append(privacy.CloudItem(case_id=case.case_id,reason_codes=case.reason_codes,action=action,
            activity_type=choice.activity_type,summary=summary,note=note,explanation='AI chọn góc trao đổi; nội dung dựng từ bản chụp. '+' '.join(reasons[r] for r in case.reason_codes)))
    return privacy.CloudDraft(items=items)


async def analyze(payload,*,request_policy=None):
    from . import followups as f
    trace=[]
    cases,mapping=privacy.project(payload,f.facts)
    public=[PlanCase(**c.model_dump(),allowed_focus=allowed_focus(c)) for c in cases]
    policy=request_policy or transport.configured_policy()
    accepted=False; failure=None; choices=None
    try:
        async with asyncio.timeout(85):
            from langchain_core.messages import HumanMessage,SystemMessage
            providers={p.name:p for p in llm.providers()}
            if not {'groq','gemini'}<=providers.keys():raise ValueError('MissingProvider')
            prompt=agent_skills.read('olist-customer-followup')['instructions']+'\nChọn góc trao đổi trong allowed_focus cho từng case_id. Chỉ chọn call khi action là request_feedback; còn lại chọn todo. Không soạn văn bản, không thêm trường. Khi có cờ hiệu lực hoặc quá hạn, ưu tiên góc đối chiếu tương ứng nếu được phép. Trả JSON theo schema: '+json.dumps(Plan.model_json_schema())
            envelope=Envelope(cases=public)
            choices=await f._model_json(providers['groq'],[SystemMessage(content=prompt),HumanMessage(content=envelope.model_dump_json())],Plan,trace,policy,guard_factory=wire_guard,privacy_version=VERSION)
            validate(choices,cases)
            reviewer=agent_skills.read('olist-followup-check')['instructions']+'\nBản nháp chỉ chọn góc trao đổi và loại công việc, chưa có văn bản. Chấp nhận khi đủ case_id, focus thuộc allowed_focus và call chỉ dành cho request_feedback. Trả JSON theo schema: '+json.dumps(f.Verification.model_json_schema())
            envelope.draft=choices
            verification=await f._model_json(providers['gemini'],[SystemMessage(content=reviewer),HumanMessage(content=envelope.model_dump_json())],f.Verification,trace,policy,guard_factory=wire_guard,privacy_version=VERSION)
            if not verification.valid:raise ValueError('ReviewRejected')
            draft=render(choices,cases)
            accepted=True
    except (f.AnalysisFailure,ValueError,TimeoutError,ImportError) as exc:
        failure=getattr(exc,'reason',str(exc) if str(exc) in {'MissingProvider','ReviewRejected','PlanCaseMismatch','PlanScopeMismatch'} else type(exc).__name__)
        draft=f.rules_draft(cases)
        for item in draft.items:
            item.explanation='Mẫu quy tắc dự phòng; chưa có kết quả AI được chấp nhận. '+item.explanation
    privacy.validate_draft(draft,cases)
    items=[f.Suggestion(order_id=mapping[item.case_id],**item.model_dump(exclude={'case_id'})).model_dump() for item in draft.items]
    return f._clean({'items':items,'trace':trace,'strategy':'assisted' if accepted else 'rules_fallback','ai_completed':accepted,
        'fallback_reason':failure,'privacy_version':VERSION,'grounding_version':RENDER_VERSION,'request_policy':policy.metadata(),
        'cloud_fields':list(PlanCase.model_fields),'choices':[c.model_dump() for c in choices.items] if accepted else [],
        'skills':agent_skills.catalog(['olist-customer-followup','olist-followup-check'])})
