"""Small reproducible lexical retrieval baseline; optional local dense embeddings."""
import hashlib
import json
import os
import re
import unicodedata
from functools import lru_cache
import httpx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from .config import ROOT, settings


def normalize(s):
    s = s.lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def documents():
    chunks = []
    for path in sorted((ROOT / "docs/knowledge").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for n, part in enumerate(re.split(r"(?m)(?=^## )", text)):
            if len(part.strip()) < 50:
                continue
            # A deterministic chunk identifier tied to source content.
            key = hashlib.sha256((path.name + part).encode()).hexdigest()[:12]
            chunks.append({"id": key, "source": path.name, "section": part.splitlines()[0].lstrip("# "), "text": part.strip()[:4000]})
    return chunks


@lru_cache(maxsize=4)
def lexical_index(fingerprint):
    chunks = documents()
    v = TfidfVectorizer(preprocessor=normalize, analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    matrix = v.fit_transform([d["text"] for d in chunks])
    return chunks, v, matrix


def fingerprint():
    return tuple((p.name, p.stat().st_mtime_ns) for p in sorted((ROOT / "docs/knowledge").glob("*.md")))


def embed(texts):
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    if not base.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("Embedding endpoint must be local")
    r = httpx.post(base + "/api/embed", json={"model": os.getenv("EMBED_MODEL", ""), "input": texts}, timeout=60, trust_env=False)
    r.raise_for_status()
    a = np.array(r.json()["embeddings"], dtype=np.float32)
    return a / np.maximum(np.linalg.norm(a, axis=1, keepdims=True), 1e-9)


def build_embeddings():
    settings()
    if not os.getenv("EMBED_MODEL"):
        raise ValueError("Set EMBED_MODEL and pull that model in Ollama first")
    chunks = documents()
    vectors = np.vstack([embed([d["text"] for d in chunks[k:k+8]]) for k in range(0, len(chunks), 8)])
    out = ROOT / "data/processed"
    np.save(out / "rag_vectors.npy", vectors)
    (out / "rag_vectors.json").write_text(json.dumps({"model": os.getenv("EMBED_MODEL"), "ids": [d["id"] for d in chunks]}))
    return {"chunks": len(chunks), "dimensions": vectors.shape[1]}


def retrieve(query, k=3):
    settings()
    chunks, v, matrix = lexical_index(fingerprint())
    scores = (matrix @ v.transform([query]).T).toarray().ravel()
    method = "lexical_tfidf"
    meta = ROOT / "data/processed/rag_vectors.json"
    if os.getenv("RAG_MODE", "lexical") == "hybrid" and meta.exists():
        try:
            m = json.loads(meta.read_text())
            if m["ids"] == [d["id"] for d in chunks] and m["model"] == os.getenv("EMBED_MODEL"):
                dense = np.load(meta.with_suffix(".npy")) @ embed([query])[0]
                scores = .45 * scores + .55 * np.maximum(dense, 0)
                method = "hybrid_ollama"
        except (httpx.HTTPError, ValueError, KeyError, OSError):
            method = "lexical_fallback"
    ix = np.argsort(-scores)[:k]
    return {"method": method, "sources": [{**chunks[n], "score": round(float(scores[n]), 4)} for n in ix if scores[n] >= .06]}
