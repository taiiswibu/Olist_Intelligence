import time
from fastapi.testclient import TestClient
from olist.api import app, session_signature


def test_html_assets_do_not_expose_runtime_key(db):
    c=TestClient(app)
    html=c.get('/')
    assert html.status_code==200 and 'text/html' in html.headers['content-type']
    assert 'frontend' not in html.text and 'local-test-token' not in html.text
    assert c.get('/assets/app.js').status_code==200
    assert c.get('/.env').status_code==404
    assert c.get('/status').status_code==401


def test_key_exchange_creates_private_cookie(db):
    c=TestClient(app)
    r=c.post('/session',json={'key':'local-test-token'})
    assert r.status_code==200
    assert 'local-test-token' not in r.text
    cookie=r.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie
    assert c.get('/status').status_code==200


def test_cookie_writes_require_same_origin_custom_header(db):
    c=TestClient(app)
    c.post('/session',json={'key':'local-test-token'})
    payload={'question':'Tổng quan KPI năm 2018'}
    assert c.post('/agent/chat',json=payload).status_code==403
    assert c.post('/agent/chat',json=payload,headers={'X-Olist-Request':'1'}).status_code==200
    assert c.post('/agent/chat',json=payload,headers={'X-Olist-Request':'1','Origin':'https://unrelated.example'}).status_code==403


def test_session_exchange_rejects_cross_origin_and_wrong_key(db):
    c=TestClient(app)
    assert c.post('/session',json={'key':'wrong'}).status_code==401
    assert c.post('/session',json={'key':'local-test-token'},headers={'Origin':'https://unrelated.example'}).status_code==403


def test_expired_or_tampered_cookie_is_rejected(db):
    c=TestClient(app)
    expiry=str(int(time.time())-10)
    c.cookies.set('olist_session',expiry+'.'+session_signature(expiry))
    assert c.get('/status').status_code==401
    expiry=str(int(time.time())+3600)
    c.cookies.set('olist_session',expiry+'.'+'0'*64)
    assert c.get('/status').status_code==401


def test_browser_ticket_is_one_use(db,monkeypatch):
    monkeypatch.setenv('OLIST_BROWSER_TICKET','one-use-test-ticket')
    monkeypatch.setattr(app.state,'ticket_used',False,raising=False)
    first=TestClient(app)
    assert first.post('/session',json={'ticket':'one-use-test-ticket'}).status_code==200
    assert first.get('/status').status_code==200
    assert TestClient(app).post('/session',json={'ticket':'one-use-test-ticket'}).status_code==401


def test_logout_removes_browser_session(db):
    c=TestClient(app)
    c.post('/session',json={'key':'local-test-token'})
    assert c.delete('/session').status_code==200
    assert c.get('/status').status_code==401
