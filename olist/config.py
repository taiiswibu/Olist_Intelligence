from dataclasses import dataclass
from pathlib import Path
import os
import secrets
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


def init_env():
    path = ROOT / ".env"
    if not path.exists():
        template = (ROOT / ".env.example").read_text(encoding="utf-8")
        path.write_text(template.replace("CHANGE_ME_LOCAL_TOKEN", secrets.token_urlsafe(32)), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    else:
        content = path.read_text(encoding="utf-8")
        if "APP_TOKEN=CHANGE_ME_LOCAL_TOKEN" in content:
            path.write_text(content.replace("APP_TOKEN=CHANGE_ME_LOCAL_TOKEN", "APP_TOKEN=" + secrets.token_urlsafe(32)), encoding="utf-8")


@dataclass
class Settings:
    database_url: str
    app_token: str
    api_url: str
    llm_providers: str
    odoo_url: str
    odoo_db: str
    odoo_login: str
    odoo_password: str


def settings():
    load_dotenv(ROOT / ".env", override=False)
    return Settings(
        os.getenv("DATABASE_URL") or f"sqlite:///{(ROOT / 'data/processed/olist.db').as_posix()}",
        os.getenv("APP_TOKEN", ""), os.getenv("API_URL", "http://127.0.0.1:8000"),
        os.getenv("LLM_PROVIDERS", ""), os.getenv("ODOO_URL", "http://127.0.0.1:8069"),
        os.getenv("ODOO_DB", "olist_demo"), os.getenv("ODOO_LOGIN", "admin"),
        os.getenv("ODOO_PASSWORD", ""),
    )
