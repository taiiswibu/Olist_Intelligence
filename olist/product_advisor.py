"""Private Odoo bridge for ranking bounded, anonymized product candidates."""
import asyncio
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import Field, model_validator

from .config import ROOT
from . import database, agent_skills, llm, followup_privacy as privacy, followup_transport as transport
from .followups import Strict, Verification, AnalysisFailure, _model_json, _clean, bridge_auth

CATALOG = json.loads((ROOT/'odoo_addons/olist_sales_ai/data/advisor_catalog.json').read_text(encoding='utf-8'))
CATEGORIES = {c for v in CATALOG.values() for c in v['categories']}
VERSION = 'product-advisor-minimized-v1'
REASONS = {'category_match', 'lower_cost', 'alternative'}


class Candidate(Strict):
    alias: str = Field(pattern=r'^ITEM_[a-f0-9]{16}$')
    category: str
    price_band: Literal['low', 'medium', 'high']


class Pick(Strict):
    alias: str = Field(pattern=r'^ITEM_[a-f0-9]{16}$')
    reason: Literal['category_match', 'lower_cost', 'alternative']


class Ranking(Strict):
    picks: list[Pick] = Field(min_length=1, max_length=3)


class PublicInput(Strict):
    intent: str
    candidates: list[Candidate] = Field(min_length=1, max_length=12)
    draft: Ranking | None = None

    @model_validator(mode='after')
    def supported(self):
        if self.intent not in CATALOG or any(c.category not in CATALOG[self.intent]['categories'] for c in self.candidates):
            raise ValueError('Nhóm nhu cầu hoặc nhóm hàng chưa được hỗ trợ.')
        if len({c.alias for c in self.candidates}) != len(self.candidates):
            raise ValueError('Mã tạm bị lặp.')
        if self.draft: validate_ranking(self.draft, self)
        return self


class AdviceRequest(Strict):
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    database: str = Field(min_length=1, max_length=120)
    user_id: int = Field(gt=0)
    company_id: int = Field(gt=0)
    features: PublicInput

    @model_validator(mode='after')
    def no_draft(self):
        if self.features.draft is not None: raise ValueError('Chỉ gửi ứng viên, không gửi bản xếp hạng tự lập.')
        return self


def validate_ranking(ranking, envelope):
    known = {c.alias: c for c in envelope.candidates}
    if len(ranking.picks) != min(3, len(known)) or len({p.alias for p in ranking.picks}) != len(ranking.picks):
        raise ValueError('Danh sách xếp hạng thiếu hoặc lặp ứng viên.')
    for pick in ranking.picks:
        item = known.get(pick.alias)
        if item is None or (pick.reason == 'lower_cost' and item.price_band != 'low') or (
            pick.reason == 'category_match' and item.category not in CATALOG[envelope.intent]['categories']):
            raise ValueError('Lý do hoặc mã không khớp ứng viên Odoo.')


def wire_guard(messages, audit=None):
    return privacy.pinned_guard(messages, PublicInput.model_validate_json, audit)


async def analyze(payload):
    trace = []
    envelope = payload.features.model_copy(deep=True)
    if os.getenv('FOLLOWUP_AI_MODE', 'cloud_minimized') == 'rules_only':
        ranking = Ranking(picks=[Pick(alias=c.alias, reason='category_match') for c in envelope.candidates[:3]])
        validate_ranking(ranking, envelope)
        return {'picks':ranking.model_dump()['picks'], 'strategy':'rules', 'trace':[], 'privacy_version':VERSION}
    if os.getenv('FOLLOWUP_AI_MODE', 'cloud_minimized') != 'cloud_minimized': raise ValueError('Chế độ AI chưa hợp lệ.')
    providers = {p.name:p for p in llm.providers()}
    if not {'groq','gemini'} <= providers.keys(): raise ValueError('Chưa cấu hình đủ hai model xếp hạng.')
    from langchain_core.messages import SystemMessage, HumanMessage
    instructions = agent_skills.read('olist-product-advice')['instructions']
    categories = {k:v['categories'] for k,v in CATALOG.items()}
    system = instructions+'\nDanh mục nhóm: '+json.dumps(categories)
    policy = transport.configured_policy()
    try:
        async with asyncio.timeout(90):
            ranking = await _model_json(providers['groq'], [SystemMessage(content=system+'\nTrả JSON: '+json.dumps(Ranking.model_json_schema())),
                HumanMessage(content=envelope.model_dump_json(exclude_none=True))], Ranking, trace, policy, guard_factory=wire_guard, privacy_version=VERSION)
            try: validate_ranking(ranking, envelope)
            except ValueError: raise AnalysisFailure(trace,'ProductRankingRejected') from None
            envelope.draft = ranking
            checked = await _model_json(providers['gemini'], [SystemMessage(content=system+'\nKiểm tra lựa chọn và lý do. Trả JSON: '+json.dumps(Verification.model_json_schema())),
                HumanMessage(content=envelope.model_dump_json())], Verification, trace, policy, guard_factory=wire_guard, privacy_version=VERSION)
            if not checked.valid: raise AnalysisFailure(trace,'ReviewRejected')
    except TimeoutError: raise AnalysisFailure(trace,'AnalysisDeadlineExceeded') from None
    return _clean({'picks':ranking.model_dump()['picks'], 'strategy':'pipeline', 'trace':trace, 'privacy_version':VERSION,
        'skills':agent_skills.catalog(['olist-product-advice'])})


@contextmanager
def connection():
    conn = database.operational()
    conn.execute('''CREATE TABLE IF NOT EXISTS product_advice_jobs (
        request_id TEXT PRIMARY KEY, database_name TEXT NOT NULL, user_id INTEGER NOT NULL, company_id INTEGER NOT NULL,
        fingerprint TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, result TEXT, created_at TEXT NOT NULL)''')
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def decode(row):
    return {'request_id':row['request_id'],'state':row['state'],**(json.loads(row['result']) if row['result'] else {})}


def claim(payload):
    serialized = payload.model_dump_json()
    fingerprint = hashlib.sha256(serialized.encode()).hexdigest()
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM product_advice_jobs WHERE request_id=?',(payload.request_id,)).fetchone()
        if row:
            if row['fingerprint'] != fingerprint: raise ValueError('Mã lượt đã dùng cho nội dung khác.')
            return decode(row), False
        conn.execute('INSERT INTO product_advice_jobs VALUES (?,?,?,?,?,?,?,?,?)',(payload.request_id,payload.database,payload.user_id,
            payload.company_id,fingerprint,serialized,'pending',None,database.now()))
    return {'request_id':payload.request_id,'state':'pending'}, True


async def run_job(request_id):
    with connection() as conn:
        if conn.execute("UPDATE product_advice_jobs SET state='running' WHERE request_id=? AND state='pending'",(request_id,)).rowcount != 1: return
        row = conn.execute('SELECT payload FROM product_advice_jobs WHERE request_id=?',(request_id,)).fetchone()
    try:
        result = await analyze(AdviceRequest.model_validate_json(row['payload']))
        state = 'complete'
    except Exception as exc:
        result = {'error':'Chưa hoàn tất xếp hạng ('+getattr(exc,'reason',type(exc).__name__)+'). Các phương án local vẫn được giữ.',
            'trace':getattr(exc,'trace',[])}
        state = 'failed'
    with connection() as conn:
        conn.execute("UPDATE product_advice_jobs SET state=?,result=?,payload='' WHERE request_id=? AND state='running'",
            (state,json.dumps(result,ensure_ascii=False),request_id))


router = APIRouter(prefix='/odoo-ai/product-advice',dependencies=[Depends(bridge_auth)])


@router.post('')
async def start(payload: AdviceRequest, tasks: BackgroundTasks):
    result, fresh = claim(payload)
    if fresh: tasks.add_task(run_job,payload.request_id)
    return result


@router.get('/{request_id}')
def poll(request_id: str, database: str, user_id: int, company_id: int):
    with connection() as conn:
        row = conn.execute('SELECT * FROM product_advice_jobs WHERE request_id=? AND database_name=? AND user_id=? AND company_id=?',
            (request_id,database,user_id,company_id)).fetchone()
        if not row: raise HTTPException(404,'Không có lượt trong phạm vi này.')
        if row['state'] in {'pending','running'} and (datetime.now(timezone.utc)-datetime.fromisoformat(row['created_at'])).total_seconds()>150:
            conn.execute("UPDATE product_advice_jobs SET state='interrupted',payload='',result=? WHERE request_id=? AND state IN ('pending','running')",
                (json.dumps({'error':'Lượt xếp hạng bị ngắt; tạo lần gợi ý mới để thử lại.'}),request_id))
            row = conn.execute('SELECT * FROM product_advice_jobs WHERE request_id=?',(request_id,)).fetchone()
        return decode(row)
