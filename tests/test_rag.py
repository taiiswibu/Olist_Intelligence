import json
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from olist import rag, rag_store as store
from olist.api import app


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    folder=tmp_path/'docs/knowledge'
    folder.mkdir(parents=True)
    (folder/'policy.md').write_text('## Đổi trả hàng\nSản phẩm được đổi trả trong bảy ngày nếu còn nguyên tem và hóa đơn. Liên hệ bộ phận bán hàng để đối chiếu điều kiện.',encoding='utf-8')
    monkeypatch.setattr(rag,'ROOT',tmp_path)
    monkeypatch.setenv('EMBED_MODEL','fixture')
    monkeypatch.setenv('RAG_MODE','hybrid')
    monkeypatch.setattr(store,'model_identity',lambda model:{'model':model,'digest':'fixture-digest'})
    monkeypatch.setattr(store,'embed',lambda texts,model,**kw:np.asarray([[1.,0.,0.]]*len(texts),dtype=np.float32))
    rag.lexical_index.cache_clear()
    return folder


def test_real_vector_database_and_stale_content(corpus):
    manifest=rag.build_embeddings()
    assert manifest['dimensions']==3
    result=rag.retrieve('Điều kiện đổi trả hàng')
    assert result['method']=='hybrid_sqlite_vec' and result['answerable']
    assert result['sources'][0]['semantic_score']==1
    (corpus/'policy.md').write_text('## Chính sách mới\n'+'Điều kiện giao hàng được thay đổi. '*10,encoding='utf-8')
    result=rag.retrieve('Điều kiện đổi trả hàng')
    assert result['method']=='lexical_fallback' and 'warning' in result
    assert not rag.status()['ready']


def test_failed_rebuild_keeps_previous_index(corpus, monkeypatch):
    rag.build_embeddings()
    before=rag.index_path().read_bytes()
    monkeypatch.setattr(store,'embed',lambda *a,**kw: (_ for _ in ()).throw(ValueError('failure')))
    with pytest.raises(ValueError):rag.build_embeddings()
    assert rag.index_path().read_bytes()==before


def test_changed_model_and_missing_service_are_visible(corpus,monkeypatch):
    rag.build_embeddings()
    monkeypatch.setattr(store,'model_identity',lambda model:{'model':model,'digest':'changed'})
    assert not rag.status()['ready']
    assert rag.retrieve('Điều kiện đổi trả')['method']=='lexical_fallback'
    monkeypatch.setattr(store,'model_identity',lambda model: (_ for _ in ()).throw(httpx.ConnectError('offline')))
    assert not rag.status()['ready']
    assert rag.retrieve('Điều kiện đổi trả')['method']=='lexical_fallback'


def test_verbatim_answer_has_resolvable_citation(corpus,monkeypatch):
    rag.build_embeddings()
    monkeypatch.setenv('RAG_ANSWER_MODEL','local-fixture')
    source=rag.documents()[0]
    data={'quotes':[{'source_id':source['id'],'quote':source['text']}]}
    monkeypatch.setattr(httpx,'post',lambda *a,**kw:SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'message':{'content':json.dumps(data)}}))
    result=rag.answer('Điều kiện đổi trả hàng')
    assert result['generation']=='local_extractive' and result['answerable']
    assert result['citations']==data['quotes'] and source['id'] in result['answer']


@pytest.mark.parametrize('url',['http://127.0.0.1:11434.evil.test','http://localhost@evil.test:11434','http://localhost:11434/path','https://example.com','http://127.0.0.1:11434?target=cloud'])
def test_embedding_never_uses_nonlocal_endpoints(monkeypatch,url):
    monkeypatch.setenv('OLLAMA_BASE_URL',url)
    with pytest.raises(ValueError):store.local_url()


@pytest.mark.parametrize('vectors',[[[0,0]],[[float('nan'),1]],[[1,2],[3,4]],[1,2],[]])
def test_invalid_embeddings_are_rejected(monkeypatch,vectors):
    monkeypatch.setattr(httpx,'post',lambda *a,**kw:SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'embeddings':vectors}))
    with pytest.raises(ValueError):store.embed(['test'],'fixture')


def test_long_documents_not_silently_truncated(corpus):
    (corpus/'long.md').write_text('## Long\n'+'Nội dung dài. '*700+'KẾT THÚC',encoding='utf-8')
    assert any('KẾT THÚC' in d['text'] for d in rag.documents())
    assert max(len(d['text']) for d in rag.documents())<=1300


@pytest.mark.parametrize('bad',['invented','wrong_source','extra','empty'])
def test_only_verbatim_citations_reach_answer(corpus,monkeypatch,bad):
    rag.build_embeddings()
    monkeypatch.setenv('RAG_ANSWER_MODEL','local-fixture')
    source=rag.documents()[0]
    quotes=[{'source_id':source['id'],'quote':source['text']}]
    if bad=='invented':quotes[0]['quote']='Bạn được hoàn tiền vô điều kiện trong một năm.'
    if bad=='wrong_source':quotes[0]['source_id']='unknown'
    if bad=='empty':quotes=[]
    data={'quotes':quotes}
    if bad=='extra':data['answer']='fabricated'
    def post(url,**kw):
        assert url.startswith('http://127.0.0.1:11434/')
        assert kw['trust_env'] is False and kw['follow_redirects'] is False
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'message':{'content':json.dumps(data)}})
    monkeypatch.setattr(httpx,'post',post)
    result=rag.answer('Điều kiện đổi trả hàng')
    assert result['answer']==rag.REFUSAL if bad=='empty' else result['generation']=='source_excerpts'
    assert not result['citations']


def test_refusal_does_not_call_generation(corpus,monkeypatch):
    monkeypatch.setenv('RAG_MODE','lexical')
    monkeypatch.setattr(httpx,'post',lambda *a,**kw:pytest.fail('No generation on insufficient evidence'))
    assert rag.answer('xyzzy quantum zebra')['answer']==rag.REFUSAL


def test_rag_api_requires_authentication():
    client=TestClient(app)
    assert client.get('/rag/status').status_code==401
    assert client.post('/rag/answer',json={'question':'test'}).status_code==401
