import os
import signal
import subprocess
import sys
import time
import httpx
from olist.config import ROOT, init_env, settings


def main():
    os.chdir(ROOT)
    init_env()
    cfg = settings()
    if not cfg.app_token or cfg.app_token == "CHANGE_ME_LOCAL_TOKEN":
        raise SystemExit("APP_TOKEN missing/placeholder. Remove that line from .env and regenerate a random token.")
    from olist.database import ready
    if not ready():
        raise SystemExit("Chưa có dữ liệu. Chạy python manage.py setup trước.")
    children = []
    try:
        with httpx.Client(timeout=1, trust_env=False) as client:
            try:
                client.get("http://127.0.0.1:8000/health")
            except httpx.HTTPError:
                pass
            else:
                raise SystemExit("Port 8000 đang được dùng. Dừng bản API cũ trước khi chạy lại.")
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "olist.api:app", "--host", "127.0.0.1", "--port", "8000"])
        children.append(api)
        for _ in range(60):
            if api.poll() is not None:
                raise RuntimeError("API failed to start")
            try:
                if httpx.get("http://127.0.0.1:8000/health", timeout=1, trust_env=False).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(.25)
        else:
            raise RuntimeError("Timed out starting API")
        print("Olist Intelligence: http://127.0.0.1:8501\nCtrl+C to stop", flush=True)
        ui = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.address", "127.0.0.1", "--server.port", "8501", "--browser.gatherUsageStats", "false"])
        children.append(ui)
        while ui.poll() is None and api.poll() is None:
            time.sleep(.5)
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    main()
