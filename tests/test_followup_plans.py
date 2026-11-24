import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage,SystemMessage

from olist import followups as f, followup_plans as p, followup_evaluation as evaluation
from olist import followup_privacy as privacy
from test_followups import payload
from test_followup_privacy import sensitive_payload


def transport(monkeypatch,*,bad=None):
    providers=[SimpleNamespace(name=n,model=n+'-fixture',base='https://'+n+'.example.invalid',key='private-api-canary') for n in ['groq','gemini']]
    monkeypatch.setattr(f.llm,'providers',lambda:providers)
    monkeypatch.setenv('FOLLOWUP_REQUEST_INTERVAL_SECONDS','0')
    monkeypatch.setenv('FOLLOWUP_MAX_ATTEMPTS','1')
    requests=[]
    def handler(request):
        body=json.loads(request.content);requests.append(body)
        wire=json.dumps(body)
        for secret in ['PERSON_PRIVATE_CANARY','SECRET_QUOTE_CANARY','837251.46','client_omega@example.invalid','SECRET_ADDRESS_CANARY','SUMMARY_PRIVATE_CANARY','private-api-canary','odoo-test']:
            assert secret not in wire
        assert 'tools' not in body
        envelope=p.Envelope.model_validate_json(body['messages'][1]['content'])
        if request.url.host.startswith('groq'):
            if bad=='http':return httpx.Response(503,json={'error':'unavailable'})
            result={'items':[{'case_id':c.case_id,'focus':c.allowed_focus[0],'activity_type':'todo'} for c in envelope.cases]}
            if bad=='id':result['items'][0]['case_id']='CASE_0000000000000000'
            if bad=='scope':result['items'][0]['focus']='receipt'
            if bad=='extra':result['items'][0]['note']='Untrusted free prose'
        else:result={'valid':bad!='review','findings':[]}
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':json.dumps(result)},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    return requests


def test_production_uses_bounded_plans_and_both_http_guards(monkeypatch):
    requests=transport(monkeypatch)
    result=asyncio.run(f.analyze(f.AnalysisRequest.model_validate(sensitive_payload())))
    assert len(requests)==2 and result['strategy']=='assisted' and result['ai_completed']
    assert result['privacy_version']==p.VERSION
    assert all(t['privacy']['requests_checked']==1 for t in result['trace'])
    assert result['items'][0]['order_id']==9
    assert result['items'][0]['action']=='review_existing_activity'
    assert 'chưa biết' in result['items'][0]['explanation']


@pytest.mark.parametrize('bad',['http','id','scope','extra','review'])
def test_bad_cloud_result_falls_back_without_claiming_ai_success(monkeypatch,bad):
    requests=transport(monkeypatch,bad=bad)
    result=asyncio.run(f.analyze(f.AnalysisRequest.model_validate(payload())))
    assert result['strategy']=='rules_fallback' and not result['ai_completed']
    assert result['fallback_reason'] and result['items']
    assert 'Mẫu quy tắc dự phòng' in result['items'][0]['explanation']
    assert len(requests)==(2 if bad=='review' else 1)


def test_every_focus_renders_only_supported_data_for_development_cases():
    _,cases=evaluation.load_cases('dev')
    for raw in cases:
        request=f.AnalysisRequest.model_validate(raw['payload'])
        projected,_=privacy.project(request,f.facts)
        case=projected[0]
        for focus in p.allowed_focus(case):
            draft=p.render(p.Plan(items=[p.Choice(case_id=case.case_id,focus=focus,activity_type='todo')]),projected)
            privacy.validate_draft(draft,projected)
            item=draft.items[0]
            assert item.action==raw['expected_action']
            assert set(item.reason_codes)==set(raw['expected_codes'])
            assert 'PERSON_' not in item.note and 'SECRET_' not in item.note


def test_call_cannot_replace_review_of_draft_or_existing_activity():
    cases,_=privacy.project(f.AnalysisRequest.model_validate(payload()),f.facts)
    with pytest.raises(ValueError):p.render(p.Plan(items=[p.Choice(case_id=cases[0].case_id,focus='content',activity_type='call')]),cases)


def test_wire_guard_rejects_changed_fields_before_sending():
    cases,_=privacy.project(f.AnalysisRequest.model_validate(payload()),f.facts)
    envelope=p.Envelope(cases=[p.PlanCase(**c.model_dump(),allowed_focus=p.allowed_focus(c)) for c in cases])
    messages=[SystemMessage(content='Fixed instructions'),HumanMessage(content=envelope.model_dump_json())]
    audit={'requests_checked':0};guard=p.wire_guard(messages,audit)
    body={'messages':[{'role':'system','content':messages[0].content},{'role':'user','content':messages[1].content}]}
    guard(body)
    body['messages'][1]['content']=json.dumps({**envelope.model_dump(),'private_note':'canary'})
    with pytest.raises(ValueError):guard(body)
    assert audit['requests_checked']==1


def test_deadline_returns_a_labeled_rules_result(monkeypatch):
    transport(monkeypatch)
    async def timeout(*a,**kw):raise TimeoutError()
    monkeypatch.setattr(f,'_model_json',timeout)
    result=asyncio.run(f.analyze(f.AnalysisRequest.model_validate(payload())))
    assert result['strategy']=='rules_fallback' and result['fallback_reason']=='TimeoutError'
    assert not result['ai_completed']
