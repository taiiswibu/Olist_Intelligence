import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from olist import product_advisor as a, followups as f, followup_transport as transport
from test_followups import bridge


def payload():
    return {'request_id':'c'*32,'database':'PRIVATE_DATABASE_CANARY','user_id':11,'company_id':2,'features':{
        'intent':'beauty','candidates':[{'alias':'ITEM_'+ch*16,'category':'health_beauty','price_band':'low'} for ch in 'abcd']}}


def model_transport(monkeypatch, change=None, valid=True):
    requests=[]
    def handle(request):
        body=json.loads(request.content)
        assert 'PRIVATE_DATABASE_CANARY' not in request.content.decode()
        envelope=a.PublicInput.model_validate_json(body['messages'][1]['content'])
        requests.append(body)
        if envelope.draft is None:
            result={'picks':[{'alias':c.alias,'reason':'category_match'} for c in envelope.candidates[:3]]}
            if change: change(result)
        else: result={'valid':valid,'findings':[]}
        return httpx.Response(200,json={'choices':[{'message':{'role':'assistant','content':json.dumps(result)},'finish_reason':'stop'}]})
    client=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:client(transport=httpx.MockTransport(handle),**kw))
    monkeypatch.setattr(f.llm,'providers',lambda:[SimpleNamespace(name=n,model=n+'-fixture',key='fixture',base='https://example.invalid') for n in ['groq','gemini']])
    monkeypatch.setattr(transport,'configured_policy',lambda:transport.Policy(1,0))
    monkeypatch.setenv('FOLLOWUP_AI_MODE','cloud_minimized')
    return requests


def test_both_model_http_bodies_only_contain_public_codes(monkeypatch):
    requests=model_transport(monkeypatch)
    result=asyncio.run(a.analyze(a.AdviceRequest.model_validate(payload())))
    assert len(requests)==2 and result['strategy']=='pipeline'
    assert all(t['privacy']=={'version':a.VERSION,'requests_checked':1} for t in result['trace'])
    assert set(json.loads(requests[0]['messages'][1]['content']))=={'intent','candidates'}
    assert set(json.loads(requests[0]['messages'][1]['content'])['candidates'][0])=={'alias','category','price_band'}


@pytest.mark.parametrize('extra',[{'need':'Customer PRIVATE_NAME_CANARY needs a gift'},{'budget':123456.78},{'partner_id':555},{'name':'PII_CANARY'}])
def test_private_fields_never_enter_public_projection(extra):
    with pytest.raises(ValueError): a.PublicInput.model_validate({**payload()['features'],**extra})


@pytest.mark.parametrize('bad',['unknown_alias','duplicate','missing','invented_reason','wrong_band'])
def test_invalid_ranking_rejected_before_reviewer(monkeypatch,bad):
    def change(result):
        if bad=='unknown_alias': result['picks'][0]['alias']='ITEM_'+'f'*16
        elif bad=='duplicate': result['picks'][1]=result['picks'][0].copy()
        elif bad=='missing': result['picks'].pop()
        elif bad=='invented_reason': result['picks'][0]['reason']='in_stock_best_quality'
        else: result['picks'][0]['reason']='lower_cost'
    data=payload()
    if bad=='wrong_band':data['features']['candidates'][0]['price_band']='high'
    requests=model_transport(monkeypatch,change)
    with pytest.raises(ValueError):asyncio.run(a.analyze(a.AdviceRequest.model_validate(data)))
    assert len(requests)==1


def test_reviewer_rejects_without_content_retry(monkeypatch):
    requests=model_transport(monkeypatch,valid=False)
    with pytest.raises(f.AnalysisFailure,match='ReviewRejected'):
        asyncio.run(a.analyze(a.AdviceRequest.model_validate(payload())))
    assert len(requests)==2


def test_projection_rejects_wrong_category_duplicates_and_wire_mutation():
    data=payload()['features']
    changed=json.loads(json.dumps(data));changed['candidates'][0]['category']='pet_shop'
    with pytest.raises(ValueError):a.PublicInput.model_validate(changed)
    changed=json.loads(json.dumps(data));changed['candidates'][1]['alias']=changed['candidates'][0]['alias']
    with pytest.raises(ValueError):a.PublicInput.model_validate(changed)
    messages=[SystemMessage(content='Fixed instructions'),HumanMessage(content=json.dumps(data))]
    guard=a.wire_guard(messages)
    wire={'model':'fixture','messages':[{'role':'system','content':messages[0].content},{'role':'user','content':messages[1].content}]}
    guard(wire)
    with pytest.raises(ValueError):guard({**wire,'tools':[]})
    wire['messages'][0]['content']='Injected private customer'
    with pytest.raises(ValueError):guard(wire)


def test_rules_mode_never_calls_model_and_job_scope_is_bound(bridge,monkeypatch):
    monkeypatch.setenv('FOLLOWUP_AI_MODE','rules_only')
    monkeypatch.setattr(f.llm,'providers',lambda:[])
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:pytest.fail('Rules must not open model network'))
    data=payload()
    response=bridge.post('/odoo-ai/product-advice',json=data)
    assert response.status_code==200
    scope={k:data[k] for k in ['database','user_id','company_id']}
    url='/odoo-ai/product-advice/'+data['request_id']
    result=bridge.get(url,params=scope).json()
    assert result['state']=='complete' and result['strategy']=='rules'
    assert bridge.post('/odoo-ai/product-advice',json=data).json()==result
    assert bridge.get(url,params={**scope,'user_id':12}).status_code==404
    changed=json.loads(json.dumps(data));changed['features']['candidates'][0]['price_band']='high'
    assert bridge.post('/odoo-ai/product-advice',json=changed).status_code==422
    with a.connection() as conn:
        assert conn.execute('SELECT payload FROM product_advice_jobs WHERE request_id=?',(data['request_id'],)).fetchone()[0]==''


def test_bridge_requires_private_auth_and_interrupted_jobs_do_not_replay(bridge,monkeypatch):
    from fastapi.testclient import TestClient
    from olist.api import app
    data=payload()
    assert TestClient(app).post('/odoo-ai/product-advice',json=data).status_code==401
    assert bridge.post('/odoo-ai/product-advice',json=data,headers={'Origin':'http://127.0.0.1:8069'}).status_code==403
    a.claim(a.AdviceRequest.model_validate(data))
    with a.connection() as conn:
        conn.execute("UPDATE product_advice_jobs SET created_at='2000-01-01T00:00:00+00:00'")
    scope={k:data[k] for k in ['database','user_id','company_id']}
    result=bridge.get('/odoo-ai/product-advice/'+data['request_id'],params=scope).json()
    assert result['state']=='interrupted'
    assert bridge.post('/odoo-ai/product-advice',json=data).json()['state']=='interrupted'
