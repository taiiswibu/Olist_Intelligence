"""Bounded provider fallback. No account/key rotation and no inferred free quotas."""
import json
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse
import httpx
from .config import settings

BASES = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "ollama": "http://127.0.0.1:11434",
}


@dataclass
class Provider:
    name: str
    base: str
    model: str
    key: str


def providers():
    cfg = settings()
    result = []
    for name in cfg.llm_providers.lower().split(","):
        name = name.strip()
        if not name:
            continue
        prefix = name.upper()
        base = os.getenv(prefix + "_BASE_URL", BASES.get(name, "")).rstrip("/")
        model = os.getenv(prefix + "_MODEL", "")
        key = os.getenv(prefix + "_API_KEY", "")
        if not base or not model or (name != "ollama" and not key):
            continue
        parsed = urlparse(base)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
            continue
        result.append(Provider(name, base, model, key))
    return result[:6]


def provider_status():
    return [{"provider": p.name, "model": p.model, "configured": True} for p in providers()]


def complete(messages, max_tokens=500):
    failures = []
    # One request per provider, bounded total elapsed time for responsive local UX.
    import time
    deadline = time.monotonic() + 45
    for p in providers():
        remaining = deadline - time.monotonic()
        if remaining < 1:
            break
        try:
            timeout = httpx.Timeout(min(18, remaining), connect=min(5, remaining))
            with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=p.name != "ollama") as client:
                if p.name == "ollama":
                    r = client.post(p.base + "/api/chat", json={"model": p.model, "messages": messages,
                        "stream": False, "think": False, "options": {"temperature": 0, "num_predict": max_tokens, "num_ctx": 4096}})
                    r.raise_for_status()
                    content = r.json()["message"]["content"]
                else:
                    payload = {"model": p.model, "messages": messages, "max_tokens": max_tokens, "temperature": 0, "stream": False}
                    r = client.post(p.base + "/chat/completions", headers={"Authorization": "Bearer " + p.key}, json=payload)
                    r.raise_for_status()
                    content = r.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("Empty response")
                return {"content": content, "provider": p.name, "model": p.model, "failures": failures}
        except httpx.HTTPStatusError as exc:
            # Never expose response bodies or URLs, which can contain sensitive content.
            failures.append({"provider": p.name, "error": f"HTTP {exc.response.status_code}"})
        except Exception as exc:
            failures.append({"provider": p.name, "error": type(exc).__name__})
    return {"content": None, "provider": None, "model": None, "failures": failures}


def json_object(value):
    text = re.sub(r"<think>.*?</think>", "", value, flags=re.S).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("Object required")
    return parsed
