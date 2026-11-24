"""Local-only embeddings and an atomically replaced SQLite vector index."""
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import numpy as np
import sqlite_vec

VERSION = 'rag-sqlite-vec-v1'


def local_url():
    value = os.getenv('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')
    parsed = urlsplit(value)
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError('Cổng Ollama không hợp lệ.')
    if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path):
        raise ValueError('Ollama phải là địa chỉ HTTP loopback, không có đường dẫn hoặc thông tin đăng nhập.')
    return value


def model_identity(model):
    response = httpx.get(local_url()+'/api/tags', timeout=5, trust_env=False, follow_redirects=False)
    response.raise_for_status()
    name = model if ':' in model else model+':latest'
    for item in response.json()['models']:
        if item.get('name') == name or item.get('model') == name:
            return {'model': model, 'digest': item['digest']}
    raise ValueError('Chưa tải model embedding trong Ollama.')


def embed(texts, model, *, query=False):
    if not model or not texts:
        raise ValueError('Cần model embedding và nội dung.')
    if model.split(':')[0] == 'embeddinggemma':
        texts = [('task: search result | query: '+text) if query else ('title: Olist Intelligence | text: '+text) for text in texts]
    response = httpx.post(local_url()+'/api/embed', json={'model': model, 'input': texts, 'truncate': False, 'keep_alive': '5m'},
                          timeout=60 if query else 120, trust_env=False, follow_redirects=False)
    response.raise_for_status()
    vectors = np.asarray(response.json()['embeddings'], dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] != len(texts) or not 1 <= vectors.shape[1] <= 4096 or not np.isfinite(vectors).all():
        raise ValueError('Embedding trả sai số dòng, số chiều hoặc giá trị.')
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if (norms <= 0).any():
        raise ValueError('Embedding không được là vector rỗng.')
    return vectors / norms


@contextmanager
def connection(path, *, readonly=True):
    conn = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True) if readonly else sqlite3.connect(path)
    try:
        conn.enable_load_extension(True)
        try:
            sqlite_vec.load(conn)
        finally:
            conn.enable_load_extension(False)
        yield conn
    finally:
        conn.close()


def corpus_hash(chunks):
    return hashlib.sha256(json.dumps(chunks, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def build(path, chunks, model):
    if not chunks:
        raise ValueError('Kho tri thức chưa có tài liệu; giữ nguyên index cũ.')
    identity = model_identity(model)
    vectors = np.vstack([embed([d['section']+'\n'+d['text'] for d in chunks[n:n+8]], model) for n in range(0, len(chunks), 8)])
    if model_identity(model) != identity:
        raise ValueError('Model đã đổi trong lúc lập index; giữ index cũ.')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='rag-', suffix='.sqlite', dir=path.parent)
    os.close(handle)
    try:
        with connection(temporary, readonly=False) as conn:
            dimensions = vectors.shape[1]
            conn.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            conn.execute('CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, chunk_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL)')
            conn.execute(f'CREATE VIRTUAL TABLE vectors USING vec0(embedding float[{dimensions}] distance_metric=cosine)')
            manifest = {'version': VERSION, **identity, 'corpus_hash': corpus_hash(chunks), 'chunks': len(chunks), 'dimensions': dimensions}
            conn.execute('INSERT INTO metadata VALUES (?,?)', ('manifest', json.dumps(manifest)))
            for rowid, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True), 1):
                conn.execute('INSERT INTO chunks VALUES (?,?,?)', (rowid, chunk['id'], json.dumps(chunk, ensure_ascii=False)))
                conn.execute('INSERT INTO vectors(rowid,embedding) VALUES (?,?)', (rowid, vector.tobytes()))
            conn.commit()
        os.replace(temporary, path)
        return manifest
    finally:
        Path(temporary).unlink(missing_ok=True)


def manifest(path):
    with connection(path) as conn:
        return json.loads(conn.execute("SELECT value FROM metadata WHERE key='manifest'").fetchone()[0])


def search(path, vector, k):
    with connection(path) as conn:
        rows = conn.execute('SELECT rowid,distance FROM vectors WHERE embedding MATCH ? AND k=? ORDER BY distance',
                            (np.asarray(vector, dtype=np.float32).tobytes(), k)).fetchall()
        return [(json.loads(conn.execute('SELECT payload FROM chunks WHERE rowid=?', (rowid,)).fetchone()[0]), max(0., 1.-distance)) for rowid, distance in rows]
