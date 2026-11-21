"""Start the HTML application on one local port with a one-use browser ticket."""
import os
import secrets
import sys
import threading
import time
import webbrowser
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    try:
        import uvicorn
        from olist.config import init_env, settings
        from olist.database import ready
    except ImportError as exc:
        print(f"Thiếu thư viện: {exc.name}. Bước cài đặt chưa hoàn tất.")
        print(r"Chạy SETUP_WINDOWS.bat hoặc .\.venv\Scripts\python.exe -m pip install --timeout 180 --retries 10 -r requirements.txt")
        raise SystemExit(1)
    init_env()
    if not settings().app_token or settings().app_token == "CHANGE_ME_LOCAL_TOKEN":
        raise SystemExit("APP_TOKEN chưa hợp lệ. Chạy lại python manage.py setup")
    import socket
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", 8000))
        except OSError:
            raise SystemExit("Port 8000 đang được dùng. Dừng bản ứng dụng cũ rồi chạy lại.")
    ticket = secrets.token_urlsafe(32)
    os.environ["OLIST_BROWSER_TICKET"] = ticket
    url = "http://127.0.0.1:8000/"
    def open_browser():
        import urllib.request
        for _ in range(60):
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(url + "health", timeout=1) as r:
                    if r.status == 200:
                        webbrowser.open(url + "#ticket=" + ticket)
                        return
            except Exception:
                time.sleep(.25)
    if os.getenv("OLIST_NO_BROWSER") != "1":
        threading.Thread(target=open_browser, daemon=True).start()
    print("Olist Intelligence · HTML/CSS web app", flush=True)
    print(url + "  |  Ctrl+C để dừng", flush=True)
    print("Nếu mở thủ công: dùng APP_TOKEN trong .env ở màn hình kết nối.", flush=True)
    if not ready():
        print("Chưa có dữ liệu: chạy python manage.py setup để tải Olist.", flush=True)
    uvicorn.run("olist.api:app", host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
