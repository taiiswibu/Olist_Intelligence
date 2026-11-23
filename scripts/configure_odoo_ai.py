"""Create the server-to-server bridge key locally without displaying any credential."""
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from olist.config import ROOT, init_env
from dotenv import dotenv_values


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    init_env()
    path = ROOT / ".env"
    existing = dotenv_values(path).get("ODOO_AI_BRIDGE_TOKEN", "") or ""
    if len(existing) >= 32:
        print("Kết nối Odoo AI đã có khóa riêng; giữ nguyên khóa hiện tại.")
        return
    content = path.read_text(encoding="utf-8")
    line = "ODOO_AI_BRIDGE_TOKEN=" + secrets.token_urlsafe(48)
    if re.search(r"^ODOO_AI_BRIDGE_TOKEN=.*$", content, re.M):
        content = re.sub(r"^ODOO_AI_BRIDGE_TOKEN=.*$", line, content, flags=re.M)
    else:
        content = content.rstrip() + "\n\n" + line + "\n"
    path.write_text(content, encoding="utf-8")
    print("Đã lưu khóa kết nối riêng trong .env. Khởi động lại backend và container Odoo để áp dụng.")


if __name__ == "__main__":
    main()
