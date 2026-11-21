import os
import httpx
from olist.config import settings
from olist.llm import BASES


def list_models(name):
    settings()
    prefix = name.upper()
    base = os.getenv(prefix + "_BASE_URL", BASES.get(name, "")).rstrip("/")
    if not base:
        raise ValueError("Cần cấu hình BASE_URL; với AMD dùng endpoint do dịch vụ của bạn cung cấp")
    key = os.getenv(prefix + "_API_KEY", "")
    headers = {"Authorization": "Bearer " + key} if key else {}
    r = httpx.get(base + ("/api/tags" if name == "ollama" else "/models"), headers=headers, timeout=30)
    if r.status_code >= 400:
        raise ValueError(f"Provider returned HTTP {r.status_code}; check key and endpoint")
    data = r.json()
    records = data.get("models", []) if name == "ollama" else data.get("data", [])
    return [{"id": x.get("id", x.get("name")), "pricing": x.get("pricing")} for x in records]
